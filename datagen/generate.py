"""Generate a synthetic dataset.

    python -m datagen.generate --config datagen/config/tiny.yaml
    python -m datagen.generate --config datagen/config/default.yaml --out /tmp/dev

Implemented: all layers (world, tracking, enquiries, handling, follow-up, costs, ground truth,
rendering, defect injection).
Clean exports are validated against the data dictionary before defects are injected;
generation fails on any issue.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from datagen.config_schema import GeneratorConfig, ServiceRules, load_config, load_rules
from datagen.dictionary_tools import load_dictionary, validate_records, validate_references
from datagen.generator.defects import inject
from datagen.generator.costs import ai_invoice_rows, cost_parameters, rollout_rows, staffing_rows
from datagen.generator.enquiries import build_enquiries
from datagen.generator.export import build_tables, datetime_fields, handling_tables, localize, write_exports
from datagen.generator.handling import Handled, handle_all
from datagen.generator.model import World
from datagen.generator.review import render_review
from datagen.generator.truth import counterfactual_metrics, planted_effects, true_outcome_rows
from datagen.generator.world import build_world

CONFIG_DIR = Path(__file__).resolve().parent / "config"
DATASETS_DIR = Path(__file__).resolve().parent / "datasets"
LAYERS_IMPLEMENTED = ["world", "tracking", "enquiries", "handling", "follow_up", "costs", "ground_truth",
                      "rendering", "defects"]
REVIEW_SHEET_MAX_SHIPMENTS = 60


@dataclass
class Generated:
    cfg: GeneratorConfig
    rules: ServiceRules
    world: World
    handled: Handled
    tables: dict  # final exports + ground truth, with defects injected (what gets written)
    clean_tables: dict  # the same before defect injection (validated against the dictionary)
    clean_issues: list[str]


def rules_for(cfg: GeneratorConfig, config_dir: Path = CONFIG_DIR) -> ServiceRules:
    return load_rules(config_dir / cfg.service_rules_file)


def counterfactual_runs(cfg: GeneratorConfig, rules: ServiceRules) -> dict:
    """Handle the same world and enquiry stream once per arm, with every enquiry given that arm."""
    runs = {}
    for arm in cfg.design.arms:
        data = cfg.model_dump()
        other = next(a.name for a in cfg.design.arms if a.name != arm.name)
        data["design"] = {"type": "randomized_split", "rollout_date": None,
                          "arms": [{"name": arm.name, "share": 1.0}, {"name": other, "share": 0.0}]}
        data["counterfactuals"] = False
        one = GeneratorConfig.model_validate(data)
        world = build_world(one, rules.follow_up.observation_window_days)
        world.enquiries = build_enquiries(one, world)
        runs[arm.name] = handle_all(one, rules, world).truths
    return runs


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
        "planted_effects": [planted_effects(
            cfg, rules, world, handled,
            counterfactual_metrics(cfg, counterfactual_runs(cfg, rules), world) if cfg.counterfactuals else None)],
    }
    d = load_dictionary()
    localize(tables, cfg.rendering.local_time_files, cfg.rendering.local_timezone, d)
    clean_issues = validate_tables(tables)
    clean = copy.deepcopy(tables)
    dt_fields = {k: datetime_fields(k, d) for k in cfg.rendering.local_time_files}
    tables["injected_defects"] = inject(cfg, tables, handled, dt_fields)
    return Generated(cfg, rules, world, handled, tables, clean, clean_issues)


def export_metadata(g: Generated) -> dict:
    """What a partner would tell us about the export (time zones, window, rule version)."""
    r = g.cfg.rendering
    return {
        "study_period": [g.world.period_start.isoformat(), g.world.period_end.isoformat()],
        "data_cutoff": g.world.data_cutoff.isoformat(),
        "rule_version": g.rules.rule_version,
        "timezones": {f: (r.local_timezone if f in r.local_time_files else "UTC") for f in
                      ["customers", "shipments", "tracking_events", "enquiries", "agent_runs", "cases",
                       "case_history", "agent_work", "responses", "ai_invoice", "rollout_log", "staffing"]},
        "notes": "Timestamps carry a UTC offset. If an offset is missing, interpret it in the file's time zone above.",
    }


def summarize(g: Generated) -> dict:
    w, truths = g.world, g.handled.truths
    pop = [t for t in truths if t.in_population and t.in_scope]
    defects = g.tables.get("injected_defects", [])
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
        "defects_injected": dict(sorted(Counter(x["defect_type"] for x in defects).items())),
        "expected_unknown": sum(r["expected_evaluator_state"] == "unknown" for r in g.tables["true_outcome"]),
    }


def validate_tables(tables: dict[str, list[dict]]) -> list[str]:
    d = load_dictionary()
    issues = [str(i) for key, rows in tables.items() if key not in ("planted_effects", "injected_defects")
              for i in validate_records(key, rows, d)]
    issues += [str(i) for i in validate_references(tables, d)]
    return issues


def run(config_path: Path, out_dir: Path | None = None) -> Path:
    cfg = load_config(config_path)
    rules = rules_for(cfg, Path(config_path).parent)
    g = generate_all(cfg, rules)
    issues = g.clean_issues + [str(i) for i in validate_records("injected_defects", g.tables["injected_defects"])]
    if issues:
        raise RuntimeError("generated data failed validation:\n" + "\n".join(issues[:50]))

    out_dir = out_dir or DATASETS_DIR / cfg.dataset_name
    for sub in ("exports", "ground_truth"):
        shutil.rmtree(out_dir / sub, ignore_errors=True)
    write_exports(g.tables, out_dir)
    rules_src = Path(config_path).parent / cfg.service_rules_file
    shutil.copyfile(rules_src, out_dir / "exports" / "service_rules.yaml")
    (out_dir / "exports" / "export_metadata.json").write_text(json.dumps(export_metadata(g), indent=2) + "\n",
                                                              encoding="utf-8")

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
