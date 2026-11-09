# Synthetic Data Generation Plan

Status: plan (Nov 2026). Builds on `DATA_REQUIREMENTS.md` and `DATA_SOURCES_AND_ROI.md`.

## 1. Principle
The synthetic dataset has **exactly the same files and fields we will request from a partner company**.
The generator spec and the partner data request are the same document (section 9).

Study period vs data cutoff: the evaluation population is enquiries received inside the study period;
exports run until period end + observation window, so every enquiry in the population can be judged.
When real data arrives, only a mapping step changes; the evaluator does not.

Every generated dataset has two parts:
- `exports/`: what a company would give us (messy, incomplete, partner-shaped).
- `ground_truth/`: the true answers, written **before** defects are injected. The evaluator never reads it;
  only the test harness does.

Values below marked *(assumption)* are placeholders to tune, not facts about any company.

## 2. Files to generate (= partner exports)

| # | File | Mirrors (real source) | Key fields |
|---|---|---|---|
| E1 | `customers.csv` | CRM accounts | customer_id (pseudonymized), segment, country, preferred_channel |
| E2 | `shipments.csv` | Booking system | booking_ref, bl_ref, container_refs, customer_id, origin, destination, planned_departure, planned_arrival |
| E3 | `tracking_events.json` | Carrier T&T (DCSA-style) | event_id, booking_ref, container_ref, event_type (EQUIPMENT/TRANSPORT/SHIPMENT), event_type_code, classifier (ACT/PLN/EST), event_datetime, event_created_datetime, location |
| E4 | `enquiries.csv` | Support records | enquiry_id, customer_id, channel (voice/email/chat), received_at, stated_reference, enquiry_type, language |
| E5 | `agent_runs.json` | Agent platform logs (HappyRobot-style runs) | run_id, enquiry_id, agent_version, started_at, ended_at, steps[] (tool_name, tool_input, tool_output, snapshot_time), claimed_status, claimed_eta, response_text, self_reported_outcome, handoff_flag, tokens_in, tokens_out, voice_seconds |
| E6 | `cases.csv` | Case system | case_id, enquiry_id, opened_at, reason, owner_id, priority, closed_at, closure_code |
| E7 | `case_history.csv` | Case field history (CaseHistory2-style) | case_id, changed_at, field (status/owner), old_value, new_value, changed_by |
| E8 | `agent_work.csv` | Human effort (AgentWork-style) | work_id, case_id or enquiry_id, agent_id, accepted_at, closed_at, active_seconds, handle_seconds, acw_seconds, activity |
| E9 | `ai_invoice.csv` | Vendor billing | period, line_item (calls/minutes/tokens/platform fee), quantity, unit_price, amount |
| E10 | `rollout_log.csv` | Integrator deployment log | date, agent_version, arm_assignment_rule, traffic_share, change_description |
| E11 | `cost_parameters.json` | Finance | labor_rate_per_hour (fully loaded), currency, setup_cost, amortization_months, platform_fee_month, maintenance_month |
| E12 | `service_rules.yaml` | Workflow owner | escalate_if_delay_hours, followup_deadline_hours, repeat_contact_window_days, resolution_definition, closure_code_list |
| E13 | `staffing.csv` (optional) | HR/finance | month, support_headcount, overtime_hours, outsourcing_spend (needed for realized cash savings) |
| E14 | `responses.csv` | Interaction history (emails, chats, call transcripts) | response_id, enquiry_id, case_id, sent_at, actor_type, purpose (answer/correction/case_update), shipment_reference, claimed_status, claimed_eta, message_text |

Ground truth files (`ground_truth/`):
`true_outcome.csv` (per enquiry: resolved / escalated_open / failed, true status and ETA at handling time,
info_correct, required_actions_done, was_rescued, true_human_minutes), `planted_effects.json`,
`injected_defects.csv` (every defect: file, row, type).

## 3. Generation pipeline (layers)

1. **World**: customers, ports, vessel rotations, shipments with planned schedule.
2. **Operations**: actual journey per shipment. Delays drawn from a mix (none / short / long) *(assumption)*.
   ETA revisions emitted as EST events; actual events as ACT.
   Each event gets `event_created_datetime` = event time + recording lag (some lags long, to create stale-status cases).
3. **Enquiries**: arrivals per shipment as a Poisson process; rate rises after a delay or ETA change *(assumption)*.
   Type: status / delay / documents-out-of-scope. Some quote a wrong or partial reference.
4. **Handling**: each enquiry is routed to an arm (section 4).
   - Human baseline: handling time lognormal *(assumption)*, small error rate.
   - AI agent: behaviour parameters per version: lookup success, stale-cache probability, wrong-shipment
     probability, escalation compliance, unsupported-claim probability, handoff probability.
   - Handoffs and rescues generate human work records (E8) and case updates (E7).
5. **Follow-up**: repeat contacts generated with higher probability when the true outcome was wrong or unresolved.
6. **Costs**: tokens and voice seconds per run, invoice lines aggregated per month, fixed costs from E11.
7. **Truth snapshot**: write `ground_truth/` now.
8. **Export rendering**: render each layer into partner-shaped files (E1 to E13), with realistic formats
   (timezones, string IDs, nested JSON for runs).
9. **Defect injection** (logged in `injected_defects.csv`): duplicates, missing fields, missing tracking
   snapshots, timezone mix-ups, ID typos, orphan cases, retries, late-arriving records, conflicting closure codes,
   agent self-reporting success on failed cases.

Everything is driven by one config file and a random seed, so any dataset can be regenerated exactly.

## 4. Comparison designs to simulate

| Design | What it tests |
|---|---|
| D1 Randomized split: human baseline vs AI agent | Deployment value with a clean counterfactual |
| D2 Randomized split: agent v1 vs v2 (integrator enhancement) | Integrator contribution |
| D3 Staged rollout by region/date | Realistic rollout analysis |
| D4 Before/after with a seasonal delay spike at rollout time | The evaluator must flag confounding, not report a false effect |

## 5. Scenarios with planted answers

| ID | Scenario | Expected evaluator behaviour |
|---|---|---|
| S1 | Normal status enquiry, correct answer | Resolved |
| S2 | Delay above threshold, agent escalates | Escalated/open, required action done |
| S3 | Delay above threshold, agent does not escalate | Failed (required action missing) |
| S4 | Agent answers from stale status | Information incorrect at handling time |
| S5 | Status changed after the answer (agent was right then) | Correct; not penalized |
| S6 | Wrong shipment linked | Failed; detected via reference mismatch |
| S7 | Human rescue after bad AI answer | Not AI-only; rescue minutes counted |
| S8 | Repeat contact within window | Original enquiry not verified-resolved |
| S9 | Tracking snapshot missing | Unknown, not success |
| S10 | Agent self-reports success, evidence says failure | Counted as failure; false-claim metric increments |
| S11 | Ticket created but never actioned | Not resolved |
| S12 | Out-of-scope enquiry (documents) | Excluded with reason |

Planted effects (`planted_effects.json`): e.g. v2 raises verified resolution by a fixed number of points
and cuts human minutes by a fixed amount *(assumption)*; plus a **null dataset** where v1 and v2 are
identical, to test that no false effect is reported.

## 6. Datasets to produce

| Set | Size | Use |
|---|---|---|
| `tiny` | ~40-50 enquiries, hand-checked | Unit tests; every row reviewed by a human |
| `dev` | ~2,000 shipments over 3 months (currently ~2,200 enquiries; volume will be raised in step 6 to give enough statistical power) | Development |
| `heldout` | Same size, different seed and slightly different parameters, generated by the other teammate | Final accuracy test |
| `damaged` | dev + heavy defect injection | Robustness |
| `null_effect` | v1 = v2 | False-positive test |
| `confounded` | Design D4 | Attribution refusal test |

## 7. Optional realism upgrade: live LLM agent
Run a real LLM agent (two prompt/tool versions) against the simulated shipment backend instead of the
behaviour parameters in layer 4. Produces genuine transcripts, token costs and a real (not planted)
v1 vs v2 difference. Ground truth then comes from the simulator's backend state, not from the agent.

## 8. Checking the generator itself
- Every generated dataset passes schema validation against the data dictionary.
- Distribution report per run (delays, enquiry types, handling times, outcome mix).
- `tiny` is reviewed row by row by the teammate who did not write the generator.
- Generator and evaluator are written by different people; held-out scenarios stay hidden until week 4.

## 9. Partner data request (same files, real source)

| # | Request | Typical owner | Format | Period |
|---|---|---|---|---|
| E1 | Customer accounts, pseudonymized | CRM admin | CSV export | Study window |
| E2 | Shipments and booking/BL/container references | Operations | CSV/API | Study window + 30 days |
| E3 | Tracking events **with recorded/created timestamps** | Operations / IT | DCSA T&T API or export | Study window + 30 days |
| E4 | Customer enquiries (all channels in scope) | Customer service | CSV | Study window |
| E5 | AI agent run logs, transcripts, tool calls, versions, usage | Integrator / agent vendor | JSON export or API | Study window |
| E6–E7 | Cases and status/owner history | Customer service / CRM admin | CSV | Study window + follow-up window |
| E8 | Human handling time (active time if logged) | Customer service / WFM | CSV | Study window |
| E9 | AI vendor invoices | Finance | CSV/PDF | Study window |
| E10 | Rollout dates, versions, traffic split | Integrator | Document/CSV | Full history |
| E11 | Fully loaded labor rate, setup and running costs | Finance | Form | Current |
| E12 | Escalation and resolution rules | Workflow owner | Workshop + document | Current |
| E13 | Headcount, overtime, outsourcing (optional) | HR / Finance | CSV | 6 months before + study window |
| E14 | Messages sent to customers (AI and human), with stated status/ETA | Customer service / integrator | CSV or transcripts | Study window + follow-up window |

Privacy: request pseudonymized customer and agent IDs; no personal data beyond IDs and timestamps;
transcripts redacted of personal details; data stays in an agreed storage location.

If a partner cannot provide an item, the fallback is recorded: E8 -> timed sample study;
E3 created timestamps -> answers marked "unverifiable at time"; E10 -> before/after with confounding flagged.

## 10. Build order

| Step | Output | Owner (proposal) |
|---|---|---|
| 1 | Data dictionary (all fields, types, allowed values) + `service_rules.yaml` + config schema | Both |
| 2 | Layers 1–3 (world, tracking, enquiries) + `tiny` set | Generator owner |
| 3 | Layers 4–6 (handling, follow-up, costs) + ground truth | Generator owner |
| 4 | Export rendering + defect injection | Generator owner |
| 5 | Scenario library S1–S12 with expected results, written independently | Evaluator owner reviews |
| 6 | `dev`, `damaged`, `null_effect`, `confounded` sets | Generator owner |
| 7 | `heldout` set with hidden parameters | Other teammate |
| 8 | Optional live-LLM agent mode | Later |

## 11. Repo layout
```
datagen/
  config/default.yaml        # all parameters and seed
  config/service_rules.yaml
  dictionary/                # data dictionary per file
  generator/                 # layers 1-9
  scenarios/                 # S1-S12 definitions + expected results
  datasets/<name>/exports/   # partner-shaped files
  datasets/<name>/ground_truth/
```
