"""Run the documented source-to-findings rehearsal in the regression suite."""

from qa.pilot_readiness import rehearse


def test_pilot_rehearsal_checks_clean_and_incomplete_extracts():
    result = rehearse()
    assert len(result["scenarios"]) == len({case["import_id"] for case in result["scenarios"]}) == 4
    assert result["passed"], [case["mismatches"] for case in result["scenarios"]]
