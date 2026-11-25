from copy import deepcopy
import csv
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from evaluator.exports import TABLES
from evaluator.verification import verify_exports
from pilot.approval import approve_exports


PROJECT = Path(__file__).resolve().parents[1]
SCENARIOS = PROJECT / "datagen" / "datasets" / "scenarios"
POLICY = json.loads((PROJECT / "evaluator" / "policy.json").read_text(encoding="utf-8"))


def evaluate(case):
    return verify_exports(SCENARIOS / case / "exports", POLICY)["enquiries"]


def expected(case):
    file = SCENARIOS / case / "ground_truth" / "expected.json"
    return next(iter(json.loads(file.read_text(encoding="utf-8")).values()))


class ExportVerificationTests(unittest.TestCase):
    def test_contextual_timing_from_raw_exports(self):
        for case in ("S28", "S29", "S30"):
            with self.subTest(case=case):
                result, = evaluate(case)
                oracle = expected(case)
                name = "coordination_eta" if case == "S30" else "eta_accuracy"
                timing = result["criteria"][name]
                self.assertEqual(timing["eta_error_seconds"], oracle["eta_error_seconds"])
                self.assertEqual(timing["severity"], oracle["severity"])
                self.assertEqual(result["outcome"]["state"], oracle["state"])
                self.assertEqual(result["verification"]["initial_reply"]["matches_record"], oracle["first_answer_correct"])
                self.assertEqual(result["verification"]["human_work"]["active_seconds"], oracle["human_seconds"])
                self.assertIn("tracking_events.json#E-24C", timing["refs"])
        coordination, = evaluate("S30")
        self.assertFalse(coordination["criteria"]["arrival_decision"]["passed"])
        self.assertTrue(coordination["criteria"]["coordination_eta"]["crosses_decision_cutoff"])

    def test_recovers_without_erasing_initial_failure_or_lateness(self):
        for case in ("S31", "S32", "S33"):
            with self.subTest(case=case):
                result, = evaluate(case)
                oracle = expected(case)
                verification = result["verification"]
                self.assertEqual(result["outcome"]["state"], oracle["state"])
                self.assertEqual(result["initial_failure"], oracle.get("initial_failure", False))
                self.assertEqual(verification["human_recovery"], oracle.get("rescued", False))
                self.assertEqual(verification["human_work"]["active_seconds"], oracle["human_seconds"])
                self.assertEqual(verification["initial_reply"]["matches_record"], oracle["first_answer_correct"])
                self.assertEqual(verification["last_reply"]["matches_record"], oracle["info_correct"])
                if "escalation_delay_seconds" in oracle:
                    deadline = result["criteria"]["escalation_deadline"]
                    self.assertEqual(deadline["delay_seconds"], oracle["escalation_delay_seconds"])
                    self.assertFalse(deadline["on_time"])
                    self.assertTrue(any(ref.startswith("case_history.csv#") for ref in deadline["refs"]))

    def test_later_closure_differs_from_early_snapshot(self):
        for case in ("S23", "S24", "S25", "S26", "S27"):
            with self.subTest(case=case):
                result, = evaluate(case)
                oracle = expected(case)
                self.assertEqual(result["outcome"]["state"], oracle["state"])
                self.assertEqual(result["verification"]["human_work"]["active_seconds"], oracle["human_seconds"])
        later, = evaluate("S24")
        self.assertEqual(later["verification"]["resolved_at"], "2026-03-25T10:00:00+00:00")

    def test_tracking_revision_and_unrelated_transshipment(self):
        delayed, = evaluate("S19")
        self.assertEqual(delayed["verification"]["escalation"]["trigger_at"], "2026-03-08T08:00:00+00:00")
        self.assertTrue(delayed["criteria"]["escalation_deadline"]["on_time"])
        wrong, = evaluate("S21")
        right, = evaluate("S22")
        self.assertEqual(wrong["outcome"]["state"], "failed")
        self.assertEqual(right["outcome"]["state"], "resolved")
        self.assertIn("tracking_events.json#E-T5", right["outcome"]["refs"])
        self.assertNotIn("tracking_events.json#E-T3", right["outcome"]["refs"])

    def test_repeat_contact_requires_evidence_about_the_same_request(self):
        repeat, correction = evaluate("S17")
        self.assertIs(repeat["verification"]["repeat_contact"]["same_unresolved_request"], True)
        self.assertEqual(repeat["outcome"]["state"], "failed")
        self.assertEqual(correction["outcome"]["state"], "resolved")
        original, revision = evaluate("S18")
        self.assertIs(original["verification"]["repeat_contact"]["same_unresolved_request"], False)
        self.assertEqual(revision["outcome"]["state"], "resolved")

    def test_export_only_and_missing_work_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exports = shutil.copytree(SCENARIOS / "S32" / "exports", root / "exports")
            payload = verify_exports(exports, POLICY)
            answers = root / "ground_truth"
            answers.mkdir()
            (answers / "expected.json").write_text("unreadable reference answers", encoding="utf-8")
            self.assertEqual(verify_exports(exports, POLICY), payload)
            with self.assertRaises(ValueError):
                verify_exports(root, POLICY)
            with self.assertRaises(ValueError):
                verify_exports(answers, POLICY)
            (exports / "agent_work.csv").unlink()
            result, = verify_exports(exports, POLICY)["enquiries"]
            self.assertEqual(result["outcome"]["state"], "resolved")
            self.assertIsNone(result["verification"]["human_work"]["active_seconds"])
            self.assertIs(result["verification"]["human_work"]["ai_only_handling"], False)

    def test_conflicting_sent_reply_cannot_be_used(self):
        with tempfile.TemporaryDirectory() as directory:
            exports = shutil.copytree(SCENARIOS / "S28" / "exports", Path(directory) / "exports")
            file = exports / "responses.csv"
            with file.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                row = next(reader)
                fields = reader.fieldnames
            with file.open("a", encoding="utf-8", newline="") as handle:
                csv.DictWriter(handle, fields).writerow({**row, "claimed_eta": "2026-03-16T16:00:00+00:00"})
            payload = verify_exports(exports, POLICY)
            result, = payload["enquiries"]
            self.assertEqual(result["outcome"]["state"], "unknown")
            self.assertIsNone(result["verification"]["initial_reply"])
            self.assertTrue(any(issue["code"] == "conflicting_record_id" for issue in payload["input_issues"]))

    def test_sent_eta_takes_precedence_and_ambiguous_service_text_stays_unknown(self):
        cases = (
            ("The current Rotterdam ETA is 16 March at 17:00 local time.", 21600, 30),
            ("The current Rotterdam ETA is 16 March at 05:00 local time.", -21600, 30),
            ("The current Rotterdam ETA is 17 March at 07:00 local time.", 72000, 100),
            ("The current Rotterdam ETA is 15 March at 11:00 local time.", -86400, 100),
            ("The current Rotterdam ETA is around lunchtime.", None, None),
            ("The current Rotterdam ETA is 16 March at 11:00 local time or 17:00 local time.", None, None),
        )
        with tempfile.TemporaryDirectory() as directory:
            exports = shutil.copytree(SCENARIOS / "S28" / "exports", Path(directory) / "exports")
            meta_path = exports / "export_metadata.json"
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            meta_path.write_text(json.dumps({
                **metadata, "dataset_origin": "company",
                "source_completeness": dict.fromkeys(TABLES, "complete"),
                "tracking_creation_visibility_ref": "Synthetic publication fixture",
            }), encoding="utf-8")
            response_path = exports / "responses.csv"
            with response_path.open(encoding="utf-8", newline="") as stream:
                row = next(csv.DictReader(stream))
            for message, seconds, penalty in cases:
                with self.subTest(message=message):
                    with response_path.open("w", encoding="utf-8", newline="") as stream:
                        writer = csv.DictWriter(stream, row.keys())
                        writer.writeheader()
                        writer.writerow({**row, "message_text": message})
                    reviewed = approve_exports(exports, Path(directory) / "approved", reviewer="Test reviewer",
                                               note="Reviewed the synthetic evidence fixture.")
                    result, = verify_exports(reviewed["exports_path"], POLICY)["enquiries"]
                    grade = result["criteria"]["eta_accuracy"]
                    reply = result["verification"]["initial_reply"]
                    self.assertEqual(grade.get("eta_error_seconds"), seconds)
                    if penalty is None:
                        self.assertEqual(grade["status"], "unknown")
                        self.assertIsNone(reply["matches_record"])
                    else:
                        self.assertAlmostEqual(grade["timing_failure_score"], penalty)
                        self.assertTrue(grade["structured_eta_disagrees"])
                        self.assertIs(reply["matches_record"], False)
                    self.assertNotEqual(result["outcome"]["state"], "resolved")

    def test_policy_changes_numeric_grade_without_changing_the_observed_error(self):
        policy = deepcopy(POLICY)
        policy["criteria"]["eta_accuracy"]["zero_score_late_seconds"] = 120
        policy["criteria"]["eta_accuracy"]["zero_score_early_seconds"] = 120
        result, = verify_exports(SCENARIOS / "S29" / "exports", policy)["enquiries"]
        self.assertEqual(result["criteria"]["eta_accuracy"]["score"], 50)
        self.assertEqual(result["criteria"]["eta_accuracy"]["eta_error_seconds"], 60)

    def test_rule_version_alone_does_not_allow_eta_from_an_internal_field(self):
        with tempfile.TemporaryDirectory() as directory:
            exports = shutil.copytree(SCENARIOS / "S28" / "exports", Path(directory) / "exports")
            meta_path = exports / "export_metadata.json"
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata.pop("dataset_origin"), "synthetic")
            metadata["source_completeness"] = dict.fromkeys(TABLES, "complete")
            metadata["tracking_creation_visibility_ref"] = "Synthetic publication fixture"
            response_path = exports / "responses.csv"
            with response_path.open(encoding="utf-8", newline="") as stream:
                response = next(csv.DictReader(stream))
            with response_path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, response.keys())
                writer.writeheader()
                writer.writerow({**response, "message_text": "Update on your shipment."})
            for label in ({}, {"dataset_origin": None}, {"dataset_origin": "company"},
                          {"dataset_origin": "unconfirmed"}, {"dataset_origin": "synthetic"}):
                with self.subTest(label=label):
                    meta_path.write_text(json.dumps({**metadata, **label}), encoding="utf-8")
                    reviewed = approve_exports(exports, Path(directory) / "approved", reviewer="Test reviewer",
                                               note="Reviewed the synthetic evidence fixture.")
                    result, = verify_exports(reviewed["exports_path"], POLICY)["enquiries"]
                    grade = result["criteria"]["eta_accuracy"]
                    benchmark = label.get("dataset_origin") == "synthetic"
                    self.assertEqual(result["outcome"]["state"], "resolved" if benchmark else "unknown")
                    self.assertEqual(grade["status"], "met" if benchmark else "unknown")
                    self.assertEqual(grade["eta_claim_basis"],
                                     "legacy_structured_claim" if benchmark else "no_eta_in_sent_message")

    def test_all_scenario_exports_produce_one_result_per_exported_enquiry(self):
        count = 0
        for exports in sorted(SCENARIOS.glob("*/exports")):
            with self.subTest(case=exports.parent.name):
                data = verify_exports(exports, POLICY)
                with (exports / "enquiries.csv").open(encoding="utf-8", newline="") as file:
                    expected_ids = list(dict.fromkeys(row["enquiry_id"] for row in csv.DictReader(file)))
                self.assertEqual([row["enquiry_id"] for row in data["enquiries"]], expected_ids)
                self.assertEqual(data["input_issues"], [])
                count += len(expected_ids)
        self.assertEqual(count, 61)

    def test_malformed_newer_tracking_is_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            exports = shutil.copytree(SCENARIOS / "S28" / "exports", Path(directory) / "exports")
            file = exports / "tracking_events.json"
            events = json.loads(file.read_text(encoding="utf-8"))
            latest = dict(next(row for row in events if row["event_id"] == "E-24C"))
            latest.update({
                "event_id": "E-LATE-REVISION",
                "event_created_datetime": "2026-03-09T09:02:00+00:00",
                "event_datetime": "2026-03-17T10:00:00+00:00",
            })
            del latest["event_type"]
            events.append(latest)
            file.write_text(json.dumps(events), encoding="utf-8")
            after_reply, = verify_exports(exports, POLICY)["enquiries"]
            self.assertEqual(after_reply["criteria"]["eta_accuracy"]["status"], "met")

            latest["event_created_datetime"] = "2026-03-09T09:00:05+00:00"
            file.write_text(json.dumps(events), encoding="utf-8")
            before_reply, = verify_exports(exports, POLICY)["enquiries"]
            self.assertEqual(before_reply["outcome"]["state"], "unknown")
            self.assertEqual(before_reply["criteria"]["eta_accuracy"]["status"], "unknown")

    def test_blank_account_cannot_authorize_a_shipment_match(self):
        with tempfile.TemporaryDirectory() as directory:
            exports = shutil.copytree(SCENARIOS / "S28" / "exports", Path(directory) / "exports")
            file = exports / "enquiries.csv"
            source = file.read_text(encoding="utf-8")
            file.write_text(source.replace("CUS-T1,", ",", 1), encoding="utf-8")
            result, = verify_exports(exports, POLICY)["enquiries"]
            self.assertEqual(result["outcome"]["state"], "unknown")
            self.assertEqual(result["criteria"]["shipment_identity"]["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
