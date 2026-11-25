import json
from unittest.mock import Mock

import pytest
import requests

from evaluator.claim_reader import ActionClaim, EtaReading, OllamaClaimReader, ReplyClaims, StatusClaim


class OllamaResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def iter_content(self, *, chunk_size):
        yield json.dumps(self.payload).encode()


def chat_response(status_claims=(), action_claims=(), **extra):
    content = json.dumps({
        "status_claims": status_claims, "action_claims": action_claims,
        "state": "extracted",
    })
    return OllamaResponse({"done": True, "done_reason": "stop", **extra,
                           "message": {"role": "assistant", "content": content}})


def reader_with_responses(*responses, max_reads=25):
    reader = OllamaClaimReader("local:instruct", max_reads=max_reads)
    reader._session.post = Mock(side_effect=[
        OllamaResponse({"capabilities": ["completion"]}), *responses,
    ])
    return reader


def eta_response(question, message, **updates):
    fields = {"state": "classified", "intent": "arrival_time", "response": "provided",
              "request_quote": question, "reply_quote": message}
    fields.update(updates)
    return OllamaResponse({"done": True, "message": {"role": "assistant", "content": json.dumps(fields)}})


def test_eta_interpretation_receives_the_two_original_texts():
    question = "Any idea when the ship gets here?"
    sent = "We expect her in Rotterdam on 16 March at 11:00 local time."
    reader = reader_with_responses(eta_response(question, sent))
    assert reader.interpret_eta(question, sent) == EtaReading(
        intent="arrival_time", response="provided", request_quote=question, reply_quote=sent,
    )
    call = reader._session.post.call_args_list[-1]
    assert call.args == ("http://127.0.0.1:11434/api/chat",)
    payload = call.kwargs["json"]
    assert len(payload["messages"]) == 2
    assert json.loads(payload["messages"][1]["content"]) == {"customer_question": question, "sent_reply": sent}
    assert "tools" not in payload and payload["stream"] is False


@pytest.mark.parametrize("updates", [
    {"request_quote": None},
    {"request_quote": "a different question"},
    {"reply_quote": "11:30 local time"},
    {"reply_quote": " "},
    {"reply_quote": None},
    {"intent": "other"},
    {"response": "resolved"},
    {"state": "needs_review"},
])
def test_eta_reading_rejects_unsupported_classification(updates):
    question = "Any idea when the ship gets here?"
    sent = "We expect her in Rotterdam on 16 March at 11:00 local time."
    reader = reader_with_responses(eta_response(question, sent, **updates))
    assert reader.interpret_eta(question, sent) == EtaReading(state="needs_review")


def test_eta_pair_cache_and_reply_reader_share_budget():
    arrival = "When do you expect the ship to dock?"
    status = "Has the ship left?"
    sent = "The ship has left."
    reader = reader_with_responses(
        eta_response(arrival, sent, response="omitted"),
        eta_response(status, sent, intent="other", response="unknown", reply_quote=None),
        chat_response(),
        max_reads=3,
    )
    assert reader.interpret_eta("", sent).state == "needs_review"
    assert reader.interpret_eta(arrival, "x" * 6000).state == "needs_review"
    eta = reader.interpret_eta(arrival, sent)
    assert eta.response == "omitted"
    assert reader.interpret_eta(status, sent).intent == "other"
    assert reader(sent) == ReplyClaims()
    assert reader.interpret_eta(arrival, sent) == eta
    assert reader.interpret_eta(arrival, "A fresh message").state == "unavailable"
    assert reader("A fresh message").state == "unavailable"
    assert reader.reads == 3
    assert reader._session.post.call_count == 4


def test_eta_promise_is_rejected_as_a_provided_time_even_with_verbatim_quote():
    question = "When should we expect the ship?"
    message = "We will send you the ETA on 16 March at 11:00 local time."
    reader = reader_with_responses(eta_response(question, message))
    assert reader.interpret_eta(question, message) == EtaReading(state="needs_review")


def test_grounded_claims_use_only_sent_text_and_local_endpoint():
    status = {"status": "arrived", "subject": "vessel", "quote": "The vessel docked"}
    action = {"action": "opened_case", "quote": "I opened case C-41", "case_id": "C-41"}
    reader = reader_with_responses(chat_response([status], [action]))
    message = "The vessel docked. I opened case C-41."
    assert reader(message) == ReplyClaims((StatusClaim(**status),), (ActionClaim(**action),))
    calls = reader._session.post.call_args_list
    assert calls[0].args == ("http://127.0.0.1:11434/api/show",)
    assert calls[0].kwargs["json"] == {"model": "local:instruct"}
    assert calls[1].args == ("http://127.0.0.1:11434/api/chat",)
    body = calls[1].kwargs["json"]
    assert body["messages"][1:] == [{"role": "user", "content": message}]
    assert len(body["messages"]) == 2
    assert "tools" not in body and body["stream"] is False
    assert set(body["format"]["required"]) == {"status_claims", "action_claims", "state"}
    assert all(call.kwargs["allow_redirects"] is False for call in calls)
    assert reader._session.trust_env is False


@pytest.mark.parametrize("claim", [
    {"status": "arrived", "subject": "vessel", "quote": "The vessel arrived"},
    {"status": "arrived", "subject": "vessel", "quote": "vessel REF-21 docked", "reference": "REF-2"},
    {"status": "dock", "subject": "vessel", "quote": "vessel REF-21 docked"},
])
def test_invalid_claim_requires_review(claim):
    reader = reader_with_responses(chat_response([claim]))
    assert reader("The vessel REF-21 docked.") == ReplyClaims(state="needs_review")


def test_case_id_must_be_inside_the_action_quote():
    reader = reader_with_responses(chat_response(action_claims=[{
        "action": "opened_case", "quote": "I opened a new case", "case_id": "C-41",
    }]))
    assert reader("The old case was C-41. I opened a new case.") == ReplyClaims(state="needs_review")


def test_claims_are_not_accepted_when_model_requests_review():
    quote = "I notified the operations team."
    reader = reader_with_responses(OllamaResponse({"done": True, "message": {
        "role": "assistant",
        "content": json.dumps({
            "state": "needs_review", "status_claims": [],
            "action_claims": [{"action": "routed_to_operations", "quote": quote}],
        }),
    }}))
    assert reader(quote) == ReplyClaims(state="needs_review")


@pytest.mark.parametrize("content", [
    "{}", "bad json", '{"state":"extracted","state":"needs_review","status_claims":[],"action_claims":[]}',
])
def test_missing_or_ambiguous_extraction_envelope_requires_review(content):
    reader = reader_with_responses(OllamaResponse({"done": True,
        "message": {"role": "assistant", "content": content},
    }))
    assert reader("A genuine sent reply") == ReplyClaims(state="needs_review")


def test_run_budget_counts_unique_requests_and_cached_results_still_available():
    reader = reader_with_responses(chat_response(), max_reads=1)
    assert reader("") == ReplyClaims(state="needs_review")
    assert reader("x" * 6_001) == ReplyClaims(state="needs_review")
    assert reader("An exact sent reply") == ReplyClaims()
    assert reader("A different message") == ReplyClaims(state="unavailable")
    assert reader("An exact sent reply") == ReplyClaims()
    assert reader.reads == 1
    assert reader._session.post.call_count == 2


def test_rejects_remote_alias_before_sending_reply():
    with pytest.raises(ValueError):
        OllamaClaimReader("local:cloud")
    with pytest.raises(ValueError):
        OllamaClaimReader("ollama.com/library/example")
    reader = OllamaClaimReader("local-alias")
    reader._session.post = Mock(return_value=OllamaResponse({
        "capabilities": ["completion"], "remote_host": "https://ollama.com",
    }))
    assert reader("Prospective customer data") == ReplyClaims(state="unavailable")
    assert reader._session.post.call_count == 1
    assert reader.reads == 0


def test_transport_failure_stops_further_chat_attempts():
    reader = reader_with_responses(requests.Timeout("offline"))
    assert reader("First sent reply") == ReplyClaims(state="unavailable")
    assert reader("Second sent reply") == ReplyClaims(state="unavailable")
    assert reader.reads == 1
    assert reader._session.post.call_count == 2


def test_truncated_output_requires_review():
    reader = reader_with_responses(chat_response(done_reason="length"))
    assert reader("A genuine sent reply") == ReplyClaims(state="needs_review")
