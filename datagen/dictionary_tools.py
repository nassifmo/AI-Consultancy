"""Load the data dictionary, check it is self-consistent, validate exported records
against it, and render it as a Markdown document.

Usage:
    python -m datagen.dictionary_tools render     # writes docs/DATA_DICTIONARY.md
    python -m datagen.dictionary_tools check      # checks the dictionary itself
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent
DICTIONARY_PATH = ROOT / "dictionary" / "dictionary.yaml"
SCALAR_TYPES = {"string", "integer", "number", "boolean", "datetime", "date", "enum", "list"}
ALL_TYPES = SCALAR_TYPES | {"object_list"}


def load_dictionary(path: str | Path = DICTIONARY_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _iter_fields(fields: list[dict], prefix: str = ""):
    for f in fields:
        yield prefix + f["name"], f
        if f.get("type") == "object_list":
            yield from _iter_fields(f.get("item_fields", []), prefix + f["name"] + ".")


def check_dictionary(d: dict) -> list[str]:
    """Return a list of problems; empty means the dictionary is consistent."""
    problems: list[str] = []
    sections = {**d.get("files", {}), **d.get("ground_truth", {})}
    field_index = {
        (fname, f["name"]) for fname, spec in d.get("files", {}).items() for f in spec.get("fields", [])
    }
    ids = [spec.get("id") for spec in d.get("files", {}).values()]
    if len(ids) != len(set(ids)):
        problems.append("duplicate file ids")

    for fname, spec in sections.items():
        for key in ("filename", "format"):
            if key not in spec:
                problems.append(f"{fname}: missing '{key}'")
        names = [f["name"] for f in spec.get("fields", [])]
        if len(names) != len(set(names)):
            problems.append(f"{fname}: duplicate field names")
        pk = spec.get("primary_key")
        for k in [pk] if isinstance(pk, str) else (pk or []):
            if k not in names:
                problems.append(f"{fname}: primary_key '{k}' is not a field")
        for path, f in _iter_fields(spec.get("fields", [])):
            t = f.get("type")
            if t not in ALL_TYPES:
                problems.append(f"{fname}.{path}: unknown type '{t}'")
            if t == "enum" and not f.get("values"):
                problems.append(f"{fname}.{path}: enum without values")
            if t == "object_list" and not f.get("item_fields"):
                problems.append(f"{fname}.{path}: object_list without item_fields")
            if "required" not in f:
                problems.append(f"{fname}.{path}: 'required' not set")
            if not f.get("description"):
                problems.append(f"{fname}.{path}: missing description")
            ref = f.get("references")
            if ref:
                rfile, _, rfield = ref.partition(".")
                if (rfile, rfield) not in field_index:
                    problems.append(f"{fname}.{path}: reference '{ref}' does not resolve")
    return problems


# ---------------------------------------------------------------- record validation


@dataclass
class Issue:
    file: str
    record: int
    field: str
    message: str

    def __str__(self) -> str:
        return f"{self.file}[{self.record}].{self.field}: {self.message}"


def _parse_datetime(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError("datetime has no UTC offset")
    return dt


def _check_value(value: Any, spec: dict) -> str | None:
    """Return an error message, or None if the value matches the field spec.

    Accepts both native JSON values and CSV strings."""
    t = spec["type"]
    try:
        if t == "string":
            return None if isinstance(value, str) else "expected string"
        if t == "integer":
            if isinstance(value, bool):
                return "expected integer"
            if isinstance(value, int):
                return None
            int(str(value))
            return None
        if t == "number":
            if isinstance(value, bool):
                return "expected number"
            float(value)
            return None
        if t == "boolean":
            if isinstance(value, bool) or str(value).lower() in {"true", "false"}:
                return None
            return "expected true/false"
        if t == "datetime":
            _parse_datetime(str(value))
            return None
        if t == "date":
            date.fromisoformat(str(value))
            return None
        if t == "enum":
            return None if value in spec["values"] else f"'{value}' not in {spec['values']}"
        if t == "list":
            return None if isinstance(value, (list, str)) else "expected list"
        if t == "object_list":
            return None if isinstance(value, list) else "expected list of objects"
    except (TypeError, ValueError) as e:
        return f"invalid {t}: {e}"
    return f"unsupported type {t}"


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def validate_records(file_key: str, records: list[dict], d: dict | None = None) -> list[Issue]:
    """Validate rows of one export file (types, required fields, enums, unknown columns, nested items)."""
    d = d or load_dictionary()
    spec = {**d["files"], **d.get("ground_truth", {})}[file_key]
    issues: list[Issue] = []

    def check(fields: list[dict], rec: dict, idx: int, prefix: str = ""):
        known = {f["name"] for f in fields}
        for extra in sorted(set(rec) - known):
            issues.append(Issue(file_key, idx, prefix + extra, "unknown field"))
        for f in fields:
            name = prefix + f["name"]
            value = rec.get(f["name"])
            if _is_empty(value):
                if f["required"]:
                    issues.append(Issue(file_key, idx, name, "required field is empty"))
                continue
            msg = _check_value(value, f)
            if msg:
                issues.append(Issue(file_key, idx, name, msg))
            elif f["type"] == "object_list":
                for item in value:
                    if not isinstance(item, dict):
                        issues.append(Issue(file_key, idx, name, "item is not an object"))
                    else:
                        check(f["item_fields"], item, idx, name + ".")

    for i, rec in enumerate(records):
        check(spec.get("fields", []), rec, i)
    return issues


def validate_references(tables: dict[str, list[dict]], d: dict | None = None) -> list[Issue]:
    """Check that every declared reference resolves across the provided tables."""
    d = d or load_dictionary()
    issues: list[Issue] = []
    for fkey, rows in tables.items():
        spec = d["files"].get(fkey)
        if not spec:
            continue
        for f in spec.get("fields", []):
            ref = f.get("references")
            if not ref:
                continue
            rfile, _, rfield = ref.partition(".")
            if rfile not in tables:
                continue
            targets = {r.get(rfield) for r in tables[rfile]}
            for i, r in enumerate(rows):
                v = r.get(f["name"])
                if not _is_empty(v) and v not in targets:
                    issues.append(Issue(fkey, i, f["name"], f"'{v}' not found in {ref}"))
    return issues


# ---------------------------------------------------------------- markdown rendering


def _fmt_type(f: dict) -> str:
    if f["type"] == "enum":
        return "enum: " + ", ".join(f"`{v}`" for v in f["values"])
    return f["type"]


def render_markdown(d: dict) -> str:
    out = [
        "# Data Dictionary",
        "",
        f"Generated from `datagen/dictionary/dictionary.yaml` (version {d['version']}). Do not edit by hand.",
        "",
        "Each file is both a synthetic export we generate and a file we will request from partner companies.",
        "",
    ]

    def table(fields: list[dict], prefix: str = "") -> list[str]:
        rows = []
        for path, f in _iter_fields(fields, prefix):
            ref = f" (-> `{f['references']}`)" if f.get("references") else ""
            req = "yes" if f["required"] else "no"
            rows.append(f"| `{path}` | {_fmt_type(f)} | {req} | {f['description']}{ref} |")
        return rows

    for title, section in (("Partner exports", d["files"]), ("Ground truth (generator only)", d["ground_truth"])):
        out += [f"## {title}", ""]
        for key, spec in section.items():
            label = f"{spec['id']} " if spec.get("id") else ""
            out += [f"### {label}{key} (`{spec['filename']}`)", ""]
            meta = []
            if spec.get("partner_source"):
                meta.append(f"**Real source:** {spec['partner_source']}")
            if spec.get("owner"):
                meta.append(f"**Owner:** {spec['owner']}")
            if spec.get("optional"):
                meta.append("**Optional**")
            if meta:
                out += [" | ".join(meta), ""]
            if spec.get("notes"):
                out += [spec["notes"].strip(), ""]
            if spec.get("fields"):
                out += ["| Field | Type | Required | Description |", "|---|---|---|---|"]
                out += table(spec["fields"])
                out.append("")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "check"
    d = load_dictionary()
    problems = check_dictionary(d)
    if problems:
        print("\n".join(problems))
        return 1
    if cmd == "render":
        target = ROOT.parent / "docs" / "DATA_DICTIONARY.md"
        target.write_text(render_markdown(d) + "\n", encoding="utf-8")
        print(f"wrote {target}")
    else:
        print("dictionary OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
