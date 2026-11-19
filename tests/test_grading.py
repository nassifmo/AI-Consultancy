from copy import deepcopy
import csv
from datetime import datetime, timedelta
import json
from pathlib import Path
import unittest

from evaluator import grade_enquiry


PROJECT = Path(__file__).resolve().parents[1]
BENCHMARK = PROJECT / "datagen" / "datasets" / "scenarios"
POLICY = json.loads((PROJECT / "evaluator" / "policy.json").read_text(encoding="utf-8"))
NOW = datetime.fromisoformat("2026-03-09T09:00:00+00:00")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def export_rows(case, filename):
    with (BENCHMARK / case / "exports" / filename).open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def expected(case, enquiry_id):
    return read_json(BENCHMARK / case / "ground_truth" / "expected.json")[enquiry_id]


def timing(deviation, **extra):
    return {
        "observed_at": (NOW + timedelta(seconds=deviation)).isoformat(),
        "reference_at": NOW.isoformat(),
        "refs": ["tracking_events.json#event", "responses.csv#message"],
        **extra,
    }


class GradingTests(unittest.TestCase):
    def test_carrier_eta_and_request_context_from_benchmark_exports(self):
        for case in ("S28", "S29", "S30"):
            with self.subTest(case=case):
                request, = export_rows(case, "enquiries.csv")
                reply, = export_rows(case, "responses.csv")
                events = read_json(BENCHMARK / case / "exports" / "tracking_events.json")
                shipment = next(r for r in export_rows(case, "shipments.csv") if r["booking_ref"] == request["stated_reference"])
                visible = [
                    event for event in events
                    if event["booking_ref"] == shipment["booking_ref"] and event["classifier"] == "EST"
                    and event["event_type_code"] == "ARRI"
                    and datetime.fromisoformat(event["event_created_datetime"]) <= datetime.fromisoformat(reply["sent_at"])
                ]
                reference = max(visible, key=lambda event: datetime.fromisoformat(event["event_created_datetime"]))
                profile = "arrival_coordination" if "monitoring team" in request["customer_message"] else "shipment_status"
                criterion = "coordination_eta" if profile == "arrival_coordination" else "eta_accuracy"
                # The test supplies reviewed customer context. Production extraction is a separate step.
                context = {"decision_cutoff_at": "2026-03-16T11:00:00+01:00"} if profile == "arrival_coordination" else {"context_impact": "minor"}
                result = grade_enquiry(POLICY, {
                    "enquiry_id": request["enquiry_id"],
                    "profile": profile,
                    "conditions": {"eta_reply_in_scope": True, "status_reply_in_scope": True},
                    "evidence": {
                        "shipment_identity": {
                            "passed": reply["shipment_reference"] == shipment["booking_ref"],
                            "refs": ["shipments.csv#" + shipment["booking_ref"], "responses.csv#" + reply["response_id"]],
                        },
                        criterion: {
                            "observed_at": reply["claimed_eta"],
                            "reference_at": reference["event_datetime"],
                            "refs": [
                                "tracking_events.json#" + reference["event_id"],
                                "responses.csv#" + reply["response_id"],
                                "enquiries.csv#" + request["enquiry_id"],
                            ],
                            **context,
                        },
                    },
                })
                target = expected(case, request["enquiry_id"])
                grade = result["criteria"][criterion]
                self.assertEqual(grade["eta_error_seconds"], target["eta_error_seconds"])
                self.assertEqual(grade["severity"], target["severity"])
                self.assertEqual(grade["crosses_decision_cutoff"], True if case == "S30" else None)
                self.assertIsNone(grade["score"])
                self.assertEqual(result["outcome"]["state"], "unknown")

    def test_configurable_timing_scores_are_profile_specific_and_asymmetric(self):
        policy = deepcopy(POLICY)
        policy["criteria"]["eta_accuracy"].update(zero_score_early_seconds=120, zero_score_late_seconds=240)
        policy["criteria"]["coordination_eta"].update(zero_score_early_seconds=60, zero_score_late_seconds=120)
        for profile, criterion, seconds, score in [
            ("shipment_status", "eta_accuracy", 60, 75),
            ("shipment_status", "eta_accuracy", -60, 50),
            ("arrival_coordination", "coordination_eta", 60, 50),
            ("arrival_coordination", "coordination_eta", -3600, 0),
        ]:
            with self.subTest(profile=profile, seconds=seconds):
                finding = grade_enquiry(policy, {
                    "enquiry_id": "test", "profile": profile,
                    "conditions": {"eta_reply_in_scope": True},
                    "evidence": {criterion: timing(seconds)},
                })["criteria"][criterion]
                self.assertEqual(finding["score"], score)
                self.assertEqual(finding["eta_error_seconds"], seconds)
                self.assertEqual(finding["severity"], "unknown")

    def test_deadline_penalizes_only_lateness(self):
        policy = deepcopy(POLICY)
        policy["criteria"]["escalation_deadline"]["zero_score_late_seconds"] = 60
        for seconds, on_time, delay, score in [(-10, True, 0, 100), (0, True, 0, 100), (1, False, 1, 100 * (1 - 1 / 60))]:
            with self.subTest(seconds=seconds):
                finding = grade_enquiry(policy, {
                    "enquiry_id": "test", "profile": "shipment_delay",
                    "conditions": {"escalation_required": True},
                    "evidence": {"escalation_deadline": timing(seconds, context_impact="minor")},
                })["criteria"]["escalation_deadline"]
                self.assertEqual(finding["on_time"], on_time)
                self.assertEqual(finding["delay_seconds"], delay)
                self.assertAlmostEqual(finding["score"], score)

    def test_timing_boundary_and_recovery_from_benchmark_exports(self):
        for case in ("S31", "S33"):
            with self.subTest(case=case):
                request, = export_rows(case, "enquiries.csv")
                ticket, = export_rows(case, "cases.csv")
                replies = export_rows(case, "responses.csv")
                update = next(reply for reply in replies if reply["purpose"] == "case_update")
                closing_reply = replies[-1]
                opened = datetime.fromisoformat(ticket["opened_at"])
                due = datetime.fromisoformat(request["received_at"]) + timedelta(hours=2)
                refs = ["enquiries.csv#" + request["enquiry_id"], "cases.csv#" + ticket["case_id"]]
                self.assertEqual(ticket["closure_code"], "resolved_after_investigation")
                self.assertEqual(closing_reply["case_id"], ticket["case_id"])
                self.assertEqual(closing_reply["sent_at"], ticket["closed_at"])
                self.assertEqual(closing_reply["claimed_eta"], "2026-03-17T12:00:00+00:00")
                evidence = {
                    "escalation_deadline": {
                        "observed_at": ticket["opened_at"], "reference_at": due.isoformat(),
                        "refs": refs, "context_impact": "minor" if case == "S31" else "critical",
                    },
                    "follow_up_deadline": {
                        "observed_at": update["sent_at"],
                        "reference_at": (opened + timedelta(hours=48)).isoformat(),
                        "refs": refs + ["responses.csv#" + update["response_id"]],
                    },
                }
                if case == "S33":
                    run, = read_json(BENCHMARK / case / "exports" / "agent_runs.json")
                    tool_names = {step["tool_name"] for step in run["steps"]}
                    evidence["initial_escalation"] = {
                        "steps": {
                            "opened_case": "create_case" in tool_names,
                            "routed_to_operations": "escalate_case" in tool_names,
                        },
                        "refs": ["agent_runs.json#" + run["run_id"]],
                    }
                result = grade_enquiry(POLICY, {
                    "enquiry_id": request["enquiry_id"], "profile": "shipment_delay",
                    "conditions": {"escalation_required": True, "follow_up_required": True},
                    "evidence": evidence,
                    "outcome": {
                        "state": "resolved",
                        "refs": refs + ["responses.csv#" + closing_reply["response_id"]],
                    },
                })
                target = expected(case, request["enquiry_id"])
                deadline = result["criteria"]["escalation_deadline"]
                self.assertEqual(deadline["on_time"], target["escalation_on_time"])
                self.assertEqual(deadline["delay_seconds"], target["escalation_delay_seconds"])
                self.assertTrue(result["criteria"]["follow_up_deadline"]["on_time"])
                self.assertEqual(result["outcome"]["state"], target["state"])
                if case == "S33":
                    self.assertTrue(result["initial_failure"])
                    self.assertEqual(result["criteria"]["initial_escalation"]["severity"], "critical")

    def test_wrong_container_stays_flagged_after_a_human_correction(self):
        case = "S32"
        request, = export_rows(case, "enquiries.csv")
        _, correction = export_rows(case, "responses.csv")
        run, = read_json(BENCHMARK / case / "exports" / "agent_runs.json")
        lookup = next(step for step in run["steps"] if step["tool_name"] == "get_tracking_status")
        result = grade_enquiry(POLICY, {
            "enquiry_id": request["enquiry_id"], "profile": "shipment_status",
            "conditions": {"eta_reply_in_scope": False, "status_reply_in_scope": True},
            "evidence": {
                "shipment_identity": {
                    "passed": request["stated_reference"] == lookup["tool_input"],
                    "refs": ["enquiries.csv#" + request["enquiry_id"], "agent_runs.json#" + run["run_id"]],
                },
                "milestone_status": {
                    "passed": correction["claimed_status"] == "arrived",
                    "refs": ["responses.csv#" + correction["response_id"], "tracking_events.json#E-M1"],
                },
            },
            "outcome": {
                "state": "resolved" if correction["purpose"] == "correction" and correction["container_reference"] == request["stated_reference"] else "unknown",
                "refs": ["responses.csv#" + correction["response_id"]],
            },
        })
        target = expected(case, request["enquiry_id"])
        self.assertEqual(result["outcome"]["state"], target["state"])
        self.assertEqual(result["initial_failure"], target["initial_failure"])
        self.assertEqual(result["criteria"]["shipment_identity"]["severity"], target["severity"])
        self.assertEqual(result["criteria"]["eta_accuracy"]["status"], "not_applicable")
        self.assertEqual(result["criteria"]["milestone_status"]["status"], "met")

    def test_missing_proof_and_inapplicable_checks_are_distinct(self):
        result = grade_enquiry(POLICY, {
            "enquiry_id": "test", "profile": "shipment_delay",
            "conditions": {"escalation_required": False, "eta_reply_in_scope": True},
            "evidence": {
                "shipment_identity": {"passed": True, "refs": []},
                "eta_accuracy": timing(0, observed_at="2026-03-09T09:00:00"),
            },
            "outcome": {"state": "resolved"},
        })
        self.assertEqual(result["criteria"]["escalation_deadline"]["status"], "not_applicable")
        self.assertEqual(result["criteria"]["follow_up_deadline"]["status"], "unknown")
        self.assertEqual(result["criteria"]["shipment_identity"]["status"], "unknown")
        self.assertEqual(result["criteria"]["eta_accuracy"]["status"], "unknown")
        self.assertEqual(result["outcome"]["state"], "unknown")
        self.assertIsNone(result["initial_failure"])

    def test_partial_steps_and_critical_omission_use_separate_fields(self):
        policy = deepcopy(POLICY)
        policy["criteria"]["initial_escalation"]["critical_steps"] = ["opened_case"]
        for steps, status, score, failure in [
            ({"opened_case": True, "routed_to_operations": False}, "partial", 50, False),
            ({"opened_case": True}, "unknown", None, False),
            ({"opened_case": False}, "unmet", None, True),
        ]:
            with self.subTest(steps=steps):
                result = grade_enquiry(policy, {
                    "enquiry_id": "test", "profile": "shipment_delay",
                    "conditions": {"escalation_required": True},
                    "evidence": {
                        "shipment_identity": {"passed": True, "refs": ["tracking_events.json#event"]},
                        "initial_escalation": {"steps": steps, "refs": ["case_history.csv#event"]},
                    },
                })
                finding = result["criteria"]["initial_escalation"]
                self.assertEqual(finding["status"], status)
                self.assertEqual(finding["score"], score)
                self.assertEqual(result["initial_failure"], failure)

    def test_new_request_type_uses_added_policy_criteria(self):
        policy = deepcopy(POLICY)
        policy["profiles"]["document_status"] = ["document_verified"]
        policy["criteria"]["document_verified"] = {"method": "binary"}
        result = grade_enquiry(policy, {
            "enquiry_id": "test", "profile": "document_status",
            "evidence": {"document_verified": {"passed": True, "refs": ["documents.csv#doc"]}},
        })
        self.assertEqual(set(result["criteria"]), {"document_verified"})
        self.assertEqual(result["criteria"]["document_verified"]["status"], "met")

    def test_bad_policy_is_rejected(self):
        policy = deepcopy(POLICY)
        policy["criteria"]["eta_accuracy"]["zero_score_late_seconds"] = -1
        with self.assertRaisesRegex(ValueError, "positive number"):
            grade_enquiry(policy, {"enquiry_id": "test", "profile": "shipment_status"})


if __name__ == "__main__":
    unittest.main()
