"""Compare extracted reply claims against contemporaneous operational records."""

import re

from .eta_claims import ETA_MENTION
from .exports import reference


_STATUSES = {"booked", "gated_in", "loaded", "departed", "arrived", "discharged", "released", "gated_out"}
_SUBJECTS = {"vessel", "container", "shipment", "unspecified"}
_ACTIONS = {"opened_case", "routed_to_operations"}
_STATUS_TERMS = {
    "booked": "booked", "gated_in": "gated[ -]in", "loaded": "loaded", "departed": "departed",
    "arrived": "arrived", "discharged": "(?:discharged|unloaded)", "released": "released",
    "gated_out": "gated[ -]out",
}
_ARRIVAL_EVENT = re.compile(r"\b(?:arrived|docked|berthed|reached|actual arrival|arrival (?:was |is )?recorded)\b", re.IGNORECASE)
_SUBJECT_TERMS = {"vessel": r"(?:vessel|ship)", "container": "container", "shipment": r"(?:shipment|booking)"}
_OPEN_TERMS = r"(?:opened|created|raised|logged)"
_ROUTE_TERMS = r"(?:routed|assigned|escalated|forwarded|transferred)"
_ACTION_TERMS = {
    "opened_case": rf"\b{_OPEN_TERMS}\b.{{0,35}}\b(?:case|ticket)\b"
                   rf"|\b(?:case|ticket)\b.{{0,35}}\b{_OPEN_TERMS}\b",
    "routed_to_operations": rf"\b{_ROUTE_TERMS}\b.{{0,35}}\b(?:operations|ops)\b"
                            rf"|\b(?:operations|ops)\b.{{0,35}}\b{_ROUTE_TERMS}\b",
    "operations_notification": r"\b(?:notified|informed|contacted|alerted)\b.{0,35}\b(?:operations|ops)\b"
                               r"|\b(?:operations|ops)\b.{0,35}\b(?:notified|informed|contacted|alerted)\b",
}
_PORT_PHRASE = re.compile(
    r"\b(?:arrived|arrival|departed|discharged|unloaded|released|gated out)\s+(?:at|in|from)\s+([\w-]+)",
    re.IGNORECASE,
)
_NONFACT = re.compile(r"\b(?:not|never|expected to|scheduled to|will)\b|n['’]t\b", re.IGNORECASE)
_HISTORICAL = re.compile(r"\b(?:previously|earlier|originally|recorded on|on \d{1,2} \w+)\b", re.IGNORECASE)
_FIRST_PERSON = re.compile(
    r"\b(I(?:['’]ve)?|we(?:['’]ve)?)\s+(?:(?:have|has|just|now|[a-z]+ly)\s+){0,3}"
    rf"(?:{_OPEN_TERMS}|{_ROUTE_TERMS})\b",
    re.IGNORECASE,
)
_QUOTED_CASE = re.compile(r"\b(?:case|ticket)(?:\s+(?:id|number))?(?:\s+|\s*[:#]\s*)#?([\w-]*\d[\w-]*)\b", re.IGNORECASE)
_OPERATIONS = {"operations", "ops", "operations team"}


def historical_benchmark(data):
    # A rule version describes the rubric, not where the evidence came from.
    return data.metadata.get("dataset_origin") == "synthetic"


def status_terms(message):
    return {label for label, term in _STATUS_TERMS.items()
            if re.search(rf"\b{term}\b", message or "", re.IGNORECASE)}


def action_terms(message):
    return {label for label, term in _ACTION_TERMS.items() if re.search(term, message or "", re.IGNORECASE)}


def mentions_status(message):
    return bool(status_terms(message))


def mentions_action(message):
    return bool(action_terms(message))


def _finding(kind, value, quote, passed, reason, refs=(), **fields):
    verdict = "supported" if passed is True else "contradicted" if passed is False else "unknown"
    return {"kind": kind, "value": value, "quote": quote, "verdict": verdict,
            "refs": list(dict.fromkeys(refs)), "reason": reason, **fields}


def _check_status(tracking, target, claim, sent, settings):
    status, subject, quote = claim.status, claim.subject, claim.quote
    fields = {"subject": subject, "reference": claim.reference}
    if target is None or _NONFACT.search(quote):
        return _finding("status", status, quote, None, "The stated milestone could not be scoped.", **fields)
    if status_terms(quote).difference({status}):
        return _finding("status", status, quote, None, "The extracted status does not match the words in the quote.",
                        **fields)
    named_subjects = {name for name, term in _SUBJECT_TERMS.items() if re.search(rf"\b{term}\b", quote, re.IGNORECASE)}
    if len(named_subjects) == 1 and subject not in named_subjects:
        return _finding("status", status, quote, None, "The extracted subject does not match the words in the quote.",
                        **fields)
    shipment_ref = reference("shipments", target.shipment)
    identifiers = [claim.reference] if claim.reference else []
    identifiers.extend(tracking.references_in_text(quote))
    for identifier in dict.fromkeys(identifiers):
        fields["reference"] = identifier
        match = tracking.resolve(identifier)
        if match is None:
            return _finding("status", status, quote, None, "The quoted reference could not be linked.",
                            [shipment_ref], **fields)
        if (match.shipment["booking_ref"] != target.shipment["booking_ref"]
                or (target.container and match.container and match.container != target.container)):
            return _finding("status", status, quote, False, "The quote identifies different equipment or a different shipment.",
                            [shipment_ref, reference("shipments", match.shipment)], reason_code="wrong_reference", **fields)
        # A booking-only request does not establish which container the customer meant.
        if match.container and not target.container:
            return _finding("status", status, quote, None, "The request did not identify the quoted container.",
                            [shipment_ref], **fields)
    port = _PORT_PHRASE.search(quote)
    if port:
        port_code = target.shipment.get("origin" if status == "departed" else "destination") or ""
        port_name = settings.get("port_names", {}).get(port_code, "")
        permitted = {port_code.casefold()}
        if port_name:
            permitted.add(port_name.split()[0].casefold())
        if port[1].casefold() not in permitted:
            return _finding("status", status, quote, None, "The quoted location could not be matched to the tracking milestone.",
                            [shipment_ref], **fields)
    if subject == "container" and not target.container:
        return _finding("status", status, quote, None, "The request did not identify a single container.",
                        [shipment_ref], **fields)

    snapshot = tracking.snapshot(target, sent, status_subject=subject)
    refs = [shipment_ref, *snapshot.status_refs]
    if snapshot.status is None:
        return _finding("status", status, quote, None, "The matching tracking milestone is unavailable at the reply time.",
                        refs, **fields)
    if subject == "container" and status in {"arrived", "departed"}:
        return _finding("status", status, quote, None, "The available events do not establish the transport movement of this container.",
                        refs, **fields)
    passed = snapshot.status == status
    if not passed and _HISTORICAL.search(quote):
        return _finding("status", status, quote, None, "The quote describes a historical milestone.",
                        refs, **fields)
    return _finding("status", status, quote, passed,
                    f"The matching milestone recorded at the reply time was {snapshot.status}.", refs, **fields)


def _operations_route(data, case, change):
    field = (change.get("field") or "").casefold()
    value = (change.get("new_value") or "").casefold()
    destination = (change.get("destination_queue") or change.get("queue_name") or "").casefold()
    if field in {"owner", "queue", "team", "routing"} and value in _OPERATIONS:
        return True
    if field == "status" and value == "escalated":
        # The synthetic case workflow uses escalated for a delay investigation
        # routed to operations. A company export must identify the destination.
        return (destination in _OPERATIONS or
                not destination and historical_benchmark(data) and case.get("reason") == "delay_investigation")
    return False


def _source_complete(data, table):
    return (
        data.is_complete(table) and table not in data.unscoped
        and (data.metadata.get("source_completeness") is not None or historical_benchmark(data))
    )


def _check_action(data, enquiry, reply, claim, sent, cases, histories):
    action, quote = claim.action, claim.quote
    visible_ids = set(_QUOTED_CASE.findall(quote))
    if len(visible_ids) > 1:
        return _finding("action", action, quote, None, "Several case identifiers occur in the quoted action.")
    asserted_id = claim.case_id or next(iter(visible_ids), None)
    fields = {"case_id": asserted_id}
    refs = []
    terms = action_terms(quote)
    if terms and action not in terms:
        return _finding("action", action, quote, None, "The extracted action does not match the words in the quote.",
                        **fields)
    if _NONFACT.search(quote):
        return _finding("action", action, quote, None, "The text does not establish a completed action.", **fields)
    source_complete = _source_complete(data, "cases")
    if action == "routed_to_operations":
        source_complete &= _source_complete(data, "case_history")
    case_id = asserted_id or reply.get("case_id")
    if asserted_id and reply.get("case_id") and asserted_id != reply["case_id"]:
        return _finding("action", action, quote, None, "The quoted case differs from the case linked to the reply.", **fields)
    candidates = []
    possible = [case for case in cases if not case_id or case["case_id"] == case_id]
    visible_cases = {case["case_id"] for case in possible}
    for case in possible:
        if case.get("enquiry_id") != enquiry["enquiry_id"] and reply.get("case_id") != case["case_id"]:
            source_complete = False
            continue
        opened = data.time("cases", case["opened_at"])
        if opened is None:
            source_complete = False
        elif opened <= sent:
            candidates.append((opened, case))
    for row in data.conflicts.get("cases", ()):
        if (row.get("enquiry_id") == enquiry["enquiry_id"] or row.get("case_id") in visible_cases
                or (case_id and row.get("case_id") == case_id)):
            at = data.time("cases", row.get("opened_at"))
            if at is None or at <= sent:
                return _finding("action", action, quote, None, "The case records conflict at the reply time.",
                                [reference("cases", row)], **fields)
    if len(candidates) > 1:
        return _finding("action", action, quote, None, "Several cases could match the claim.",
                        [reference("cases", case) for _, case in candidates], **fields)
    if not candidates:
        return _finding("action", action, quote, False if source_complete else None,
                        "No linked case was recorded by the time of the reply."
                        if source_complete else "Case coverage is insufficient to check the action.", **fields)

    opened, case = candidates[0]
    started = data.time("enquiries", enquiry.get("received_at"))
    refs = [reference("cases", case)]
    visible_history = []
    history_uncertain = False
    for change in histories:
        if change["case_id"] != case["case_id"]:
            continue
        changed = data.time("case_history", change.get("changed_at"))
        if changed is None or changed < opened:
            history_uncertain = True
        elif changed <= sent:
            visible_history.append((changed, change))
    for change in data.conflicts.get("case_history", ()):
        if change.get("case_id") == case["case_id"]:
            changed = data.time("case_history", change.get("changed_at"))
            if changed is None or changed <= sent:
                history_uncertain = True
                refs.append(reference("case_history", change))

    if started is None or opened < started:
        return _finding("action", action, quote, None, "The case creation could not be placed within this enquiry.",
                        refs, **fields)
    first_person = _FIRST_PERSON.search(quote)
    if action == "opened_case":
        if not first_person:
            return _finding("action", action, quote, True, "The linked case was opened by the reply time.",
                            refs, **fields)
        qualifying = [change for changed, change in visible_history
                      if changed == opened and change.get("field") == "status" and change.get("new_value") == "new"]
    else:
        qualifying = [change for _, change in visible_history if _operations_route(data, case, change)]
        possible_escalation = any(change.get("field") == "status" and change.get("new_value") == "escalated"
                                  for _, change in visible_history)
        if not qualifying and possible_escalation:
            return _finding("action", action, quote, None, "An escalation is recorded but its destination is unverified.",
                            refs, **fields)
        if not qualifying and not history_uncertain:
            return _finding("action", action, quote, False if source_complete else None,
                            "No operations routing was recorded by the time of the reply."
                            if source_complete else "Routing history coverage is insufficient to check the action.",
                            refs, **fields)
    refs.extend(reference("case_history", change) for change in qualifying)
    if history_uncertain:
        return _finding("action", action, quote, None, "The action history is inconsistent or incomplete.",
                        refs, **fields)
    if not first_person:
        return _finding("action", action, quote, True, "The linked case was routed to operations by the reply time.",
                        refs, **fields)
    actors = {change["changed_by"] for change in qualifying if change.get("changed_by") not in {None, "", "system"}}
    if action == "opened_case" and case.get("opened_by") not in {None, "", "system"}:
        actors.add(case["opened_by"])
    expected = {reply["actor_id"]} if reply.get("actor_id") else set()
    if historical_benchmark(data) and reply.get("actor_type") == "ai_agent":
        expected.add("ai_agent")
    if not actors or not expected:
        return _finding("action", action, quote, None, "The record does not identify who performed the claimed action.",
                        refs, **fields)
    if actors.isdisjoint(expected):
        if first_person[1].lower().startswith("we"):
            return _finding("action", action, quote, None, "The record cannot link the team action to the reply sender.",
                            refs, **fields)
        return _finding("action", action, quote, False, "The recorded actor does not match the reply sender.",
                        refs, **fields)
    if not actors.issubset(expected):
        return _finding("action", action, quote, None, "The records disagree about who performed the action.",
                        refs, **fields)
    return _finding("action", action, quote, True, "The case history corroborates the sender's action by the reply time.",
                    refs, **fields)


def review_claims(reader, data, tracking, target, enquiry, reply, sent, settings, cases, histories):
    message = reply.get("message_text") or ""
    if not message.strip():
        return {"state": "unavailable", "findings": []}
    try:
        extracted = reader(message)
        state = extracted.state
        statuses = tuple(extracted.status_claims)
        actions = tuple(extracted.action_claims)
    except Exception:
        # The reader can be an external model. Unavailability is evidence loss.
        return {"state": "unavailable", "findings": []}
    if state not in {"extracted", "needs_review"}:
        return {"state": "unavailable", "findings": []}
    findings = []
    for claim in statuses:
        if (claim.status not in _STATUSES or claim.subject not in _SUBJECTS or not claim.quote
                or message.count(claim.quote) != 1 or (claim.reference and claim.reference not in claim.quote)):
            state = "needs_review"
            continue
        if claim.status == "arrived" and ETA_MENTION.search(claim.quote) and not _ARRIVAL_EVENT.search(claim.quote):
            # An explicitly identified estimate cannot by itself assert that arrival occurred.
            continue
        if _negated_prefix(message, claim.quote):
            state = "needs_review"
            continue
        findings.append(_check_status(tracking, target, claim, sent, settings))
    for claim in actions:
        if (claim.action not in _ACTIONS or not claim.quote or message.count(claim.quote) != 1
                or (claim.case_id and claim.case_id not in claim.quote)):
            state = "needs_review"
            continue
        if _negated_prefix(message, claim.quote):
            state = "needs_review"
            continue
        findings.append(_check_action(data, enquiry, reply, claim, sent, cases, histories))
    return {"state": state, "findings": findings}


def _negated_prefix(message, quote):
    prefix = re.split(r"[.!?;\n]", message.partition(quote)[0])[-1]
    return bool(_NONFACT.search(prefix))
