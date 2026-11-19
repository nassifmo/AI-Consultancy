# Evaluating an AI agent in shipment customer support

Bahaa Hamdan and Mohamad Nassif · Advisor meeting, 18 November 2026

**Research question.** How much does adding or upgrading an AI agent change the quality, human effort and cost of handling shipment status and delay enquiries?

**What we built.** We load exported enquiries, tracking events, agent replies, case histories, human work records and billing data. The evaluator checks the evidence available at the time of each answer and follows each request through to its observed outcome. It records an initial error separately from a later human correction. We compare assigned handling policies at a common seven-day checkpoint and can trace each result back to the source records.

| Result on 1,108 eligible synthetic requests | Human handling | Agent v1 | Agent v2 |
| --- | ---: | ---: | ---: |
| Requests | 385 | 348 | 375 |
| Verified resolution | 66.0% | 74.1% | 70.1% |
| Active human minutes per request | 12.31 | 4.20 | 3.66 |
| Scoped resource cost per request (USD) | $4.10 | $6.09 | $5.88 |

**What the demonstration shows.** Both AI groups used less recorded human time. Both had higher scoped resource costs after allocating platform, setup and maintenance costs. The results suggest capacity could be reassigned in the simulated setting. Cash savings and the use of that capacity remain unmeasured. Some outcomes lack sufficient evidence, and the resulting bounds allow either an improvement or a decline in overall resolution.

**What we will validate next.** We will freeze the evaluator before testing on Mohamad’s held-out exports. For a pilot, we would confirm how the company records assignments, tracking changes, follow-ups, active work and spending. CMA CGM is our first pilot opportunity. Company data access and participation remain unconfirmed.
