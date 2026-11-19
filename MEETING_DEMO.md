# Shipment AI value evaluator demonstration

The 18 November 2026 meeting release evaluates the handling of shipment-status and delay enquiries using synthetic records. [Launch instructions](README.md)

| Time | What to show |
| --- | --- |
| 0:00–0:45 | Launch the app, choose the clean three-arm demonstration, and open **Data readiness**. Point to the study period, evidence cutoff, eligible initial requests, and assignment records. |
| 0:45–1:45 | Choose **S32**, run it, and open **Enquiry evidence**. The initial reply used another container’s discharge event. The critical finding stays visible after a human corrects the answer. Show the linked records and five active minutes of logged human work. |
| 1:45–3:10 | Return to the clean demo and open **Comparison**. Show verified resolutions and unknown outcomes across human handling, v1, and v2. Explain that the seven-day checkpoint makes follow-up comparable. The bounds show how conclusions may change depending on the unknown outcomes. |
| 3:10–4:20 | Open **Costs and settings**. Show active human minutes, invoice reconciliation, the allocation of setup and maintenance, and the resulting cost per request. Explain that freed time can be used for other work while actual changes in spending still need evidence. |
| 4:20–5:00 | Show the downloadable results and the saved run bundle. Close with the held-out test and the company fields a pilot would need, including assignment, case history, active-work logging, and finance records. |

## What the analysis can establish

- The prototype checks what the support team and AI did against the available records. It uses recorded assignment and one initial request per episode for comparisons. Verified resolution, unknown-outcome bounds and sampling intervals each answer a different question. [HM Treasury evaluation methods](https://www.gov.uk/government/publications/the-magenta-book/magenta-book-annex-a-analytical-methods-for-use-within-an-evaluation-html) · [Cameron and Miller on clustered inference](https://cameron.econ.ucdavis.edu/research/Cameron_Miller_JHR_2015.pdf)
- Recorded active work measures labour use. The resource costs use supplied labour and contract inputs. Realized cash savings require observed expenditure and a credible comparison. [Kaplan and Anderson on practical capacity](https://www.hbs.edu/ris/Publication%20Files/04-045_d62528d4-7931-4ea1-a205-d9683c639d6e.pdf)
- The before/after and staged datasets demonstrate why rollout comparisons need stronger evidence. The release shows descriptive results and flags unsupported attribution. Company validation will calibrate the service rules, available language and records, and comparison design. [HM Treasury evaluation methods](https://www.gov.uk/government/publications/the-magenta-book/magenta-book-annex-a-analytical-methods-for-use-within-an-evaluation-html)

## Remaining work

Freeze the reviewed release and score Mohamad’s held-out exports once available. Reconcile historical bulk labels against independently reviewed current-policy references before scoring agreement on those datasets. Review company field mappings, text interpretation, service rules, logging completeness, and cost and attribution inputs with an authorized workflow owner. CMA CGM remains a pilot opportunity.
