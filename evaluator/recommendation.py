"""Propose a reviewable decision for one pair of shipment handling policies."""

from math import isfinite

import numpy as np

from .comparisons import cluster_weights
from .upgrade_value import _success, assess_upgrade


VALUE_BASES = {
    "illustrative": "Illustrative assumption",
    "company_estimate": "Company estimate supplied by the reviewer",
    "documented": "Documented financial evidence supplied by the reviewer",
}

CASE_ACTIONS = {
    "shipment_identity": "Review how the reply was tied to the requested container. Test a check that blocks sending when the selected tracking event belongs to another container.",
    "initial_escalation": "Check where the escalation failed. Test that a required case is recorded and reaches the operations queue before the enquiry leaves agent handling.",
}

NEXT_ACTIONS = {
    "collect_assignment": ("Collect comparison evidence", "Link requests to their original handling assignments and obtain an eligible group for each policy."),
    "agree_failure_limit": ("Agree on the critical failure limit", "Ask the support owner to define what counts as a critical failure and set the review limit before comparing economics."),
    "redesign_and_retest": ("Review failures and retest", "Open the linked critical cases. Confirm their cause with support and operations, correct the workflow, and retest before expanding its use."),
    "verify_critical_cases": ("Verify the unresolved critical checks", "Obtain missing reply, tracking or case evidence and review the affected requests before increasing exposure."),
    "improve_comparison": ("Improve the comparison design", "Confirm recorded allocation and follow-up. Use a controlled comparison to test the change in outcomes and costs."),
    "reconcile_costs": ("Reconcile the cost inputs", "Confirm the scoped usage, labour and invoices for both policies and reconcile them in one currency."),
    "validate_business_value": ("Agree on what an improvement is worth", "Use the break-even threshold with finance and operations. Confirm what decision or documented expense the improvement changes."),
    "continue_controlled_trial": ("Continue the controlled trial", "Keep the current scope. Resolve the material evidence gaps and gather more comparable requests before changing the rollout."),
    "keep_comparator": ("Keep the current handling policy for this scope", "Review the business and cost assumptions with finance. Reassess if costs, service outcomes or scope change."),
    "consider_controlled_expansion": ("Consider a monitored expansion trial", "Review the cost assumptions with finance and seek approval from the service owner. Set the next test scope, ongoing critical-failure checks and a rollback condition."),
}


def _critical_risk(rows, limit):
    failures = [row["root_enquiry_id"] for row in rows if row.get("initial_failure") is True]
    unknown = [row["root_enquiry_id"] for row in rows if row.get("initial_failure") is None]
    counts = {"eligible": len(rows), "verified_failures": len(failures), "unknown": len(unknown)}
    bounds = [len(failures) / len(rows), (len(failures) + len(unknown)) / len(rows)] if rows else None
    status = "unavailable"
    if bounds is not None and limit is not None:
        status = "exceeded" if bounds[0] > limit else "within_limit" if bounds[1] <= limit else "uncertain"
    return {**counts, "limit": limit, "bounds": bounds, "status": status,
            "failure_episode_ids": failures, "unknown_episode_ids": unknown}


def case_review_actions(assessment):
    """Suggest a test for a verified critical finding in an individual enquiry."""
    return [
        {"criterion": criterion, "action": CASE_ACTIONS[criterion], "refs": finding["refs"]}
        for criterion, finding in assessment.get("criteria", {}).items()
        if criterion in CASE_ACTIONS and finding["status"] == "unmet"
        and finding["severity"] == "critical" and finding.get("refs")
    ]


def _net_uncertainty(rows, config, priority, target_hours, value):
    """Resample bounds on net value jointly with the recorded per-request costs."""
    customers = [{row.get("customer_id") for row in arm} for arm in rows]
    if any(None in ids or "" in ids for ids in customers):
        return None, "Missing customer identifiers for clustered uncertainty."
    if min(map(len, customers)) < config["minimum_customers_per_arm_for_interval"]:
        return None, "Too few customers in a comparison group for the configured interval."
    keys = {customer: index for index, customer in enumerate(sorted(customers[0] | customers[1]))}
    totals = np.zeros((len(keys), 7))
    target_seconds = target_hours * 3600 if target_hours else None
    for index, arm in enumerate(rows):
        if any(type(row.get("total_cost")) not in (int, float) or not isfinite(row["total_cost"]) for row in arm):
            return None, "Comparable per-request costs are missing."
        for row in arm:
            success = _success(row, priority, target_seconds)
            contribution = value * (success is True) - row["total_cost"]
            possible_contribution = contribution if success is not None else value - row["total_cost"]
            customer = keys[row["customer_id"]]
            totals[customer, index * 3:index * 3 + 3] += (contribution, possible_contribution, 1)
            if index == 1:
                totals[customer, 6] += row.get("initial_failure") is not False

    weights = cluster_weights(len(keys), config["bootstrap_resamples"], config["bootstrap_seed"])
    samples = weights @ totals
    samples = samples[(samples[:, 2] > 0) & (samples[:, 5] > 0)]
    if len(samples) < 0.95 * len(weights) or not np.isfinite(samples).all():
        return None, "The clustered resampling did not produce a stable finite result."
    left = samples[:, :2] / samples[:, 2:3]
    right = samples[:, 3:5] / samples[:, 5:6]
    lower = right[:, 0] - left[:, 1]
    upper = right[:, 1] - left[:, 0]
    if min(np.ptp(lower), np.ptp(upper)) <= 1e-12:
        return None, "The available customer variation does not support this bootstrap range."
    tail = (1 - config["confidence_level"]) / 2
    endpoints = [float(np.quantile(lower, tail)), float(np.quantile(upper, 1 - tail))]
    if not all(map(isfinite, endpoints)):
        return None, "The resampled value range is outside the supported calculation limits."
    critical = samples[:, 6] / samples[:, 5]
    critical_upper = float(np.quantile(critical, 1 - tail)) if np.ptp(critical) > 1e-12 else None
    return {"bounds": endpoints, "confidence_level": config["confidence_level"],
            "method": "pooled_customer_cluster_percentile_outer_bounds",
            "critical_upper": critical_upper, "valid_resamples": len(samples),
            "customers_per_arm": list(map(len, customers))}, None


def _decision(value, risk, uncertainty, value_basis, value_evidence):
    if any(not item["eligible"] for item in value["metrics"].values()):
        return "collect_assignment", "Two eligible handling groups are needed for a recommendation."
    if risk["limit"] is None:
        return "agree_failure_limit", "This review has no agreed maximum critical failure rate."
    if risk["status"] == "exceeded":
        return "redesign_and_retest", "Verified critical failures alone exceed the limit in the evaluated sample."
    if value["comparison_status"] != "randomized_assignment":
        return "improve_comparison", "Recorded assignment is insufficient to attribute the observed difference to this policy."
    if risk["status"] != "within_limit":
        return "verify_critical_cases", "Critical checks with unknown results could put the proposed policy above the sample limit."
    if value["incremental_cost_per_request"] is None:
        return "reconcile_costs", "At least one group lacks complete comparable resource costs."
    if value["value_per_success"] is None or value_basis in {None, "illustrative"} or not value_evidence:
        return "validate_business_value", "There is no confirmed value per additional success for this decision."
    if uncertainty is None:
        return "continue_controlled_trial", "The available data do not support a stable resampled range for the modeled net value."
    lower, upper = uncertainty["bounds"]
    if lower > 1e-9:
        critical_upper = uncertainty["critical_upper"]
        if critical_upper is None or critical_upper > risk["limit"]:
            return "continue_controlled_trial", "The modeled net value is positive across the range. The critical-failure evidence needs to be stronger before expansion."
        return "consider_controlled_expansion", "The modeled net value stays above zero across the range. The upper critical failure estimate is within the selected limit."
    if upper < -1e-9:
        return "keep_comparator", "The modeled net value stays below zero across the estimated range at the supplied business value."
    return "continue_controlled_trial", "The uncertainty range includes zero at the supplied business value."


def assess_recommendation(analysis, comparator, treatment, priority, *, target_hours=None,
                          value_per_success=None, value_basis=None, value_evidence=None, max_critical_rate=None):
    """Suggest an action for human review and preserve the evidence and decision settings."""
    if max_critical_rate is not None and (type(max_critical_rate) not in (int, float) or not 0 <= max_critical_rate <= 1):
        raise ValueError("The maximum critical failure rate must be between zero and one.")
    if value_basis is not None and value_basis not in VALUE_BASES:
        raise ValueError("Choose a supported basis for the business value.")
    if value_evidence is not None and (not isinstance(value_evidence, str) or len(value_evidence) > 280):
        raise ValueError("The value evidence note must be text up to 280 characters.")
    value_evidence = (value_evidence or "").strip() or None
    value = assess_upgrade(analysis, comparator, treatment, priority, target_hours, value_per_success)
    rows = tuple([row for row in analysis.get("episodes", ()) if row.get("eligible") and row.get("assigned_arm") == arm]
                 for arm in (comparator, treatment))
    risk = _critical_risk(rows[1], max_critical_rate)
    uncertainty = None
    uncertainty_gap = None
    if (value["comparison_status"] == "randomized_assignment" and value["net_value_bounds"] is not None):
        uncertainty, uncertainty_gap = _net_uncertainty(rows, analysis["analysis_config"], priority,
                                                        value["target_hours"], value_per_success)
    action, reason = _decision(value, risk, uncertainty, value_basis, value_evidence)
    title, next_step = NEXT_ACTIONS[action]
    return {
        "schema_version": "1.0", "source_run_id": value["source_run_id"],
        "dataset_origin": analysis.get("data_readiness", {}).get("dataset_origin", "unconfirmed"),
        "action": action, "title": title, "reason": reason, "next_step": next_step,
        "value_basis": value_basis, "value_evidence": value_evidence, "value_assessment": value,
        "critical_check": risk, "net_uncertainty": uncertainty, "uncertainty_gap": uncertainty_gap,
        "scope": "Decision support for human review of the evaluated workflow and policies.",
    }
