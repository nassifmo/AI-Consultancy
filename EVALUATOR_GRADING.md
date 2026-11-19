# Verifying and grading shipment enquiries

The grading layer accepts a request type and verified evidence from the shipment evaluator. Its versioned policy determines which checks apply and how to grade them. The initial request types are shipment status, arrival coordination and shipment delay. A new request type can reuse existing grading methods by declaring its criteria in the [policy](evaluator/policy.json). This follows the practice of choosing the scoring format per metric. [ServiceNow evaluation metrics](https://www.servicenow.com/docs/r/intelligent-experiences/mon-ai-evaluation-metrics-reference.html)

| Check | Grade |
| --- | --- |
| Shipment identity | Verify that the reply covers the requested shipment or container. A proven initial failure receives a critical flag. |
| Milestone status | Check a status claim against the linked tracking evidence when it is part of the reply or request. |
| ETA accuracy | Record the signed time difference from the carrier's reference. When the case has a documented decision cutoff, check whether the error changes the decision. |
| Arrival coordination | Independently check whether the reply names the right monitoring team for the documented cutoff. |
| Escalation and follow-up deadlines | Check the exact deadline and measure the seconds overdue. Completion at or before the deadline has zero lateness. |
| Initial escalation steps | Check each expected action. Award partial credit when the step evidence is complete and some steps are met. Keep proven critical omissions visible. |

An established false applicability condition produces `not_applicable`. A missing condition or missing evidence produces `unknown`. Supply a failed check or missing action as false only when the evidence establishes it. Leave unverified values absent or null. A measurable ETA error can still have unknown severity when the customer's context is incomplete. Each result includes the policy version, the checks, their source references, and the independently verified outcome where supplied. A severe initial handling failure stays visible when a later human correction resolves the request.

## Timing score configuration

The policy can set positive `zero_score_early_seconds` and `zero_score_late_seconds` for a distance check, or only `zero_score_late_seconds` for a deadline. An enabled score drops linearly from 100 at zero error to zero at the configured distance. A deadline uses lateness as its distance. Each request type can reference a criterion with its own range. Choose ranges with workflow owners using realistic request examples. The shipped policy reports the measured times and has no assumed numeric scoring ranges.

## Run from exported records

From this folder, with the benchmark dependencies installed, run:

```sh
python -m evaluator --exports datagen/datasets/scenarios/S30/exports
```

The verifier reads the whitelisted shipment, tracking, enquiry, agent and case records inside the supplied `exports` folder. It checks shipment ownership and container identity, then compares the first answer against the tracking records visible when it was sent. It checks the CRM route, follow-up and case history separately. It uses the export's cutoff as the last observation time and records the actual closure date when a resolution is verified.

The JSON includes the initial and last replies, whether their facts match the records, the contextual grades and the outcome. Human work uses exported active durations, with missing or inconsistent coverage shown as unknown. When only part of the work is documented, the output retains the supported subtotal and record references. A verified recovery leaves the initial critical flag visible. The recontact check requires a reliable link and evidence that the customer is pursuing the same unresolved request. Missing links or incomplete follow-up can leave this check unknown.

The policy settings for the synthetic benchmark include a delay trigger, escalation and follow-up deadlines, a recontact window, and the tested minor timing examples. The included text rules cover the documented fixture phrasing and structured fields. Additional client phrasing, port data, logging coverage and service policies need calibration and review. The ETA check measures the quoted time against the source available at reply time. It provides no measure of forecast error against eventual arrival unless that actual milestone was already available when answering.

Run `python -m unittest discover -s tests -v` after generating the scenario exports. The tests compare selected end-to-end outputs with the benchmark answers and run every scenario through the input path. The answers sit outside the runtime input. Earlier fixtures and the six bulk datasets retain older rule versions, recorded separately from the applied policy version, so a run on those data does not establish label agreement. The evaluator currently verifies each enquiry. Causal and financial estimates require a separate comparison.

## Run from normalized evidence

Run `python -m evaluator enquiry.json` from this folder, or use `python -m evaluator -` and supply the enquiry JSON on standard input. An optional `--policy` points to a versioned alternative. The Python entry point is `evaluator.grade_enquiry(policy, enquiry)`.

Here is normalized evidence for an arrival decision, using the dates and scoped tracking reference in benchmark case S30.

```json
{
  "enquiry_id": "ENQ-S28",
  "profile": "arrival_coordination",
  "conditions": { "status_reply_in_scope": false },
  "evidence": {
    "shipment_identity": {
      "passed": true,
      "refs": ["shipments.csv#BKG-T-D24", "responses.csv#RSP-S30-AI1"]
    },
    "coordination_eta": {
      "reference_at": "2026-03-16T10:00:00+00:00",
      "observed_at": "2026-03-16T11:01:00+01:00",
      "decision_cutoff_at": "2026-03-16T11:00:00+01:00",
      "refs": ["tracking_events.json#E-24C", "responses.csv#RSP-S30-AI1", "enquiries.csv#ENQ-S28"]
    }
  }
}
```

The timing check returns a 60-second error and material severity because the quoted time crosses the documented cutoff. The result for the service outcome is unknown until the verifier supplies a source-linked outcome.
