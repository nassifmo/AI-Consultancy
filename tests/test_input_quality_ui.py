"""Verify that the dashboard can explain and locate input quality problems."""

from streamlit.testing.v1 import AppTest


def _quality_app():
    from input_quality_ui import render_input_quality

    render_input_quality({"input_quality": {
        "summary": {"input_rows": 100, "affected_rows": 3, "affected_fraction": .03,
                    "duplicate_rows": 1, "conflict_ids": 1, "files_unavailable": 1, "files_partial": 1},
        "files": [
            {"table": "responses", "filename": "responses.csv", "status": "partially_valid",
             "source_completeness": "partial", "input_rows": 100, "affected_rows": 3,
             "affected_fraction": .03, "duplicate_rows": 1, "conflicting_ids": 1},
            {"table": "tracking_events", "filename": "tracking_events.json", "status": "missing",
             "source_completeness": "unknown", "input_rows": None, "affected_rows": None,
             "affected_fraction": None, "duplicate_rows": None, "conflicting_ids": None},
        ],
        "issues": [
            {"table": "responses", "filename": "responses.csv", "kind": "conflicting_record_id",
             "record_id": "RSP-001", "row_number": 53, "impact": "critical", "enquiry_ids": ["ENQ-001"],
             "source_ref": "messages.csv row 17", "detail": "Mapped values disagree."},
            {"table": "responses", "filename": "responses.csv", "kind": "duplicate_row",
             "record_id": "RSP-090", "row_number": 100, "impact": "counted_once"},
            {"table": "tracking_events", "filename": "tracking_events.json", "kind": "missing_file",
             "impact": "coverage"},
        ],
        "review_required": {"required": True, "affected_enquiry_ids": ["ENQ-001"]},
    }})


def _pagination_app():
    from input_quality_ui import render_input_quality

    render_input_quality({"input_quality": {"issues": [
        {"filename": "responses.csv", "kind": "duplicate_row", "record_id": f"TEST-{n:03d}"}
        for n in range(1, 102)
    ]}})


def _prepared_import_app():
    from input_quality_ui import render_input_quality

    render_input_quality({"input_quality": {
        "summary": {"input_rows": 9, "affected_rows": 0, "affected_fraction": 0.0},
        "preparation": [{"table": "enquiries", "filename": "intake.csv", "input_rows": 10,
                         "affected_rows": 1, "affected_fraction": 0.1}],
        "issues": [{"filename": "intake.csv", "kind": "malformed_source_row", "row_number": 10,
                    "basis": "source_records", "source_ref": "intake.csv row 10"}],
    }})


def test_dashboard_reports_fraction_and_searches_for_linked_enquiry():
    app = AppTest.from_function(_quality_app).run()
    assert not app.exception
    assert {metric.label: metric.value for metric in app.metric}["Rows with detected issues"] == "3.0%"
    assert any("3 of 100 rows checked" in caption.value for caption in app.caption)
    assert any("before expanding" in notice.value for notice in app.warning)
    assert app.dataframe[0].value.loc[1, "Affected share"] == "Unavailable"
    assert len(app.dataframe[1].value) == 3
    assert any(button.label == "Download all data issues" for button in app.get("download_button"))
    app.text_input(key="input_quality_search").set_value("enq-001").run()
    assert not app.exception
    row, = app.dataframe[1].value.to_dict(orient="records")
    assert row["Record ID"] == "RSP-001"
    assert row["Source reference"] == "messages.csv row 17"
    app.text_input(key="input_quality_search").set_value("")
    app.selectbox(key="input_quality_kind").select("missing_file").run()
    assert not app.exception
    assert list(app.dataframe[1].value["File"]) == ["tracking_events.json"]


def test_dashboard_paginates_without_losing_unlisted_records():
    app = AppTest.from_function(_pagination_app).run()
    assert not app.exception
    assert len(app.dataframe[0].value) == 100
    app.selectbox(key="input_quality_page").select(2).run()
    assert list(app.dataframe[0].value["Record ID"]) == ["TEST-101"]
    app.text_input(key="input_quality_search").set_value("test-003").run()
    assert not app.exception
    assert list(app.dataframe[0].value["Record ID"]) == ["TEST-003"]


def test_preparation_counts_use_a_separate_source_denominator():
    app = AppTest.from_function(_prepared_import_app).run()
    assert not app.exception
    assert any("0 of 9 rows checked" in caption.value for caption in app.caption)
    record, = app.dataframe[0].value.to_dict(orient="records")
    assert record == {"Source file": "intake.csv", "Original rows checked": 10,
                      "Rows with mapping issues": 1, "Affected share": "10.0%"}
    assert app.dataframe[1].value.iloc[0]["Evidence stage"] == "Original extract"
