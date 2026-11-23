import unittest

from evaluator.upgrade_value import assess_error_loss_scenario, assess_upgrade


BASE = "agent_v1"
UPGRADE = "agent_v2"


def _analysis(base, upgrade, base_cost=1.0, upgrade_cost=1.5):
    episodes = []
    metrics = {}
    for arm, rows, cost in ((BASE, base, base_cost), (UPGRADE, upgrade, upgrade_cost)):
        for state, correct, elapsed in rows:
            episodes.append({
                "assigned_arm": arm, "eligible": True, "outcome": {"state": state},
                "first_answer_correct": correct, "elapsed_resolution_seconds": elapsed,
            })
        metrics[arm] = {"cost_per_request": {
            "value": cost, "unit": "USD", "coverage": 1, "denominator": len(rows),
        }}
    return {
        "analysis_config": {"comparison_followup_days": 7}, "episodes": episodes, "group_metrics": metrics,
        "cost_ledger": {"currency": "USD"}, "data_readiness": {"comparison_status": "randomized_assignment"},
    }


PASS = ("resolved", True, 1200)
FAIL = ("failed", False, None)
UNKNOWN = ("unknown", None, None)


class UpgradeValueTests(unittest.TestCase):
    def test_infrequent_expensive_errors_can_reverse_modeled_value(self):
        analysis = _analysis([PASS, FAIL], [PASS, PASS])
        result = assess_upgrade(analysis, BASE, UPGRADE, "verified_resolution", value_per_success=2)
        scenario = assess_error_loss_scenario(result, 1000)
        self.assertEqual(scenario["cost_change_with_loss_per_request"], 1.50)
        self.assertEqual(scenario["net_value_with_loss_per_request"], -0.50)
        self.assertEqual(scenario["net_value_with_loss_bounds"], [-0.50, -0.50])
        self.assertEqual(result["net_value_per_request"], 0.50)
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            assess_error_loss_scenario(result, -1)

    def test_break_even_and_net_value_for_higher_cost(self):
        analysis = _analysis([PASS, FAIL], [PASS, PASS])
        result = assess_upgrade(analysis, BASE, UPGRADE, "verified_resolution", value_per_success=2)
        self.assertEqual(result["success_difference"], 0.5)
        self.assertEqual(result["break_even_value_per_success"], 1)
        self.assertEqual(result["break_even_value_bounds"], [1, 1])
        self.assertEqual(result["net_value_per_request"], 0.5)
        self.assertEqual(result["net_value_bounds"], [0.5, 0.5])
        self.assertEqual(result["point_dominance"], "tradeoff")
        self.assertEqual(result["status"], "modeled_benefit_exceeds_cost")

    def test_accuracy_unknowns_remain_in_eligible_denominator_and_bounds(self):
        analysis = _analysis([PASS, FAIL, UNKNOWN, UNKNOWN], [PASS, PASS, UNKNOWN, UNKNOWN])
        result = assess_upgrade(analysis, BASE, UPGRADE, "first_answer_accuracy", value_per_success=3)
        self.assertEqual(result["metrics"][BASE]["outcome_bounds"], [0.25, 0.75])
        self.assertEqual(result["success_difference"], 0.25)
        self.assertEqual(result["success_difference_bounds"], [-0.25, 0.75])
        self.assertEqual(result["break_even_value_bounds"], [0.5 / 0.75, None])
        self.assertEqual(result["net_value_bounds"], [-1.25, 1.75])
        self.assertEqual(result["status"], "inconclusive_missing_evidence")

    def test_target_includes_exact_deadline_and_keeps_missing_resolution_time_unknown(self):
        analysis = _analysis([("resolved", True, 3600), ("resolved", True, 3601), ("escalated_open", True, None)],
                             [("resolved", True, None), UNKNOWN, PASS])
        result = assess_upgrade(analysis, BASE, UPGRADE, "verified_resolution_within_target", target_hours=1)
        self.assertEqual(result["metrics"][BASE]["successes"], 1)
        self.assertEqual(result["metrics"][BASE]["failures"], 2)
        self.assertEqual(result["metrics"][UPGRADE]["unknown"], 2)
        self.assertEqual(result["status"], "value_unspecified")
        with self.assertRaisesRegex(ValueError, "within the comparison follow-up"):
            assess_upgrade(analysis, BASE, UPGRADE, "verified_resolution_within_target", target_hours=168.1)

    def test_lower_cost_lower_success_has_a_loss_threshold(self):
        analysis = _analysis([PASS, PASS], [PASS, FAIL], base_cost=1.5, upgrade_cost=1)
        result = assess_upgrade(analysis, BASE, UPGRADE, "verified_resolution", value_per_success=1)
        self.assertEqual(result["max_value_per_lost_success"], 1)
        self.assertIsNone(result["break_even_value_per_success"])
        self.assertEqual(result["status"], "modeled_break_even")

    def test_incomplete_costs_and_currency_mismatch_preclude_valuation(self):
        analysis = _analysis([FAIL], [PASS])
        for missing in ({"coverage": 0.8}, {"unit": "EUR"}, {"value": None}):
            with self.subTest(missing=missing):
                metric = analysis["group_metrics"][UPGRADE]["cost_per_request"]
                analysis["group_metrics"][UPGRADE]["cost_per_request"] = {**metric, **missing}
                result = assess_upgrade(analysis, BASE, UPGRADE, "verified_resolution", value_per_success=1)
                self.assertIsNone(result["incremental_cost_per_request"])
                self.assertIsNone(result["net_value_per_request"])
                self.assertEqual(result["status"], "cost_unavailable")
                analysis["group_metrics"][UPGRADE]["cost_per_request"] = metric

    def test_cheaper_and_better_on_verified_point_dominates_without_assumed_value(self):
        result = assess_upgrade(_analysis([FAIL], [PASS], base_cost=2, upgrade_cost=1),
                                BASE, UPGRADE, "verified_resolution")
        self.assertEqual(result["point_dominance"], "treatment")
        self.assertIsNone(result["net_value_per_request"])
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            assess_upgrade(_analysis([FAIL], [PASS]), BASE, UPGRADE, "verified_resolution", value_per_success=-1)
