"""Prepare and inspect local company extracts before running the evaluator."""

from contextlib import contextmanager
from io import BytesIO
from hashlib import sha256
import json
from pathlib import Path
import shutil
import stat
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile

import streamlit as st

from input_quality_ui import render_input_quality
from pilot.approval import approve_exports, intake_fingerprints, read_approval
from pilot.inspection import inspect_exports, review_limitations
from pilot.review import (
    apply_path_suggestion,
    inspect_source_fields,
    preview_source_record,
    suggest_paths,
    suggest_paths_with_ollama,
)
from pilot.importing import import_source, validate_profile


ROOT = Path(__file__).resolve().parent
IMPORTS = ROOT / "pilot_imports"
EXAMPLE = ROOT / "pilot" / "examples" / "renamed_shipment"
MAX_UPLOAD = 100 * 1024**2
MAX_EXPANSION = 300 * 1024**2


@contextmanager
def unpack_company_files(payload, profile):
    """Extract only the source files named in an executable-free mapping profile."""
    validate_profile(profile)
    if len(payload) > MAX_UPLOAD:
        raise ValueError("The source ZIP exceeds 100 MiB.")
    names = {table["file"] for table in profile["tables"].values()}
    names.update(item["file"] for item in profile.get("objects", {}).values())
    try:
        with ZipFile(BytesIO(payload)) as archive, TemporaryDirectory(prefix="shipment-source-") as folder:
            total = 0
            seen = set()
            for member in archive.infolist():
                if member.is_dir() and member.filename == "source/":
                    continue
                name = member.filename
                if name.startswith("source/"):
                    name = name[len("source/"):]
                mode = stat.S_IFMT(member.external_attr >> 16)
                if (name not in names or member.is_dir() or mode not in (0, stat.S_IFREG)
                        or member.orig_filename != member.filename or member.flag_bits & 1
                        or member.compress_type not in (ZIP_DEFLATED, ZIP_STORED)):
                    raise ValueError("The ZIP can contain only regular source files named in the mapping profile.")
                if name in seen:
                    raise ValueError("The ZIP repeats a source filename.")
                seen.add(name)
                total += member.file_size
                if total > MAX_EXPANSION:
                    raise ValueError("The source files exceed 300 MiB after expansion.")
                with archive.open(member) as source, (Path(folder) / name).open("xb") as target:
                    shutil.copyfileobj(source, target, length=64 * 1024)
            yield Path(folder)
    except BadZipFile as error:
        raise ValueError("The source file must be a standard ZIP archive.") from error


def _source_zip(files):
    if sum(len(content) for _, content in files) > MAX_UPLOAD:
        raise ValueError("The selected files exceed the 100 MiB upload limit.")
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in files:
            archive.writestr(name, content)
    return buffer.getvalue()


def _preview(payload, profile, unpack_exports):
    if profile is None:
        with unpack_exports(payload) as exports:
            return {"inspection": inspect_exports(exports), "prepared": None,
                    "fingerprints": intake_fingerprints(exports)}
    with unpack_company_files(payload, profile) as source, TemporaryDirectory(prefix="shipment-preview-") as temp:
        prepared = import_source(source, profile, temp)
        prepared.pop("bundle_path")
        exports = prepared.pop("exports_path")
        return {
            "prepared": prepared, "inspection": inspect_exports(exports),
            "fingerprints": intake_fingerprints(exports),
            "source_fields": inspect_source_fields(source, profile),
        }


def _start_review(payload, profile, unpack_exports):
    preview = _preview(payload, profile, unpack_exports)
    revision = preview["prepared"]["import_id"] if profile else sha256(payload).hexdigest()[:16]
    st.session_state["company_review"] = {
        **preview, "payload": payload, "profile": profile, "decisions": [],
        "revision": revision,
    }
    st.session_state.pop("company_mapping_trial", None)
    st.session_state.pop("company_ai_suggestions", None)


def _show_inputs(review):
    inspection = review["inspection"]
    prepared = review["prepared"]
    st.write("**Files received and mapped**")
    if prepared:
        st.dataframe([
            {"Source": item["source_file"], "Export": item["file"], "Original rows": item["input_rows"],
             "Mapped rows": item["output_rows"], "Rows withheld": item["input_rows"] - item["output_rows"],
             "Duplicate copies": item["exact_duplicates"], "Conflicting IDs": item["conflicting_ids"],
             "Status": item["status"]}
            for item in prepared["tables"].values()
        ], hide_index=True)
    else:
        st.dataframe(inspection["files"], hide_index=True)
    st.write("**Study period**", inspection["study_period"] or "Unknown")
    st.write("**Evidence cutoff**", inspection["data_cutoff"] or "Unknown")
    ref = inspection["tracking_creation_visibility_ref"]
    if ref:
        st.text(f"Tracking creation-time reference · {ref}")
    elif inspection["dataset_origin"] != "synthetic":
        st.caption("For historical tracking, supply event availability or a confirmed reference for using creation time.")


def _mapped_row_ref(prepared, table, row_number):
    ref = next((item for item in prepared["row_provenance"]
                if item["table"] == table and item["row"] == row_number), None)
    if ref:
        return prepared["exports"][ref["target_file"]][ref["target_row"] - 1], ref
    return None, None


def _show_row(review):
    prepared, profile = review["prepared"], review["profile"]
    if prepared is None:
        st.caption("These files already use the evaluator format. Review their rows in the issue register.")
        return
    st.write("**Original and mapped record**")
    table = st.selectbox("Source table", list(prepared["tables"]), key=f"intake_table:{review['revision']}")
    count = prepared["tables"][table]["input_rows"]
    if not count:
        st.info("Choose a table with supplied records to see the mapping.")
        return
    row_number = st.number_input("Original record number", min_value=1, max_value=count, step=1,
                                 key=f"intake_row:{review['revision']}:{table}")
    if st.button("Show source and mapped values", key=f"intake_show_row:{review['revision']}:{table}"):
        with unpack_company_files(review["payload"], profile) as source:
            original = preview_source_record(source, profile, table, row_number)
        mapped, ref = _mapped_row_ref(prepared, table, row_number)
        left, right = st.columns(2)
        left.write("**Source record**")
        left.json(original)
        right.write("**Evaluator record**")
        if ref:
            right.json(mapped)
            st.text(f"{ref['source_file']} record {ref['row']} → {ref['target_file']} record {ref['target_row']}")
        else:
            right.caption("This record was withheld. Check its position in the review register.")


def _trial_mapping(review, profile, unpack_exports, description):
    result = _preview(review["payload"], profile, unpack_exports)
    st.session_state["company_mapping_trial"] = {**result, "profile": profile, "description": description}


def _show_suggestions(review, unpack_exports):
    profile, prepared = review["profile"], review["prepared"]
    if profile is None:
        return
    st.subheader("Review suggested corrections")
    fields, issues = review["source_fields"], prepared["issues"]
    suggestions = suggest_paths(profile, issues, fields)
    if any(issue["code"] in {"missing_source_field", "unmapped_required_field"} for issue in issues):
        model = st.text_input("Local model for optional suggestions", value="qwen2.5:7b-instruct")
        if st.button("Ask local AI for mapping suggestions"):
            st.session_state["company_ai_suggestions"] = suggest_paths_with_ollama(profile, issues, fields, model)
        local = st.session_state.get("company_ai_suggestions", [])
        known = {(item["table"], item["field"], item["source_path"]) for item in suggestions}
        suggestions.extend(item for item in local if (item["table"], item["field"], item["source_path"]) not in known)
        st.caption("The local model receives field names and mapping information. Every suggestion needs reviewer approval.")
    dismissed = {(item.get("table"), item.get("field"), item.get("source_path"))
                 for item in review["decisions"] if item["decision"] in {"rejected", "clarification_requested"}}
    suggestions = [item for item in suggestions if (item["table"], item["field"], item["source_path"]) not in dismissed]
    if suggestions:
        selected = st.selectbox(
            "Suggested source field", range(len(suggestions)), key=f"intake_suggestion:{review['revision']}",
            format_func=lambda idx: f"{suggestions[idx]['table']}.{suggestions[idx]['field']} ← {suggestions[idx]['source_path']}",
        )
        suggestion = suggestions[selected]
        st.text(f"{suggestion['source_file']} record {suggestion['source_row']} · {suggestion['reason']}")
        with st.form("review_source_suggestion"):
            disposition = st.selectbox("Suggested correction decision", ["Preview correction", "Reject", "Request clarification"])
            reason = st.text_input("Reason for rejection or clarification", max_chars=300)
            submit = st.form_submit_button("Record suggestion decision")
        if submit:
            if disposition == "Preview correction":
                revised = apply_path_suggestion(profile, suggestion, fields)
                _trial_mapping(review, revised, unpack_exports, {**suggestion, "decision": "accepted"})
            elif reason.strip():
                action = "rejected" if disposition == "Reject" else "clarification_requested"
                review["decisions"].append({**suggestion, "decision": action, "review_note": reason.strip()})
                st.session_state.pop("company_mapping_trial", None)
                st.rerun()
            else:
                st.error("Give a source-based reason for the review decision.")
    else:
        st.caption("No source-field correction is proposed. Unresolved items stay in the review register.")

    st.caption("You can edit the profile to correct a field, category, timezone or owner-confirmed coverage.")
    with st.form(f"intake_mapping_editor:{review['revision']}"):
        editor = st.text_area("Mapping profile JSON", value=json.dumps(profile, ensure_ascii=False, indent=2), height=170)
        propose = st.form_submit_button("Preview mapping edit")
    if propose:
        edited = validate_profile(json.loads(editor))
        if edited == profile:
            st.info("The mapping matches the current draft.")
        else:
            if edited["profile_version"] == profile["profile_version"]:
                suffix = sha256(editor.encode("utf-8")).hexdigest()[:8]
                edited["profile_version"] = f"{profile['profile_version']}-{suffix}"
            _trial_mapping(review, edited, unpack_exports, {"decision": "edited_mapping", "origin": "reviewer"})

    trial = st.session_state.get("company_mapping_trial")
    if trial is None:
        return
    previous, revised = review["inspection"], trial["inspection"]
    st.write("**Trial conversion awaiting approval**")
    st.write(f"Preparation issues: {len(prepared['issues'])} → {len(trial['prepared']['issues'])}. "
             f"Export rows with detected issues: {previous['input_quality']['summary']['affected_rows']} → "
             f"{revised['input_quality']['summary']['affected_rows']}.")
    st.dataframe(revised["capabilities"], hide_index=True)
    detail = trial["description"]
    if detail.get("source_row"):
        original_row, _ = _mapped_row_ref(prepared, detail["table"], detail["source_row"])
        trial_row, _ = _mapped_row_ref(trial["prepared"], detail["table"], detail["source_row"])
        field = detail["field"]
        st.dataframe([{"Sample": f"{detail['source_file']} record {detail['source_row']}", "Mapped field": field,
                       "Current value": (original_row or {}).get(field),
                       "Trial value": (trial_row or {}).get(field)}], hide_index=True)
    before = review["profile"]["tables"]
    after = trial["profile"]["tables"]
    st.json({table: {"before": before.get(table), "after": after.get(table)} for table in before.keys() | after.keys()
             if before.get(table) != after.get(table)}, expanded=False)
    trial_id = trial["prepared"]["import_id"]
    reason = st.text_input("Evidence for the revised mapping", max_chars=300, key=f"intake_mapping_change_evidence:{trial_id}")
    left, right = st.columns(2)
    if left.button("Apply reviewed mapping", disabled=not reason.strip()):
        review["decisions"].append({**trial["description"], "review_note": reason.strip(),
                                    "profile_version": trial["profile"]["profile_version"]})
        review.update({key: trial[key] for key in ("profile", "prepared", "inspection", "source_fields", "fingerprints")})
        review["revision"] = trial["prepared"]["import_id"]
        st.session_state.pop("company_mapping_trial", None)
        st.session_state.pop("company_ai_suggestions", None)
        st.rerun()
    if right.button("Discard trial conversion"):
        st.session_state.pop("company_mapping_trial", None)
        st.rerun()


def _select_approved(exports):
    st.session_state["shipment_import_path"] = str(exports)
    st.session_state["shipment_source"] = "Approved company files"
    st.session_state["company_import_saved"] = True
    for name in ("company_review", "company_mapping_trial", "company_ai_suggestions",
                 "shipment_analysis", "shipment_downloads"):
        st.session_state.pop(name, None)
    st.rerun()


def _approve(review, unpack_exports, reviewer, note):
    reviewed = review["inspection"]
    if reviewed["blocking_reasons"] or st.session_state.get("company_mapping_trial"):
        raise ValueError("Resolve intake blockers and apply or discard the trial before approval.")
    limitations = review_limitations(reviewed)
    profile, payload = review["profile"], review["payload"]
    expected_files = review["fingerprints"]

    def approve(path):
        return approve_exports(path, IMPORTS, reviewer=reviewer, note=note, decisions=review["decisions"],
                               limitations=limitations, expected_files=expected_files)

    if profile is None:
        with unpack_exports(payload) as exports:
            return approve(exports)
    with unpack_company_files(payload, profile) as source:
        bundle = import_source(source, profile, IMPORTS)
        if bundle["import_id"] != review["prepared"]["import_id"]:
            raise ValueError("The mapped export changed. Review the new import before approving it.")
        return approve(bundle["exports_path"])


def render_company_import(unpack_exports):
    """Review and approve one version of the source records before analysis."""
    if st.session_state.pop("company_import_saved", False):
        st.success("Approved files selected. Choose Run evaluation to use the reviewed records.")
    with st.expander("Prepare company files", expanded=bool(st.session_state.get("company_review"))):
        st.caption("Preview the evidence, review any corrections, then approve the records for evaluation.")
        method = st.radio("Input format", ["Company files and mapping", "Evaluator exports ZIP"], horizontal=True,
                          key="company_intake_method")
        try:
            if method == "Company files and mapping":
                profile_file = st.file_uploader("Field mapping profile (JSON)", type=["json"], key="company_profile")
                source_file = st.file_uploader("Company source files (ZIP)", type=["zip"], key="company_source")
                loose = st.file_uploader("Or select the individual source files", type=["csv", "json", "jsonl"],
                                        accept_multiple_files=True, key="company_loose_source")
                if st.button("Preview company mapping"):
                    if profile_file is None or bool(source_file) == bool(loose):
                        raise ValueError("Select a profile and either one source ZIP or individual files.")
                    if profile_file.size > 2 * 1024**2:
                        raise ValueError("The mapping profile exceeds 2 MiB.")
                    profile = validate_profile(json.loads(profile_file.getvalue().decode("utf-8-sig")))
                    payload = source_file.getvalue() if source_file else _source_zip([(item.name, item.getvalue()) for item in loose])
                    _start_review(payload, profile, unpack_exports)
            else:
                archive = st.file_uploader("Exports ZIP to review", type=["zip"], key="intake_standard_exports")
                if st.button("Preview evaluator exports"):
                    if archive is None:
                        raise ValueError("Choose the exports ZIP to review.")
                    _start_review(archive.getvalue(), None, unpack_exports)
            if st.button("Preview synthetic company extract"):
                profile = json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8"))
                payload = _source_zip([(path.name, path.read_bytes()) for path in sorted((EXAMPLE / "source").iterdir())])
                _start_review(payload, profile, unpack_exports)
            saved = sorted(path.name for path in IMPORTS.glob("approved-*") if (path / "exports").is_dir())
            if saved:
                selected = st.selectbox("Previously approved import", saved)
                if st.button("Use approved import"):
                    exports = IMPORTS / selected / "exports"
                    read_approval(exports, required=True)
                    _select_approved(exports)
            review = st.session_state.get("company_review")
            if review is None:
                return
            files, mapping, issues, approval = st.tabs(["Files received", "Mapping preview", "Review issues", "Approval"])
            with files:
                _show_inputs(review)
            with mapping:
                _show_row(review)
            with issues:
                render_input_quality(review["inspection"], key_prefix="intake_quality", preparing=True)
                with st.expander("Field, time and link checks"):
                    st.dataframe(review["inspection"]["joins"], hide_index=True)
                    st.json(review["inspection"]["fields"], expanded=False)
                _show_suggestions(review, unpack_exports)
            with approval:
                st.write("**Evidence available before evaluation**")
                st.caption("This preview checks the supplied inputs. The evaluator reports verified metric coverage after approval.")
                st.dataframe(review["inspection"]["capabilities"], hide_index=True)
                if review["decisions"]:
                    st.dataframe(review["decisions"], hide_index=True)
                blocks = review["inspection"]["blocking_reasons"]
                for block in blocks:
                    st.error(block)
                if st.session_state.get("company_mapping_trial"):
                    st.info("Apply or discard the trial conversion before approval.")
                revision = review["revision"]
                reviewer = st.text_input("Reviewer name", max_chars=120, key=f"intake_reviewer:{revision}")
                note = st.text_area("Review basis and unresolved evidence", max_chars=2000, key=f"intake_note:{revision}")
                confirmed = st.checkbox("I reviewed the mapping, issue register and remaining limitations.",
                                        key=f"intake_confirmed:{revision}")
                if st.button("Approve for evaluation", type="primary", disabled=bool(blocks or not confirmed
                             or not reviewer.strip() or not note.strip() or st.session_state.get("company_mapping_trial"))):
                    published = _approve(review, unpack_exports, reviewer.strip(), note.strip())
                    _select_approved(published["exports_path"])
        except (ValueError, OSError, TypeError, OverflowError, KeyError) as error:
            st.error(str(error))
