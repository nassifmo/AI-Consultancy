"""Verify conservative policy recommendations against independently specified inputs."""

from copy import deepcopy
import json
import unittest

from evaluator.analysis import DEFAULT_CONFIG
from evaluator.comparisons import design_diagnostics
from evaluator.exports import ExportData
from evaluator.recommendation import assess_recommendation, case_review_actions
from evaluator.reporting import render_decision_brief


BASE, CANDIDATE = "agent_v1", "agent_v2"


def trial():
    episodes = []
    group_metrics = {}
    for arm in (BASE, CANDIDATE):
        rows = []
        for index in range(72):
            proposed = arm == CANDIDATE
            resolved = index % 5 != 0 if proposed else index % 4 == 0
            cost = 3 + (index % 7) * 0.08 if proposed else 2 + (index % 3) * 0.1
            rows.append({"root_enquiry_id": f"{arm}-{index}", "customer_id": f"account-{index}",
                         "assigned_arm": arm, "eligible": True, "total_cost": cost,
                         "initial_failure": proposed and index == 1,
                         "outcome": {"state": "resolved" if resolved else "failed"}})
        episodes.extend(rows)
        group_metrics[arm] = {"cost_per_request": {
            "value": sum(row["total_cost"] for row in rows) / len(rows),
            "unit": "USD", "coverage": 1, "denominator": len(rows),
        }}
    return {
        "analysis_config": {**DEFAULT_CONFIG, "bootstrap_resamples": 500},
        "run_provenance": {"run_id": "trial-1"}, "episodes": episodes, "group_metrics": group_metrics,
        "data_readiness": {"dataset_origin": "synthetic", "comparison_status": "randomized_assignment"},
        "cost_ledger": {"currency": "USD"},
    }


def recommend(analysis, **changes):
    settings = {"max_critical_rate": 0.1, "value_per_success": 12.0, "value_basis": "company_estimate",
                "value_evidence": "Fixture-specific approved finance estimate"}
    return assess_recommendation(analysis, BASE, CANDIDATE, "verified_resolution", **{**settings, **changes})


class RecommendationTests(unittest.TestCase):
    def test_joint_value_uncertainty_is_reproducible_and_drives_action(self):
        data = trial()
        positive = recommend(data)
        self.assertEqual(positive["action"], "consider_controlled_expansion")
        self.assertGreater(positive["net_uncertainty"]["bounds"][0], 0)
        self.assertLessEqual(positive["net_uncertainty"]["critical_upper"], 0.1)
        self.assertEqual(positive, recommend(deepcopy(data)))
        self.assertEqual(positive["source_run_id"], "trial-1")
        self.assertIn(b"Synthetic demonstration", render_decision_brief(positive))
        json.dumps(positive, allow_nan=False)
        negative = recommend(data, value_per_success=0.25)
        self.assertEqual(negative["action"], "keep_comparator")
        self.assertLess(negative["net_uncertainty"]["bounds"][1], 0)

    def test_critical_findings_take_priority_and_unknowns_block_a_pass(self):
        data = trial()
        decision = recommend(data, max_critical_rate=0.01)
        self.assertEqual(decision["action"], "redesign_and_retest")
        self.assertEqual(decision["critical_check"]["failure_episode_ids"], [f"{CANDIDATE}-1"])
        data["episodes"][-1]["initial_failure"] = None
        decision = recommend(data, max_critical_rate=0.02)
        self.assertEqual(decision["action"], "verify_critical_cases")
        self.assertEqual(decision["critical_check"]["bounds"], [1 / 72, 2 / 72])

    def test_failed_checks_generate_sorted_case_evidence_and_retests(self):
        data = trial()
        first, second, third = data["episodes"][73:76]
        mismatch = {"status": "unmet", "severity": "critical", "refs": ["responses.csv#reply-1"]}
        first["criteria"] = {"shipment_identity": mismatch, "initial_escalation": {
            "status": "unmet", "severity": "critical", "refs": ["case_history.csv#event-1"],
        }}
        second.update(initial_failure=True, criteria={"shipment_identity": {**mismatch, "refs": ["tracking_events.json#event-2"]}})
        third.update(initial_failure=True, criteria={"shipment_identity": {**mismatch, "refs": []}})
        result = recommend(data, max_critical_rate=.01)
        self.assertEqual(result["action"], "redesign_and_retest")
        self.assertIn("3 of 72", result["reason"])
        identity, escalation = result["failure_reviews"]
        self.assertEqual(identity["criterion"], "shipment_identity")
        self.assertEqual(identity["cases"], [
            {"enquiry_id": f"{CANDIDATE}-1", "refs": ["responses.csv#reply-1"]},
            {"enquiry_id": f"{CANDIDATE}-2", "refs": ["tracking_events.json#event-2"]},
        ])
        self.assertEqual(escalation["cases"][0]["enquiry_id"], f"{CANDIDATE}-1")
        self.assertEqual(result["unclassified_failure_episode_ids"], [f"{CANDIDATE}-3"])
        self.assertIn("ambiguous reference", identity["retest"])
        self.assertIn("fresh trial", result["reconsider_when"])
        self.assertIn(b"Shipment or container mismatch (2 enquiries)", render_decision_brief(result))

    def test_hypothetical_downstream_loss_can_hold_expansion_for_finance_review(self):
        data = trial()
        initial = recommend(data)
        self.assertEqual(initial["action"], "consider_controlled_expansion")
        stressed = recommend(data, additional_loss_per_1000=9000)
        self.assertEqual(stressed["action"], "validate_downstream_loss")
        self.assertEqual(stressed["net_uncertainty"], initial["net_uncertainty"])
        self.assertEqual(stressed["downstream_loss_scenario"]["sampling_net_value_bounds"],
                         [value - 9 for value in initial["net_uncertainty"]["bounds"]])
        self.assertIn(b"Assumed additional loss", render_decision_brief(stressed))
        self.assertEqual(recommend(data, additional_loss_per_1000=100)["action"], "consider_controlled_expansion")
        self.assertEqual(recommend(data, additional_loss_per_1000=9000, max_critical_rate=.01)["action"],
                         "redesign_and_retest")

    def test_disputed_population_prevents_expansion_even_with_positive_modelled_value(self):
        data = trial()
        self.assertEqual(recommend(data)["action"], "consider_controlled_expansion")
        review = {"required": True, "population_issues": 1, "unresolved_critical_issues": 0,
                  "affected_enquiry_ids": ["ENQ-DISPUTED"],
                  "reasons": ["Conflicting enquiry records may affect eligibility."]}
        data["input_quality"] = {"review_required": review}
        result = recommend(data)
        self.assertEqual(result["action"], "review_source_conflicts")
        self.assertEqual(result["input_quality_review"], review)
        self.assertGreater(result["net_uncertainty"]["bounds"][0], 0)
        self.assertEqual(result["critical_check"]["eligible"], 72)
        self.assertEqual(result["critical_check"]["verified_failures"], 1)

    def test_source_review_precedes_unsupported_design_and_preserves_known_critical_exceedance(self):
        data = trial()
        data["data_readiness"]["comparison_status"] = "incomplete_assignment"
        review = {"required": True, "population_issues": 1, "unresolved_critical_issues": 2,
                  "affected_enquiry_ids": ["ENQ-DISPUTED"],
                  "reasons": ["Unresolved source conflicts."]}
        data["input_quality"] = {"review_required": review}
        self.assertEqual(recommend(data)["action"], "review_source_conflicts")
        exceedance = recommend(data, max_critical_rate=0.01)
        self.assertEqual(exceedance["action"], "redesign_and_retest")
        self.assertEqual(exceedance["critical_check"]["failure_episode_ids"], [f"{CANDIDATE}-1"])
        self.assertEqual(exceedance["input_quality_review"], review)

    def test_nonblocking_quality_entry_leaves_existing_recommendation(self):
        data = trial()
        data["input_quality"] = {"review_required": {"required": False, "population_issues": 0,
            "unresolved_critical_issues": 0, "affected_enquiry_ids": [], "reasons": []}}
        self.assertEqual(recommend(data)["action"], "consider_controlled_expansion")

    def test_zero_recorded_critical_failures_cannot_establish_rare_event_safety(self):
        data = trial()
        for row in data["episodes"]:
            row["initial_failure"] = False
        decision = recommend(data, max_critical_rate=0.01)
        self.assertEqual(decision["critical_check"]["status"], "within_limit")
        self.assertIsNone(decision["net_uncertainty"]["critical_upper"])
        self.assertEqual(decision["action"], "continue_controlled_trial")

    def test_unknown_service_outcomes_can_change_the_economic_decision(self):
        data = trial()
        for row in data["episodes"][:50]:
            row["outcome"]["state"] = "unknown"
        decision = recommend(data)
        lower, upper = decision["net_uncertainty"]["bounds"]
        self.assertLess(lower, 0)
        self.assertGreater(upper, 0)
        self.assertEqual(decision["action"], "continue_controlled_trial")

    def test_action_identifies_the_first_decision_input_to_resolve(self):
        data = trial()
        self.assertEqual(recommend(data, max_critical_rate=None)["action"], "agree_failure_limit")
        self.assertEqual(recommend(data, value_basis="illustrative")["action"], "validate_business_value")
        self.assertEqual(recommend(data, value_evidence="  ")["action"], "validate_business_value")
        data["group_metrics"][CANDIDATE]["cost_per_request"]["coverage"] = 0.5
        self.assertEqual(recommend(data)["action"], "reconcile_costs")
        data["data_readiness"]["comparison_status"] = "unsupported_design"
        decision = recommend(data)
        self.assertEqual(decision["action"], "improve_comparison")
        self.assertIsNone(decision["net_uncertainty"])

    def test_source_declared_partial_rollout_blocks_causal_status(self):
        rollout = [{"date": "2026-01-01", "agent_version": arm, "arm_assignment_rule": "random_by_enquiry"}
                   for arm in (BASE, CANDIDATE)]
        episodes = [{"eligible": True, "exclusion_reasons": [], "assigned_arm": arm,
                     "assignment_method": "randomized", "assignment_at": "2026-01-02T00:00:00Z",
                     "received_at": "2026-01-02T00:00:00Z", "outcome": {"state": "resolved"}}
                    for arm in (BASE, CANDIDATE)]
        data = ExportData(tables={"rollout_log": rollout}, available={"enquiries", "rollout_log"})
        self.assertEqual(design_diagnostics(data, episodes, 0)["comparison_status"], "randomized_assignment")
        data.metadata["source_completeness"] = {"enquiries": "complete", "rollout_log": "partial"}
        self.assertEqual(design_diagnostics(data, episodes, 0)["comparison_status"], "unverified_randomization")
        data.metadata["source_completeness"]["enquiries"] = "partial"
        self.assertEqual(design_diagnostics(data, episodes, 0)["comparison_status"], "incomplete_assignment")

    def test_case_advice_requires_a_verified_critical_finding(self):
        assessment = {"criteria": {"shipment_identity": {"status": "unmet", "severity": "critical", "refs": ["reply-1"]},
                                   "initial_escalation": {"status": "unknown", "severity": "unknown", "refs": ["case-1"]}}}
        actions = case_review_actions(assessment)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["refs"], ["reply-1"])
        self.assertIn("tracking event belongs to another container", actions[0]["action"])
