# Shipment support pilot intake and validation

## 1. Agree on the decision and scope

Choose one support channel, a segment of shipment-status and delay enquiries, and one handling comparison. Record who owns the decision, the outcome they want to improve, and the quality limits the agent must meet. Examples include wrong-container answers, missed escalations, and responses that arrive too late for an operational decision. Record the scope, time window, follow-up period, and known process or release changes.

Begin with one bounded sample of **30–50 consecutive in-scope initial enquiries** and the events needed to follow them. If rare but consequential cases are absent, request **up to 10 additional cases** covering examples such as wrong-container information, human correction and missing tracking history. Use those cases to test specific rules and keep them separate from the consecutive sample. These are proposed starting sizes for checking feasibility and reviewing cases. A later impact study needs a separately justified size, comparator and follow-up.

## 2. Obtain authorized evidence

Agree with the company on pseudonymization, access, transfer, storage and deletion before extraction. Preserve stable keys across the supplied records. Minimize the free text and identifiers in the extract while keeping the evidence needed to verify what the customer asked and what the answer said. Start with scoped exports and consider a read-only connector once the source owner confirms the endpoint, permissions, history and export behavior.

| Company contact | First sample requirements |
| --- | --- |
| Support owner and CRM contact | In-scope enquiry counts, receipt times, request text or intent, sent replies, stable case and contact links, escalation and follow-up history, final status and resolution evidence |
| Tracking or operations owner | Linkable booking and container references, milestone and location, planned/estimated/actual classification, event time and publication time, and available corrections |
| AI or integration owner | Agent and version, request/run/reply links, completed actions, failures, retries, handoffs and usage where available |
| Operations and finance, when applicable | Observed active-work records and their timing method, comparable labour and usage rates, invoice or spending records, and the payer and final amount for any downstream charge being evaluated |
| Rollout or experiment owner, when applicable | Intended handling policy recorded before exposure, eligibility, release changes, comparator assignment or rollout schedule, and any known contamination between groups |

The support owner sets operating rules and guardrails. Data owners reconcile the extracts and attest to their coverage. Two suitable reviewers label the selected feasibility cases independently using the same source evidence. The project team maps the data, runs the frozen evaluator, explains discrepancies and publishes results. The named company owner decides whether the resulting action is appropriate.

## 3. Validate before advancing

| Gate | Proposed pass criteria | If the gate remains open |
| --- | --- | --- |
| Source fit | Reconcile population and table counts to the extract scope. Explain unmatched identifiers, duplicates, revisions and missing history. Verify time zone, event time and publication time on reviewed records. | Repair the mapping or restrict the supported findings to the verified subset. |
| Case verification | Review each selected enquiry for shipment identity, evidence visible at reply time, required actions, and final outcome. Reconcile every discrepancy. Block the affected rule if a critical handling error is missed, an unsupported resolution is reported, or records link to the wrong customer's shipment. Keep uncertain findings visible. | Adjudicate against source records and confirm the revised policy on additional cases. Hold the affected automatic finding until review passes. |
| Effort and cost | Reconcile a sample of measured durations and cost lines to the source and agree the applicable rates, currency, scope and shared-cost treatment. | Show only supported quantities, such as elapsed service time or a documented cost subtotal. |
| Comparative evidence | Prespecify eligibility, assignment unit, comparator, observation period, coverage floors and a minimum worthwhile improvement before estimating the effect. Confirm the available design can support attribution and meet the minimum scale. | Keep the findings descriptive. Improve tracking or run a controlled comparison where feasible. |
| Decision support | Have the decision owner check that the proposed action follows the agreed service limits, economic criteria and evidence. Record the rationale, material uncertainty, next action, owner and recheck point. | Propose a bounded follow-up, such as collecting a missing field, keeping human review or comparing a specific change. |

Classify documented active time, capacity released, company cash changes and customer cost consequences separately. For example, a failed truck trip requires evidence of the dispatch decision, when the correct pickup information was available, the final cost or credit and who paid it. A tariff alone supplies a potential charge under stated terms. A company claim needs the actual evidence and a defensible comparison.

## Before and during the pilot

| Before a company shares records | Once the company authorizes a pilot |
| --- | --- |
| Rehearse file preparation, record linking, incomplete-data handling, comparison and exports with synthetic records. Test independent held-out cases once they are available. Prepare review sheets and synthetic tests for decision thresholds and clear reasons to defer an action. | Verify the partner’s sources and text, calibrate and freeze service and decision rules, validate individual findings, and confirm which measures the sources support. Test a credible comparison with the follow-up and volume it needs. |
| Demonstrate that outputs trace to their inputs and that changed assumptions can change the recommended action. | Have the decision owner review the evidence and the proposed action. Assess realized results only when the supporting company records and comparison are available. |

[Independent review sheet](INDEPENDENT_REVIEW_SHEET.md) · [Pilot preparation guide](../PILOT_PREPARATION.md) · [Detailed data dictionary](../docs/DATA_DICTIONARY.md) · [Test report](../TEST_REPORT.md)
