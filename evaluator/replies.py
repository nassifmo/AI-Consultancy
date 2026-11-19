"""Check what was sent against source records visible at that time."""

from dataclasses import dataclass, field
from datetime import datetime
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .exports import reference


ETA_REQUEST = re.compile(r"\beta\b|arrival (?:estimate|time)|when .*arriv|(?:what time|expected to) .*arriv", re.IGNORECASE)
STATUS_REQUEST = re.compile(r"\b(status|unload(?:ed|ing)?|discharg(?:e|ed)|arrived|departed)\b|where is", re.IGNORECASE)
DISCHARGE_REQUEST = re.compile(r"\b(unload(?:ed|ing)?|discharg(?:e|ed))\b", re.IGNORECASE)
COORDINATION_REQUEST = re.compile(r"\bwhich\b.{0,45}\bteam\b.{0,40}\bnotify\b", re.IGNORECASE)
LOCAL_CUTOFF = re.compile(r"\beta of (\d{1,2}):(\d{2}) local time or earlier\b", re.IGNORECASE)
MONITORING_DECISION = re.compile(r"\bnotify the (morning|afternoon)(?: monitoring)? team\b", re.IGNORECASE)
TIMING_CONSTRAINT = re.compile(r"\b(pickup|deadline|cutoff|appointment|before|after|by \d)\b", re.IGNORECASE)


@dataclass
class ReplyReview:
    reply: dict
    verdict: str = "unknown"
    matches_record: bool | None = None
    evidence: dict = field(default_factory=dict)
    eta_in_scope: bool | None = None
    status_in_scope: bool | None = None
    refs: list[str] = field(default_factory=list)
    reason: str | None = None


def coordination_request(enquiry: dict) -> bool:
    return enquiry.get("request_profile") == "arrival_coordination" or bool(
        COORDINATION_REQUEST.search(enquiry.get("customer_message") or "")
    )


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


def _identity(tracking, target, reply: dict, run: dict | None) -> bool | None:
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


def review_reply(data, tracking, enquiry: dict, reply: dict, runs: list[dict], settings: dict) -> ReplyReview:
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
    identity = _identity(tracking, target, reply, run)
    result.evidence["shipment_identity"] = {"passed": identity, "refs": result.refs.copy()}
    if identity is not True:
        result.verdict = "failed" if identity is False else "unknown"
        result.matches_record = identity
        result.reason = "The reply used the wrong shipment or container." if identity is False else "The requested and reported shipment could not be reliably linked."
        return result

    snapshot = tracking.snapshot(target, sent)
    question = enquiry.get("customer_message") or ""
    planned = coordination_request(enquiry)
    eta_claim = reply.get("claimed_eta")
    if not eta_claim and run is not None:
        eta_claim = run.get("claimed_eta")
    status_text = bool(STATUS_REQUEST.search(question))
    eta_text = bool(ETA_REQUEST.search(question)) or planned
    result.status_in_scope = bool(reply.get("claimed_status")) or status_text
    result.eta_in_scope = bool(eta_claim) or eta_text or (not question and snapshot.eta_kind in {"EST", "PLN"})

    checks = []
    record_checks = []
    if result.status_in_scope:
        status_pass = _status_check(target, enquiry, reply, snapshot, settings)
        result.evidence["milestone_status"] = {
            "passed": status_pass, "refs": result.refs + snapshot.status_refs + snapshot.eta_refs,
        }
        checks.append(status_pass)
        record_checks.append(status_pass)
    if result.eta_in_scope:
        observed = data.time("responses", reply.get("claimed_eta"))
        if not reply.get("claimed_eta") and run is not None:
            observed = data.time("agent_runs", run.get("claimed_eta"))
        eta_result = {
            "observed_at": observed.isoformat() if observed is not None else None,
            "reference_at": snapshot.eta.isoformat() if snapshot.eta is not None else None,
            "refs": result.refs + snapshot.eta_refs,
        }
        eta_match = None
        exact_eta = None
        if observed is not None and snapshot.eta is not None:
            deviation = abs((observed - snapshot.eta).total_seconds())
            exact_eta = deviation == 0
            if deviation == 0:
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
    if False in checks:
        result.verdict = "failed"
        result.reason = "The sent reply contradicted a verified status or decision."
    elif checks and all(check is True for check in checks):
        result.verdict = "supported"
    else:
        result.reason = "Evidence is incomplete for the requested reply or its operational context."
    if False in record_checks:
        result.matches_record = False
    elif record_checks and all(check is True for check in record_checks):
        result.matches_record = True
    return result
