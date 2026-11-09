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

## Commands
```bash
pip install -r requirements.txt
python -m pytest -q datagen
python -m datagen.dictionary_tools check
python -m datagen.dictionary_tools render   # regenerates docs/DATA_DICTIONARY.md
```
