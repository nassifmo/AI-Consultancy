"""Map one replay trial to the evaluator's operational exports, without answers."""

import csv
import json
import re
from pathlib import Path

from evaluator.exports import TABLES
from evaluator.verification import verify_exports


def _csv(path, columns, rows):
    extra = sorted({key for row in rows for key in row} - set(columns))
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=(*columns, *extra))
        writer.writeheader()
        writer.writerows(rows)


def _json_file(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def export_and_verify(case, trial, path):
    """Observe up to the synthetic enquiry clock; later outcomes are not simulated."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=False)
    at, enquiry_id = case["now"], case["id"]
    text = case["message"]
    ids = re.findall(r"\bTEST-(?:BOX|BL|BKG)-[A-Z0-9-]+\b", text, re.IGNORECASE)
    reference = "/".join(dict.fromkeys(ids)) or None
    rows = {
        "enquiries": [{"enquiry_id": enquiry_id, "customer_id": case["account_id"], "received_at": at,
                       "enquiry_type": "delay" if re.search(r"\bdelay(?:ed)?\b", text, re.IGNORECASE) else "status",
                       "stated_reference": reference, "customer_message": text, "language": "en", "channel": "chat"}],
        "customers": [{"customer_id": customer} for customer in sorted(
            {case["account_id"]} | {s["account_id"] for s in case["shipments"]})],
        "shipments": [{"booking_ref": s["booking_ref"], "bl_ref": s["bl_ref"], "customer_id": s["account_id"],
                       "container_refs": ";".join(s["container_refs"]), "planned_arrival": s["planned_eta"],
                       "origin": s["origin"], "destination": s["destination"]} for s in case["shipments"]],
        "tracking_events": case["events"],
    }
    actor = trial["requested_model"]
    # The same parser accepts the model's structured payload; no reference or
    # graded result is needed for export or for the existing verifier.
    from .world import _answer

    reply = _answer(trial["answer"])
    rows["responses"] = []
    rows["agent_runs"] = []
    steps = []
    for call in trial["tool_calls"]:
        status = call["result"].get("status")
        args = call["arguments"] or {}
        if call["name"] == "lookup_tracking":
            steps.append({"tool_name": "get_tracking_status", "tool_input": args.get("container_ref") or args.get("reference"),
                          "tool_output": status, "success": status == "ok", "snapshot_time": at})
        # An escalation is derived only from scratchpad state below.
    rows["cases"] = []
    rows["case_history"] = []
    for event in trial["case_events"]:
        case_id = event["case_id"]
        opened = event["synthetic_at"]
        rows["cases"].append({"case_id": case_id, "enquiry_id": enquiry_id, "opened_at": opened,
                              "owner_id": "operations", "reason": "delay_investigation"})
        for stage, tool in (("new", "create_case"), ("escalated", "escalate_case")):
            rows["case_history"].append({"history_id": f"{case_id}-{stage}", "case_id": case_id,
                                         "changed_at": opened, "field": "status", "new_value": stage,
                                         "changed_by": actor})
            steps.append({"tool_name": tool, "tool_input": case_id, "tool_output": stage, "success": True})
    if isinstance(reply, dict):
        response_id, run_id = f"{enquiry_id}-reply", f"{enquiry_id}-run"
        steps.append({"tool_name": "send_message", "tool_input": None, "tool_output": "synthetic_delivered", "success": True})
        rows["responses"].append({"response_id": response_id, "run_id": run_id, "enquiry_id": enquiry_id,
                                  "sent_at": at, "actor_type": "ai_agent", "actor_id": actor,
                                  "purpose": "clarification" if reply["action"] == "clarify" else "answer",
                                  "shipment_reference": reply["booking_ref"], "container_reference": reply["container_ref"],
                                  "claimed_status": reply["status"], "claimed_eta": reply["eta"],
                                  "case_id": reply["case_id"], "message_text": reply["reply"]})
        rows["agent_runs"].append({"run_id": run_id, "response_id": response_id, "enquiry_id": enquiry_id,
                                   "agent_version": actor, "started_at": at, "ended_at": at,
                                   "response_text": reply["reply"], "handoff_flag": reply["action"] == "escalate",
                                   "steps": [dict(s, step_no=i) for i, s in enumerate(steps, start=1)]})
    rows["agent_work"] = []
    completeness = {table: "complete" for table in rows}
    completeness["agent_work"] = "unknown"
    if not case["source_complete"]:
        completeness["tracking_events"] = "partial"
    if not rows["responses"]:
        completeness["responses"] = completeness["agent_runs"] = "unknown"
    _json_file(path / "export_metadata.json", {
        "dataset_origin": "synthetic", "data_cutoff": at, "rule_version": "replay-observation-v1",
        "source_completeness": completeness, "replay_clock": "Frozen simulated enquiry time.",
        "scope": "Initial sandbox interaction only. No causal assignments, human work, finance or follow-up.",
    })
    for table, table_rows in rows.items():
        name, columns = TABLES[table]
        if name.endswith(".csv"):
            _csv(path / name, columns, table_rows)
        else:
            _json_file(path / name, table_rows)
    policy = json.loads((Path(__file__).resolve().parent.parent / "evaluator" / "policy.json").read_text(encoding="utf-8"))
    return verify_exports(path, policy)
