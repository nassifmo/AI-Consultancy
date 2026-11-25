"""Check the evidence boundary for an unanswered ETA handoff."""

from datetime import datetime

from evaluator.eta_handoff import review_eta_handoff
from evaluator.exports import ExportData


RECEIVED = "2026-03-09T09:00:00+00:00"
SENT = "2026-03-09T09:01:00+00:00"
ROUTED = "2026-03-09T09:02:00+00:00"
CLOSED = "2026-03-09T09:03:00+00:00"
ENQUIRY = {"enquiry_id": "E1", "received_at": RECEIVED}
REPLY = {"response_id": "M1", "actor_type": "ai_agent", "actor_id": "v1",
         "sent_at": SENT, "message_text": "The vessel has departed."}
CASE = {"case_id": "C1", "enquiry_id": "E1", "opened_at": SENT, "reason": "callback_request"}
ROUTE = {"history_id": "H1", "case_id": "C1", "field": "queue", "new_value": "human_review",
         "changed_at": ROUTED}


def _review(*, cutoff=CLOSED, metadata=None, cases=(), histories=(), runs=(), reply=REPLY, conflicts=None):
    data = ExportData(available={"agent_runs", "cases", "case_history"}, metadata=metadata or {},
                      tables={"agent_runs": runs, "cases": cases}, conflicts=conflicts or {},
                      cutoff=datetime.fromisoformat(cutoff))
    return review_eta_handoff(data, ENQUIRY, reply, cases, histories, runs)


def _run(*, response=REPLY["message_text"], step=None, handoff=False):
    return {
        "run_id": "R1", "enquiry_id": "E1", "agent_version": "v1",
        "started_at": RECEIVED, "ended_at": SENT, "response_text": response, "handoff_flag": handoff,
        "steps": [{"tool_name": "send_message", "success": True}] + ([step] if step else []),
    }


def test_complete_exports_can_show_no_recorded_handoff_despite_a_stale_run_message():
    result = _review(runs=[_run(response="The vessel ETA is 11:00.")])
    assert result["state"] == "not_recorded"
    assert result["pending"] is None


def test_partial_or_conflicted_sources_keep_absence_unknown():
    result = _review(metadata={"source_completeness": {"agent_runs": "complete", "cases": "complete",
                                                       "case_history": "partial"}})
    assert result["state"] == "unknown"
    result = _review(cases=[CASE], histories=[ROUTE], conflicts={"case_history": [ROUTE]})
    assert result["state"] == "unknown"


def test_flag_or_promise_is_unverified_but_linked_queued_transfer_is_pending():
    assert _review(runs=[_run(handoff=True)])["state"] == "unknown"
    assert _review(reply={**REPLY, "message_text": "I will transfer you to a human agent."})["state"] == "unknown"
    step = {"tool_name": "handoff_to_human", "success": True, "tool_output": "queued"}
    result = _review(runs=[_run(step=step)])
    assert result["state"] == "verified"
    assert result["pending"] is True
    assert "agent_runs.json#R1" in result["refs"]
    assert _review(runs=[_run(step={**step, "tool_output": "received"})])["state"] == "unknown"
    assert _review(runs=[_run(response="Other message.", step=step)])["state"] == "unknown"


def test_case_requires_routing_evidence_and_closed_case_is_not_pending():
    assert _review(cases=[CASE])["state"] == "unknown"
    assert _review(cutoff=SENT, cases=[CASE], histories=[ROUTE])["state"] == "unknown"
    result = _review(cutoff=ROUTED, cases=[{**CASE, "closed_at": CLOSED}], histories=[ROUTE])
    assert result["state"] == "verified"
    assert result["pending"] is True
    assert "case_history.csv#H1" in result["refs"]
    result = _review(cases=[{**CASE, "closed_at": CLOSED}], histories=[ROUTE])
    assert result["state"] == "verified"
    assert result["pending"] is False


def test_verified_route_with_partial_closure_history_has_unknown_pending_status():
    result = _review(metadata={"source_completeness": {"cases": "complete", "case_history": "partial"}},
                     cases=[CASE], histories=[ROUTE])
    assert result["state"] == "verified"
    assert result["pending"] is None


def test_company_escalation_status_requires_a_documented_destination():
    status = {**ROUTE, "field": "status", "new_value": "escalated"}
    metadata = {"dataset_origin": "company"}
    assert _review(metadata=metadata, cases=[CASE], histories=[status])["state"] == "unknown"
    result = _review(metadata=metadata, cases=[CASE], histories=[{**status, "destination_queue": "operations"}])
    assert result["state"] == "verified"
    assert result["pending"] is True
