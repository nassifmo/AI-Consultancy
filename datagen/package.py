"""Package generated datasets for hand-off to the evaluator builder.

    python -m datagen.package                     # every built dataset -> datagen/handoff/<name>.zip
    python -m datagen.package heldout             # selected ones

Each zip holds exports/, manifest.json, the data dictionary and the hand-off guide.
ground_truth/ is included for development datasets so the evaluator can be checked while it is
built, and NEVER for `heldout` (its answers stay with the data owner until the evaluator is frozen).
Build the datasets first with `python -m datagen.build_datasets`.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATASETS_DIR = ROOT / "datasets"
HANDOFF_DIR = ROOT / "handoff"
DOCS = [ROOT.parent / "docs" / "DATA_HANDOFF.md", ROOT.parent / "docs" / "DATA_DICTIONARY.md"]
HIDDEN_TRUTH = {"heldout"}


def package(name: str, out_dir: Path = HANDOFF_DIR, datasets_dir: Path = DATASETS_DIR) -> Path:
    src = datasets_dir / name
    if not (src / "exports").exists():
        raise FileNotFoundError(f"{src} not built; run python -m datagen.build_datasets {name}")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{name}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for sub in ["exports"] + ([] if name in HIDDEN_TRUTH else ["ground_truth"]):
            for f in sorted((src / sub).rglob("*")):
                if f.is_file():
                    z.write(f, f"{name}/{f.relative_to(src)}")
        if name not in HIDDEN_TRUTH:  # heldout manifest and review sheet would reveal its settings/answers
            for extra in ("manifest.json", "review.md"):
                if (src / extra).exists():
                    z.write(src / extra, f"{name}/{extra}")
        for doc in DOCS:
            if doc.exists():
                z.write(doc, f"{name}/{doc.name}")
    return target


def main(argv: list[str] | None = None) -> int:
    names = (argv if argv is not None else sys.argv[1:]) or sorted(
        p.name for p in DATASETS_DIR.iterdir() if (p / "exports").exists() and p.name != "scenarios")
    for name in names:
        path = package(name)
        hidden = " (ground truth withheld)" if name in HIDDEN_TRUTH else ""
        print(f"{path} {path.stat().st_size / 1e6:.1f} MB{hidden}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
