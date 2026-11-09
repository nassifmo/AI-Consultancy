# Data Dictionary

Generated from `datagen/dictionary/dictionary.yaml` (version 0.1.0). Do not edit by hand.

Each file is both a synthetic export we generate and a file we will request from partner companies.

## Partner exports

### E1 customers (`customers.csv`)

**Real source:** CRM account records (pseudonymized) | **Owner:** CRM admin

| Field | Type | Required | Description |
|---|---|---|---|
| `customer_id` | string | yes | Pseudonymized customer/account ID |
| `segment` | enum: `large_account`, `mid_market`, `small` | yes | Commercial segment |
| `country` | string | yes | ISO 3166-1 alpha-2 country code |
| `preferred_channel` | enum: `voice`, `email`, `chat` | no | Usual contact channel |

### E2 shipments (`shipments.csv`)

**Real source:** Booking system | **Owner:** Operations

| Field | Type | Required | Description |
|---|---|---|---|
| `booking_ref` | string | yes | Carrier booking reference |
| `bl_ref` | string | no | Bill of lading number (issued later in the journey) |
| `container_refs` | list | yes | Container numbers (ISO 6346), semicolon-separated in CSV |
| `customer_id` | string | yes | Booking party (-> `customers.customer_id`) |
| `origin` | string | yes | UN/LOCODE of port of loading |
| `destination` | string | yes | UN/LOCODE of port of discharge |
| `planned_departure` | datetime | yes | Planned departure at booking time |
| `planned_arrival` | datetime | yes | Planned arrival at booking time |

### E3 tracking_events (`tracking_events.json`)

**Real source:** Carrier Track and Trace (DCSA T&T style API or export) | **Owner:** Operations / IT

event_created_datetime is essential: it tells us when the carrier system knew about the event, which lets us rebuild what the agent could have known at handling time. Field names follow DCSA T&T 2.x style; verify against the current DCSA spec.

| Field | Type | Required | Description |
|---|---|---|---|
| `event_id` | string | yes | Unique event ID |
| `booking_ref` | string | yes | Booking the event belongs to (-> `shipments.booking_ref`) |
| `container_ref` | string | no | Container for EQUIPMENT events |
| `event_type` | enum: `EQUIPMENT`, `TRANSPORT`, `SHIPMENT` | yes | DCSA event type |
| `event_type_code` | enum: `GTIN`, `GTOT`, `LOAD`, `DISC`, `ARRI`, `DEPA`, `RECE`, `CONF`, `ISSU`, `RELS`, `HOLD` | yes | Event code (subset of DCSA codes; verify) |
| `classifier` | enum: `ACT`, `PLN`, `EST` | yes | Actual, planned or estimated |
| `event_datetime` | datetime | yes | When it happened (ACT) or is expected to happen (PLN/EST) |
| `event_created_datetime` | datetime | yes | When the carrier system recorded the event |
| `location` | string | no | UN/LOCODE |

### E4 enquiries (`enquiries.csv`)

**Real source:** Customer service records (all in-scope channels) | **Owner:** Customer service

| Field | Type | Required | Description |
|---|---|---|---|
| `enquiry_id` | string | yes | Unique enquiry ID |
| `customer_id` | string | yes | Who contacted us (-> `customers.customer_id`) |
| `channel` | enum: `voice`, `email`, `chat` | yes | Contact channel |
| `received_at` | datetime | yes | When the enquiry arrived |
| `stated_reference` | string | no | Reference as given by the customer (may be wrong or partial) |
| `enquiry_type` | enum: `status`, `delay`, `documents`, `other` | yes | Classified enquiry type |
| `language` | string | no | ISO 639-1 language code |

### E5 agent_runs (`agent_runs.json`)

**Real source:** AI agent platform logs (e.g. HappyRobot runs / call logs) or LLM traces | **Owner:** Integrator / agent vendor

| Field | Type | Required | Description |
|---|---|---|---|
| `run_id` | string | yes | Unique agent run ID |
| `enquiry_id` | string | yes | Enquiry handled (-> `enquiries.enquiry_id`) |
| `agent_version` | string | yes | Agent release identifier |
| `started_at` | datetime | yes | Run start |
| `ended_at` | datetime | yes | Run end |
| `steps` | object_list | yes | Ordered tool calls made by the agent |
| `steps.step_no` | integer | yes | Order within the run |
| `steps.tool_name` | enum: `lookup_shipment`, `get_tracking_status`, `create_case`, `escalate_case`, `send_message`, `handoff_to_human` | yes | Tool called |
| `steps.tool_input` | string | no | Input (e.g. reference looked up) |
| `steps.tool_output` | string | no | Output summary |
| `steps.snapshot_time` | datetime | no | Time of the data the tool returned (for status lookups) |
| `steps.success` | boolean | yes | Whether the tool call succeeded technically |
| `claimed_status` | string | no | Shipment status stated to the customer (structured) |
| `claimed_eta` | datetime | no | ETA stated to the customer |
| `response_text` | string | no | Message sent to the customer |
| `self_reported_outcome` | enum: `resolved`, `escalated`, `handed_off`, `failed` | yes | Outcome as reported by the agent itself (not trusted) |
| `handoff_flag` | boolean | yes | Run ended by handing to a human |
| `tokens_in` | integer | no | LLM input tokens |
| `tokens_out` | integer | no | LLM output tokens |
| `voice_seconds` | integer | no | Billable voice seconds (voice channel) |

### E6 cases (`cases.csv`)

**Real source:** Case / ticket system | **Owner:** Customer service / CRM admin

| Field | Type | Required | Description |
|---|---|---|---|
| `case_id` | string | yes | Unique case ID |
| `enquiry_id` | string | yes | Originating enquiry (-> `enquiries.enquiry_id`) |
| `opened_at` | datetime | yes | Case creation |
| `reason` | enum: `delay_investigation`, `wrong_information`, `callback_request`, `documents`, `other` | yes | Why the case exists |
| `owner_id` | string | no | Pseudonymized human owner |
| `priority` | enum: `low`, `normal`, `high` | no | Priority |
| `closed_at` | datetime | no | Closure time (empty if open) |
| `closure_code` | enum: `resolved_info_provided`, `resolved_after_investigation`, `escalated_to_operations`, `customer_unreachable`, `duplicate`, `out_of_scope`, `cancelled` | no | Standardized closure reason |

### E7 case_history (`case_history.csv`)

**Real source:** Case field history (e.g. Salesforce CaseHistory2) | **Owner:** CRM admin

| Field | Type | Required | Description |
|---|---|---|---|
| `history_id` | string | yes | Unique change ID |
| `case_id` | string | yes | Case changed (-> `cases.case_id`) |
| `changed_at` | datetime | yes | Time of change |
| `field` | enum: `status`, `owner` | yes | Field that changed |
| `old_value` | string | no | Previous value |
| `new_value` | string | yes | New value (status values new/open/escalated/pending_customer/closed) |
| `changed_by` | string | yes | Human ID, "ai_agent" or "system" |

### E8 agent_work (`agent_work.csv`)

**Real source:** Human handling records (e.g. Salesforce Omni-Channel AgentWork) or timed sample | **Owner:** Customer service / workforce management

At least one of enquiry_id or case_id must be present. Elapsed ticket time is NOT effort.

| Field | Type | Required | Description |
|---|---|---|---|
| `work_id` | string | yes | Unique work item ID |
| `enquiry_id` | string | no | Enquiry worked (-> `enquiries.enquiry_id`) |
| `case_id` | string | no | Case worked (-> `cases.case_id`) |
| `agent_id` | string | yes | Pseudonymized human agent |
| `accepted_at` | datetime | yes | Work accepted |
| `closed_at` | datetime | no | Work closed |
| `active_seconds` | integer | no | Time actively worked |
| `handle_seconds` | integer | no | Accept to close |
| `acw_seconds` | integer | no | After-conversation work |
| `activity` | enum: `handle_enquiry`, `handle_case`, `correct_ai_answer`, `follow_up` | yes | Type of work |
| `measurement_method` | enum: `logged`, `timed`, `estimated` | yes | How effort was measured |

### E9 ai_invoice (`ai_invoice.csv`)

**Real source:** AI vendor invoices | **Owner:** Finance

| Field | Type | Required | Description |
|---|---|---|---|
| `period` | string | yes | Billing month YYYY-MM |
| `line_item` | enum: `voice_minutes`, `llm_tokens_in`, `llm_tokens_out`, `runs`, `platform_fee` | yes | Charge type |
| `quantity` | number | yes | Billed quantity |
| `unit_price` | number | yes | Price per unit |
| `amount` | number | yes | quantity x unit_price |
| `currency` | string | yes | ISO 4217 |

### E10 rollout_log (`rollout_log.csv`)

**Real source:** Integrator deployment log / release notes | **Owner:** Integrator

| Field | Type | Required | Description |
|---|---|---|---|
| `date` | date | yes | Effective date |
| `agent_version` | string | yes | Version deployed (or "human_baseline") |
| `arm_assignment_rule` | enum: `random_by_enquiry`, `by_region`, `all_traffic`, `none` | yes | How traffic was assigned |
| `traffic_share` | number | yes | Share of in-scope traffic (0-1) |
| `change_description` | string | no | What changed |

### E11 cost_parameters (`cost_parameters.json`)

**Real source:** Finance and integrator contract | **Owner:** Finance

| Field | Type | Required | Description |
|---|---|---|---|
| `currency` | string | yes | ISO 4217 |
| `labor_rate_per_hour` | number | yes | Fully loaded human cost per hour (wage + benefits + overhead) |
| `setup_cost` | number | yes | One-off integration/setup cost |
| `amortization_months` | integer | yes | Months to spread setup cost over |
| `platform_fee_month` | number | no | Fixed monthly platform fee |
| `maintenance_month` | number | no | Monthly maintenance/integrator support |
| `valid_from` | date | yes | Date these parameters apply from |

### E12 service_rules (`service_rules.yaml`)

**Real source:** Workflow owner workshop + policy documents | **Owner:** Workflow owner

Schema defined in datagen/config_schema.py (ServiceRules). Example in datagen/config/service_rules.yaml.

### E14 responses (`responses.csv`)

**Real source:** Interaction history (emails, chat and call transcripts) with the stated status/ETA extracted | **Owner:** Customer service / integrator

Every message that gave the customer shipment information, from the AI agent or a human. claimed_status / claimed_eta are structured here; with real data they come from transcripts and their extraction must be validated separately.

| Field | Type | Required | Description |
|---|---|---|---|
| `response_id` | string | yes | Unique message ID |
| `enquiry_id` | string | yes | Enquiry answered (-> `enquiries.enquiry_id`) |
| `case_id` | string | no | Case the message belongs to, if any (-> `cases.case_id`) |
| `sent_at` | datetime | yes | When the message was sent |
| `actor_type` | enum: `ai_agent`, `human` | yes | Who sent it |
| `actor_id` | string | yes | Agent version or pseudonymized human ID |
| `purpose` | enum: `answer`, `correction`, `case_update` | yes | Why it was sent |
| `shipment_reference` | string | no | Booking reference the message is about, as linked by the sender |
| `claimed_status` | string | no | Shipment status stated |
| `claimed_eta` | datetime | no | ETA stated |
| `message_text` | string | no | Message body |

### E13 staffing (`staffing.csv`)

**Real source:** HR / finance records | **Owner:** HR / Finance | **Optional**

Only needed to support realized cash-savings claims.

| Field | Type | Required | Description |
|---|---|---|---|
| `month` | string | yes | YYYY-MM |
| `support_headcount` | number | yes | FTE in scope |
| `overtime_hours` | number | no | Paid overtime hours |
| `outsourcing_spend` | number | no | Outsourced support spend |

## Ground truth (generator only)

### true_outcome (`true_outcome.csv`)

| Field | Type | Required | Description |
|---|---|---|---|
| `enquiry_id` | string | yes | Enquiry |
| `in_population` | boolean | yes | Received inside the study period (evaluation population) |
| `repeat_of` | string | no | Enquiry this one follows up, if generated as a repeat contact |
| `true_booking_ref` | string | yes | Shipment the customer actually meant |
| `arm` | string | yes | human_baseline or agent version |
| `scenario_id` | string | yes | S1-S12 scenario planted |
| `true_outcome` | enum: `resolved`, `escalated_open`, `failed`, `out_of_scope` | yes | True outcome |
| `true_status_at_handling` | string | no | Latest recorded status at handling time |
| `true_eta_at_handling` | datetime | no | Latest recorded ETA at handling time |
| `linked_correct_shipment` | boolean | no | First handler linked the right shipment |
| `first_answer_correct` | boolean | no | First answer matched what was known when it was given |
| `info_correct` | boolean | no | Final answer (after any correction) matched what was known when it was given |
| `escalation_required` | boolean | no | Rules required an escalation case |
| `required_actions_done` | boolean | no | All rule-required actions performed |
| `handed_off` | boolean | yes | AI handed the enquiry to a human |
| `self_report_false` | boolean | yes | AI reported success but the true outcome is not resolved |
| `ai_only` | boolean | yes | Resolved with no human work |
| `was_rescued` | boolean | yes | Human corrected or took over after AI |
| `repeat_contact` | boolean | yes | Customer contacted again within window |
| `true_human_seconds` | integer | yes | True active human effort (handling, cases, rescue, follow-up) |
| `true_ai_cost` | number | yes | True variable AI cost of this enquiry (tokens and voice) |
| `expected_evaluator_state` | enum: `resolved`, `escalated_open`, `failed`, `unknown`, `out_of_scope` | yes | What a correct evaluator should output given the (possibly damaged) exports |

### planted_effects (`planted_effects.json`)

### injected_defects (`injected_defects.csv`)

missing_snapshot removes a shipment's whole tracking history (record_id = booking_ref). affected_enquiries lists in-scope enquiries whose expected evaluator state became "unknown".

| Field | Type | Required | Description |
|---|---|---|---|
| `defect_id` | string | yes | Unique defect |
| `file` | string | yes | Export file affected |
| `record_id` | string | yes | Affected record |
| `defect_type` | enum: `duplicate_row`, `missing_field`, `missing_snapshot`, `timezone_shift`, `id_typo`, `orphan_record`, `retry_row`, `late_record`, `conflicting_closure`, `false_self_report` | yes | Defect injected |
| `field` | string | no | Field changed, if one field |
| `detail` | string | no | What was changed |
| `affected_enquiries` | list | no | Enquiries whose expected evaluator state became unknown (semicolon-separated) |

