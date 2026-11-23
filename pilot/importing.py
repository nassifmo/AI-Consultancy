"""Normalize local extracts using a versioned, declarative mapping profile."""

import csv
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from evaluator.exports import ANALYSIS_KEYS, ANALYSIS_TABLES, TABLES


SCHEMA_VERSION = "1.0"
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_TOTAL_BYTES = 300 * 1024 * 1024
MAX_ROWS = 250_000
TABLE_DEFINITIONS = TABLES | ANALYSIS_TABLES
FORMATS = {"csv", "json", "jsonl"}
TYPES = {"string", "datetime", "integer", "number", "boolean", "list", "object_list"}


def _json(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON repeats field {key!r}.")
        result[key] = value
    return result


def _read_json(text):
    def reject(value):
        raise ValueError(f"Unsupported JSON number {value}.")
    return json.loads(text, object_pairs_hook=_unique_object, parse_constant=reject)


def _filename(value):
    return (isinstance(value, str) and bool(value) and value not in {".", ".."}
            and not any(char in value for char in '/\\:\x00') and value == value.strip()
            and not value.endswith((".", " ")))


def _validate_columns(columns):
    if not isinstance(columns, dict) or not columns:
        raise ValueError("Each mapped table needs a nonempty columns object.")
    for target, specification in columns.items():
        if not isinstance(target, str) or not target.strip():
            raise ValueError("Target field names must be nonempty text.")
        if isinstance(specification, str):
            specification = {"path": specification}
        if not isinstance(specification, dict) or set(specification) - {"path", "type", "values", "timezone", "items"}:
            raise ValueError(f"Unsupported mapping for {target}.")
        if not isinstance(specification.get("path"), str) or not specification["path"].strip():
            raise ValueError(f"Supply the source path for {target}.")
        kind = specification.get("type", "string")
        if not isinstance(kind, str) or kind not in TYPES:
            raise ValueError(f"Unsupported conversion for {target}.")
        if "values" in specification and not isinstance(specification["values"], dict):
            raise ValueError(f"Value mapping for {target} must be an object.")
        if "timezone" in specification:
            try:
                ZoneInfo(specification["timezone"])
            except (ValueError, TypeError, ZoneInfoNotFoundError) as error:
                raise ValueError(f"Unknown source timezone for {target}.") from error
        if "items" in specification:
            if specification.get("type") != "object_list":
                raise ValueError(f"Item mappings on {target} require object_list.")
            _validate_columns(specification["items"])


def validate_profile(profile):
    """Validate executable-free source mapping and explicit observation metadata."""
    if not isinstance(profile, dict) or set(profile) - {"schema_version", "profile_id", "profile_version", "metadata", "tables", "objects"}:
        raise ValueError("Supply a mapping profile with recognized fields.")
    if profile.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("The mapping profile schema_version must be 1.0.")
    for key in ("profile_id", "profile_version"):
        if not isinstance(profile.get(key), str) or not profile[key].strip():
            raise ValueError(f"Supply {key}.")
    metadata = profile.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("Supply explicit metadata for the observation window.")
    for key in ("data_cutoff",):
        value = metadata.get(key)
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.utcoffset() is None:
                raise ValueError()
        except (TypeError, ValueError) as error:
            raise ValueError(f"metadata.{key} needs an ISO time with a UTC offset.") from error
    period = metadata.get("study_period")
    if not isinstance(period, list) or len(period) != 2:
        raise ValueError("metadata.study_period needs start and end timestamps.")
    try:
        start, end = [datetime.fromisoformat(value) for value in period]
        if start.utcoffset() is None or end.utcoffset() is None or start >= end:
            raise ValueError()
    except (ValueError, TypeError) as error:
        raise ValueError("The study period needs increasing ISO times with UTC offsets.") from error
    origin = metadata.get("dataset_origin", "unconfirmed")
    if not isinstance(origin, str) or origin not in {"synthetic", "company", "unconfirmed"}:
        raise ValueError("metadata.dataset_origin must be synthetic, company, or unconfirmed.")
    completeness = metadata.get("source_completeness", {})
    if (not isinstance(completeness, dict) or set(completeness) - TABLE_DEFINITIONS.keys()
            or any(not isinstance(value, str) or value not in {"complete", "partial", "unknown"} for value in completeness.values())):
        raise ValueError("source_completeness needs recognized tables and complete, partial, or unknown values.")
    tables = profile.get("tables")
    if not isinstance(tables, dict) or not tables or set(tables) - TABLE_DEFINITIONS.keys():
        raise ValueError("Supply recognized canonical table mappings.")
    for table, specification in tables.items():
        if not isinstance(specification, dict) or set(specification) - {"file", "format", "records_path", "columns"}:
            raise ValueError(f"Unsupported table mapping for {table}.")
        if (not _filename(specification.get("file")) or not isinstance(specification.get("format"), str)
                or specification["format"] not in FORMATS):
            raise ValueError(f"{table} needs a direct filename and csv, json, or jsonl format.")
        if "records_path" in specification and not isinstance(specification["records_path"], str):
            raise ValueError(f"{table}.records_path must be a JSON object path.")
        _validate_columns(specification.get("columns"))
    objects = profile.get("objects", {})
    if not isinstance(objects, dict) or set(objects) - {"cost_parameters"}:
        raise ValueError("Only cost_parameters can be mapped as an object.")
    for name, specification in objects.items():
        if (not isinstance(specification, dict) or set(specification) != {"file"}
                or not _filename(specification["file"])):
            raise ValueError(f"Supply a direct JSON filename for {name}.")
    _json(profile)
    return profile


def _path(record, key):
    if key in record:
        return record[key]
    value = record
    for component in key.split("."):
        if not isinstance(value, dict) or component not in value:
            raise KeyError(key)
        value = value[component]
    return value


def _timestamp(value, zone_name):
    if not isinstance(value, str) or ("T" not in value and " " not in value):
        raise ValueError("An ISO timestamp is required.")
    instant = datetime.fromisoformat(value)
    if instant.utcoffset() is None:
        if not zone_name:
            raise ValueError("The source time has no offset or explicit timezone.")
        zone = ZoneInfo(zone_name)
        instant = instant.replace(tzinfo=zone, fold=0)
        if instant.utcoffset() != instant.replace(fold=1).utcoffset():
            raise ValueError("The source local time is ambiguous or does not exist.")
    return instant.astimezone(timezone.utc).isoformat()


def _convert(value, specification, issues, location):
    if value is None or value == "":
        return None
    values = specification.get("values")
    if values is not None:
        key = str(value).lower() if isinstance(value, bool) else str(value)
        if key not in values:
            raise ValueError("The source value has no explicit mapping.")
        value = values[key]
        if value is None or value == "":
            return None
    kind = specification.get("type", "string")
    if kind == "datetime":
        return _timestamp(value, specification.get("timezone"))
    if kind in {"integer", "number"}:
        if isinstance(value, bool):
            raise ValueError("A boolean cannot supply a numeric measurement.")
        try:
            number = Decimal(str(value))
        except InvalidOperation as error:
            raise ValueError("A numeric measurement is required.") from error
        if not number.is_finite() or kind == "integer" and number != number.to_integral_value():
            raise ValueError("The numeric measurement is invalid.")
        return int(number) if kind == "integer" else str(number)
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in {"true", "false"}:
            return value.lower() == "true"
        raise ValueError("An explicit true or false is required.")
    if kind in {"list", "object_list"}:
        if isinstance(value, str):
            value = _read_json(value)
        if not isinstance(value, list):
            raise ValueError("A list is required.")
        if kind == "object_list":
            if not all(isinstance(item, dict) for item in value):
                raise ValueError("Each list entry must be an object.")
            if "items" in specification:
                return [_mapped_row(item, specification["items"], issues, {**location, "item": index})
                        for index, item in enumerate(value, 1)]
        return value
    if isinstance(value, (dict, list)):
        raise ValueError("Map this structured source as a list or object_list.")
    return str(value)


def _mapped_row(record, columns, issues, location):
    mapped = {}
    for target, specification in columns.items():
        specification = {"path": specification} if isinstance(specification, str) else specification
        try:
            source = _path(record, specification["path"])
            mapped[target] = _convert(source, specification, issues, {**location, "field": target})
        except (ValueError, TypeError, KeyError, OverflowError, ZoneInfoNotFoundError) as error:
            code = "missing_source_field" if isinstance(error, KeyError) else "conversion_failed"
            issues.append({**location, "field": target, "code": code, "detail": str(error)})
            mapped[target] = None
    return mapped


def _source_file(root, filename, retained):
    if filename in retained:
        return retained[filename]
    path = root / filename
    if not path.exists() and not path.is_symlink():
        raise FileNotFoundError("Source file is missing.")
    if path.is_symlink() or path.resolve().parent != root or not path.is_file():
        raise ValueError("Expected a regular direct source file.")
    with path.open("rb") as stream:
        content = stream.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise ValueError("The source file exceeds the 100 MiB preparation limit.")
    if sum(len(value) for value in retained.values()) + len(content) > MAX_TOTAL_BYTES:
        raise ValueError("Source files exceed the 300 MiB preparation limit.")
    retained[filename] = content
    return content


def _source_rows(content, specification):
    text = content.decode("utf-8-sig")
    kind = specification["format"]
    if kind == "csv":
        reader = csv.DictReader(StringIO(text, newline=""), strict=True)
        header = reader.fieldnames or []
        if not header or not all(header) or len(set(header)) != len(header):
            raise ValueError("CSV needs unique, nonempty column names.")
        rows = []
        for record in reader:
            if len(rows) == MAX_ROWS:
                raise ValueError("The source table exceeds the 250,000 record preparation limit.")
            rows.append(record)
        return rows
    if kind == "jsonl":
        rows = []
        for line in text.splitlines():
            if line.strip():
                if len(rows) == MAX_ROWS:
                    raise ValueError("The source table exceeds the 250,000 record preparation limit.")
                rows.append(_read_json(line))
        return rows
    records = _read_json(text)
    if specification.get("records_path"):
        records = _path(records, specification["records_path"])
    if not isinstance(records, list) or len(records) > MAX_ROWS:
        raise ValueError("JSON source needs an array within the 250,000 record limit.")
    return records


def _table(root, table, specification, retained, issues, provenance):
    filename, required = TABLE_DEFINITIONS[table]
    location = {"table": table, "source_file": specification["file"]}
    summary = {"file": filename, "source_file": specification["file"], "input_rows": 0,
               "output_rows": 0, "exact_duplicates": 0, "conflicting_ids": 0,
               "missing_required_fields": sorted(set(required) - specification["columns"].keys()), "status": "mapped"}
    try:
        records = _source_rows(_source_file(root, specification["file"], retained), specification)
    except (OSError, ValueError, UnicodeError, csv.Error, KeyError) as error:
        summary["status"] = "missing" if isinstance(error, FileNotFoundError) else "invalid"
        issues.append({**location, "code": "source_unavailable", "detail": str(error)})
        return None, summary
    for field in summary["missing_required_fields"]:
        issues.append({**location, "field": field, "code": "unmapped_required_field", "detail": "Required source mapping is missing."})
    summary["input_rows"] = len(records)
    rows = []
    identifiers = {}
    conflicted = set()
    for index, record in enumerate(records, 1):
        current = {**location, "row": index}
        if not isinstance(record, dict) or None in record:
            issues.append({**current, "code": "malformed_source_row", "detail": "Source row is not a regular record."})
            continue
        row = _mapped_row(record, specification["columns"], issues, current)
        for field in required:
            row.setdefault(field, None)
        if filename.endswith(".csv"):
            row = {key: "" if value is None else json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict))
                   else str(value).lower() if isinstance(value, bool) else str(value) for key, value in row.items()}
        identity_fields = ANALYSIS_KEYS.get(table, (required[0],))
        identity = "|".join(str(row.get(key) or "") for key in identity_fields)
        signature = _json(row)
        if identity in identifiers:
            if signature in identifiers[identity]:
                summary["exact_duplicates"] += 1
            elif identity not in conflicted:
                conflicted.add(identity)
                issues.append({**current, "code": "conflicting_record_id", "detail": identity})
            identifiers[identity].add(signature)
        else:
            identifiers[identity] = {signature}
        for field in required:
            if row[field] is None or row[field] == "":
                issues.append({**current, "field": field, "code": "missing_required_value", "detail": "Required evidence is unavailable."})
        provenance.append({**current, "target_file": filename, "target_row": len(rows) + 1,
                           "record_id": identity, "source_row_sha256": sha256(_json(record)).hexdigest()})
        rows.append(row)
    summary.update(output_rows=len(rows), conflicting_ids=len(conflicted))
    return rows, summary


def _artifact_bytes(result, retained, profile):
    files = {"profile.json": _json(profile), "preparation.json": _json({key: value for key, value in result.items() if key != "exports"})}
    files.update({f"raw/{filename}": content for filename, content in retained.items()})
    for filename, records in result["exports"].items():
        if filename.endswith(".csv"):
            table = next(key for key, (name, _) in TABLE_DEFINITIONS.items() if name == filename)
            fields = list(dict.fromkeys((*TABLE_DEFINITIONS[table][1], *profile["tables"][table]["columns"])))
            text = StringIO(newline="")
            writer = csv.DictWriter(text, fieldnames=fields)
            writer.writeheader()
            writer.writerows(records)
            files[f"exports/{filename}"] = text.getvalue().encode("utf-8")
        else:
            files[f"exports/{filename}"] = _json(records)
    return files


def _publish(output_dir, result, retained, profile):
    parent = Path(output_dir)
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / result["import_id"]
    files = _artifact_bytes(result, retained, profile)
    def check():
        if destination.is_symlink() or not destination.is_dir():
            raise FileExistsError("The import destination is occupied.")
        contents = list(destination.rglob("*"))
        if any(path.is_symlink() for path in contents):
            raise FileExistsError("The existing import contains a symbolic link.")
        actual = {path.relative_to(destination).as_posix() for path in contents if path.is_file()}
        if actual != files.keys():
            raise FileExistsError("The existing import contains different files.")
        for filename, expected in files.items():
            path = destination / filename
            if path.is_symlink() or path.read_bytes() != expected:
                raise FileExistsError("The existing import does not match its recorded inputs.")
    if destination.exists() or destination.is_symlink():
        check()
    else:
        with TemporaryDirectory(dir=parent, prefix=".preparing-") as temporary:
            stage = Path(temporary) / "bundle"
            stage.mkdir()
            for filename, content in files.items():
                path = stage / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            try:
                stage.rename(destination)
            except OSError:
                if not destination.exists():
                    raise
                check()
    return str(destination.resolve()), str((destination / "exports").resolve())


def import_source(source_path, profile, output_dir=None):
    """Preview or publish normalized exports, retaining source evidence separately."""
    profile = validate_profile(profile)
    source = Path(source_path)
    if source.is_symlink() or not source.is_dir():
        raise ValueError("Choose a regular source directory.")
    root = source.resolve(strict=True)
    if any(part.casefold() == "ground_truth" for part in root.parts):
        raise ValueError("Benchmark answer directories cannot supply pilot records.")
    retained, issues, provenance, summaries, exports = {}, [], [], {}, {}
    metadata = dict(profile["metadata"])
    metadata.setdefault("dataset_origin", "unconfirmed")
    metadata["source_completeness"] = {
        table: metadata.get("source_completeness", {}).get(table, "unknown") for table in TABLE_DEFINITIONS
    }
    metadata["declared_source_completeness"] = dict(metadata["source_completeness"])
    exports["export_metadata.json"] = metadata
    for table, specification in profile["tables"].items():
        rows, summary = _table(root, table, specification, retained, issues, provenance)
        summaries[table] = summary
        if rows is not None:
            exports[TABLE_DEFINITIONS[table][0]] = rows
    for name, specification in profile.get("objects", {}).items():
        try:
            value = _read_json(_source_file(root, specification["file"], retained).decode("utf-8-sig"))
            if not isinstance(value, dict):
                raise ValueError("A configuration object is required.")
            exports[f"{name}.json"] = value
        except (OSError, ValueError, UnicodeError) as error:
            issues.append({"table": name, "source_file": specification["file"], "code": "source_unavailable", "detail": str(error)})
    counts_by_table = Counter(issue["table"] for issue in issues)
    for table in counts_by_table:
        if table in metadata["source_completeness"]:
            metadata["source_completeness"][table] = "partial"
    metadata["preparation_issue_counts"] = {
        "total": len(issues), "by_table": dict(sorted(counts_by_table.items())),
        "by_code": dict(sorted(Counter(issue["code"] for issue in issues).items())),
    }
    # Carry diagnostic locations, without the original field values. Rejected
    # rows cannot otherwise be listed after the mapped exports are loaded.
    preparation_kinds = {"source_unavailable", "malformed_source_row", "missing_source_field",
                         "conversion_failed", "unmapped_required_field", "missing_required_value"}
    by_table = {}
    for problem in issues:
        if problem["table"] in summaries and problem["code"] in preparation_kinds:
            by_table.setdefault(problem["table"], []).append(
                {"kind": problem["code"], "row_number": problem.get("row"), "field": problem.get("field")})
    metadata["quality_preparation"] = {
        table: {"source_file": summary["source_file"],
                "input_rows": summary["input_rows"] if summary["status"] == "mapped" else None,
                "issues": by_table.get(table, [])}
        for table, summary in summaries.items()
    }
    source_manifest = [{"filename": name, "sha256": sha256(content).hexdigest(), "bytes": len(content)}
                       for name, content in sorted(retained.items())]
    importer_sha = sha256(Path(__file__).read_bytes()).hexdigest()
    identity = {"profile": profile, "source_manifest": source_manifest, "importer_sha256": importer_sha}
    import_id = "import-" + sha256(_json(identity)).hexdigest()[:24]
    metadata["preparation_id"] = import_id
    metadata["source_profile_id"] = profile["profile_id"]
    metadata["source_profile_version"] = profile["profile_version"]
    result = {"schema_version": SCHEMA_VERSION, "import_id": import_id, "importer_sha256": importer_sha,
              "profile_id": profile["profile_id"], "profile_version": profile["profile_version"],
              "source_manifest": source_manifest, "row_provenance": provenance,
              "tables": summaries, "issues": issues, "exports": exports,
              "status": "needs_review" if issues else "prepared",
              "bundle_path": None, "exports_path": None}
    if output_dir is not None:
        result["bundle_path"], result["exports_path"] = _publish(output_dir, result, retained, profile)
    return result
