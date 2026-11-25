"""Load the hand-written scenario library (datagen/scenarios/) into partner-format tables.

Each scenario becomes its own small dataset: base customers/shipments/tracking from base.yaml,
plus the scenario's enquiries, agent runs, responses, cases, case history and human work.
Expected evaluator results are kept alongside. These golden cases are the acceptance tests
for the evaluator; they were written from the service rules, not from the generator code.

    python -m datagen.scenario_library            # validate and summarize
    python -m datagen.scenario_library --write    # write each scenario to datagen/datasets/scenarios/<id>/
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from datagen.dictionary_tools import load_dictionary, validate_records, validate_references
from datagen.generator.export import write_exports

SCENARIO_DIR = Path(__file__).resolve().parent / "scenarios"
OUT_DIR = Path(__file__).resolve().parent / "datasets" / "scenarios"
STATES = {"resolved", "escalated_open", "awaiting_customer", "closed_unresolved", "failed", "unknown", "out_of_scope"}
EXPECTED_FIELDS = {
    "state", "first_answer_correct", "info_correct", "escalation_required", "required_actions_done",
    "ai_only", "rescued", "handed_off", "repeat_contact", "self_report_false", "human_seconds",
    "clarification_requested", "escalation_triggered_at",
    "severity", "eta_error_seconds", "escalation_on_time", "escalation_delay_seconds", "initial_failure",
}
SEVERITIES = {"none", "minor", "material", "critical", "unknown"}
DEFAULT_CUSTOMER = "CUS-T1"


@dataclass
class Scenario:
    id: str
    title: str
    tests: str
    tables: dict
    expected: dict
    timezones: dict = field(default_factory=dict)
    expect_schema_issues: int = 0
    expect_reference_issues: int = 0
    rule_version: str = "0.1.0-proposed"
    data_cutoff: datetime | None = None


def _load_yaml(name: str) -> dict:
    return yaml.safe_load((SCENARIO_DIR / name).read_text(encoding="utf-8"))


def _event_rows(base: dict, drop: set[str]) -> list[dict]:
    rows = []
    for eid, ref, etype, code, cls, when, created in base["tracking_events"]:
        if ref in drop:
            continue
        rows.append({"event_id": eid, "booking_ref": ref, "container_ref": None, "event_type": etype,
                     "event_type_code": code, "classifier": cls, "event_datetime": when,
                     "event_created_datetime": created, "location": None})
    return rows


def _run_rows(sc_id: str, runs: list[dict], enquiries: dict) -> tuple[list[dict], list[dict]]:
    agent_runs, responses = [], []
    for n, r in enumerate(runs, start=1):
        q = enquiries[r["enquiry"]]
        clarification = r.get("clarification")
        lookup_reference = r.get("lookup_reference", q["stated_reference"])
        steps = []
        if lookup_reference or not clarification:
            steps.append({
                "step_no": 1, "tool_name": "lookup_shipment", "tool_input": lookup_reference,
                "tool_output": r.get("lookup_output", r.get("linked") or ("timeout" if r.get("retry") else "not_found")),
                "snapshot_time": None, "success": not r.get("retry"),
            })

        def step(name, output, inp=None, snap=None):
            steps.append({"step_no": len(steps) + 1, "tool_name": name, "tool_input": inp,
                          "tool_output": output, "snapshot_time": snap, "success": True})

        answered = not (r.get("handoff") or r.get("retry") or clarification)
        if answered:
            tracking_eta = r.get("tracking_eta", r.get("eta"))
            step("get_tracking_status", f"status={r.get('status')}; eta={tracking_eta}",
                 r.get("tracking_reference", r["linked"]), r.get("snapshot", r["end"]))
        if answered or clarification:
            step("send_message", "sent")
        if r.get("escalated"):
            step("create_case", "created", r["linked"])
            step("escalate_case", "escalated", r["linked"])
        if r.get("handoff"):
            step("handoff_to_human", "queued")
        message_text = ""
        if answered:
            message_text = f"Shipment {r['linked']} is {r.get('status')}."
        elif clarification:
            message_text = clarification
        overrides = r.get("response_override", {})
        message_text = overrides.get("message_text", message_text)
        agent_runs.append({
            "run_id": f"RUN-{sc_id}-{n}", "enquiry_id": r["enquiry"], "agent_version": r.get("version", "agent_v1"),
            "started_at": r["start"], "ended_at": r["end"], "steps": steps,
            "claimed_status": r.get("status") if answered else None,
            "claimed_eta": r.get("eta") if answered else None,
            "response_text": message_text,
            "self_reported_outcome": r["self"], "handoff_flag": bool(r.get("handoff")),
            "tokens_in": None if r.get("retry") else 2500, "tokens_out": None if r.get("retry") else 300,
            "voice_seconds": None,
        })
        if answered or clarification:
            resp = {"response_id": f"RSP-{sc_id}-AI{n}", "enquiry_id": r["enquiry"], "case_id": None,
                    "sent_at": r["end"], "actor_type": "ai_agent", "actor_id": r.get("version", "agent_v1"),
                    "purpose": "answer" if answered else "clarification",
                    "shipment_reference": r["linked"] if answered else None,
                    "claimed_status": r.get("status") if answered else None,
                    "claimed_eta": r.get("eta") if answered else None, "message_text": message_text}
            resp.update(overrides)
            responses.append(resp)
    return agent_runs, responses


def _human_response_rows(sc_id: str, items: list[dict]) -> list[dict]:
    responses = []
    for n, r in enumerate(items, start=1):
        response = {
            "response_id": f"RSP-{sc_id}-H{n}", "enquiry_id": r["enquiry"], "case_id": r.get("case"),
            "sent_at": r["at"], "actor_type": "human", "actor_id": r["actor"], "purpose": r["purpose"],
            "shipment_reference": r.get("ref"), "claimed_status": r.get("status"), "claimed_eta": r.get("eta"),
            "message_text": r.get("message_text",
                                  "Update on your shipment." if r.get("ref") else "Forwarded to the documentation team."),
        }
        if "container_reference" in r:
            response["container_reference"] = r["container_reference"]
        responses.append(response)
    return responses


def _work_rows(sc_id: str, items: list[dict]) -> list[dict]:
    rows = []
    for n, w in enumerate(items, start=1):
        handle = round(w["active"] * 1.2)
        closed = datetime.fromisoformat(w["at"]) + timedelta(seconds=handle)
        rows.append({"work_id": f"WRK-{sc_id}-{n}", "enquiry_id": w["enquiry"], "case_id": w.get("case"),
                     "agent_id": w["agent"], "accepted_at": w["at"], "closed_at": closed.isoformat(),
                     "active_seconds": w["active"], "handle_seconds": handle, "acw_seconds": 0,
                     "activity": w["activity"], "measurement_method": "logged"})
    return rows


def build(sc: dict, base: dict, extension: dict | None = None) -> Scenario:
    sid = sc["id"]
    enquiries = [{"customer_id": DEFAULT_CUSTOMER, "channel": "voice", "language": "en", **q} for q in sc["enquiries"]]
    by_id = {q["enquiry_id"]: q for q in enquiries}
    runs, ai_responses = _run_rows(sid, sc.get("runs", []), by_id)
    tables = {
        "customers": [dict(c) for c in base["customers"]],
        "shipments": [dict(s) for s in base["shipments"]],
        "tracking_events": _event_rows(base, set(sc.get("drop_tracking", []))),
        "enquiries": enquiries,
        "agent_runs": runs,
        "responses": sorted(ai_responses + _human_response_rows(sid, sc.get("responses", [])),
                            key=lambda r: r["sent_at"]),
        "cases": [{"case_id": c["case_id"], "enquiry_id": c["enquiry"], "opened_at": c["opened"], "reason": c["reason"],
                   "owner_id": c["owner"], "priority": "high" if c["reason"] == "delay_investigation" else "normal",
                   "closed_at": c.get("closed"), "closure_code": c.get("code")} for c in sc.get("cases", [])],
        "case_history": [{"history_id": f"CH-{sid}-{n}", "case_id": h[0], "changed_at": h[1], "field": h[2],
                          "old_value": h[3], "new_value": h[4], "changed_by": h[5]}
                         for n, h in enumerate(sc.get("history", []), start=1)],
        "agent_work": _work_rows(sid, sc.get("work", [])),
    }
    if extension:
        tables["shipments"].extend(dict(row) for row in extension.get("shipments", []))
        tables["tracking_events"].extend(
            dict(row) for row in extension.get("tracking_events", [])
            if row["booking_ref"] not in sc.get("drop_tracking", [])
        )
    for key in sc.get("duplicate", []):
        tables[key] = tables[key] + [dict(r) for r in tables[key]]
    cutoff = sc.get("data_cutoff")
    return Scenario(
        id=sid, title=sc["title"], tests=sc["tests"], tables=tables, expected=sc["expected"],
        timezones=sc.get("timezones", {}),
        expect_schema_issues=sc.get("expect_schema_issues", 0),
        expect_reference_issues=sc.get("expect_reference_issues", 0),
        rule_version=extension["rule_version"] if extension else "0.1.0-proposed",
        data_cutoff=datetime.fromisoformat(cutoff) if cutoff else None,
    )


def load_library() -> list[Scenario]:
    base, lib = _load_yaml("base.yaml"), _load_yaml("library.yaml")
    cases = [build(sc, base) for sc in lib["scenarios"]]
    coverage = _load_yaml("extended.yaml")
    # Reuse the coverage fixtures' container and port history for the grading cases.
    grading = {**coverage, **_load_yaml("eta_accuracy.yaml")}
    for extension in (coverage, _load_yaml("outcomes.yaml"), grading):
        cases.extend(build(sc, base, extension) for sc in extension["scenarios"])
    return cases


def load_state_checks() -> list[dict]:
    return _load_yaml("base.yaml")["state_checks"]


def check(scenarios: list[Scenario]) -> list[str]:
    """Problems with the library itself (not with any evaluator)."""
    d = load_dictionary()
    problems = []
    ids = [s.id for s in scenarios]
    if len(ids) != len(set(ids)):
        problems.append("duplicate scenario ids")
    for s in scenarios:
        schema = [i for k, rows in s.tables.items() for i in validate_records(k, rows, d)]
        refs = validate_references(s.tables, d)
        if len(schema) != s.expect_schema_issues:
            problems.append(f"{s.id}: {len(schema)} schema issues, expected {s.expect_schema_issues}: "
                            + "; ".join(map(str, schema[:3])))
        if len(refs) != s.expect_reference_issues:
            problems.append(f"{s.id}: {len(refs)} reference issues, expected {s.expect_reference_issues}: "
                            + "; ".join(map(str, refs[:3])))
        enquiry_ids = {q["enquiry_id"] for q in s.tables["enquiries"]}
        if set(s.expected) != enquiry_ids:
            problems.append(f"{s.id}: expected results must cover exactly its enquiries")
        if s.data_cutoff is not None:
            latest_receipt = max(datetime.fromisoformat(q["received_at"]) for q in s.tables["enquiries"])
            if s.data_cutoff.utcoffset() is None or s.data_cutoff <= latest_receipt:
                problems.append(f"{s.id}: data cutoff must include a UTC offset and follow the last receipt")
        for eid, exp in s.expected.items():
            if exp.get("state") not in STATES:
                problems.append(f"{s.id}/{eid}: invalid state {exp.get('state')}")
            if "severity" in exp and exp["severity"] not in SEVERITIES:
                problems.append(f"{s.id}/{eid}: invalid severity {exp['severity']}")
            unknown = set(exp) - EXPECTED_FIELDS
            if unknown:
                problems.append(f"{s.id}/{eid}: unknown expected fields {sorted(unknown)}")
    return problems


def write(scenarios: list[Scenario], out_dir: Path = OUT_DIR) -> None:
    for s in scenarios:
        target = out_dir / s.id
        write_exports(s.tables, target)
        received = [datetime.fromisoformat(q["received_at"]) for q in s.tables["enquiries"]]
        period_end = max(received) + timedelta(seconds=1)
        meta = {
            "dataset_origin": "synthetic",
            "rule_version": s.rule_version,
            "study_period": [min(received).isoformat(), period_end.isoformat()],
            "data_cutoff": (s.data_cutoff or period_end + timedelta(days=14)).isoformat(),
            "timezones": {key: s.timezones.get(key, "UTC") for key in s.tables},
        }
        (target / "exports" / "export_metadata.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        truth_dir = target / "ground_truth"
        truth_dir.mkdir(exist_ok=True)
        (truth_dir / "expected.json").write_text(json.dumps(s.expected, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--write", action="store_true")
    args = p.parse_args(argv)
    lib = load_library()
    problems = check(lib)
    if problems:
        print("\n".join(problems))
        return 1
    print(f"{len(lib)} scenarios, {sum(len(s.expected) for s in lib)} expected enquiry results: OK")
    if args.write:
        write(lib)
        print(f"wrote {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
