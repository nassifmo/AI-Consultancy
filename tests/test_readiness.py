"""Check evidence readiness against missing, damaged and partial source records."""

import csv
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from evaluator.exports import TABLES, load_exports
from evaluator.readiness import assess_readiness


ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "evaluator" / "policy.json").read_text(encoding="utf-8"))
SCENARIO = ROOT / "datagen" / "datasets" / "scenarios" / "S32" / "exports"


def write_rows(path, rows):
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def csv_rows(path):
    return list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))


def capabilities(report):
    return {row["id"]: row for row in report["capabilities"]}


class ReadinessTests(unittest.TestCase):
    def test_fixture_has_verifiable_answer_but_logging_completeness_needs_confirmation(self):
        report = assess_readiness(load_exports(SCENARIO, analysis=True), POLICY)
        factual = capabilities(report)["first_answer_verification"]
        self.assertEqual((factual["assessable"], factual["total"]), (1, 1))
        self.assertEqual(factual["status"], "partial")
        self.assertIn("responses.csv", factual["sources_needing_completeness_confirmation"])
        self.assertEqual(report["work_measurement"]["measurement_methods"], {"logged": 1})
        self.assertEqual(capabilities(report)["scoped_costs"]["status"], "unavailable")
        json.dumps(report, allow_nan=False)

    def test_completeness_declaration_and_real_check_allow_ready_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            exports = shutil.copytree(SCENARIO, Path(temporary) / "exports")
            metadata = json.loads((exports / "export_metadata.json").read_text(encoding="utf-8"))
            metadata["source_completeness"] = dict.fromkeys(TABLES, "complete")
            (exports / "export_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
            report = assess_readiness(load_exports(exports, analysis=True), POLICY)
            self.assertEqual(capabilities(report)["first_answer_verification"]["status"], "ready")
            self.assertEqual(capabilities(report)["active_human_work"]["status"], "ready")
            self.assertEqual(capabilities(report)["comparison_assignment"]["status"], "unavailable")

    def test_orphan_links_and_naive_timestamp_are_explicit_quality_gaps(self):
        with tempfile.TemporaryDirectory() as temporary:
            exports = shutil.copytree(SCENARIO, Path(temporary) / "exports")
            replies = csv_rows(exports / "responses.csv")
            replies[0]["enquiry_id"] = "UNKNOWN-ENQUIRY"
            replies[1]["sent_at"] = "2026-03-15T13:08:00"
            metadata = json.loads((exports / "export_metadata.json").read_text(encoding="utf-8"))
            metadata.get("timezones", {}).pop("responses", None)
            (exports / "export_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
            write_rows(exports / "responses.csv", replies)
            report = assess_readiness(load_exports(exports, analysis=True), POLICY)
            link = next(row for row in report["joins"] if row["source"] == "responses.csv.enquiry_id")
            self.assertEqual((link["matched"], link["orphaned"]), (1, 1))
            self.assertTrue(any(row["code"] == "uninterpretable_timestamp" and row["source"] == "responses.csv.sent_at"
                                for row in report["issues"]))
            self.assertEqual(capabilities(report)["first_answer_timing"]["status"], "unavailable")

    def test_elapsed_interval_without_active_duration_never_establishes_effort(self):
        with tempfile.TemporaryDirectory() as temporary:
            exports = shutil.copytree(SCENARIO, Path(temporary) / "exports")
            work = csv_rows(exports / "agent_work.csv")
            work[0]["active_seconds"] = ""
            write_rows(exports / "agent_work.csv", work)
            report = assess_readiness(load_exports(exports, analysis=True), POLICY)
            self.assertEqual(report["work_measurement"]["invalid_durations"], 1)
            self.assertEqual(capabilities(report)["active_human_work"]["status"], "unavailable")
            self.assertEqual(capabilities(report)["first_answer_verification"]["assessable"], 1)

    def test_impossible_action_order_is_reported_with_source_time_coverage(self):
        with tempfile.TemporaryDirectory() as temporary:
            exports = shutil.copytree(SCENARIO, Path(temporary) / "exports")
            replies = csv_rows(exports / "responses.csv")
            replies[0]["sent_at"] = "2026-03-15T12:59:00+00:00"
            write_rows(exports / "responses.csv", replies)
            runs = json.loads((exports / "agent_runs.json").read_text(encoding="utf-8"))
            runs[0]["ended_at"] = "2026-03-15T12:58:00+00:00"
            (exports / "agent_runs.json").write_text(json.dumps(runs), encoding="utf-8")
            report = assess_readiness(load_exports(exports, analysis=True), POLICY)
            codes = {row["code"] for row in report["issues"]}
            self.assertIn("event_before_enquiry", codes)
            self.assertIn("reversed_run_interval", codes)
            table = next(row for row in report["tables"] if row["table"] == "responses")
            field = next(row for row in table["fields"] if row["field"] == "sent_at")
            self.assertEqual(field["earliest"], "2026-03-15T12:59:00+00:00")
            self.assertEqual(field["valid_timestamps"], 2)

    def test_reuses_supplied_results_and_cost_scope_with_missing_fields_preserved(self):
        data = load_exports(SCENARIO, analysis=True)
        verified = [{"enquiry_id": "E1", "in_scope": True, "outcome": {"state": "unknown"},
                     "verification": {"human_work": {"active_seconds": None}}}]
        report = assess_readiness(
            data, POLICY, verified=verified,
            episodes=[{"root_enquiry_id": "E1", "eligible": True}, {"root_enquiry_id": "E2", "eligible": True}],
            ledger={"per_episode": {"E1": {"complete": True}, "E2": {"complete": False}}},
            diagnostics={"comparison_status": "incomplete_assignment"},
        )
        costs = capabilities(report)["scoped_costs"]
        self.assertEqual((costs["assessable"], costs["total"], costs["coverage"]), (1, 2, 0.5))
        self.assertEqual(costs["status"], "partial")
        self.assertEqual(capabilities(report)["service_outcomes"]["assessable"], 0)
        enquiry = next(row for row in report["tables"] if row["table"] == "enquiries")
        assignment = next(field for field in enquiry["fields"] if field["field"] == "assigned_arm")
        self.assertEqual(assignment["present"], 0)


if __name__ == "__main__":
    unittest.main()
