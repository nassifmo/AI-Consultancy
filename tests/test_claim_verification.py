"""Exercise the verifier on deliberately conflicting sent replies and records."""

import csv
from datetime import datetime
import json
from pathlib import Path
import shutil

import pytest

from evaluator.claim_reader import ActionClaim, EtaReading, ReplyClaims, StatusClaim
from evaluator.exports import TABLES, load_exports
from evaluator.verification import Verifier, verify_exports


PROJECT = Path(__file__).resolve().parents[1]
POLICY = json.loads((PROJECT / "evaluator" / "policy.json").read_text(encoding="utf-8"))
ORIGINAL = PROJECT / "datagen" / "datasets" / "scenarios" / "S28" / "exports"
ETA = "The current Rotterdam ETA is 16 March at 11:00 local time."
DEPARTED = "The vessel has departed."
ARRIVED = "The vessel has already arrived in Rotterdam."
OPENED = "I opened case CAS-V1."
ROUTED = "I routed the case to operations."


def _read(path):
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        return list(reader), reader.fieldnames


def _write(path, rows, fields=None):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fields or rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def _exports(tmp_path, message):
    exports = shutil.copytree(ORIGINAL, tmp_path / "exports")
    rows, _ = _read(exports / "responses.csv")
    rows[0]["message_text"] = message
    _write(exports / "responses.csv", rows)
    return exports


def _declare_company_scenario(exports, origin="company"):
    path = exports / "export_metadata.json"
    metadata = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({
        **metadata, "dataset_origin": origin, "source_completeness": dict.fromkeys(TABLES, "complete"),
    }), encoding="utf-8")


def _case_history(exports, opened, routed=None, actor="agent_v1", case_id="CAS-V1"):
    case_path = exports / "cases.csv"
    cases, fields = _read(case_path)
    cases.append({"case_id": case_id, "enquiry_id": "ENQ-S28", "opened_at": opened,
                  "reason": "other", "owner_id": actor})
    _write(case_path, cases, fields)
    history_path = exports / "case_history.csv"
    histories, fields = _read(history_path)
    histories.append({"history_id": f"{case_id}-create", "case_id": case_id, "changed_at": opened,
                      "field": "status", "new_value": "new", "changed_by": actor})
    if routed:
        histories.append({"history_id": f"{case_id}-route", "case_id": case_id, "changed_at": routed,
                          "field": "owner", "new_value": "Operations", "changed_by": actor})
    _write(history_path, histories, fields)


def _result(exports, reader=None):
    result, = verify_exports(exports, POLICY, claim_reader=reader)["enquiries"]
    return result


def _claims(result, position="initial_reply"):
    return result["verification"][position]["reply_claims"]["findings"]


def _action_reader(message):
    return ReplyClaims(
        status_claims=(StatusClaim("departed", "vessel", DEPARTED),) if DEPARTED in message else (),
        action_claims=tuple(
            ActionClaim(action, quote) for action, quote in
            (("opened_case", OPENED), ("routed_to_operations", ROUTED)) if quote in message
        ),
    )


def test_sent_status_takes_precedence_over_structured_status(tmp_path):
    exports = _exports(tmp_path, f"{ARRIVED} {ETA}")
    captured = []

    def read_only_sent_reply(text):
        captured.append(text)
        return ReplyClaims(status_claims=(StatusClaim("arrived", "vessel", ARRIVED),))

    result = _result(exports, read_only_sent_reply)
    assert captured == [f"{ARRIVED} {ETA}"]
    assert result["outcome"]["state"] == "failed"
    assert result["criteria"]["eta_accuracy"]["eta_error_seconds"] == 0
    assert result["criteria"]["milestone_status"]["passed"] is False
    assert _claims(result)[0]["verdict"] == "contradicted"
    assert any(ref.startswith("tracking_events.json#") for ref in _claims(result)[0]["refs"])


def test_reader_unavailable_or_missing_claim_never_reuses_status_log(tmp_path):
    exports = _exports(tmp_path, f"{ARRIVED} {ETA}")
    for reader in (lambda _: ReplyClaims(), lambda _: ReplyClaims(state="unavailable"),
                   lambda _: ReplyClaims(status_claims=(StatusClaim("departed", "vessel", DEPARTED),)),
                   lambda _: ReplyClaims(status_claims=(StatusClaim("departed", "vessel", ARRIVED),))):
        result = _result(exports, reader)
        assert result["outcome"]["state"] == "unknown"
        assert result["criteria"]["milestone_status"]["status"] == "unknown"
        assert result["verification"]["initial_reply"]["matches_record"] is None


def test_rules_only_mode_does_not_trust_company_structured_status(tmp_path):
    exports = _exports(tmp_path, f"{ARRIVED} {ETA}")
    _declare_company_scenario(exports)

    result = _result(exports)
    assert result["outcome"]["state"] == "unknown"
    assert result["criteria"]["milestone_status"]["status"] == "unknown"


def test_status_only_reply_fails_an_explicit_eta_request_in_both_modes(tmp_path):
    exports = _exports(tmp_path, DEPARTED)
    for reader in (None, _action_reader):
        result = _result(exports, reader)
        initial = result["verification"]["initial_reply"]
        assert initial["verdict"] == "failed"
        assert initial["matches_record"] is False
        assert initial["requested_eta"]["state"] == "omitted"
        assert initial["requested_eta"]["handoff"]["state"] == "not_recorded"
        assert result["criteria"]["eta_request_answered"]["status"] == "unmet"
        assert result["criteria"]["eta_accuracy"]["status"] == "unknown"
        assert result["outcome"]["state"] == "failed"


def test_missing_handoff_source_keeps_outcome_unknown_but_retains_reply_failure(tmp_path):
    exports = _exports(tmp_path, DEPARTED)
    (exports / "case_history.csv").unlink()

    result = _result(exports, _action_reader)
    initial = result["verification"]["initial_reply"]
    assert initial["verdict"] == "failed"
    assert initial["requested_eta"]["handoff"]["state"] == "unknown"
    assert result["outcome"]["state"] == "unknown"


def test_verified_handoff_waits_for_the_human_reply(tmp_path):
    exports = _exports(tmp_path, "The ETA is unavailable.")
    before_route = _result(exports, _action_reader)
    assert before_route["outcome"]["state"] == "failed"
    assert before_route["verification"]["initial_reply"]["requested_eta"]["state"] == "declared_unavailable"

    _case_history(exports, "2026-03-09T09:02:00+00:00", "2026-03-09T09:03:00+00:00")
    pending = _result(exports, _action_reader)
    assert pending["verification"]["initial_reply"]["requested_eta"]["handoff"]["state"] == "verified"
    assert pending["outcome"]["state"] == "escalated_open"

    responses = exports / "responses.csv"
    rows, fields = _read(responses)
    rows.append({**rows[0], "response_id": "RSP-S28-H2", "actor_type": "human", "actor_id": "HUM-T1",
                 "sent_at": "2026-03-09T09:10:00+00:00", "case_id": "CAS-V1",
                 "purpose": "correction", "message_text": ETA})
    _write(responses, rows, fields)
    recovered = _result(exports, _action_reader)
    assert recovered["outcome"]["state"] == "resolved"
    assert recovered["criteria"]["eta_request_answered"]["status"] == "unmet"
    assert recovered["verification"]["last_reply"]["requested_eta"]["state"] == "provided"


def test_unsupported_eta_wording_or_absent_body_still_needs_review(tmp_path):
    exports = _exports(tmp_path, "")
    responses = exports / "responses.csv"
    rows, fields = _read(responses)
    for message in ("", "It should reach Rotterdam tomorrow morning."):
        _write(responses, [{**rows[0], "message_text": message}], fields)
        result = _result(exports, _action_reader)
        assert result["outcome"]["state"] == "unknown"
        assert result["criteria"]["eta_request_answered"]["status"] == "unknown"


def test_mentioning_an_eta_is_not_necessarily_an_eta_request(tmp_path):
    exports = _exports(tmp_path, DEPARTED)
    enquiries = exports / "enquiries.csv"
    rows, fields = _read(enquiries)
    rows[0]["customer_message"] = "I have the ETA. Has the vessel departed?"
    _write(enquiries, rows, fields)

    result = _result(exports, _action_reader)
    assert result["outcome"]["state"] == "resolved"
    assert result["criteria"]["eta_request_answered"]["status"] == "not_applicable"


class ExchangeReader:
    def __init__(self, response_states):
        self.response_states = response_states

    def __call__(self, message):
        return _action_reader(message)

    def interpret_eta(self, question, reply):
        return EtaReading(intent="arrival_time", response=self.response_states[reply],
                          request_quote=question, reply_quote=reply)


def _set_customer_message(exports, message):
    path = exports / "enquiries.csv"
    rows, fields = _read(path)
    _write(path, [{**rows[0], "customer_message": message}], fields)


def test_ai_understands_eta_request_and_omission_in_natural_phrasing(tmp_path):
    message = "She put to sea last night."
    question = "How long until she gets to Rotterdam?"
    exports = _exports(tmp_path, message)
    _set_customer_message(exports, question)
    _declare_company_scenario(exports, "unconfirmed")

    assert _result(exports)["outcome"]["state"] == "unknown"
    result = _result(exports, ExchangeReader({message: "omitted"}))
    assert result["outcome"]["state"] == "failed"
    assert result["criteria"]["eta_request_answered"]["status"] == "unmet"
    first = result["verification"]["initial_reply"]
    assert first["requested_eta"]["basis"] == "ai"
    assert first["eta_interpretation"]["request_quote"] == question
    assert first["eta_interpretation"]["reply_quote"] == message


def test_ai_eta_quote_is_scored_against_tracking_and_falls_back_to_review(tmp_path):
    question = "When is she due in Rotterdam?"
    message = "We expect her alongside in Rotterdam on 16 March at 11:00 local time."
    later = message.replace("11:00", "17:00")
    vague = "We expect her alongside tomorrow around lunchtime."
    reader = ExchangeReader({reply: "provided" for reply in (message, later, vague)})
    exports = _exports(tmp_path, message)
    _set_customer_message(exports, question)

    result = _result(exports, reader)
    assert result["outcome"]["state"] == "resolved"
    assert result["criteria"]["eta_accuracy"]["eta_claim_basis"] == "ai_quote"
    assert result["criteria"]["eta_accuracy"]["eta_error_seconds"] == 0

    path = exports / "responses.csv"
    rows, fields = _read(path)
    _write(path, [{**rows[0], "message_text": later}], fields)
    inaccurate = _result(exports, reader)
    assert inaccurate["verification"]["initial_reply"]["matches_record"] is False
    assert inaccurate["criteria"]["eta_accuracy"]["eta_error_seconds"] == 6 * 3600

    _write(path, [{**rows[0], "message_text": vague}], fields)
    needs_review = _result(exports, reader)
    assert needs_review["outcome"]["state"] == "unknown"
    assert needs_review["criteria"]["eta_request_answered"]["status"] == "met"
    assert needs_review["criteria"]["eta_accuracy"]["status"] == "unknown"


def test_ai_understands_an_unavailable_eta_and_a_later_human_update(tmp_path):
    question = "When is she due in Rotterdam?"
    waiting = "I'm still waiting on a firm estimate from the carrier."
    answer = "We expect her alongside in Rotterdam on 16 March at 11:00 local time."
    reader = ExchangeReader({waiting: "declared_unavailable", answer: "provided"})
    exports = _exports(tmp_path, waiting)
    _set_customer_message(exports, question)
    _case_history(exports, "2026-03-09T09:02:00+00:00", "2026-03-09T09:03:00+00:00")

    result = _result(exports, reader)
    assert result["outcome"]["state"] == "escalated_open"
    assert result["verification"]["initial_reply"]["requested_eta"]["handoff"]["state"] == "verified"

    path = exports / "responses.csv"
    rows, fields = _read(path)
    rows.append({**rows[0], "response_id": "RSP-S28-H2", "actor_type": "human", "actor_id": "HUM-T1",
                 "sent_at": "2026-03-09T09:10:00+00:00", "purpose": "case_update", "case_id": "CAS-V1",
                 "message_text": answer})
    _write(path, rows, fields)
    confirmed = _result(exports, reader)
    assert confirmed["outcome"]["state"] == "resolved"
    assert confirmed["verification"]["last_reply"]["requested_eta"]["state"] == "provided"


def test_a_model_cannot_verify_another_ports_eta_or_a_promised_update(tmp_path):
    question = "When is she due in Rotterdam?"
    other_port = "She is expected in Antwerp on 16 March at 10:00 UTC."
    promise = "We will send you the Rotterdam ETA on 16 March at 11:00 local time."
    reader = ExchangeReader({other_port: "provided", promise: "provided"})
    exports = _exports(tmp_path, other_port)
    _set_customer_message(exports, question)
    path = exports / "responses.csv"
    rows, fields = _read(path)
    for message in (other_port, promise):
        _write(path, [{**rows[0], "message_text": message}], fields)
        result = _result(exports, reader)
        assert result["outcome"]["state"] == "unknown"
        assert result["criteria"]["eta_request_answered"]["status"] == "unknown"
        assert result["criteria"]["eta_accuracy"].get("eta_error_seconds") is None


@pytest.mark.parametrize("message", [
    "The current Antwerp ETA is 2026-03-16T10:00:00Z.",
    "If the vessel remains on schedule, the ETA is 2026-03-16T10:00:00Z.",
])
def test_matching_timestamp_with_ambiguous_scope_is_not_a_verified_eta(tmp_path, message):
    exports = _exports(tmp_path, message)
    _declare_company_scenario(exports)

    class TimeOnlyReader(ExchangeReader):
        def interpret_eta(self, question, reply):
            return EtaReading(intent="arrival_time", response="provided", request_quote=question,
                              reply_quote="2026-03-16T10:00:00Z")

    for reader in (None, TimeOnlyReader({})):
        result = _result(exports, reader)
        assert result["outcome"]["state"] == "unknown"
        assert result["criteria"]["eta_accuracy"]["status"] == "unknown"
        assert result["criteria"]["eta_accuracy"].get("eta_error_seconds") is None
        if "Antwerp" in message:
            assert result["criteria"]["eta_request_answered"]["status"] == "unknown"


@pytest.mark.parametrize(("identifier", "identity", "outcome"), [
    ("SYNU9000006", "unmet", "failed"),
    ("SYNU9555555", "unknown", "unknown"),
    ("SYNU9000003", "met", "resolved"),
])
def test_visible_reference_controls_eta_scope(tmp_path, identifier, identity, outcome):
    reply = f"For {identifier}, the Rotterdam ETA is 2026-03-16T10:00:00Z."
    exports = _exports(tmp_path, reply)
    _declare_company_scenario(exports)

    # The structured reply still names the requested booking and contains the right timestamp.
    for reader in (None, ExchangeReader({reply: "provided"})):
        result = _result(exports, reader)
        assert result["criteria"]["shipment_identity"]["status"] == identity
        assert result["outcome"]["state"] == outcome
        if outcome == "failed":
            assert result["initial_failure"] is True
            assert "shipments.csv#BKG-T-OTHER" in result["verification"]["initial_reply"]["refs"]


def test_resolution_time_waits_for_correct_reply_even_if_case_already_closed(tmp_path):
    fixture = ORIGINAL.parent.parent / "S33" / "exports"
    exports = shutil.copytree(fixture, tmp_path / "exports")
    responses = exports / "responses.csv"
    rows, fields = _read(responses)
    rows[-1]["sent_at"] = "2026-03-13T10:00:00+00:00"
    _write(responses, rows, fields)

    result = _result(exports)
    assert result["outcome"]["state"] == "resolved"
    assert result["verification"]["human_recovery"] is True
    assert result["verification"]["resolved_at"] == rows[-1]["sent_at"]


@pytest.mark.parametrize("destination", ["", "Billing", "Operations", "queue-record"])
def test_company_delay_escalation_requires_evidence_of_operations_routing(tmp_path, destination):
    fixture = ORIGINAL.parent.parent / "S33" / "exports"
    exports = shutil.copytree(fixture, tmp_path / "exports")
    _declare_company_scenario(exports)
    history = exports / "case_history.csv"
    rows, fields = _read(history)
    changes, = [row for row in rows if row["new_value"] == "escalated"]
    if destination == "queue-record":
        rows.append({**changes, "history_id": "ROUTE-S33", "field": "queue", "old_value": "Support",
                     "new_value": "Operations"})
    else:
        changes["destination_queue"] = destination
    _write(history, rows, [*fields, "destination_queue"])

    result = _result(exports)
    confirmed = destination in {"Operations", "queue-record"}
    assert result["outcome"]["state"] == ("resolved" if confirmed else "unknown")
    assert result["criteria"]["escalation_deadline"]["status"] == ("unmet" if confirmed else "unknown")


def test_mislabeled_arrival_estimate_does_not_erase_human_recovery():
    fixture = ORIGINAL.parent.parent / "S33" / "exports"
    forecast = "Operations reviewed the delay and confirmed the 17 March arrival estimate at 12:00 UTC."

    def reader(message):
        if forecast in message:
            return ReplyClaims(status_claims=(StatusClaim("arrived", "shipment", forecast),))
        return _action_reader(message)

    result = _result(fixture, reader)
    assert result["outcome"]["state"] == "resolved"
    assert result["initial_failure"] is True
    assert result["verification"]["human_recovery"] is True


def test_vessel_status_is_not_compared_with_a_container_milestone(tmp_path):
    exports = _exports(tmp_path, f"{DEPARTED} {ETA}")
    path = exports / "tracking_events.json"
    events = json.loads(path.read_text(encoding="utf-8"))
    events.append({
        "event_id": "LOAD-V1", "booking_ref": "BKG-T-D24", "container_ref": "SYNU9000003",
        "event_type": "EQUIPMENT", "event_type_code": "LOAD", "classifier": "ACT", "location": "LBBEY",
        "event_datetime": "2026-03-08T12:00:00+00:00", "event_created_datetime": "2026-03-08T12:01:00+00:00",
    })
    path.write_text(json.dumps(events), encoding="utf-8")

    result = _result(exports, _action_reader)
    assert result["outcome"]["state"] == "resolved"
    assert _claims(result)[0]["verdict"] == "supported"
    assert "tracking_events.json#LOAD-V1" not in _claims(result)[0]["refs"]


def test_visible_wrong_booking_is_caught_even_if_extraction_omits_identifier(tmp_path):
    wrong_booking = "The vessel for BKG-T-D24P has departed."
    exports = _exports(tmp_path, f"{wrong_booking} {ETA}")
    result = _result(exports, lambda _: ReplyClaims(status_claims=(StatusClaim("departed", "vessel", wrong_booking),)))
    finding, = _claims(result)
    assert result["outcome"]["state"] == "failed"
    assert result["initial_failure"] is True
    assert finding["verdict"] == "contradicted"
    assert finding["reference"] == "BKG-T-D24P"
    assert "shipments.csv#BKG-T-D24P" in finding["refs"]


def test_extracting_only_words_after_a_negation_cannot_create_proof(tmp_path):
    exports = _exports(tmp_path, f"The vessel has not departed. {ETA}")

    result = _result(exports, lambda _: ReplyClaims(status_claims=(StatusClaim("departed", "vessel", "departed."),)))
    assert result["outcome"]["state"] == "unknown"
    assert result["verification"]["initial_reply"]["reply_claims"]["state"] == "needs_review"


def test_case_and_operations_completed_separately_and_in_time(tmp_path):
    exports = _exports(tmp_path, f"{DEPARTED} {ETA} {OPENED} {ROUTED}")
    _case_history(exports, "2026-03-09T09:00:10+00:00", routed="2026-03-09T09:00:30+00:00")

    result = _result(exports, _action_reader)
    assert result["outcome"]["state"] == "resolved"
    assert {finding["value"]: finding["verdict"] for finding in _claims(result)} == {
        "departed": "supported", "opened_case": "supported", "routed_to_operations": "supported",
    }
    assert "case_history.csv#CAS-V1-route" in _claims(result)[2]["refs"]
    assert _claims(result)[1]["case_id"] == "CAS-V1"


def test_future_operations_history_cannot_validate_earlier_claim(tmp_path):
    exports = _exports(tmp_path, f"{DEPARTED} {ETA} {OPENED} {ROUTED}")
    _case_history(exports, "2026-03-09T09:00:10+00:00", routed="2026-03-09T09:01:01+00:00")

    outcome = _result(exports, _action_reader)
    assert outcome["outcome"]["state"] == "failed"
    assert [finding["verdict"] for finding in _claims(outcome)] == ["supported", "supported", "contradicted"]
    assert outcome["criteria"]["sent_action_claim"]["passed"] is False
    assert "case_history.csv#CAS-V1-route" not in _claims(outcome)[2]["refs"]


def test_case_created_after_reply_and_no_model_claim_omission_false_pass(tmp_path):
    exports = _exports(tmp_path, f"{DEPARTED} {ETA} {OPENED} {ROUTED}")
    _case_history(exports, "2026-03-09T09:02:00+00:00", routed="2026-03-09T09:02:10+00:00")

    outcome = _result(exports, _action_reader)
    assert outcome["outcome"]["state"] == "failed"
    assert [finding["verdict"] for finding in _claims(outcome)] == ["supported", "contradicted", "contradicted"]

    def missed_actions(_):
        return ReplyClaims(status_claims=(StatusClaim("departed", "vessel", DEPARTED),))

    outcome = _result(exports, missed_actions)
    assert outcome["outcome"]["state"] == "unknown"
    assert outcome["criteria"]["sent_action_claim"]["status"] == "unknown"


def test_compound_quote_cannot_erase_an_omitted_action(tmp_path):
    both = "I opened case CAS-V1 and routed it to operations."
    exports = _exports(tmp_path, f"{DEPARTED} {ETA} {both}")
    _case_history(exports, "2026-03-09T09:00:10+00:00")

    def opened_only(_):
        return ReplyClaims(status_claims=(StatusClaim("departed", "vessel", DEPARTED),),
                           action_claims=(ActionClaim("opened_case", both),))

    result = _result(exports, opened_only)
    assert result["outcome"]["state"] == "unknown"
    assert result["criteria"]["sent_action_claim"]["status"] == "unknown"


def test_case_queue_does_not_prove_an_operations_notification(tmp_path):
    notification = "I notified operations."
    exports = _exports(tmp_path, f"{DEPARTED} {ETA} {notification}")
    _case_history(exports, "2026-03-09T09:00:10+00:00", routed="2026-03-09T09:00:30+00:00")

    def mislabeled(_):
        return ReplyClaims(status_claims=(StatusClaim("departed", "vessel", DEPARTED),),
                           action_claims=(ActionClaim("routed_to_operations", notification),))

    result = _result(exports, mislabeled)
    assert result["outcome"]["state"] == "unknown"
    assert _claims(result)[1]["verdict"] == "unknown"


def test_partial_routing_source_is_unknown(tmp_path):
    exports = _exports(tmp_path, f"{DEPARTED} {ETA} {OPENED} {ROUTED}")
    _case_history(exports, "2026-03-09T09:00:10+00:00")
    path = exports / "export_metadata.json"
    metadata = json.loads(path.read_text(encoding="utf-8"))
    metadata["source_completeness"] = {
        "responses": "complete", "tracking_events": "complete", "cases": "complete", "case_history": "partial",
    }
    path.write_text(json.dumps(metadata), encoding="utf-8")

    outcome = _result(exports, _action_reader)
    assert outcome["outcome"]["state"] == "unknown"
    assert [finding["verdict"] for finding in _claims(outcome)] == ["supported", "supported", "unknown"]


def test_multiple_cases_need_a_link_and_a_human_cannot_prove_the_ai_acted(tmp_path):
    exports = _exports(tmp_path, f"{DEPARTED} {ETA} {OPENED} {ROUTED}")
    _case_history(exports, "2026-03-09T09:00:10+00:00", actor="HUM-1")
    _case_history(exports, "2026-03-09T09:00:20+00:00", case_id="CAS-OTHER")

    result = _result(exports, _action_reader)
    assert [finding["verdict"] for finding in _claims(result)] == ["supported", "contradicted", "unknown"]
    assert result["outcome"]["state"] == "failed"


def test_later_human_reply_can_recover_without_erasing_initial_failure(tmp_path):
    exports = _exports(tmp_path, f"{DEPARTED} {ETA} {OPENED}")
    responses = exports / "responses.csv"
    rows, _ = _read(responses)
    rows.append({
        **rows[0], "response_id": "RSP-S28-H2", "sent_at": "2026-03-09T09:04:00+00:00",
        "actor_type": "human", "actor_id": "HUM-1", "purpose": "correction", "message_text": f"{DEPARTED} {ETA}",
    })
    _write(responses, rows)

    result = _result(exports, _action_reader)
    assert result["outcome"]["state"] == "resolved"
    assert result["initial_failure"] is True
    assert result["verification"]["human_recovery"] is True
    assert _claims(result)[1]["verdict"] == "contradicted"
    assert _claims(result, "last_reply")[0]["verdict"] == "supported"

    data = load_exports(exports)
    verifier = Verifier(data, POLICY, claim_reader=_action_reader)
    early = verifier.evaluate_at(data.tables["enquiries"][0], datetime.fromisoformat("2026-03-09T09:02:00+00:00"), ())
    assert early["outcome"]["state"] == "failed"
    assert early["verification"]["last_reply"]["actor_type"] == "ai_agent"
