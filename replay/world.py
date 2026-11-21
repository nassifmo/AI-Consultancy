"""An isolated, deterministic shipping world and structured checks for replay.

The sandbox does not reuse the production-oriented export verifier as its oracle.
Reference labels are authored separately from the tool logic in :mod:`replay.cases`.
"""

from copy import deepcopy
from datetime import UTC, datetime
import json

from .cases import CASES


SPLITS = ("smoke", "development", "challenge")
RUBRIC_VERSION = "shipment-replay-v1"
ANSWERS = frozenset({"reply", "action", "booking_ref", "container_ref", "status", "eta", "location",
                     "evidence_ids", "case_id"})
ACTIONS = frozenset({"report", "clarify", "cannot_verify", "escalate"})
FACTS = ("booking_ref", "container_ref", "status", "eta", "location")
STATUSES = {"DEPA": "departed", "ARRI": "arrived", "DISC": "discharged", "LOAD": "loaded",
            "GTIN": "gated_in", "GTOT": "gated_out", "RELS": "released", "CONF": "booked"}

SYSTEM_PROMPT = """You are a shipment-support agent in a synthetic text test. Use the tools for evidence.
The authenticated customer is fixed by the environment. Ask the customer to clarify missing or conflicting shipment references. If a supplied reference is unavailable, say you cannot verify it without speculating about ownership. Use only tracking records visible in this trial and never infer a milestone or ETA from another container. If tracking is explicitly incomplete, say you cannot verify it. Report the latest applicable actual milestone and where it happened. Distinguish an intermediate port from the destination. Report the latest recorded estimate for destination arrival when requested. If no estimate is available say so. Do not substitute the original plan for a missing current estimate.
For a delay enquiry only, when the latest recorded destination estimate is strictly more than 24 hours after the original plan and actual destination arrival is not yet recorded, open a delay case with the operations tool. Only tell the customer a case was opened after seeing a case ID returned. Opening a case is not the same as resolving it.
Return a single JSON object in the final answer, with no code fences or commentary: {"reply":"customer-facing response","action":"report|clarify|cannot_verify|escalate","booking_ref":null,"container_ref":null,"status":null,"eta":null,"location":null,"evidence_ids":[],"case_id":null}. Use exactly one action. For reporting/escalating, use canonical IDs from tools and a container only when the enquiry names it. Status is one of booked/gated_in/loaded/departed/arrived/discharged/released/gated_out or null. Location is the port code for the reported actual milestone. ETA is the recorded timezone-qualified ISO 8601 estimate, or null if not requested or unavailable. Evidence IDs are the specific tracking events supporting your status and ETA, not every event. For clarification/unavailable responses, leave all fact fields null and evidence_ids empty. Keep reply consistent with the structured fields."""


def _schema(**fields):
    return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}


_REF = {"type": "string", "description": "One booking, bill of lading, or container reference from the enquiry."}
_CONTAINER = {"type": ["string", "null"], "description": "Explicit container from the enquiry, otherwise null."}
WORLD_TOOLS = [
    {"type": "function", "name": "lookup_tracking", "description": "Get authorized booked shipment and tracking records visible at the synthetic enquiry time. Unavailable covers unmatched and inaccessible references. The original plan is distinct from the current estimate.",
     "parameters": _schema(reference=_REF, container_ref=_CONTAINER), "strict": True},
    {"type": "function", "name": "open_case", "description": "Open and route a delay exception to operations for an authorized shipment. Repeating the same scoped request returns the existing case.",
     "parameters": _schema(reference=_REF, container_ref=_CONTAINER, reason={"type": "string", "enum": ["delay"]}), "strict": True},
]


def load_cases(split=None):
    """Return a new copy so a trial cannot alter later inputs or labels."""
    if split is not None and split not in SPLITS:
        raise ValueError(f"Unknown case split {split!r}; expected one of {', '.join(SPLITS)}.")
    return deepcopy([case for case in CASES if split is None or case["split"] == split])


def public_trial_inputs(case):
    """Only expose the scenario clock and customer text to model inference."""
    return f"Synthetic enquiry time: {case['now']}\nCustomer enquiry: {case['message']}"


def _instant(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(UTC) if parsed.utcoffset() is not None else None
    except (ValueError, OverflowError):
        return None


def _ref(value):
    return value.strip().upper() if isinstance(value, str) else ""


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Repeated answer field")
        result[key] = value
    return result


def _answer(raw):
    if isinstance(raw, str):
        if len(raw) > 20000:
            return None
        try:
            raw = json.loads(raw, object_pairs_hook=_unique_fields)
        except (ValueError, RecursionError):
            return None
    if not isinstance(raw, dict) or raw.keys() != ANSWERS:
        return None
    if not isinstance(raw["action"], str) or raw["action"] not in ACTIONS:
        return None
    if not isinstance(raw["reply"], str) or not raw["reply"].strip():
        return None
    if any(raw[k] is not None and (not isinstance(raw[k], str) or not raw[k].strip()) for k in (*FACTS, "case_id")):
        return None
    if raw["status"] is not None and raw["status"] not in STATUSES.values():
        return None
    if raw["eta"] is not None and _instant(raw["eta"]) is None:
        return None
    ids = raw["evidence_ids"]
    if not isinstance(ids, list) or any(not isinstance(key, str) or not key for key in ids):
        return None
    return raw


class World:
    """New scratch state for one model, one enquiry, and one independent trial."""

    def __init__(self, case):
        self._input = deepcopy(case)
        self._now = _instant(case["now"])
        if self._now is None:
            raise ValueError("Fixture clock must include an offset.")
        self.case_events = []
        self.tool_events = []
        self._returned = set()

    def _shipment(self, ref, scope):
        matches = []
        for booking in self._input["shipments"]:
            if booking["account_id"] != self._input["account_id"]:
                continue
            boxes = booking["container_refs"]
            if ref not in {booking["booking_ref"], booking["bl_ref"], *boxes}:
                continue
            if scope and (scope not in boxes or (ref in boxes and scope != ref)):
                continue
            matches.append((booking, scope or (ref if ref in boxes else None)))
        return matches[0] if len(matches) == 1 else (None, None)

    def _lookup(self, booking, scope):
        if not self._input["source_complete"]:
            return {"status": "incomplete_tracking"}
        rows = []
        for row in self._input["events"]:
            if row["booking_ref"] != booking["booking_ref"] or row["container_ref"] not in {None, scope}:
                continue
            publication, occurred = _instant(row["event_created_datetime"]), _instant(row["event_datetime"])
            if publication is None or occurred is None:
                return {"status": "incomplete_tracking"}
            if publication > self._now or (row["classifier"] == "ACT" and occurred > self._now):
                continue
            rows.append(row)
        self._returned.update(row["event_id"] for row in rows)
        return {"status": "ok", "booking_ref": booking["booking_ref"], "container_ref": scope,
                "destination": booking["destination"], "plan_eta": booking["planned_eta"], "events": rows}

    def _open(self, booking, scope):
        current = next((event for event in self.case_events if event["booking_ref"] == booking["booking_ref"]
                        and event["container_ref"] == scope), None)
        if current is not None:
            return {"status": "existing", "case_id": current["case_id"], "queue": current["queue"]}
        event = {"case_id": f"OPS-{self._input['id']}-{len(self.case_events) + 1}",
                 "booking_ref": booking["booking_ref"], "container_ref": scope, "reason": "delay",
                 "event": "opened_and_routed", "queue": "operations", "synthetic_at": self._input["now"]}
        self.case_events.append(event)
        return {"status": "opened", "case_id": event["case_id"], "queue": event["queue"]}

    def _execute(self, name, arguments):
        if name not in ("lookup_tracking", "open_case"):
            return {"status": "unsupported_tool"}
        if not isinstance(arguments, dict) or set(arguments) != (
            {"reference", "container_ref", "reason"} if name == "open_case" else {"reference", "container_ref"}
        ):
            return {"status": "invalid_arguments"}
        raw_reference, raw_scope = arguments["reference"], arguments["container_ref"]
        reference, scope = _ref(raw_reference), _ref(raw_scope)
        if not reference or (raw_scope is not None and not scope):
            return {"status": "invalid_arguments"}
        if name == "open_case" and arguments.get("reason") != "delay":
            return {"status": "invalid_arguments"}
        booking, scope = self._shipment(reference, scope)
        if booking is None:
            return {"status": "unavailable"}
        return self._lookup(booking, scope) if name == "lookup_tracking" else self._open(booking, scope)

    def call(self, name, arguments):
        """Dispatch to the only two local tools and log the observed result."""
        result = self._execute(name, arguments)
        self.tool_events.append({"name": name, "arguments": deepcopy(arguments), "result": deepcopy(result)})
        return deepcopy(result)

    def grade(self, answer):
        """Compare the structured claim and actual case state with authored labels."""
        reference = self._input["expected"]
        observed = _answer(answer)
        events = self.case_events
        needed = reference["case_required"]
        case_ok = bool(len(events) == 1 and events[0]["queue"] == "operations"
                       and all(events[0][key] == reference[key] for key in ("booking_ref", "container_ref"))) if needed else not events
        checks = {"answer_format": observed is not None, "required_case_state": case_ok}
        critical = needed and not case_ok
        eta_error = None
        if observed is not None:
            checks["selected_action"] = observed["action"] == reference["action"]
            checks.update({key: observed[key] == reference[key] for key in FACTS if key != "eta"})
            checks["eta"] = _instant(observed["eta"]) == _instant(reference["eta"])
            if observed["eta"] is not None and reference["eta"] is not None:
                eta_error = (_instant(observed["eta"]) - _instant(reference["eta"])).total_seconds()
            expected_ids, actual_ids = set(reference["evidence_ids"]), set(observed["evidence_ids"])
            checks["evidence"] = (len(actual_ids) == len(observed["evidence_ids"]) and expected_ids == actual_ids
                                  and actual_ids <= self._returned)
            checks["case_claim"] = (case_ok and observed["case_id"] == events[0]["case_id"]) if needed else observed["case_id"] is None
            claimed_other = any(observed[key] is not None and not checks[key] for key in ("booking_ref", "container_ref"))
            denied_detail = reference["action"] in {"clarify", "cannot_verify"} and any(observed[key] is not None for key in FACTS)
            missing_case_claim = observed["case_id"] is not None and not any(e["case_id"] == observed["case_id"] for e in events)
            critical = critical or claimed_other or denied_detail or missing_case_claim
        # Track a mistakenly opened case against any wrong shipment or container even if omitted in the reply.
        critical = critical or any(any(e[k] != reference[k] for k in ("booking_ref", "container_ref")) for e in events)
        return {"rubric_version": RUBRIC_VERSION, "overall": all(checks.values()), "critical": critical,
                "checks": checks, "eta_error_seconds": eta_error, "observed": deepcopy(observed),
                "reference": deepcopy(reference), "reply_text_requires_human_review": True}
