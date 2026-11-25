"""Load the shipment records the evaluator is permitted to inspect."""

import csv
from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import io
import json
from math import isfinite
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


# The first column is the stable record ID used for deduplication.
TABLES = {
    "customers": ("customers.csv", ("customer_id",)),
    "shipments": ("shipments.csv", ("booking_ref", "customer_id")),
    "tracking_events": (
        "tracking_events.json",
        ("event_id", "booking_ref", "event_type", "event_type_code", "classifier", "event_created_datetime", "event_datetime"),
    ),
    "enquiries": ("enquiries.csv", ("enquiry_id", "customer_id", "received_at", "enquiry_type")),
    "agent_runs": ("agent_runs.json", ("run_id", "enquiry_id", "started_at", "ended_at", "steps")),
    "responses": ("responses.csv", ("response_id", "enquiry_id", "sent_at", "actor_type", "purpose")),
    "cases": ("cases.csv", ("case_id", "enquiry_id", "opened_at")),
    "case_history": ("case_history.csv", ("history_id", "case_id", "changed_at", "field")),
    "agent_work": ("agent_work.csv", ("work_id", "accepted_at", "agent_id")),
}
ANALYSIS_TABLES = {
    "ai_invoice": ("ai_invoice.csv", ("period", "line_item", "quantity", "unit_price", "amount", "currency")),
    "rollout_log": ("rollout_log.csv", ("date", "agent_version", "arm_assignment_rule")),
    "staffing": ("staffing.csv", ("month", "support_headcount")),
}
ANALYSIS_KEYS = {"ai_invoice": ("period", "line_item", "currency"),
                 "rollout_log": ("date", "agent_version", "region")}
EXPORT_FILENAMES = frozenset(filename for filename, _ in (TABLES | ANALYSIS_TABLES).values()) | {
    "export_metadata.json", "cost_parameters.json"
}
MEASURED_WORK_METHODS = frozenset({"logged", "timed"})


@dataclass
class ExportData:
    tables: dict[str, list[dict]] = field(default_factory=dict)
    available: set[str] = field(default_factory=set)
    metadata: dict = field(default_factory=dict)
    issues: list[dict] = field(default_factory=list)
    conflicts: dict[str, list[dict]] = field(default_factory=dict)
    unscoped: set[str] = field(default_factory=set)
    cutoff: datetime | None = None
    cost_parameters: dict | None = None
    files: dict = field(default_factory=dict)
    input_rows: dict[str, list] = field(default_factory=dict, repr=False)
    row_issues: dict[str, list[dict]] = field(default_factory=dict, repr=False)

    def is_complete(self, table: str) -> bool:
        """Check an explicit source-owner declaration when one accompanies the export.

        Historical synthetic benchmarks predate completeness declarations.
        Other exports require explicitly confirmed coverage.
        """
        declarations = self.metadata.get("source_completeness")
        if "source_completeness" not in self.metadata:
            return table in self.available
        return (isinstance(declarations, dict) and declarations.get(table) == "complete"
                and table in self.available)

    def time(self, table: str, value: object) -> datetime | None:
        """Return a UTC instant when the export provides an unambiguous time."""
        if not isinstance(value, str):
            return None
        value = value.strip()
        if "T" not in value and " " not in value:
            return None  # A date or a blank cannot establish an instant.
        try:
            timestamp = datetime.fromisoformat(value)
            if timestamp.utcoffset() is None:
                timezones = self.metadata.get("timezones")
                name = timezones.get(table) if isinstance(timezones, dict) else None
                if not isinstance(name, str):
                    return None
                zone = UTC if name == "UTC" else ZoneInfo(name)
                local = timestamp.replace(tzinfo=zone, fold=0)
                if local.utcoffset() != local.replace(fold=1).utcoffset():
                    return None  # Ambiguous or skipped local clock time.
                timestamp = local
            return timestamp.astimezone(UTC)
        except (ValueError, OverflowError, ZoneInfoNotFoundError):
            return None


def reference(table: str, row: dict) -> str:
    filename, columns = TABLES[table]
    return f"{filename}#{row[columns[0]]}"


def _object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key {key!r}.")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON value {value!r}.")


def finite_json_float(value: str) -> float:
    number = float(value)
    if not isfinite(number):
        raise ValueError("JSON contains a number outside the supported range.")
    return number


def _read_json(source: str):
    return json.loads(source, object_pairs_hook=_object, parse_constant=_invalid_constant,
                      parse_float=finite_json_float)


def _read_metadata(source: str) -> dict:
    metadata = _read_json(source)
    if not isinstance(metadata, dict):
        raise ValueError("Expected a JSON object for export metadata.")
    return metadata


def _read_rows(source: str, filename: str, columns: tuple[str, ...]) -> list:
    if filename.endswith(".json"):
        rows = _read_json(source)
        if not isinstance(rows, list):
            raise ValueError("Expected a JSON array of records.")
        return rows
    reader = csv.DictReader(io.StringIO(source, newline=""), strict=True)
    header = reader.fieldnames or []
    if len(set(header)) != len(header) or not all(header) or not set(columns).issubset(header):
        raise ValueError(f"Expected a CSV header containing {', '.join(columns)}.")
    return list(reader)


def _load_file(root: Path, filename: str, table: str, data: ExportData, reader):
    path = root / filename
    info = data.files.setdefault(filename, {"name": filename, "sha256": None, "row_count": None, "status": "missing"})
    try:
        if path.is_symlink():
            raise ValueError("Symbolic links are not accepted for export files.")
        resolved = path.resolve(strict=True)
        if resolved.parent != root or resolved.name != filename or not resolved.is_file():
            raise ValueError("Expected a regular file inside the exports directory.")
        contents = resolved.read_bytes()
        info["sha256"] = hashlib.sha256(contents).hexdigest()
        parsed = reader(contents.decode("utf-8-sig"))
        info.update(status="loaded", row_count=len(parsed) if isinstance(parsed, list) else 1)
        return parsed
    except FileNotFoundError:
        data.issues.append({"table": table, "code": "missing_file", "detail": filename})
    except (OSError, ValueError, csv.Error, RuntimeError) as error:
        info["status"] = "invalid"
        data.issues.append({"table": table, "code": "invalid_file", "detail": str(error)})
    data.unscoped.add(table)
    return None


def _read_table(data: ExportData, table: str, rows: list, columns: tuple[str, ...]) -> None:
    id_key = columns[0]
    unique = {}
    conflicting = {}
    malformed = set()
    seen = {}
    is_csv = (TABLES | ANALYSIS_TABLES)[table][0].endswith(".csv")
    issues_before = len(data.issues)
    data.input_rows[table] = rows
    row_issues = data.row_issues.setdefault(table, [])

    def issue(code, index, record_id=None, fields=()):
        row_issues.append({"kind": code, "row_number": index, "record_id": record_id, "fields": list(fields)})

    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            issue("malformed_row", index)
            data.issues.append({"table": table, "code": "malformed_row", "row": index})
            data.unscoped.add(table)
            continue
        record_id = row.get(id_key)
        if not isinstance(record_id, str) or not record_id.strip():
            issue("missing_record_id", index, fields=(id_key,))
            data.issues.append({"table": table, "code": "missing_record_id", "row": index})
            data.unscoped.add(table)
            continue
        if table in ANALYSIS_KEYS:
            record_id = "|".join(str(row.get(column) or "") for column in ANALYSIS_KEYS[table])
        copies = seen.setdefault(record_id, [])
        if any(row == prior for prior in copies):
            issue("exact_duplicate", index, record_id)
        else:
            copies.append(row)
        if (
            None in row
            or (is_csv and None in row.values())
            or not set(columns).issubset(row)
            or any(value is not None and not isinstance(value, str) for key, value in row.items()
                   if key in columns and key != "steps")
        ):
            issue("malformed_row", index, record_id)
            malformed.add(record_id)
            data.issues.append({"table": table, "code": "malformed_row", "record_id": record_id})
        elif any(row[column] is None or row[column] == "" for column in columns):
            issue("missing_required_field", index, record_id, (c for c in columns if row[c] is None or row[c] == ""))
            data.issues.append({"table": table, "code": "missing_required_field", "record_id": record_id})
        if table == "agent_runs" and (
            not isinstance(row.get("steps"), list) or any(not isinstance(step, dict) for step in row["steps"])
        ):
            issue("malformed_steps", index, record_id, ("steps",))
            malformed.add(record_id)
            data.issues.append({"table": table, "code": "malformed_steps", "record_id": record_id})
        if record_id in conflicting:
            if row not in conflicting[record_id]:
                conflicting[record_id].append(row)
        elif record_id not in unique:
            unique[record_id] = row
        elif unique[record_id] != row:
            conflicting[record_id] = [unique.pop(record_id), row]
            data.issues.append({"table": table, "code": "conflicting_record_id", "record_id": record_id})
    data.tables[table] = [row for record_id, row in unique.items() if record_id not in malformed]
    data.conflicts[table] = (
        [row for group in conflicting.values() for row in group]
        + [row for record_id, row in unique.items() if record_id in malformed]
    )
    if len(data.issues) == issues_before:
        data.available.add(table)


def load_exports(path: Path, *, analysis: bool = False) -> ExportData:
    """Load only the whitelisted files directly inside an exports directory."""
    path = Path(path)
    if path.name.casefold() != "exports" or path.is_symlink():
        raise ValueError("Supply the exports directory.")
    root = path.resolve(strict=True)
    if (
        root.name.casefold() != "exports"
        or not root.is_dir()
        or any(part.casefold() == "ground_truth" for part in root.parts)
    ):
        raise ValueError("Supply the exports directory.")

    tables = TABLES | ANALYSIS_TABLES if analysis else TABLES
    data = ExportData(tables={table: [] for table in tables}, conflicts={table: [] for table in tables})
    metadata = _load_file(root, "export_metadata.json", "export_metadata", data, _read_metadata)
    if metadata is not None:
        data.metadata = metadata
        if metadata.get("dataset_origin") != "synthetic":
            # Successfully reading a file only proves the supplied rows could be read.
            metadata.setdefault("source_completeness", {})
        if "source_completeness" in metadata and not isinstance(metadata["source_completeness"], dict):
            metadata["source_completeness"] = {}
        data.cutoff = data.time("export_metadata", metadata.get("data_cutoff"))
        if data.cutoff is not None:
            data.available.add("export_metadata")
        else:
            data.issues.append({"table": "export_metadata", "code": "invalid_cutoff", "detail": "data_cutoff"})

    for table, (filename, columns) in tables.items():
        rows = _load_file(root, filename, table, data, lambda source: _read_rows(source, filename, columns))
        if rows is not None:
            _read_table(data, table, rows, columns)
            if table not in data.available:
                data.files[filename]["status"] = "partially_valid"
    if analysis:
        data.cost_parameters = _load_file(root, "cost_parameters.json", "cost_parameters", data, _read_metadata)
    return data
