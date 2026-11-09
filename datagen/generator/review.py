"""Human review sheet for small datasets (e.g. `tiny`): one section per shipment with its
timeline and every enquiry, showing what the carrier's systems knew at enquiry time versus
what had actually happened. Used for the row-by-row check by the teammate who did not write
the generator (docs/SYNTHETIC_DATA_PLAN.md, section 8)."""

from __future__ import annotations

from .model import World
from .state import known_state_at, true_state_at


def _t(dt) -> str:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else "-"


def render_review(w: World) -> str:
    by_ship: dict[str, list] = {}
    for q in w.enquiries:
        by_ship.setdefault(q.true_booking_ref, []).append(q)

    out = [
        "# Review sheet",
        "",
        f"Period: {_t(w.period_start)} to {_t(w.period_end)} (UTC). "
        f"{len(w.shipments)} shipments, {len(w.events)} events, {len(w.enquiries)} enquiries.",
        "",
        "For each enquiry check: the stated reference points to the right shipment (or is flagged wrong),",
        "the enquiry type makes sense, and 'known' vs 'actual' differ only when an event was recorded late (stale).",
        "",
    ]
    for s in w.shipments:
        qs = by_ship.get(s.booking_ref, [])
        out += [
            f"## {s.booking_ref} ({s.customer_id}) {s.origin} -> {s.destination}",
            "",
            f"- Delay class: **{s.delay_class}** ({s.delay_hours:+.1f} h vs plan)",
            f"- Planned: depart {_t(s.planned_departure)}, arrive {_t(s.planned_arrival)}",
            f"- Actual: depart {_t(s.actual_departure)}, arrive {_t(s.actual_arrival)}, released {_t(s.released_at)}",
            f"- Containers: {', '.join(s.container_refs)}; BL {s.bl_ref} issued {_t(s.bl_issued_at)}",
            "",
            "| Event | Class | Happened / expected | Recorded | Stale |",
            "|---|---|---|---|---|",
        ]
        for e in sorted(w.events_for(s.booking_ref), key=lambda e: e.event_created_datetime):
            cont = f" {e.container_ref}" if e.container_ref else ""
            out.append(
                f"| {e.event_type_code}{cont} | {e.classifier} | {_t(e.event_datetime)} | "
                f"{_t(e.event_created_datetime)} | {'yes' if e.stale else ''} |"
            )
        out.append("")
        if qs:
            out += [
                "| Enquiry | Received | Type | Stated ref (kind) | Known status / ETA | Actual status / ETA |",
                "|---|---|---|---|---|---|",
            ]
            events = w.events_for(s.booking_ref)
            for q in qs:
                k, a = known_state_at(events, q.received_at), true_state_at(events, q.received_at)
                out.append(
                    f"| {q.enquiry_id} | {_t(q.received_at)} | {q.enquiry_type}{' (delay-driven)' if q.delay_driven else ''} | "
                    f"{q.stated_reference} ({q.reference_kind}) | {k.status} / {_t(k.eta)} | {a.status} / {_t(a.eta)} |"
                )
        else:
            out.append("_No enquiries in the period._")
        out.append("")
    return "\n".join(out)
