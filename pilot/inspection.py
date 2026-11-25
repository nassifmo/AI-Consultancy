"""Run input checks without producing enquiry judgments, KPIs or costs."""

from pathlib import Path

from evaluator.economics import overlapping_work_ids
from evaluator.exports import load_exports
from evaluator.input_quality import assess_input_quality
from evaluator.readiness import _join_profiles, _table_profiles


def inspect_exports(path):
    """Describe a draft's inputs and which evidence needs a reviewer."""
    data = load_exports(Path(path), analysis=True)
    quality = assess_input_quality(data, (), overlapping_work_ids(data))
    notices = []
    fields = _table_profiles(data, notices)
    joins = _join_profiles(data, notices)
    period = data.metadata.get("study_period")
    valid_period = (isinstance(period, list) and len(period) == 2
                    and all(data.time("export_metadata", time) is not None for time in period)
                    and data.time("export_metadata", period[0]) < data.time("export_metadata", period[1]))
    blocks = []
    if data.cutoff is None or not valid_period:
        blocks.append("Supply an interpretable study period and evidence cutoff.")
    if not data.tables.get("enquiries"):
        blocks.append("Supply at least one identifiable enquiry in a readable export.")

    by_file = {item["table"]: item for item in fields}
    support_sources = {
        "Reply accuracy": ("enquiries", "responses", "shipments", "tracking_events"),
        "Handoff and follow-up": ("cases", "case_history", "responses"),
        "Active work": ("agent_work",),
        "Deployment comparisons": ("enquiries", "rollout_log"),
        "Cost totals": ("agent_work", "agent_runs", "ai_invoice"),
    }
    capabilities = []
    for question, tables in support_sources.items():
        absent = [table for table in tables if by_file[table]["status"] in {"missing", "invalid"}]
        partial = [table for table in tables if table not in absent and (
            by_file[table]["status"] == "partially_valid" or by_file[table]["source_completeness"] != "complete"
        )]
        capabilities.append({"assessment": question, "required_sources": ", ".join(tables),
                             "missing_or_invalid": ", ".join(absent),
                             "partial_or_unconfirmed": ", ".join(partial)})
    return {
        "files": list(data.files.values()), "study_period": period,
        "data_cutoff": data.cutoff.isoformat() if data.cutoff else None,
        "dataset_origin": data.metadata.get("dataset_origin", "unconfirmed"),
        "fields": fields, "joins": joins, "notices": notices, "input_quality": quality,
        "capabilities": capabilities, "blocking_reasons": blocks,
        "tracking_creation_visibility_ref": data.metadata.get("tracking_creation_visibility_ref"),
    }


def review_limitations(inspection):
    limitations = [f"{item['assessment']}: {status} from {item[field]}."
                   for item in inspection["capabilities"]
                   for field, status in (("missing_or_invalid", "unavailable source evidence"),
                                         ("partial_or_unconfirmed", "partial or unconfirmed coverage"))
                   if item[field]]
    counts = inspection["input_quality"]["summary"]
    if counts["affected_rows"]:
        limitations.append(f"{counts['affected_rows']} exported rows have detected issues. See the review register.")
    limitations.extend(inspection["input_quality"]["review_required"]["reasons"])
    return limitations
