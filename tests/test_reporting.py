"""Checks for reproducible, safely reusable analysis artifacts."""

from copy import deepcopy
import csv
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from evaluator.reporting import make_downloads, write_run_bundle


ANALYSIS = {
    "schema_version": "1.0",
    "run_provenance": {"evaluator_sha256": "example", "policy_version": "0.5.0-proposed"},
    "analysis_config": {"comparison_followup_days": 7},
    "data_readiness": {"dataset_origin": "synthetic", "eligible_roots": 5},
    "group_metrics": {"agent_v2": {"n": 5, "verified_resolution_rate": {
        "value": 0.8, "unit": "fraction", "numerator": 4, "denominator": 5,
        "coverage": 0.8, "episode_ids": ["E1", "E2", "E3", "E4", "E5"],
    }}},
    "cost_ledger": {"currency": "USD", "entries": [{
        "amount": 2.5, "currency": "USD", "category": "human_resource", "source_refs": ["agent_work.csv#W1"],
    }], "realized_cash_savings": None},
    "comparisons": [{
        "comparator": "agent_v1", "treatment": "agent_v2", "status": "descriptive",
        "metrics": {"verified_resolution_rate": {
            "unit": "pp", "estimate": 20.0, "interval": None, "identification_bounds": [-5.0, 25.0],
            "interpretation_limit": "Unknown outcomes could reverse the observed difference.",
        }},
    }],
    "limitations": ["<script>example</script>"],
}


class ReportTests(unittest.TestCase):
    def test_downloads_preserve_numbers_and_escape_display_input(self):
        files = make_downloads(ANALYSIS)
        self.assertEqual(json.loads(files["analysis.json"]), ANALYSIS)
        group, = csv.DictReader(StringIO(files["group_metrics.csv"].decode("utf-8-sig")))
        self.assertEqual((group["value"], group["denominator"]), ("0.8", "5"))
        cost, = csv.DictReader(StringIO(files["cost_ledger.csv"].decode("utf-8-sig")))
        self.assertEqual(cost["amount"], "2.5")
        summary = files["summary.html"].decode("utf-8")
        self.assertIn("Synthetic demonstration", summary)
        self.assertIn("80.0%", summary)
        self.assertIn("+20.00 pp", summary)
        self.assertIn("-5.00 pp to +25.00 pp", summary)
        self.assertIn("Descriptive", summary)
        self.assertIn("Unknown outcomes could reverse the observed difference.", summary)
        self.assertNotIn("<script>", summary)

    def test_run_bundle_is_reusable_and_detects_changes_to_saved_files(self):
        with TemporaryDirectory() as root:
            first = write_run_bundle(root, ANALYSIS, {"version": "test"})
            self.assertEqual(first, write_run_bundle(root, ANALYSIS, {"version": "test"}))
            manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
            for filename, digest in manifest["artifacts"].items():
                self.assertEqual(sha256((first / filename).read_bytes()).hexdigest(), digest)
            modified = deepcopy(ANALYSIS)
            modified["analysis_config"]["comparison_followup_days"] = 8
            second = write_run_bundle(root, modified, {"version": "test"})
            self.assertNotEqual(first, second)
            self.assertEqual({first, second}, set(Path(root).iterdir()))
            (first / "summary.html").write_text("changed", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                write_run_bundle(root, ANALYSIS, {"version": "test"})

    def test_unavailable_values_remain_null_and_nonfinite_values_are_rejected(self):
        modified = deepcopy(ANALYSIS)
        modified["group_metrics"]["agent_v2"]["verified_resolution_rate"]["value"] = float("nan")
        with self.assertRaises(ValueError):
            make_downloads(modified)


if __name__ == "__main__":
    unittest.main()
