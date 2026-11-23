import json

import pytest

from replay.__main__ import PRICES, main, run_trial
from replay.openai_provider import ProviderError
from replay.world import load_cases


class TwoTurnProvider:
    def __init__(self):
        self.calls = []

    def turn(self, model, system, items, tools, max_output_tokens):
        self.calls.append(json.loads(json.dumps(items)))
        if len(self.calls) == 1:
            output = [{"type": "function_call", "call_id": "lookup-1", "name": "lookup_tracking",
                       "arguments": '{"reference":"MISSING","container_ref":null}'}]
        else:
            assert items[-1]["type"] == "function_call_output"
            assert items[-1]["call_id"] == "lookup-1"
            assert isinstance(json.loads(items[-1]["output"]), dict)
            output = [{"type": "message", "content": [{"type": "output_text", "text": "{}"}]}]
        return {"status": "completed", "items": output, "usage": {"input_tokens": 100, "output_tokens": 10},
                "model": model, "response_id": f"reply-{len(self.calls)}"}


def test_runner_measures_executed_tools_and_prices_every_call():
    p = TwoTurnProvider()
    case = load_cases("smoke")[0]
    record = run_trial(p, "gpt-6.1-terra", case, before_call=lambda _: True, max_turns=4, max_output_tokens=500)
    assert '"expected"' not in json.dumps(p.calls[0])
    assert record["status"] == "completed"
    assert record["grade"]["overall"] is False
    assert record["tool_calls"][0]["call_id"] == "lookup-1"
    assert record["observed_usage"] == {"input_tokens": 200, "output_tokens": 20}
    assert record["cost_estimate_usd"] == "0.00030"


def test_failed_request_keeps_unmeasured_cost_unknown(monkeypatch):
    p = TwoTurnProvider()

    def error(*args):
        raise ProviderError("transport", "Mock request failed.")

    monkeypatch.setattr(p, "turn", error)
    record = run_trial(p, "gpt-6-luna", load_cases("smoke")[0],
                       before_call=lambda _: True, max_turns=4, max_output_tokens=500)
    assert record["status"] == "provider_error"
    assert record["grade"] is None
    assert record["cost_estimate_usd"] is None
    assert record["metering_complete"] is False


def test_cli_rehearsal_does_not_instantiate_live_client(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "SHOULD-NOT-BE-USED")

    def forbidden(*args, **kwargs):
        raise AssertionError("dry-run opened a paid client")

    monkeypatch.setattr("replay.__main__.OpenAIProvider", forbidden)
    output = tmp_path / "rehearsal"
    assert main(["--output", str(output)]) == 0
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    records = [json.loads(line) for line in (output / "trials.jsonl").read_text(encoding="utf-8").splitlines()]
    assert set(summary["by_model"]) == set(PRICES)
    assert summary["mode"] == "protocol_rehearsal_only"
    assert summary["calls_attempted"] == 0
    assert summary["expected_trials"] == 2 * len(manifest["case_ids"]) == len(records)
    assert summary["complete_pairs"] == len(manifest["case_ids"])
    assert summary["paired_summary"]["mean_incremental_api_cost_usd"] is None
    assert {r["turns"][0]["model"] for r in records} == {"scripted-rehearsal"}
    for record in records:
        exports = output / record["canonical_exports"]
        assert exports.is_dir()
        assert not any("truth" in path.name for path in exports.iterdir())
        verification = json.loads((exports.parent / "verification.json").read_text(encoding="utf-8"))
        assert len(verification["enquiries"]) == 1


def test_ollama_feeds_tool_results_back_and_exports_without_cloud_cost(tmp_path, monkeypatch):
    from replay.ollama_provider import OllamaProvider

    def post(self, endpoint, payload):
        if endpoint == "show":
            return {"capabilities": ["completion", "tools"]}
        assert endpoint == "chat"
        assert payload["model"] == "local-test:7b"
        assert not payload["stream"] and not self._session.trust_env
        assert '"expected"' not in json.dumps(payload)
        tail = payload["messages"][-1]
        if tail["role"] == "user":
            message = {"tool_calls": [{"function": {"name": "lookup_tracking", "arguments": {
                "reference": "TEST-BKG-A", "container_ref": None,
            }}}]}
        else:
            assert tail["tool_name"] == "lookup_tracking"
            assert json.loads(tail["content"])["status"] == "ok"
            message = {"content": "{}"}
        return {"done": True, "done_reason": "stop", "message": {"role": "assistant", **message},
                "prompt_eval_count": 60, "eval_count": 10}

    monkeypatch.setattr(OllamaProvider, "_post", post)
    output = tmp_path / "local"
    assert main(["--ollama", "local-test:7b", "--case-id", "R01", "--output", str(output)]) == 0
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    record = json.loads((output / "trials.jsonl").read_text(encoding="utf-8"))
    assert summary["mode"] == "local_ollama_development"
    assert summary["recorded_trials"] == 1 and summary["calls_attempted"] == 2
    assert summary["paired_summary"] is None and summary["known_cost_estimate_usd"] is None
    assert record["grade"]["overall"] is False and record["cost_estimate_usd"] is None
    assert record["observed_usage"] == {"input_tokens": 120, "output_tokens": 20}
    assert (output / record["canonical_exports"]).is_dir()


def test_ollama_rejects_remote_model_alias(monkeypatch):
    from replay.ollama_provider import OllamaProvider

    provider = OllamaProvider()
    monkeypatch.setattr(provider, "_post", lambda *args: {"capabilities": ["tools"], "remote_model": "example"})
    with pytest.raises(ProviderError, match="runs on this laptop"):
        provider.check_model("example")


def test_verified_escalation_comes_from_world_and_excludes_future_history(tmp_path):
    from replay.exports import export_and_verify
    from replay.world import World

    case = load_cases("smoke")[1]
    world = World(case)
    lookup = {"reference": "TEST-BKG-A", "container_ref": None}
    tracking = world.call("lookup_tracking", lookup)
    event = world.call("open_case", lookup | {"reason": "delay"})
    answer = {"reply": "I opened a delay case.", "action": "escalate", "booking_ref": "TEST-BKG-A",
              "container_ref": None, "status": "departed", "eta": "2026-03-14T14:00:00+00:00",
              "location": "LBBEY", "evidence_ids": ["TRACK-DEPART", "TRACK-LATE"], "case_id": event["case_id"]}
    out = export_and_verify(case, {"requested_model": "agent", "answer": json.dumps(answer),
                                   "case_events": world.case_events,
                                   "tool_calls": [{"name": "lookup_tracking", "arguments": lookup, "result": tracking}]},
                            tmp_path / "exports")
    assert out["input_issues"] == []
    verified = out["enquiries"][0]["verification"]
    assert verified["case_ids"] == [event["case_id"]]
    assert verified["resolved_at"] is None
    assert verified["human_recovery"] is None


def test_budget_guard_does_not_make_provider_call():
    p = TwoTurnProvider()
    record = run_trial(p, "gpt-6-luna", load_cases("smoke")[0], before_call=lambda _: False,
                       max_turns=3, max_output_tokens=500)
    assert p.calls == []
    assert record["grade"] is None and record["status"] == "budget_or_call_limit"


def test_reviewer_provided_suite_keeps_labels_out_of_review_file(tmp_path):
    case = load_cases("challenge")[0]
    suite = tmp_path / "reviewer.json"
    suite.write_text(json.dumps({"origin": "synthetic", "cases": [case]}), encoding="utf-8")
    output = tmp_path / "separate"
    assert main(["--suite", str(suite), "--output", str(output)]) == 0
    reviewers = [json.loads(line) for line in (output / "reviewer_cases.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(reviewers) == 2
    assert all(r["case_id"] == case["id"] and not ({"grade", "expected", "usage", "model"} & r.keys()) for r in reviewers)
