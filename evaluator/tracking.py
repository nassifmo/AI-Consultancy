"""Resolve shipment references and reconstruct the tracking evidence known at a time."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from .exports import reference


_STATUS = {
    "CONF": "booked",
    "GTIN": "gated_in",
    "LOAD": "loaded",
    "DEPA": "departed",
    "ARRI": "arrived",
    "DISC": "discharged",
    "RELS": "released",
    "GTOT": "gated_out",
}
_FINAL_DESTINATION_CODES = {"ARRI", "DISC", "RELS", "GTOT"}
_STATUS_ORDER = {code: index for index, code in enumerate(_STATUS)}
_EVENT_TYPE = {
    "CONF": "SHIPMENT", "RELS": "SHIPMENT", "DEPA": "TRANSPORT", "ARRI": "TRANSPORT",
    "GTIN": "EQUIPMENT", "LOAD": "EQUIPMENT", "DISC": "EQUIPMENT", "GTOT": "EQUIPMENT",
}
_ETA_PRIORITY = {"PLN": 0, "EST": 1, "ACT": 2}


def _key(value):
    return value.strip().upper() if isinstance(value, str) else ""


def _containers(shipment):
    value = shipment.get("container_refs")
    if isinstance(value, str):
        return tuple(ref.strip() for ref in value.split(";") if ref.strip())
    return ()


@dataclass(frozen=True)
class Target:
    shipment: dict
    container: str | None = None


@dataclass(frozen=True)
class Snapshot:
    status: str | None
    eta: datetime | None
    eta_kind: str | None
    status_refs: list[str]
    eta_refs: list[str]


@dataclass(frozen=True)
class _Event:
    row: dict
    recorded: datetime | None
    occurred: datetime | None
    conflicting: bool

    @property
    def code(self):
        return _key(self.row.get("event_type_code"))

    @property
    def classifier(self):
        return _key(self.row.get("classifier"))

    @property
    def ref(self):
        return reference("tracking_events", self.row)


class Tracking:
    def __init__(self, data):
        self.data = data
        self.aliases = defaultdict(list)
        self.conflicting_aliases = defaultdict(set)
        self.events = defaultdict(list)
        self.unscoped_events = "tracking_events" in data.unscoped
        for shipment in data.tables.get("shipments", ()):
            self._index_shipment(shipment)
        for shipment in data.conflicts.get("shipments", ()):
            self._index_shipment(shipment, conflicting=True)
        for row in data.tables.get("tracking_events", ()):
            self._index_event(row)
        for row in data.conflicts.get("tracking_events", ()):
            self._index_event(row, conflicting=True)

    def _index_shipment(self, shipment, conflicting=False):
        booking = _key(shipment.get("booking_ref"))
        aliases = [(booking, None), (_key(shipment.get("bl_ref")), None)]
        aliases.extend((_key(ref), ref) for ref in _containers(shipment))
        for alias, container in aliases:
            if alias:
                if conflicting:
                    self.conflicting_aliases[alias].add(shipment.get("customer_id"))
                elif booking:
                    self.aliases[alias].append(Target(shipment, container))

    def _index_event(self, row, conflicting=False):
        booking = _key(row.get("booking_ref"))
        if booking:
            self.events[booking].append(_Event(
                row,
                self.data.time("tracking_events", row.get("event_created_datetime")),
                self.data.time("tracking_events", row.get("event_datetime")),
                conflicting,
            ))
        else:
            self.unscoped_events = True

    def _resolve_exact(self, value, customer_id):
        alias = _key(value)
        conflicting_customers = self.conflicting_aliases.get(alias, ())
        if conflicting_customers and (customer_id is None or customer_id in conflicting_customers):
            return None
        matches = {}
        for target in self.aliases.get(alias, ()):
            if customer_id is None or target.shipment.get("customer_id") == customer_id:
                key = (_key(target.shipment["booking_ref"]), _key(target.container))
                if key in matches and target.shipment != matches[key].shipment:
                    return None
                matches[key] = target
        return next(iter(matches.values())) if len(matches) == 1 else None

    def resolve(self, value, customer_id=None):
        """Match whole aliases, including mutually consistent slash-separated aliases."""
        target = self._resolve_exact(value, customer_id)
        if target is not None or not isinstance(value, str) or "/" not in value:
            return target
        targets = [self._resolve_exact(part, customer_id) for part in value.split("/")]
        if any(target is None for target in targets):
            return None
        bookings = {_key(target.shipment["booking_ref"]) for target in targets}
        containers = {_key(target.container) for target in targets if target.container}
        if len(bookings) != 1 or len(containers) > 1:
            return None
        return next((target for target in targets if target.container), targets[0])

    def _through_cutoff(self, as_of):
        if as_of is None or as_of.utcoffset() is None:
            return None
        cutoff = self.data.cutoff
        return min(as_of, cutoff) if cutoff is not None else as_of

    def for_request(self, enquiry, as_of):
        as_of = self._through_cutoff(as_of)
        account = enquiry.get("customer_id")
        if as_of is None or not isinstance(account, str) or not account.strip():
            return None
        received = self.data.time("enquiries", enquiry.get("received_at"))
        if received is not None and received > as_of:
            return None
        stated = enquiry.get("stated_reference")
        confirmed = enquiry.get("confirmed_reference")
        if _key(confirmed) and _key(confirmed) != _key(stated):
            confirmed_at = self.data.time("enquiries", enquiry.get("reference_confirmed_at"))
            if confirmed_at is None or (received is not None and confirmed_at < received):
                return None
            if confirmed_at <= as_of:
                stated = confirmed
        return self.resolve(stated, account)

    def _scoped(self, target, as_of):
        booking = _key(target.shipment["booking_ref"])
        allowed_containers = {_key(target.container)} if target.container else set()
        booking_containers = _containers(target.shipment)
        if not allowed_containers and len(booking_containers) == 1:
            allowed_containers.add(_key(booking_containers[0]))
        for event in self.events.get(booking, ()):
            container = _key(event.row.get("container_ref"))
            if container and container not in allowed_containers:
                continue
            if event.recorded is not None and event.recorded > as_of:
                continue
            if event.classifier == "ACT" and event.occurred is not None and event.occurred > as_of:
                continue
            yield event

    def snapshot(self, target, as_of):
        as_of = self._through_cutoff(as_of)
        coverage = self.data.metadata.get("source_completeness")
        incomplete_history = coverage is not None and (
            not isinstance(coverage, dict) or coverage.get("tracking_events") != "complete")
        if target is None or as_of is None or self.unscoped_events or incomplete_history:
            return Snapshot(None, None, None, [], [])
        destination = _key(target.shipment.get("destination"))
        events = list(self._scoped(target, as_of))
        intermediate_arrival = any(
            event.code == "ARRI"
            and _key(event.row.get("location")) not in {"", destination}
            for event in events
        )
        status_events, eta_events = [], []
        uncertain_status, uncertain_eta = [], []
        for event in events:
            if event.code not in _STATUS:
                if not event.code:
                    uncertain_status.append(event)
                    uncertain_eta.append(event)
                continue
            location = _key(event.row.get("location"))
            final_milestone = event.code in _FINAL_DESTINATION_CODES
            if final_milestone and destination and location and location != destination:
                continue
            # Legacy exports omit ports where the booking has one identifiable arrival.
            uncertain_scope = final_milestone and (
                not destination or (not location and intermediate_arrival)
            )
            uncertain = (
                uncertain_scope or event.conflicting or event.recorded is None or event.occurred is None
                or _key(event.row.get("event_type")) != _EVENT_TYPE[event.code]
                or event.classifier not in _ETA_PRIORITY
            )
            if event.classifier not in {"EST", "PLN"}:
                (uncertain_status if uncertain else status_events).append(event)
            if event.code == "ARRI":
                (uncertain_eta if uncertain else eta_events).append(event)

        status, status_refs = self._status(status_events, uncertain_status)
        eta, eta_kind, eta_refs = self._eta(eta_events, uncertain_eta)
        return Snapshot(status, eta, eta_kind, status_refs, eta_refs)

    @staticmethod
    def _status(events, uncertain):
        if uncertain:
            return None, sorted({event.ref for event in uncertain})
        if not events:
            return None, []
        latest = max((event.occurred, _STATUS_ORDER[event.code]) for event in events)
        selected = [event for event in events if (event.occurred, _STATUS_ORDER[event.code]) == latest]
        return _STATUS[selected[0].code], sorted({event.ref for event in selected})

    @staticmethod
    def _eta(events, uncertain):
        if uncertain:
            return None, None, sorted({event.ref for event in uncertain})
        if not events:
            return None, None, []
        latest = max((_ETA_PRIORITY[event.classifier], event.recorded) for event in events)
        selected = [event for event in events if (_ETA_PRIORITY[event.classifier], event.recorded) == latest]
        refs = sorted({event.ref for event in selected})
        times = {event.occurred for event in selected}
        if len(times) != 1:
            return None, None, refs
        return times.pop(), selected[0].classifier, refs

    def escalation(self, target, received, through, delay_hours):
        through = self._through_cutoff(through)
        if (target is None or received is None or received.utcoffset() is None
                or through is None or through < received):
            return None, None, []
        initial = self.snapshot(target, received)
        if initial.eta_kind == "ACT":
            return False, None, initial.eta_refs
        plan_ref = reference("shipments", target.shipment)
        plan = self.data.time("shipments", target.shipment.get("planned_arrival"))
        if plan is None:
            return None, None, [plan_ref]
        deadline = plan + timedelta(hours=delay_hours)
        revisions = {
            event.recorded for event in self._scoped(target, through)
            if event.code == "ARRI" and event.recorded is not None and received < event.recorded <= through
        }
        unknown = False
        refs = {plan_ref}
        for time in (received, *sorted(revisions)):
            snapshot = initial if time == received else self.snapshot(target, time)
            refs.update(snapshot.eta_refs)
            if snapshot.eta_kind == "ACT":
                break
            if snapshot.eta is None:
                unknown = True
            elif snapshot.eta > deadline:
                return True, None if unknown else time, sorted(refs)
        return (None if unknown else False), None, sorted(refs)
