"""Regression checks for absence-of-evidence assumptions in pilot imports."""

import json
import csv
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

from evaluator.exports import TABLES, load_exports
from evaluator.verification import verify_exports


ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "evaluator" / "policy.json").read_text(encoding="utf-8"))


class CompletenessTests(unittest.TestCase):
    def test_explicit_run_link_supports_asynchronous_delivery(self):
        with TemporaryDirectory() as directory:
            exports = shutil.copytree(ROOT / "datagen" / "datasets" / "scenarios" / "S33" / "exports",
                                      Path(directory) / "exports")
            runs_path = exports / "agent_runs.json"
            runs = json.loads(runs_path.read_text(encoding="utf-8"))
            run = runs[0]
            run["ended_at"] = run["ended_at"].replace(":00+", ":01+")
            runs_path.write_text(json.dumps(runs), encoding="utf-8")
            replies_path = exports / "responses.csv"
            with replies_path.open(newline="", encoding="utf-8") as file:
                replies = list(csv.DictReader(file))
            replies[0]["run_id"] = run["run_id"]
            with replies_path.open("w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(file, [*replies[0]])
                writer.writeheader()
                writer.writerows(replies)
            result = verify_exports(exports, POLICY)["enquiries"][0]
            self.assertTrue(result["initial_failure"])
            self.assertIn("agent_runs.json#" + run["run_id"], result["verification"]["initial_reply"]["refs"])
            replies[0]["run_id"] = "MISSING-RUN"
            with replies_path.open("w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(file, [*replies[0]])
                writer.writeheader()
                writer.writerows(replies)
            result = verify_exports(exports, POLICY)["enquiries"][0]
            self.assertNotIn("agent_runs.json#" + run["run_id"], result["verification"]["initial_reply"]["refs"])

    def _evaluate(self, name, completeness):
        with TemporaryDirectory() as directory:
            exports = shutil.copytree(ROOT / "datagen" / "datasets" / "scenarios" / name / "exports",
                                      Path(directory) / "exports")
            path = exports / "export_metadata.json"
            metadata = json.loads(path.read_text(encoding="utf-8"))
            metadata["source_completeness"] = completeness
            path.write_text(json.dumps(metadata), encoding="utf-8")
            return verify_exports(exports, POLICY)["enquiries"][0]

    def test_partial_work_retains_subtotal_and_does_not_imply_total_effort(self):
        result = self._evaluate("S32", {"responses": "complete", "tracking_events": "complete",
                                       "agent_work": "partial"})
        self.assertEqual(result["outcome"]["state"], "resolved")
        work = result["verification"]["human_work"]
        self.assertIsNone(work["active_seconds"])
        self.assertEqual(work["recorded_seconds"], 300)

    def test_partial_tracking_cannot_establish_a_complete_as_of_answer(self):
        result = self._evaluate("S28", {"responses": "complete", "tracking_events": "partial"})
        self.assertIsNone(result["verification"]["initial_reply"]["matches_record"])
        self.assertEqual(result["outcome"]["state"], "unknown")

    def test_missing_response_coverage_cannot_establish_the_first_or_final_answer(self):
        result = self._evaluate("S32", {"responses": "unknown", "tracking_events": "complete"})
        self.assertIsNone(result["verification"]["initial_reply"])
        self.assertEqual(result["outcome"]["state"], "unknown")

    def test_canonical_company_file_presence_does_not_confirm_absence_of_handoff(self):
        with TemporaryDirectory() as directory:
            exports = shutil.copytree(ROOT / "datagen" / "datasets" / "scenarios" / "S28" / "exports",
                                      Path(directory) / "exports")
            path = exports / "export_metadata.json"
            metadata = json.loads(path.read_text(encoding="utf-8"))
            metadata.pop("dataset_origin", None)
            replies = exports / "responses.csv"
            with replies.open(encoding="utf-8", newline="") as stream:
                row, = list(csv.DictReader(stream))
            row["message_text"] = "The vessel has departed."
            with replies.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, row.keys())
                writer.writeheader()
                writer.writerow(row)
            inputs = (
                ({"dataset_origin": "company"}, "unknown", "unknown"),
                ({}, "unknown", "unknown"),
                ({"source_completeness": None}, "unknown", "unknown"),
                ({"source_completeness": {"responses": "complete", "tracking_events": "complete"}},
                 "unknown", "unmet"),
                ({"source_completeness": dict.fromkeys(TABLES, "complete")}, "failed", "unmet"),
            )
            for declarations, outcome, reply_grade in inputs:
                with self.subTest(declarations=declarations):
                    path.write_text(json.dumps({**metadata, **declarations}), encoding="utf-8")
                    result, = verify_exports(exports, POLICY)["enquiries"]
                    self.assertEqual(result["outcome"]["state"], outcome)
                    self.assertEqual(result["criteria"]["eta_request_answered"]["status"], reply_grade)

    def test_overflowing_canonical_json_is_reported_as_an_invalid_file(self):
        with TemporaryDirectory() as directory:
            exports = Path(directory) / "exports"
            exports.mkdir()
            (exports / "cost_parameters.json").write_text('{"labor_rate_per_hour":1e400}', encoding="utf-8")
            data = load_exports(exports, analysis=True)
            self.assertIsNone(data.cost_parameters)
            self.assertEqual(data.files["cost_parameters.json"]["status"], "invalid")
            self.assertTrue(any(issue["table"] == "cost_parameters" and issue["code"] == "invalid_file"
                                for issue in data.issues))


if __name__ == "__main__":
    unittest.main()
