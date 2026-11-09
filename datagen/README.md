# datagen

Synthetic data generator for the AI customer-service agent value evaluator.
Plan: `docs/SYNTHETIC_DATA_PLAN.md`. Human-readable field list: `docs/DATA_DICTIONARY.md`.

## Step 1 (done): contracts
- `dictionary/dictionary.yaml`: every export file (E1-E13) and ground-truth file, field by field.
  Same files we will request from partner companies.
- `config/service_rules.yaml`: proposed escalation, follow-up, information-check and resolution rules (E12).
- `config/default.yaml`: generator parameters for the `dev` dataset. All numbers are assumptions.
- `config_schema.py`: validates the two YAML configs (probabilities, shares, arms, windows).
- `dictionary_tools.py`: checks the dictionary, validates records and references, renders the Markdown doc.

## Step 2 (done): layers 1-3
- `generator/world.py`: customers, shipments (planned vs actual journey, delay class), DCSA-style tracking
  events with event time and recorded time (some recorded late = stale), ETA estimates that reveal delays.
- `generator/enquiries.py`: baseline enquiries over each shipment's life, extra "delay" enquiries after a delay
  is announced, stated references (booking / BL / container, sometimes mistyped or another shipment).
- `generator/state.py`: `known_state_at` (what systems showed at time t) vs `true_state_at` (what had happened).
- `generator/export.py`: writes E1-E4 to `datasets/<name>/exports/`; every file is validated before writing.
- `generator/review.py`: `review.md` sheet for row-by-row human checking of small datasets.
- `config/tiny.yaml`: ~40-50 enquiries; committed output in `datasets/tiny/` for review.

## Step 3 (done): layers 4-7
- `generator/handling.py`: arm assignment (randomized split, staged rollout, before/after), human handling
  (queue, typo lookups, ETA errors, escalation), AI agent runs (lookup, wrong shipment, stale snapshot,
  unsupported claim, handoff, escalation, self-report), escalation cases (follow-up, closure, or never actioned),
  rescues of bad AI answers, repeat contacts, true outcome per rules, scenario labels S1-S12.
- `generator/costs.py`: AI invoices from run usage, cost parameters, flat staffing (no realized cash savings),
  rollout log.
- `generator/truth.py`: `ground_truth/true_outcome.csv` and `ground_truth/planted_effects.json`
  (true per-arm metrics and differences the evaluator must recover).
- Exports now E1-E14 (E14 `responses.csv` added: every message with stated status/ETA, AI or human).
- Independent contacts about one shipment are spaced `min_days_between_contacts` apart, so recontacts
  inside the repeat window come from handling quality (plus a small noise rate).

## Step 4 (done): rendering and defects
- Case, case-history and human-work files are exported in local time (`Asia/Beirut`, offset kept);
  `exports/export_metadata.json` declares each file's time zone, the study period and the data cutoff.
- All timestamps have whole-second precision.
- `generator/defects.py` injects defects after the clean exports are validated and logs each one in
  `ground_truth/injected_defects.csv`. Recoverable defects (duplicates, retries, out-of-order rows,
  dropped offsets, orphans, ID typos recoverable via another link) leave the expected result unchanged.
  Evidence-removing defects (missing tracking history, blank claim on the final answer, conflicting
  case closure) set `expected_evaluator_state` to `unknown`. The true outcome itself never changes.
- `tiny` has defects disabled (clean, for review). `default` uses light rates; heavy sets come in step 6.

## Step 5 (done, pending review): scenario library
- `scenarios/base.yaml`: hand-written shipments and tracking timelines, plus "what systems showed at time t"
  checks that the tests compare with `generator/state.py`.
- `scenarios/library.yaml`: 35 golden cases (S1-S12, human paths, rule boundaries B1-B10, damaged evidence D1-D7)
  with expected evaluator results, written from the service rules, not the generator code.
- `scenario_library.py`: builds each case into partner-format tables and validates it.
- Review checklist and open questions: `docs/SCENARIO_REVIEW.md`.

## Step 6 (done): named datasets
Configs extend each other (`extends: default.yaml`, deep merge; lists replaced). Build them all with
`python -m datagen.build_datasets`, which prints what each one plants.

| Dataset | Config | What it tests |
|---|---|---|
| tiny | `tiny.yaml` | ~50 enquiries, clean, committed for row-by-row review |
| dev | `default.yaml` | 3 arms (human, agent_v1, agent_v2), randomized, light defects; ~2,500 enquiries per arm so the v2 - v1 effect is detectable |
| damaged | `damaged.yaml` | dev with 5% of every defect type |
| null_effect | `null_effect.yaml` | agent_v2 identical to agent_v1: true effect is zero |
| confounded | `confounded.yaml` | before/after rollout coinciding with a jump in long delays; naive difference is biased |
| staged | `staged.yaml` | staged rollout by region |
| heldout | `heldout.template.yaml` | copied privately to `heldout.yaml` (git-ignored) by the teammate who does not build the evaluator |

`ground_truth/planted_effects.json` now gives every pairwise comparison with its standard error and
`mde_80` (minimum detectable effect, 80% power, 5% two-sided), and for rollout designs
`counterfactual.*.causal_effects`: the true effect from re-running the same world and enquiries with
every enquiry given each arm.

## Commands
```bash
pip install -r requirements.txt
python -m pytest -q datagen
python -m datagen.dictionary_tools check
python -m datagen.dictionary_tools render   # regenerates docs/DATA_DICTIONARY.md
python -m datagen.generate --config datagen/config/tiny.yaml     # -> datagen/datasets/tiny
python -m datagen.generate --config datagen/config/default.yaml  # -> datagen/datasets/dev (not committed)
python -m datagen.scenario_library --write                       # -> datagen/datasets/scenarios/<id> (not committed)
python -m datagen.build_datasets                                 # all named datasets (~40 s)
```
