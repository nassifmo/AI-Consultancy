"""Exercise the Responses protocol and failure telemetry without a live API."""

import json
from unittest.mock import patch

import pytest
import requests

from replay.openai_provider import OpenAIProvider, ProviderError


KEY = "dummy-test-key"
MODEL = "gpt-6-luna"
SYSTEM = "Use the local tool for status."
CASE = {"role": "user", "content": "Where is container TEST-42?"}
TOOLS = [{
    "type": "function",
    "name": "get_tracking",
    "parameters": {"type": "object", "properties": {"container": {"type": "string"}},
                   "required": ["container"], "additionalProperties": False},
    "strict": True,
}]


def api_response(payload, *, status_code=200, request_id="req_test42"):
    response = requests.Response()
    response.status_code = status_code
    response.headers["x-request-id"] = request_id
    response._content = json.dumps(payload).encode("utf-8")
    return response


def test_stateless_tool_round_trip_and_token_usage():
    reasoning = {"type": "reasoning", "id": "rs_42", "summary": [],
                 "encrypted_content": "example-encrypted-reasoning"}
    function = {"type": "function_call", "id": "fc_42", "name": "get_tracking",
                "arguments": '{"container":"TEST-42"}', "call_id": "call_42", "status": "completed"}
    tool_answer = {"type": "function_call_output", "call_id": "call_42", "output": '{"status":"in_transit"}'}
    answer = {"type": "message", "id": "msg_42", "role": "assistant", "status": "completed",
              "phase": "final_answer", "content": [{"type": "output_text", "text": "It is in transit."}]}
    usage = {"input_tokens": 40, "output_tokens": 19, "input_tokens_details": {"cached_tokens": 2}}
    first = api_response({"id": "resp_first", "status": "completed", "model": "gpt-6-luna-snapshot",
                          "service_tier": "default",
                          "output": [reasoning, function], "usage": usage})
    second = api_response({"id": "resp_second", "status": "completed", "output": [answer], "usage": usage})
    provider = OpenAIProvider(KEY, timeout=13)
    with patch("replay.openai_provider.requests.post", side_effect=[first, second]) as post:
        turn = provider.turn(MODEL, SYSTEM, [CASE], TOOLS, 1024)
        final = provider.turn(MODEL, SYSTEM, [CASE, *turn["items"], tool_answer], TOOLS, 1024)
    assert turn["items"] == [reasoning, function]
    assert turn["response_id"] == "resp_first"
    assert turn["model"] == "gpt-6-luna-snapshot"
    assert turn["service_tier"] == "default"
    assert turn["usage"] == {"input_tokens": 40, "output_tokens": 19}
    assert turn["usage_details"] == usage
    assert final["model"] == MODEL
    assert final["items"] == [answer]
    assert final["status"] == "completed"
    args, kwargs = post.call_args_list[1]
    assert args == ("https://api.openai.com/v1/responses",)
    assert kwargs["headers"]["Authorization"] == f"Bearer {KEY}"
    assert kwargs["timeout"] == (10, 13)
    assert kwargs["allow_redirects"] is False
    assert kwargs["json"] == {
        "model": MODEL, "instructions": SYSTEM, "input": [CASE, reasoning, function, tool_answer],
        "tools": TOOLS, "max_output_tokens": 1024, "parallel_tool_calls": False,
        "reasoning": {"effort": "low"}, "service_tier": "default",
        "store": False, "include": ["reasoning.encrypted_content"],
    }


@pytest.mark.parametrize("status,kind", [(302, "request_rejected"), (401, "authorization"),
    (403, "authorization"), (429, "rate_limit"), (503, "provider_unavailable")])
def test_http_error_is_safe_and_is_not_retried(status, kind):
    provider = OpenAIProvider(KEY)
    with patch("replay.openai_provider.requests.post",
               return_value=api_response({"error": {"message": KEY}}, status_code=status)) as post:
        with pytest.raises(ProviderError) as exc:
            provider.turn(MODEL, SYSTEM, [CASE], TOOLS, 1024)
    assert exc.value.kind == kind
    assert exc.value.request_id == "req_test42"
    assert exc.value.http_status == status
    assert KEY not in str(exc.value)
    post.assert_called_once()


@pytest.mark.parametrize("error,kind", [(requests.Timeout(KEY), "timeout"),
                                       (requests.ConnectionError(KEY), "transport")])
def test_request_error_is_not_retained_on_exception(error, kind):
    with patch("replay.openai_provider.requests.post", side_effect=error) as post:
        with pytest.raises(ProviderError) as exc:
            OpenAIProvider(KEY).turn(MODEL, SYSTEM, [CASE], TOOLS, 1024)
    assert exc.value.kind == kind
    assert KEY not in str(exc.value)
    assert exc.value.__context__ is None
    assert exc.value.__cause__ is None
    post.assert_called_once()


@pytest.mark.parametrize("usage", [None, {"input_tokens": 17, "output_tokens": 1024}])
def test_incomplete_response_keeps_measured_usage_without_assuming_zero(usage):
    reply = api_response({"status": "incomplete", "id": "resp_limited", "output": [],
                          "usage": usage, "incomplete_details": {"reason": "max_output_tokens"}})
    with patch("replay.openai_provider.requests.post", return_value=reply):
        result = OpenAIProvider(KEY).turn(MODEL, SYSTEM, [CASE], TOOLS, 1024)
    assert result["status"] == "incomplete"
    assert result["usage"] == usage
    assert result["incomplete_reason"] == "max_output_tokens"


@pytest.mark.parametrize("usage", [None, {"input_tokens": True, "output_tokens": 0},
                                   {"input_tokens": 4, "output_tokens": -1}])
def test_completed_response_requires_measured_usage(usage):
    with patch("replay.openai_provider.requests.post",
               return_value=api_response({"status": "completed", "output": [], "usage": usage})):
        with pytest.raises(ProviderError, match="valid input and output token counts"):
            OpenAIProvider(KEY).turn(MODEL, SYSTEM, [CASE], TOOLS, 1024)


def test_bad_json_does_not_attach_provider_body():
    response = api_response(None, request_id=KEY)
    response._content = KEY.encode("utf-8")
    with patch("replay.openai_provider.requests.post", return_value=response):
        with pytest.raises(ProviderError) as exc:
            OpenAIProvider(KEY).turn(MODEL, SYSTEM, [CASE], TOOLS, 1024)
    assert exc.value.kind == "invalid_response"
    assert exc.value.__context__ is None
    assert exc.value.request_id is None
    assert KEY not in str(exc.value)


def test_hosted_tools_rejected_before_request():
    with patch("replay.openai_provider.requests.post") as post:
        with pytest.raises(ProviderError, match="local function tools only"):
            OpenAIProvider(KEY).turn(MODEL, SYSTEM, [CASE], [{"type": "web_search"}], 1024)
    post.assert_not_called()
