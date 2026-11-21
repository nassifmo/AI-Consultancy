# Shipment enquiry benchmark

The app extends Mohamad Nassif's [data handoff at commit 26e0206](https://github.com/nassifmo/AI-Consultancy/tree/26e0206a311f75641e1f4321b79eb95aabc60ac3) as its base. The original library, coverage cases and case outcome snapshots test earlier rule versions. The [grading cases](datagen/scenarios/eta_accuracy.yaml) exercise the contextual rubric in the [scoring rules](RULES_FOR_REVIEW.md). Each export identifies its applicable rule version.

The [evaluator](EVALUATOR_GRADING.md) links the exported records, verifies each enquiry and selects grading methods by request and criterion. The output includes source references, the initial findings, the final outcome, and recorded human work.

## Run the meeting release

From a fresh checkout, use Python 3.11 to install the environment and generate the demo exports. On Windows:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-lock.txt
.venv/Scripts/python.exe -m datagen.scenario_library --write
.venv/Scripts/python.exe -m datagen.build_datasets --out-root datagen/datasets/release_1 demo
.venv/Scripts/python.exe -m streamlit run app.py --server.address 127.0.0.1
```

The lock file records the tested Windows and Python 3.11 environment. `requirements-release.txt` lists the direct dependencies if you need to set up another supported platform. Keep the launch terminal open while using the app.

After setup, you can also double-click `Launch evaluator.cmd` on Windows.

Choose **Three handling policies · clean demo**, leave follow-up at **7 days**, then select **Run evaluation**. Use **S32 · Wrong container with human recovery** for the case walkthrough. See the [five-minute meeting guide](MEETING_DEMO.md), [advisor summary](ADVISOR_SUMMARY.md), and [test report](TEST_REPORT.md). To try **Upload an exports ZIP**, generate `meeting_release/demo_exports.zip` with the packaging command below.

### Prepare for a company pilot

Start with the [client one-pager](pilot_prospect/PILOT_ONE_PAGER.html), the [five-minute pilot demo](pilot_prospect/FIVE_MINUTE_DEMO.md) and the [sample decision brief](pilot_prospect/DEMO_DECISION.html). Use the [intake and validation plan](pilot_prospect/INTAKE_AND_VALIDATION.md) and [independent review sheet](pilot_prospect/INDEPENDENT_REVIEW_SHEET.md) to scope a first authorized sample. The [synthetic pilot rehearsal](qa/pilot_readiness.md) reproduces the full preparation and analysis path on complete and damaged inputs.

Open **Prepare company files** to preview a ZIP of CSV, JSON or JSONL extracts through a versioned mapping profile. Use **Preview synthetic company extract** to try the process. Save the prepared files, choose **Run evaluation**, and review which measurements the data can support. The original records and mapping remain traceable in a local import bundle.

The [pilot preparation guide](PILOT_PREPARATION.md) describes required records, missing-data behavior and remaining company-specific work. The [mapping guide](pilot/README.md) explains field profiles. A [read-only API collector](acquisition/README.md) prepares JSON extracts once a company endpoint and permissions are confirmed. Its pagination, retries and incomplete-run behavior are tested with mocked responses.

For the new offline rehearsal and first live model run, see the [replay guide](docs/REPLAY_QUICKSTART.md) and [readiness walkthrough](docs/READINESS_WALKTHROUGH.md). For the separate financial comparison, see the [pilot economics contract](docs/PILOT_ECONOMICS_CONTRACT.md).

### Compare cost against your service priority

The **Decision and next action** panel checks the selected critical failure limit, evidence for attribution, cost completeness and the stated basis for a business value before suggesting a step. Open **Decision evidence and downloads** for the linked critical cases and a shareable decision brief. Suggested actions go to the responsible service owner for review.

After running an evaluation, open **Upgrade value**. Choose a pair of handling policies and the outcome you want to value. You can use a verified correct first answer, a verified resolution, or a verified resolution within a time target you set. Each outcome uses all eligible requests as its denominator. The existing **Comparison** view also reports first-answer accuracy among assessable replies.

When the more expensive option improves your chosen outcome, break-even is the extra cost per request divided by the increase in the outcome rate. Enter your own value per additional success to see how it compares with the cost. The table keeps the other service measures visible. For a cheaper option with fewer successes, the threshold shows how much a lost success would need to be worth to cancel the cost reduction. The downloadable assessment records the selected assumptions and the source run identifier.

The ranges vary unknown outcomes while holding reported costs and your entered value fixed. Use the ledger to check the cost scope and avoid counting labour reductions twice. The demo uses synthetic data and the dollar amount you enter is a scenario assumption. [HM Treasury guidance on switching values](https://www.gov.uk/government/publications/the-green-book--2/the-green-book-2026#sensitivity-analysis-and-switching-values)

### Run the command-line analysis

The same analysis runs from the command line. Use `--analysis-config` with an optional JSON file to override the saved defaults.

```powershell
.venv/Scripts/python.exe -m evaluator --exports datagen/datasets/release_1/demo/exports --analyze --output-dir runs
```

The analysis writes JSON to standard output. An optional output directory saves an immutable run bundle with results, source hashes, versions, policy, configuration and download files. It publishes the bundle only after its files are complete. Set `--output-dir` to a directory beside the source export, such as `runs`.

If generated exports are absent, follow the [dataset generation instructions](datagen/RELEASE_1_DATASETS.md). Give the application a ZIP containing the recognized files directly under `exports/`. Bring benchmark answers into the separate test process.

Run the generator and evaluator tests after the setup above:

```powershell
.venv/Scripts/python.exe -m pytest -q datagen/tests tests
.venv/Scripts/python.exe -m qa.pilot_readiness
.venv/Scripts/python.exe -m qa.package_meeting_release
```

For the full synthetic compatibility check, generate the six additional named datasets before packaging:

```powershell
.venv/Scripts/python.exe -m datagen.build_datasets --out-root datagen/datasets/release_1 tiny dev damaged null_effect confounded staged
.venv/Scripts/python.exe -m qa.package_meeting_release --bulk
```

Scenario and bulk datasets, analysis runs and import bundles are generated locally. The repository retains the original small `tiny` dataset for historical review. The current runs start from regenerated `release_1` exports.

## Run the benchmark

From this folder, in a Python environment with the listed dependencies:

```sh
python -m pip install -r requirements.txt
python -m datagen.dictionary_tools check
python -m datagen.scenario_library --write
python -m unittest discover -s tests -v
python -m evaluator --exports datagen/datasets/scenarios/S30/exports
```

Each case is written to `datagen/datasets/scenarios/<case-id>/`. Give the evaluator only the directory named `exports`. Use `ground_truth/expected.json` to score its output separately. Fixture exports contain the timing and rule version needed to judge each case. The input field definitions are in the [data dictionary](docs/DATA_DICTIONARY.md).

Fixtures through `0.3.0-proposed` retain their earlier expectations. The case outcome and grading cases set an explicit data cutoff for each snapshot. A cutoff says when the evidence ends. The seven-day repeat check has its own timing. Before running one unified suite under the revised rules, review historical cases where the policy would change the answer, including B1, B6, B8, S8, B9, D4 and S20. These are synthetic acceptance cases. The coverage question for a real pilot requires a de-identified support sample.

Each scenario has one expected-results file keyed by enquiry ID. A scenario with two contacts has two entries in that file. The scenario passes when all its entries match. Five scenarios have two entries, so the current 56 scenarios contain 61 expected enquiry results.

To integrate into the handoff repository, carry over the extension files, the scenario compiler, dictionary and CSV export changes together. The random dataset still uses the handoff's original scoring assumptions.

## Additional cases

| Case | Evidence and expected outcome |
| --- | --- |
| S13 | The agent requests the missing reference. The customer confirms it, then receives a correct answer within the same enquiry. Resolved. |
| S14 | Two valid references identify different bookings. The agent asks which booking to use. Awaiting customer at cutoff. |
| S15 and S16 | The two containers have different visible tracking events. A correct report of no recorded unloading for the requested container resolves the request. Using its sibling's unloading event fails. |
| S17 | The customer follows up about the promised written confirmation. The original fails the qualifying repeat check. A subsequent human response provides the confirmation. |
| S18 | The same customer asks about a newly issued ETA. The two correct answers each resolve their own enquiry. |
| S19 | A qualifying delay enters tracking during the wait. Opening the escalation 1 hour and 45 minutes after that update meets the proposed trigger rule. Required follow-up and closure resolve the enquiry. |
| S20 | A timely escalation and update end with a customer-unreachable closure. The enquiry fails the resolution check. |
| S21 and S22 | A transshipment arrival is mistaken for final arrival in one answer. The other identifies the intermediate port and gives the supported final ETA. The first fails and the second resolves. |
| S23 and S24 | Two observations of the same escalation. The first captures an open case. The second captures a valid resolution after day 14, including the additional human work. |
| S25 and S26 | One case has an evidenced unsuccessful closure. The other has a recorded closing event with insufficient evidence to verify the result. |
| S27 | The same documented resolution as S24, with visible AI and human actions and no active-work records. The outcome is resolved and human effort is unknown. |
| S28–S30 | Matching local time has zero error. One minute later is minor for routine tracking and material when it changes the answer at a documented staffing cutoff. |
| S31 | The team resolves an enquiry and the escalation deadline was missed by one second. Both results are recorded. |
| S32 and S33 | An agent uses the wrong container or omits a required escalation. The initial critical failure stays visible when a human resolves the enquiry. |
