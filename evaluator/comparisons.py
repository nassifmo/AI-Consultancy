"""Estimate assigned-policy differences and document design limitations."""

from collections import Counter, defaultdict
from datetime import date
from math import fsum, isclose

import numpy as np


METRICS = {
    "verified_resolution_rate": ("percentage points", 100),
    "first_answer_accuracy": ("percentage points", 100),
    "critical_initial_failure_rate": ("percentage points", 100),
    "human_minutes_per_request": ("minutes/request", 1),
    "cost_per_request": (None, 1),
}


def cluster_weights(n_clusters, n_resamples, seed):
    return np.random.default_rng(seed).multinomial(n_clusters, np.full(n_clusters, 1 / n_clusters), size=n_resamples)


def percentile_difference(totals, weights, confidence):
    return interval_from_samples(weights @ totals, confidence)


def interval_from_samples(samples, confidence):
    usable = (samples[:, 1] > 0) & (samples[:, 3] > 0)
    values = samples[usable]
    if len(values) < 0.95 * len(samples):
        return None, len(values), "unstable_resamples"
    differences = values[:, 2] / values[:, 3] - values[:, 0] / values[:, 1]
    if np.ptp(differences) <= 1e-12:
        return None, len(values), "degenerate_resamples"
    tail = (1 - confidence) / 2
    return np.quantile(differences, [tail, 1 - tail]).tolist(), len(values), None


def _value(row, metric):
    if metric == "verified_resolution_rate":
        return int(row["outcome"]["state"] == "resolved")
    if metric == "first_answer_accuracy":
        return row.get("first_answer_correct")
    if metric == "critical_initial_failure_rate":
        return row.get("initial_failure")
    if metric == "human_minutes_per_request":
        seconds = row["active_seconds"]
        return seconds / 60 if seconds is not None else None
    return row["total_cost"]


def _estimate(metric, comparator, treatment, left, right, groups, customers, weights, config, status, currency):
    unit, scale = METRICS[metric]
    base = groups[comparator][metric]
    ai = groups[treatment][metric]
    bounds = None
    if metric == "verified_resolution_rate" and base["bounds"] and ai["bounds"]:
        bounds = [(ai["bounds"][0] - base["bounds"][1]) * scale, (ai["bounds"][1] - base["bounds"][0]) * scale]
    delta = ((ai["value"] - base["value"]) * scale
             if base["value"] is not None and ai["value"] is not None else None)
    interval = None
    resamples = 0
    reason = None
    cluster_counts = []
    totals = np.zeros((len(customers), 4))
    for index, rows in enumerate((left, right)):
        represented = set()
        for row in rows:
            value = _value(row, metric)
            if value is None:
                continue
            customer = row["customer_id"]
            represented.add(customer)
            location = customers[customer]
            totals[location, index * 2] += value * scale
            totals[location, index * 2 + 1] += 1
        cluster_counts.append(len(represented))
    if delta is None:
        reason = "missing_or_incomplete_metric"
    elif status != "randomized_assignment":
        reason = status
    elif weights is None or min(cluster_counts) < config["minimum_customers_per_arm_for_interval"]:
        reason = "too_few_assessable_customers"
    else:
        interval, resamples, reason = percentile_difference(totals, weights, config["confidence_level"])
    complete = base["coverage"] == ai["coverage"] == 1
    if metric == "verified_resolution_rate":
        complete = complete and bounds is not None and abs(bounds[1] - bounds[0]) < 1e-12
    estimates_inputs = bool(base.get("estimated_requests") or ai.get("estimated_requests"))
    return {
        "estimate": delta, "unit": unit or currency, "interval": interval, "identification_bounds": bounds,
        "status": "unavailable" if delta is None else "estimated_inputs" if estimates_inputs else "observed_difference",
        "reason": reason, "cluster_counts": cluster_counts, "valid_resamples": resamples,
        "interval_method": "pooled_customer_cluster_percentile" if interval is not None else None,
        "confidence_level": config["confidence_level"] if interval is not None else None,
        "comparator_n": base["population"], "treatment_n": ai["population"],
        "coverage": [base["coverage"], ai["coverage"]],
        "causal_interpretation": bool(complete and not estimates_inputs and interval is not None),
        "interpretation_limit": ("Unknown outcomes widen the range for underlying resolution."
                                 if metric == "verified_resolution_rate" and bounds and bounds[1] > bounds[0] + 1e-12
                                 else "The cost includes modeled allocations." if estimates_inputs
                                 else "The metric has incomplete evidence coverage." if delta is not None and not complete
                                 else None),
    }


def compare(groups, group_rows, status, config, ledger):
    output = []
    rate = ledger.get("labor_rate_per_hour")
    currency = ledger.get("currency")
    for comparator, treatment in config["comparison_pairs"]:
        left, right = group_rows[comparator], group_rows[treatment]
        customers = {customer: i for i, customer in enumerate(sorted({row["customer_id"] for row in left + right}))}
        weights = (cluster_weights(len(customers), config["bootstrap_resamples"], config["bootstrap_seed"])
                   if status == "randomized_assignment" and len(customers) >= config["minimum_customers_per_arm_for_interval"]
                   else None)
        metrics = {
            metric: _estimate(metric, comparator, treatment, left, right, groups, customers, weights,
                              config, status, currency)
            for metric in METRICS
        }
        work = metrics["human_minutes_per_request"]
        capacity = -work["estimate"] * 1000 / 60 if work["estimate"] is not None else None
        output.append({
            "comparator": comparator, "treatment": treatment,
            "status": status if left and right else "missing_comparison_arm",
            "reason": (None if status == "randomized_assignment" and left and right else
                       "An arm has no eligible roots." if not left or not right else
                       "Recorded assignment does not support a randomized comparison."),
            "comparator_n": len(left), "treatment_n": len(right), "metrics": metrics,
            "capacity_hours_per_1000": capacity,
            "capacity_resource_value_per_1000": capacity * rate if capacity is not None and rate is not None else None,
            "capacity_status": ("randomized_estimate" if work["causal_interpretation"] else
                                "descriptive" if capacity is not None else "unavailable"),
            "capacity_interval": ([-work["interval"][1] * 1000 / 60, -work["interval"][0] * 1000 / 60]
                                  if work["interval"] else None),
        })
    return output


def _randomization_limit(rollout, eligible):
    dates = [date.fromisoformat(row["assignment_at"][:10]) for row in eligible]
    start, end = min(dates), max(dates)
    schedules = {row["assigned_arm"]: {} for row in eligible}
    for record in rollout:
        arm = record["agent_version"]
        if arm not in schedules or record.get("region"):
            continue
        try:
            day = date.fromisoformat(record["date"])
        except (ValueError, TypeError):
            return "A rollout effective date is invalid."
        schedules[arm][day] = record
    documented_shares = []
    for schedule in schedules.values():
        initial_date = max((day for day in schedule if day <= start), default=None)
        if initial_date is None:
            return "Each compared policy needs a concurrent allocation record from the first eligible assignment."
        shares = set()
        effective_records = [schedule[day] for day in schedule if initial_date <= day <= end]
        for record in effective_records:
            if record["arm_assignment_rule"] != "random_by_enquiry":
                return "An active policy lacks enquiry-level random allocation during the comparison window."
            share = record.get("traffic_share")
            if share in (None, "") and len(effective_records) == 1:
                continue  # Older exports document the random allocation without a share.
            try:
                share = float(share)
            except (ValueError, TypeError):
                return "Recorded allocation changes need usable traffic shares."
            if not 0 < share <= 1:
                return "Each compared policy needs a positive, valid traffic share throughout the comparison window."
            shares.add(share)
        if len(shares) > 1:
            return "The current unadjusted comparison cannot account for changing allocation shares."
        documented_shares.extend(shares)
    total_share = fsum(documented_shares)
    if (total_share > 1 and not isclose(total_share, 1)) or (len(schedules) > 1 and 1 in documented_shares):
        return "The documented shares cannot allocate the same comparison population across these policies."
    return None


def design_diagnostics(data, episodes, unlinked_contacts):
    eligible = [row for row in episodes if row["eligible"]]
    rollout = data.tables["rollout_log"]
    methods = Counter(row["assignment_method"] for row in eligible)
    nonrandom = any(row.get("arm_assignment_rule") in {"by_region", "all_traffic"} for row in rollout)
    incomplete = any(
        row["exclusion_reasons"] and set(row["exclusion_reasons"]).intersection(
            {"missing_or_invalid_assignment", "missing_or_invalid_root", "assignment_after_handling"})
        and not set(row["exclusion_reasons"]).intersection({"out_of_scope", "outside_study_period", "incomplete_followup"})
        for row in episodes
    )
    randomization_limit = None
    if nonrandom or any(method != "randomized" for method in methods):
        status = "unsupported_design"
    elif not eligible or incomplete or unlinked_contacts or not data.is_complete("enquiries"):
        status = "incomplete_assignment"
    else:
        randomization_limit = (_randomization_limit(rollout, eligible) if data.is_complete("rollout_log")
                               else "The rollout log is unavailable or incomplete.")
        status = "unverified_randomization" if randomization_limit else "randomized_assignment"
    trends = defaultdict(lambda: {"eligible_roots": 0, "resolved": 0, "unknown": 0})
    intake_mix = Counter()
    for row in eligible:
        region = row["assignment_unit_id"] if row["assignment_method"] == "regional_rollout" else None
        month = row["received_at"][:7]
        trend = trends[month, region, row["assigned_arm"]]
        trend["eligible_roots"] += 1
        trend["resolved"] += row["outcome"]["state"] == "resolved"
        trend["unknown"] += row["outcome"]["state"] == "unknown"
        intake_mix[(month, region, row["assigned_arm"], row.get("enquiry_type"))] += 1
    return {
        "comparison_status": status, "randomization_limit": randomization_limit,
        "methods": dict(methods), "rollout_records": rollout,
        "required_for_regional_attribution": ["contemporaneous comparison regions", "credible common trends",
                                             "sufficient region-level inference", "aligned reference target population"],
        "monthly_trends": [{"month": month, "region": region, "arm": arm, **values}
                           for (month, region, arm), values in sorted(trends.items(), key=lambda item: str(item[0]))],
        "intake_mix": [{"month": month, "region": region, "arm": arm, "enquiry_type": enquiry_type, "count": count}
                       for (month, region, arm, enquiry_type), count in sorted(intake_mix.items(), key=lambda item: str(item[0]))],
    }
