"""Count affected delivered rows once and retain references to review them."""

from collections import defaultdict
from math import isfinite

from .exports import ANALYSIS_KEYS, ANALYSIS_TABLES, MEASURED_WORK_METHODS, TABLES
from .readiness import JOIN_FIELDS, TIME_FIELDS, _present


DEFINITIONS = TABLES | ANALYSIS_TABLES
CRITICAL_SOURCES = {"shipments", "tracking_events", "responses", "agent_runs", "cases", "case_history"}
DISPUTES = {"conflicting_record_id", "malformed_row", "missing_record_id", "malformed_steps"}
METER_FIELDS = {"tokens_in", "tokens_out", "voice_seconds", "model_rate", "input_tokens", "output_tokens"}
STAMP = {"responses": "sent_at", "tracking_events": "event_created_datetime", "agent_runs": "started_at",
         "cases": "opened_at", "case_history": "changed_at"}
MESSAGES = {
    "exact_duplicate": "A repeated copy of the same record. It is not counted twice.",
    "conflicting_record_id": "The same ID has different values. Neither version is used as verified evidence.",
    "malformed_row": "A row could not be accepted as a valid record.",
    "missing_record_id": "The row lacks the ID needed to identify or link it.",
    "missing_required_field": "A required value is missing.",
    "malformed_steps": "The run does not contain a valid sequence of tool records.",
    "uninterpretable_timestamp": "The timestamp does not establish an unambiguous instant.",
    "missing_link": "A required link is missing.",
    "unmatched_link": "No matching record was found in the target export.",
    "unverified_enquiry_link": "The case could not be reliably linked to an enquiry.",
    "event_before_enquiry": "The action time precedes the linked enquiry.",
    "reversed_run_interval": "The run end is earlier than its start.",
    "active_work_unverified": "The logged active duration is missing or inconsistent with its work interval.",
    "work_method_unverified": "This timing method cannot establish measured active work. The duration is excluded from measured effort and labour cost.",
    "work_link_unverified": "The work record has no consistent enquiry or case link.",
    "overlapping_active_work": "Logged intervals overlap for the same worker.",
    "missing_file": "No file was provided. The number of missing rows is unknown.",
    "invalid_file": "The file could not be read as a valid input. The affected row count is unknown.",
    "invalid_cutoff": "The observation cutoff could not be verified.",
    "source_partial": "The evidence source was marked partial. Omitted rows cannot be counted from the export.",
    "source_unconfirmed": "Completeness of this evidence source has not been confirmed.",
    "source_unavailable": "The source file could not be prepared.",
    "malformed_source_row": "This source row could not be mapped to an export record.",
    "missing_source_field": "A source field required by the mapping is absent.",
    "conversion_failed": "A source value could not be converted using the mapping.",
    "unmapped_required_field": "No source field is mapped to a required export field.",
    "missing_required_value": "The mapped record has no value for this required field.",
}


def _identity(table, row):
    id_key = DEFINITIONS[table][1][0]
    normal = row.get(id_key)
    if not isinstance(normal, str) or not normal.strip():
        return None
    return "|".join(str(row.get(key) or "") for key in ANALYSIS_KEYS[table]) if table in ANALYSIS_KEYS else normal


def _text(value):
    return value if isinstance(value, str) and value.strip() else None


def _source_info(metadata, table):
    source = metadata.get("quality_preparation")
    original = source.get(table) if isinstance(source, dict) else None
    if not isinstance(original, dict):
        return None, None, []
    filename = _text(original.get("source_file"))
    total = original.get("input_rows")
    if not filename or "/" in filename or "\\" in filename:
        return None, None, []
    if type(total) is not int or not 0 <= total <= 250_000:
        total = None
    diagnostics = original.get("issues")
    if not isinstance(diagnostics, list):
        return None, None, []
    return filename, total, [d for d in diagnostics if isinstance(d, dict)]


def _ordinal(item, total):
    n = item.get("row_number")
    return n if type(n) is int and total is not None and 1 <= n <= total else None


def assess_input_quality(data, verified, overlap_ids, episodes=()):
    """Fractions describe supplied rows, not how much real history was captured."""
    issues, files = [], []
    population_rows, critical_rows, affected_enquiries = set(), set(), set()
    outcome = {row["enquiry_id"]: row.get("initial_failure") for row in verified}
    outcome.update({row["root_enquiry_id"]: row.get("initial_failure") for row in episodes if row["eligible"]})
    mappings = data.metadata.get("source_completeness")
    mappings = mappings if isinstance(mappings, dict) else {}
    raw_enquiries = data.input_rows.get("enquiries", ())
    enquiries = {row["enquiry_id"]: row for row in data.tables.get("enquiries", ())}
    known = {table: {row[DEFINITIONS[table][1][0]] for row in data.tables.get(table, ())}
             for table in ("customers", "shipments", "enquiries", "cases")}
    cases = defaultdict(set)
    shipment_refs = defaultdict(set)
    booking_aliases = defaultdict(set)
    for table in ("shipments", "cases"):
        for row in data.input_rows.get(table, ()):
            if not isinstance(row, dict):
                continue
            if table == "cases":
                case, enquiry = _text(row.get("case_id")), _text(row.get("enquiry_id"))
                if case and enquiry:
                    cases[case].add(enquiry)
            elif booking := _text(row.get("booking_ref")):
                aliases = [booking, _text(row.get("bl_ref")), *str(row.get("container_refs") or "").split(";")]
                booking_aliases[booking].update(a.strip().upper() for a in aliases if a and a.strip())
    for row in raw_enquiries:
        if isinstance(row, dict) and (identifier := _text(row.get("enquiry_id"))):
            for key in ("stated_reference", "confirmed_reference"):
                ref = _text(row.get(key))
                if ref:
                    for alias in ref.split("/"):
                        shipment_refs[alias.strip().upper()].add(identifier)
    by_booking = {booking: set().union(*(shipment_refs[alias] for alias in aliases))
                  for booking, aliases in booking_aliases.items()}
    joins = defaultdict(list)
    for table, key, target, optional in JOIN_FIELDS:
        joins[table].append((key, target, optional))
    bad_case_links = {i.get("ref", "") for i in data.issues if i.get("code") == "unverified_enquiry_link"}
    impact_for_table = {"enquiries": "Enquiry count and comparison",
                        "agent_work": "Human effort and cost", "ai_invoice": "Cost",
                        "staffing": "Cost context", "rollout_log": "Comparison design",
                        "cost_parameters": "Cost", "export_metadata": "Time and scope",
                        "customers": "Account and enquiry links"}
    clocks = {"responses": "sent_at", "cases": "opened_at", "agent_runs": "started_at"}

    def linked(table, row):
        if not isinstance(row, dict):
            return set()
        links = {key for name in ("enquiry_id", "root_enquiry_id") if (key := _text(row.get(name)))}
        if case := _text(row.get("case_id")):
            links.update(cases[case])
        if booking := _text(row.get("booking_ref")):
            links.update(by_booking.get(booking, ()))
        return links

    for table in (*DEFINITIONS, "cost_parameters", "export_metadata"):
        filename = DEFINITIONS[table][0] if table in DEFINITIONS else table + ".json"
        metadata = data.files.get(filename, {})
        row_count = metadata.get("row_count") if table in DEFINITIONS else None
        status = metadata.get("status", "missing")
        declaration = mappings.get(table)
        completeness = declaration if declaration in ("complete", "partial", "unknown") else "unspecified"
        rows = data.input_rows.get(table, ())
        duplicates, conflicts, affected = set(), set(), set()
        counts_before = len(issues)
        same_id = defaultdict(list)
        origin, source_total, diagnostics = _source_info(data.metadata, table)
        dropped = {n for d in diagnostics if d.get("kind") == "malformed_source_row"
                   and (n := _ordinal(d, source_total)) is not None}
        source_numbers = ([n for n in range(1, source_total + 1) if n not in dropped]
                          if source_total is not None and source_total - len(dropped) == row_count and dropped else None)
        source_aligned = (data.metadata.get("preparation_id") and source_total is not None
                          and source_total - len(dropped) == row_count)

        def add(kind, number=None, row=None, identifier=None, key=None, meter_only=False):
            impact = impact_for_table.get(table, "Answer or case verification")
            if meter_only:
                impact = "Cost"
            if kind == "exact_duplicate":
                impact = "Counted once"
            elif kind in {"missing_file", "invalid_file", "source_partial", "source_unconfirmed"}:
                impact = "Evidence coverage"
            enquiries_for_row = linked(table, row)
            if number is not None:
                affected.add(number)
            if kind in DISPUTES and table == "enquiries":
                population_rows.add((filename, number))
                affected_enquiries.update(enquiries_for_row)
            if kind in DISPUTES and table in CRITICAL_SOURCES and not meter_only:
                stamp = STAMP.get(table)
                at = data.time(table, row.get(stamp)) if stamp and isinstance(row, dict) else None
                if data.cutoff is None or at is None or at <= data.cutoff:
                    if not enquiries_for_row or any(outcome.get(i) is not True for i in enquiries_for_row):
                        critical_rows.add((filename, number))
                        affected_enquiries.update(enquiries_for_row)
            source_number = source_numbers[number - 1] if source_numbers is not None and number is not None else number
            source_ref = (f"{origin} · record {source_number} (original extract)" if source_aligned and number
                          else f"{filename} · record {number}" if number is not None else filename)
            issues.append({"table": table, "filename": filename, "kind": kind, "record_id": identifier,
                           "row_number": number, "field": key, "detail": MESSAGES[kind], "impact": impact,
                           "enquiry_ids": sorted(enquiries_for_row),
                           "source_ref": source_ref,
                           "basis": "exported_records"})

        if status in {"missing", "invalid"}:
            add(f"{status}_file")
        elif table == "export_metadata" and data.cutoff is None:
            add("invalid_cutoff")
        elif table in DEFINITIONS and completeness in {"partial", "unknown", "unspecified"}:
            add("source_partial" if completeness == "partial" else "source_unconfirmed")

        for number, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            identifier = _identity(table, row)
            if identifier is not None:
                same_id[identifier].append((number, row))
            for key in TIME_FIELDS.get(table, ()):
                if _present(row.get(key)) and data.time(table, row.get(key)) is None:
                    add("uninterpretable_timestamp", number, row, identifier, key)
            for key, target, optional in joins[table]:
                value = row.get(key)
                if not _present(value):
                    if not optional:
                        add("missing_link", number, row, identifier, key)
                elif _text(value) is None or value not in known[target]:
                    add("unmatched_link", number, row, identifier, key)
            if table in clocks:
                clock = clocks[table]
                at = data.time(table, row.get(clock))
                receipt = data.time("enquiries", enquiries.get(_text(row.get("enquiry_id")), {}).get("received_at"))
                if at is not None and receipt is not None and at < receipt:
                    add("event_before_enquiry", number, row, identifier, clock)
                if table == "agent_runs":
                    end = data.time(table, row.get("ended_at"))
                    if at is not None and end is not None and end < at:
                        add("reversed_run_interval", number, row, identifier, "ended_at")
                if table == "cases" and f"{filename}#{identifier}" in bad_case_links:
                    add("unverified_enquiry_link", number, row, identifier, "enquiry_id")
            if table == "agent_work":
                if row.get("measurement_method") not in MEASURED_WORK_METHODS:
                    add("work_method_unverified", number, row, identifier, "measurement_method")
                start, end = (data.time(table, row.get(key)) for key in ("accepted_at", "closed_at"))
                try:
                    active = float(row.get("active_seconds"))
                    valid = start is not None and end is not None and isfinite(active) and 0 <= active <= (end - start).total_seconds()
                except (TypeError, ValueError):
                    valid = False
                if not valid:
                    add("active_work_unverified", number, row, identifier, "active_seconds")
                enquiry, case = _text(row.get("enquiry_id")), _text(row.get("case_id"))
                matched = cases.get(case, set())
                if not (enquiry in known["enquiries"] if enquiry is not None else bool(matched & known["enquiries"])) or (
                    enquiry is not None and case is not None and enquiry not in matched
                ):
                    add("work_link_unverified", number, row, identifier)
                if identifier in overlap_ids:
                    add("overlapping_active_work", number, row, identifier)

        for identifier, versions in same_id.items():
            first = versions[0][1]
            if any(row != first for _, row in versions[1:]):
                conflicts.add(identifier)
                absent = object()
                fields = sorted({key for _, row in versions[1:] for key in row.keys() | first.keys()
                                 if isinstance(key, str) and row.get(key, absent) != first.get(key, absent)})
                for number, row in versions:
                    add("conflicting_record_id", number, row, identifier, ", ".join(fields) or None,
                        meter_only=table == "agent_runs" and bool(fields) and set(fields) <= METER_FIELDS)
        for issue in data.row_issues.get(table, ()):
            row_number = issue["row_number"]
            if issue["kind"] == "exact_duplicate":
                duplicates.add(row_number)
            add(issue["kind"], row_number, rows[row_number - 1], issue["record_id"],
                ", ".join(issue["fields"]) or None)
        files.append({"table": table, "filename": filename, "status": status, "input_rows": row_count,
                      "affected_rows": len(affected) if row_count is not None else None,
                      "affected_fraction": len(affected) / row_count if row_count else None,
                      "duplicate_rows": len(duplicates) if row_count is not None else None,
                      "conflicting_ids": len(conflicts), "issue_count": len(issues) - counts_before,
                      "source_completeness": completeness})
    preparation = _preparation_view(data, issues)
    for issue in issues:
        if issue["basis"] != "source_records" or issue["kind"] != "malformed_source_row":
            continue
        if issue["table"] == "enquiries":
            population_rows.add((issue["source_ref"], issue["row_number"]))
        elif issue["table"] in CRITICAL_SOURCES:
            critical_rows.add((issue["source_ref"], issue["row_number"]))
    problem_total = sum(f["affected_rows"] or 0 for f in files)
    physical_total = sum(f["input_rows"] or 0 for f in files)
    reasons = []
    if population_rows:
        reasons.append("Some enquiry rows cannot establish which requests belong in the comparison.")
    if critical_rows:
        reasons.append("Disputed or rejected evidence may change a critical answer or action check.")
    summary = {"input_rows": physical_total, "affected_rows": problem_total,
               "affected_fraction": problem_total / physical_total if physical_total else None,
               "duplicate_rows": sum(f["duplicate_rows"] or 0 for f in files),
               "conflict_ids": sum(f["conflicting_ids"] for f in files),
               "files_unavailable": sum(f["status"] in {"missing", "invalid"} for f in files),
               "files_partial": sum(f["status"] == "partially_valid" or
                                    (f["status"] == "loaded" and f["source_completeness"] == "partial") for f in files)}
    return {"basis": "exported_records", "files": files, "issues": issues, "summary": summary,
            "preparation": preparation, "review_required": {
                "required": bool(reasons), "population_issues": len(population_rows),
                "unresolved_critical_issues": len(critical_rows), "affected_enquiry_ids": sorted(affected_enquiries),
                "reasons": reasons,
            }}


def _preparation_view(data, issues):
    """Include only diagnostic coordinates, never values from raw source fields."""
    source = data.metadata.get("quality_preparation")
    if not isinstance(source, dict):
        return []
    profiles = []
    for table in DEFINITIONS:
        source_file, total, diagnostics = _source_info(data.metadata, table)
        if not source_file:
            continue
        affected = set()
        for d in diagnostics:
            if not isinstance(d, dict) or not isinstance(d.get("kind"), str) or d["kind"] not in MESSAGES:
                continue
            num = _ordinal(d, total)
            if num is not None:
                affected.add(num)
            issues.append({"table": table, "filename": source_file, "kind": d["kind"], "record_id": None,
                           "row_number": num, "field": _text(d.get("field")), "detail": MESSAGES[d["kind"]],
                           "impact": "Source preparation", "enquiry_ids": [],
                           "source_ref": f"{source_file} · record {num}" if num is not None else source_file,
                           "basis": "source_records"})
        profiles.append({"table": table, "filename": source_file, "input_rows": total,
                         "affected_rows": len(affected) if total is not None else None,
                         "affected_fraction": len(affected) / total if total else None})
    return profiles
