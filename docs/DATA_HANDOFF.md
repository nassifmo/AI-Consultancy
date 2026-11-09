# Data Hand-off: Synthetic Shipment-Enquiry Datasets

From: Mohamad Nassif (data) · To: Bahaa Hamdan (evaluator)

These datasets stand in for what we will later request from a partner company (e.g. CMA CGM).
Every file and field matches the partner data request, so the evaluator built on them should work
on real exports after a field-mapping step. All data is synthetic; all behaviour numbers are
assumptions chosen to test the evaluator, not facts about any company.

## 1. What you receive

Each dataset is a folder (or zip from `python -m datagen.package`):

```
<dataset>/
  exports/          what a partner would give us  -> the evaluator's ONLY input
  ground_truth/     true answers (not included for heldout)  -> for checking the evaluator, never as input
  manifest.json     size and summary (not included for heldout)
  DATA_DICTIONARY.md
  DATA_HANDOFF.md   this guide
```

**Rule: the evaluator must never read `ground_truth/`.** It is only for scoring the evaluator's output.

### Exports (14 files + 2 metadata files)
| File | Contents |
|---|---|
| customers.csv | Pseudonymized customer accounts |
| shipments.csv | Bookings, BL, containers, planned departure/arrival |
| tracking_events.json | DCSA-style events with `event_datetime` (when it happened) and `event_created_datetime` (when systems recorded it) |
| enquiries.csv | Customer enquiries: time, channel, type, the reference the customer quoted |
| agent_runs.json | AI agent runs with tool-call steps, claimed status/ETA, self-reported outcome, tokens, voice seconds |
| responses.csv | Every message to the customer (AI or human): answer, correction or case update, with claimed status/ETA |
| cases.csv / case_history.csv | Escalation and correction cases and their status changes |
| agent_work.csv | Human work items with active time |
| ai_invoice.csv | Monthly AI vendor charges |
| rollout_log.csv | Which arm/version ran when and how traffic was assigned |
| cost_parameters.json | Labour rate, setup, platform and maintenance costs |
| staffing.csv | Headcount, overtime, outsourcing (needed before claiming cash savings) |
| service_rules.yaml | The rules that define "resolved" (thresholds, windows, closure codes) |
| export_metadata.json | Study period, data cutoff, time zone of each file |

Field-level definitions: `DATA_DICTIONARY.md`.

## 2. Things the evaluator must handle (found in the exports on purpose)

- **Time zones.** Cases, case history and human work are in Beirut local time (+02:00/+03:00). Some rows
  lost their offset: read them in the file's time zone from `export_metadata.json`.
- **Population.** Judge in-scope enquiries (`status`, `delay`) received inside the study period. Exports run
  14 days past the period so every enquiry can be followed up.
- **What counts as correct.** Compare a claim with what the tracking data showed *when the answer was given*
  (events with `event_created_datetime` before that time), not with what physically happened.
- **Agent self-reports are not evidence.** About half of failed AI runs report "resolved".
- **References.** Customers quote a booking, BL or container number, sometimes mistyped or for another of
  their shipments.
- **Damaged data.** Duplicate rows, out-of-order rows, technical retries in agent runs, orphan work rows,
  mistyped enquiry IDs, blank fields, conflicting case closures, shipments with no tracking history.
  Recover what can be recovered; return `unknown` where evidence is genuinely missing.

## 3. What the evaluator should output (so it can be scored)

1. **Per enquiry**: state = `resolved` / `escalated_open` / `failed` / `unknown` / `out_of_scope`, plus whether
   the first and final answers were correct, whether escalation was required and done, AI-only, rescued,
   handed off, repeat contact, human seconds. Scored against `ground_truth/true_outcome.csv`
   (`expected_evaluator_state` is the target, since it accounts for missing evidence).
2. **Per arm**: verified resolution rate, AI-only rate, first-answer correctness, false self-report rate,
   human minutes, cost per enquiry and per verified resolution. Scored against
   `ground_truth/planted_effects.json` -> `metrics_by_arm`.
3. **Comparisons**: the effect of each arm vs the baseline and of agent_v2 vs agent_v1, with uncertainty.
   Scored against `comparisons` (randomized datasets) or `counterfactual.*.causal_effects` (rollout datasets).
4. **Economics**: released capacity and realized cash savings reported separately (true cash savings are 0).

## 4. Datasets

| Dataset | Use | What a correct evaluator should find |
|---|---|---|
| tiny | First runs and debugging (~50 enquiries, clean); `review.md` explains every enquiry | Matches review.md row by row |
| dev | Main development set: human, agent_v1, agent_v2 randomized | v2 beats v1 on resolution (~+5 pts) and correctness; both agents cut human time and cost vs human |
| damaged | Robustness | Same metrics as dev within noise; more `unknown` enquiries; no crash |
| null_effect | False-positive test | No real difference between v1 and v2 |
| confounded | Attribution test | Naive before/after is biased; must flag or correct it |
| staged | Rollout by region | Effect close to the counterfactual truth |
| heldout | Final test, settings hidden | Ground truth kept by Mohamad until the evaluator is frozen |

Golden cases: `datagen/scenarios/library.yaml` (35 hand-written cases with expected results, including rule
boundaries). Build them with `python -m datagen.scenario_library --write`. Use them as unit tests.

## 5. Regenerating

Everything is reproducible from the repository:
```
pip install -r requirements.txt
python -m datagen.build_datasets            # all datasets into datagen/datasets/
python -m datagen.scenario_library --write  # golden cases into datagen/datasets/scenarios/
```

## 6. Open items before the evaluator is final
- Review the scenario expected results and the 8 open rule questions in `docs/SCENARIO_REVIEW.md`
  (you implement the rules, so your interpretation must match). Changes go back to Mohamad to regenerate.
- The held-out set will be delivered as exports only.
