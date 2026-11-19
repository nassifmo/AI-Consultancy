"""Build and check distribution files using the dedicated Python environment."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from app import unpack_exports
from evaluator.analysis import analyze_exports
from evaluator.exports import EXPORT_FILENAMES
from evaluator.reporting import write_run_bundle


ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "datagen" / "datasets" / "release_1"
POLICY = ROOT / "evaluator" / "policy.json"
RELEASE = ROOT / "meeting_release"
BULK = ("tiny", "dev", "damaged", "null_effect", "confounded", "staged")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bulk", action="store_true", help="Also run the six bulk compatibility checks.")
    parser.add_argument("--test-evidence", type=Path, help="Path to the final test transcript.")
    args = parser.parse_args()
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    RELEASE.mkdir(exist_ok=True)

    if args.bulk:
        cases = {}
        for name in BULK:
            result = analyze_exports(DATASETS / name / "exports", policy)
            json.dumps(result, allow_nan=False)
            readiness = result["data_readiness"]
            cases[name] = {
                "contacts": len(result["enquiries"]), "eligible_roots": readiness["eligible_roots"],
                "input_issues": len(readiness["input_issues"]), "comparison_status": readiness["comparison_status"],
                "run_id": result["run_provenance"]["run_id"],
            }
            print(name, cases[name], flush=True)
        (RELEASE / "bulk_validation.json").write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")
        return

    exports = DATASETS / "demo" / "exports"
    archive_path = RELEASE / "demo_exports.zip"
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(exports.iterdir()):
            if path.name in EXPORT_FILENAMES and path.is_file():
                member = ZipInfo(f"exports/{path.name}", date_time=(2026, 11, 17, 0, 0, 0))
                archive.writestr(member, path.read_bytes(), compress_type=ZIP_DEFLATED)
    result = analyze_exports(exports, policy)
    with unpack_exports(archive_path.read_bytes()) as imported:
        if analyze_exports(imported, policy) != result:
            raise RuntimeError("ZIP input and folder input did not produce identical results.")
    if args.test_evidence:
        result["test_metadata"] = {"transcript": args.test_evidence.name,
                                   "sha256": sha256(args.test_evidence.read_bytes()).hexdigest()}
    run = write_run_bundle(RELEASE / "runs", result, policy)
    if write_run_bundle(RELEASE / "runs", result, policy) != run:
        raise RuntimeError("The same result did not resolve to the same bundle path.")
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    for name, digest in manifest["artifacts"].items():
        if sha256((run / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"File hash differs from the run manifest: {name}")
    print(f"ZIP import reproduced the folder analysis. Bundle hashes verified.\n{run}")


if __name__ == "__main__":
    main()
