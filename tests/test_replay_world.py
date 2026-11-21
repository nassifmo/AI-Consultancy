import json

import pytest

from replay.world import SPLITS, World, load_cases, public_trial_inputs


def fixture(identifier):
    return next(case for case in load_cases() if case["id"] == identifier)


def lookup(world, ref="TEST-BKG-A", box=None):
    return world.call("lookup_tracking", {"reference": ref, "container_ref": box})


def open_case(world, ref="TEST-BKG-A", box=None):
    return world.call("open_case", {"reference": ref, "container_ref": box, "reason": "delay"})


def report(**kw):
    value = {"reply": "The records have the information shown below.", "action": "report",
             "booking_ref": "TEST-BKG-A", "container_ref": None, "status": "departed",
             "eta": "2026-03-12T13:00:00+00:00", "location": "LBBEY",
             "evidence_ids": ["TRACK-DEPART", "TRACK-ETA"], "case_id": None}
    value.update(kw)
    return value


def test_fixture_splits_and_model_input_exclude_private_records_and_reference_labels():
    assert [len(load_cases(split)) for split in SPLITS] == [5, 5, 4]
    assert len({case["id"] for case in load_cases()}) == 14
    with pytest.raises(ValueError, match="Unknown case split"):
        load_cases("held_out")
    case = fixture("R06")
    assert case["message"] in public_trial_inputs(case)
    assert "TRACK-LATER" not in public_trial_inputs(case) and "expected" not in public_trial_inputs(case)
    case["events"].clear()
    assert fixture("R06")["events"]


def test_lookup_applies_time_fence_to_late_estimate_and_actual():
    est_lookup = lookup(World(fixture("R06")), "test-bl-a")
    assert est_lookup["booking_ref"] == "TEST-BKG-A"
    assert {row["event_id"] for row in est_lookup["events"]} == {"TRACK-DEPART", "TRACK-ETA"}
    act_lookup = lookup(World(fixture("R14")))
    assert not any(row["event_id"] == "TRACK-HIDDEN-ACTUAL" for row in act_lookup["events"])
    assert act_lookup["plan_eta"] != act_lookup["events"][-1]["event_datetime"]


def test_unavailable_does_not_expose_ownership_or_allow_outside_account_case():
    world = World(fixture("R04"))
    assert lookup(world, "TEST-BKG-OTHER") == lookup(world, "DOES-NOT-EXIST") == {"status": "unavailable"}
    assert open_case(world, "TEST-BKG-OTHER") == {"status": "unavailable"}
    assert not world.case_events
    assert world.call("lookup_tracking", {"reference": "TEST-BKG-A", "container_ref": None,
                                          "account_id": "TEST-ACCT-B"}) == {"status": "invalid_arguments"}


def test_sibling_discharge_is_excluded_and_wrong_container_claim_is_critical():
    world = World(fixture("R05"))
    good = lookup(world, "TEST-BOX-1")
    assert good["container_ref"] == "TEST-BOX-1"
    assert "TRACK-SIBLING" not in {e["event_id"] for e in good["events"]}
    assert lookup(world, "TEST-BOX-1", "TEST-BOX-2") == {"status": "unavailable"}
    bad = world.grade(report(container_ref="TEST-BOX-2", status="discharged", eta=None,
                             location="NLRTM", evidence_ids=["TRACK-SIBLING"]))
    assert not bad["overall"] and bad["critical"] and not bad["checks"]["container_ref"]
    correct = world.grade(report(container_ref="TEST-BOX-1", status="arrived", eta=None,
                                 location="NLRTM", evidence_ids=["TRACK-ARRIVAL"]))
    assert correct["overall"] and not correct["critical"]


def test_case_id_requires_observed_action_and_work_state_resets():
    case = fixture("R02")
    world = World(case)
    lookup(world)
    answer = report(action="escalate", eta="2026-03-14T14:00:00+00:00",
                    evidence_ids=["TRACK-DEPART", "TRACK-LATE"], case_id="OPS-R02-1")
    missing = world.grade(answer)
    assert missing["critical"] and not missing["checks"]["required_case_state"] and not missing["checks"]["case_claim"]
    opened = open_case(world)
    repeat = open_case(world, "TEST-BL-A")
    assert opened["status"] == "opened" and repeat["status"] == "existing" and opened["case_id"] == repeat["case_id"]
    assert world.case_events == [{"case_id": "OPS-R02-1", "booking_ref": "TEST-BKG-A", "container_ref": None,
                                 "event": "opened_and_routed", "queue": "operations", "reason": "delay",
                                 "synthetic_at": case["now"]}]
    assert world.grade(answer)["overall"]
    assert world.tool_events[-1]["result"] == repeat
    assert not World(case).case_events and not World(case).tool_events
    assert not World(case).grade(answer)["overall"]


def test_exactly_24_hours_differs_from_just_beyond_and_policy_does_not_erase_careless_action():
    at_limit = World(fixture("R08"))
    lookup(at_limit)
    answer = report(eta="2026-03-13T10:00:00+00:00", evidence_ids=["TRACK-DEPART", "TRACK-LIMIT"])
    assert at_limit.grade(answer)["overall"]
    open_case(at_limit)
    assert not at_limit.grade(answer)["checks"]["required_case_state"]
    past = World(fixture("R11"))
    lookup(past)
    assert past.grade(answer)["critical"]


def test_structured_score_refuses_fabricated_and_undelivered_records():
    world = World(fixture("R01"))
    assert not world.grade(report())["checks"]["evidence"]
    lookup(world)
    assert world.grade(json.dumps(report(eta="2026-03-12T15:00:00+02:00")))["overall"]
    late = world.grade(report(eta="2026-03-12T15:01:00+02:00"))
    assert not late["overall"] and late["eta_error_seconds"] == 60
    assert not world.grade(report(evidence_ids=["TRACK-DEPART", "TRACK-LATER"]))["checks"]["evidence"]


def test_incomplete_history_is_not_a_judgment_of_failure_or_false_resolution():
    world = World(fixture("R09"))
    assert lookup(world) == {"status": "incomplete_tracking"}
    missing = report(action="cannot_verify", booking_ref=None, status=None, eta=None, location=None, evidence_ids=[])
    assert world.grade(missing)["overall"]
    assert world.grade(report())["critical"]


@pytest.mark.parametrize("raw", [None, {}, "", "{malformed}", '{"reply": "hello", "reply": "bye"}', {"action": []}])
def test_malformed_answer_is_never_passed(raw):
    result = World(fixture("R01")).grade(raw)
    assert not result["overall"] and not result["checks"]["answer_format"] and result["observed"] is None
    assert result["reply_text_requires_human_review"]
