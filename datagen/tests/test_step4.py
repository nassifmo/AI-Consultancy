"""Tests for step 4: local-time rendering and defect injection.

Each recoverable defect is checked by recovering the clean data from the damaged export;
each evidence-removing defect is checked by its effect on the expected evaluator state."""

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from datagen.config_schema import GeneratorConfig, load_config
from datagen.generate import generate_all, run
from datagen.generator.handling import HUMAN_BASELINE

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
HEAVY = {k: 0.05 for k in ("duplicate_row", "missing_field", "missing_snapshot", "timezone_shift", "id_typo",
                           "orphan_record", "retry_row", "late_record", "conflicting_closure")}


def _cfg(name="default.yaml", rates=None, enabled=True):
    data = load_config(CONFIG_DIR / name).model_dump()
    data["defects"]["enabled"] = enabled
    if rates:
        data["defects"]["rates"] = rates
    return GeneratorConfig.model_validate(data)


@pytest.fixture(scope="module")
def g():
    return generate_all(_cfg(rates=HEAVY))


def _defects(g, kind):
    return [d for d in g.tables["injected_defects"] if d["defect_type"] == kind]


def _dedupe(rows, pk):
    seen, out = set(), []
    for r in rows:
        if r[pk] not in seen:
            seen.add(r[pk])
            out.append(r)
    return out


# ---------------------------------------------------------------- rendering


def test_local_time_files_keep_the_same_instant(g):
    tz = ZoneInfo("Asia/Beirut")
    cases = {c["case_id"]: c for c in g.clean_tables["cases"]}
    for c in g.handled.cases:
        exported = datetime.fromisoformat(cases[c["_id"]]["opened_at"])
        assert exported.utcoffset() == c["opened_at"].astimezone(tz).utcoffset()
        assert exported == c["opened_at"]


def test_utc_files_stay_utc(g):
    for r in g.clean_tables["responses"][:200]:
        assert datetime.fromisoformat(r["sent_at"]).utcoffset().total_seconds() == 0


def test_no_sub_second_timestamps(g):
    for key in ("cases", "responses", "agent_work", "enquiries"):
        for r in g.clean_tables[key][:500]:
            for v in r.values():
                if isinstance(v, str) and "T" in v and v[:4].isdigit():
                    assert "." not in v, v


# ---------------------------------------------------------------- bookkeeping


def test_every_defect_type_injected_and_logged(g):
    kinds = Counter(d["defect_type"] for d in g.tables["injected_defects"])
    assert set(HEAVY) <= set(kinds)
    ids = [d["defect_id"] for d in g.tables["injected_defects"]]
    assert len(ids) == len(set(ids))


def test_defects_are_deterministic():
    a, b = generate_all(_cfg(rates=HEAVY)), generate_all(_cfg(rates=HEAVY))
    assert a.tables["injected_defects"] == b.tables["injected_defects"]


def test_disabled_means_clean():
    t = generate_all(_cfg("tiny.yaml", enabled=False))
    assert t.tables["injected_defects"] == []
    assert t.tables["responses"] == t.clean_tables["responses"]


def test_tiny_writes_empty_defect_file_with_header(tmp_path):
    out = run(CONFIG_DIR / "tiny.yaml", tmp_path / "t")
    lines = (out / "ground_truth" / "injected_defects.csv").read_text().splitlines()
    assert lines == ["defect_id,file,record_id,defect_type,field,detail,affected_enquiries"]
    assert (out / "exports" / "export_metadata.json").exists()


# ---------------------------------------------------------------- recoverable defects


@pytest.mark.parametrize("key, pk", [("enquiries", "enquiry_id"), ("responses", "response_id")])
def test_duplicates_and_late_rows_recoverable(g, key, pk):
    damaged = sorted(_dedupe(g.tables[key], pk), key=lambda r: r[pk])
    clean = sorted(g.clean_tables[key], key=lambda r: r[pk])
    assert [r[pk] for r in damaged] == [r[pk] for r in clean]
    assert len(g.tables[key]) > len(clean)  # duplicates really were added


def test_late_rows_break_file_order(g):
    times = [r["received_at"] for r in g.tables["enquiries"]]
    assert times != sorted(times)


def test_retry_rows_are_technical_and_precede_their_run(g):
    runs = {r["run_id"]: r for r in g.tables["agent_runs"]}
    retries = _defects(g, "retry_row")
    assert retries
    for d in retries:
        retry, original = runs[d["record_id"]], runs[d["record_id"][:-2]]
        assert retry["enquiry_id"] == original["enquiry_id"]
        assert retry["started_at"] < original["started_at"]
        assert retry["tokens_in"] is None and retry["steps"][0]["success"] is False


def test_timezone_shift_recoverable_from_metadata(g):
    tz = ZoneInfo("Asia/Beirut")
    clean = {r["case_id"]: r for r in g.clean_tables["cases"]}
    damaged = {r["case_id"]: r for r in g.tables["cases"]}
    hits = [d for d in _defects(g, "timezone_shift") if d["file"] == "cases.csv"]
    assert hits
    for d in hits:
        naive = datetime.fromisoformat(damaged[d["record_id"]]["opened_at"])
        assert naive.tzinfo is None
        assert naive.replace(tzinfo=tz) == datetime.fromisoformat(clean[d["record_id"]]["opened_at"])


def test_case_id_typo_recoverable_through_responses(g):
    known = {q["enquiry_id"] for q in g.clean_tables["enquiries"]}
    clean = {c["case_id"]: c["enquiry_id"] for c in g.clean_tables["cases"]}
    via_responses = {r["case_id"]: r["enquiry_id"] for r in g.tables["responses"] if r["case_id"]}
    damaged = {c["case_id"]: c["enquiry_id"] for c in g.tables["cases"]}
    hits = [d for d in _defects(g, "id_typo") if d["file"] == "cases.csv"]
    assert hits
    for d in hits:
        cid = d["record_id"]
        assert damaged[cid] not in known
        if cid in via_responses:
            assert via_responses[cid] == clean[cid]


def test_orphans_point_nowhere(g):
    known = {q["enquiry_id"] for q in g.clean_tables["enquiries"]}
    work = {w["work_id"]: w for w in g.tables["agent_work"]}
    for d in _defects(g, "orphan_record"):
        assert work[d["record_id"]]["enquiry_id"] not in known


def test_closed_at_blank_but_history_shows_closure(g):
    history = {(h["case_id"], h["new_value"]) for h in g.tables["case_history"]}
    for d in _defects(g, "missing_field"):
        if d["field"] == "closed_at":
            assert (d["record_id"], "closed") in history


# ---------------------------------------------------------------- evidence-removing defects


def test_missing_snapshot_removes_tracking_and_makes_enquiries_unknown(g):
    ships = {d["record_id"] for d in _defects(g, "missing_snapshot")}
    assert ships
    assert not ships & {e["booking_ref"] for e in g.tables["tracking_events"]}
    for r in g.tables["true_outcome"]:
        if r["true_booking_ref"] in ships and r["true_outcome"] != "out_of_scope":
            assert r["expected_evaluator_state"] == "unknown" and r["scenario_id"] == "S9"


def test_missing_claim_on_final_answer_is_unknown(g):
    truth = {r["enquiry_id"]: r for r in g.tables["true_outcome"]}
    hits = [d for d in _defects(g, "missing_field") if d["field"] in ("claimed_eta", "claimed_status")]
    assert any(d["affected_enquiries"] for d in hits)
    for d in hits:
        for eid in (d["affected_enquiries"] or "").split(";"):
            if eid:
                assert truth[eid]["expected_evaluator_state"] == "unknown"


def test_conflicting_closure_marks_deciding_case_unknown(g):
    hits = _defects(g, "conflicting_closure")
    assert hits
    reopened = {h["case_id"] for h in g.tables["case_history"] if h["new_value"] == "open" and h["old_value"] == "closed"}
    truth = {r["enquiry_id"]: r for r in g.tables["true_outcome"]}
    for d in hits:
        assert d["record_id"] in reopened
        for eid in (d["affected_enquiries"] or "").split(";"):
            if eid:
                assert truth[eid]["expected_evaluator_state"] == "unknown"


def test_expected_state_only_changes_to_unknown_for_in_scope(g):
    clean = {r["enquiry_id"]: r for r in g.clean_tables["true_outcome"]}
    changed = 0
    for r in g.tables["true_outcome"]:
        assert r["true_outcome"] == clean[r["enquiry_id"]]["true_outcome"]  # truth never changes
        if r["expected_evaluator_state"] != r["true_outcome"]:
            assert r["expected_evaluator_state"] == "unknown" and r["true_outcome"] != "out_of_scope"
            changed += 1
    assert changed > 0


def test_planted_effects_unaffected_by_defects(g):
    assert g.tables["planted_effects"] == g.clean_tables["planted_effects"]
    assert HUMAN_BASELINE in g.tables["planted_effects"][0]["metrics_by_arm"]
