"""Tests for step 2: layers 1-3 (customers, shipments, tracking events, enquiries)."""

from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from datagen.config_schema import load_config
from datagen.generate import generate, run, validate_tables
from datagen.generator import ids
from datagen.generator.enquiries import first_delay_notice
from datagen.generator.export import build_tables
from datagen.generator.model import TrackingEvent
from datagen.generator.sampling import layer_rng, lognormal, poisson
from datagen.generator.state import known_state_at, true_state_at

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


@pytest.fixture(scope="module")
def tiny_cfg():
    return load_config(CONFIG_DIR / "tiny.yaml")


@pytest.fixture(scope="module")
def dev_cfg():
    return load_config(CONFIG_DIR / "default.yaml")


@pytest.fixture(scope="module")
def tiny(tiny_cfg):
    return generate(tiny_cfg)


@pytest.fixture(scope="module")
def dev(dev_cfg):
    return generate(dev_cfg)


# ---------------------------------------------------------------- helpers


def test_container_check_digit_known_example():
    # Worked example from the ISO 6346 standard: CSQU305438 -> check digit 3.
    assert ids.iso6346_check_digit("CSQU305438") == 3
    assert ids.is_valid_container("CSQU3054383")
    assert not ids.is_valid_container("CSQU3054384")


def test_lognormal_median_and_p95():
    rng = layer_rng(1, "t")
    xs = sorted(lognormal(rng, 10, 40) for _ in range(20000))
    assert xs[len(xs) // 2] == pytest.approx(10, rel=0.05)
    assert xs[int(len(xs) * 0.95)] == pytest.approx(40, rel=0.08)


def test_poisson_mean():
    rng = layer_rng(1, "p")
    for lam in (0.5, 3.0, 80.0):
        mean = sum(poisson(rng, lam) for _ in range(20000)) / 20000
        assert mean == pytest.approx(lam, rel=0.05)


def test_typo_changes_exactly_one_character():
    rng = layer_rng(1, "x")
    t = ids.typo("BKG000100123", rng)
    assert t != "BKG000100123" and sum(a != b for a, b in zip(t, "BKG000100123")) == 1


# ---------------------------------------------------------------- reproducibility and validity


def test_same_seed_same_output(tiny_cfg):
    a, b = build_tables(generate(tiny_cfg)), build_tables(generate(tiny_cfg))
    assert a == b


def test_different_seed_different_output(tiny_cfg):
    other = tiny_cfg.model_copy(update={"seed": 7})
    assert build_tables(generate(tiny_cfg)) != build_tables(generate(other))


@pytest.mark.parametrize("world", ["tiny", "dev"])
def test_exports_match_dictionary(world, request):
    assert validate_tables(build_tables(request.getfixturevalue(world))) == []


def test_run_writes_files_and_manifest(tiny_cfg, tmp_path):
    out = run(CONFIG_DIR / "tiny.yaml", tmp_path / "tiny")
    names = {p.name for p in (out / "exports").iterdir()}
    assert names == {"customers.csv", "shipments.csv", "tracking_events.json", "enquiries.csv"}
    assert (out / "manifest.json").exists() and (out / "review.md").exists()


# ---------------------------------------------------------------- world and tracking


def test_containers_are_valid_and_unique(dev):
    refs = [c for s in dev.shipments for c in s.container_refs]
    assert len(refs) == len(set(refs))
    assert all(ids.is_valid_container(c) for c in refs)


def test_delay_mix_matches_config(dev, dev_cfg):
    counts = Counter(s.delay_class for s in dev.shipments)
    for cls, share in dev_cfg.operations.delay_mix.model_dump().items():
        assert counts[cls] / len(dev.shipments) == pytest.approx(share, abs=0.03)


def test_journey_is_in_order(dev):
    for s in dev.shipments:
        assert s.booked_at < s.actual_departure < s.bl_issued_at < s.actual_arrival < s.released_at < s.gated_out_at


def test_actual_events_recorded_after_they_happen(dev):
    for e in dev.events:
        if e.classifier == "ACT":
            assert e.event_created_datetime >= e.event_datetime


def test_stale_share_close_to_config(dev, dev_cfg):
    act = [e for e in dev.events if e.classifier == "ACT"]
    share = sum(e.stale for e in act) / len(act)
    assert share == pytest.approx(dev_cfg.tracking.stale_lag_share, abs=0.01)


def test_delays_are_announced_before_arrival(dev):
    for s in dev.shipments:
        if s.delay_class != "none":
            notice = first_delay_notice(dev, s)
            assert notice is not None and notice < s.actual_arrival


def test_last_estimate_is_close_to_actual_arrival(dev):
    for s in dev.shipments:
        ests = [e for e in dev.events_for(s.booking_ref) if e.classifier == "EST"]
        if ests:
            last = max(ests, key=lambda e: e.event_created_datetime)
            assert abs((last.event_datetime - s.actual_arrival).total_seconds()) <= 2 * 3600


def test_export_omits_events_recorded_after_period(dev):
    exported = build_tables(dev)["tracking_events"]
    cutoff = dev.period_end.isoformat()
    assert all(r["event_created_datetime"] < cutoff for r in exported)
    assert len(exported) < len(dev.events)


# ---------------------------------------------------------------- state at time t


def _ev(code, cls, when, created, etype="TRANSPORT", eid="E"):
    return TrackingEvent(eid, "B", None, etype, code, cls, when, created, None)


def test_known_state_lags_behind_true_state_when_event_is_stale():
    t0 = datetime(2026, 1, 10, tzinfo=timezone.utc)
    events = [
        _ev("ARRI", "PLN", t0 + timedelta(days=10), t0 - timedelta(days=5), eid="P"),
        _ev("DEPA", "ACT", t0, t0 + timedelta(minutes=20), eid="D"),
        _ev("ARRI", "EST", t0 + timedelta(days=12), t0 + timedelta(days=3), eid="X"),
        _ev("ARRI", "ACT", t0 + timedelta(days=12), t0 + timedelta(days=14), eid="A"),  # recorded 2 days late
    ]
    t = t0 + timedelta(days=13)
    known, actual = known_state_at(events, t), true_state_at(events, t)
    assert known.status == "departed" and known.eta == t0 + timedelta(days=12)
    assert actual.status == "arrived"


def test_plan_used_only_until_first_estimate():
    t0 = datetime(2026, 1, 10, tzinfo=timezone.utc)
    events = [
        _ev("ARRI", "PLN", t0 + timedelta(days=10), t0, eid="P"),
        _ev("ARRI", "EST", t0 + timedelta(days=11), t0 + timedelta(days=2), eid="X"),
    ]
    assert known_state_at(events, t0 + timedelta(days=1)).eta_event_id == "P"
    assert known_state_at(events, t0 + timedelta(days=3)).eta_event_id == "X"


def test_nothing_known_before_any_record():
    t0 = datetime(2026, 1, 10, tzinfo=timezone.utc)
    s = known_state_at([_ev("DEPA", "ACT", t0, t0 + timedelta(hours=1))], t0)
    assert s.status is None and s.eta is None


def test_stale_knowledge_occurs_in_dev(dev):
    diffs = [
        q
        for q in dev.enquiries
        if known_state_at(dev.events_for(q.true_booking_ref), q.received_at).status
        != true_state_at(dev.events_for(q.true_booking_ref), q.received_at).status
    ]
    assert diffs, "dev should contain enquiries where the recorded status lags reality"


# ---------------------------------------------------------------- enquiries


def test_enquiries_inside_period_and_sorted(dev):
    times = [q.received_at for q in dev.enquiries]
    assert times == sorted(times)
    assert all(dev.period_start <= t < dev.period_end for t in times)


def test_enquiry_belongs_to_its_shipment_customer(dev):
    for q in dev.enquiries:
        assert q.customer_id == dev.shipment(q.true_booking_ref).customer_id


def test_delayed_shipments_get_more_enquiries(dev):
    per = Counter(q.true_booking_ref for q in dev.enquiries)
    def mean(cls):
        group = [s for s in dev.shipments if s.delay_class == cls]
        return sum(per[s.booking_ref] for s in group) / len(group)
    assert mean("long") > 1.3 * mean("none")


def test_delay_driven_enquiries_come_after_notice(dev):
    for q in dev.enquiries:
        if q.delay_driven:
            s = dev.shipment(q.true_booking_ref)
            assert q.enquiry_type == "delay" and q.received_at >= first_delay_notice(dev, s)


def test_stated_reference_matches_kind(dev):
    for q in dev.enquiries:
        s = dev.shipment(q.true_booking_ref)
        if q.reference_kind == "booking":
            assert q.stated_reference == s.booking_ref
        elif q.reference_kind == "container":
            assert q.stated_reference in s.container_refs
        elif q.reference_kind == "bl":
            assert q.stated_reference == s.bl_ref and q.received_at >= s.bl_issued_at
        else:
            assert q.stated_reference not in {s.booking_ref, s.bl_ref, *s.container_refs}


def test_wrong_reference_share_close_to_config(dev, dev_cfg):
    wrong = sum(q.reference_kind in {"typo", "other_shipment"} for q in dev.enquiries)
    assert wrong / len(dev.enquiries) == pytest.approx(dev_cfg.enquiries.wrong_reference_share, abs=0.015)
