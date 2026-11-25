"""Check what was sent against source records visible at that time."""

from dataclasses import asdict, dataclass, field
from datetime import datetime
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .claim_checks import action_terms, historical_benchmark, mentions_action, mentions_status, review_claims, status_terms
from .eta_claims import conflicting_eta_passage, quoted_eta, requested_eta_response, sent_eta
from .exports import reference


ETA_REQUEST = re.compile(r"\beta\b|arrival (?:estimate|time)|when .*arriv|(?:what time|expected to) .*arriv", re.IGNORECASE)
ETA_SUBJECT = r"(?:ETA|arrival (?:estimate|time|date)|estimated (?:time|date) of arrival)"
EXPLICIT_ETA_REQUEST = re.compile(
    rf"^\s*(?:(?:current|new|revised|latest)\s+)?{ETA_SUBJECT}\s*\??\s*$"
    rf"|\b(?:what(?:['’]s| is| will be)|provide|tell (?:me|us)|send|give|check|confirm|share|need)\b[^.!?]{{0,40}}\b{ETA_SUBJECT}\b"
    r"|(?:^|[.!?]\s+|\b(?:confirm|tell me|check)\s+)(?:when|what (?:date|time))\b[^.!?]{0,75}\b(?:arriv(?:e|al|ing)|reach|dock)\b",
    re.IGNORECASE,
)
STATUS_REQUEST = re.compile(r"\b(status|unload(?:ed|ing)?|discharg(?:e|ed)|arrived|departed)\b|where is", re.IGNORECASE)
DISCHARGE_REQUEST = re.compile(r"\b(unload(?:ed|ing)?|discharg(?:e|ed))\b", re.IGNORECASE)
COORDINATION_REQUEST = re.compile(r"\bwhich\b.{0,45}\bteam\b.{0,40}\bnotify\b", re.IGNORECASE)
LOCAL_CUTOFF = re.compile(r"\beta of (\d{1,2}):(\d{2}) local time or earlier\b", re.IGNORECASE)
MONITORING_DECISION = re.compile(r"\bnotify the (morning|afternoon)(?: monitoring)? team\b", re.IGNORECASE)
TIMING_CONSTRAINT = re.compile(r"\b(pickup|deadline|cutoff|appointment|before|after|by \d)\b", re.IGNORECASE)
REFERENCE_QUALIFIER = re.compile(
    r"\b(?:not|ignore|disregard|previously|earlier|mistakenly|incorrectly)\b", re.IGNORECASE,
)


@dataclass
class ReplyReview:
    reply: dict
    verdict: str = "unknown"
    matches_record: bool | None = None
    evidence: dict = field(default_factory=dict)
    eta_in_scope: bool | None = None
    status_in_scope: bool | None = None
    action_in_scope: bool | None = None
    requested_eta: dict | None = None
    eta_interpretation: dict | None = None
    reply_claims: dict | None = None
    refs: list[str] = field(default_factory=list)
    reason: str | None = None


def coordination_request(enquiry: dict) -> bool:
    return enquiry.get("request_profile") == "arrival_coordination" or bool(
        COORDINATION_REQUEST.search(enquiry.get("customer_message") or "")
    )


def explicit_eta_request(enquiry: dict) -> bool:
    return coordination_request(enquiry) or bool(EXPLICIT_ETA_REQUEST.search((enquiry.get("customer_message") or "").strip()))


def interpret_exchange(reader, question, message):
    interpret = getattr(reader, "interpret_eta", None)
    if not callable(interpret) or not question.strip() or not message.strip():
        return None
    return interpret(question, message)


def _apply_eta_interpretation(reading, known, explicit):
    ai_eta_request = (reading is not None and reading.state == "classified" and reading.intent == "arrival_time")
    if not explicit and not ai_eta_request:
        return None
    state, basis = known, "rules" if explicit else "ai"
    if known == "unknown" and ai_eta_request and reading.response != "unknown":
        state, basis = reading.response, "ai"
    return {"state": state, "basis": basis}


def _successful_steps(run: dict, tool: str) -> list[dict]:
    steps = run.get("steps")
    if not isinstance(steps, list):
        return []
    return [s for s in steps if isinstance(s, dict) and s.get("tool_name") == tool and s.get("success") is True]


def _sent_run(data, reply: dict, sent: datetime, runs: list[dict]) -> dict | None:
    if reply.get("actor_type") != "ai_agent" or not reply.get("actor_id"):
        return None
    matched = []
    for run in runs:
        if run.get("agent_version") != reply["actor_id"] or run.get("response_text") != reply.get("message_text"):
            continue
        if not _successful_steps(run, "send_message"):
            continue
        started = data.time("agent_runs", run.get("started_at"))
        ended = data.time("agent_runs", run.get("ended_at"))
        if started is None or ended is None or not started <= min(sent, ended):
            continue
        explicit_link = bool(reply.get("run_id") or run.get("response_id"))
        if reply.get("run_id") and reply["run_id"] != run.get("run_id"):
            continue
        if run.get("response_id") and run["response_id"] != reply.get("response_id"):
            continue
        if explicit_link or ended == sent:
            matched.append(run)
    return matched[0] if len(matched) == 1 else None


def _identity(tracking, target, reply: dict, run: dict | None, text_targets) -> bool | None:
    if target is None:
        return None
    sent_booking = tracking.resolve(reply.get("shipment_reference"))
    sent_container = tracking.resolve(reply.get("container_reference"))
    tool_targets = []
    if run is not None:
        tool_targets = [
            tracking.resolve(step.get("tool_input")) for step in _successful_steps(run, "get_tracking_status")
        ]
    sent_targets = [match for match in (sent_booking, sent_container) if match is not None]
    # A conclusively wrong outbound reference matters even if a separate lookup was correct.
    if any(match.shipment["booking_ref"] != target.shipment["booking_ref"] for match in sent_targets):
        return False
    if target.container and any(match.container and match.container != target.container for match in sent_targets):
        return False
    if (reply.get("shipment_reference") and sent_booking is None) or (reply.get("container_reference") and sent_container is None):
        return None
    text_matches = [
        None if match is None else (
            match.shipment["booking_ref"] == target.shipment["booking_ref"]
            and (not target.container or not match.container or match.container == target.container)
        )
        for match in text_targets
    ]
    if False in text_matches:
        return (False if all(matches is False for matches in text_matches)
                and not REFERENCE_QUALIFIER.search(reply.get("message_text") or "") else None)
    if None in text_matches:
        return None
    sent_targets.extend(text_targets)
    tool_identities = {
        (match.shipment["booking_ref"], match.container) for match in tool_targets if match is not None
    }
    if len(tool_identities) > 1:
        return None
    if tool_identities:
        booking, container = next(iter(tool_identities))
        if booking != target.shipment["booking_ref"] or (target.container and container and container != target.container):
            return False
    if any(match is None for match in tool_targets):
        return None
    if target.container and reply.get("container_reference"):
        return sent_container is not None and sent_container.container == target.container
    if target.container and any(match.container == target.container for match in sent_targets + [m for m in tool_targets if m]):
        return True
    if target.container and len(str(target.shipment.get("container_refs") or "").split(";")) > 1:
        return None
    return True if sent_targets or tool_identities else None


def _cutoff(data, enquiry: dict, at: datetime, port: str, settings: dict) -> datetime | None:
    explicit = enquiry.get("decision_cutoff_at")
    if explicit:
        return data.time("enquiries", explicit)
    question = enquiry.get("customer_message") or ""
    clock = LOCAL_CUTOFF.search(question)
    zone_name = settings["port_timezones"].get(port)
    if clock is None or not zone_name:
        return None
    try:
        zone = ZoneInfo(zone_name)
        local = at.astimezone(zone)
        # The requested local date has to be explicit. Never infer it from the answer.
        dates = (f"{local.day} {local:%B}", f"{local.day:02d} {local:%B}")
        if not any(re.search(r"\b" + re.escape(date) + r"\b", question, re.IGNORECASE) for date in dates):
            return None
        time = local.replace(hour=int(clock[1]), minute=int(clock[2]), second=0, microsecond=0)
        if time.replace(fold=0).utcoffset() != time.replace(fold=1).utcoffset():
            return None
        return time
    except (ValueError, ZoneInfoNotFoundError):
        return None


def _status_check(target, enquiry: dict, reply: dict, snapshot, settings: dict) -> bool | None:
    status = reply.get("claimed_status")
    if not status:
        destination = settings.get("port_names", {}).get(target.shipment.get("destination"))
        if destination and re.search(
            rf"\bno recorded {re.escape(destination)} arrival yet\b", reply.get("message_text") or "", re.IGNORECASE,
        ):
            if snapshot.eta_kind in {"EST", "PLN"}:
                return True
            if snapshot.eta_kind == "ACT":
                return False
    if not snapshot.status:
        return None
    if not status:
        return None
    # A container status has to refer to the requested equipment. A booking-wide
    # vessel arrival alone cannot establish unloading or readiness for pickup.
    if DISCHARGE_REQUEST.search(enquiry.get("customer_message") or "") and not target.container:
        return None
    return status.casefold() == snapshot.status


def _matches_display(observed, reference_time, precision):
    if precision == 60:
        reference_time = reference_time.replace(second=0, microsecond=0)
    return observed == reference_time


def review_reply(data, tracking, enquiry: dict, reply: dict, runs: list[dict], settings: dict, *,
                 claim_reader=None, cases=(), histories=()) -> ReplyReview:
    result = ReplyReview(reply)
    sent = data.time("responses", reply.get("sent_at"))
    if sent is None:
        result.reason = "The time of the sent reply is unverified."
        return result
    target = tracking.for_request(enquiry, sent)
    run = _sent_run(data, reply, sent, runs)
    result.refs = [reference("enquiries", enquiry), reference("responses", reply)]
    if run is not None:
        result.refs.append(reference("agent_runs", run))
    if target is not None:
        result.refs.append(reference("shipments", target.shipment))
    text_targets = [tracking.resolve(identifier) for identifier in tracking.references_in_text(reply.get("message_text"))]
    result.refs.extend(ref for ref in dict.fromkeys(
        reference("shipments", match.shipment) for match in text_targets if match is not None
    ) if ref not in result.refs)
    identity = _identity(tracking, target, reply, run, text_targets)
    result.evidence["shipment_identity"] = {"passed": identity, "refs": result.refs.copy()}
    if identity is not True:
        if claim_reader is not None and text_targets and mentions_status(reply.get("message_text")):
            result.reply_claims = review_claims(
                claim_reader, data, tracking, target, enquiry, reply, sent, settings, cases, histories,
            )
        result.verdict = "failed" if identity is False else "unknown"
        result.matches_record = identity
        result.reason = "The reply used the wrong shipment or container." if identity is False else "The requested and reported shipment could not be reliably linked."
        return result

    snapshot = tracking.snapshot(target, sent)
    question = enquiry.get("customer_message") or ""
    message = reply.get("message_text") or ""
    planned = coordination_request(enquiry)
    eta_claim = reply.get("claimed_eta")
    if not eta_claim and run is not None:
        eta_claim = run.get("claimed_eta")
    port = target.shipment.get("destination")
    port_name = settings.get("port_names", {}).get(port)
    port_timezone = settings["port_timezones"].get(port)
    observed, precision, eta_basis = sent_eta(message, sent, port_name, port_timezone)
    structured = (data.time("responses", reply["claimed_eta"]) if reply.get("claimed_eta") else
                  data.time("agent_runs", eta_claim) if run is not None else None)
    known_response = requested_eta_response(message, eta_basis)
    reading = interpret_exchange(claim_reader, question, message)
    if reading is not None:
        result.eta_interpretation = asdict(reading)
    result.requested_eta = _apply_eta_interpretation(reading, known_response, explicit_eta_request(enquiry))
    eta_text = result.requested_eta is not None
    legacy = claim_reader is None and historical_benchmark(data)
    eta_response = (result.requested_eta or {}).get("state")
    non_answer = eta_response in {"omitted", "declared_unavailable"}
    if eta_text and eta_response == "provided" and known_response == "unknown":
        observed, precision, eta_basis = quoted_eta(reading.reply_quote, message, sent, port_name, port_timezone)
        if conflicting_eta_passage(message, port_name):
            eta_response = result.requested_eta["state"] = "unknown"
    if eta_text:
        result.evidence["eta_request_answered"] = {
            "passed": None if eta_response == "unknown" else not non_answer,
            "context_impact": "material", "refs": result.refs.copy(),
        }
    if eta_basis == "no_eta_in_sent_message" and legacy and structured is not None and not non_answer:
        observed, eta_basis = structured, "legacy_structured_claim"
    status_text = bool(STATUS_REQUEST.search(question))
    result.status_in_scope = status_text or (bool(reply.get("claimed_status")) if legacy else mentions_status(message))
    result.eta_in_scope = (eta_basis != "no_eta_in_sent_message" or eta_text
                           or (legacy and not question and snapshot.eta_kind in {"EST", "PLN"}))

    checks = []
    record_checks = []
    if legacy and result.status_in_scope:
        status_pass = _status_check(target, enquiry, reply, snapshot, settings)
        result.evidence["milestone_status"] = {
            "passed": status_pass, "refs": result.refs + snapshot.status_refs + snapshot.eta_refs,
        }
        checks.append(status_pass)
        record_checks.append(status_pass)
    if not legacy:
        if claim_reader is not None:
            result.reply_claims = review_claims(
                claim_reader, data, tracking, target, enquiry, reply, sent, settings, cases, histories,
            )
            if result.reply_claims["state"] != "extracted":
                checks.append(None)
                record_checks.append(None)
        findings = result.reply_claims["findings"] if result.reply_claims else []
        unquoted = message
        for finding in findings:
            unquoted = unquoted.replace(finding["quote"], " ")
            result.refs.extend(ref for ref in finding["refs"] if ref not in result.refs)
        if any(finding.get("reason_code") == "wrong_reference" for finding in findings):
            result.evidence["shipment_identity"] = {"passed": False, "refs": result.refs.copy()}
        result.action_in_scope = mentions_action(message) or any(f["kind"] == "action" for f in findings)
        result.status_in_scope |= any(f["kind"] == "status" for f in findings)
        for needed, kind, criterion, terms in (
            (result.status_in_scope, "status", "milestone_status", status_terms),
            (result.action_in_scope, "action", "sent_action_claim", action_terms),
        ):
            if needed:
                selected = [finding for finding in findings if finding["kind"] == kind]
                verdicts = {finding["verdict"] for finding in selected}
                unaccounted = terms(unquoted) or terms(message).difference(finding["value"] for finding in selected)
                passed = (False if "contradicted" in verdicts else
                          True if verdicts == {"supported"} and not unaccounted else None)
                result.evidence[criterion] = {"passed": passed, "refs": result.refs.copy()}
                checks.append(passed)
                record_checks.append(passed)
    if result.eta_in_scope:
        disagrees = (eta_basis in {"sent_message", "ai_quote"} and structured is not None
                     and not _matches_display(observed, structured, precision))
        eta_result = {
            "observed_at": observed.isoformat() if observed is not None else None,
            "reference_at": snapshot.eta.isoformat() if snapshot.eta is not None else None,
            "refs": result.refs + snapshot.eta_refs,
            "eta_claim_basis": eta_basis,
            "eta_display_precision_seconds": precision,
            "structured_eta_disagrees": disagrees,
        }
        if disagrees:
            eta_result["structured_eta_at"] = structured.isoformat()
        eta_match = None
        exact_eta = None
        if observed is not None and snapshot.eta is not None:
            deviation = abs((observed - snapshot.eta).total_seconds())
            exact_eta = _matches_display(observed, snapshot.eta, precision)
            if exact_eta:
                eta_match = True
            elif (not planned and enquiry.get("enquiry_type") == "status"
                  and not TIMING_CONSTRAINT.search(question) and deviation <= settings["routine_eta_minor_seconds"]):
                eta_match = True
                eta_result["context_impact"] = "minor"
        if planned:
            cutoff = _cutoff(data, enquiry, snapshot.eta, target.shipment.get("destination"), settings) if snapshot.eta else None
            decision_pass = None
            if cutoff is not None:
                eta_result["decision_cutoff_at"] = cutoff.isoformat()
                decisions = {team.casefold() for team in MONITORING_DECISION.findall(reply.get("message_text") or "")}
                if len(decisions) == 1:
                    correct_team = "morning" if snapshot.eta <= cutoff else "afternoon"
                    decision_pass = next(iter(decisions)) == correct_team
                if observed is not None:
                    eta_match = (observed <= cutoff) == (snapshot.eta <= cutoff)
            result.evidence["arrival_decision"] = {
                "passed": decision_pass, "context_impact": "material", "refs": eta_result["refs"],
            }
            checks.append(decision_pass)
        result.evidence["coordination_eta" if planned else "eta_accuracy"] = eta_result
        checks.append(eta_match)
        record_checks.append(exact_eta)
    result.refs.extend(ref for ref in dict.fromkeys(snapshot.status_refs + snapshot.eta_refs) if ref not in result.refs)
    if eta_response == "omitted":
        result.verdict = "failed"
        result.reason = "The sent reply did not answer the customer's arrival-time question."
    elif False in checks:
        result.verdict = "failed"
        result.reason = "The sent reply contradicted a verified status, action or decision."
    elif checks and all(check is True for check in checks):
        result.verdict = "supported"
    else:
        result.reason = "Evidence is incomplete for the requested reply or its operational context."
    if eta_response == "omitted" or False in record_checks:
        result.matches_record = False
    elif record_checks and all(check is True for check in record_checks):
        result.matches_record = True
    return result
