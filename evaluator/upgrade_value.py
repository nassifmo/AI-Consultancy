"""Compare scoped costs with a chosen service outcome and an assumed value."""

from math import isclose, isfinite
from sys import float_info

from .cohorts import ARMS
from .metrics import STATES


PRIORITIES = (
    "verified_resolution",
    "first_answer_accuracy",
    "verified_resolution_within_target",
)


def _nonnegative_number(value):
    return type(value) in (int, float) and 0 <= value <= float_info.max


def _success(episode, priority, target_seconds):
    if priority == "first_answer_accuracy":
        correct = episode.get("first_answer_correct")
        return correct if isinstance(correct, bool) else None
    state = episode.get("outcome", {}).get("state")
    if state not in STATES or state == "unknown":
        return None
    if state != "resolved":
        return False
    if priority == "verified_resolution_within_target":
        elapsed = episode.get("elapsed_resolution_seconds")
        return elapsed <= target_seconds if _nonnegative_number(elapsed) else None
    return True


def _arm_metric(rows, priority, target_seconds):
    outcomes = [_success(row, priority, target_seconds) for row in rows]
    count = len(outcomes)
    successes = outcomes.count(True)
    unknown = outcomes.count(None)
    verified_rate = successes / count if count else None
    return {
        "eligible": count,
        "successes": successes,
        "failures": count - successes - unknown,
        "unknown": unknown,
        "verified_rate": verified_rate,
        "outcome_bounds": [verified_rate, (successes + unknown) / count] if count else None,
    }


def _full_cost(analysis, arm, count, currency):
    metric = analysis.get("group_metrics", {}).get(arm, {}).get("cost_per_request", {})
    comparable = (currency and metric.get("unit") == currency and count > 0
                  and metric.get("denominator") == count and metric.get("coverage") == 1
                  and _nonnegative_number(metric.get("value")))
    return metric.get("value") if comparable else None, bool(metric.get("estimated_requests"))


def _safe_ratio(numerator, denominator):
    result = numerator / denominator
    return result if isfinite(result) else None


def _point_dominance(success_delta, cost_delta):
    if success_delta == cost_delta == 0:
        return "equal"
    if success_delta >= 0 and cost_delta <= 0:
        return "treatment"
    if success_delta <= 0 and cost_delta >= 0:
        return "comparator"
    return "tradeoff"


def _net_status(bounds):
    lower, upper = bounds
    if isclose(lower, 0, abs_tol=1e-9) and isclose(upper, 0, abs_tol=1e-9):
        return "modeled_break_even"
    if lower > 0 and not isclose(lower, 0, abs_tol=1e-9):
        return "modeled_benefit_exceeds_cost"
    if upper < 0 and not isclose(upper, 0, abs_tol=1e-9):
        return "modeled_cost_exceeds_benefit"
    return "inconclusive_missing_evidence"


def assess_upgrade(analysis, comparator, treatment, priority, target_hours=None, value_per_success=None):
    """Return a conditional comparison of cost and the selected service outcome.

    All eligible requests remain in the denominator. Bounds vary the status of
    requests with missing evidence. They do not capture sampling uncertainty.
    """
    if comparator not in ARMS or treatment not in ARMS or comparator == treatment:
        raise ValueError("Choose two different handling groups.")
    if priority not in PRIORITIES:
        raise ValueError("Choose a supported service priority.")
    if value_per_success is not None and not _nonnegative_number(value_per_success):
        raise ValueError("The assumed value per success must be a finite nonnegative number.")
    if priority == "verified_resolution_within_target":
        followup_days = analysis.get("analysis_config", {}).get("comparison_followup_days")
        if (not _nonnegative_number(followup_days) or not _nonnegative_number(target_hours)
                or not 0 < target_hours <= followup_days * 24):
            raise ValueError("Choose a positive time target within the comparison follow-up window.")
    else:
        target_hours = None
    target_seconds = target_hours * 3600 if target_hours is not None else None

    currency = analysis.get("cost_ledger", {}).get("currency")
    metrics = {}
    costs = {}
    estimated_costs = False
    for arm in (comparator, treatment):
        rows = [row for row in analysis.get("episodes", ()) if row.get("eligible") and row.get("assigned_arm") == arm]
        metrics[arm] = _arm_metric(rows, priority, target_seconds)
        costs[arm], modeled = _full_cost(analysis, arm, len(rows), currency)
        estimated_costs = estimated_costs or modeled

    result = {
        "source_run_id": analysis.get("run_provenance", {}).get("run_id"),
        "priority": priority,
        "comparator": comparator,
        "treatment": treatment,
        "target_hours": target_hours,
        "value_per_success": value_per_success,
        "currency": currency,
        "metrics": metrics,
        "costs_per_request": costs,
        "estimated_costs": estimated_costs,
        "comparison_status": analysis.get("data_readiness", {}).get("comparison_status"),
        "success_difference": None,
        "success_difference_bounds": None,
        "incremental_cost_per_request": None,
        "point_dominance": None,
        "break_even_value_per_success": None,
        "break_even_value_bounds": None,
        "max_value_per_lost_success": None,
        "net_value_per_request": None,
        "net_value_bounds": None,
        "status": "missing_outcomes",
    }
    if costs[comparator] is not None and costs[treatment] is not None:
        result["incremental_cost_per_request"] = costs[treatment] - costs[comparator]
    before, after = metrics[comparator], metrics[treatment]
    if not before["eligible"] or not after["eligible"]:
        return result
    success_delta = after["verified_rate"] - before["verified_rate"]
    lower = after["outcome_bounds"][0] - before["outcome_bounds"][1]
    upper = after["outcome_bounds"][1] - before["outcome_bounds"][0]
    result["success_difference"] = success_delta
    result["success_difference_bounds"] = [lower, upper]

    cost_delta = result["incremental_cost_per_request"]
    if cost_delta is None:
        result["status"] = "cost_unavailable"
        return result
    result["point_dominance"] = _point_dominance(success_delta, cost_delta)
    if cost_delta > 0 and success_delta > 0:
        result["break_even_value_per_success"] = _safe_ratio(cost_delta, success_delta)
    if cost_delta > 0 and upper > 0:
        result["break_even_value_bounds"] = [
            _safe_ratio(cost_delta, upper), _safe_ratio(cost_delta, lower) if lower > 0 else None,
        ]
    if cost_delta < 0 and success_delta < 0:
        result["max_value_per_lost_success"] = _safe_ratio(-cost_delta, -success_delta)

    result["status"] = "value_unspecified"
    if value_per_success is not None:
        net_value = value_per_success * success_delta - cost_delta
        net_bounds = [value_per_success * delta - cost_delta for delta in (lower, upper)]
        if not all(isfinite(number) for number in [net_value, *net_bounds]):
            raise ValueError("The assumed value exceeds the supported calculation range.")
        result["net_value_per_request"] = net_value
        result["net_value_bounds"] = net_bounds
        result["status"] = _net_status(net_bounds)
    return result
