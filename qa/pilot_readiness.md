# Synthetic pilot rehearsal

Run this check from the shipment benchmark directory. It prepares the same synthetic enquiry from four variations of the mixed-format source extract. It checks that each draft is blocked, approves the reviewed export, and compares the evaluator's result with expected findings read directly from the fixture. No network access or company records are used.

```powershell
.venv/Scripts/python.exe -B -m qa.pilot_readiness
```

| Input | Expected result |
|---|---|
| Complete extract | The AI looked up a sibling container and gave the wrong status. The enquiry resolved after a verified human correction and 300 seconds of logged work. |
| Partial work log with a repeated row | The documented subtotal stays at 300 seconds. The complete active work duration remains unknown. |
| Missing response history | Reply accuracy, initial failure, recovery and outcome remain unknown. The work record still supports 300 seconds. |
| Malformed row in tracking history | Preparation reports the malformed row. The wrong-container failure remains verifiable. Recovery and final resolution remain unknown because the tracking history is incomplete. |

All four cases lack assignment and finance records. The result withholds the policy comparison and complete costs. The check also traces the work finding to its source row, verifies hashes against retained source files and compares each analysis with its repeat. The command prints JSON with the import and run identifiers and returns a nonzero exit status if any expected finding differs. Temporary inputs and imports are removed on exit.

This exercise establishes repeatability and handling of specific evidence gaps. Company accuracy, workflow coverage, business value and attribution require a separate validation with an authorized pilot sample.

## Replaying the first authorized sample

1. Record the source counts, extraction window and access scope with each data owner. Use a consistent identifier for the same shipment or enquiry across files. Record which histories the extracts cover.
2. Freeze the extraction, mapping, grading policy and comparison settings. Ask operations reviewers to check selected source cases independently before they see evaluator findings. Include correct replies, wrong references, escalation or correction, and ambiguous or missing evidence.
3. Reconcile the evaluator's findings with the reviewers' answers and record disagreements by criterion. Check that every material finding can be traced back to the original row. Correct the mapping or rules in a new version and replay the same sample. Keep unresolved interpretation gaps visible.
4. Confirm the minimum service and safety criteria with the service owner, and confirm scoped costs and any business-value assumption with finance. Treat the sample as descriptive until the allocation records and study design support a policy comparison. This validation run does not open production access or change rollout scope.
