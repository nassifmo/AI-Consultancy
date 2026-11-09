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

## Commands
```bash
pip install -r requirements.txt
python -m pytest -q datagen
python -m datagen.dictionary_tools check
python -m datagen.dictionary_tools render   # regenerates docs/DATA_DICTIONARY.md
python -m datagen.generate --config datagen/config/tiny.yaml     # -> datagen/datasets/tiny
python -m datagen.generate --config datagen/config/default.yaml  # -> datagen/datasets/dev (not committed)
```
