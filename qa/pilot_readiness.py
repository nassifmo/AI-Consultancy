"""Run a synthetic pilot rehearsal through source preparation and analysis."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from shutil import copytree
from tempfile import TemporaryDirectory

from evaluator.analysis import analyze_exports
from pilot import import_source


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "pilot" / "examples" / "renamed_shipment"

# These expectations come from reading the fixture. The initial AI trace queried a
# sibling container. The human response corrects it and has one 300-second work row.
# Withhold any inference that depends on a removed or explicitly partial history.
BASELINE = {
    "outcome": "resolved", "initial_failure": True, "first_answer_matches": False,
    "human_recovery": True, "active_seconds": 300, "documented_seconds": 300,
    "eligible_requests": 0, "comparison_evidence": "unavailable", "cost_evidence": "unavailable",
    "preparation_issues": [], "duplicate_work_rows": 0,
    "human_work_source_row": 1, "retained_sources_match": True, "repeat_run_matches": True,
}
EXPECTED = {
    "complete_extract": BASELINE,
    "partial_work_log_with_duplicate": BASELINE | {"active_seconds": None, "duplicate_work_rows": 1},
    "missing_response_history": BASELINE | {
        "outcome": "unknown", "initial_failure": None, "first_answer_matches": None,
        "human_recovery": None, "preparation_issues": ["source_unavailable"],
    },
    "malformed_tracking_row": BASELINE | {
        "outcome": "unknown", "human_recovery": None, "preparation_issues": ["malformed_source_row"],
    },
}


def _append(path, line):
    with path.open("a", encoding="utf-8", newline="") as stream:
        stream.write(line + "\n")


def _edit_source(scenario, source, profile):
    if scenario == "partial_work_log_with_duplicate":
        profile["metadata"]["source_completeness"]["agent_work"] = "partial"
        work = source / "work_sessions.csv"
        _append(work, work.read_text(encoding="utf-8").splitlines()[-1])
    elif scenario == "missing_response_history":
        (source / "messages.csv").unlink()
    elif scenario == "malformed_tracking_row":
        _append(source / "tracking.jsonl", json.dumps("unreadable provider entry"))


def _observe(prepared, result):
    (enquiry,) = result["enquiries"]
    verification = enquiry["verification"]
    effort = verification["human_work"]
    evidence = {item["id"]: item["status"] for item in result["readiness_assessment"]["capabilities"]}
    work_row = next(item for item in prepared["row_provenance"]
                    if item["source_file"] == "work_sessions.csv" and item["record_id"] == "WRK-S32-1")
    raw = Path(prepared["bundle_path"]) / "raw"
    return {
        "outcome": enquiry["outcome"]["state"],
        "initial_failure": enquiry["initial_failure"],
        "first_answer_matches": (verification["initial_reply"] or {}).get("matches_record"),
        "human_recovery": verification["human_recovery"],
        "active_seconds": effort["active_seconds"], "documented_seconds": effort["recorded_seconds"],
        "eligible_requests": result["data_readiness"]["eligible_roots"],
        "comparison_evidence": evidence["comparison_assignment"], "cost_evidence": evidence["scoped_costs"],
        "preparation_issues": sorted(issue["code"] for issue in prepared["issues"]),
        "duplicate_work_rows": prepared["tables"]["agent_work"]["exact_duplicates"],
        "human_work_source_row": work_row["row"] if "agent_work.csv#WRK-S32-1" in effort["refs"] else None,
        "retained_sources_match": all(sha256((raw / item["filename"]).read_bytes()).hexdigest() == item["sha256"]
                                      for item in prepared["source_manifest"]),
    }


def rehearse():
    profile = json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8"))
    policy = json.loads((ROOT / "evaluator" / "policy.json").read_text(encoding="utf-8"))
    cases = []
    with TemporaryDirectory(prefix="shipment-pilot-rehearsal-") as folder:
        root = Path(folder)
        for scenario, expected in EXPECTED.items():
            work_dir = root / scenario
            source = copytree(EXAMPLE / "source", work_dir / "source")
            mapping = deepcopy(profile)
            _edit_source(scenario, source, mapping)
            imports = work_dir / "imports"
            prepared = import_source(source, mapping, imports)
            result = analyze_exports(Path(prepared["exports_path"]), policy)
            observed = _observe(prepared, result)
            repeated = import_source(source, mapping, imports)
            observed["repeat_run_matches"] = (repeated["import_id"] == prepared["import_id"]
                                              and result == analyze_exports(Path(repeated["exports_path"]), policy))
            failures = {key: {"expected": value, "observed": observed[key]} for key, value in expected.items()
                        if (observed[key] is not value if isinstance(value, bool) else observed[key] != value)}
            cases.append({"scenario": scenario, "passed": not failures, "findings": observed, "mismatches": failures,
                          "import_id": prepared["import_id"], "run_id": result["run_provenance"]["run_id"]})
    return {
        "scope": "Synthetic source preparation, verification and analysis rehearsal",
        "passed": all(case["passed"] for case in cases),
        "mapping_id": profile["profile_id"], "mapping_version": profile["profile_version"],
        "policy_version": policy["version"], "scenarios": cases,
    }


def main():
    report = rehearse()
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
