"""Human review sheet for small datasets (e.g. `tiny`): one section per shipment with its
timeline and every enquiry, showing what the carrier's systems knew at enquiry time versus
what had actually happened. Used for the row-by-row check by the teammate who did not write
the generator (docs/SYNTHETIC_DATA_PLAN.md, section 8)."""

from __future__ import annotations

from .model import World
from .state import known_state_at, true_state_at


def _t(dt) -> str:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else "-"


def _claim(a) -> str:
    if a is None:
        return "-"
    ok = "ok" if a.correct else "WRONG"
    ref = a.linked.booking_ref if a.linked else "?"
    return f"{a.actor_type} {ref}: {a.claimed_status} / {_t(a.claimed_eta)} ({ok})"


def render_review(w: World, h=None) -> str:
    truth = {id(t.enquiry): t for t in h.truths} if h else {}
    by_ship: dict[str, list] = {}
    for q in w.enquiries:
        by_ship.setdefault(q.true_booking_ref, []).append(q)

    out = [
        "# Review sheet",
        "",
        f"Period: {_t(w.period_start)} to {_t(w.period_end)} (UTC). "
        f"Data cutoff: {_t(w.data_cutoff)}. "
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
                kind = q.reference_kind + (f", repeat of {q.repeat_of.enquiry_id}" if q.repeat_of else "")
                out.append(
                    f"| {q.enquiry_id} | {_t(q.received_at)} | {q.enquiry_type}{' (delay-driven)' if q.delay_driven else ''} | "
                    f"{q.stated_reference} ({kind}) | {k.status} / {_t(k.eta)} | {a.status} / {_t(a.eta)} |"
                )
            if truth:
                out += [
                    "",
                    "| Enquiry | Arm | First answer | Final answer | Escalation req / cases | Human min | Outcome | Scenario |",
                    "|---|---|---|---|---|---|---|---|",
                ]
                for q in qs:
                    t = truth[id(q)]
                    esc = f"{'yes' if t.escalation_required else 'no'} / {len(t.escalations)}"
                    flags = "".join([" handoff" if t.handed_off else "", " rescued" if t.rescued else "",
                                     " repeat" if t.repeat_contact else ""])
                    out.append(
                        f"| {q.enquiry_id} | {t.arm} | {_claim(t.first_answer)} | {_claim(t.final_answer)} | {esc} | "
                        f"{t.human_seconds / 60:.1f} | **{t.true_outcome}**{flags} | {t.scenario_id} |"
                    )
        else:
            out.append("_No enquiries in the period._")
        out.append("")
    return "\n".join(out)
