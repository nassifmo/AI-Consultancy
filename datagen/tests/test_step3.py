"""Tests for step 3: handling, cases, human work, rescues, repeat contacts, costs and ground truth.

Several tests recompute truth independently from the *exported* files, to make sure the
ground truth is recoverable from what a partner would give us (no defects yet)."""

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from datagen.config_schema import GeneratorConfig, load_config
from datagen.generate import generate_all, rules_for, run, validate_tables
from datagen.generator.handling import HUMAN_BASELINE
from datagen.generator.state import known_state_at

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def _cfg(name="default.yaml", **design):
    cfg = load_config(CONFIG_DIR / name)
    if design:
        data = cfg.model_dump()
        data["design"].update(design)
        cfg = GeneratorConfig.model_validate(data)  # re-validate the modified design
    return cfg


@pytest.fixture(scope="module")
def dev():
    return generate_all(_cfg())


@pytest.fixture(scope="module")
def tiny():
    return generate_all(_cfg("tiny.yaml"))


def _dt(s):
    return datetime.fromisoformat(s) if s else None


def _by(rows, key):
    out = defaultdict(list)
    for r in rows:
        out[r[key]].append(r)
    return out


# ---------------------------------------------------------------- validity


@pytest.mark.parametrize("g", ["tiny", "dev"])
def test_all_tables_match_dictionary(g, request):
    assert request.getfixturevalue(g).clean_issues == []


def test_full_output_reproducible():
    a, b = generate_all(_cfg("tiny.yaml")), generate_all(_cfg("tiny.yaml"))
    assert a.tables == b.tables and a.clean_tables == b.clean_tables


def test_run_writes_exports_and_ground_truth(tmp_path):
    out = run(CONFIG_DIR / "tiny.yaml", tmp_path / "t")
    exports = {p.name for p in (out / "exports").iterdir()}
    assert {"agent_runs.json", "cases.csv", "case_history.csv", "agent_work.csv", "responses.csv",
            "ai_invoice.csv", "rollout_log.csv", "cost_parameters.json", "staffing.csv",
            "service_rules.yaml"} <= exports
    assert {p.name for p in (out / "ground_truth").iterdir()} == {
        "true_outcome.csv", "planted_effects.json", "injected_defects.csv"}


# ---------------------------------------------------------------- arms and agent runs


def test_randomized_split_shares(dev):
    pop = [t for t in dev.handled.truths if t.enquiry.repeat_of is None]
    counts = Counter(t.arm for t in pop)
    for arm in dev.cfg.design.arms:
        assert counts[arm.name] / len(pop) == pytest.approx(arm.share, abs=0.03)


def test_repeats_stay_in_parent_arm(dev):
    for q in dev.world.enquiries:
        if q.repeat_of is not None:
            assert q.arm == q.repeat_of.arm
            assert q.customer_id == q.repeat_of.customer_id
            assert q.true_booking_ref == q.repeat_of.true_booking_ref
            assert q.received_at > q.repeat_of.received_at


def test_one_agent_run_per_ai_enquiry_and_none_for_humans(dev):
    runs = Counter(r["enquiry_id"] for r in dev.clean_tables["agent_runs"])
    for t in dev.handled.truths:
        assert runs[t.enquiry.enquiry_id] == (0 if t.arm == HUMAN_BASELINE else 1)


def test_handoffs_have_human_work(dev):
    work = _by(dev.clean_tables["agent_work"], "enquiry_id")
    for r in dev.clean_tables["agent_runs"]:
        if r["handoff_flag"]:
            assert any(w["activity"] == "handle_enquiry" for w in work[r["enquiry_id"]])
            assert r["self_reported_outcome"] == "handed_off"


def test_out_of_scope_always_handed_off(dev):
    for t in dev.handled.truths:
        if not t.in_scope:
            assert t.true_outcome == "out_of_scope"
            assert t.arm == HUMAN_BASELINE or t.handed_off


# ---------------------------------------------------------------- truth recoverable from exports


def test_human_seconds_match_exported_work(dev):
    work = _by(dev.clean_tables["agent_work"], "enquiry_id")
    for row in dev.clean_tables["true_outcome"]:
        assert row["true_human_seconds"] == sum(w["active_seconds"] for w in work[row["enquiry_id"]])


def test_first_answer_correctness_recomputed_from_exports(dev):
    rules = dev.rules
    tol = timedelta(hours=rules.information_check.eta_tolerance_hours)
    events = _by(dev.clean_tables["tracking_events"], "booking_ref")
    truth = {r["enquiry_id"]: r for r in dev.clean_tables["true_outcome"]}
    world = dev.world
    first = {}
    for r in sorted(dev.clean_tables["responses"], key=lambda r: r["sent_at"]):
        if r["purpose"] == "answer" and r["enquiry_id"] not in first:
            first[r["enquiry_id"]] = r
    checked = 0
    for eid, r in first.items():
        tr = truth[eid]
        if tr["first_answer_correct"] is None:
            continue
        ship = tr["true_booking_ref"]
        k = known_state_at(world.events_for(ship), _dt(r["sent_at"]))
        eta = _dt(r["claimed_eta"])
        ok = (r["shipment_reference"] == ship and r["claimed_status"] == k.status
              and ((eta is None and k.eta is None) or (eta and k.eta and abs(eta - k.eta) <= tol)))
        assert ok == tr["first_answer_correct"], eid
        assert all(e["event_created_datetime"] for e in events[ship])
        checked += 1
    assert checked > 1000


def test_resolved_escalations_meet_the_rules(dev):
    r = dev.rules
    cases = _by(dev.clean_tables["cases"], "enquiry_id")
    updates = _by([x for x in dev.clean_tables["responses"] if x["purpose"] == "case_update"], "case_id")
    enquiries = {q["enquiry_id"]: q for q in dev.clean_tables["enquiries"]}
    n = 0
    for row in dev.clean_tables["true_outcome"]:
        if row["escalation_required"] and row["true_outcome"] in ("resolved", "escalated_open"):
            received = _dt(enquiries[row["enquiry_id"]]["received_at"])
            ok = False
            for c in cases[row["enquiry_id"]]:
                if c["reason"] != "delay_investigation":
                    continue
                opened = _dt(c["opened_at"])
                ups = [_dt(u["sent_at"]) for u in updates[c["case_id"]]]
                if opened - received <= timedelta(hours=r.escalation.max_hours_to_escalate) and any(
                    u - opened <= timedelta(hours=r.follow_up.followup_deadline_hours) for u in ups
                ):
                    ok = True
            assert ok, row["enquiry_id"]
            n += 1
    assert n > 20


def test_rescues_leave_evidence(dev):
    cases = _by(dev.clean_tables["cases"], "enquiry_id")
    corrections = Counter(r["enquiry_id"] for r in dev.clean_tables["responses"] if r["purpose"] == "correction")
    rescued = [r for r in dev.clean_tables["true_outcome"] if r["was_rescued"]]
    assert rescued
    for r in rescued:
        assert corrections[r["enquiry_id"]] == 1
        assert any(c["reason"] == "wrong_information" for c in cases[r["enquiry_id"]])
        assert r["true_human_seconds"] > 0 and not r["ai_only"]


def test_repeat_contact_flag_matches_definition(dev):
    window = timedelta(days=dev.rules.follow_up.repeat_contact_window_days)
    enq = {q["enquiry_id"]: q for q in dev.clean_tables["enquiries"]}
    groups = _by(dev.clean_tables["true_outcome"], "true_booking_ref")
    for rows in groups.values():
        for r in rows:
            q = enq[r["enquiry_id"]]
            later = [
                o for o in rows
                if enq[o["enquiry_id"]]["customer_id"] == q["customer_id"]
                and timedelta(0) < _dt(enq[o["enquiry_id"]]["received_at"]) - _dt(q["received_at"]) <= window
            ]
            assert r["repeat_contact"] == bool(later)


def test_repeat_contact_means_not_resolved(dev):
    for r in dev.clean_tables["true_outcome"]:
        if r["repeat_contact"] and r["true_outcome"] != "out_of_scope":
            assert r["true_outcome"] == "failed"


def test_ai_only_definition(dev):
    for r in dev.clean_tables["true_outcome"]:
        if r["ai_only"]:
            assert r["arm"] != HUMAN_BASELINE and r["true_human_seconds"] == 0 and r["true_outcome"] == "resolved"


def test_false_self_reports_exist_and_are_flagged(dev):
    runs = {r["enquiry_id"]: r for r in dev.clean_tables["agent_runs"]}
    flagged = [r for r in dev.clean_tables["true_outcome"] if r["self_report_false"]]
    assert flagged
    for r in flagged:
        assert runs[r["enquiry_id"]]["self_reported_outcome"] == "resolved" and r["true_outcome"] != "resolved"


def test_every_scenario_label_is_known(dev):
    assert {r["scenario_id"] for r in dev.clean_tables["true_outcome"]} <= {f"S{i}" for i in range(1, 13)}


# ---------------------------------------------------------------- costs


def test_invoice_matches_true_ai_cost(dev):
    invoiced = sum(r["amount"] for r in dev.clean_tables["ai_invoice"] if r["line_item"] != "platform_fee")
    true = sum(r["true_ai_cost"] for r in dev.clean_tables["true_outcome"])
    assert invoiced == pytest.approx(true, rel=0.01)


def test_staffing_flat_and_no_cash_savings(dev):
    heads = {r["support_headcount"] for r in dev.clean_tables["staffing"]}
    assert len(heads) == 1
    assert dev.clean_tables["planted_effects"][0]["realized_cash_savings"] == 0.0


def test_planted_metrics_match_truth_rows(dev):
    pe = dev.clean_tables["planted_effects"][0]
    pop = [r for r in dev.clean_tables["true_outcome"] if r["in_population"] and r["true_outcome"] != "out_of_scope"]
    for arm, m in pe["metrics_by_arm"].items():
        rows = [r for r in pop if r["arm"] == arm]
        assert m["n"] == len(rows)
        rate = sum(r["true_outcome"] == "resolved" for r in rows) / len(rows)
        assert m["verified_resolution_rate"] == pytest.approx(rate, abs=1e-4)


# ---------------------------------------------------------------- designs and planted differences


def test_integrator_enhancement_is_better():
    cfg = _cfg(arms=[{"name": "agent_v1", "share": 0.5}, {"name": "agent_v2", "share": 0.5}])
    g = generate_all(cfg)
    m = g.clean_tables["planted_effects"][0]["metrics_by_arm"]
    assert m["agent_v2"]["first_answer_correct_rate"] > m["agent_v1"]["first_answer_correct_rate"]
    assert m["agent_v2"]["verified_resolution_rate"] > m["agent_v1"]["verified_resolution_rate"]


def test_ai_agent_uses_less_human_time_than_baseline(dev):
    m = dev.clean_tables["planted_effects"][0]["metrics_by_arm"]
    assert m["agent_v1"]["human_minutes_per_enquiry"] < m[HUMAN_BASELINE]["human_minutes_per_enquiry"]


def test_before_after_design_switches_on_rollout_date():
    from datetime import date

    cfg = _cfg(type="before_after_confounded", rollout_date=date(2026, 2, 15))
    g = generate_all(cfg)
    cut = datetime(2026, 2, 15, tzinfo=g.world.period_start.tzinfo)
    for q in g.world.enquiries:
        if q.repeat_of is None:
            assert q.arm == (HUMAN_BASELINE if q.received_at < cut else "agent_v1")
    assert len(g.clean_tables["rollout_log"]) == 2


def test_staged_rollout_splits_by_region():
    from datetime import date

    cfg = _cfg(type="staged_rollout", rollout_date=date(2026, 2, 1))
    g = generate_all(cfg)
    cut = datetime(2026, 2, 1, tzinfo=g.world.period_start.tzinfo)
    after = Counter(q.arm for q in g.world.enquiries if q.repeat_of is None and q.received_at >= cut)
    assert after[HUMAN_BASELINE] > 0 and after["agent_v1"] > 0
