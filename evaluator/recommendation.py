"""Propose a reviewable decision for one pair of shipment handling policies."""

from math import isfinite

import numpy as np

from .comparisons import cluster_weights
from .upgrade_value import _success, assess_error_loss_scenario, assess_upgrade


VALUE_BASES = {
    "illustrative": "Illustrative assumption",
    "company_estimate": "Company estimate supplied by the reviewer",
    "documented": "Documented financial evidence supplied by the reviewer",
}

CASE_ACTIONS = {
    "shipment_identity": (
        "Shipment or container mismatch",
        "Compare the requested container, selected tracking event and sent reply. Test a check that blocks sending when the selected tracking event belongs to another container.",
        "Replay a booking with two containers at different milestones and a request with an ambiguous reference. Check that the agent uses the requested container or asks for clarification or hands off when it cannot verify the match.",
    ),
    "initial_escalation": (
        "Required escalation step missed",
        "Use the case and routing history to find the missing step. Check that a required case is recorded and reaches the operations queue before the enquiry leaves agent handling.",
        "Replay a required escalation with a failed case-creation or routing attempt. Check that the workflow verifies the case and queue or activates a confirmed fallback within the agreed service deadline.",
    ),
}

NEXT_ACTIONS = {
    "collect_assignment": ("Collect comparison evidence", "Link eligible enquiries to their original handling assignments.",
                           "Rollout owner", "Both policies have an eligible group with recorded assignment and follow-up."),
    "agree_failure_limit": ("Agree on the critical failure limit", "Agree which failures are critical and the maximum rate for the proposed scope.",
                            "Customer support and operations", "The service owner has agreed to the failure definition and limit."),
    "redesign_and_retest": ("Review failures and retest", "Keep the trial at its current scope. Open the linked cases and use the proposed replay tests to check the fixes.",
                            "Customer support, operations and the AI integrator", "The fixes pass the targeted replays, and a fresh trial supports the agreed critical-failure limit."),
    "review_source_conflicts": ("Review the disputed records", "Use Data readiness to reconcile the flagged records against the original sources.",
                                "Owner of the affected records", "Reconciliation resolves the eligibility or critical-check dispute and the evaluation is rerun."),
    "verify_critical_cases": ("Verify the unresolved critical checks", "Use the listed enquiries to request missing replies, tracking events or case records.",
                              "Customer support and source owners", "Review of the missing evidence narrows the possible failure rate enough to apply the limit."),
    "improve_comparison": ("Improve the comparison design", "Confirm allocation before handling and use a consistent follow-up window.",
                           "Rollout owner and evaluation team", "A supported study design can estimate the effect of the selected handling policy."),
    "reconcile_costs": ("Reconcile the cost inputs", "Trace usage, labour and invoices for both policies on the same basis and in one currency.",
                        "Finance and support operations", "Both policies have complete comparable costs for the evaluated enquiries."),
    "validate_business_value": ("Agree on what an improvement is worth", "Identify the decision or expense an extra success changes. Compare its evidenced value with the break-even amount when available.",
                                "Finance and operations", "A documented estimate covers the selected outcome, payer and any material losses."),
    "continue_controlled_trial": ("Continue the controlled trial", "Keep the current scope while resolving the evidence gap shown above and gathering comparable enquiries.",
                                  "Rollout owner and evaluation team", "The trial provides enough evidence to judge both economic value and the agreed failure limit."),
    "validate_downstream_loss": ("Check downstream losses before expanding", "Trace costly failures to shipment decisions, charges and credits, then compare those losses with the baseline policy.",
                                 "Finance and shipment operations", "Reconciled evidence shows whether the value remains positive after downstream losses."),
    "keep_comparator": ("Keep the comparator for this scope", "Review the cost and business-value inputs with finance.",
                        "Service owner and finance", "New evidence on costs, outcomes or scope could change the financial comparison."),
    "consider_controlled_expansion": ("Consider a monitored expansion trial", "Propose the next test scope, ongoing outcome checks and a rollback condition for approval.",
                                      "Service owner, operations and finance", "The service owner approves the trial and agrees when to stop or roll back."),
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
        {"criterion": criterion, "finding": CASE_ACTIONS[criterion][0], "action": CASE_ACTIONS[criterion][1],
         "retest": CASE_ACTIONS[criterion][2], "refs": finding["refs"]}
        for criterion, finding in assessment.get("criteria", {}).items()
        if criterion in CASE_ACTIONS and finding["status"] == "unmet"
        and finding["severity"] == "critical" and finding.get("refs")
    ]


def _failure_reviews(rows):
    reviews = {}
    unclassified = []
    for row in rows:
        if row.get("initial_failure") is not True:
            continue
        enquiry_id = row["root_enquiry_id"]
        actions = case_review_actions(row)
        if not actions:
            unclassified.append(enquiry_id)
        for action in actions:
            refs = action.pop("refs")
            review = reviews.setdefault(action["criterion"], {**action, "cases": []})
            review["cases"].append({"enquiry_id": enquiry_id, "refs": refs})
    return sorted(reviews.values(), key=lambda review: (-len(review["cases"]), review["criterion"])), unclassified


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


def _decision(value, risk, uncertainty, value_basis, value_evidence, input_quality_review, loss_scenario):
    if risk["status"] == "exceeded":
        reason = (f"{risk['verified_failures']:,} of {risk['eligible']:,} eligible enquiries already had a critical failure "
                  f"({risk['bounds'][0]:.2%}). That exceeds the {risk['limit']:.2%} limit.")
        if input_quality_review and input_quality_review.get("required") is True:
            reason += " Review the disputed records before reconsidering expansion."
        return "redesign_and_retest", reason
    if input_quality_review and input_quality_review.get("required") is True:
        return ("review_source_conflicts",
                "Unresolved data problems may change which enquiries qualify or whether some "
                "enquiries had a critical failure. The verified cases alone do not settle this decision.")
    if any(not item["eligible"] for item in value["metrics"].values()):
        return "collect_assignment", "Two eligible handling groups are needed for a recommendation."
    if risk["limit"] is None:
        return "agree_failure_limit", "This review has no agreed maximum critical failure rate."
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
        if loss_scenario and loss_scenario["sampling_net_value_bounds"][0] <= 1e-9:
            return "validate_downstream_loss", "The additional loss scenario brings the lower end of the modeled value range to zero or below."
        return "consider_controlled_expansion", "The modeled net value stays above zero across the range. The upper critical failure estimate is within the selected limit."
    if upper < -1e-9:
        return "keep_comparator", "The modeled net value stays below zero across the estimated range at the supplied business value."
    return "continue_controlled_trial", "The uncertainty range includes zero at the supplied business value."


def assess_recommendation(analysis, comparator, treatment, priority, *, target_hours=None,
                          value_per_success=None, value_basis=None, value_evidence=None, max_critical_rate=None,
                          additional_loss_per_1000=None):
    """Suggest an action for human review and preserve the evidence and decision settings."""
    if max_critical_rate is not None and (type(max_critical_rate) not in (int, float) or not 0 <= max_critical_rate <= 1):
        raise ValueError("The maximum critical failure rate must be between zero and one.")
    if value_basis is not None and value_basis not in VALUE_BASES:
        raise ValueError("Choose a supported basis for the business value.")
    if value_evidence is not None and (not isinstance(value_evidence, str) or len(value_evidence) > 280):
        raise ValueError("The value evidence note must be text up to 280 characters.")
    value_evidence = (value_evidence or "").strip() or None
    value = assess_upgrade(analysis, comparator, treatment, priority, target_hours, value_per_success)
    input_quality_review = (analysis.get("input_quality") or {}).get("review_required")
    rows = tuple([row for row in analysis.get("episodes", ()) if row.get("eligible") and row.get("assigned_arm") == arm]
                 for arm in (comparator, treatment))
    risk = _critical_risk(rows[1], max_critical_rate)
    uncertainty = None
    uncertainty_gap = None
    if (value["comparison_status"] == "randomized_assignment" and value["net_value_bounds"] is not None):
        uncertainty, uncertainty_gap = _net_uncertainty(rows, analysis["analysis_config"], priority,
                                                        value["target_hours"], value_per_success)
    loss_scenario = None
    if additional_loss_per_1000 is not None:
        loss_scenario = assess_error_loss_scenario(value, additional_loss_per_1000)
        bounds = [amount - additional_loss_per_1000 / 1000 for amount in uncertainty["bounds"]] if uncertainty else None
        if bounds is not None and not all(map(isfinite, bounds)):
            raise ValueError("The assumed additional loss exceeds the supported calculation range.")
        loss_scenario["sampling_net_value_bounds"] = bounds
    action, reason = _decision(value, risk, uncertainty, value_basis, value_evidence, input_quality_review, loss_scenario)
    title, next_step, suggested_reviewer, reconsider_when = NEXT_ACTIONS[action]
    failure_reviews, unclassified_failures = _failure_reviews(rows[1])
    return {
        "schema_version": "1.0", "source_run_id": value["source_run_id"],
        "dataset_origin": analysis.get("data_readiness", {}).get("dataset_origin", "unconfirmed"),
        "action": action, "title": title, "reason": reason, "next_step": next_step,
        "suggested_reviewer": suggested_reviewer, "reconsider_when": reconsider_when,
        "value_basis": value_basis, "value_evidence": value_evidence, "value_assessment": value,
        "critical_check": risk, "net_uncertainty": uncertainty, "uncertainty_gap": uncertainty_gap,
        "failure_reviews": failure_reviews, "unclassified_failure_episode_ids": unclassified_failures,
        "downstream_loss_scenario": loss_scenario,
        "scope": "Decision support for human review of the evaluated workflow and policies.",
        **({"input_quality_review": input_quality_review} if input_quality_review is not None else {}),
    }
