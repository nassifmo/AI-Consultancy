# Workflow and Architecture Plan (advisor brief, 3 Nov 2026)

Source: `docs/reports/2026-11-03_Workflow_Architecture_Plan.pdf`. This is the agreed baseline for development.

## Workflow
Shipment-status and delay enquiries: receive request -> identify shipment -> check operational status
-> respond or create exception case -> escalate when needed -> record follow-up and outcome.
Assess the whole enquiry, including human corrections and repeat contacts.
Scope = enquiry handling only. Effects on physical delivery need separate evidence.
Pilot opportunity: CMA CGM (team process and data still to be confirmed).

## Research focus
Test whether linked evidence reduces unsupported outcome and value claims when records are
missing, conflicting or show human rescue. Advantage over existing tools remains to be demonstrated.

## Architecture
Inputs:
- Enquiries and logs: request/shipment IDs, responses, tools, actor
- Tracking and cases: status and ETA history, escalation, follow-up
- Costs and versions: human time, AI usage, baseline vs AI release

Pipeline:
1. Import, validate and link each enquiry (join request, booking/container and case IDs; preserve event times)
2. Verify enquiry handling (status/ETA known at the time, case actions, human work, follow-up)
   -> outcome: resolved / escalated-open / failed / unknown
3. Compare baseline and AI (completion, repeats, time, work)
4. Calculate value and report (full costs, quality, evidence)

Cross-cutting: shared evidence store, rule versions, human review of exceptions.

Stack: Python, SQLite, FastAPI, Streamlit. Start with structured test records and rules;
validate any free-text claim extraction separately.

## Data (CSV/JSON exports first; simulated records until access)
| Data | Essential fields | Potential source |
|---|---|---|
| Enquiry and agent | Request ID, shipment IDs, times, response, tool result, agent version | Support records, agent traces |
| Shipment history | Booking/container, status, ETA, event time, recorded time, snapshot ID | Tracking exports or authorized feed |
| Cases and follow-up | Case ID, reason, owner, handoff, updates, closure, repeat contact | Case system, interaction history |
| Human work | Request/case ID, activity, active duration, correction or rescue | Handling tools or measured activity |
| Costs and rules | AI usage/charges, labor rate, setup cost, permissions, service criteria | Finance, workflow owner, policy records |

Mapping reference: DCSA Track and Trace.

Preparation: agree mappings, permissions, authoritative sources and observation windows with the
workflow owner; validate fields and times; remove export duplicates; preserve retries; link IDs into
enquiry histories; reconcile counts and check sample histories before automating.

Shipment checks: compare claims with status/ETA available when handled; check required case actions
and follow-up; record human rescue. Missing historical snapshots limit past-answer verification.
A created ticket alone does not prove resolution.

## Outputs
Verified resolution, AI-only handling, incorrect/outdated information, required-action completion,
handoffs, repeat contacts, human minutes, elapsed time, evidence coverage, cost per verified resolution.
Open and unknown cases stay visible.

Comparisons: deployment value = existing workflow vs agent-enabled workflow; integrator enhancement =
earlier vs updated agent. Choose one first comparison and replay equivalent test cases.
Field effects need a credible production comparison (Magenta Book).
Costs include all scoped attempts, technology, setup, review and correction. Released staff time and
realized cash savings reported separately.

## First-month prototype
Test scenarios: normal tracking, delay escalation, stale status, wrong-shipment linkage, human rescue,
repeat contact, missing records, against independently checked expected results.
Baselines: agent-reported success, and a strong independent SQL/code analysis on the same evidence.
Measures: false resolution claims, accuracy, evidence coverage, economic error, preparation/review effort.

| Week | Deliverable |
|---|---|
| 1 | Define enquiry states and comparison; map fields; build simulated tracking and case histories |
| 2 | Imports, enquiry linkage, status/case checks, human-work and cost calculations |
| 3 | Comparison, review interface, exports; test against baseline analyses |
| 4 | Held-out and damaged-evidence cases; document errors; reproducible results |

Contribution: model, retrieval, tool and human effects via valid comparisons incl. interactions (NIST
factorial design). KPIs kept separate initially; any weighted score needs agreed priorities, scales and
sensitivity checks, separate from financial ROI.

## Open items for the advisor
Service boundaries, success criteria, research question, architecture, data-preparation plan, first comparison.
Status: design only. No development or experiments yet. Advantage and financial benefit unproven.

## References
1. CMA CGM and HappyRobot customer service deployment
2. Workhelix FAQ on AI measurement and comparisons
3. DCSA Track and Trace implementation guide
4. HM Treasury Magenta Book Annex A
5. FinOps Foundation, FinOps for AI overview
6. Salesforce Architects shipping enquiry runtime example
7. NIST factorial design example
8. Government Analysis Function guide to criteria and weights
