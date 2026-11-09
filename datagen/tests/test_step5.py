"""Tests for step 5: the hand-written scenario library.

The library is written from the service rules, independently of the generator. These tests
check the library is well formed, cross-check the generator's state logic against the
hand-written expectations, and check the generator produces every scenario type."""

from collections import Counter
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from datagen.config_schema import load_config
from datagen.generate import generate_all
from datagen.generator.model import TrackingEvent
from datagen.generator.state import known_state_at
from datagen.scenario_library import SCENARIO_DIR, check, load_library, load_state_checks, write

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


@pytest.fixture(scope="module")
def lib():
    return load_library()


def test_library_is_well_formed(lib):
    assert check(lib) == []


def test_library_covers_all_planned_scenarios(lib):
    ids = {s.id for s in lib}
    assert {f"S{i}" for i in range(1, 13)} <= ids
    assert {f"B{i}" for i in range(1, 11)} <= ids
    assert any(i.startswith("D") for i in ids) and {"H1", "H2"} <= ids


def test_every_outcome_state_is_exercised(lib):
    states = {e["state"] for s in lib for e in s.expected.values()}
    assert states == {"resolved", "escalated_open", "failed", "unknown", "out_of_scope"}


def test_boundary_pairs_disagree(lib):
    """Each boundary pair must flip the result, or the pair tests nothing."""
    exp = {s.id: next(iter(s.expected.values()))["state"] for s in lib}
    for a, b in [("B1", "B2"), ("B3", "B4"), ("B5", "B6"), ("B7", "B8")]:
        assert exp[a] != exp[b], (a, b)
    first = lambda sid: next(s for s in lib if s.id == sid).expected
    assert first("B9")["ENQ-B09A"]["state"] != first("B10")["ENQ-B10A"]["state"]


def test_hand_written_state_checks_match_generator_logic():
    base = yaml.safe_load((SCENARIO_DIR / "base.yaml").read_text())
    events = [TrackingEvent(eid, ref, None, et, code, cls, datetime.fromisoformat(when),
                            datetime.fromisoformat(created), None)
              for eid, ref, et, code, cls, when, created in base["tracking_events"]]
    for c in load_state_checks():
        k = known_state_at([e for e in events if e.booking_ref == c["booking_ref"]], datetime.fromisoformat(c["at"]))
        assert k.status == c["status"], c
        assert k.eta == (datetime.fromisoformat(c["eta"]) if c["eta"] else None), c


def test_service_rules_document_boundary_interpretation():
    text = (CONFIG_DIR / "service_rules.yaml").read_text()
    for phrase in ("STRICTLY greater", "INCLUSIVE"):
        assert phrase in text


def test_generator_produces_every_scenario_label():
    g = generate_all(load_config(CONFIG_DIR / "default.yaml"))
    labels = Counter(r["scenario_id"] for r in g.tables["true_outcome"])
    missing = {f"S{i}" for i in range(1, 13)} - set(labels)
    assert not missing, f"generator never produced {sorted(missing)}"


def test_ai_answer_missing_claim_is_not_unknown():
    """Found while writing scenario D3A: the claim survives in agent_runs."""
    from datagen.config_schema import GeneratorConfig

    data = load_config(CONFIG_DIR / "default.yaml").model_dump()
    data["defects"]["rates"] = {"missing_field": 0.1}
    g = generate_all(GeneratorConfig.model_validate(data))
    responses = {r["response_id"]: r for r in g.clean_tables["responses"]}
    hits = [d for d in g.tables["injected_defects"]
            if d["file"] == "responses.csv" and d["field"] in ("claimed_eta", "claimed_status")]
    assert any(responses[d["record_id"]]["actor_type"] == "ai_agent" for d in hits)
    for d in hits:
        if responses[d["record_id"]]["actor_type"] == "ai_agent":
            assert d["affected_enquiries"] is None


def test_write_scenarios(tmp_path, lib):
    write(lib[:3], tmp_path)
    sc = tmp_path / lib[0].id
    assert (sc / "exports" / "enquiries.csv").exists() and (sc / "expected.json").exists()
