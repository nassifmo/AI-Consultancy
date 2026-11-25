"""Verify that schema suggestions are grounded and require a separate profile edit."""

from copy import deepcopy
import json
from unittest.mock import patch

import pytest

from pilot.importing import import_source
from pilot.review import apply_path_suggestion, inspect_source_fields, preview_source_record, suggest_paths, suggest_paths_with_ollama


@pytest.fixture
def draft(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "shipments.jsonl").write_text(
        '{broken line}\n{"Ship_Ref":"BOOK-001","Account":{"ID":"C-02"},"Comment":"Private text"}\n',
        encoding="utf-8",
    )
    profile = {
        "schema_version": "1.0",
        "profile_id": "test-shipping",
        "profile_version": "1.0",
        "metadata": {
            "study_period": ["2026-11-01T00:00:00+00:00", "2026-11-08T00:00:00+00:00"],
            "data_cutoff": "2026-11-08T12:00:00+00:00",
            "source_completeness": {"shipments": "complete"},
        },
        "tables": {
            "shipments": {
                "file": "shipments.jsonl",
                "format": "jsonl",
                "columns": {
                    "booking_ref": {"path": "OldBookingField", "type": "string"},
                    "customer_id": "Account.ID",
                },
            },
        },
    }
    prepared = import_source(source, profile)
    fields = inspect_source_fields(source, profile)
    return source, profile, prepared, fields


def test_suggest_and_apply_without_changing_original(draft):
    source, profile, prepared, fields = draft
    original_file = (source / "shipments.jsonl").read_bytes()
    original_profile = deepcopy(profile)

    suggestions = suggest_paths(profile, prepared["issues"], fields)

    suggestion, = suggestions
    assert suggestion["source_path"] == "Ship_Ref"
    assert suggestion["source_row"] == 2
    assert suggestion["previous_path"] == "OldBookingField"
    assert suggestion["source_file"] == "shipments.jsonl"
    assert prepared["exports"]["shipments.csv"][0]["booking_ref"] == ""
    assert preview_source_record(source, profile, "shipments", 1) is None
    assert preview_source_record(source, profile, "shipments", 2)["Ship_Ref"] == "BOOK-001"

    revised = apply_path_suggestion(profile, suggestion, fields)
    checked = import_source(source, revised)

    assert revised["profile_version"] != profile["profile_version"]
    assert revised["tables"]["shipments"]["columns"]["booking_ref"] == {"path": "Ship_Ref", "type": "string"}
    assert revised["metadata"] == profile["metadata"]
    assert profile == original_profile
    assert (source / "shipments.jsonl").read_bytes() == original_file
    assert checked["exports"]["shipments.csv"][0]["booking_ref"] == "BOOK-001"
    assert checked["exports"]["export_metadata.json"]["source_completeness"]["shipments"] == "partial"
    assert {item["code"] for item in checked["issues"]} == {"malformed_source_row"}

    with pytest.raises(ValueError, match="current profile"):
        apply_path_suggestion(revised, suggestion, fields)
    with pytest.raises(ValueError, match="observed source path"):
        apply_path_suggestion(profile, {**suggestion, "source_path": "invented"}, fields)


def test_only_schema_wide_missing_paths_are_proposed(draft):
    source, profile, _, _ = draft
    with (source / "shipments.jsonl").open("a", encoding="utf-8") as stream:
        stream.write('{"OldBookingField":"BOOK-002","Account":{"ID":"C-02"}}\n')
    prepared = import_source(source, profile)
    fields = inspect_source_fields(source, profile)
    assert suggest_paths(profile, prepared["issues"], fields) == []
    assert suggest_paths(profile, [{"table": "shipments", "field": "booking_ref", "code": "conflicting_record_id"}],
                         fields) == []


def test_local_model_sees_names_only_and_cannot_choose_invented_path(draft):
    _, profile, prepared, fields = draft
    with patch("pilot.review.OllamaClaimReader", autospec=True) as reader:
        local = reader.return_value
        local._local_model_is_ready.return_value = True
        local._structured_chat.return_value = '{"suggestions":[{"issue_index":0,"candidate_index":2}]}'

        result, = suggest_paths_with_ollama(profile, prepared["issues"], fields, "qwen2.5:7b-instruct")

        sent = local._structured_chat.call_args.args[0]
        payload, = json.loads(sent)
        assert result["source_path"] == payload["source_paths"][2]
        assert result["origin"] == "ollama:qwen2.5:7b-instruct"
        assert {"BOOK-001", "Private text", "C-02"}.isdisjoint(sent.split('"'))
        reader.assert_called_once_with("qwen2.5:7b-instruct", max_reads=1)
        local._structured_chat.return_value = '{"suggestions":[{"issue_index":0,"candidate_index":500}]}'
        with pytest.raises(ValueError, match="outside the observed"):
            suggest_paths_with_ollama(profile, prepared["issues"], fields, "qwen2.5:7b-instruct")


def test_unmapped_required_field_can_be_added_without_default_values(draft):
    _, profile, prepared, fields = draft
    del profile["tables"]["shipments"]["columns"]["booking_ref"]
    missing = {"table": "shipments", "field": "booking_ref", "code": "unmapped_required_field"}
    suggestion, = suggest_paths(profile, [missing, *prepared["issues"]], fields)
    assert suggestion["previous_path"] is None
    revised = apply_path_suggestion(profile, suggestion, fields)
    assert revised["tables"]["shipments"]["columns"]["booking_ref"] == "Ship_Ref"
