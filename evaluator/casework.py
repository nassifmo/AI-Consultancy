"""Verify case actions and the case lifecycle from linked operational records."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .claim_checks import _operations_route, historical_benchmark
from .exports import ExportData, reference
from .replies import _sent_run


OPEN_STATUSES = {"new", "escalated", "open", "pending_customer"}
RESOLVED_CODES = {"resolved_info_provided", "resolved_after_investigation"}
UNRESOLVED_CODES = {"customer_unreachable", "cancelled", "escalated_to_operations"}
CUSTOMER_UPDATE_PURPOSES = {"case_update", "correction"}


@dataclass
class Casework:
    evidence: dict = field(default_factory=dict)
    follow_up_required: bool | None = None
    outcome: dict | None = None
    case_ids: list[str] = field(default_factory=list)
    human_actor_ids: set[str] = field(default_factory=set)
    resolved_at: datetime | None = None


def _in_view(start: datetime, end: datetime, at: datetime | None) -> bool:
    return at is not None and start <= at <= end


def _deadline(observed: datetime, due: datetime, refs: list[str], minor_seconds: float) -> dict:
    evidence = {"observed_at": observed.isoformat(), "reference_at": due.isoformat(), "refs": refs}
    # The reviewed benchmark identifies a one-second miss as minor. Larger
    # deviations need evidence of the customer or operational consequence.
    if 0 < (observed - due).total_seconds() <= minor_seconds:
        evidence["context_impact"] = "minor"
    return evidence


def _initial_run(data: ExportData, runs: list[dict], reply: dict, sent: datetime) -> dict | None:
    return _sent_run(data, reply, sent, runs)


def _initial_actions(data, reply, runs, creation, routes, trigger, due, case_ref):
    if not reply:
        return None, set()
    sent = data.time("responses", reply.get("sent_at"))
    if sent is None or sent < trigger or reply.get("actor_type") not in {"human", "ai_agent"}:
        return None, set()

    ai_reply = reply["actor_type"] == "ai_agent"
    actor = reply.get("actor_id")
    run = _initial_run(data, runs, reply, sent) if ai_reply else None
    steps = run["steps"] if run else []
    actions = {step["tool_name"] for step in steps if step.get("success") is True and isinstance(step.get("tool_name"), str)}
    # Only a complete matched trace can show that the initial handling omitted a step.
    recorded_steps = [step.get("step_no") for step in steps]
    complete = (
        data.cutoff >= due and run is not None
        and all(data.is_complete(name) for name in ("agent_runs", "cases", "case_history"))
        and run.get("handoff_flag") is False
        and "send_message" in actions and recorded_steps == list(range(1, len(steps) + 1))
        and all(isinstance(step.get("tool_name"), str) and type(step.get("success")) is bool for step in steps)
    )
    refs = [reference("responses", reply)]
    if run is not None:
        refs.append(reference("agent_runs", run))

    observations = {}
    for criterion, events, tool in (
        ("opened_case", creation, "create_case"),
        ("routed_to_operations", routes, "escalate_case"),
    ):
        matching = [
            (when, change) for when, change in events
            if when >= trigger
            and change.get("changed_by") in ({actor, "ai_agent"} if ai_reply else {actor})
            and (not ai_reply or when <= sent or tool in actions)
            and bool(change.get("changed_by"))
        ]
        if matching:
            observations[criterion] = True
            refs.append(reference("case_history", matching[0][1]))
        elif case_ref and ai_reply and tool in actions and not events and historical_benchmark(data):
            # The CRM case corroborates the trace, but the trace has no action timestamp.
            observations[criterion] = True
            refs.append(case_ref)
        elif complete and tool not in actions:
            observations[criterion] = False
        else:
            observations[criterion] = None
    return {"steps": observations, "refs": refs}, actions


def _case_status(changes: list[tuple[datetime, dict]], closed: datetime | None) -> str | None:
    """Read the latest status, accepting a documented reopening after closure."""
    if not changes:
        return "closed" if closed else "open"
    last_time = changes[-1][0]
    latest = [change for when, change in changes if when == last_time]
    destinations = {change.get("new_value") for change in latest}
    if len(destinations) > 1:
        destinations -= {change.get("old_value") for change in latest}
    if len(destinations) != 1:
        return None
    status = next(iter(destinations))
    if status == "closed":
        return "closed" if closed == last_time else None
    if status in OPEN_STATUSES:
        if closed is None:
            return "open"
        if closed >= last_time:
            return None
        if any(when > closed and change.get("old_value") == "closed" and
               change.get("new_value") in OPEN_STATUSES for when, change in changes):
            return "open"
    return None


def review_casework(
    data: ExportData,
    enquiry: dict,
    cases: list[dict],
    histories: list[dict],
    responses: list[dict],
    runs: list[dict],
    *,
    required: bool | None,
    trigger_at: datetime | None,
    initial_reply: dict | None,
    escalation_hours: float,
    followup_hours: float,
    deadline_minor_seconds: float,
) -> Casework:
    """Reconstruct initial actions, eventual action timing and terminal status independently."""
    result = Casework(follow_up_required=False if required is False else None)
    received = data.time("enquiries", enquiry.get("received_at"))
    cutoff = data.cutoff
    if received is None or cutoff is None or received > cutoff:
        return result

    visible = []
    for case in cases:
        opened = data.time("cases", case.get("opened_at"))
        if _in_view(received, cutoff, opened):
            visible.append((opened, case))
    result.case_ids = [case["case_id"] for _, case in visible]
    visible_case_ids = set(result.case_ids)
    known_ai_actors = {row["agent_version"] for row in runs if isinstance(row.get("agent_version"), str)}
    known_ai_actors.update({None, "", "ai_agent", "system"})
    linked_changes = []
    for change in histories:
        changed = data.time("case_history", change.get("changed_at"))
        if change.get("case_id") in visible_case_ids and _in_view(received, cutoff, changed):
            if change.get("changed_by") not in known_ai_actors:
                result.human_actor_ids.add(change["changed_by"])
            linked_changes.append((changed, change))
    if required is not True or trigger_at is None:
        return result

    candidates = [(opened, case) for opened, case in visible
                  if opened >= trigger_at and case.get("reason") == "delay_investigation"]
    if len(candidates) > 1 or any(
        (row.get("enquiry_id") == enquiry.get("enquiry_id") or row.get("case_id") in visible_case_ids)
        and (data.time("cases", row.get("opened_at")) or cutoff) <= cutoff
        for row in data.conflicts.get("cases", [])
    ):
        return result

    opened, case = candidates[0] if candidates else (None, None)
    case_ref = reference("cases", case) if case is not None else None
    case_id = case["case_id"] if case is not None else None
    case_changes = sorted(
        ((when, change) for when, change in linked_changes if change.get("case_id") == case_id),
        key=lambda item: item[0],
    )
    changes = [(when, change) for when, change in case_changes if change.get("field") == "status"]
    if case is not None and any(
        row.get("case_id") == case_id and row.get("field") in {"status", "owner", "queue", "team", "routing"} and
        (data.time("case_history", row.get("changed_at")) or cutoff) <= cutoff
        for row in data.conflicts.get("case_history", [])
    ):
        return result

    due = trigger_at + timedelta(hours=escalation_hours)
    creation = [(when, change) for when, change in changes if when == opened and change.get("new_value") == "new"]
    routes = [(when, change) for when, change in case_changes
              if when >= opened and _operations_route(data, case, change)]
    initial_actions, tools = _initial_actions(data, initial_reply, runs, creation, routes, trigger_at, due, case_ref)
    if initial_actions is not None:
        result.evidence["initial_escalation"] = initial_actions
    if case is None:
        return result

    result.follow_up_required = True
    opened_ref = [case_ref]
    route = routes[0] if routes else None
    if route:
        routed_at, transition = route
        opened_ref.append(reference("case_history", transition))
        result.evidence["escalation_deadline"] = _deadline(
            routed_at, due, opened_ref, deadline_minor_seconds,
        )

    closed = data.time("cases", case.get("closed_at"))
    visible_close = closed if _in_view(opened, cutoff, closed) else None
    updates = []
    for response in responses:
        if response.get("case_id") != case_id or response.get("purpose") not in CUSTOMER_UPDATE_PURPOSES:
            continue
        sent = data.time("responses", response.get("sent_at"))
        message = response.get("message_text")
        if _in_view(opened, visible_close or cutoff, sent) and isinstance(message, str) and message.strip():
            updates.append((sent, response))
    updates.sort(key=lambda item: item[0])
    if updates:
        first_at, first_update = updates[0]
        result.evidence["follow_up_deadline"] = _deadline(
            first_at, opened + timedelta(hours=followup_hours),
            [case_ref, reference("responses", first_update)], deadline_minor_seconds,
        )

    if ((case.get("closed_at") and (closed is None or closed < opened))
            or (case.get("closure_code") and closed is None and not any(
                change.get("old_value") == "closed" and change.get("new_value") in OPEN_STATUSES
                for _, change in changes))
            or any(when < opened for when, _ in changes)
            or any(change.get("case_id") == case_id and change.get("field") == "status"
                   and data.time("case_history", change.get("changed_at")) is None for change in histories)):
        return result
    status = _case_status(changes, visible_close)
    closure = case.get("closure_code")
    routed = route is not None or historical_benchmark(data) and "escalate_case" in tools
    if status == "open" and routed:
        state = "escalated_open"
    elif status == "closed" and closure in UNRESOLVED_CODES:
        state = "closed_unresolved"
    elif status == "closed" and closure in RESOLVED_CODES and routed and updates:
        state = "resolved"
    else:
        return result

    refs = list(opened_ref)
    if changes:
        refs.append(reference("case_history", changes[-1][1]))
    if route is None and routed and initial_actions:
        refs.extend(initial_actions["refs"])
    if state == "resolved":
        refs.append(reference("responses", updates[-1][1]))
        result.resolved_at = visible_close
    result.outcome = {"state": state, "refs": list(dict.fromkeys(refs))}
    return result
