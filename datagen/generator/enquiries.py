"""Layer 3: customer enquiries about shipments.

Each shipment gets a baseline stream of enquiries spread evenly over its life
(booking to gate-out + 2 days). Once a delay is announced (an estimate later than the plan),
extra enquiries arrive at `delay_rate_multiplier` times the baseline intensity for the rest
of the journey; these are typed "delay". Only enquiries inside the study period are kept.
"""

from __future__ import annotations

from datetime import timedelta

from datagen.config_schema import GeneratorConfig

from . import ids
from .model import Enquiry, Shipment, World
from .sampling import choice_weighted, hours, layer_rng, poisson, uniform_time

REFERENCE_KIND_SHARES = {"booking": 0.60, "container": 0.25, "bl": 0.15}
DELAY_NOTICE_HOURS = 2.0  # an estimate this much later than the plan counts as an announced delay


def first_delay_notice(world: World, s: Shipment):
    """When the first estimate later than the planned arrival was issued (None if never)."""
    ests = sorted(
        (e for e in world.events_for(s.booking_ref) if e.classifier == "EST" and e.event_type_code == "ARRI"),
        key=lambda e: e.event_created_datetime,
    )
    for e in ests:
        if e.event_datetime >= s.planned_arrival + hours(DELAY_NOTICE_HOURS):
            return e.event_created_datetime
    return None


def _stated_reference(rng, cfg: GeneratorConfig, s: Shipment, received_at, same_customer: list[Shipment]):
    if rng.random() < cfg.enquiries.wrong_reference_share:
        others = [o for o in same_customer if o.booking_ref != s.booking_ref]
        if others and rng.random() < 0.5:
            return rng.choice(others).booking_ref, "other_shipment"
        return ids.typo(s.booking_ref, rng), "typo"
    kind = choice_weighted(rng, REFERENCE_KIND_SHARES)
    if kind == "bl" and received_at < s.bl_issued_at:
        kind = "booking"  # BL number not known to the customer yet
    if kind == "container":
        return rng.choice(s.container_refs), kind
    if kind == "bl":
        return s.bl_ref, kind
    return s.booking_ref, kind


def build_enquiries(cfg: GeneratorConfig, world: World) -> list[Enquiry]:
    rng = layer_rng(cfg.seed, "enquiries")
    eq = cfg.enquiries
    by_customer: dict[str, list[Shipment]] = {}
    for s in world.shipments:
        by_customer.setdefault(s.customer_id, []).append(s)

    drafts = []  # (received_at, shipment, enquiry_type, delay_driven)
    for s in world.shipments:
        life_start, life_end = s.booked_at, s.gated_out_at + timedelta(days=2)
        life_len = (life_end - life_start).total_seconds()
        for _ in range(poisson(rng, eq.base_rate_per_shipment)):
            drafts.append((uniform_time(rng, life_start, life_end), s, choice_weighted(rng, eq.type_mix), False))
        notice = first_delay_notice(world, s)
        if notice is not None and s.delay_class != "none":
            post_end = s.actual_arrival + timedelta(days=2)
            post_len = max(0.0, (post_end - notice).total_seconds())
            extra = eq.base_rate_per_shipment * (eq.delay_rate_multiplier - 1) * post_len / life_len
            for _ in range(poisson(rng, extra)):
                drafts.append((uniform_time(rng, notice, post_end), s, "delay", True))

    drafts = [d for d in drafts if world.period_start <= d[0] < world.period_end]
    drafts.sort(key=lambda d: (d[0], d[1].booking_ref))

    enquiries = []
    for n, (received_at, s, etype, driven) in enumerate(drafts, start=1):
        ref, kind = _stated_reference(rng, cfg, s, received_at, by_customer[s.customer_id])
        enquiries.append(
            Enquiry(
                enquiry_id=ids.enquiry_id(n),
                customer_id=s.customer_id,
                channel=choice_weighted(rng, eq.channel_mix),
                received_at=received_at,
                stated_reference=ref,
                enquiry_type=etype,
                language=choice_weighted(rng, eq.language_mix),
                true_booking_ref=s.booking_ref,
                reference_kind=kind,
                delay_driven=driven,
            )
        )
    return enquiries
