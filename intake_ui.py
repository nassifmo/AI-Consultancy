"""Prepare and inspect local company extracts before running the evaluator."""

from contextlib import contextmanager
from io import BytesIO
import json
from pathlib import Path
import shutil
import stat
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile

import streamlit as st

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


def _summary(prepared):
    st.write("**Mapping preview**")
    st.dataframe([
        {"Records": name.replace("_", " "), "Source file": summary["source_file"],
         "Input rows": summary["input_rows"], "Mapped rows": summary["output_rows"],
         "Duplicates": summary["exact_duplicates"], "Conflicting IDs": summary["conflicting_ids"],
         "Status": summary["status"]}
        for name, summary in prepared["tables"].items()
    ], hide_index=True)
    if prepared["issues"]:
        st.write("**Fields to review**")
        st.dataframe(prepared["issues"][:100], hide_index=True)
        st.caption(f"Showing {min(100, len(prepared['issues']))} of {len(prepared['issues'])} preparation issues.")
    else:
        st.write("The mapped source files passed preparation checks.")
    completeness = prepared["exports"]["export_metadata.json"]["source_completeness"]
    unconfirmed = [name.replace("_", " ") for name, state in completeness.items()
                   if name in prepared["tables"] and state != "complete"]
    if unconfirmed:
        st.caption("Source coverage still needs confirmation for " + ", ".join(unconfirmed) + ".")
    with st.expander("Source files and traceability"):
        st.dataframe(prepared["source_manifest"], hide_index=True)
        st.dataframe(prepared["row_provenance"][:50], hide_index=True)
        st.caption("The saved import keeps the original extracts, mapping version, and source row references beside its normalized exports.")


def render_company_import():
    """Keep source preparation local and independent of enquiry verification."""
    if st.session_state.pop("company_import_saved", False):
        st.success("Prepared files selected. Choose Run evaluation to check the evidence.")
    with st.expander("Prepare company files"):
        st.write("Bring the company's CSV, JSON, or JSONL extracts and a mapping profile. Preview the fields, then "
                 "save a local import and choose Run evaluation to see what the records support.")
        profile_file = st.file_uploader("Field mapping profile (JSON)", type=["json"], key="company_profile")
        source_file = st.file_uploader("Company source files (ZIP)", type=["zip"], key="company_source")
        if st.button("Preview company mapping"):
            st.session_state.pop("company_preview", None)
            try:
                if profile_file is None or source_file is None:
                    raise ValueError("Select the mapping profile and source ZIP for the preview.")
                if profile_file.size > 2 * 1024**2:
                    raise ValueError("The mapping profile exceeds 2 MiB.")
                profile = validate_profile(json.loads(profile_file.getvalue().decode("utf-8-sig")))
                payload = source_file.getvalue()
                with unpack_company_files(payload, profile) as source:
                    prepared = import_source(source, profile)
                st.session_state["company_preview"] = (prepared, profile, payload)
            except (ValueError, OSError, TypeError, OverflowError) as error:
                st.error(str(error))
        if st.button("Preview synthetic company extract"):
            try:
                profile = json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8"))
                source = EXAMPLE / "source"
                prepared = import_source(source, profile)
                buffer = BytesIO()
                with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
                    for path in sorted(source.iterdir()):
                        archive.writestr(f"source/{path.name}", path.read_bytes())
                st.session_state["company_preview"] = (prepared, profile, buffer.getvalue())
            except (ValueError, OSError, TypeError, OverflowError) as error:
                st.error(str(error))
        preview = st.session_state.get("company_preview")
        if preview:
            prepared, profile, payload = preview
            _summary(prepared)
            if st.button("Save and use prepared files"):
                try:
                    with unpack_company_files(payload, profile) as source:
                        published = import_source(source, profile, IMPORTS)
                    st.session_state["shipment_import_path"] = published["exports_path"]
                    st.session_state["shipment_import_id"] = published["import_id"]
                    st.session_state["shipment_source"] = "Prepared company files"
                    st.session_state["company_import_saved"] = True
                    st.session_state.pop("company_preview", None)
                    st.session_state.pop("shipment_analysis", None)
                    st.session_state.pop("shipment_downloads", None)
                    st.rerun()
                except (ValueError, OSError, TypeError, OverflowError) as error:
                    st.error(str(error))
        st.caption("Source files stay on this PC. Confirm the sample, data retention, and the meaning of each field with the company before using live records.")
