import json
import subprocess
import sys
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest

from evaluator.pilot_economics import assess_pilot_economics


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "pilot_prospect" / "ECONOMICS_EXAMPLE.json"


@pytest.fixture()
def input_data():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def test_scoped_cost_and_capacity_stay_separate(input_data):
    r = assess_pilot_economics(input_data)
    assert r["incremental_handling_expense_per_enquiry"] == Decimal(".80")
    assert r["observed_downstream_expense_reduction_per_enquiry"] == Decimal("1.30")
    assert r["observed_net_expense_reduction_per_enquiry"] == Decimal(".50")
    assert r["released_active_work_hours_per_1000_enquiries"] == Decimal(50)
    assert r["assessment_status"] == "illustrative_only"
    assert r["handling_only_break_even"]["point_price_per_extra_timely_resolution"] == Decimal("4")
    assert r["handling_only_break_even"]["price_range"][0] == Decimal("3.20")


def test_unassessed_downstream_cannot_make_net_known(input_data):
    input_data["origin"] = "company"
    input_data["downstream_scope"] = "not_assessed"
    input_data["buckets"].pop()
    r = assess_pilot_economics(input_data)
    assert r["observed_net_expense_reduction_per_enquiry"] is None
    assert r["incremental_handling_expense_per_enquiry"] == Decimal(".80")
    assert r["assessment_status"] == "financial_evidence_incomplete"


def test_costly_wrong_answer_reverses_financial_result_despite_better_service(input_data):
    dispatch = input_data["buckets"][1]["candidate"]
    dispatch.append(dict(dispatch[0], entry_id="DEMO-DSP-3", amount="400.00",
                         evidence_ref="DEMO: net dispatch charge after relying on incorrect pickup advice"))
    input_data["candidate"]["critical_failures"]["verified"] = 1
    r = assess_pilot_economics(input_data)
    assert r["service"]["verified_timely_correct_rate_difference"] == Decimal(".20")
    assert r["service"]["gates"]["critical_failures"] == "within_limit"
    assert r["observed_downstream_expense_reduction_per_enquiry"] == Decimal("-2.70")
    assert r["observed_net_expense_reduction_per_enquiry"] == Decimal("-3.50")
    assert r["assessment_status"] == "illustrative_only"


def test_zero_reconciliation_and_missing_records_are_distinct(input_data):
    b = input_data["buckets"][1]
    b["candidate"] = []
    result = assess_pilot_economics(input_data)
    assert result["downstream_expense"]["cost_per_eligible_enquiry"]["candidate"] == 0
    b["candidate_reconciliation_ref"] = None
    result = assess_pilot_economics(input_data)
    assert result["downstream_expense"]["cost_per_eligible_enquiry"] is None
    assert result["observed_net_expense_reduction_per_enquiry"] is None


def test_downstream_linkage_required_and_handling_only_remains_scoped(input_data):
    input_data["buckets"][1]["downstream_linkage_ref"] = None
    result = assess_pilot_economics(input_data)
    assert result["observed_downstream_expense_reduction_per_enquiry"] is None
    assert result["downstream_expense"]["unreconciled_buckets"] == ["failed-dispatch-expense:downstream_linkage"]
    input_data["buckets"].pop()
    input_data["downstream_scope"] = "out_of_scope"
    result = assess_pilot_economics(input_data)
    assert result["observed_net_expense_reduction_per_enquiry"] == Decimal("-.80")
    assert result["net_expense_scope"] == "handling_only"


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("entry_id", "DEMO-SUP-1", "duplicate ledger"),
        ("payer", "customer", "mixed payer"),
        ("currency", "EUR", "mixed payer or currency"),
        ("expense_date", "2026-11-15", "outside the stated study period"),
    ],
)
def test_rejects_cross_scope_or_overlapping_entries(input_data, field, value, message):
    input_data["buckets"][1]["candidate"][0][field] = value
    with pytest.raises(ValueError, match=message):
        assess_pilot_economics(input_data)


def test_quality_gate_and_uncertainty_precede_economic_claim(input_data):
    input_data["origin"] = "company"
    assert assess_pilot_economics(input_data)["assessment_status"] == "observed_comparison_only"
    input_data.update(
        finance_review_ref="approved scoped reconciliation",
        attribution_review_ref="approved analysis design and limitations",
        net_effect_interval={
            "lower_per_enquiry": ".10", "upper_per_enquiry": ".85",
            "confidence_level": ".95", "reference": "reviewed net financial effect by shipment cluster",
        },
    )
    assert assess_pilot_economics(input_data)["assessment_status"] == "supports_financial_review"
    no_target = deepcopy(input_data)
    no_target["minimum_timely_correct_rate"] = None
    assert assess_pilot_economics(no_target)["assessment_status"] == "service_evidence_incomplete"
    input_data["net_effect_interval"]["lower_per_enquiry"] = "-.10"
    assert assess_pilot_economics(input_data)["assessment_status"] == "financial_effect_uncertain"
    input_data["candidate"]["critical_failures"]["unknown"] = 5
    assert assess_pilot_economics(input_data)["assessment_status"] == "service_evidence_incomplete"
    input_data["candidate"]["critical_failures"]["verified"] = 3
    assert assess_pilot_economics(input_data)["assessment_status"] == "blocked_by_service_policy"


def test_bounds_keep_unbounded_break_even_and_missing_work_visible(input_data):
    input_data["comparator"]["timely_correct_resolutions"]["unknown"] = 20
    input_data["comparator"]["active_work_reconciliation_ref"] = None
    result = assess_pilot_economics(input_data)
    assert result["handling_only_break_even"]["price_range"][1] is None
    assert result["handling_only_break_even"]["status"] == "no_finite_worst_case_threshold"
    assert result["released_active_work_hours_per_1000_enquiries"] is None
    no_scope = deepcopy(input_data)
    no_scope["comparable_scope_ref"] = None
    result = assess_pilot_economics(no_scope)
    assert result["incremental_handling_expense_per_enquiry"] is None
    assert result["handling_expense"]["documented_totals"]["comparator"] == Decimal("250.00")


def test_cli_returns_machine_readable_result():
    result = subprocess.run(
        [sys.executable, "-m", "evaluator.pilot_economics", str(SAMPLE)],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)
    assert Decimal(data["observed_net_expense_reduction_per_enquiry"]) == Decimal(".50")
