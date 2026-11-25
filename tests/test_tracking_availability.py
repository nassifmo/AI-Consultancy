"""Verify that historical shipment claims use information available at the time."""

from datetime import datetime

import pytest

from evaluator.exports import ExportData
from evaluator.tracking import Tracking


EARLIER_ETA = "2026-11-27T10:00:00Z"
REVISED_ETA = "2026-11-28T10:00:00Z"
RECEIVED = "2026-11-25T10:00:00Z"
REVISION_VISIBLE = "2026-11-25T10:05:00Z"


def event(identifier, eta, created, available=None, *, code="ARRI", classifier="EST"):
    return {
        "event_id": identifier,
        "booking_ref": "BOOKING-A",
        "location": "ROTTERDAM",
        "event_type": "TRANSPORT",
        "event_type_code": code,
        "classifier": classifier,
        "event_datetime": eta,
        "event_created_datetime": created,
        "event_available_datetime": available,
    }


def tracking(events, **metadata):
    data = ExportData(
        tables={
            "tracking_events": events,
            "shipments": [{
                "booking_ref": "BOOKING-A",
                "customer_id": "CUSTOMER-A",
                "destination": "ROTTERDAM",
                "planned_arrival": EARLIER_ETA,
            }],
        },
        available={"tracking_events", "shipments"},
        metadata={
            "dataset_origin": "company",
            "source_completeness": {"tracking_events": "complete"},
            **metadata,
        },
    )
    result = Tracking(data)
    return result, result.resolve("BOOKING-A", "CUSTOMER-A")


def test_new_eta_first_counts_when_visible_to_support():
    earlier = event("earlier", EARLIER_ETA, "2026-11-24T13:00:00Z", "2026-11-24T13:10:00Z")
    revised = event("revised", REVISED_ETA, "2026-11-25T09:55:00Z", REVISION_VISIBLE)
    subject, target = tracking([earlier, revised])
    received = datetime.fromisoformat(RECEIVED)
    visible = datetime.fromisoformat(REVISION_VISIBLE)

    original_snapshot = subject.snapshot(target, received)
    assert original_snapshot.eta == datetime.fromisoformat(EARLIER_ETA)
    assert original_snapshot.eta_refs == ["tracking_events.json#earlier"]
    assert subject.snapshot(target, visible).eta == datetime.fromisoformat(REVISED_ETA)
    assert subject.escalation(target, received, datetime.fromisoformat("2026-11-25T10:04:00Z"), 12)[:2] == (False, None)
    assert subject.escalation(target, received, visible, 12)[:2] == (True, visible)


def test_new_actual_milestone_cannot_be_used_before_it_is_visible():
    departure = event("departure", "2026-11-25T08:00:00Z", "2026-11-25T09:55:00Z", REVISION_VISIBLE,
                      code="DEPA", classifier="ACT")
    subject, target = tracking([departure])

    assert subject.snapshot(target, datetime.fromisoformat(RECEIVED), status_subject="vessel").status is None
    observed = subject.snapshot(target, datetime.fromisoformat(REVISION_VISIBLE), status_subject="vessel")
    assert observed.status == "departed"
    assert observed.status_refs == ["tracking_events.json#departure"]


def test_later_revision_without_visibility_prevents_an_escalation_conclusion():
    earlier = event("earlier", EARLIER_ETA, "2026-11-24T13:00:00Z", "2026-11-24T13:10:00Z")
    revised = event("revised", REVISED_ETA, "2026-11-25T10:03:00Z")
    subject, target = tracking([earlier, revised])
    received = datetime.fromisoformat(RECEIVED)

    assert subject.snapshot(target, received).eta == datetime.fromisoformat(EARLIER_ETA)
    assert subject.snapshot(target, datetime.fromisoformat(REVISION_VISIBLE)).eta is None
    result = subject.escalation(target, received, datetime.fromisoformat(REVISION_VISIBLE), 12)
    assert result[:2] == (None, None)
    assert "tracking_events.json#revised" in result[2]


@pytest.mark.parametrize("metadata,expected", [
    ({}, None),
    ({"tracking_creation_visibility_ref": " "}, None),
    ({"tracking_creation_visibility_ref": "Partner source-owner confirmation"}, EARLIER_ETA),
    ({"dataset_origin": "synthetic"}, EARLIER_ETA),
])
def test_creation_time_requires_an_explicit_basis(metadata, expected):
    subject, target = tracking([event("earlier", EARLIER_ETA, "2026-11-25T09:55:00Z")], **metadata)
    observed = subject.snapshot(target, datetime.fromisoformat(RECEIVED))

    assert observed.eta == (datetime.fromisoformat(expected) if expected else None)


@pytest.mark.parametrize("available", ["unknown", "2026-11-25T09:50:00Z"])
def test_invalid_explicit_visibility_is_not_overridden_by_a_proxy(available):
    revision = event("revised", REVISED_ETA, "2026-11-25T09:55:00Z", available)
    subject, target = tracking([revision], tracking_creation_visibility_ref="Partner source-owner confirmation")

    observed = subject.snapshot(target, datetime.fromisoformat(RECEIVED))
    assert observed.eta is None
    assert observed.eta_refs == ["tracking_events.json#revised"]


def test_known_visibility_has_priority_over_creation_as_a_proxy():
    revision = event("revised", REVISED_ETA, "2026-11-25T09:55:00Z", REVISION_VISIBLE)
    subject, target = tracking([revision], tracking_creation_visibility_ref="Partner source-owner confirmation")

    assert subject.snapshot(target, datetime.fromisoformat(RECEIVED)).eta is None
    assert subject.snapshot(target, datetime.fromisoformat(REVISION_VISIBLE)).eta == datetime.fromisoformat(REVISED_ETA)
