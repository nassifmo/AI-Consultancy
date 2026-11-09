"""Layer 6: costs and commercial records (AI invoices, cost parameters, staffing, rollout log)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from datagen.config_schema import GeneratorConfig

from .handling import HUMAN_BASELINE, Handled
from .model import World


def _months(start: datetime, end: datetime) -> list[str]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def ai_invoice_rows(cfg: GeneratorConfig, world: World, h: Handled) -> list[dict]:
    """Monthly vendor invoice: usage lines from every agent run (failures and handoffs included)."""
    p = cfg.costs.unit_prices
    usage: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r in h.agent_runs:
        month = r["started_at"].strftime("%Y-%m")
        usage[month]["voice_minutes"] += (r["voice_seconds"] or 0) / 60
        usage[month]["llm_tokens_in"] += r["tokens_in"]
        usage[month]["llm_tokens_out"] += r["tokens_out"]
        usage[month]["runs"] += 1
    prices = {"voice_minutes": p.voice_minutes, "llm_tokens_in": p.llm_tokens_in,
              "llm_tokens_out": p.llm_tokens_out, "runs": p.runs}
    uses_ai = any(a.name != HUMAN_BASELINE for a in cfg.design.arms)
    rows = []
    for month in _months(world.period_start, world.data_cutoff):
        for item, price in prices.items():
            qty = round(usage[month][item], 2)
            rows.append({"period": month, "line_item": item, "quantity": qty, "unit_price": price,
                         "amount": round(qty * price, 2), "currency": cfg.costs.currency})
        if uses_ai:
            rows.append({"period": month, "line_item": "platform_fee", "quantity": 1,
                         "unit_price": cfg.costs.platform_fee_month, "amount": cfg.costs.platform_fee_month,
                         "currency": cfg.costs.currency})
    return rows


def cost_parameters(cfg: GeneratorConfig, world: World) -> dict:
    c = cfg.costs
    return {"currency": c.currency, "labor_rate_per_hour": c.labor_rate_per_hour, "setup_cost": c.setup_cost,
            "amortization_months": c.amortization_months, "platform_fee_month": c.platform_fee_month,
            "maintenance_month": c.maintenance_month, "valid_from": world.period_start.date().isoformat()}


def staffing_rows(cfg: GeneratorConfig, world: World) -> list[dict]:
    """Headcount stays flat: the AI releases capacity but no spending is actually cut (planted truth)."""
    if not cfg.costs.staffing.generate:
        return []
    return [{"month": m, "support_headcount": cfg.costs.staffing.baseline_headcount, "overtime_hours": 0,
             "outsourcing_spend": 0} for m in _months(world.period_start, world.data_cutoff)]


def rollout_rows(cfg: GeneratorConfig, world: World) -> list[dict]:
    d = cfg.design
    start = world.period_start.date().isoformat()
    if d.type == "randomized_split":
        return [{"date": start, "agent_version": a.name, "arm_assignment_rule": "random_by_enquiry",
                 "traffic_share": a.share, "change_description": _describe(a.name)} for a in d.arms]
    before, after = d.arms[0].name, d.arms[1].name
    rule = "by_region" if d.type == "staged_rollout" else "all_traffic"
    share = 0.5 if d.type == "staged_rollout" else 1.0
    return [
        {"date": start, "agent_version": before, "arm_assignment_rule": "all_traffic", "traffic_share": 1.0,
         "change_description": _describe(before)},
        {"date": d.rollout_date.isoformat(), "agent_version": after, "arm_assignment_rule": rule,
         "traffic_share": share, "change_description": _describe(after)},
    ]


def _describe(arm: str) -> str:
    return {
        HUMAN_BASELINE: "Existing human-handled process",
        "agent_v1": "AI agent first release",
        "agent_v2": "Integrator enhancement: fresher tracking data, stricter escalation",
    }.get(arm, arm)
