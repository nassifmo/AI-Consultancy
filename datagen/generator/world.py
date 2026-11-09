"""Layer 1 (customers, shipments) and layer 2 (actual journey + tracking events)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from datagen.config_schema import GeneratorConfig

from . import ids
from .model import Customer, Shipment, TrackingEvent, World
from .sampling import choice_weighted, hours, layer_rng, lognormal, uniform_time

# Countries matching the default port list (ISO 3166-1 alpha-2).
COUNTRIES = ["LB", "AE", "SA", "EG", "FR", "CN", "SG", "NL"]


def period_bounds(cfg: GeneratorConfig) -> tuple[datetime, datetime]:
    start = datetime.combine(cfg.period.start, datetime.min.time(), tzinfo=timezone.utc)
    y, m = start.year, start.month + cfg.period.months
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    return start, start.replace(year=y, month=m)


def _round_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


def build_customers(cfg: GeneratorConfig) -> list[Customer]:
    rng = layer_rng(cfg.seed, "customers")
    return [
        Customer(
            customer_id=ids.customer_id(i + 1),
            segment=choice_weighted(rng, cfg.world.segment_shares),
            country=rng.choice(COUNTRIES),
            preferred_channel=choice_weighted(rng, cfg.enquiries.channel_mix),
        )
        for i in range(cfg.world.n_customers)
    ]


def _delay_hours(cfg: GeneratorConfig, rng, delay_class: str) -> float:
    ops = cfg.operations
    if delay_class == "short":
        return rng.uniform(ops.short_delay_hours.min, ops.short_delay_hours.max)
    if delay_class == "long":
        return rng.uniform(ops.long_delay_hours.min, ops.long_delay_hours.max)
    return rng.uniform(-2.0, 1.0)  # on time, within normal noise


def build_shipments(cfg: GeneratorConfig, customers: list[Customer]) -> list[Shipment]:
    rng = layer_rng(cfg.seed, "shipments")
    start, end = period_bounds(cfg)
    # Departures spread so that shipments are in flight throughout the period.
    dep_from, dep_to = start - timedelta(days=25), end - timedelta(days=5)
    container_serial = 0
    shipments = []
    for i in range(cfg.world.n_shipments):
        origin, destination = rng.sample(cfg.world.ports, 2)
        planned_departure = _round_hour(uniform_time(rng, dep_from, dep_to))
        transit = rng.randint(cfg.world.transit_days.min, cfg.world.transit_days.max)
        planned_arrival = planned_departure + timedelta(days=transit)
        n_cont = rng.randint(cfg.world.containers_per_shipment.min, cfg.world.containers_per_shipment.max)
        containers = []
        for _ in range(n_cont):
            container_serial += 1
            containers.append(ids.container_ref(container_serial))

        delay_class = choice_weighted(rng, cfg.operations.delay_mix.model_dump())
        delay = _delay_hours(cfg, rng, delay_class)
        actual_departure = planned_departure + hours(rng.uniform(-3, 6))
        actual_arrival = planned_arrival + hours(delay)
        discharge = actual_arrival + hours(rng.uniform(4, 24))
        released = discharge + hours(rng.uniform(2, 48))
        shipments.append(
            Shipment(
                booking_ref=ids.booking_ref(100000 + i),
                bl_ref=ids.bl_ref(500000 + i),
                container_refs=containers,
                customer_id=rng.choice(customers).customer_id,
                origin=origin,
                destination=destination,
                planned_departure=planned_departure,
                planned_arrival=planned_arrival,
                booked_at=planned_departure - timedelta(days=rng.uniform(7, 21)),
                actual_departure=actual_departure,
                actual_arrival=actual_arrival,
                bl_issued_at=actual_departure + hours(rng.uniform(6, 48)),
                released_at=released,
                gated_out_at=released + hours(rng.uniform(6, 72)),
                delay_class=delay_class,
                delay_hours=round(delay, 2),
            )
        )
    return shipments


def _eta_revisions(cfg: GeneratorConfig, rng, s: Shipment) -> list[tuple[datetime, datetime]]:
    """(issued_at, eta) pairs. Delays become known gradually; the last estimate is close to the truth."""
    lo, hi = cfg.operations.eta_revisions.min, cfg.operations.eta_revisions.max
    n = rng.randint(lo, hi)
    if s.delay_class != "none":
        n = max(n, 1)  # a real delay is always announced before arrival
    if n == 0:
        return []
    window_start = s.actual_departure + hours(6)
    window_end = s.actual_arrival - hours(12)
    times = sorted(uniform_time(rng, window_start, window_end) for _ in range(n))
    revisions = []
    for k, t in enumerate(times, start=1):
        frac = k / n
        noise = 0.0 if k == n else rng.uniform(-2, 2)
        eta = s.planned_arrival + hours(s.delay_hours * frac + noise)
        if k == n:
            eta = s.actual_arrival + hours(rng.uniform(-1, 1))
        revisions.append((t, _round_hour(eta + timedelta(minutes=30))))
    return revisions


def build_events(cfg: GeneratorConfig, shipments: list[Shipment]) -> list[TrackingEvent]:
    rng = layer_rng(cfg.seed, "tracking")
    tr = cfg.tracking
    events: list[TrackingEvent] = []

    def recorded(t: datetime) -> tuple[datetime, bool]:
        if rng.random() < tr.stale_lag_share:
            return t + hours(rng.uniform(tr.stale_lag_hours.min, tr.stale_lag_hours.max)), True
        lag = lognormal(rng, tr.recording_lag_minutes.median, tr.recording_lag_minutes.p95)
        return t + timedelta(minutes=round(lag)), False

    def add(s, etype, code, cls, when, created, loc, container=None, stale=False):
        events.append(
            TrackingEvent(
                event_id="",
                booking_ref=s.booking_ref,
                container_ref=container,
                event_type=etype,
                event_type_code=code,
                classifier=cls,
                event_datetime=when,
                event_created_datetime=created,
                location=loc,
                stale=stale,
            )
        )

    def act(s, etype, code, when, loc, container=None):
        created, stale = recorded(when)
        add(s, etype, code, "ACT", when, created, loc, container, stale)

    for s in shipments:
        # At booking: confirmation + planned schedule.
        act(s, "SHIPMENT", "CONF", s.booked_at, s.origin)
        add(s, "TRANSPORT", "DEPA", "PLN", s.planned_departure, s.booked_at, s.origin)
        add(s, "TRANSPORT", "ARRI", "PLN", s.planned_arrival, s.booked_at, s.destination)
        # Origin.
        for c in s.container_refs:
            act(s, "EQUIPMENT", "GTIN", s.actual_departure - hours(rng.uniform(24, 72)), s.origin, c)
            act(s, "EQUIPMENT", "LOAD", s.actual_departure - hours(rng.uniform(2, 12)), s.origin, c)
        act(s, "TRANSPORT", "DEPA", s.actual_departure, s.origin)
        act(s, "SHIPMENT", "ISSU", s.bl_issued_at, s.origin)
        # In transit: estimated arrival revisions (estimates are created when issued).
        for issued, eta in _eta_revisions(cfg, rng, s):
            add(s, "TRANSPORT", "ARRI", "EST", eta, issued, s.destination)
        # Destination.
        act(s, "TRANSPORT", "ARRI", s.actual_arrival, s.destination)
        for c in s.container_refs:
            act(s, "EQUIPMENT", "DISC", s.actual_arrival + hours(rng.uniform(4, 24)), s.destination, c)
        act(s, "SHIPMENT", "RELS", s.released_at, s.destination)
        for c in s.container_refs:
            act(s, "EQUIPMENT", "GTOT", s.gated_out_at + hours(rng.uniform(0, 24)), s.destination, c)

    events.sort(key=lambda e: (e.event_created_datetime, e.booking_ref, e.event_type_code))
    for n, e in enumerate(events, start=1):
        e.event_id = ids.event_id(n)
    return events


def build_world(cfg: GeneratorConfig) -> World:
    start, end = period_bounds(cfg)
    customers = build_customers(cfg)
    shipments = build_shipments(cfg, customers)
    events = build_events(cfg, shipments)
    return World(customers=customers, shipments=shipments, events=events, period_start=start, period_end=end)
