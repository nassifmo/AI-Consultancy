"""Publish and verify the reviewed revision of a shipment intake."""

from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from evaluator.exports import EXPORT_FILENAMES, _read_json


APPROVAL_FILENAME = "intake_approval.json"
REVIEW_INPUTS = (EXPORT_FILENAMES | {"service_rules.yaml"}) - {APPROVAL_FILENAME}
REQUIRED_INPUTS = {"export_metadata.json", "enquiries.csv"}
MAX_INPUT_BYTES = 100 * 1024**2
MAX_SNAPSHOT_BYTES = 300 * 1024**2
MAX_APPROVAL_BYTES = 2 * 1024**2


def _json_bytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _exports_root(exports_path):
    path = Path(exports_path)
    if path.name.casefold() != "exports" or path.is_symlink() or not path.is_dir():
        raise ValueError("Supply a regular exports directory for intake review.")
    root = path.resolve(strict=True)
    if root.name.casefold() != "exports" or any(part.casefold() == "ground_truth" for part in root.parts):
        raise ValueError("Benchmark answers cannot supply intake evidence.")
    return root


def _direct_file(root, name, limit):
    path = root / name
    if path.is_symlink():
        raise ValueError(f"{name} must be a regular file directly inside exports.")
    if not path.exists():
        return None
    resolved = path.resolve(strict=True)
    if resolved.parent != root or resolved.name != name or not resolved.is_file():
        raise ValueError(f"{name} must be a regular file directly inside exports.")
    with resolved.open("rb") as stream:
        payload = stream.read(limit + 1)
    if len(payload) > limit:
        raise ValueError(f"{name} exceeds the intake review size limit.")
    return payload


def _snapshot(root, *, retain=False):
    fingerprints, contents = {}, {}
    total = 0
    for name in sorted(REVIEW_INPUTS):
        payload = _direct_file(root, name, min(MAX_INPUT_BYTES, MAX_SNAPSHOT_BYTES - total))
        if payload is None:
            continue
        total += len(payload)
        fingerprints[name] = {"sha256": sha256(payload).hexdigest(), "bytes": len(payload)}
        if retain:
            contents[name] = payload
    if not REQUIRED_INPUTS <= fingerprints.keys():
        raise ValueError("Approving an intake requires export_metadata.json and enquiries.csv.")
    return fingerprints, contents


def _review_text(value, label, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"Supply {label} up to {limit:,} characters for intake approval.")
    return value.strip()


def _review_fields(reviewer, note, decisions, limitations):
    if not isinstance(decisions, (list, tuple)) or not all(isinstance(decision, dict) for decision in decisions):
        raise ValueError("Intake review decisions must be a list of records.")
    if not isinstance(limitations, (list, tuple)):
        raise ValueError("Intake limitations must be a list of review notes.")
    return {
        "reviewer": _review_text(reviewer, "the reviewer", 120),
        "review_note": _review_text(note, "a review note", 4000),
        "decisions": list(decisions),
        "limitations": [_review_text(item, "each limitation", 2000) for item in limitations],
    }


def _approval_id(record):
    return "approved-" + sha256(_json_bytes(record)).hexdigest()[:24]


def intake_fingerprints(exports_path):
    """Bind a review to the exact inputs it inspected."""
    fingerprints, _ = _snapshot(_exports_root(exports_path))
    return fingerprints


def read_approval(exports_path, *, required=False):
    """Read a local approval record and verify that the supplied files match it."""
    root = _exports_root(exports_path)
    payload = _direct_file(root, APPROVAL_FILENAME, MAX_APPROVAL_BYTES)
    if payload is None:
        if required:
            raise ValueError("This intake must be reviewed and approved before evaluation.")
        return None

    record = _read_json(payload.decode("utf-8"))
    fields = {"schema_version", "approved_at", "reviewer", "review_note", "decisions",
              "limitations", "input_files", "preparation"}
    if not isinstance(record, dict) or set(record) != fields | {"approval_id"} or record["schema_version"] != "1.0":
        raise ValueError("The intake approval record has an unsupported format.")
    instant = record["approved_at"]
    if not isinstance(instant, str) or datetime.fromisoformat(instant).utcoffset() is None:
        raise ValueError("The intake approval needs a timestamp with an offset.")
    _review_fields(record["reviewer"], record["review_note"], record["decisions"], record["limitations"])
    if not isinstance(record["preparation"], dict):
        raise ValueError("The intake approval has an invalid source preparation reference.")
    if record["approval_id"] != _approval_id({key: value for key, value in record.items() if key != "approval_id"}):
        raise ValueError("The intake approval record fingerprint does not match.")
    actual, _ = _snapshot(root)
    if record["input_files"] != actual:
        raise ValueError("The export files have changed since intake approval.")
    return record


def approve_exports(exports_path, output_dir, *, reviewer, note, decisions=(), limitations=(), expected_files=None):
    """Save the review and exact export bytes as a separate approved revision."""
    root = _exports_root(exports_path)
    review = _review_fields(reviewer, note, decisions, limitations)
    inputs, contents = _snapshot(root, retain=True)
    if expected_files is not None and inputs != expected_files:
        raise ValueError("The export files changed during intake review. Review the current files before approving.")
    metadata = _read_json(contents["export_metadata.json"].decode("utf-8-sig"))
    if not isinstance(metadata, dict):
        raise ValueError("The export metadata must be a JSON object.")
    preparation = {
        key: metadata[key] for key in ("preparation_id", "source_profile_id", "source_profile_version")
        if isinstance(metadata.get(key), str)
    }
    record = {"schema_version": "1.0", "approved_at": datetime.now(UTC).isoformat(),
              **review, "input_files": inputs, "preparation": preparation}
    approval_id = _approval_id(record)
    record["approval_id"] = approval_id
    approved_bytes = _json_bytes(record)
    if len(approved_bytes) > MAX_APPROVAL_BYTES:
        raise ValueError("The intake approval exceeds the 2 MiB review size limit.")

    parent = Path(output_dir)
    if parent.is_symlink():
        raise ValueError("Use a regular destination for approved intake bundles.")
    parent = parent.resolve()
    if parent.is_relative_to(root):
        raise ValueError("Store an approved intake beside its source exports directory.")
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / approval_id
    with TemporaryDirectory(dir=parent, prefix=".approving-") as temporary:
        staging = Path(temporary) / "bundle"
        approved_exports = staging / "exports"
        approved_exports.mkdir(parents=True)
        for name, payload in contents.items():
            (approved_exports / name).write_bytes(payload)
        (approved_exports / APPROVAL_FILENAME).write_bytes(approved_bytes)
        if destination.exists() or destination.is_symlink():
            raise FileExistsError("This intake approval destination is already occupied.")
        staging.rename(destination)
    return {"approval_id": approval_id, "exports_path": str(destination / "exports"), "approval": record}
