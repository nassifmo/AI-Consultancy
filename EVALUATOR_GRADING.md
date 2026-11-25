# Verifying and grading shipment enquiries

The grading layer accepts a request type and verified evidence from the shipment evaluator. Its versioned policy determines which checks apply and how to grade them. The initial request types are shipment status, arrival coordination and shipment delay. A new request type can reuse existing grading methods by declaring its criteria in the [policy](evaluator/policy.json). This follows the practice of choosing the scoring format per metric. [ServiceNow evaluation metrics](https://www.servicenow.com/docs/r/intelligent-experiences/mon-ai-evaluation-metrics-reference.html)

| Check | Grade |
| --- | --- |
| Shipment identity | Verify that the reply covers the requested shipment or container. A proven initial failure receives a critical flag. |
| Milestone status | Check a status claim against the linked tracking evidence when it is part of the reply or request. |
| Requested ETA answered | Check whether the reply supplied the time the customer asked for. Record any verified human handoff and the eventual outcome. |
| ETA accuracy | Record the signed time difference from the carrier's reference. When the case has a documented decision cutoff, check whether the error changes the decision. |
| Arrival coordination | Independently check whether the reply names the right monitoring team for the documented cutoff. |
| Escalation and follow-up deadlines | Check the exact deadline and measure the seconds overdue. Completion at or before the deadline has zero lateness. |
| Initial escalation steps | Check each expected action. Award partial credit when the step evidence is complete and some steps are met. Keep proven critical omissions visible. |

An established false applicability condition produces `not_applicable`. A missing condition or missing evidence produces `unknown`. Supply a failed check or missing action as false only when the evidence establishes it. Leave unverified values absent or null. A measurable ETA error can still have unknown severity when the customer's context is incomplete. Each result includes the policy version, the checks, their source references, and the independently verified outcome where supplied. A severe initial handling failure stays visible when a later human correction resolves the request.

## Read sent replies with local AI

With Ollama running, expand **Read sent replies with local AI** in the dashboard and enable the reader. Select an installed local model and start with **S28 · Vessel status and ETA**. The command line accepts the same option.

```powershell
.\.venv\Scripts\python.exe -m evaluator --exports datagen/datasets/scenarios/S28/exports --ollama-model qwen2.5:7b-instruct
```

The local model reads the customer question and sent reply together. It can recognize an arrival-time request in ordinary phrasing and distinguish an estimate, an omitted answer, an explicit statement of unavailability, and wording that needs review. It supplies verbatim quotes from the question and reply. The evaluator parses supported absolute timestamps from the quoted reply and compares them with tracking at send time. It keeps possible conflicts, such as a quote about the wrong destination, out of the numeric ETA check. Relative or imprecise estimates can be recognized as an answer while their accuracy remains unknown.

The model also extracts quoted shipment status and completed action claims. The evaluator verifies them against the correct shipment's historical tracking and the linked case records. A claim about opening a case or routing it to operations is checked even for enquiries that had no escalation requirement. The **Enquiry evidence** tab shows the quoted question and reply, classification basis, verdict, and source references. The original reply and any human recovery remain visible.

The reader is opt-in and uses the local Ollama service. Duplicate question and reply pairs reuse their interpretation within a run. Identical replies also reuse their shipment and action extraction. Both tasks share the model-call budget, which defaults to 25 calls and can be set up to 500. Unclear or unavailable model results leave unsupported findings unknown. Use a reviewed set of replies to measure missed, misread and unsupported claims before relying on the results for a pilot. Saved analysis runs record the model and the findings used. A new local inference may produce different findings. [Ollama structured output documentation](https://docs.ollama.com/capabilities/structured-outputs)

## Hosted evaluator candidates

The planned hosted comparison starts with GPT-6 Luna, Claude Haiku 5.5, and Gemini 3.8 Flash. Review the same shipment exchanges for missed critical errors, quotes that support each classification, appropriate deferral, and billed tokens. Dialpad's contact-center results inform the shortlist. Shipment-specific performance will come from reviewed project cases. [Contact-center comparison](https://arxiv.org/html/2611.22949v1)

The evaluator currently uses Ollama for language interpretation. The hosted connection is a separate development step from the [shipment-agent replay](docs/REPLAY_QUICKSTART.md). Eligible subscriptions can fund calls through a linked API account, and the hosted evaluator will use the account's API key. Verify which provider the company approves before sending pilot transcripts. [OpenAI API credit eligibility](https://developers.openai.com/api/docs/guides/chatgpt-api-credits) · [Claude API credit eligibility](https://platform.claude.com/docs/en/about-claude/api-credits-for-subscribers)

## Timing score configuration

### Verify the sent ETA before scoring

The benchmark checks the ETA the customer received against the same shipment milestone in the tracking snapshot visible at send time. It can read an explicitly labelled ETA in a timezone-qualified ISO timestamp or supported English date and clock wording. Destination-local wording needs a named port and its configured time zone. Multiple conflicting times and unclear dates or offsets need review. Claimed values from the structured export remain visible when they disagree with the sent ETA. A minute-level display can match tracking at the stated precision, while the raw signed difference and any documented cutoff check use the underlying instants.

Some synthetic fixtures contain a placeholder message and a structured claim. The rules-only evaluator can use that field when the export explicitly declares `dataset_origin: synthetic`. Such a result shows `legacy_structured_claim`. Use the synthetic label only for benchmark data. Company exports and exports of unconfirmed origin, including uploads with an absent origin, require a verifiable sent ETA when the customer requested one or the reply mentioned one. A missing or unsupported ETA leaves that check unknown, even when a structured field supplies a timestamp. The export's rule version identifies its rubric. The same verification checks can later be calibrated to the carrier's actual text or transcripts. A forecasting study would compare its forecast with the eventual actual event for the same milestone and track the forecast's lead time. [DCSA port-call timestamp definitions](https://reference.dcsa.org/content/standards/releases/port-call/v2/pc-v2-use-cases) · [Veenstra and Harmelink's Antwerp ETA study](https://ris.utwente.nl/ws/files/275305413/Veenstra2021quality.pdf)

### Check whether the ETA question was answered

When the customer explicitly asks for an ETA and the reply only gives a shipment status, mark **Requested ETA answered** as unmet. For example, “The vessel has departed” is a clear omission in response to “When will it arrive?” ETA accuracy has no numeric error to report because the customer received no ETA. The same treatment applies to a clear omission in a labeled synthetic case. Historical structured fields are still available for explicitly synthetic placeholders.

The reply can explicitly state that the ETA is unavailable. The evaluator checks a handoff against the linked run or case routing evidence, including its coverage and the observation cutoff. A verified pending handoff is open. If the records cover the workflow and show neither a handoff nor a later answer, the service outcome fails. Incomplete handoff coverage can leave the outcome unknown while the omission is still recorded. A later verified answer can resolve the case. The initial reply remains visible. Empty transcripts and unsupported wording need review before the evaluator can say what the customer received. The checks cover supported English phrasing and the configured workflow.

### Apply the shipping decision context

For directional grading, signed error is the sent ETA minus the reference ETA. A negative value means the reply quoted an earlier time. A positive value means it quoted a later time. Select the early or late limit based on that sign. The **timing failure score** is `100 × min(1, absolute error / selected limit)`. An exact match receives 0 and either boundary receives 100, as do values beyond it. The accuracy score is `100 − timing failure score`. Deadline grading remains a separate one-sided method. The configured `zero_score_on_cutoff_crossing` option makes a confirmed decision-boundary crossing a full timing failure for that criterion. When the governing cutoff is unavailable, the result only reflects the time difference.

Since `0.6.0-proposed`, the policy uses **20 hours on either side** for the synthetic benchmark and turns on the cutoff override for the arrival-coordination case. A six-hour early or late error has a 30/100 failure score under that curve. The same case has a 100/100 score when an approved decision boundary is crossed and the override applies. The band is an engineering example to exercise the wider scale. Exact correctness, operational severity, eventual resolution and verified monetary impact retain their own evidence.

| Situation | Evidence that determines the relevant timing harm |
| --- | --- |
| Routine tracking | Compare against the quoted milestone and current published estimate. Use symmetric limits until the workflow provides evidence of meaningful directional harm. |
| Dispatch or staffing | An early claim can trigger a truck or staff before they are needed. Check the actual readiness event, recorded dispatch decision, booking window and any delay or waiting expense. [Maersk truck waiting time](https://www.maersk.com/news/articles/2023/06/05/truck-waiting-time-fee-announcement) |
| Pickup appointment or last free day | A late claim can delay an otherwise possible pickup or lead to a missed slot or paid storage. Use the actual release and availability times, appointment records, last free day and any reconciled charges. [Maersk free-time details](https://www.maersk.com/support/faqs/access-demurrage-and-detention-details) · [Maersk appointment and dispute evidence](https://www.maersk.com/local-information/north-america/united-states-of-america/import) |

For a company profile, review dated examples on each side of the correct time with support and operations. Record which errors would change the action and verify realized consequences with finance where available. Choose separate early/late limits only if the workflow evidence supports a difference, and confirm them against independent cases near each boundary before using the scores in a decision. Use the applicable container readiness or release evidence for pickup decisions. The vessel ETA and pickup readiness refer to different events. [Maersk import release instructions](https://www.maersk.com/de-de/support/faqs/2025/09/05/how-can-i-submit-my-import-container-release-instructions)

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
