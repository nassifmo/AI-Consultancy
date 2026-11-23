"""Check the analysis against independently specified outcomes and arithmetic."""

import csv
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy.stats import binom

from evaluator.analysis import DEFAULT_CONFIG, analyze_exports, validate_config
from evaluator.comparisons import cluster_weights, compare, interval_from_samples
from evaluator.exports import EXPORT_FILENAMES
from evaluator.grading import grade_enquiry
from evaluator.metrics import summarize


PROJECT = Path(__file__).resolve().parents[1]
POLICY = json.loads((PROJECT / "evaluator" / "policy.json").read_text(encoding="utf-8"))
SCENARIOS = PROJECT / "datagen" / "datasets" / "scenarios"


def read_csv(path):
    return list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"), newline="")))


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def install_assignment(folder, scenario, arm="agent_v1"):
    exports = shutil.copytree(SCENARIOS / scenario / "exports", Path(folder) / "exports")
    path = exports / "enquiries.csv"
    records = read_csv(path)
    for record in records:
        key = record["enquiry_id"]
        record.update(assigned_arm=arm, assignment_at=record["received_at"],
                      root_enquiry_id=key, related_enquiry_id="", contact_relation="initial",
                      assignment_unit_id=key, assignment_method="randomized")
    write_csv(path, records)
    write_csv(exports / "rollout_log.csv", [
        {"date": "2026-03-01", "agent_version": arm, "arm_assignment_rule": "random_by_enquiry"},
    ])
    return exports, records[0]


def outcome_row(key, arm, state, seconds, cost):
    return {
        "root_enquiry_id": key, "assigned_arm": arm, "customer_id": key, "eligible": True,
        "outcome": {"state": state}, "total_cost": cost, "active_seconds": seconds,
        "recorded_seconds": seconds, "criteria": {}, "ai_only_handling": None,
        "elapsed_resolution_seconds": 10 if state == "resolved" else None,
    }


class AnalysisTests(unittest.TestCase):
    def test_required_actions_missed_evidence_and_unknown_applicability_are_separate(self):
        rows = []
        for index, required in enumerate((True, None)):
            grade = grade_enquiry(POLICY, {"enquiry_id": str(index), "profile": "shipment_delay", "conditions":
                                          {"escalation_required": required, "follow_up_required": False}})
            row = outcome_row(str(index), "agent_v1", "unknown", None, None)
            row["criteria"] = grade["criteria"]
            rows.append(row)
        metrics, _ = summarize(rows, "USD")
        result = metrics["agent_v1"]["required_action_compliance"]
        self.assertEqual(result["population"], 3)
        self.assertEqual(result["denominator"], 0)
        self.assertEqual(result["unknown_applicability"], 3)
        self.assertIsNone(result["value"])

    def test_reconstruct_at_checkpoint_and_exclude_immature_root(self):
        with tempfile.TemporaryDirectory() as directory:
            exports, _ = install_assignment(directory, "S24")
            result = analyze_exports(exports, POLICY)
            self.assertEqual(result["enquiries"][0]["outcome"]["state"], "resolved")
            root = result["episodes"][0]
            self.assertTrue(root["eligible"])
            self.assertEqual(root["checkpoint"], "2026-03-16T09:00:00+00:00")
            self.assertEqual(root["outcome"]["state"], "escalated_open")
            self.assertEqual(root["active_seconds"], 240)
            self.assertIsNone(root["resolved_at"])
            immature = analyze_exports(exports, POLICY, {"comparison_followup_days": 40})
            self.assertEqual(immature["data_readiness"]["eligible_roots"], 0)
            self.assertEqual(immature["data_readiness"]["exclusion_counts"]["incomplete_followup"], 1)

    def test_continuation_work_and_resolution_keep_the_original_assignment(self):
        with tempfile.TemporaryDirectory() as directory:
            exports, root = install_assignment(directory, "S32")
            followup = dict(root, enquiry_id="CONTINUATION", related_enquiry_id=root["enquiry_id"],
                            received_at="2026-03-15T13:02:00+00:00", contact_relation="continuation",
                            customer_message="I am still waiting for the discharge status of SYNU9000020.")
            write_csv(exports / "enquiries.csv", [root, followup])
            replies = read_csv(exports / "responses.csv")
            replies[1].update(enquiry_id="CONTINUATION", purpose="answer")
            write_csv(exports / "responses.csv", list(reversed(replies)))
            work = read_csv(exports / "agent_work.csv")
            work[0].update(enquiry_id="CONTINUATION")
            write_csv(exports / "agent_work.csv", work)
            result = analyze_exports(exports, POLICY)
            episode, = result["episodes"]
            self.assertEqual(episode["contacts"], ["ENQ-S32", "CONTINUATION"])
            self.assertEqual(episode["outcome"]["state"], "resolved")
            self.assertIs(episode["initial_failure"], True)
            self.assertIs(episode["human_recovery"], True)
            self.assertIs(episode["repeat_contact"], True)
            self.assertEqual(episode["active_seconds"], 300)
            self.assertEqual(result["group_metrics"]["agent_v1"]["n"], 1)
            self.assertEqual(result["group_metrics"]["agent_v1"]["human_minutes_per_request"]["value"], 5)

    def test_estimated_and_elapsed_time_do_not_establish_human_effort_or_cost(self):
        for method, active in (("estimated", "300"), ("ticket_elapsed", "360"), ("logged", "")):
            with self.subTest(method=method, active=active), tempfile.TemporaryDirectory() as directory:
                exports, _ = install_assignment(directory, "S32")
                work = read_csv(exports / "agent_work.csv")
                work[0].update(measurement_method=method, active_seconds=active)
                write_csv(exports / "agent_work.csv", work)
                (exports / "cost_parameters.json").write_text(json.dumps({
                    "currency": "USD", "valid_from": "2026-03-01", "labor_rate_per_hour": 60,
                }), encoding="utf-8")
                result = analyze_exports(exports, POLICY)
                enquiry, = result["enquiries"]
                self.assertTrue(enquiry["initial_failure"])
                self.assertTrue(enquiry["verification"]["human_recovery"])
                self.assertEqual(enquiry["outcome"]["state"], "resolved")
                self.assertIsNone(result["group_metrics"]["agent_v1"]["human_minutes_per_request"]["value"])
                self.assertIsNone(result["cost_ledger"]["per_episode"]["ENQ-S32"]["total_cost"])
                self.assertFalse(any(line["category"] == "human_work" for line in result["cost_ledger"]["entries"]))
                kind = "active_work_unverified" if method == "logged" else "work_method_unverified"
                self.assertTrue(any(issue["kind"] == kind and issue["record_id"] == "WRK-S32-1"
                                    for issue in result["input_quality"]["issues"]))

    def test_unknown_assignment_stays_out_of_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            exports, record = install_assignment(directory, "S32")
            write_csv(exports / "enquiries.csv", [dict(record, assigned_arm="")])
            result = analyze_exports(exports, POLICY)
            self.assertEqual(result["enquiries"][0]["outcome"]["state"], "resolved")
            self.assertEqual(result["data_readiness"]["eligible_roots"], 0)
            self.assertEqual(result["data_readiness"]["comparison_status"], "incomplete_assignment")
            self.assertIn("missing_or_invalid_assignment", result["episodes"][0]["exclusion_reasons"])

    def test_study_end_is_excluded_and_observational_design_is_flagged(self):
        with tempfile.TemporaryDirectory() as directory:
            exports, record = install_assignment(directory, "S32")
            second = dict(record, enquiry_id="AFTER-STUDY", root_enquiry_id="AFTER-STUDY",
                          assignment_unit_id="AFTER-STUDY", assignment_at="2026-03-15T13:00:01+00:00",
                          received_at="2026-03-15T13:00:01+00:00")
            write_csv(exports / "enquiries.csv", [second, record])
            write_csv(exports / "rollout_log.csv", [
                {"date": "2026-03-01", "agent_version": "agent_v1", "arm_assignment_rule": "all_traffic"},
            ])
            result = analyze_exports(exports, POLICY)
            self.assertIn("outside_study_period", result["episodes"][0]["exclusion_reasons"])
            self.assertEqual(result["data_readiness"]["eligible_roots"], 1)
            self.assertEqual(result["data_readiness"]["comparison_status"], "unsupported_design")
            self.assertEqual(result["data_readiness"]["monthly_trends"][0]["resolved"], 1)

    def test_runtime_reads_only_allowed_export_names(self):
        with tempfile.TemporaryDirectory() as directory:
            exports, _ = install_assignment(directory, "S32")
            (exports / "manifest.json").write_text("private benchmark hints", encoding="utf-8")
            (exports.parent / "ground_truth").mkdir()
            (exports.parent / "ground_truth" / "expected.json").write_text("private answers", encoding="utf-8")
            read_bytes = Path.read_bytes
            opened = []

            def audited(path):
                if path.is_relative_to(exports.parent):
                    self.assertEqual(path.parent, exports.resolve())
                    self.assertIn(path.name, EXPORT_FILENAMES)
                    opened.append(path.name)
                return read_bytes(path)

            with patch.object(Path, "read_bytes", audited):
                first = analyze_exports(exports, POLICY)
                second = analyze_exports(exports, POLICY)
            self.assertIn("enquiries.csv", opened)
            self.assertEqual(first, second)
            json.dumps(first, allow_nan=False)

    def test_known_group_arithmetic_preserves_tradeoff_and_bounds(self):
        episodes = [
            outcome_row("H1", "human_baseline", "resolved", 480, 4),
            outcome_row("H2", "human_baseline", "unknown", 720, 6),
            outcome_row("A1", "agent_v1", "resolved", 300, 7),
            outcome_row("A2", "agent_v1", "resolved", 180, 9),
            outcome_row("B1", "agent_v2", "failed", 780, 9),
            outcome_row("B2", "agent_v2", "closed_unresolved", 660, 11),
        ]
        groups, rows = summarize(episodes, "USD")
        h, v1, v2 = (groups[arm] for arm in ("human_baseline", "agent_v1", "agent_v2"))
        self.assertEqual(h["verified_resolution_rate"]["bounds"], [0.5, 1.0])
        self.assertEqual(h["verified_resolution_rate"]["coverage"], 0.5)
        self.assertEqual(h["cost_per_verified_resolution"]["value"], 10)
        self.assertEqual(v1["cost_per_verified_resolution"]["value"], 8)
        self.assertIsNone(v2["cost_per_verified_resolution"]["value"])
        v1_effect, v2_effect, _ = compare(groups, rows, "randomized_assignment", DEFAULT_CONFIG,
                                           {"currency": "USD", "labor_rate_per_hour": 20})
        self.assertEqual(v1_effect["metrics"]["verified_resolution_rate"]["estimate"], 50)
        self.assertEqual(v1_effect["metrics"]["cost_per_request"]["estimate"], 3)
        self.assertEqual(v1_effect["metrics"]["human_minutes_per_request"]["estimate"], -6)
        self.assertEqual(v1_effect["capacity_hours_per_1000"], 100)
        self.assertEqual(v2_effect["metrics"]["verified_resolution_rate"]["estimate"], -50)
        self.assertEqual(v2_effect["metrics"]["cost_per_request"]["estimate"], 5)
        self.assertFalse(v1_effect["metrics"]["verified_resolution_rate"]["causal_interpretation"])

    def test_bootstrap_known_null_calibration(self):
        n = 500
        trials = 200
        p_success = 0.55
        weights = cluster_weights(2 * n, 2000, DEFAULT_CONFIG["bootstrap_seed"]).astype(np.float32)
        outcomes = np.stack([
            np.random.default_rng(seed).binomial(1, p_success, 2 * n) for seed in range(trials)
        ], axis=1).astype(np.float32)
        left_weights = np.ascontiguousarray(weights[:, :n])
        right_weights = np.ascontiguousarray(weights[:, n:])
        left, right = left_weights @ outcomes[:n], right_weights @ outcomes[n:]
        left_denom, right_denom = left_weights.sum(axis=1), right_weights.sum(axis=1)
        misses = []
        for seed in range(trials):
            sample = np.column_stack([left[:, seed], left_denom, right[:, seed], right_denom])
            interval, valid, reason = interval_from_samples(sample, 0.95)
            self.assertIsNone(reason)
            self.assertEqual(valid, 2000)
            if interval[1] < 0 or interval[0] > 0:
                misses.append(seed)
        low, high = (int(binom.ppf(q, trials, 0.05)) for q in (0.025, 0.975))
        print(f"\nNull calibration: {len(misses)}/{trials} excluded zero. "
              f"Acceptance interval {low}–{high}. Seeds {misses}", flush=True)
        self.assertLessEqual(low, len(misses), misses)
        self.assertLessEqual(len(misses), high, misses)

    def test_invalid_configuration_reports_actionable_error(self):
        for config in ([], {"comparison_followup_days": False}, {"confidence_level": float("nan")},
                       {"unrecognized": 1}, {"comparison_pairs": [["agent_v1", "agent_v1"]]}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                validate_config(config)
