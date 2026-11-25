"""Describe which evaluator outputs the supplied evidence can support."""

from collections import Counter
from math import isfinite

from .cohorts import ARMS, METHODS
from .economics import overlapping_work_ids
from .exports import ANALYSIS_TABLES, MEASURED_WORK_METHODS, TABLES
from .verification import Verifier


TIME_FIELDS = {
    "enquiries": ("received_at", "assignment_at"),
    "tracking_events": ("event_created_datetime", "event_available_datetime", "event_datetime"),
    "responses": ("sent_at",),
    "agent_runs": ("started_at", "ended_at"),
    "cases": ("opened_at", "closed_at"),
    "case_history": ("changed_at",),
    "agent_work": ("accepted_at", "closed_at"),
}
ASSIGNMENT_FIELDS = ("assigned_arm", "assignment_at", "root_enquiry_id", "contact_relation",
                     "assignment_unit_id", "assignment_method")
JOIN_FIELDS = (
    ("enquiries", "customer_id", "customers", False),
    ("shipments", "customer_id", "customers", False),
    ("tracking_events", "booking_ref", "shipments", False),
    ("responses", "enquiry_id", "enquiries", False),
    ("responses", "case_id", "cases", True),
    ("agent_runs", "enquiry_id", "enquiries", False),
    ("cases", "enquiry_id", "enquiries", False),
    ("case_history", "case_id", "cases", False),
    ("enquiries", "root_enquiry_id", "enquiries", False),
    ("enquiries", "related_enquiry_id", "enquiries", True),
)
EXTRA_FIELDS = {
    "enquiries": ("stated_reference", "customer_message", *ASSIGNMENT_FIELDS),
    "shipments": ("container_refs", "destination", "planned_arrival"),
    "responses": ("shipment_reference", "message_text", "claimed_status", "claimed_eta"),
    "tracking_events": ("container_ref", "location"),
    "agent_runs": ("agent_version", "tokens_in", "tokens_out", "voice_seconds"),
    "agent_work": ("enquiry_id", "case_id", "active_seconds", "measurement_method"),
}


def _present(value):
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


def _coverage(count, total):
    return count / total if total else None


def _status(count, total):
    return "unavailable" if not count else "ready" if count == total else "partial"


def _declared_completeness(data, table, filename):
    declarations = data.metadata.get("source_completeness", {})
    value = declarations.get(table, declarations.get(filename)) if isinstance(declarations, dict) else None
    return value if isinstance(value, str) and value in {"complete", "partial", "unknown"} else "unspecified"


def _notice(code, source, count, detail, action):
    return {"code": code, "source": source, "count": count, "detail": detail, "action": action}


def _table_profiles(data, issues):
    profiles = []
    for table, (filename, required) in (TABLES | ANALYSIS_TABLES).items():
        rows = data.tables.get(table, ())
        fields = []
        for name in dict.fromkeys((*required, *EXTRA_FIELDS.get(table, ()), *TIME_FIELDS.get(table, ()))):
            present = sum(_present(row.get(name)) for row in rows)
            valid_time = None
            earliest = latest = None
            if name in TIME_FIELDS.get(table, ()):
                instants = [when for row in rows if (when := data.time(table, row.get(name))) is not None]
                valid_time = len(instants)
                earliest = min(instants).isoformat() if instants else None
                latest = max(instants).isoformat() if instants else None
                invalid = present - valid_time
                if invalid:
                    issues.append(_notice("uninterpretable_timestamp", f"{filename}.{name}", invalid,
                                          "Some timestamps have no unambiguous instant.",
                                          "Supply the original UTC offset or a documented source time zone. Resolve ambiguous local times."))
            fields.append({"field": name, "present": present, "total": len(rows),
                           "coverage": _coverage(present, len(rows)), "required_by_loader": name in required,
                           "valid_timestamps": valid_time, "earliest": earliest, "latest": latest})
        file_info = data.files.get(filename, {})
        profiles.append({"table": table, "filename": filename, "status": file_info.get("status", "missing"),
                         "rows": len(rows), "source_rows": file_info.get("row_count"),
                         "conflicting_or_rejected_rows": len(data.conflicts.get(table, ())),
                         "loader_complete": table in data.available,
                         "source_completeness": _declared_completeness(data, table, filename), "fields": fields})
    return profiles


def _join_profiles(data, issues):
    tables = data.tables
    ids = {table: {row.get(key) for row in tables.get(table, ()) if _present(row.get(key))}
           for table, key in (("customers", "customer_id"), ("shipments", "booking_ref"),
                              ("enquiries", "enquiry_id"), ("cases", "case_id"))}
    joins = []
    for table, key, target, optional in JOIN_FIELDS:
        rows = [row for row in tables.get(table, ()) if not optional or _present(row.get(key))]
        matched = sum(row.get(key) in ids[target] for row in rows)
        missing = sum(not _present(row.get(key)) for row in rows)
        orphaned = len(rows) - matched - missing
        filename = (TABLES | ANALYSIS_TABLES)[table][0]
        source = f"{filename}.{key}"
        joins.append({"source": source, "target": (TABLES | ANALYSIS_TABLES)[target][0],
                      "records": len(rows), "matched": matched, "missing": missing, "orphaned": orphaned,
                      "coverage": _coverage(matched, len(rows))})
        if orphaned or missing:
            issues.append(_notice("unlinked_records", source, orphaned + missing,
                                  "Some source records lack a matching identifier in the target export.",
                                  "Confirm identifier mapping and extraction windows. Preserve unresolved links for review."))
    return joins


def _capability(identifier, title, assessable, total, sources, reason, next_steps, *, force_partial=False):
    status = _status(assessable, total)
    if force_partial and status == "ready":
        status = "partial"
    return {"id": identifier, "title": title, "status": status, "assessable": assessable, "total": total,
            "coverage": _coverage(assessable, total), "source_files": sources, "reason": reason,
            "next_steps": next_steps}


def _work_diagnostics(data, issues):
    methods = Counter()
    invalid = 0
    unlinked = 0
    enquiries = {row.get("enquiry_id") for row in data.tables.get("enquiries", ())}
    cases = {row.get("case_id"): row.get("enquiry_id") for row in data.tables.get("cases", ())}
    for row in data.tables.get("agent_work", ()):
        method = row.get("measurement_method")
        methods[method if method in MEASURED_WORK_METHODS or method == "estimated" else "unrecognized"] += 1
        start = data.time("agent_work", row.get("accepted_at"))
        end = data.time("agent_work", row.get("closed_at"))
        try:
            active = float(row.get("active_seconds"))
            valid = isfinite(active) and active >= 0 and start is not None and end is not None and start <= end
            valid = valid and active <= (end - start).total_seconds()
        except (TypeError, ValueError):
            valid = False
        invalid += not valid
        enquiry = row.get("enquiry_id")
        case = row.get("case_id")
        linked = enquiry in enquiries if _present(enquiry) else cases.get(case) in enquiries
        if _present(enquiry) and _present(case):
            linked = linked and cases.get(case) == enquiry
        unlinked += not linked
    overlap_count = len(overlapping_work_ids(data))
    if invalid:
        issues.append(_notice("active_work_unverified", "agent_work.csv", invalid,
                              "Active duration is missing or inconsistent with the work interval.",
                              "Provide observed active work or a labelled representative estimate. Ticket elapsed time does not establish effort."))
    if unlinked:
        issues.append(_notice("work_link_unverified", "agent_work.csv", unlinked,
                              "The work record has no consistent link to an enquiry or its case.",
                              "Map both case and enquiry identifiers and resolve conflicting work links."))
    if overlap_count:
        issues.append(_notice("overlapping_active_work", "agent_work.csv", overlap_count,
                              "A worker has overlapping intervals across the supplied work records.",
                              "Confirm the source's concurrency and duration semantics before adding the durations."))
    return {"measurement_methods": dict(sorted(methods.items())), "invalid_durations": invalid,
            "unlinked_records": unlinked, "overlapping_records": overlap_count}


def _assignment_count(data):
    rows = data.tables.get("enquiries", ())
    valid = 0
    arms = set()
    for row in rows:
        at = data.time("enquiries", row.get("received_at"))
        assigned = data.time("enquiries", row.get("assignment_at"))
        root = row.get("root_enquiry_id")
        relation = row.get("contact_relation")
        consistent = (relation in {"initial", "new_request"} and root == row.get("enquiry_id")) or (
            relation == "continuation" and bool(root) and bool(row.get("related_enquiry_id")))
        if (all(_present(row.get(key)) for key in ASSIGNMENT_FIELDS) and consistent
                and row.get("assigned_arm") in ARMS and row.get("assignment_method") in METHODS
                and at is not None and assigned is not None and assigned <= at):
            valid += 1
            arms.add(row["assigned_arm"])
    return valid, len(rows), sorted(arms)


def _chronology_notices(data):
    receipts = {row["enquiry_id"]: data.time("enquiries", row.get("received_at"))
                for row in data.tables.get("enquiries", ())}
    notices = []
    for table, time_key in (("responses", "sent_at"), ("cases", "opened_at"), ("agent_runs", "started_at")):
        early = 0
        reversed_runs = 0
        for row in data.tables.get(table, ()):
            at = data.time(table, row.get(time_key))
            receipt = receipts.get(row.get("enquiry_id"))
            early += at is not None and receipt is not None and at < receipt
            if table == "agent_runs":
                end = data.time(table, row.get("ended_at"))
                reversed_runs += at is not None and end is not None and end < at
        if early:
            notices.append(_notice("event_before_enquiry", TABLES[table][0], early,
                                   "An action timestamp precedes the linked customer request.",
                                   "Check the time basis, join keys and whether the action belongs to an earlier contact."))
        if reversed_runs:
            notices.append(_notice("reversed_run_interval", TABLES[table][0], reversed_runs,
                                   "An AI run ends before its recorded start.",
                                   "Confirm the API clock and export timestamp mapping."))
    return notices


def assess_readiness(data, policy, *, verified=None, episodes=None, ledger=None, diagnostics=None):
    """Return evidence capabilities and fixable data gaps, preserving unknowns.

    Ready describes computability on the supplied records. Logging completeness,
    company policy and independent outcome accuracy require pilot validation.
    Existing analysis results may be supplied to avoid duplicate verification.
    """
    issues = []
    tables = _table_profiles(data, issues)
    joins = _join_profiles(data, issues)
    work = _work_diagnostics(data, issues)
    issues.extend(_chronology_notices(data))
    preparation = data.metadata.get("preparation_issue_counts", {})
    if isinstance(preparation, dict) and isinstance(preparation.get("by_table"), dict):
        for name, count in preparation["by_table"].items():
            if type(count) is int and count > 0:
                issues.append(_notice("source_preparation_loss", name, count,
                                      "Source preparation reported missing, rejected or unconvertible evidence.",
                                      "Review the retained raw source and preparation record before declaring complete coverage."))
    if verified is None:
        verifier = Verifier(data, policy, excluded_work_ids=overlapping_work_ids(data))
        verified = [verifier.evaluate(row) for row in verifier.enquiries]
    verified = [row for row in verified if row.get("in_scope")]
    total = len(verified)
    factual = sum(type((row.get("verification", {}).get("initial_reply") or {}).get("matches_record")) is bool
                  for row in verified)
    outcomes = sum(row.get("outcome", {}).get("state") not in {None, "unknown"} for row in verified)
    effort = sum(row.get("verification", {}).get("human_work", {}).get("active_seconds") is not None
                 for row in verified)
    timing = sum(data.time("responses", (row.get("verification", {}).get("initial_reply") or {}).get("sent_at"))
                 is not None for row in verified)
    actions = [grade for row in verified for name, grade in row.get("criteria", {}).items()
               if name in {"initial_escalation", "escalation_deadline", "follow_up_deadline"}
               and grade.get("status") != "not_applicable"]
    checked_actions = sum(grade.get("status") not in {None, "unknown"} for grade in actions)
    valid_assignments, assignment_total, arms = _assignment_count(data)
    comparison_status = (diagnostics or {}).get("comparison_status")
    eligible = [row for row in episodes or () if row.get("eligible")]
    costs = (ledger or {}).get("per_episode", {})
    complete_costs = sum(costs.get(row["root_enquiry_id"], {}).get("complete") is True for row in eligible)
    capabilities = [
        _capability("first_answer_verification", "First-answer accuracy", factual, total,
                    ["enquiries.csv", "shipments.csv", "tracking_events.json", "responses.csv", "agent_runs.json"],
                    "Answers are checked against the authorized shipment and records published by reply time.",
                    ["Map customer accounts, exact shipment/container references, historical event publication times and the sent reply."]),
        _capability("service_outcomes", "Service outcome verification", outcomes, total,
                    ["enquiries.csv", "responses.csv", "cases.csv", "case_history.csv"],
                    "Counts use the verifier's latest-observed outcome for each in-scope enquiry.",
                    ["Supply case history, closure reasons, customer follow-ups and required actions through a stated cutoff."]),
        _capability("required_actions", "Escalation and follow-up checks", checked_actions, len(actions),
                    ["agent_runs.json", "cases.csv", "case_history.csv", "responses.csv"],
                    "An action is assessable only when its applicability and supporting events can be checked.",
                    ["Map action types and timestamps. Confirm the client's escalation and follow-up rules."]),
        _capability("active_human_work", "Human active-work calculation", effort, total,
                    ["agent_work.csv", "cases.csv", "responses.csv"],
                    "Validated active durations and explicit handling evidence support effort. Measurement methods are shown separately.",
                    ["Check timer coverage, paused work, concurrent tasks and after-contact work with the source owner."],
                    force_partial=bool(work["invalid_durations"] or work["unlinked_records"] or work["overlapping_records"]
                                       or work["measurement_methods"].get("estimated") or work["measurement_methods"].get("unrecognized"))),
        _capability("first_answer_timing", "Time to first substantive answer", timing, total,
                    ["enquiries.csv", "responses.csv"],
                    "The first qualifying reply and intake timestamps are available at enquiry level. Group timing is not yet aggregated.",
                    ["Confirm customer-visible send time and a common time basis. Define the substantive-response rule."]),
        _capability("comparison_assignment", "Assigned-policy comparison", valid_assignments, assignment_total,
                    ["enquiries.csv", "rollout_log.csv", "export_metadata.json"],
                    f"Recorded allocation covers {valid_assignments} contacts across {len(arms)} handling policies. Design status is {comparison_status or 'not yet assessed'}.",
                    ["Provide allocation recorded before handling, root/follow-up links, rollout rules and a comparable follow-up period."],
                    force_partial=comparison_status != "randomized_assignment" or len(arms) < 2),
        _capability("scoped_costs", "Scoped resource cost calculation", complete_costs, len(eligible),
                    ["agent_work.csv", "agent_runs.json", "ai_invoice.csv", "cost_parameters.json"],
                    "Complete costs require reconciled consumption, applicable rates, a common currency and explicit shared-cost allocations.",
                    ["Map usage units and effective vendor rates, labour cost and invoices. Confirm the scope with finance."]),
    ]
    if data.cutoff is None:
        issues.append(_notice("missing_observation_cutoff", "export_metadata.json.data_cutoff", 1,
                              "The end of observable evidence is unknown.",
                              "Provide the source extraction cutoff with an explicit time zone."))
    if valid_assignments < assignment_total:
        issues.append(_notice("incomplete_assignment", "enquiries.csv", assignment_total - valid_assignments,
                              "Handling allocation or root/continuation evidence is incomplete.",
                              "Obtain the allocation log and explicit contact relationships. Preserve unknown allocation."))
    by_filename = {item["filename"]: item for item in tables}
    for capability in capabilities:
        missing_confirmation = [name for name in capability["source_files"] if name in by_filename
                                and by_filename[name]["source_completeness"] != "complete"]
        capability["sources_needing_completeness_confirmation"] = missing_confirmation
        if missing_confirmation and capability["status"] == "ready":
            capability["status"] = "partial"
            capability["next_steps"].append("Confirm that the source covers the full declared period and population, including failures and deleted or unlogged events.")
    return {"schema_version": "1.0", "scope": "Supplied-evidence computability",
            "validation_note": "Validate source completeness, permissions, interpretation accuracy and company rules against an authorized sample before a pilot conclusion.",
            "capabilities": capabilities, "tables": tables, "joins": joins, "issues": issues,
            "preparation_issue_counts": preparation,
            "work_measurement": work, "comparison_status": comparison_status,
            "loader_issues": list(data.issues)}
