"""Run a bounded paired replay: python -m replay --help."""

import argparse
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

from .exports import export_and_verify
from .ollama_provider import OllamaProvider
from .openai_provider import OpenAIProvider, ProviderError, REASONING_EFFORT, REQUESTED_SERVICE_TIER
from .world import ANSWERS, SYSTEM_PROMPT, WORLD_TOOLS, World, load_cases, public_trial_inputs


# Standard text rates per million tokens, checked against official model pages.
# Use full input rate even for cache hits. Defaults cover only these tested adapters.
PRICES = {"gpt-6-luna": ("0.10", "0.50"), "gpt-6.1-terra": ("1.00", "5.00")}
RATE_VERSION = "2026-11-21/openai-standard-short-context"
MILLION = Decimal(1_000_000)
SMALL_CALL_INPUT_ALLOWANCE = 12_000


def encode(data):
    return json.dumps(data, ensure_ascii=False, allow_nan=False, sort_keys=True)


def _cost(model, usage):
    if usage is None:
        return None
    a, b = map(Decimal, PRICES[model])
    return (a * usage["input_tokens"] + b * usage["output_tokens"]) / MILLION


def _json_args(text):
    def unique(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError("duplicate argument")
            out[key] = value
        return out

    def no_constant(value):
        raise ValueError("invalid argument")

    try:
        value = json.loads(text, object_pairs_hook=unique, parse_constant=no_constant)
        return value if isinstance(value, dict) else None
    except (TypeError, ValueError, RecursionError):
        return None


def _final_text(items):
    parts = []
    for item in items:
        chunks = item.get("content")
        if item.get("type") == "message" and isinstance(chunks, list):
            parts.extend(chunk["text"] for chunk in chunks if isinstance(chunk, dict)
                         and chunk.get("type") == "output_text" and isinstance(chunk.get("text"), str))
    return "\n".join(parts)


def run_trial(provider, model, case, *, before_call, max_turns, max_output_tokens, price_api=True):
    """Run against a fresh world. Provider replies are never proof a tool ran."""
    world = World(case)
    items = [{"role": "user", "content": public_trial_inputs(case)}]
    turns, actions, seen = [], [], set()
    answer, result, pending = "", "turn_limit", False
    observed_cost = Decimal(0)
    observed_usage = {"input_tokens": 0, "output_tokens": 0}
    metering_complete = True
    started = time.perf_counter()
    for _ in range(max_turns):
        if not before_call(model):
            result = "budget_or_call_limit"
            break
        step_started = time.perf_counter()
        try:
            turn = provider.turn(model, SYSTEM_PROMPT, items, WORLD_TOOLS, max_output_tokens)
        except ProviderError as exc:
            turns.append({"status": "provider_error", "kind": exc.kind, "http_status": exc.http_status,
                          "request_id": exc.request_id, "usage": None,
                          "elapsed_seconds": round(time.perf_counter() - step_started, 4)})
            metering_complete = False
            result = "provider_error"
            break
        usage = turn["usage"]
        turns.append({key: turn.get(key) for key in (
            "response_id", "model", "status", "usage", "usage_details", "service_tier", "incomplete_reason")} | {
            "elapsed_seconds": round(time.perf_counter() - step_started, 4)})
        if usage is None:
            metering_complete = False
        else:
            if price_api:
                observed_cost += _cost(model, usage)
            for key in observed_usage:
                observed_usage[key] += usage[key]
        if turn["status"] != "completed":
            result = "provider_response_" + turn["status"]
            break
        output = turn["items"]
        calls = [i for i in output if i.get("type") == "function_call"]
        if not calls:
            answer = _final_text(output)
            result = "completed" if answer else "no_final_reply"
            break
        ids = [call.get("call_id") for call in calls]
        if (len(calls) > 1 or any(not isinstance(i, str) or not i or i in seen for i in ids)
                or len(set(ids)) != len(ids)):
            result = "invalid_tool_protocol"
            break
        # Do not mutate even the sandbox if no remaining turn can read the result.
        if len(turns) == max_turns:
            break
        items.extend(output)
        for call in calls:
            call_id = call["call_id"]
            seen.add(call_id)
            name = call.get("name")
            args = _json_args(call.get("arguments"))
            if args is None or name not in {item["name"] for item in WORLD_TOOLS}:
                tool_result = {"error": "invalid_tool_or_arguments"}
            else:
                tool_result = world.call(name, args)
            actions.append({"call_id": call_id, "name": name, "arguments": args, "result": tool_result})
            items.append({"type": "function_call_output", "call_id": call_id, "output": encode(tool_result)})
        pending = True
    # Limits and provider faults are separate from a completed agent answer.
    grade = world.grade(answer) if result == "completed" else None
    return {"status": result, "requested_model": model, "turns": turns, "tool_calls": actions,
            "world_events": world.tool_events, "case_events": world.case_events,
            "answer": answer or None, "grade": grade, "tool_used": pending,
            "elapsed_seconds": round(time.perf_counter() - started, 4), "observed_usage": observed_usage,
            "metering_complete": metering_complete,
            "known_cost_estimate_usd": str(observed_cost) if price_api else None,
            "cost_estimate_usd": str(observed_cost) if price_api and metering_complete else None}


def _manifest(args, cases):
    h = hashlib.sha256(encode({"cases": cases, "tools": WORLD_TOOLS, "instructions": SYSTEM_PROMPT}).encode())
    for path in sorted(Path(__file__).parent.glob("*.py")):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    manifest = {"schema_version": "shipment-replay-1", "split": args.split, "models": list(PRICES),
            "case_source": "reviewer_supplied_synthetic" if args.suite else "checked_in_synthetic",
            "mode": "live_models_synthetic_shipments" if args.live else "protocol_rehearsal_only",
            "case_ids": [c["id"] for c in cases], "suite_sha256": h.hexdigest(),
            "repeats": args.repeats, "max_turns": args.max_turns, "max_output_tokens": args.max_output_tokens,
            "max_api_calls": args.max_api_calls, "local_estimated_spend_stop_usd": str(args.max_usd),
            "requested_reasoning_effort": REASONING_EFFORT, "requested_service_tier": REQUESTED_SERVICE_TIER,
            "rate_version": RATE_VERSION, "usd_per_million_input_output": PRICES,
            "call_input_token_allowance": SMALL_CALL_INPUT_ALLOWANCE,
            "limits": "Standard-rate equivalent before cache adjustments and tax. The local spend stop is approximate. Review provider billing, especially after a timeout."}
    if args.ollama:
        manifest.update(models=[args.ollama], mode="local_ollama_development", requested_reasoning_effort=None,
                        requested_service_tier=None, rate_version=None, usd_per_million_input_output=None,
                        local_estimated_spend_stop_usd=None, call_input_token_allowance=None,
                        limits="Loopback inference with a local model. Hosted API pricing does not apply. Local compute cost is unmeasured.")
    return manifest


def _write(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(encode(value) + "\n", encoding="utf-8")
    temp.replace(path)


def _schedule(cases, repeats, models):
    for ix, c in enumerate(cases):
        for rep in range(1, repeats + 1):
            order = models if (ix + rep) % 2 else tuple(reversed(models))
            for model in order:
                yield c, rep, model


def load_reviewer_suite(path):
    """Load the same row structure as author fixtures from a separately held file."""
    if path.stat().st_size > 2_000_000:
        raise ValueError("synthetic suite exceeds 2 MB")
    source = _json_args(path.read_text(encoding="utf-8-sig"))
    if not source or set(source) != {"origin", "cases"} or source.get("origin") != "synthetic":
        raise ValueError("expected a JSON object declaring synthetic origin and cases")
    cases = source.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 250:
        raise ValueError("reviewer suite needs 1 to 250 cases")
    used = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != {
            "id", "split", "message", "account_id", "now", "shipments", "events", "source_complete", "expected"
        }:
            raise ValueError("reviewer case fields must match the authored case template")
        case_id = case["id"]
        if not isinstance(case_id, str) or not re.fullmatch(r"[A-Z][A-Z0-9_-]{0,39}", case_id) or case_id in used:
            raise ValueError("reviewer case identifiers must be safe and unique")
        used.add(case_id)
        if (not isinstance(case["message"], str) or not 0 < len(case["message"]) <= 2000
                or not isinstance(case["account_id"], str) or not case["account_id"].startswith("TEST-")
                or type(case["source_complete"]) is not bool or case["split"] != "challenge"):
            raise ValueError("reviewer cases must be synthetic challenge cases with TEST- account IDs")
        expected = case["expected"]
        if (not isinstance(expected, dict) or set(expected) != ((ANSWERS - {"reply", "case_id"}) | {"case_required"})
                or type(expected["case_required"]) is not bool or not isinstance(expected["evidence_ids"], list)
                or not all(isinstance(i, str) for i in expected["evidence_ids"])):
            raise ValueError("reviewer case reference label has an invalid shape")
        keys = (("shipments", {"booking_ref", "bl_ref", "account_id", "container_refs", "origin", "destination", "planned_eta"}),
                ("events", {"event_id", "booking_ref", "container_ref", "event_type", "event_type_code", "classifier",
                            "event_datetime", "event_created_datetime", "location"}))
        for collection, required in keys:
            rows = case[collection]
            if (not isinstance(rows, list) or len(rows) > 100
                    or any(not isinstance(row, dict) or set(row) != required for row in rows)):
                raise ValueError(f"invalid reviewer {collection} rows")
            for row in rows:
                if any(key != "container_refs" and value is not None
                       and (not isinstance(value, str) or len(value) > 200)
                       for key, value in row.items()):
                    raise ValueError(f"invalid reviewer {collection} field value")
                if collection == "shipments":
                    if (not all(isinstance(row[key], str) and row[key].startswith("TEST-")
                                for key in ("booking_ref", "bl_ref", "account_id"))
                            or not isinstance(row["container_refs"], list)
                            or len(row["container_refs"]) > 20
                            or not all(isinstance(i, str) and 5 <= len(i) <= 80 and i.startswith("TEST-")
                                       for i in row["container_refs"])):
                        raise ValueError("reviewer shipment references must start with TEST-")
                elif not isinstance(row["booking_ref"], str) or not row["booking_ref"].startswith("TEST-"):
                    raise ValueError("reviewer event booking references must start with TEST-")
        World(case)  # Validate the supplied synthetic observation clock.
    return cases


def _summary(manifest, records):
    by_model = {}
    models = manifest["models"]
    local = manifest["mode"] == "local_ollama_development"
    for model in models:
        rows = [r for r in records if r["requested_model"] == model]
        graded = [r["grade"] for r in rows if r["grade"] is not None]
        by_model[model] = {"recorded_trials": len(rows), "graded_trials": len(graded),
                           "passed_trials": sum(g["overall"] is True for g in graded),
                           "critical_trials": sum(g["critical"] is True for g in graded),
                           "ungraded_trials": len(rows) - len(graded),
                           "unknown_metering_trials": sum(not r["metering_complete"] for r in rows),
                           "known_cost_estimate_usd": None if local else str(sum(Decimal(r["known_cost_estimate_usd"]) for r in rows))}
    summary = {"mode": manifest["mode"], "expected_trials": len(manifest["case_ids"]) * manifest["repeats"] * len(models),
               "recorded_trials": len(records), "by_model": by_model,
               "inference": "Descriptive sandbox results only. No company savings or causal impact."}
    if local:
        return summary | {"complete_pairs": 0, "paired_summary": None}
    pairs = {}
    for row in records:
        if row["grade"] is not None:
            pairs.setdefault((row["case_id"], row["repeat"]), {})[row["requested_model"]] = row
    baseline, candidate = models
    complete = [(p[baseline], p[candidate]) for p in pairs.values() if set(p) == set(models)]
    n = len(complete)
    paired_status = {"both_passed": 0, "only_baseline_passed": 0, "only_candidate_passed": 0, "neither_passed": 0}
    for a, b in complete:
        passes = (a["grade"]["overall"] is True, b["grade"]["overall"] is True)
        paired_status[{(True, True): "both_passed", (True, False): "only_baseline_passed",
                       (False, True): "only_candidate_passed", (False, False): "neither_passed"}[passes]] += 1
    priced_pairs = [(Decimal(a["cost_estimate_usd"]), Decimal(b["cost_estimate_usd"])) for a, b in complete
                    if a["cost_estimate_usd"] is not None and b["cost_estimate_usd"] is not None]
    if manifest["mode"] != "live_models_synthetic_shipments":
        priced_pairs = []
    paired_data = {
        "baseline": baseline, "candidate": candidate, "both_graded_pairs": n, "fully_metered_pairs": len(priced_pairs),
        "pass_counts": paired_status,
        "pass_rate_difference": (paired_status["only_candidate_passed"] - paired_status["only_baseline_passed"]) / n if n else None,
        "mean_latency_difference_seconds": round(sum(b["elapsed_seconds"] - a["elapsed_seconds"] for a, b in complete) / n, 4) if n else None,
        "mean_incremental_api_cost_usd": str(sum(b - a for a, b in priced_pairs) / len(priced_pairs)) if priced_pairs else None,
    }
    return summary | {"complete_pairs": n, "paired_summary": paired_data}


class RehearsalProvider:
    """Exercise a real lookup and final-message handoff without claiming a model ran."""

    def turn(self, model, system, items, tools, max_output_tokens):
        # A deliberately unhelpful, fully scripted response; test real behavior with --live.
        first = len(items) == 1
        if first:
            out = [{"type": "function_call", "name": "lookup_tracking", "call_id": "rehearsal-lookup",
                    "arguments": encode({"reference": "REHEARSAL-MISSING", "container_ref": None})}]
        else:
            out = [{"type": "message", "content": [{"type": "output_text", "text": encode({
                "reply": "I cannot verify the requested shipment in this scripted dry run.", "action": "cannot_verify",
                "booking_ref": None, "container_ref": None, "status": None, "eta": None, "location": None,
                "evidence_ids": [], "case_id": None})}]}]
        return {"status": "completed", "items": out, "usage": {"input_tokens": 0, "output_tokens": 0},
                "model": "scripted-rehearsal", "response_id": "rehearsal-lookup" if first else "rehearsal-answer"}


def replay(args, cases, provider):
    manifest = _manifest(args, cases)
    run = args.output.resolve()
    run.mkdir(parents=True, exist_ok=False)
    _write(run / "manifest.json", manifest)
    records, calls = [], 0
    spend = Decimal(0)
    trial_cost = Decimal(0)

    def before_call(model):
        nonlocal calls, trial_cost
        if args.live:
            # Reserve a per-call allowance within the trial since sibling turns are not settled yet.
            estimate = _cost(model, {"input_tokens": SMALL_CALL_INPUT_ALLOWANCE,
                                     "output_tokens": args.max_output_tokens})
            if calls >= args.max_api_calls or spend + trial_cost + estimate > args.max_usd:
                return False
            calls += 1
            trial_cost += estimate
        elif args.ollama:
            if calls >= args.max_api_calls:
                return False
            calls += 1
        return True

    try:
        with ((run / "trials.jsonl").open("x", encoding="utf-8") as stream,
              (run / "reviewer_cases.jsonl").open("x", encoding="utf-8") as review):
            for case, repeat, model in _schedule(cases, args.repeats, manifest["models"]):
                trial_cost = Decimal(0)
                result = run_trial(provider, model, case, before_call=before_call,
                                   max_turns=args.max_turns, max_output_tokens=args.max_output_tokens,
                                   price_api=not args.ollama)
                record = {"case_id": case["id"], "repeat": repeat,
                          "finished_at": datetime.now(UTC).isoformat(), **result}
                trial_dir = run / "observations" / f"trial-{len(records) + 1:04d}"
                record["canonical_exports"] = (trial_dir / "exports").relative_to(run).as_posix()
                verifier_result = export_and_verify(case, record, trial_dir / "exports")
                _write(trial_dir / "verification.json", verifier_result)
                stream.write(encode(record) + "\n")
                stream.flush()
                # Share this file alone for independent review. Exclude model,
                # grades, usage and gold labels.
                review.write(encode({
                    "review_id": f"trial-{len(records) + 1:04d}", "case_id": case["id"], "repeat": repeat,
                    "enquiry": case["message"], "synthetic_at": case["now"], "reply": result["answer"],
                    "source_complete": case["source_complete"],
                    "tool_calls": result["tool_calls"], "case_events": result["case_events"],
                }) + "\n")
                review.flush()
                records.append(record)
                if not args.ollama:
                    spend += Decimal(record["known_cost_estimate_usd"])
                if ((args.live or args.ollama) and result["status"] in {"provider_error", "budget_or_call_limit"}
                        or args.live and not result["metering_complete"]):
                    break
    finally:
        overview = _summary(manifest, records) | {"calls_attempted": calls,
                                                    "known_cost_estimate_usd": None if args.ollama else str(spend)}
        _write(run / "summary.json", overview)
    return overview


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    provider_options = p.add_mutually_exclusive_group()
    provider_options.add_argument("--live", action="store_true", help="Opt in to billable calls using OPENAI_API_KEY.")
    provider_options.add_argument("--ollama", metavar="MODEL", help="Run one installed tool-capable Ollama model locally.")
    p.add_argument("--preflight", action="store_true", help="Print cases and settings without making calls.")
    p.add_argument("--split", choices=("smoke", "development", "challenge", "all"), default="smoke")
    p.add_argument("--suite", type=Path, help="Use a separately reviewed synthetic JSON suite instead of built-in cases.")
    p.add_argument("--case-id", action="append", help="Run an individual case in the selected split. Repeat for several cases.")
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--max-turns", type=int, default=4)
    p.add_argument("--max-output-tokens", type=int, default=800)
    p.add_argument("--max-api-calls", type=int, default=50, help="Maximum provider turns for either live mode.")
    p.add_argument("--max-usd", type=Decimal, default=Decimal("2.00"), help="Approximate local USD stop; use a provider cap as well.")
    p.add_argument("--output", type=Path, help="A new output directory outside tracked source files.")
    try:
        args = p.parse_args(argv)
    except InvalidOperation:
        p.error("--max-usd must be a valid decimal")
    if (not 1 <= args.repeats <= 10 or not 2 <= args.max_turns <= 8 or not 100 <= args.max_output_tokens <= 4000
            or not 1 <= args.max_api_calls <= 20_000 or not args.max_usd.is_finite() or not 0 < args.max_usd <= 150):
        p.error("settings out of range; see --help")
    try:
        cases = load_reviewer_suite(args.suite) if args.suite else load_cases(None if args.split == "all" else args.split)
    except (ValueError, OSError) as exc:
        p.error(str(exc))
    if args.suite:
        args.split = "reviewer_suite"
    if args.case_id:
        selected = set(args.case_id)
        missing = selected - {case["id"] for case in cases}
        if missing:
            p.error("case IDs not found in the selected suite or split: " + ", ".join(sorted(missing)))
        cases = [case for case in cases if case["id"] in selected]
    if not cases:
        p.error("no cases in selected split")
    if args.preflight:
        print(encode(_manifest(args, cases)))
        return 0
    if args.output is None:
        p.error("--output is required (choose a directory that does not exist yet)")
    key = os.getenv("OPENAI_API_KEY", "").strip() if args.live else None
    if args.live and not key:
        p.error("OPENAI_API_KEY is required for --live; run without --live to rehearse")
    try:
        if args.ollama:
            provider = OllamaProvider()
            provider.check_model(args.ollama)
        else:
            provider = OpenAIProvider(key) if args.live else RehearsalProvider()
        result = replay(args, cases, provider)
    except ProviderError as exc:
        p.error(str(exc))
    except FileExistsError:
        p.error("output already exists; use a new directory to preserve earlier records")
    print(encode(result))
    return 2 if result["recorded_trials"] != result["expected_trials"] or any(
        r["ungraded_trials"] for r in result["by_model"].values()) else 0


if __name__ == "__main__":
    sys.exit(main())
