# Data Sources, KPIs and ROI Method

Companion to `docs/DATA_REQUIREMENTS.md`. Status: research proposal (Nov 2026).
Verification note: sources were checked through web search results only (direct site access was blocked
in this session). Exact field names must be confirmed against the official docs and the company's real exports.

## 1. Where each kind of data comes from

### A. AI agent work (what the agent did, and what it cost)
| Need | Likely source | Evidence |
|---|---|---|
| Each agent run/call, actions, tool calls, outcome of the run | Agent platform logs. CMA CGM's documented vendor is HappyRobot: every workflow execution is logged as a "run"; API has `GET /calls/{id}/logs`; public REST API and gateway for data export | HappyRobot docs: runs, call logs API, developer tools |
| Tokens, cost, latency per step | LLM tracing (if the agent is custom-built): LangSmith run records include `total_tokens`, `total_cost`, start/end times; OpenTelemetry GenAI convention `gen_ai.usage.input_tokens` / `output_tokens` | LangSmith run data format and export cookbook; OpenTelemetry GenAI spans |
| Agent sessions inside a CRM | If Salesforce Agentforce is used: session tracing in Data Cloud (AiAgentInteraction, AiAgentSessionLog) | Salesforce DMO mapping guide (field prefixes differ between sources, verify) |
| Agent version / release date | Vendor release notes or deployment log from the integrator | To request |
| AI charges | Vendor invoices (per call/minute/run) and platform subscription | Finance |

### B. Employee work (human effort)
| Need | Likely source | Evidence |
|---|---|---|
| Active human minutes per case | Salesforce Omni-Channel `AgentWork`: `ActiveTime` (tab open and in focus), `HandleTime` (accept to close), `AfterConversationActualTime`. Requires Omni-Channel. | Salesforce AgentWork object reference |
| Case lifecycle, escalation, ownership changes | Salesforce `CaseHistory2` (status and owner changes, API 59+); `Case.Status`, `Origin`, `ClosedDate`. History only exists from when tracking was enabled. | Salesforce object reference |
| If Zendesk is used | Ticket Metrics API: `full_resolution_time`, `agent_wait_time`, `reopens`. These are **elapsed** times, not effort; effort needs a time-tracking app or work timers. | Zendesk Ticket Metrics docs |
| No usable effort logs | Short time-and-motion study on a sample of enquiries (timed handling), labelled `measurement_method = timed` | Method choice, to agree with company |

Key rule: elapsed ticket time is not human effort. Only active/handle time or a timed study counts as labour.

### C. Shipment operational truth
| Need | Likely source | Evidence |
|---|---|---|
| Status and ETA history with when it was known | Carrier tracking events in DCSA Track and Trace format: `eventClassifierCode` ACT/PLN/EST, `eventDateTime`, `eventCreatedDateTime` (query param in the DCSA Event domain spec). T&T 2.2 is current; 3.0 announced to handle corrected events and timestamp conflicts. | DCSA self-certification checklist; DCSA Event domain on SwaggerHub; Tradlinx (secondary) |

`eventCreatedDateTime` is what lets us rebuild "what was known when the agent answered". Exact definition still to be read in the DCSA data model.

### D. Costs and finance
| Need | Source |
|---|---|
| Fully loaded labour rate | Company HR/finance (wage + benefits + overhead). Benchmark for structure: BLS Employer Costs for Employee Compensation (June 2026: $49.46/hour civilian, wages = 70% of cost). US data, structure only, not a Lebanese rate. |
| Setup, integration, maintenance, review costs | Integrator contract, internal project time |
| Actual expenditure change (overtime, outsourcing, headcount) | Finance records; needed before claiming cash savings |

### E. Comparison data
Arm and version per enquiry: from an A/B split by the vendor/integrator, or a dated rollout log. Method guidance: HM Treasury Magenta Book (revised May 2026; Chapter 9 and Annex A cover counterfactual methods).

## 2. KPIs computed from those sources
| KPI | Formula | Sources |
|---|---|---|
| Verified resolution rate | verified-resolved enquiries / all enquiries in scope | A, B, C, rules |
| AI-only resolution rate | verified-resolved with no human actor / all | A, B |
| Information correctness | claims matching status/ETA known at handling time / claims checked | A, C |
| Required-action completion | enquiries with all rule-required actions done / enquiries requiring them | A, B, rules |
| Handoff rate | enquiries handed to a human / all | A, B |
| Repeat-contact rate | enquiries followed by contact on same customer + shipment within window / all | B, customer ID |
| Human minutes per enquiry | sum active minutes / enquiries | B |
| Elapsed time to resolution | resolved_at - received_at (median) | A, B |
| Evidence coverage | enquiries with all required records / all | all |
| Cost per enquiry | (AI cost + human cost + allocated fixed cost) / enquiries | A, B, D |
| Cost per verified resolution | total cost / verified-resolved enquiries | A, B, C, D |

Unknown and open enquiries stay in denominators and are reported separately, never dropped.

## 3. ROI measurement

### 3.1 Cost per arm, per period
- Human cost = active minutes / 60 x fully loaded hourly rate
- AI variable cost = vendor usage charges (calls, minutes, tokens) for all scoped attempts, including failures and retries
- Fixed cost = setup and integration amortized over the agreed horizon + platform fees + maintenance
- Review/correction cost = human minutes flagged as rescue or correction (already in human cost, reported separately)

### 3.2 Incremental effect (attribution)
Effect = AI arm outcome - comparison arm outcome, on equivalent enquiries (same type mix, same period
or a valid comparison). Before/after alone is not accepted. Report the estimate with its uncertainty.

### 3.3 Benefit lines (kept separate, never summed blindly)
1. Released capacity = human hours saved per enquiry x volume x rate (capacity value, not cash)
2. Realized cash savings = documented reduction in overtime, outsourcing or staffing spend
3. Quality effects = change in verified resolution, correctness, repeat contacts (reported in natural units;
   monetized only if the company provides an agreed value, e.g. cost of a repeat contact)

### 3.4 ROI figures
- Net benefit = incremental benefit - incremental cost (AI arm cost - baseline cost difference included)
- ROI = net benefit / incremental investment
- Payback period = incremental investment / monthly net benefit
- NPV over the horizon with a stated discount rate (Green Book approach), for multi-year views
- Two ROI versions always shown: on realized cash savings only, and including released-capacity value

### 3.5 Sensitivity
Test pessimistic cases (Green Book optimism-bias principle: raise costs, lower and delay benefits):
labour rate, share of capacity actually redeployed, AI price changes, ±uncertainty of the effect estimate.
Report whether the ROI sign changes.

## 4. Open questions for CMA CGM
- Which CRM/case system and which agent platform (HappyRobot confirmed publicly; deployment details not)?
- Is human handling time logged (e.g. Omni-Channel), or do we need a timed sample?
- Is tracking history exported with creation timestamps?
- Is there an A/B split or a dated rollout we can use as the comparison?
- Fully loaded hourly rate and who owns finance data?

## Sources
- HappyRobot runs: https://docs.happyrobot.ai/overview/runs
- HappyRobot call logs API: https://docs.happyrobot.ai/api-reference/calls/return-the-logs-for-a-call
- HappyRobot developer tools: https://happyrobot.ai/product/developer-tools
- LangSmith run data format: https://docs.langchain.com/langsmith/run-data-format
- LangSmith export cookbook: https://docs.smith.langchain.com/cookbook/exploratory-data-analysis/exporting-llm-runs-and-feedback
- OpenTelemetry GenAI spans: https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans
- Salesforce AgentWork: https://developer.salesforce.com/docs/atlas.en-us.256.0.object_reference.meta/object_reference/sforce_api_objects_agentwork.htm
- Salesforce CaseHistory2: https://developer.salesforce.com/docs/atlas.en-us.264.0.object_reference.meta/object_reference/sforce_api_objects_casehistory2.htm
- Salesforce AiAgentInteraction DMO: https://developer.salesforce.com/docs/data/data-cloud-dmo-mapping/guide/c360dm-si-aiagentinteractiondmo-dmo.html
- Zendesk Ticket Metrics: https://developer.zendesk.com/rest_api/docs/core/ticket_metrics
- DCSA T&T self-certification checklist: https://dcsa.org/wp-content/uploads/2020/10/20210621_DCSA_SCC-for-TT-1.2.pdf
- DCSA Event domain 3.1.0: https://api.swaggerhub.com/domains/dcsaorg/EVENT_DOMAIN/3.1.0
- BLS ECEC: https://www.bls.gov/news.release/archives/ecec_06122026.htm
- Magenta Book: https://gov.uk/government/publications/the-magenta-book
- Bain, FinOps for AI (cost per outcome): https://www.bain.com/insights/finops-for-ai-from-managing-costs-to-maximizing-value/
