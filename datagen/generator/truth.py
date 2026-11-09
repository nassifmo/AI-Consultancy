"""Ground truth outputs: per-enquiry true outcomes and the planted effects a correct evaluator
should recover. Written before any defect is injected; never given to the evaluator."""

from __future__ import annotations

from collections import defaultdict
from math import sqrt
from statistics import mean, pstdev

from datagen.config_schema import GeneratorConfig, ServiceRules

from .handling import HUMAN_BASELINE, Handled, Truth
from .model import World


def _iso(dt):
    return dt.isoformat() if dt else None


def true_outcome_rows(world: World, h: Handled) -> list[dict]:
    from .state import known_state_at

    rows = []
    for t in h.truths:
        q, fa, final = t.enquiry, t.first_answer, t.final_answer
        k = known_state_at(world.events_for(q.true_booking_ref), final.sent_at) if final and t.in_scope else None
        rows.append(
            {
                "enquiry_id": q.enquiry_id,
                "in_population": t.in_population,
                "repeat_of": q.repeat_of.enquiry_id if q.repeat_of else None,
                "true_booking_ref": q.true_booking_ref,
                "arm": t.arm,
                "scenario_id": t.scenario_id,
                "true_outcome": t.true_outcome,
                "true_status_at_handling": k.status if k else None,
                "true_eta_at_handling": _iso(k.eta) if k else None,
                "linked_correct_shipment": (fa.linked is not None and fa.linked.booking_ref == q.true_booking_ref)
                if fa and t.in_scope else None,
                "first_answer_correct": fa.correct if fa and t.in_scope else None,
                "info_correct": final.correct if final and t.in_scope else None,
                "escalation_required": t.escalation_required,
                "required_actions_done": t.required_actions_done,
                "ai_only": t.true_outcome == "resolved" and t.arm != HUMAN_BASELINE and t.human_seconds == 0,
                "was_rescued": t.rescued,
                "handed_off": t.handed_off,
                "self_report_false": t.self_reported == "resolved" and t.true_outcome != "resolved",
                "repeat_contact": t.repeat_contact,
                "true_human_seconds": t.human_seconds,
                "true_ai_cost": round(t.ai_cost, 6),
                "expected_evaluator_state": t.true_outcome,  # step 4 changes this where evidence is damaged
            }
        )
    return rows


RATE_METRICS = [
    "verified_resolution_rate", "escalated_open_rate", "failed_rate", "ai_only_rate", "first_answer_correct_rate",
    "handoff_rate", "rescue_rate", "repeat_contact_rate", "false_self_report_rate",
]
MEAN_METRICS = {"human_minutes_per_enquiry": "human_minutes_sd", "variable_cost_per_enquiry": "variable_cost_sd"}
Z_80_POWER = 2.80  # 1.96 (two-sided 5%) + 0.84 (80% power)


def _sd(xs: list[float]) -> float:
    return pstdev(xs) if len(xs) > 1 else 0.0


def _arm_metrics(ts: list[Truth], labor_rate: float) -> dict:
    n = len(ts)
    if n == 0:
        return {"n": 0}
    rate = lambda pred: round(sum(pred(t) for t in ts) / n, 4)
    human_min = [t.human_seconds / 60 for t in ts]
    human_cost = [m / 60 * labor_rate for m in human_min]
    ai_cost = [t.ai_cost for t in ts]
    var_cost = [h + a for h, a in zip(human_cost, ai_cost)]
    resolved = sum(t.true_outcome == "resolved" for t in ts)
    return {
        "n": n,
        "verified_resolution_rate": rate(lambda t: t.true_outcome == "resolved"),
        "escalated_open_rate": rate(lambda t: t.true_outcome == "escalated_open"),
        "failed_rate": rate(lambda t: t.true_outcome == "failed"),
        "ai_only_rate": rate(lambda t: t.true_outcome == "resolved" and t.arm != HUMAN_BASELINE and t.human_seconds == 0),
        "first_answer_correct_rate": rate(lambda t: bool(t.first_answer and t.first_answer.correct)),
        "handoff_rate": rate(lambda t: t.handed_off),
        "rescue_rate": rate(lambda t: t.rescued),
        "repeat_contact_rate": rate(lambda t: t.repeat_contact),
        "false_self_report_rate": rate(lambda t: t.self_reported == "resolved" and t.true_outcome != "resolved"),
        "human_minutes_per_enquiry": round(mean(human_min), 3),
        "human_minutes_sd": round(_sd(human_min), 3),
        "human_cost_per_enquiry": round(mean(human_cost), 4),
        "ai_variable_cost_per_enquiry": round(mean(ai_cost), 5),
        "variable_cost_per_enquiry": round(mean(var_cost), 4),
        "variable_cost_sd": round(_sd(var_cost), 4),
        "variable_cost_per_verified_resolution": round(sum(var_cost) / resolved, 4) if resolved else None,
    }


def compare(a: dict, b: dict) -> dict:
    """b minus a for every metric, with standard error and the minimum detectable effect
    (80% power, 5% two-sided) for rates and means. A difference smaller than mde_80 cannot be
    expected to be detected reliably at this sample size."""
    if not a.get("n") or not b.get("n"):
        return {}
    out = {}
    for k, v in b.items():
        if k == "n" or k.endswith("_sd") or not isinstance(v, float) or not isinstance(a.get(k), float):
            continue
        entry = {"diff": round(v - a[k], 5)}
        if k in RATE_METRICS:
            se = sqrt(a[k] * (1 - a[k]) / a["n"] + v * (1 - v) / b["n"])
        elif k in MEAN_METRICS:
            sd = MEAN_METRICS[k]
            se = sqrt(a[sd] ** 2 / a["n"] + b[sd] ** 2 / b["n"])
        else:
            se = None
        if se is not None:
            entry.update(se=round(se, 5), mde_80=round(Z_80_POWER * se, 5),
                         detectable=abs(entry["diff"]) >= Z_80_POWER * se)
        out[k] = entry
    return out


def _population(h_truths: list[Truth], post_from=None) -> list[Truth]:
    pop = [t for t in h_truths if t.in_population and t.in_scope]
    if post_from is not None:
        pop = [t for t in pop if t.enquiry.received_at >= post_from]
    return pop


def counterfactual_metrics(cfg: GeneratorConfig, runs: dict[str, list[Truth]], world: World) -> dict:
    """Every arm applied to the same world and enquiry stream: true causal effects (vs the first arm),
    for the whole population and, for rollout designs, for enquiries after the rollout date."""
    rate = cfg.costs.labor_rate_per_hour
    ref = cfg.design.arms[0].name
    scopes = {"all": None}
    if cfg.design.rollout_date:
        from datetime import datetime

        scopes["after_rollout"] = datetime.combine(cfg.design.rollout_date, datetime.min.time(),
                                                   tzinfo=world.period_start.tzinfo)
    out = {}
    for scope, since in scopes.items():
        m = {arm: _arm_metrics(_population(ts, since), rate) for arm, ts in runs.items()}
        out[scope] = {
            "metrics_if_everyone_got_arm": m,
            "causal_effects": {f"{arm}_minus_{ref}": {k: v["diff"] for k, v in compare(m[ref], m[arm]).items()}
                               for arm in m if arm != ref},
        }
    return out


def planted_effects(cfg: GeneratorConfig, rules: ServiceRules, world: World, h: Handled,
                    counterfactual: dict | None = None) -> dict:
    """True in-sample metrics per arm on the evaluation population (in-scope enquiries in the study
    period), every pairwise difference with its precision, and (optionally) true causal effects."""
    by_arm: dict[str, list[Truth]] = defaultdict(list)
    for t in _population(h.truths):
        by_arm[t.arm].append(t)
    arms = [a.name for a in cfg.design.arms]
    metrics = {a: _arm_metrics(by_arm[a], cfg.costs.labor_rate_per_hour) for a in arms}
    comparisons = {}
    for i, a in enumerate(arms):
        for b in arms[i + 1 :]:
            c = {"difference": compare(metrics[a], metrics[b])}
            if a in cfg.agents and b in cfg.agents:
                c["identical_behaviour"] = cfg.agents[a] == cfg.agents[b]
            comparisons[f"{b}_minus_{a}"] = c
    notes = [
        "metrics_by_arm are true in-sample values; a correct evaluator should recover them from the exports.",
        "comparisons: in-sample differences with standard error and mde_80 (minimum detectable effect at 80% power).",
        "Staffing is flat by design: released human capacity is NOT realized cash savings.",
        "Variable cost = human active minutes x labor rate + AI token/voice usage; fixed costs are separate.",
    ]
    if cfg.design.type != "randomized_split":
        notes.append("Arms are assigned by date/region, so in-sample differences are NOT causal; "
                     "use counterfactual.*.causal_effects as the true effect.")
    return {
        "dataset_name": cfg.dataset_name,
        "rule_version": rules.rule_version,
        "design": cfg.design.model_dump(mode="json"),
        "population": "in-scope enquiries received inside the study period",
        "study_period": [world.period_start.isoformat(), world.period_end.isoformat()],
        "data_cutoff": world.data_cutoff.isoformat(),
        "agent_behaviour": {k: v.model_dump() for k, v in cfg.agents.items()},
        "delay_regimes": [r.model_dump(mode="json") for r in cfg.operations.delay_regimes],
        "metrics_by_arm": metrics,
        "comparisons": comparisons,
        "counterfactual": counterfactual,
        "realized_cash_savings": 0.0,
        "notes": notes,
    }
