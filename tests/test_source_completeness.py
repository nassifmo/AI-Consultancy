"""Regression checks for absence-of-evidence assumptions in pilot imports."""

import json
import csv
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

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


if __name__ == "__main__":
    unittest.main()
