"""Independent calculation fixtures for the economic ledger."""

from datetime import datetime
import json
from unittest import TestCase

from evaluator.economics import build_cost_ledger, overlapping_work_ids
from evaluator.exports import ExportData


RECEIPT = "2026-01-03T10:00:00Z"
CHECKPOINT = "2026-01-10T10:00:00Z"


def work(identifier, contact, start, end, seconds, actor="h1"):
    return {
        "work_id": identifier, "enquiry_id": contact, "agent_id": actor,
        "accepted_at": start, "closed_at": end, "active_seconds": seconds,
        "acw_seconds": 20, "measurement_method": "logged",
    }


def run(identifier, contact, *, start="2026-01-03T10:00:10Z", end="2026-01-03T10:01:10Z"):
    return {
        "run_id": identifier, "enquiry_id": contact, "started_at": start, "ended_at": end,
        "tokens_in": 4, "tokens_out": 2, "voice_seconds": 60,
    }


def episode(identifier, arm, *, eligible=True, seconds=0, work_ids=(), contacts=None):
    return {
        "root_enquiry_id": identifier,
        "contacts": contacts if contacts is not None else [identifier],
        "assigned_arm": arm, "eligible": eligible, "active_seconds": seconds,
        "received_at": RECEIPT, "checkpoint": CHECKPOINT,
        "work_refs": [f"agent_work.csv#{identifier}" for identifier in work_ids],
    }


def finance_data():
    usage = [
        ("voice_minutes", "2", "0.60", "1.20"),
        ("llm_tokens_in", "8", "0.10", "0.80"),
        ("llm_tokens_out", "4", "0.20", "0.80"),
        ("runs", "2", "0.50", "1.00"),
        ("platform_fee", "1", "12", "12"),
    ]
    invoices = [
        {"period": "2026-01", "line_item": item, "quantity": quantity, "unit_price": rate,
         "amount": amount, "currency": "USD"}
        for item, quantity, rate, amount in usage
    ]
    human_work = [
        work("w1", "H", "2026-01-03T10:01:00Z", "2026-01-03T10:03:00Z", 60),
        work("w2", "F", "2026-01-04T11:00:00Z", "2026-01-04T11:05:00Z", 90),
    ]
    tables = {
        "enquiries": [{"enquiry_id": contact} for contact in ("H", "A1", "A2", "F")],
        "agent_work": human_work,
        "agent_runs": [run("r1", "A1"), run("r2", "A2")],
        "ai_invoice": invoices,
        "staffing": [{"month": "2026-01", "support_headcount": "15", "overtime_hours": "0"}],
    }
    data = ExportData(
        tables=tables, available=set(tables),
        metadata={"billing_timezone": "UTC", "agent_run_usage_complete": True},
        cutoff=datetime.fromisoformat("2026-01-13T00:00:00Z"),
        cost_parameters={"currency": "USD", "valid_from": "2026-01-01", "labor_rate_per_hour": 60,
                         "platform_fee_month": 99, "maintenance_month": 4, "setup_cost": 48,
                         "amortization_months": 12},
    )
    episodes = [
        episode("H", "human_baseline", seconds=60, work_ids=["w1"]),
        episode("A1", "agent_v1", seconds=90, work_ids=["w2"], contacts=["A1", "F"]),
        episode("A2", "agent_v2", eligible=False),
    ]
    return data, episodes


class EconomicsTests(TestCase):
    def test_partial_sources_retain_subtotal_without_claiming_complete_costs(self):
        data, episodes = finance_data()
        data.metadata["source_completeness"] = {
            "enquiries": "complete", "agent_work": "complete", "agent_runs": "partial", "ai_invoice": "partial",
        }
        ledger = build_cost_ledger(data, episodes)
        result = ledger["per_episode"]["A1"]
        self.assertEqual(result["known_cost"], 13.4)
        self.assertIsNone(result["total_cost"])
        self.assertFalse(result["complete"])
        self.assertIn("incomplete_source_agent_runs", result["unknown_reasons"])
        self.assertIn("incomplete_source_ai_invoice", result["unknown_reasons"])

    def test_reconciled_cost_includes_continuation_work_and_excluded_fixed_share(self):
        data, episodes = finance_data()
        # Duplicate invoice rows must not book two copies of the charge.
        data.tables["ai_invoice"].append(dict(data.tables["ai_invoice"][-1]))
        result = build_cost_ledger(data, episodes)
        self.assertEqual(result["currency"], "USD")
        self.assertEqual(result["per_episode"]["H"]["total_cost"], 1.00)
        self.assertEqual(result["per_episode"]["A1"]["by_category"]["human_work"], 1.50)
        self.assertEqual(result["per_episode"]["A1"]["total_cost"], 13.40)
        self.assertEqual(result["per_episode"]["A2"]["total_cost"], 11.90)
        platform = next(line for line in result["reconciliation"] if line["category"] == "platform_fee")
        self.assertEqual((platform["amount"], platform["included"], platform["excluded"], platform["unallocated"]),
                         (12, 6, 6, 0))
        self.assertIsNone(result["realized_cash_savings"])
        json.dumps(result, allow_nan=False)

    def test_missing_labor_rate_keeps_human_work_cost_unknown(self):
        data, episodes = finance_data()
        del data.cost_parameters["labor_rate_per_hour"]
        result = build_cost_ledger(data, episodes)
        ai = result["per_episode"]["A1"]
        self.assertIsNone(ai["total_cost"])
        self.assertEqual(ai["known_cost"], 11.90)
        self.assertIn("missing_labor_rate", ai["unknown_reasons"])
        self.assertIsNone(result["per_episode"]["H"]["known_cost"])

    def test_missing_invoice_uses_documented_platform_estimate_only(self):
        data, episodes = finance_data()
        data.tables["ai_invoice"].pop()
        result = build_cost_ledger(data, episodes)
        platform = next(line for line in result["reconciliation"] if line["category"] == "platform_fee")
        self.assertTrue(platform["estimated"])
        self.assertEqual(platform["amount"], 99)

    def test_inconsistent_usage_surfaces_invoice_and_modeled_cost_without_consolidation(self):
        data, episodes = finance_data()
        retry = run("retry", "A1", start="2026-01-03T10:00:00Z", end="2026-01-03T10:00:05Z")
        retry["tokens_in"] = None
        data.tables["agent_runs"].append(retry)
        result = build_cost_ledger(data, episodes)
        self.assertIsNone(result["per_episode"]["A1"]["total_cost"])
        self.assertIn("ai_usage_invoice_mismatch", result["per_episode"]["A2"]["unknown_reasons"])
        tokens = next(line for line in result["reconciliation"] if line["category"] == "llm_tokens_in")
        self.assertFalse(tokens["matched"])
        self.assertEqual(tokens["unallocated"], 0.80)
        self.assertEqual(tokens["modelled_meter_cost"], 0.80)
        self.assertEqual(tokens["missing_meter_count"], 1)

    def test_mixed_currencies_retains_line_items_and_does_not_consolidate(self):
        data, episodes = finance_data()
        data.tables["ai_invoice"][0]["currency"] = "EUR"
        result = build_cost_ledger(data, episodes)
        self.assertIsNone(result["currency"])
        self.assertIsNone(result["per_episode"]["A1"]["total_cost"])
        self.assertIn("consolidated_currency_unavailable", result["per_episode"]["A1"]["unknown_reasons"])
        self.assertTrue(any(line["currency"] == "EUR" for line in result["reconciliation"]))

    def test_invalid_fixed_invoice_is_reported_as_missing_without_estimate(self):
        data, episodes = finance_data()
        data.tables["ai_invoice"][-1]["amount"] = "120"
        result = build_cost_ledger(data, episodes)
        self.assertIn("missing_platform_fee", result["per_episode"]["A1"]["unknown_reasons"])
        self.assertFalse(any(item["category"] == "platform_fee" for item in result["entries"]))

    def test_unfamiliar_invoice_category_keeps_affected_cost_incomplete(self):
        data, episodes = finance_data()
        data.tables["ai_invoice"].append({
            "period": "2026-01", "line_item": "special_service", "quantity": "1",
            "unit_price": "50", "amount": "50", "currency": "USD",
        })
        result = build_cost_ledger(data, episodes)
        self.assertIsNone(result["per_episode"]["A1"]["total_cost"])
        self.assertEqual(result["per_episode"]["A1"]["known_cost"], 13.40)
        self.assertIn("unsupported_invoice_charge", result["per_episode"]["A1"]["unknown_reasons"])
        self.assertTrue(any(issue["code"] == "unsupported_invoice_row" and issue["amount"] == 50
                            for issue in result["issues"]))

    def test_usage_crossing_checkpoint_is_excluded_from_episode_but_matches_invoice(self):
        data, episodes = finance_data()
        data.tables["agent_runs"][1] = run("r2", "A2", start="2026-01-10T09:59:30Z", end="2026-01-10T10:00:30Z")
        result = build_cost_ledger(data, episodes)
        self.assertEqual(result["per_episode"]["A1"]["total_cost"], 13.40)
        self.assertIsNone(result["per_episode"]["A2"]["total_cost"])
        self.assertIn("incomplete_ai_metering", result["per_episode"]["A2"]["unknown_reasons"])
        voice = next(line for line in result["reconciliation"] if line["category"] == "voice_minutes")
        self.assertEqual((voice["included"], voice["excluded"], voice["unallocated"]), (0.6, 0.6, 0))

    def test_cross_enquiry_overlaps_include_earliest_affected_instant(self):
        data, _ = finance_data()
        data.tables["agent_work"].extend([
            work("other-contact", "A1", "2026-01-03T10:02:00Z", "2026-01-03T10:03:30Z", 60),
            work("edge", "A2", "2026-01-03T10:03:30Z", "2026-01-03T10:04:30Z", 60),
            work("orphan", "missing", "2026-01-03T10:04:00Z", "2026-01-03T10:05:30Z", 60),
        ])
        instant = datetime.fromisoformat("2026-01-03T10:02:00Z")
        self.assertEqual(overlapping_work_ids(data), {"w1": instant, "other-contact": instant})
