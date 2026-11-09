"""Render in-memory records into partner-shaped export files (layer 8, first part)."""

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
        # A BL number only exists in the export once it has been issued within the period.
        bl = s.bl_ref if w.period_end and s.bl_issued_at < w.period_end else ""
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
    """Only events already recorded by the end of the study period are exported."""
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
        if w.period_end is None or e.event_created_datetime < w.period_end
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


TABLES = {
    "customers": ("customers.csv", customers_rows),
    "shipments": ("shipments.csv", shipments_rows),
    "tracking_events": ("tracking_events.json", tracking_rows),
    "enquiries": ("enquiries.csv", enquiries_rows),
}


def build_tables(w: World) -> dict[str, list[dict]]:
    return {key: fn(w) for key, (_, fn) in TABLES.items()}


def write_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        if not rows:
            return
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows({k: ("" if v is None else v) for k, v in r.items()} for r in rows)


def write_exports(tables: dict[str, list[dict]], out_dir: Path) -> list[Path]:
    target = out_dir / EXPORT_DIR
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for key, rows in tables.items():
        filename = TABLES[key][0]
        path = target / filename
        if filename.endswith(".json"):
            path.write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        else:
            write_csv(path, rows)
        written.append(path)
    return written
