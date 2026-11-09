"""Generate a synthetic dataset.

    python -m datagen.generate --config datagen/config/tiny.yaml
    python -m datagen.generate --config datagen/config/default.yaml --out /tmp/dev

Implemented: layers 1-7 (world, tracking, enquiries, handling, follow-up, costs, ground truth).
Every written file is validated against the data dictionary; generation fails on any issue.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from datagen.config_schema import GeneratorConfig, ServiceRules, load_config, load_rules
from datagen.dictionary_tools import load_dictionary, validate_records, validate_references
from datagen.generator.costs import ai_invoice_rows, cost_parameters, rollout_rows, staffing_rows
from datagen.generator.enquiries import build_enquiries
from datagen.generator.export import build_tables, handling_tables, write_exports
from datagen.generator.handling import Handled, handle_all
from datagen.generator.model import World
from datagen.generator.review import render_review
from datagen.generator.truth import planted_effects, true_outcome_rows
from datagen.generator.world import build_world

CONFIG_DIR = Path(__file__).resolve().parent / "config"
DATASETS_DIR = Path(__file__).resolve().parent / "datasets"
LAYERS_IMPLEMENTED = ["world", "tracking", "enquiries", "handling", "follow_up", "costs", "ground_truth"]
REVIEW_SHEET_MAX_SHIPMENTS = 60


@dataclass
class Generated:
    cfg: GeneratorConfig
    rules: ServiceRules
    world: World
    handled: Handled
    tables: dict


def rules_for(cfg: GeneratorConfig, config_dir: Path = CONFIG_DIR) -> ServiceRules:
    return load_rules(config_dir / cfg.service_rules_file)


def generate(cfg: GeneratorConfig, rules: ServiceRules | None = None) -> World:
    """Layers 1-5. Returns the world with enquiries (including repeat contacts) handled."""
    return generate_all(cfg, rules).world


def generate_all(cfg: GeneratorConfig, rules: ServiceRules | None = None) -> Generated:
    rules = rules or rules_for(cfg)
    world = build_world(cfg, rules.follow_up.observation_window_days)
    world.enquiries = build_enquiries(cfg, world)
    handled = handle_all(cfg, rules, world)
    tables = {
        **build_tables(world),
        **handling_tables(handled),
        "ai_invoice": ai_invoice_rows(cfg, world, handled),
        "rollout_log": rollout_rows(cfg, world),
        "cost_parameters": [cost_parameters(cfg, world)],
        "staffing": staffing_rows(cfg, world),
        "true_outcome": true_outcome_rows(world, handled),
        "planted_effects": [planted_effects(cfg, rules, world, handled)],
    }
    return Generated(cfg, rules, world, handled, tables)


def summarize(g: Generated) -> dict:
    w, truths = g.world, g.handled.truths
    pop = [t for t in truths if t.in_population and t.in_scope]
    return {
        "customers": len(w.customers),
        "shipments": len(w.shipments),
        "tracking_events": len(w.events),
        "stale_events": sum(e.stale for e in w.events),
        "enquiries": len(w.enquiries),
        "repeat_contacts_generated": sum(q.repeat_of is not None for q in w.enquiries),
        "population_in_scope": len(pop),
        "arm": dict(Counter(t.arm for t in pop)),
        "true_outcome": dict(Counter(t.true_outcome for t in pop)),
        "scenario": dict(sorted(Counter(t.scenario_id for t in truths).items())),
        "agent_runs": len(g.tables["agent_runs"]),
        "cases": len(g.tables["cases"]),
        "human_work_items": len(g.tables["agent_work"]),
        "responses": len(g.tables["responses"]),
    }


def validate_tables(tables: dict[str, list[dict]]) -> list[str]:
    d = load_dictionary()
    issues = [str(i) for key, rows in tables.items() if key != "planted_effects"
              for i in validate_records(key, rows, d)]
    issues += [str(i) for i in validate_references(tables, d)]
    return issues


def run(config_path: Path, out_dir: Path | None = None) -> Path:
    cfg = load_config(config_path)
    rules = rules_for(cfg, Path(config_path).parent)
    g = generate_all(cfg, rules)
    issues = validate_tables(g.tables)
    if issues:
        raise RuntimeError("generated data failed validation:\n" + "\n".join(issues[:50]))

    out_dir = out_dir or DATASETS_DIR / cfg.dataset_name
    for sub in ("exports", "ground_truth"):
        shutil.rmtree(out_dir / sub, ignore_errors=True)
    write_exports(g.tables, out_dir)
    rules_src = Path(config_path).parent / cfg.service_rules_file
    shutil.copyfile(rules_src, out_dir / "exports" / "service_rules.yaml")

    manifest = {
        "dataset_name": cfg.dataset_name,
        "seed": cfg.seed,
        "config_file": str(config_path),
        "config_sha256": hashlib.sha256(Path(config_path).read_bytes()).hexdigest(),
        "rule_version": rules.rule_version,
        "study_period": [g.world.period_start.isoformat(), g.world.period_end.isoformat()],
        "data_cutoff": g.world.data_cutoff.isoformat(),
        "layers": LAYERS_IMPLEMENTED,
        "summary": summarize(g),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    review = out_dir / "review.md"
    if len(g.world.shipments) <= REVIEW_SHEET_MAX_SHIPMENTS:
        review.write_text(render_review(g.world, g.handled) + "\n", encoding="utf-8")
    elif review.exists():
        review.unlink()
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
