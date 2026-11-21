# How to check the shipment evaluator

Start with two cases and one calculation. Write down what you expect before opening a result. Agree with Mohamad on what should count as a pass. This is a check of our current prototype, not a certification of a carrier's deployment.

| Check | What you should see | What would make us stop |
| --- | --- | --- |
| R02, delay enquiry | The original plan is 12 March at 10:00 UTC and the latest visible estimate is 14 March at 14:00 UTC. The difference is 52 hours. Under the synthetic rule, the agent must open an operations case. A reply that says it opened a case cannot pass without the actual case event. The case starts open. | A made-up case ID counts as a successful escalation, or opening the case counts as resolving it. |
| R05, sibling containers | The requested container is TEST-BOX-1. Its vessel arrived. The discharge event is for TEST-BOX-2. A reply that uses the other container's event is a critical failure. | The evaluator accepts the wrong container or its tracking event. |
| Cost per improvement | The example spends USD 0.80 more per enquiry for 20 additional timely, correct resolutions per 100 comparable enquiries: USD 80 divided by 20 gives USD 4. | It divides by all resolutions or adds the dollar value of time released to the same expense savings. |
| Missing financial or service evidence | With no downstream expense records, overall net reduction is unknown and the handling-only USD 4 point estimate still shows. If unknown outcomes could erase the improvement, there is no finite worst-case break-even value. | Missing expense is treated as zero, or an uncertain point value is presented as a ceiling. |

The R02 and R05 claims were exercised with scripted provider outputs. The financial example and both missing-evidence variants were run locally. No model API, company system or financial record was used.

## Reproduce the important checks

From the shipment benchmark folder:

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_replay_world.py tests/test_replay_runner.py tests/test_pilot_economics.py
.venv/Scripts/python.exe -m evaluator.pilot_economics pilot_prospect/ECONOMICS_EXAMPLE.json
```

The dashboard displays the earlier synthetic benchmark and its recommendations. The new replay and pilot finance calculator run locally from the command line. To explore the evidence in the dashboard, open S32: the initial wrong-container answer remains a critical failure even after a later human correction.

## First run with keys

Use the [local replay instructions](REPLAY_QUICKSTART.md). Run five cases on each model. Open `summary.json` first and verify that all five pairs ran. Review the ten original replies and recorded actions in `trials.jsonl`. A run can finish successfully even when an agent fails a case. Missing output, incomplete usage or rejected calls require diagnosis before increasing volume.

1. **Connection and evidence:** five pairs with a valid final answer on each side, linked tool outcomes, actual model identifiers, latency and reported token usage. Review the charges in the provider account.
2. **Judgment:** have Mohamad label the ten anonymized replies and actions without the model labels or grades. Check wording as well as structured fields. Log disagreements, with the source record for each. Stop and investigate an unsupported pass, especially on escalation, account ownership, or container identity.
3. **Unseen cases:** freeze the runner, service rules and rubric after the smoke test. Use a separately authored suite. Its results check model and evaluator behavior in a sandbox. Keep sampled failures, missing records and ungraded trials visible.
4. **Company finances:** agree which payer and workflow are in scope. Use comparable company data and reconcile costs, staffing and shipment-linked charges. If the records cannot establish financial impact, use the break-even or stay with operational measures. The company owner approves any action.

One-off smoke-test success is evidence the test works for those cases. It does not establish a winner, company accuracy, or realized ROI.
