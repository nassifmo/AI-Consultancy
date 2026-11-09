"""Validated schemas for generator configuration and service rules.

Loading a YAML file through these models catches typos, out-of-range probabilities
and inconsistent shares before any data is generated.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Probability = Field(ge=0.0, le=1.0)
SHARE_TOLERANCE = 1e-6


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _check_shares(shares: dict[str, float], what: str) -> dict[str, float]:
    if any(v < 0 for v in shares.values()):
        raise ValueError(f"{what}: shares must be non-negative")
    total = sum(shares.values())
    if abs(total - 1.0) > SHARE_TOLERANCE:
        raise ValueError(f"{what}: shares must sum to 1 (got {total:.4f})")
    return shares


class IntRange(Strict):
    min: int
    max: int

    @model_validator(mode="after")
    def _ordered(self) -> "IntRange":
        if self.min > self.max:
            raise ValueError("min must be <= max")
        return self


class NumRange(Strict):
    min: float
    max: float

    @model_validator(mode="after")
    def _ordered(self) -> "NumRange":
        if self.min > self.max:
            raise ValueError("min must be <= max")
        return self


class Skewed(Strict):
    """Right-skewed positive quantity described by median and 95th percentile (lognormal)."""

    median: float = Field(gt=0)
    p95: float = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> "Skewed":
        if self.p95 < self.median:
            raise ValueError("p95 must be >= median")
        return self


# ---------------------------------------------------------------- generator config


class Period(Strict):
    start: date
    months: int = Field(ge=1, le=24)
    timezone: str = "UTC"


class World(Strict):
    n_customers: int = Field(ge=1)
    n_shipments: int = Field(ge=1)
    segment_shares: dict[Literal["large_account", "mid_market", "small"], float]
    containers_per_shipment: IntRange
    transit_days: IntRange
    ports: list[str] = Field(min_length=2)

    @field_validator("segment_shares")
    @classmethod
    def _shares(cls, v):
        return _check_shares(v, "segment_shares")


class DelayMix(Strict):
    none: float = Probability
    short: float = Probability
    long: float = Probability

    @model_validator(mode="after")
    def _sum(self) -> "DelayMix":
        _check_shares(self.model_dump(), "delay_mix")
        return self


class DelayRegime(Strict):
    """From `from_date` on (by planned arrival), shipments use a different delay mix.
    Used to create a confounder that coincides with a rollout."""

    from_date: date
    delay_mix: DelayMix


class Operations(Strict):
    delay_mix: DelayMix
    delay_regimes: list[DelayRegime] = Field(default_factory=list)
    short_delay_hours: NumRange
    long_delay_hours: NumRange
    eta_revisions: IntRange


class Tracking(Strict):
    recording_lag_minutes: Skewed
    stale_lag_share: float = Probability
    stale_lag_hours: NumRange


class Enquiries(Strict):
    base_rate_per_shipment: float = Field(gt=0)
    delay_rate_multiplier: float = Field(ge=1)
    type_mix: dict[Literal["status", "delay", "documents", "other"], float]
    channel_mix: dict[Literal["voice", "email", "chat"], float]
    language_mix: dict[str, float]
    min_days_between_contacts: float = Field(default=0.0, ge=0)
    wrong_reference_share: float = Probability

    @field_validator("type_mix", "channel_mix", "language_mix")
    @classmethod
    def _shares(cls, v, info):
        return _check_shares(v, info.field_name)


class Arm(Strict):
    name: str
    share: float = Probability


class Design(Strict):
    type: Literal["randomized_split", "staged_rollout", "before_after_confounded"]
    arms: list[Arm] = Field(min_length=2)
    rollout_date: date | None = None

    @model_validator(mode="after")
    def _check(self) -> "Design":
        _check_shares({a.name: a.share for a in self.arms}, "design.arms")
        names = [a.name for a in self.arms]
        if len(names) != len(set(names)):
            raise ValueError("design.arms: duplicate arm names")
        if self.type != "randomized_split" and self.rollout_date is None:
            raise ValueError(f"design.type={self.type} requires rollout_date")
        return self


class Human(Strict):
    queue_minutes: Skewed
    handle_minutes: Skewed
    acw_minutes: Skewed
    error_rate: float = Probability
    escalation_compliance: float = Probability
    case_followup_compliance: float = Probability
    case_minutes: Skewed
    followup_minutes: Skewed
    case_resolution_days: Skewed


class AgentBehaviour(Strict):
    lookup_success: float = Probability
    wrong_shipment_prob: float = Probability
    stale_cache_prob: float = Probability
    escalation_compliance: float = Probability
    unsupported_claim_prob: float = Probability
    handoff_prob: float = Probability
    false_success_report_prob: float = Probability
    tokens_in: Skewed
    tokens_out: Skewed
    voice_seconds: Skewed


class Rescue(Strict):
    rescue_minutes: Skewed
    detection_prob: float = Probability
    delay_hours: NumRange


class FollowUp(Strict):
    repeat_prob_if_failed: float = Probability
    repeat_prob_if_open: float = Probability
    repeat_prob_if_resolved: float = Probability


class UnitPrices(Strict):
    voice_minutes: float = Field(ge=0)
    llm_tokens_in: float = Field(ge=0)
    llm_tokens_out: float = Field(ge=0)
    runs: float = Field(ge=0)


class Staffing(Strict):
    generate: bool
    baseline_headcount: float = Field(gt=0)


class Costs(Strict):
    currency: str = Field(min_length=3, max_length=3)
    labor_rate_per_hour: float = Field(gt=0)
    setup_cost: float = Field(ge=0)
    amortization_months: int = Field(ge=1)
    platform_fee_month: float = Field(ge=0)
    maintenance_month: float = Field(ge=0)
    unit_prices: UnitPrices
    staffing: Staffing


DEFECT_TYPES = (
    "duplicate_row",
    "missing_field",
    "missing_snapshot",
    "timezone_shift",
    "id_typo",
    "orphan_record",
    "retry_row",
    "late_record",
    "conflicting_closure",
)


class Defects(Strict):
    enabled: bool
    rates: dict[str, float]

    @field_validator("rates")
    @classmethod
    def _rates(cls, v):
        unknown = set(v) - set(DEFECT_TYPES)
        if unknown:
            raise ValueError(f"unknown defect types: {sorted(unknown)}")
        for k, r in v.items():
            if not 0.0 <= r <= 1.0:
                raise ValueError(f"defect rate {k} must be in [0, 1]")
        return v


class Rendering(Strict):
    """How exports are rendered. Some company systems export local time (with its offset)."""

    local_timezone: str = "UTC"
    local_time_files: list[str] = Field(default_factory=list)

    @field_validator("local_timezone")
    @classmethod
    def _tz(cls, v):
        from zoneinfo import ZoneInfo

        ZoneInfo(v)  # raises if unknown
        return v


class GeneratorConfig(Strict):
    dataset_name: str
    seed: int
    service_rules_file: str = "service_rules.yaml"
    period: Period
    world: World
    operations: Operations
    tracking: Tracking
    enquiries: Enquiries
    design: Design
    human: Human
    agents: dict[str, AgentBehaviour] = Field(min_length=1)
    rescue: Rescue
    follow_up: FollowUp
    costs: Costs
    rendering: Rendering = Field(default_factory=Rendering)
    defects: Defects
    # Also run every arm on the whole population (same world and enquiries) to get true causal effects.
    counterfactuals: bool = False

    @model_validator(mode="after")
    def _arms_have_behaviour(self) -> "GeneratorConfig":
        for arm in self.design.arms:
            if arm.name != "human_baseline" and arm.name not in self.agents:
                raise ValueError(f"arm '{arm.name}' has no entry under agents")
        return self


# ---------------------------------------------------------------- service rules


class Escalation(Strict):
    escalate_if_delay_hours: float = Field(gt=0)
    max_hours_to_escalate: float = Field(gt=0)


class FollowUpRules(Strict):
    followup_deadline_hours: float = Field(gt=0)
    repeat_contact_window_days: float = Field(gt=0)
    observation_window_days: float = Field(gt=0)

    @model_validator(mode="after")
    def _windows(self) -> "FollowUpRules":
        if self.observation_window_days < self.repeat_contact_window_days:
            raise ValueError("observation_window_days must cover repeat_contact_window_days")
        return self


class InformationCheck(Strict):
    eta_tolerance_hours: float = Field(ge=0)
    status_must_match_latest_recorded: bool


class ClosureCodes(Strict):
    resolved: list[str]
    not_resolved: list[str]
    excluded: list[str]

    @model_validator(mode="after")
    def _disjoint(self) -> "ClosureCodes":
        groups = [set(self.resolved), set(self.not_resolved), set(self.excluded)]
        if any(a & b for i, a in enumerate(groups) for b in groups[i + 1 :]):
            raise ValueError("closure code groups must not overlap")
        return self

    def all_codes(self) -> set[str]:
        return set(self.resolved) | set(self.not_resolved) | set(self.excluded)


class ServiceRules(Strict):
    rule_version: str
    in_scope_enquiry_types: list[Literal["status", "delay", "documents", "other"]] = Field(min_length=1)
    escalation: Escalation
    follow_up: FollowUpRules
    information_check: InformationCheck
    resolution_definition: list[str] = Field(min_length=1)
    closure_codes: ClosureCodes


# ---------------------------------------------------------------- loaders


def _read_yaml(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def read_config_dict(path: str | Path) -> dict:
    """Read a config, resolving `extends: other.yaml` (relative to this file) by deep merge.
    Lists (e.g. design.arms) are replaced, not merged."""
    path = Path(path)
    data = _read_yaml(path)
    parent = data.pop("extends", None)
    if parent:
        data = _deep_merge(read_config_dict(path.parent / parent), data)
    return data


def load_config(path: str | Path) -> GeneratorConfig:
    return GeneratorConfig.model_validate(read_config_dict(path))


def load_rules(path: str | Path) -> ServiceRules:
    return ServiceRules.model_validate(_read_yaml(path))
