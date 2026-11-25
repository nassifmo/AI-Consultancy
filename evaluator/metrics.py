"""Measure service and cost outcomes on the fixed eligible population."""

from .cohorts import ARMS


STATES = ("resolved", "unknown", "escalated_open", "awaiting_customer", "failed", "closed_unresolved")


def _metric(numerator, denominator, population, unit, episodes, *, require_complete=False, scale=1):
    value = numerator / denominator * scale if denominator and (not require_complete or denominator == population) else None
    return {
        "value": value, "unit": unit, "numerator": numerator,
        "denominator": denominator, "population": population,
        "coverage": denominator / population if population else None,
        "reason": ("no_assessable_records" if not denominator else "incomplete_coverage") if value is None else None,
        "episode_ids": [episode["root_enquiry_id"] for episode in episodes],
    }


def _flag(episodes, name, *, all_roots=False):
    assessable = [row for row in episodes if row.get(name) is not None]
    count = sum(row[name] is True for row in assessable)
    result = _metric(count, len(episodes) if all_roots else len(assessable), len(episodes), "rate", assessable)
    result["assessable"] = len(assessable)
    result["unknown"] = len(episodes) - len(assessable)
    result["coverage"] = len(assessable) / len(episodes) if episodes else None
    return result


def _mean(episodes, name, unit, *, complete=False, scale=1):
    assessed = [row for row in episodes if row.get(name) is not None]
    return _metric(sum(row[name] for row in assessed), len(assessed), len(episodes), unit, assessed,
                   require_complete=complete, scale=scale)


def _actions(episodes):
    applicable = assessed = passed = 0
    contributors = []
    unknown_applicability = 0
    for episode in episodes:
        checks = episode["criteria"]
        for name in ("escalation_deadline", "follow_up_deadline"):
            grade = checks.get(name, {})
            if not grade or grade.get("status") == "not_applicable":
                continue
            if grade.get("reason", "").startswith("Applicability is unverified"):
                unknown_applicability += 1
                continue
            applicable += 1
            if type(grade.get("on_time")) is bool:
                assessed += 1
                passed += int(grade["on_time"])
                contributors.append(episode)
        initial = checks.get("initial_escalation", {})
        steps = initial.get("steps", {})
        if initial.get("reason", "").startswith("Applicability is unverified"):
            unknown_applicability += len(steps)
            continue
        for flag in steps.values():
            applicable += 1
            if flag in {"met", "unmet"}:
                assessed += 1
                passed += int(flag == "met")
                contributors.append(episode)
    result = _metric(passed, assessed, applicable, "rate", contributors)
    result["episode_ids"] = sorted(set(result["episode_ids"]))
    result["unknown_applicability"] = unknown_applicability
    return result


def summarize_group(rows, currency):
    rows = sorted(rows, key=lambda row: row["root_enquiry_id"])
    count = len(rows)
    resolved = [row for row in rows if row["outcome"]["state"] == "resolved"]
    output = {"n": count}
    for state in STATES:
        name = "verified_resolution_rate" if state == "resolved" else f"{state}_rate"
        output[name] = _metric(sum(row["outcome"]["state"] == state for row in rows), count, count, "rate", rows)
    output["verified_resolution_rate"]["bounds"] = (
        [len(resolved) / count, (len(resolved) + output["unknown_rate"]["numerator"]) / count] if count else None
    )
    output["verified_resolution_rate"]["coverage"] = (
        (count - output["unknown_rate"]["numerator"]) / count if count else None
    )
    output["first_answer_accuracy"] = _flag(rows, "first_answer_correct")
    output["critical_initial_failure_rate"] = _flag(rows, "initial_failure")
    output["human_recovery_rate"] = _flag(rows, "human_recovery", all_roots=True)
    output["repeat_contact_rate"] = _flag(rows, "repeat_contact")
    output["required_action_compliance"] = _actions(rows)
    ai_only = sum(row["ai_only_handling"] is True for row in resolved)
    ai_only_unknown = sum(row["ai_only_handling"] is None for row in resolved) + sum(
        row["outcome"]["state"] == "unknown" and row["ai_only_handling"] is not False for row in rows
    )
    output["ai_only_resolution_rate"] = {
        **_metric(ai_only, count, count, "rate", rows),
        "unknown": ai_only_unknown,
        "coverage": (count - ai_only_unknown) / count if count else None,
        "bounds": [ai_only / count, (ai_only + ai_only_unknown) / count] if count else None,
    }
    output["human_minutes_per_request"] = _mean(rows, "active_seconds", "minutes/request", complete=True, scale=1 / 60)
    output["human_minutes_per_request_assessable"] = _mean(rows, "active_seconds", "minutes/request", scale=1 / 60)
    output["documented_human_minutes"] = _metric(
        sum((row["active_seconds"] if row["active_seconds"] is not None else row["recorded_seconds"]) or 0 for row in rows) / 60,
        1, 1, "minutes", rows,
    )
    documented = output["documented_human_minutes"]
    documented["denominator"] = None
    documented["population"] = count
    documented["coverage"] = (sum(row["active_seconds"] is not None or row["recorded_seconds"] is not None
                                 for row in rows) / count if count else None)
    if not documented["coverage"]:
        documented.update(value=None, reason="no_assessable_records")
    output["mean_elapsed_resolution_minutes"] = _mean(resolved, "elapsed_resolution_seconds", "minutes", scale=1 / 60)
    output["cost_per_request"] = _mean(rows, "total_cost", currency, complete=True)
    output["cost_per_verified_resolution"] = _metric(
        sum(row["total_cost"] for row in rows if row["total_cost"] is not None),
        len(resolved), len(resolved), currency, rows,
    )
    if any(row["total_cost"] is None for row in rows):
        output["cost_per_verified_resolution"].update(value=None, reason="incomplete_cost_coverage")
    output["cost_per_verified_resolution"]["coverage"] = output["cost_per_request"]["coverage"]
    output["cost_per_request"]["estimated_requests"] = sum(row.get("cost_estimated") is True for row in rows)
    output["cost_per_verified_resolution"]["estimated_requests"] = output["cost_per_request"]["estimated_requests"]
    return output


def summarize(episodes, currency):
    groups = {arm: [] for arm in ARMS}
    for row in episodes:
        if row["eligible"]:
            groups[row["assigned_arm"]].append(row)
    return {arm: summarize_group(rows, currency) for arm, rows in groups.items()}, groups
