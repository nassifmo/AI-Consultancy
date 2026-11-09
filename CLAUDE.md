# FYP: Independent AI Value Evaluator

Read `docs/PROJECT_CONTEXT.md` and `docs/ARCHITECTURE_PLAN.md` before doing any work.

Working rules:
- Base claims on trusted, checked sources (papers, official docs, reputable institutions). Never invent facts or sources.
- Separate what is established from what is proposed or unverified.
- Reports for the advisor: concise, main points only, written as "we".
- Word output: black and white, 12pt minimum, footer = page number only.
- Record new decisions in `docs/PROJECT_CONTEXT.md` (Decisions log).

Code:
- Synthetic data generator lives in `datagen/` (see `datagen/README.md`). Run `python -m pytest -q datagen` before committing.
- `docs/DATA_DICTIONARY.md` is generated from `datagen/dictionary/dictionary.yaml`; edit the YAML, then run `python -m datagen.dictionary_tools render`.
