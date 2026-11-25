"""Verify where an unanswered ETA enquiry was routed by the review cutoff."""

import re

from .claim_checks import _operations_route, mentions_action
from .exports import reference


_SOURCES = ("agent_runs", "cases", "case_history")
_HUMAN_QUEUES = {"human", "human review", "human support"}
_QUEUED = {"queued", "routed", "transferred", "assigned"}
_HANDOFF_WORDING = re.compile(
    r"\b(?:handoff|hand[ -]?off|human (?:agent|review|support)|"
    r"transfer(?:red)? (?:you|this|your request)|escalat(?:e|ed|ion)|open (?:a |the )?(?:case|ticket))\b",
    re.IGNORECASE,
)


def _key(value):
    return value.strip().casefold().replace("_", " ").replace("-", " ") if isinstance(value, str) else ""


def _result(state, refs, reason, pending=None):
    return {"state": state, "refs": list(dict.fromkeys(refs)), "reason": reason, "pending": pending}


def _route_to_human(data, case, change):
    if _operations_route(data, case, change):
        return True
    field, value = _key(change.get("field")), _key(change.get("new_value"))
    queue = _key(change.get("destination_queue") or change.get("queue_name"))
    return (
        field in {"owner", "queue", "team", "routing"} and value in _HUMAN_QUEUES
        or field == "status" and value == "escalated" and queue in _HUMAN_QUEUES
    )


def _case_pending(data, case, opened_at, histories):
    from .casework import _case_status

    closed_at = data.time("cases", case.get("closed_at"))
    if case.get("closed_at") and (closed_at is None or closed_at < opened_at):
        return None
    if any(row.get("field") == "status" and at is None for at, row in histories):
        return None
    visible_close = closed_at if closed_at and closed_at <= data.cutoff else None
    status_rows = sorted(
        ((at, row) for at, row in histories
         if at is not None and opened_at <= at <= data.cutoff and row.get("field") == "status"),
        key=lambda item: item[0],
    )
    status = _case_status(status_rows, visible_close)
    if status == "open" and not _closure_covered(data):
        return None
    return None if status is None else status == "open"


def _closure_covered(data):
    return all(data.is_complete(table) and table not in data.unscoped for table in ("cases", "case_history"))


def review_eta_handoff(data, enquiry, reply, cases, histories, runs):
    """Return source-linked routing and whether the recorded handoff remains pending."""
    from .replies import _sent_run

    enquiry_id = enquiry["enquiry_id"]
    refs = [reference("enquiries", enquiry), reference("responses", reply)]
    received = data.time("enquiries", enquiry.get("received_at"))
    sent = data.time("responses", reply.get("sent_at"))
    cutoff = data.cutoff
    if received is None or sent is None or cutoff is None or not received <= sent <= cutoff:
        return _result("unknown", refs, "The handling window could not be verified.")

    linked = {case["case_id"]: case for case in cases}
    related_case_ids = set(linked) | {reply.get("case_id")}
    conflicts = [
        (table, row) for table, link, timestamp in (
            ("agent_runs", lambda row: row.get("enquiry_id") == enquiry_id, "ended_at"),
            ("cases", lambda row: row.get("enquiry_id") == enquiry_id
             or row.get("case_id") in related_case_ids, "opened_at"),
            ("case_history", lambda row: row.get("case_id") in related_case_ids, "changed_at"),
        )
        for row in data.conflicts.get(table, ())
        if link(row) and (data.time(table, row.get(timestamp)) or cutoff) <= cutoff
    ]
    if conflicts:
        refs.extend(reference(table, row) for table, row in conflicts)
        return _result("unknown", refs, "The linked handoff records conflict.")

    case_states = {}
    routed = []
    for case_id, case in linked.items():
        opened_at = data.time("cases", case.get("opened_at"))
        if opened_at is not None and opened_at > cutoff:
            continue
        refs.append(reference("cases", case))
        if opened_at is None:
            case_states[case_id] = None
            continue
        history = [
            (data.time("case_history", row.get("changed_at")), row)
            for row in histories if row.get("case_id") == case_id
        ]
        case_states[case_id] = _case_pending(data, case, opened_at, history)
        routes = [
            reference("case_history", row) for at, row in history
            if at is not None and max(received, opened_at) <= at <= cutoff and _route_to_human(data, case, row)
        ]
        if routes:
            refs.extend(routes)
            refs.extend(reference("case_history", row) for at, row in history
                        if at is not None and opened_at <= at <= cutoff and row.get("field") == "status")
            routed.append(case_states[case_id])
    if routed:
        pending = True if True in routed else None if None in routed else False
        return _result("verified", refs, "A linked CRM record shows routing for human handling.", pending)

    visible_runs = [
        row for row in runs if row.get("enquiry_id") == enquiry_id
        and (ended := data.time("agent_runs", row.get("ended_at"))) is not None
        and received <= ended <= cutoff
    ]
    refs.extend(reference("agent_runs", row) for row in visible_runs)
    matched_run = _sent_run(data, reply, sent, visible_runs)
    if matched_run is not None and any(
        step.get("tool_name") == "handoff_to_human" and step.get("success") is True
        and _key(step.get("tool_output")) in _QUEUED for step in matched_run["steps"]
    ):
        pending = case_states.get(reply.get("case_id"), True if not case_states and _closure_covered(data) else None)
        return _result("verified", refs, "The linked transfer record confirms queuing for a human.", pending)

    message = reply.get("message_text") or ""
    possible_route = any(
        row.get("handoff_flag") is True or row.get("self_reported_outcome") == "handed_off" or any(
            step.get("tool_name") in {"handoff_to_human", "escalate_case"}
            and step.get("success") is not False
            for step in row["steps"]
        ) for row in visible_runs
    )
    if case_states or reply.get("case_id") or possible_route or _HANDOFF_WORDING.search(message) or mentions_action(message):
        return _result("unknown", refs, "The records suggest possible review without establishing a handoff.")
    if any(row.get("enquiry_id") == enquiry_id and row["case_id"] not in linked
           and (data.time("cases", row.get("opened_at")) or cutoff) <= cutoff
           for row in data.tables.get("cases", ())):
        return _result("unknown", refs, "A possible case could not be linked to this enquiry.")
    for table, link, timestamp in (
        ("agent_runs", "enquiry_id", "ended_at"), ("cases", "enquiry_id", "opened_at"),
    ):
        if any(row.get(link) == enquiry_id and data.time(table, row.get(timestamp)) is None
               for row in data.tables.get(table, ())):
            return _result("unknown", refs, "A linked record has an unverified timestamp.")
    if any(table in data.unscoped or not data.is_complete(table) for table in _SOURCES):
        return _result("unknown", refs, "The handoff sources do not establish complete coverage.")
    return _result("not_recorded", refs, "No human handoff appears in the linked run, case or routing records.")
