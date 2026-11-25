import json
from pathlib import Path

import pytest

from pilot.approval import APPROVAL_FILENAME, approve_exports, read_approval


def _draft(tmp_path):
    exports = tmp_path / "draft" / "exports"
    exports.mkdir(parents=True)
    (exports / "export_metadata.json").write_text(json.dumps({
        "dataset_origin": "company",
        "preparation_id": "import-123",
        "source_profile_id": "carrier-support",
        "source_profile_version": "2",
    }), encoding="utf-8")
    (exports / "enquiries.csv").write_bytes(b"enquiry_id,customer_id,received_at,enquiry_type\r\n")
    return exports


def _approve(tmp_path, source, **kwargs):
    return approve_exports(source, tmp_path / "a", reviewer="Support reviewer",
                           note="Reviewed the available sample and source coverage.", **kwargs)


def test_approval_snapshots_export_bytes_and_stores_review_history(tmp_path):
    source = _draft(tmp_path)
    original = (source / "enquiries.csv").read_bytes()
    decisions = [{"issue": "link conflicts", "disposition": "withhold from verified totals", "source": "work.csv#12"}]
    result = _approve(tmp_path, source, decisions=decisions, limitations=["No invoice export"])

    approved = Path(result["exports_path"])
    assert approved.parent.name == result["approval_id"]
    assert approved != source
    assert (approved / "enquiries.csv").read_bytes() == original
    assert read_approval(source) is None
    assert not (source / APPROVAL_FILENAME).exists()
    record = read_approval(approved, required=True)
    assert record == result["approval"]
    assert record["decisions"] == decisions
    assert record["limitations"] == ["No invoice export"]
    assert record["reviewer"] == "Support reviewer"
    assert record["preparation"] == {
        "preparation_id": "import-123", "source_profile_id": "carrier-support", "source_profile_version": "2",
    }


def test_approval_refuses_a_stale_preview_and_preserves_previous_revision(tmp_path):
    source = _draft(tmp_path)
    first = _approve(tmp_path, source)
    (source / "responses.csv").write_bytes(b"response_id\nR-PILOT\n")

    with pytest.raises(ValueError, match="changed during intake review"):
        _approve(tmp_path, source, expected_files=first["approval"]["input_files"])
    second = _approve(tmp_path, source)
    assert second["approval_id"] != first["approval_id"]
    assert read_approval(first["exports_path"], required=True) == first["approval"]
    assert read_approval(second["exports_path"], required=True) == second["approval"]


@pytest.mark.parametrize("change", ["write", "add", "delete"])
def test_changes_to_approved_inputs_block_reading(tmp_path, change):
    source = _draft(tmp_path)
    (source / "responses.csv").write_bytes(b"response_id\nR-PILOT\n")
    approved = Path(_approve(tmp_path, source)["exports_path"])
    if change == "write":
        (approved / "responses.csv").write_bytes(b"response_id\nOTHER\n")
    elif change == "add":
        (approved / "agent_work.csv").write_bytes(b"work_id\nW-EXTRA\n")
    else:
        (approved / "responses.csv").unlink()

    with pytest.raises(ValueError, match="changed since intake approval"):
        read_approval(approved)


def test_changed_reviewer_attestation_fails_fingerprint_check(tmp_path):
    source = _draft(tmp_path)
    approved = Path(_approve(tmp_path, source)["exports_path"])
    path = approved / APPROVAL_FILENAME
    record = json.loads(path.read_text(encoding="utf-8"))
    record["reviewer"] = "Altered reviewer"
    path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(ValueError, match="fingerprint does not match"):
        read_approval(approved)


def test_required_approval_and_review_details_are_validated(tmp_path):
    source = _draft(tmp_path)
    output = tmp_path / "a"
    with pytest.raises(ValueError, match="reviewed and approved"):
        read_approval(source, required=True)
    with pytest.raises(ValueError, match="reviewer"):
        approve_exports(source, output, reviewer=" ", note="Reviewed")
    with pytest.raises(ValueError, match="review note"):
        approve_exports(source, output, reviewer="Reviewer", note=" ")
    assert not output.exists()
