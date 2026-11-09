"""Shipment state at a point in time.

Two views, which differ when events are recorded late (stale status):
- `known_state_at`: what the carrier's systems showed at time t (events with created time <= t).
  This is the reference for judging whether an answer was correct *when it was given*.
- `true_state_at`: what had physically happened by time t (event time <= t).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .model import TrackingEvent

# Physical status implied by the latest actual (ACT) event, in journey order.
STATUS_BY_CODE = {
    "CONF": "booked",
    "GTIN": "gated_in",
    "LOAD": "loaded",
    "DEPA": "departed",
    "ARRI": "arrived",
    "DISC": "discharged",
    "RELS": "released",
    "GTOT": "gated_out",
}
STATUS_ORDER = list(dict.fromkeys(STATUS_BY_CODE.values()))


@dataclass(frozen=True)
class ShipmentState:
    status: str | None
    eta: datetime | None  # latest estimated/planned arrival, or actual arrival once it happened
    status_event_id: str | None
    eta_event_id: str | None


def _state(events: list[TrackingEvent], visible) -> ShipmentState:
    seen = [e for e in events if visible(e)]
    physical = [e for e in seen if e.classifier == "ACT" and e.event_type_code in STATUS_BY_CODE]
    status_ev = max(physical, key=lambda e: (e.event_datetime, STATUS_ORDER.index(STATUS_BY_CODE[e.event_type_code])), default=None)

    arrivals = [e for e in seen if e.event_type == "TRANSPORT" and e.event_type_code == "ARRI"]
    actual = [e for e in arrivals if e.classifier == "ACT"]
    if actual:
        eta_ev = actual[0]
    else:
        # Most recently issued estimate wins; a plan is only used before any estimate exists.
        ests = [e for e in arrivals if e.classifier == "EST"] or [e for e in arrivals if e.classifier == "PLN"]
        eta_ev = max(ests, key=lambda e: e.event_created_datetime, default=None)

    return ShipmentState(
        status=STATUS_BY_CODE[status_ev.event_type_code] if status_ev else None,
        eta=eta_ev.event_datetime if eta_ev else None,
        status_event_id=status_ev.event_id if status_ev else None,
        eta_event_id=eta_ev.event_id if eta_ev else None,
    )


def known_state_at(events: list[TrackingEvent], t: datetime) -> ShipmentState:
    return _state(events, lambda e: e.event_created_datetime <= t)


def true_state_at(events: list[TrackingEvent], t: datetime) -> ShipmentState:
    def happened(e: TrackingEvent) -> bool:
        if e.classifier == "ACT":
            return e.event_datetime <= t
        return e.event_created_datetime <= t  # estimates/plans exist once issued

    return _state(events, happened)
