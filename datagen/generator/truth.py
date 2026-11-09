"""Ground truth outputs: per-enquiry true outcomes and the planted effects a correct evaluator
should recover. Written before any defect is injected; never given to the evaluator."""

from __future__ import annotations

from collections import defaultdict
from statistics import mean

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


def _arm_metrics(ts: list[Truth], labor_rate: float) -> dict:
    n = len(ts)
    if n == 0:
        return {"n": 0}
    rate = lambda pred: round(sum(pred(t) for t in ts) / n, 4)
    human_min = [t.human_seconds / 60 for t in ts]
    human_cost = [m / 60 * labor_rate for m in human_min]
    ai_cost = [t.ai_cost for t in ts]
    resolved = sum(t.true_outcome == "resolved" for t in ts)
    variable = sum(human_cost) + sum(ai_cost)
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
        "human_cost_per_enquiry": round(mean(human_cost), 4),
        "ai_variable_cost_per_enquiry": round(mean(ai_cost), 5),
        "variable_cost_per_enquiry": round(variable / n, 4),
        "variable_cost_per_verified_resolution": round(variable / resolved, 4) if resolved else None,
    }


def planted_effects(cfg: GeneratorConfig, rules: ServiceRules, world: World, h: Handled) -> dict:
    """True in-sample metrics per arm on the evaluation population (in-scope enquiries in the study
    period) and the differences a correct evaluator should recover."""
    pop = [t for t in h.truths if t.in_population and t.in_scope]
    by_arm: dict[str, list[Truth]] = defaultdict(list)
    for t in pop:
        by_arm[t.arm].append(t)
    metrics = {a.name: _arm_metrics(by_arm[a.name], cfg.costs.labor_rate_per_hour) for a in cfg.design.arms}
    ref = cfg.design.arms[0].name
    diffs = {}
    for a in cfg.design.arms[1:]:
        m, r = metrics[a.name], metrics[ref]
        if m.get("n") and r.get("n"):
            diffs[f"{a.name}_minus_{ref}"] = {
                k: round(m[k] - r[k], 5) for k in m if k != "n" and isinstance(m[k], float) and isinstance(r[k], float)
            }
    return {
        "dataset_name": cfg.dataset_name,
        "rule_version": rules.rule_version,
        "design": cfg.design.model_dump(mode="json"),
        "population": "in-scope enquiries received inside the study period",
        "study_period": [world.period_start.isoformat(), world.period_end.isoformat()],
        "data_cutoff": world.data_cutoff.isoformat(),
        "agent_behaviour": {k: v.model_dump() for k, v in cfg.agents.items()},
        "metrics_by_arm": metrics,
        "differences_vs_reference": diffs,
        "realized_cash_savings": 0.0,
        "notes": [
            "Metrics are the true in-sample values; a correct evaluator should recover them from the exports.",
            "Staffing is flat by design: released human capacity is NOT realized cash savings.",
            "Variable cost = human active minutes x labor rate + AI token/voice usage; fixed costs are separate.",
        ],
    }
