"""Display evidence quality counts and the records that need review."""

import streamlit as st

from evaluator.reporting import input_quality_csv


_PAGE_SIZE = 100

_KINDS = {
    "duplicate": "Exact duplicate",
    "exact_duplicate": "Exact duplicate",
    "duplicate_row": "Exact duplicate",
    "conflict": "Conflicting record",
    "conflicting_record": "Conflicting record",
    "conflicting_record_id": "Conflicting record",
    "missing_file": "File missing",
    "invalid_file": "File could not be read",
    "missing_required_field": "Required field missing",
    "missing_record_id": "Record ID missing",
    "missing_link": "Required link missing",
    "unmatched_link": "Target record missing",
    "unlinked_record": "Record could not be linked",
    "orphaned_link": "Target record missing",
    "source_partial": "Source coverage partial",
    "source_unconfirmed": "Source coverage unconfirmed",
    "unconfirmed_coverage": "Source coverage unconfirmed",
    "source_completeness": "Source coverage",
}

_STATUS = {
    "loaded": "Loaded",
    "valid": "Loaded",
    "partially_valid": "Loaded with issues",
    "partial": "Partial",
    "missing": "Missing",
    "invalid": "Could not be read",
    "unavailable": "Unavailable",
    "complete": "Complete",
    "unknown": "Unconfirmed",
    "unspecified": "Unconfirmed",
    "not_applicable": "Not applicable",
}

_IMPACTS = {
    "population": "May change which requests count",
    "critical": "May change a critical check",
    "measurement": "Affects the named measurement",
    "counted_once": "Counted once",
    "coverage": "Evidence coverage",
}


def _label(value, labels=None):
    if not value:
        return "—"
    return (labels or {}).get(value, str(value).replace("_", " ").capitalize())


def _id_list(values):
    if isinstance(values, str):
        return values
    return ", ".join(map(str, values or []))


def _count(value):
    return f"{value:,}" if value is not None else "—"


def _share(value):
    if value is None:
        return "Unavailable"
    if 0 < value < 0.001:
        return "<0.1%"
    return f"{value:.1%}"


def _trace(issue):
    ref = issue.get("source_ref")
    if isinstance(ref, str):
        return ref
    if isinstance(ref, dict):
        name = ref.get("filename") or ref.get("source_file") or ref.get("file")
        row = ref.get("row_number") or ref.get("row") or ref.get("source_row")
        return f"{name} · row {row}" if name and row is not None else str(name or "")
    return ""


def _matches(issue, query):
    values = (issue.get("record_id"), _id_list(issue.get("enquiry_ids")),
              issue.get("row_number"), _trace(issue))
    return any(query in str(value).casefold() for value in values if value is not None)


def _reset_page(key):
    st.session_state.pop(key, None)


@st.fragment
def render_input_quality(result, *, key_prefix="input_quality", preparing=False):
    """Keep affected-row counts distinct from files or records with unknown coverage."""
    quality = result["input_quality"]
    st.subheader("Data quality and records to review")
    summary = quality.get("summary", {})
    files = quality.get("files", [])
    preparation = quality.get("preparation", [])
    issues = quality.get("issues", [])
    review = quality.get("review_required") or {}
    columns = st.columns(3)
    denominator = summary.get("input_rows")
    numerator = summary.get("affected_rows")
    columns[0].metric("Rows with detected issues", _share(summary.get("affected_fraction")))
    if numerator is not None and denominator is not None:
        columns[0].caption(f"{_count(numerator)} of {_count(denominator)} rows checked")
    columns[1].metric("Extra copies of duplicate rows", _count(summary.get("duplicate_rows")))
    columns[2].metric("Conflicting record IDs", _count(summary.get("conflict_ids")))
    basis = summary.get("basis") or quality.get("basis")
    explanation = ("These counts use original source rows when the import retained them."
                   if basis == "source_records" else "These counts use the supplied export rows, after any company field mapping.")
    st.caption(explanation + " A row with more than one issue is counted once. Missing files and unknown source coverage "
               "are shown separately because we do not know how many records were never supplied.")
    missing, partial = summary.get("files_unavailable"), summary.get("files_partial")
    if missing is not None or partial is not None:
        st.caption(f"Files unavailable: {_count(missing)}. Files flagged partial: {_count(partial)}.")
    if review.get("required") and preparing:
        st.warning("Some disputed records may change which enquiries count or which critical checks can be verified.")
    elif review.get("required"):
        st.warning("Review these records before expanding the AI workflow. Some issues may change a critical check "
                   "or which enquiries count in the comparison.")
        population, critical = review.get("population_issues"), review.get("unresolved_critical_issues")
        if population is not None or critical is not None:
            st.caption(f"Rows affecting which enquiries count: {_count(population)}. "
                       f"Rows that may change a critical check: {_count(critical)}.")
        if review.get("affected_enquiry_ids"):
            names = list(review["affected_enquiry_ids"])
            preview = _id_list(names[:10])
            extra = f" (and {len(names) - 10:,} more)" if len(names) > 10 else ""
            st.text(f"Enquiries linked to this warning: {preview}{extra}")

    if files:
        st.dataframe([
            {"File": row.get("filename"), "Status": _label(row.get("status"), _STATUS),
             "Rows checked": row.get("input_rows"), "Affected rows": row.get("affected_rows"),
             "Affected share": _share(row.get("affected_fraction")), "Extra duplicates": row.get("duplicate_rows"),
             "Conflicting IDs": row.get("conflicting_ids"), "Source coverage": _label(row.get("source_completeness"), _STATUS)}
            for row in files
        ], hide_index=True)

    if preparation:
        with st.expander("Original source mapping issues"):
            st.caption("These figures cover the original company extracts. They include mapping or rejected-row "
                       "issues found before evaluation and have a separate denominator from the export figures above.")
            st.dataframe([
                {"Source file": row.get("filename"), "Original rows checked": row.get("input_rows"),
                 "Rows with mapping issues": row.get("affected_rows"),
                 "Affected share": _share(row.get("affected_fraction"))}
                for row in preparation
            ], hide_index=True)

    if not issues:
        st.caption("No review items were detected in the supplied records.")
        return
    with st.expander("Browse records and evidence issues", expanded=bool(review.get("required"))):
        st.caption("Use the file and row or record ID to find the original evidence. "
                   "One record can appear on more than one line if it has different issues.")
        first, second = st.columns(2)
        labels = sorted({i["filename"] for i in issues if i.get("filename")})
        filenames = ["All files", *labels]
        kinds = ["All issues", *sorted({i["kind"] for i in issues if i.get("kind")})]
        # Reset selections if a new dataset does not contain the old filter value.
        file_key, kind_key, page_key = (f"{key_prefix}_{part}" for part in ("file", "kind", "page"))
        for key, choices in ((file_key, filenames), (kind_key, kinds)):
            if key in st.session_state and st.session_state[key] not in choices:
                del st.session_state[key]
        selected_file = first.selectbox("Filter by file", filenames, key=file_key, on_change=_reset_page, args=(page_key,))
        selected_kind = second.selectbox("Filter by issue", kinds, key=kind_key,
                                         on_change=_reset_page, args=(page_key,),
                                         format_func=lambda kind: _label(kind, _KINDS) if kind != "All issues" else kind)
        query = st.text_input("Find by record ID, enquiry ID or row", key=f"{key_prefix}_search",
                              on_change=_reset_page, args=(page_key,)).strip().casefold()
        st.download_button("Download all data issues", input_quality_csv(result), file_name="input_quality.csv",
                           mime="text/csv", on_click="ignore", key=f"{key_prefix}_download")
        matches = [i for i in issues
                   if (selected_file == "All files" or i.get("filename") == selected_file)
                   and (selected_kind == "All issues" or i.get("kind") == selected_kind)
                   and (not query or _matches(i, query))]
        if not matches:
            st.info("No issues match these filters.")
            return
        pages = (len(matches) + _PAGE_SIZE - 1) // _PAGE_SIZE
        if st.session_state.get(page_key, 1) > pages:
            _reset_page(page_key)
        page = st.selectbox("Page", range(1, pages + 1), key=page_key) if pages > 1 else 1
        start = (page - 1) * _PAGE_SIZE
        stop = min(start + _PAGE_SIZE, len(matches))
        st.caption(f"Showing {start + 1:,}–{stop:,} of {len(matches):,} matching items ({len(issues):,} listed in total).")
        st.dataframe([
            {"File": issue.get("filename"), "Row": issue.get("row_number"), "Issue": _label(issue.get("kind"), _KINDS),
             "Record ID": issue.get("record_id"), "Field": issue.get("field"),
             "Enquiry IDs": _id_list(issue.get("enquiry_ids")), "What it affects": _label(issue.get("impact"), _IMPACTS),
             "Source reference": _trace(issue), "Details": issue.get("detail"),
             "Evidence stage": "Original extract" if issue.get("basis") == "source_records" else "Evaluation export"}
            for issue in matches[start:stop]
        ], hide_index=True)
