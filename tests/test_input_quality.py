import csv
from io import StringIO
import json
from pathlib import Path
import shutil

from evaluator.analysis import analyze_exports
from evaluator.recommendation import assess_recommendation
from evaluator.reporting import input_quality_csv
from pilot.importing import import_source
from qa.pilot_readiness import EXAMPLE


ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "evaluator/policy.json").read_text(encoding="utf-8"))


def scenario(tmp_path):
    return shutil.copytree(ROOT / "datagen/datasets/scenarios/S32/exports", tmp_path / "exports")


def append_version(path, **changes):
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        row, columns = next(reader), reader.fieldnames
    with path.open("a", encoding="utf-8", newline="") as stream:
        csv.DictWriter(stream, columns).writerow(row | changes)


def profile(result, table):
    return next(row for row in result["input_quality"]["files"] if row["table"] == table)


def test_work_conflict_and_duplicate_count_each_export_row_once(tmp_path):
    exports = scenario(tmp_path)
    append_version(exports / "agent_work.csv")
    append_version(exports / "agent_work.csv", active_seconds="420")
    result = analyze_exports(exports, POLICY)
    work = profile(result, "agent_work")
    assert (work["input_rows"], work["affected_rows"], work["affected_fraction"]) == (3, 3, 1.0)
    assert (work["duplicate_rows"], work["conflicting_ids"]) == (1, 1)
    flags = [row for row in result["input_quality"]["issues"] if row["kind"] == "conflicting_record_id"]
    assert [row["row_number"] for row in flags] == [1, 2, 3]
    assert all(row["field"] == "active_seconds" and row["enquiry_ids"] == ["ENQ-S32"] for row in flags)
    assert result["enquiries"][0]["initial_failure"] is True
    assert result["enquiries"][0]["verification"]["human_work"]["active_seconds"] is None
    assert result["input_quality"]["review_required"]["required"] is False


def test_conflicted_enquiry_removal_is_visible_and_blocks_recommendation(tmp_path):
    exports = scenario(tmp_path)
    append_version(exports / "enquiries.csv", customer_message="Which container has unloaded?")
    result = analyze_exports(exports, POLICY)
    assert not result["enquiries"]
    quality = result["input_quality"]
    assert quality["review_required"]["required"]
    assert quality["review_required"]["affected_enquiry_ids"] == ["ENQ-S32"]
    assert quality["review_required"]["population_issues"] == 2
    assert profile(result, "enquiries")["affected_rows"] == 2
    decision = assess_recommendation(result, "human_baseline", "agent_v1", "verified_resolution",
                                     max_critical_rate=.01)
    assert decision["action"] == "review_source_conflicts"
    records = list(csv.DictReader(StringIO(input_quality_csv(result).decode("utf-8-sig"))))
    assert any(r["record_id"] == "ENQ-S32" and r["row_number"] == "2" for r in records)


def test_conflicting_reply_links_to_the_unresolved_critical_check(tmp_path):
    exports = scenario(tmp_path)
    append_version(exports / "responses.csv", claimed_status="arrived")
    result = analyze_exports(exports, POLICY)
    review = result["input_quality"]["review_required"]
    assert result["enquiries"][0]["initial_failure"] is None
    assert review["required"] and review["unresolved_critical_issues"] == 2
    assert review["affected_enquiry_ids"] == ["ENQ-S32"]


def test_missing_file_does_not_enter_observed_row_fraction(tmp_path):
    exports = scenario(tmp_path)
    (exports / "responses.csv").unlink()
    result = analyze_exports(exports, POLICY)
    row = profile(result, "responses")
    assert row["input_rows"] is row["affected_rows"] is row["affected_fraction"] is None
    assert any(i["filename"] == "responses.csv" and i["kind"] == "missing_file"
               for i in result["input_quality"]["issues"])


def test_mapped_source_rejection_has_original_row_and_distinct_denominator(tmp_path):
    source = shutil.copytree(EXAMPLE / "source", tmp_path / "source")
    tracking = source / "tracking.jsonl"
    count = len(tracking.read_text(encoding="utf-8").splitlines())
    with tracking.open("a", encoding="utf-8") as stream:
        stream.write('"unusable source row"\n')
    mapping = json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8"))
    prepared = import_source(source, mapping, tmp_path / "prepared")
    result = analyze_exports(Path(prepared["exports_path"]), POLICY)
    quality = result["input_quality"]
    table = next(row for row in quality["preparation"] if row["table"] == "tracking_events")
    assert (table["input_rows"], table["affected_rows"]) == (count + 1, 1)
    assert profile(result, "tracking_events")["input_rows"] == count
    assert any(i["basis"] == "source_records" and i["kind"] == "malformed_source_row"
               and i["row_number"] == count + 1 and i["filename"] == "tracking.jsonl" for i in quality["issues"])
    assert quality["review_required"]["required"]
