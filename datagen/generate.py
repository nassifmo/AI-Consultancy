"""Generate a synthetic dataset.

    python -m datagen.generate --config datagen/config/tiny.yaml
    python -m datagen.generate --config datagen/config/default.yaml --out /tmp/dev

Implemented so far: layers 1-3 (customers, shipments, tracking events, enquiries).
Every written file is validated against the data dictionary; generation fails on any issue.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from datagen.config_schema import GeneratorConfig, load_config
from datagen.dictionary_tools import load_dictionary, validate_records, validate_references
from datagen.generator.enquiries import build_enquiries
from datagen.generator.export import build_tables, write_exports
from datagen.generator.model import World
from datagen.generator.review import render_review
from datagen.generator.world import build_world

DATASETS_DIR = Path(__file__).resolve().parent / "datasets"
LAYERS_IMPLEMENTED = ["world", "tracking", "enquiries"]
REVIEW_SHEET_MAX_SHIPMENTS = 60


def generate(cfg: GeneratorConfig) -> World:
    world = build_world(cfg)
    world.enquiries = build_enquiries(cfg, world)
    return world


def summarize(w: World) -> dict:
    return {
        "customers": len(w.customers),
        "shipments": len(w.shipments),
        "tracking_events": len(w.events),
        "stale_events": sum(e.stale for e in w.events),
        "enquiries": len(w.enquiries),
        "delay_class": dict(Counter(s.delay_class for s in w.shipments)),
        "enquiry_type": dict(Counter(q.enquiry_type for q in w.enquiries)),
        "reference_kind": dict(Counter(q.reference_kind for q in w.enquiries)),
        "channel": dict(Counter(q.channel for q in w.enquiries)),
    }


def validate_tables(tables: dict[str, list[dict]]) -> list[str]:
    d = load_dictionary()
    issues = [str(i) for key, rows in tables.items() for i in validate_records(key, rows, d)]
    issues += [str(i) for i in validate_references(tables, d)]
    return issues


def run(config_path: Path, out_dir: Path | None = None) -> Path:
    cfg = load_config(config_path)
    world = generate(cfg)
    tables = build_tables(world)
    issues = validate_tables(tables)
    if issues:
        raise RuntimeError("generated data failed validation:\n" + "\n".join(issues[:50]))

    out_dir = out_dir or DATASETS_DIR / cfg.dataset_name
    write_exports(tables, out_dir)
    manifest = {
        "dataset_name": cfg.dataset_name,
        "seed": cfg.seed,
        "config_file": str(config_path),
        "config_sha256": hashlib.sha256(Path(config_path).read_bytes()).hexdigest(),
        "layers": LAYERS_IMPLEMENTED,
        "summary": summarize(world),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if len(world.shipments) <= REVIEW_SHEET_MAX_SHIPMENTS:
        (out_dir / "review.md").write_text(render_review(world) + "\n", encoding="utf-8")
    return out_dir


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args(argv)
    out = run(args.config, args.out)
    print(f"wrote {out}")
    print(json.dumps(json.loads((out / "manifest.json").read_text())["summary"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
