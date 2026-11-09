# Data Requirements (verified against the architecture diagram)

Derived by tracing each pipeline step in `docs/ARCHITECTURE_PLAN.md` back to the fields it needs.
Status: proposal for week 1. Field names are ours; map to company exports once access is confirmed.

## Gaps found versus the plan's data table
| # | Gap | Needed by | Fix |
|---|---|---|---|
| 1 | No customer/account ID | Step 1 linking, Step 2 repeat contacts | Add `customer_id` to enquiries |
| 2 | "Actor" in diagram but not in table | Step 2 human work, AI-only handling | Add `actor_type` (ai/human/system) + `actor_id` to every event |
| 3 | Agent claim only as free-text "response" | Step 2 claim vs status/ETA check | Add structured `claimed_status`, `claimed_eta` (free-text extraction validated later) |
| 4 | No workflow arm on each enquiry | Step 3 comparison | Add `arm` (baseline/ai) and `agent_version` |
| 5 | No enquiry type / delay flag for fair comparison | Step 3 equivalence | Add `enquiry_type`, and derive `delay_at_request` from shipment history |
| 6 | Service criteria are not structured | Step 2 "required case actions" | Rule table: when escalation is required, follow-up deadline, resolution definition |
| 7 | Cost table has no unit or period | Step 4 cost per verified resolution | Per-request AI usage; labor rate per hour; setup cost with amortization period and volume |
| 8 | Provenance not listed | Shared evidence store, reproducibility | `source_file`, `extracted_at`, `rule_version` on imported rows and results |
| 9 | Closure reason not standardized | Step 2 resolved vs failed | `closure_code` from an agreed list |

## Canonical entities

### 1. enquiry (one per customer request)
`enquiry_id`, `customer_id`, `channel`, `received_at`, `booking_ref`, `bl_ref`, `container_ref`,
`enquiry_type` (status / delay / other), `arm` (baseline / ai), `agent_version`

### 2. interaction_event (agent and human steps inside an enquiry)
`event_id`, `enquiry_id`, `occurred_at`, `actor_type`, `actor_id`, `action`
(lookup / respond / create_case / escalate / handoff / correct), `tool_name`, `tool_result_snapshot_id`,
`claimed_status`, `claimed_eta`, `response_text`, `retry_of`

### 3. shipment_event (tracking history, DCSA Track and Trace style)
`shipment_event_id`, `booking_ref`, `container_ref`, `event_type` (equipment / transport / shipment),
`status_code`, `classifier` (actual / estimated / planned), `event_time` (when it happened or is expected),
`recorded_time` (when the carrier system recorded it), `eta`, `location`
- `recorded_time` is what lets Step 2 rebuild "what was known when the enquiry was handled".
- ETA = latest estimated arrival event recorded before the handling time.
- Field names must still be checked against the current DCSA spec before finalising.

### 4. case (exception / escalation)
`case_id`, `enquiry_id`, `opened_at`, `reason`, `owner_id`, `handoff_at`, `closed_at`, `closure_code`

### 5. case_update
`update_id`, `case_id`, `updated_at`, `actor_type`, `actor_id`, `note_type` (update / customer_contact / correction)

### 6. human_work
`work_id`, `enquiry_id` or `case_id`, `actor_id`, `activity`, `active_minutes`, `is_rescue`, `measurement_method` (logged / timed / estimated)

### 7. ai_usage
`enquiry_id`, `agent_version`, `model_calls`, `input_tokens`, `output_tokens`, `voice_minutes`, `charge`

### 8. cost_parameters
`labor_rate_per_hour`, `setup_cost`, `amortization_months`, `expected_volume`, `platform_fee_per_month`, `currency`, `valid_from`

### 9. service_rules (versioned)
`rule_version`, `escalate_if_delay_hours`, `followup_deadline_hours`, `repeat_contact_window_days`,
`resolution_definition`, `observation_window_days`

## Step-by-step check
| Step | Uses |
|---|---|
| 1 Import, validate, link | enquiry, interaction_event, case (refs + times); provenance |
| 2 Verify handling | shipment_event (recorded_time), interaction_event claims, case + updates, human_work, service_rules, repeat contacts via customer_id + shipment ref + window |
| 3 Compare | arm, agent_version, enquiry_type, delay_at_request, outcome state, human minutes, elapsed time |
| 4 Value and report | ai_usage, cost_parameters, human_work, outcome counts |

## Derived (not collected)
Outcome state (resolved / escalated-open / failed / unknown), `delay_at_request`, `status_correct_at_time`,
`eta_correct_at_time`, `required_actions_done`, `repeat_contact`, `ai_only`, `elapsed_minutes`,
`cost_per_verified_resolution`, `evidence_coverage`.

## Minimum dataset for the week-1 simulator
Entities 1 to 4, 6, 8, 9. Entities 5 and 7 can be simplified (7 as a flat per-enquiry cost).
