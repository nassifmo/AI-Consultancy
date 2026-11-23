"""Run the enquiry verifier, cohort comparison and economics on one export."""

from copy import deepcopy
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
from math import isfinite
from pathlib import Path
import platform

from .cohorts import ARMS, assemble_episodes
from .comparisons import compare, design_diagnostics
from .economics import build_cost_ledger, overlapping_work_ids
from .exports import load_exports, reference
from .input_quality import assess_input_quality
from .metrics import summarize
from .readiness import assess_readiness
from .verification import Verifier


DEFAULT_CONFIG = {
    "schema_version": "1.0",
    "comparison_followup_days": 7,
    "bootstrap_resamples": 2000,
    "bootstrap_seed": 20261117,
    "confidence_level": 0.95,
    "minimum_customers_per_arm_for_interval": 50,
    "shared_fixed_cost_allocation": "ai_root_request_count",
    "comparison_pairs": [
        ["human_baseline", "agent_v1"], ["human_baseline", "agent_v2"], ["agent_v1", "agent_v2"],
    ],
}


def validate_config(analysis_config=None):
    if analysis_config is not None and not isinstance(analysis_config, dict):
        raise ValueError("The analysis configuration must be a JSON object.")
    config = deepcopy(DEFAULT_CONFIG)
    if analysis_config:
        extra = analysis_config.keys() - config.keys()
        if extra:
            raise ValueError(f"Unknown analysis settings: {', '.join(sorted(extra))}.")
        config.update(deepcopy(analysis_config))
    for key, minimum, maximum in (
        ("comparison_followup_days", 1, 365),
        ("bootstrap_resamples", 100, 10000),
        ("bootstrap_seed", 0, 2**32 - 1),
        ("minimum_customers_per_arm_for_interval", 2, 10000),
    ):
        value = config[key]
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"{key} must be an integer from {minimum} to {maximum}.")
    value = config["confidence_level"]
    if type(value) not in (float, int) or not isfinite(value) or not 0 < value < 1:
        raise ValueError("confidence_level must be between zero and one.")
    if config["schema_version"] != "1.0" or config["shared_fixed_cost_allocation"] != "ai_root_request_count":
        raise ValueError("Unsupported analysis version or shared fixed cost allocation.")
    pairs = config["comparison_pairs"]
    if not isinstance(pairs, list) or not pairs or any(
        not isinstance(pair, list) or len(pair) != 2 or any(arm not in ARMS for arm in pair) or pair[0] == pair[1]
        for pair in pairs
    ) or len({tuple(pair) for pair in pairs}) != len(pairs):
        raise ValueError("Provide unique comparator and treatment pairs with different supported arms.")
    return config


def _timeline(verifier, enquiry):
    enquiry_id = enquiry["enquiry_id"]
    data = verifier.data
    events = []

    def append(table, row, key, event, actor, detail):
        at = data.time(table, row.get(key))
        if at and data.cutoff and at <= data.cutoff:
            events.append({"at": at.isoformat(), "event": event, "actor_id": actor or None,
                           "detail": detail, "ref": reference(table, row)})

    append("enquiries", enquiry, "received_at", "Enquiry received", None, enquiry.get("customer_message"))
    for row in verifier.runs[enquiry_id]:
        append("agent_runs", row, "ended_at", "AI run", row.get("agent_version"),
               {"steps": [{"tool": step.get("tool_name"), "success": step.get("success")} for step in row["steps"]],
                "handoff_reported": row.get("handoff_flag")})
    for row in verifier.responses[enquiry_id]:
        append("responses", row, "sent_at", f"Sent {row['purpose']}", row.get("actor_id"), row.get("message_text"))
    for row in verifier.cases[enquiry_id]:
        append("cases", row, "opened_at", "Case opened", row.get("owner_id"), row.get("reason"))
        append("cases", row, "closed_at", "Case closure recorded", row.get("owner_id"), row.get("closure_code"))
        for entry in verifier.history[row["case_id"]]:
            append("case_history", entry, "changed_at", "Case update", entry.get("changed_by"),
                   {"field": entry["field"], "new_value": entry.get("new_value")})
    for row in verifier.work[enquiry_id]:
        append("agent_work", row, "closed_at", "Human work recorded", row.get("agent_id"),
               {"activity": row.get("activity"), "reported_active_seconds": row.get("active_seconds"),
                "measurement_method": row.get("measurement_method")})
    return sorted(events, key=lambda event: (event["at"], event["event"], event["ref"]))


def _provenance(data, policy, config):
    package = Path(__file__).parent
    sources = hashlib.sha256()
    for path in sorted(package.glob("*.py")):
        sources.update(path.name.encode("utf-8"))
        sources.update(path.read_bytes())
    dependencies = {}
    for name in ("numpy", "scipy", "streamlit", "pydantic", "pyyaml", "tzdata"):
        try:
            dependencies[name] = version(name)
        except PackageNotFoundError:
            dependencies[name] = None
    files = dict(sorted(data.files.items()))
    policy_hash = hashlib.sha256(json.dumps(policy, sort_keys=True, allow_nan=False).encode()).hexdigest()
    snapshot = {
        "input_files": files, "policy_sha256": policy_hash, "policy_version": policy["version"],
        "export_rule_version": data.metadata.get("rule_version"),
        "preparation_id": data.metadata.get("preparation_id"),
        "source_profile_id": data.metadata.get("source_profile_id"),
        "source_profile_version": data.metadata.get("source_profile_version"),
        "evaluator_sha256": sources.hexdigest(), "python_version": platform.python_version(),
        "dependencies": dependencies, "analysis_config": config,
    }
    # Hash inputs and effective settings, without timestamps or location-dependent values.
    snapshot["run_id"] = hashlib.sha256(json.dumps(snapshot, sort_keys=True, allow_nan=False).encode()).hexdigest()[:24]
    return snapshot


def analyze_exports(exports_path, policy, analysis_config=None):
    """Return a reproducible analysis using operational exports only."""
    config = validate_config(analysis_config)
    data = load_exports(exports_path, analysis=True)
    overlaps = overlapping_work_ids(data)
    verifier = Verifier(data, policy, excluded_work_ids=overlaps)
    enquiries = sorted(verifier.enquiries, key=lambda row: row["enquiry_id"])
    latest = {row["enquiry_id"]: verifier.evaluate(row) for row in enquiries}
    episodes, checkpoints, exclusions, unlinked = assemble_episodes(
        verifier, latest, config["comparison_followup_days"], overlaps,
    )
    episodes.sort(key=lambda entry: entry["root_enquiry_id"])
    ledger = build_cost_ledger(data, episodes)
    for row in episodes:
        cost = ledger["per_episode"].get(row["root_enquiry_id"], {})
        row.update(total_cost=cost.get("total_cost"), known_cost=cost.get("known_cost"),
                   cost_estimated=cost.get("estimated"))
    currency = ledger.get("currency") or "currency/request"
    groups, rows = summarize(episodes, currency)
    diagnostics = design_diagnostics(data, episodes, unlinked)
    comparisons = compare(groups, rows, diagnostics["comparison_status"], config, ledger)
    for row in enquiries:
        key = row["enquiry_id"]
        result = latest[key]
        received = data.time("enquiries", row["received_at"])
        result.update(customer_id=row.get("customer_id"), received_at=received.isoformat() if received else None,
                      timeline=_timeline(verifier, row), checkpoint_result=checkpoints.get(key))

    limitations = [
        "The applied service policy and comparison follow-up setting govern this analysis.",
        "Structured replies and reviewed request phrasing determine verification coverage.",
        "The valuation is limited to documented resource costs and capacity. Realized cash savings are unavailable.",
    ]
    if data.metadata.get("dataset_origin") == "synthetic":
        limitations.append("Synthetic results represent the simulated workflow.")
    if data.metadata.get("rule_version") and data.metadata["rule_version"] != policy["version"]:
        limitations.append("The historical generator labels and applied verifier policy use different rules.")
    if diagnostics["comparison_status"] != "randomized_assignment":
        limitations.append("A randomized causal comparison is unsupported for this export.")
    readiness = assess_readiness(data, policy, verified=latest.values(), episodes=episodes,
                                 ledger=ledger, diagnostics=diagnostics)
    quality = assess_input_quality(data, latest.values(), overlaps, episodes)
    return {
        "schema_version": "1.0", "run_provenance": _provenance(data, policy, config), "analysis_config": config,
        "data_readiness": {
            "dataset_origin": data.metadata.get("dataset_origin", "unconfirmed"),
            "study_period": data.metadata.get("study_period"),
            "data_cutoff": data.cutoff.isoformat() if data.cutoff else None,
            "input_issues": data.issues, "files": list(data.files.values()),
            "eligible_roots": sum(row["eligible"] for row in episodes), "exclusion_counts": exclusions,
            "unlinked_continuations": unlinked, "overlapping_work_records": len(overlaps),
            **diagnostics,
        },
        "readiness_assessment": readiness,
        "input_quality": quality,
        "enquiries": list(latest.values()), "episodes": episodes, "group_metrics": groups,
        "cost_ledger": ledger, "comparisons": comparisons, "limitations": limitations,
    }
