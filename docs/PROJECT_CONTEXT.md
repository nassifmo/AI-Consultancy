# Project Context

## Team
- Students: Bahaa Hamdan, Mohamad Nassif
- Advisor: Prof. Imad Moukadem (first meeting 22 Sept 2026, requested by Bahaa)

## Idea
A third-party system that independently identifies the economic value created by an AI integration,
including the specific contribution of the integrator's changes.

## Current scope
- Target: AI customer-service **agent** (may use RAG internally; RAG is not the scope by itself).
- Business workflow: **shipment-status and delay enquiries**
  (receive enquiry -> identify shipment -> check operational records -> respond or open exception case
  -> escalate if needed -> record follow-up and outcome).
- First intended pilot: CMA CGM (workflow, data access and internal systems NOT yet confirmed).
- Other reachable companies: touch, Alfa, Murex.
- Strategy: broad long-term mission, start with one workflow, pilot in Lebanon, expand by demand (GCC/MENA later).

## Method (agreed principles)
Pipeline: company records -> validate/link -> verify outcomes and KPIs -> comparison/attribution
-> economic value -> evidence-linked report.

Three contribution levels, each needing its own comparison:
1. Whole agent vs existing workflow
2. Integrator enhancement vs previous agent configuration
3. Individual components (retrieval, model, tools) via comparable configurations

Rules:
- Logs show participation, not causation.
- Time saved = released capacity, not cash savings unless expenditure actually changes.
- Non-monetizable quality improvements stay visible as separate outcomes.
- Missing evidence is reported as "unknown", never assumed.
- Simple before/after comparison is not sufficient for attribution.
- Component contributions interact; do not force them to sum to 100%.

Open questions:
- Exact data extraction, validation and transformation process (to be defined with the company).
- How contribution is split between parts and how KPIs are weighted.
- Service boundaries: where the process starts and ends, and what counts as successful completion.

Development without a partner: simulated testbed, records with known expected outcomes,
public datasets (WixQA inspected: 6,221 knowledge records; 2 repeated question pairs; 29 title-only articles).
A company pilot is an extension, not a prerequisite.

## Competitors (summary)
- Direct overlap: Workhelix Nucleus, Paid, ServiceNow AI Control Tower, IBM Apptio AI Value & ROI, Worklytics.
- Contract verification: OutcomeClear, Bona (overlap with outcome-based-contract channel idea).
- Tools/data sources: Eppo/Datadog Experiments, Microsoft Copilot Analytics, LangSmith, Arize Phoenix,
  Salesforce Agentforce, Intercom Fin, UiPath Insights.
- Positioning hypothesis (unproven): independent, workflow-specific estimate of what the agent added,
  including human corrections and follow-up, with less client preparation effort.
- Market gap: not yet validated (needs a real buyer, usable data, demonstrated improvement, willingness to pay).

## Report preferences
- Advisor wants a concise 5-10 page literature review showing our own judgment; he skims.
- Word, black and white, 12pt minimum, page-number-only footer, "we" voice, polite advisor questions.
- Research-question section is provisional and must be rewritten later.
- Latest deliverable: 3-page advisor brief with shipment-enquiry architecture (see `docs/ARCHITECTURE_PLAN.md`).

## Note
Earlier reports, research notes and scripts live on Bahaa's machine (`C:/Users/user/Documents/FYP AI value/`),
not in this repo yet.

## Decisions log
- 2026-11: Scope set to AI customer-service agent; workflow = shipment-status/delay enquiries; CMA CGM first pilot target.
- 2026-11-03: Workflow and architecture plan concluded (see `docs/ARCHITECTURE_PLAN.md`); stack Python/SQLite/FastAPI/Streamlit.
- 2026-11: Build and prove the evaluator on synthetic/simulated data first, then apply to real company data (CMA CGM or others).
- 2026-11: Rule boundaries proposed (delay strictly > 24h; ETA tolerance, escalation, follow-up and repeat windows inclusive); pending team confirmation. See `docs/SCENARIO_REVIEW.md`.
- 2026-11: Test datasets defined (dev 3-arm, damaged, null_effect, confounded, staged, heldout template). dev sized so the planted integrator effect is detectable (~2,500 enquiries/arm). Rollout datasets carry true causal effects from counterfactual runs.
- 2026-11: Roles for this stage: Mohamad Nassif generates the data (datagen/) and hands it off; Bahaa Hamdan builds the evaluator. Bahaa reviews the scenario library; Mohamad creates the private heldout set and delivers exports only. Hand-off guide: `docs/DATA_HANDOFF.md`.
