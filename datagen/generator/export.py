"""Render in-memory records into partner-shaped export files and ground-truth files."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from .model import World

EXPORT_DIR = "exports"


def fmt_dt(dt: datetime | None) -> str:
    return dt.isoformat() if dt else ""


def customers_rows(w: World) -> list[dict]:
    return [
        {"customer_id": c.customer_id, "segment": c.segment, "country": c.country, "preferred_channel": c.preferred_channel}
        for c in w.customers
    ]


def shipments_rows(w: World) -> list[dict]:
    rows = []
    for s in w.shipments:
        # A BL number only exists in the export once it has been issued before the data cutoff.
        bl = s.bl_ref if w.data_cutoff and s.bl_issued_at < w.data_cutoff else ""
        rows.append(
            {
                "booking_ref": s.booking_ref,
                "bl_ref": bl,
                "container_refs": ";".join(s.container_refs),
                "customer_id": s.customer_id,
                "origin": s.origin,
                "destination": s.destination,
                "planned_departure": fmt_dt(s.planned_departure),
                "planned_arrival": fmt_dt(s.planned_arrival),
            }
        )
    return rows


def tracking_rows(w: World) -> list[dict]:
    """Only events already recorded by the data cutoff are exported."""
    return [
        {
            "event_id": e.event_id,
            "booking_ref": e.booking_ref,
            "container_ref": e.container_ref,
            "event_type": e.event_type,
            "event_type_code": e.event_type_code,
            "classifier": e.classifier,
            "event_datetime": fmt_dt(e.event_datetime),
            "event_created_datetime": fmt_dt(e.event_created_datetime),
            "location": e.location,
        }
        for e in w.events
        if w.data_cutoff is None or e.event_created_datetime < w.data_cutoff
    ]


def enquiries_rows(w: World) -> list[dict]:
    return [
        {
            "enquiry_id": q.enquiry_id,
            "customer_id": q.customer_id,
            "channel": q.channel,
            "received_at": fmt_dt(q.received_at),
            "stated_reference": q.stated_reference,
            "enquiry_type": q.enquiry_type,
            "language": q.language,
        }
        for q in w.enquiries
    ]


WORLD_TABLES = {
    "customers": customers_rows,
    "shipments": shipments_rows,
    "tracking_events": tracking_rows,
    "enquiries": enquiries_rows,
}

FILENAMES = {
    "customers": "customers.csv",
    "shipments": "shipments.csv",
    "tracking_events": "tracking_events.json",
    "enquiries": "enquiries.csv",
    "agent_runs": "agent_runs.json",
    "cases": "cases.csv",
    "case_history": "case_history.csv",
    "agent_work": "agent_work.csv",
    "responses": "responses.csv",
    "ai_invoice": "ai_invoice.csv",
    "rollout_log": "rollout_log.csv",
    "cost_parameters": "cost_parameters.json",
    "staffing": "staffing.csv",
    "true_outcome": "true_outcome.csv",
    "planted_effects": "planted_effects.json",
    "injected_defects": "injected_defects.csv",
}
GROUND_TRUTH = {"true_outcome", "planted_effects", "injected_defects"}
JSON_OBJECTS = {"cost_parameters", "planted_effects"}


def build_tables(w: World) -> dict[str, list[dict]]:
    """Layers 1-3 exports only (E1-E4)."""
    return {key: fn(w) for key, fn in WORLD_TABLES.items()}


def _numbered(rows: list[dict], key: str, prefix: str, width: int) -> None:
    rows.sort(key=lambda r: r[key])
    for n, r in enumerate(rows, start=1):
        r["_id"] = f"{prefix}-{n:0{width}d}"


def _case_id(r: dict) -> str | None:
    return r["_case"]["_id"] if r.get("_case") else None


def handling_tables(h) -> dict[str, list[dict]]:
    """Layers 4-5 exports (E5-E8, E14). Internal object links become IDs here."""
    _numbered(h.agent_runs, "started_at", "RUN", 7)
    _numbered(h.cases, "opened_at", "CAS", 6)
    _numbered(h.case_history, "changed_at", "CH", 7)
    _numbered(h.agent_work, "accepted_at", "WRK", 7)
    _numbered(h.responses, "sent_at", "RSP", 7)
    return {
        "agent_runs": [
            {
                "run_id": r["_id"],
                "enquiry_id": r["_enq"].enquiry_id,
                "agent_version": r["agent_version"],
                "started_at": fmt_dt(r["started_at"]),
                "ended_at": fmt_dt(r["ended_at"]),
                "steps": [{**st, "snapshot_time": fmt_dt(st["snapshot_time"]) or None} for st in r["steps"]],
                "claimed_status": r["claimed_status"],
                "claimed_eta": fmt_dt(r["claimed_eta"]) or None,
                "response_text": r["response_text"],
                "self_reported_outcome": r["self_reported_outcome"],
                "handoff_flag": r["handoff_flag"],
                "tokens_in": r["tokens_in"],
                "tokens_out": r["tokens_out"],
                "voice_seconds": r["voice_seconds"],
            }
            for r in h.agent_runs
        ],
        "cases": [
            {
                "case_id": c["_id"],
                "enquiry_id": c["_enq"].enquiry_id,
                "opened_at": fmt_dt(c["opened_at"]),
                "reason": c["reason"],
                "owner_id": c["owner_id"],
                "priority": c["priority"],
                "closed_at": fmt_dt(c["closed_at"]),
                "closure_code": c["closure_code"],
            }
            for c in h.cases
        ],
        "case_history": [
            {
                "history_id": r["_id"],
                "case_id": r["_case"]["_id"],
                "changed_at": fmt_dt(r["changed_at"]),
                "field": r["field"],
                "old_value": r["old_value"],
                "new_value": r["new_value"],
                "changed_by": r["changed_by"],
            }
            for r in h.case_history
        ],
        "agent_work": [
            {
                "work_id": r["_id"],
                "enquiry_id": r["_enq"].enquiry_id,
                "case_id": _case_id(r),
                "agent_id": r["agent_id"],
                "accepted_at": fmt_dt(r["accepted_at"]),
                "closed_at": fmt_dt(r["closed_at"]),
                "active_seconds": r["active_seconds"],
                "handle_seconds": r["handle_seconds"],
                "acw_seconds": r["acw_seconds"],
                "activity": r["activity"],
                "measurement_method": r["measurement_method"],
            }
            for r in h.agent_work
        ],
        "responses": [
            {
                "response_id": r["_id"],
                "enquiry_id": r["_enq"].enquiry_id,
                "case_id": _case_id(r),
                "sent_at": fmt_dt(r["sent_at"]),
                "actor_type": r["actor_type"],
                "actor_id": r["actor_id"],
                "purpose": r["purpose"],
                "shipment_reference": r["shipment_reference"],
                "claimed_status": r["claimed_status"],
                "claimed_eta": fmt_dt(r["claimed_eta"]) or None,
                "message_text": r["message_text"],
            }
            for r in h.responses
        ],
    }


def datetime_fields(file_key: str, d: dict) -> list[str]:
    spec = {**d["files"], **d.get("ground_truth", {})}[file_key]
    return [f["name"] for f in spec.get("fields", []) if f["type"] == "datetime"]


def localize(tables: dict, files: list[str], tz_name: str, d: dict) -> None:
    """Render datetime fields of the given files in a local time zone (offset kept, so still exact)."""
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(tz_name)
    for key in files:
        fields = datetime_fields(key, d)
        for row in tables.get(key, []):
            for f in fields:
                if row.get(f):
                    row[f] = datetime.fromisoformat(row[f]).astimezone(tz).isoformat()


def write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    """Write rows; an empty table still gets its header (from `fieldnames`)."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        names = list(rows[0]) if rows else fieldnames
        if not names:
            return
        writer = csv.DictWriter(f, fieldnames=names)
        writer.writeheader()
        writer.writerows({k: ("" if v is None else v) for k, v in r.items()} for r in rows)


def _dictionary_fields(key: str) -> list[str]:
    from datagen.dictionary_tools import load_dictionary

    d = load_dictionary()
    spec = {**d["files"], **d.get("ground_truth", {})}.get(key, {})
    return [f["name"] for f in spec.get("fields", [])]


def write_exports(tables: dict, out_dir: Path) -> list[Path]:
    """Write partner exports to out_dir/exports and ground truth to out_dir/ground_truth.
    JSON-object tables are passed as a one-element list."""
    written = []
    for key, rows in tables.items():
        target = out_dir / ("ground_truth" if key in GROUND_TRUTH else EXPORT_DIR)
        target.mkdir(parents=True, exist_ok=True)
        filename = FILENAMES[key]
        path = target / filename
        if filename.endswith(".json"):
            payload = rows[0] if key in JSON_OBJECTS else rows
            path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        else:
            write_csv(path, rows, _dictionary_fields(key))
        written.append(path)
    return written
