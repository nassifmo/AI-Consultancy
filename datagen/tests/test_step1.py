"""Tests for step 1: data dictionary, service rules and generator config."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from datagen.config_schema import GeneratorConfig, ServiceRules, load_config, load_rules
from datagen.dictionary_tools import (
    check_dictionary,
    load_dictionary,
    render_markdown,
    validate_records,
    validate_references,
)

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


@pytest.fixture(scope="module")
def d():
    return load_dictionary()


@pytest.fixture
def cfg_dict():
    return yaml.safe_load((CONFIG_DIR / "default.yaml").read_text())


# ---------------------------------------------------------------- dictionary


def test_dictionary_is_consistent(d):
    assert check_dictionary(d) == []


def test_dictionary_covers_all_partner_files(d):
    ids = {spec["id"] for spec in d["files"].values()}
    assert ids == {f"E{i}" for i in range(1, 14)}


def test_dictionary_detects_broken_reference(d):
    broken = yaml.safe_load(yaml.safe_dump(d))
    broken["files"]["cases"]["fields"][1]["references"] = "enquiries.nope"
    assert any("does not resolve" in p for p in check_dictionary(broken))


def test_render_markdown_lists_every_file(d):
    md = render_markdown(d)
    for spec in d["files"].values():
        assert spec["filename"] in md


# ---------------------------------------------------------------- record validation


GOOD_ENQUIRY = {
    "enquiry_id": "ENQ-1",
    "customer_id": "CUS-1",
    "channel": "voice",
    "received_at": "2026-01-05T09:00:00+00:00",
    "stated_reference": "BKG123",
    "enquiry_type": "delay",
    "language": "en",
}


def test_valid_record_passes(d):
    assert validate_records("enquiries", [GOOD_ENQUIRY], d) == []


@pytest.mark.parametrize(
    "change, expected",
    [
        ({"channel": "fax"}, "not in"),
        ({"received_at": "2026-01-05T09:00:00"}, "no UTC offset"),
        ({"enquiry_id": ""}, "required"),
        ({"unexpected": "x"}, "unknown field"),
    ],
)
def test_invalid_record_is_reported(d, change, expected):
    issues = validate_records("enquiries", [{**GOOD_ENQUIRY, **change}], d)
    assert any(expected in i.message for i in issues)


def test_nested_steps_are_validated(d):
    run = {
        "run_id": "RUN-1",
        "enquiry_id": "ENQ-1",
        "agent_version": "agent_v1",
        "started_at": "2026-01-05T09:00:00+00:00",
        "ended_at": "2026-01-05T09:02:00+00:00",
        "steps": [{"step_no": 1, "tool_name": "teleport", "success": True}],
        "self_reported_outcome": "resolved",
        "handoff_flag": False,
    }
    issues = validate_records("agent_runs", [run], d)
    assert [i.field for i in issues] == ["steps.tool_name"]


def test_csv_strings_are_accepted(d):
    row = {
        "work_id": "W1",
        "case_id": "C1",
        "agent_id": "A1",
        "accepted_at": "2026-01-05T09:00:00+00:00",
        "active_seconds": "300",
        "activity": "correct_ai_answer",
        "measurement_method": "logged",
    }
    assert validate_records("agent_work", [row], d) == []


def test_references_are_checked(d):
    tables = {
        "enquiries": [GOOD_ENQUIRY],
        "cases": [{"case_id": "C1", "enquiry_id": "ENQ-404"}],
    }
    issues = validate_references(tables, d)
    assert len(issues) == 1 and "ENQ-404" in issues[0].message


# ---------------------------------------------------------------- configs


def test_default_config_loads():
    cfg = load_config(CONFIG_DIR / "default.yaml")
    assert cfg.seed == 42


def test_service_rules_load():
    rules = load_rules(CONFIG_DIR / "service_rules.yaml")
    assert rules.escalation.escalate_if_delay_hours > 0


def test_closure_codes_match_dictionary(d):
    rules = load_rules(CONFIG_DIR / "service_rules.yaml")
    case_codes = next(f for f in d["files"]["cases"]["fields"] if f["name"] == "closure_code")["values"]
    assert rules.closure_codes.all_codes() == set(case_codes)


def test_shares_must_sum_to_one(cfg_dict):
    cfg_dict["enquiries"]["type_mix"]["status"] = 0.9
    with pytest.raises(ValidationError, match="sum to 1"):
        GeneratorConfig.model_validate(cfg_dict)


def test_probability_out_of_range(cfg_dict):
    cfg_dict["agents"]["agent_v1"]["handoff_prob"] = 1.5
    with pytest.raises(ValidationError):
        GeneratorConfig.model_validate(cfg_dict)


def test_arm_without_agent_behaviour(cfg_dict):
    cfg_dict["design"]["arms"][1]["name"] = "agent_v9"
    with pytest.raises(ValidationError, match="no entry under agents"):
        GeneratorConfig.model_validate(cfg_dict)


def test_rollout_design_needs_date(cfg_dict):
    cfg_dict["design"]["type"] = "staged_rollout"
    with pytest.raises(ValidationError, match="rollout_date"):
        GeneratorConfig.model_validate(cfg_dict)


def test_unknown_config_key_rejected(cfg_dict):
    cfg_dict["human"]["handle_minuts"] = {"median": 1, "p95": 2}
    with pytest.raises(ValidationError):
        GeneratorConfig.model_validate(cfg_dict)


def test_rules_reject_overlapping_closure_codes():
    data = yaml.safe_load((CONFIG_DIR / "service_rules.yaml").read_text())
    data["closure_codes"]["excluded"].append("resolved_info_provided")
    with pytest.raises(ValidationError, match="overlap"):
        ServiceRules.model_validate(data)
