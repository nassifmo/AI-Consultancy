"""Build every named dataset and print a summary of what each one plants.

    python -m datagen.build_datasets                  # all datasets
    python -m datagen.build_datasets dev confounded   # selected ones

Datasets (config in datagen/config/, output in datagen/datasets/<name>/):
    tiny         ~50 enquiries, clean, for row-by-row review (committed)
    dev          3 arms (human, agent_v1, agent_v2), randomized, light defects
    damaged      dev with heavy defects
    null_effect  agent_v1 vs an identical agent_v2: true effect is zero
    confounded   before/after rollout coinciding with a delay spike; true effect from counterfactual runs
    staged       staged rollout by region; true effect from counterfactual runs
    heldout      only if datagen/config/heldout.yaml exists (created privately from the template)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from datagen.generate import CONFIG_DIR, run

DATASETS = {
    "tiny": "tiny.yaml",
    "dev": "default.yaml",
    "damaged": "damaged.yaml",
    "null_effect": "null_effect.yaml",
    "confounded": "confounded.yaml",
    "staged": "staged.yaml",
    "heldout": "heldout.yaml",
}
KEY_METRICS = ["verified_resolution_rate", "first_answer_correct_rate", "human_minutes_per_enquiry",
               "variable_cost_per_enquiry"]


def describe(out: Path) -> list[str]:
    pe = json.loads((out / "ground_truth" / "planted_effects.json").read_text())
    summary = json.loads((out / "manifest.json").read_text())["summary"]
    lines = [f"== {pe['dataset_name']}: {summary['enquiries']} enquiries, "
             f"{summary['population_in_scope']} in population, arms {summary['arm']}, "
             f"expected unknown {summary['expected_unknown']}"]
    for pair, c in pe["comparisons"].items():
        same = " (identical behaviour)" if c.get("identical_behaviour") else ""
        lines.append(f"   in-sample {pair}{same}:")
        for k in KEY_METRICS:
            e = c["difference"].get(k)
            if e:
                flag = "detectable" if e.get("detectable") else "NOT detectable"
                lines.append(f"     {k:28s} {e['diff']:+.4f}  (mde_80 {e.get('mde_80', 0):.4f}, {flag})")
    for scope, cf in (pe.get("counterfactual") or {}).items():
        for pair, eff in cf["causal_effects"].items():
            lines.append(f"   TRUE causal effect [{scope}] {pair}: "
                         + ", ".join(f"{k} {eff[k]:+.4f}" for k in KEY_METRICS if k in eff))
    return lines


def main(argv: list[str] | None = None) -> int:
    names = (argv if argv is not None else sys.argv[1:]) or list(DATASETS)
    for name in names:
        config = CONFIG_DIR / DATASETS[name]
        if not config.exists():
            print(f"== {name}: skipped ({config.name} not found)")
            continue
        out = run(config)
        print("\n".join(describe(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
