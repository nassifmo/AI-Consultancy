"""Assess a reconciled shipment pilot comparison without pricing service time by assumption."""

from __future__ import annotations

import argparse
import json
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator


Ref = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
Number = Annotated[Decimal, Field(allow_inf_nan=False, max_digits=18, decimal_places=6)]
Nonnegative = Annotated[Number, Field(ge=0)]
Rate = Annotated[Number, Field(ge=0, le=1)]
PositiveCount = Annotated[int, Field(strict=True, gt=0)]
Count = Annotated[int, Field(strict=True, ge=0)]
ZERO = Decimal(0)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Outcomes(Contract):
    verified: Count
    unknown: Count


class CostLine(Contract):
    entry_id: Ref
    evidence_ref: Ref
    payer: Ref
    currency: Currency
    expense_date: date
    amount: Number  # Credits are negative, with their own document line reference.


class CostBucket(Contract):
    bucket_id: Ref
    kind: Literal["handling", "downstream"]
    comparator_reconciliation_ref: Ref | None = None
    candidate_reconciliation_ref: Ref | None = None
    downstream_linkage_ref: Ref | None = None
    comparator: list[CostLine] = Field(default_factory=list)
    candidate: list[CostLine] = Field(default_factory=list)


class Arm(Contract):
    label: Ref
    eligible_enquiries: PositiveCount
    timely_correct_resolutions: Outcomes | None = None
    critical_failures: Outcomes | None = None
    active_work_minutes: Nonnegative | None = None
    active_work_reconciliation_ref: Ref | None = None

    @model_validator(mode="after")
    def validate_counts(self) -> Arm:
        for outcomes in (self.timely_correct_resolutions, self.critical_failures):
            if outcomes and outcomes.verified + outcomes.unknown > self.eligible_enquiries:
                raise ValueError("verified plus unknown exceeds eligible enquiries")
        return self


class ReviewedInterval(Contract):
    lower_per_enquiry: Number
    upper_per_enquiry: Number
    confidence_level: Annotated[Rate, Field(gt=0, lt=1)]
    reference: Ref

    @model_validator(mode="after")
    def ordered(self) -> ReviewedInterval:
        if self.lower_per_enquiry > self.upper_per_enquiry:
            raise ValueError("effect interval lower bound exceeds upper bound")
        return self


class PilotEvidence(Contract):
    origin: Literal["synthetic", "company"]
    payer: Ref
    currency: Currency
    study_start: date
    study_end_exclusive: date
    scope_ref: Ref
    comparable_scope_ref: Ref | None = None
    downstream_scope: Literal["included", "out_of_scope", "not_assessed"]
    comparator: Arm
    candidate: Arm
    buckets: list[CostBucket]
    critical_failure_limit: Rate | None = None
    minimum_timely_correct_rate: Rate | None = None
    service_policy_ref: Ref | None = None
    finance_review_ref: Ref | None = None
    attribution_review_ref: Ref | None = None
    net_effect_interval: ReviewedInterval | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> PilotEvidence:
        if self.study_end_exclusive <= self.study_start:
            raise ValueError("study end must follow study start")
        if self.candidate.label == self.comparator.label:
            raise ValueError("candidate and comparator labels must differ")
        if self.downstream_scope != "included" and any(b.kind == "downstream" for b in self.buckets):
            raise ValueError("downstream lines require downstream_scope=included")
        seen_buckets, seen_entries = set(), set()
        for b in self.buckets:
            if b.bucket_id in seen_buckets:
                raise ValueError("duplicate bucket identifier")
            seen_buckets.add(b.bucket_id)
            for line in b.comparator + b.candidate:
                if line.entry_id in seen_entries:
                    raise ValueError("duplicate ledger entry identifier across buckets or arms")
                seen_entries.add(line.entry_id)
                if line.payer != self.payer or line.currency != self.currency:
                    raise ValueError("mixed payer or currency: provide one scoped comparison")
                if not self.study_start <= line.expense_date < self.study_end_exclusive:
                    raise ValueError("expense date outside the stated study period")
        return self


def _observed_range(outcomes: Outcomes | None, n: int) -> tuple[Decimal, Decimal] | None:
    if outcomes is None:
        return None
    return Decimal(outcomes.verified) / n, Decimal(outcomes.verified + outcomes.unknown) / n


def _scoped_amount(evidence: PilotEvidence, kind: str) -> dict:
    buckets = [b for b in evidence.buckets if b.kind == kind]
    missing = [
        f"{b.bucket_id}:{arm}" for b in buckets for arm in ("comparator", "candidate")
        if not getattr(b, f"{arm}_reconciliation_ref")
    ]
    if kind == "downstream":
        missing.extend(f"{b.bucket_id}:downstream_linkage" for b in buckets if not b.downstream_linkage_ref)
    total = {
        arm: sum((line.amount for b in buckets for line in getattr(b, arm)), ZERO)
        for arm in ("comparator", "candidate")
    }
    comparable = bool(buckets and not missing and evidence.comparable_scope_ref)
    return {
        "status": "complete" if comparable else "incomplete",
        "documented_totals": total if buckets else None,
        "cost_per_eligible_enquiry": {
            arm: amount / getattr(evidence, arm).eligible_enquiries for arm, amount in total.items()
        } if comparable else None,
        "unreconciled_buckets": missing,
        "reconciliation_refs": {
            b.bucket_id: {"comparator": b.comparator_reconciliation_ref,
                          "candidate": b.candidate_reconciliation_ref,
                          "downstream_linkage": b.downstream_linkage_ref} for b in buckets
        },
    }


def _service(evidence: PilotEvidence) -> dict:
    b, c = evidence.comparator, evidence.candidate
    b_rates = _observed_range(b.timely_correct_resolutions, b.eligible_enquiries)
    c_rates = _observed_range(c.timely_correct_resolutions, c.eligible_enquiries)
    critical = _observed_range(c.critical_failures, c.eligible_enquiries)
    checks = {}
    if not evidence.service_policy_ref or evidence.critical_failure_limit is None or critical is None:
        checks["critical_failures"] = "unassessable"
    elif critical[0] > evidence.critical_failure_limit:
        checks["critical_failures"] = "limit_exceeded"
    elif critical[1] > evidence.critical_failure_limit:
        checks["critical_failures"] = "unknowns_could_exceed_limit"
    else:
        checks["critical_failures"] = "within_limit"
    target = evidence.minimum_timely_correct_rate
    if not evidence.service_policy_ref or target is None or c_rates is None:
        checks["timely_correct_resolutions"] = "unassessable"
    elif c_rates[1] < target:
        checks["timely_correct_resolutions"] = "below_target"
    elif c_rates[0] < target:
        checks["timely_correct_resolutions"] = "unknowns_affect_target"
    else:
        checks["timely_correct_resolutions"] = "target_met"
    return {
        "gates": checks,
        "candidate_critical_failure_rate_bounds": critical,
        "comparator_timely_correct_rate_bounds": b_rates,
        "candidate_timely_correct_rate_bounds": c_rates,
        "verified_timely_correct_rate_difference": c_rates[0] - b_rates[0] if b_rates and c_rates else None,
        "timely_correct_rate_difference_bounds": (
            (c_rates[0] - b_rates[1], c_rates[1] - b_rates[0]) if b_rates and c_rates else None
        ),
    }


def _break_even(handling_delta: Decimal | None, service: dict) -> dict:
    gain = service["verified_timely_correct_rate_difference"]
    bounds = service["timely_correct_rate_difference_bounds"]
    result = {"status": "unavailable", "point_price_per_extra_timely_resolution": None,
              "price_range": None, "excludes_downstream_and_capacity": True}
    if handling_delta is None or gain is None or bounds is None:
        return result
    if handling_delta <= 0:
        return {**result, "status": "no_positive_handling_premium"}
    if bounds[1] <= 0:
        return {**result, "status": "no_positive_gain_on_selected_metric"}
    return {
        **result,
        "status": "conditional_range" if bounds[0] > 0 else "no_finite_worst_case_threshold",
        "point_price_per_extra_timely_resolution": handling_delta / gain if gain > 0 else None,
        "price_range": (handling_delta / bounds[1], handling_delta / bounds[0] if bounds[0] > 0 else None),
    }


def assess_pilot_economics(data: PilotEvidence | dict) -> dict:
    """Summarize evidence. Comparability and causal validity are reviewed upstream."""
    e = data if isinstance(data, PilotEvidence) else PilotEvidence.model_validate(data)
    with localcontext() as context:
        context.prec = 36
        handling = _scoped_amount(e, "handling")
        downstream = _scoped_amount(e, "downstream")
        h, d = handling["cost_per_eligible_enquiry"], downstream["cost_per_eligible_enquiry"]
        increment = h["candidate"] - h["comparator"] if h else None
        avoided = d["comparator"] - d["candidate"] if d else None
        net = None
        if increment is not None:
            if e.downstream_scope == "out_of_scope":
                net = -increment
            elif avoided is not None:
                net = avoided - increment
        service = _service(e)
        b, c = e.comparator, e.candidate
        capacity = (
            (b.active_work_minutes / b.eligible_enquiries - c.active_work_minutes / c.eligible_enquiries)
            * 1000 / 60 if all(
                x.active_work_minutes is not None and x.active_work_reconciliation_ref for x in (b, c)
            ) and e.comparable_scope_ref else None
        )
        interval = e.net_effect_interval
        if interval and (net is None or not interval.lower_per_enquiry <= net <= interval.upper_per_enquiry):
            raise ValueError("submitted net effect interval does not contain the comparable observed net difference")
        if e.origin == "synthetic":
            status = "illustrative_only"
        elif any(gate in {"limit_exceeded", "below_target"} for gate in service["gates"].values()):
            status = "blocked_by_service_policy"
        elif any(gate not in {"within_limit", "target_met"} for gate in service["gates"].values()):
            status = "service_evidence_incomplete"
        elif net is None:
            status = "financial_evidence_incomplete"
        elif not e.finance_review_ref or not e.attribution_review_ref or not interval:
            status = "observed_comparison_only"
        elif interval.lower_per_enquiry > 0:
            status = "supports_financial_review"
        elif interval.upper_per_enquiry < 0:
            status = "financial_case_not_supported"
        else:
            status = "financial_effect_uncertain"
        return {
            "version": 1, "origin": e.origin, "payer": e.payer, "currency": e.currency,
            "scope_ref": e.scope_ref, "comparable_scope_ref": e.comparable_scope_ref,
            "period": [e.study_start.isoformat(), e.study_end_exclusive.isoformat()],
            "eligible_enquiries": {"comparator": b.eligible_enquiries, "candidate": c.eligible_enquiries},
            "study_comparison": {"comparator": b.label, "candidate": c.label},
            "handling_expense": handling, "downstream_expense": downstream, "downstream_scope": e.downstream_scope,
            "incremental_handling_expense_per_enquiry": increment,
            "observed_downstream_expense_reduction_per_enquiry": avoided,
            "observed_net_expense_reduction_per_enquiry": net,
            "net_expense_scope": (
                ("handling_only" if e.downstream_scope == "out_of_scope" else "handling_and_listed_downstream")
                if net is not None else None
            ),
            "released_active_work_hours_per_1000_enquiries": capacity,
            "service": service, "handling_only_break_even": _break_even(increment, service),
            "review_refs": {"finance": e.finance_review_ref, "attribution": e.attribution_review_ref,
                            "service": e.service_policy_ref},
            "submitted_net_effect_interval": interval.model_dump() if interval else None,
            "assessment_status": status,
            "limitations": [
                "Amounts are scoped accounting observations; the program does not validate source authenticity, "
                "estimate causal effects, or establish realized cash savings.",
                "Active work capacity is separate from financial totals.",
                "A company owner must approve any action.",
            ],
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path, help="JSON input using the PilotEvidence contract.")
    args = parser.parse_args(argv)
    try:
        evidence = PilotEvidence.model_validate_json(args.evidence.read_bytes())
        estimate = assess_pilot_economics(evidence)
    except (OSError, ValueError, ValidationError) as exc:
        parser.exit(2, f"Pilot economics input rejected: {exc}\n")
    print(json.dumps(estimate, indent=2, default=str, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
