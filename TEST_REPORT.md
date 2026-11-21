# Shipment evaluator meeting release verification

## Local replay and finance checks, 21 November 2026

The full benchmark suite passed 135 tests and 106 subtests after the replay and financial evidence changes. A scripted rehearsal recorded all 28 trials across 14 paired synthetic cases with no API calls. A separate acceptance check exercised a real scratchpad case creation, the identical reply without the case, and a wrong sibling-container reply. The first passed. The latter two were flagged as critical failures. The synthetic financial check produced a USD 4 point threshold. Removing downstream evidence left net expense reduction unknown; widening outcome missingness removed the finite worst-case threshold. See the [readiness walkthrough](docs/READINESS_WALKTHROUGH.md) for the expected behavior and the remaining live checks.

## Repository integration, 19 November 2026

The combined checkout at the data-generator handoff regenerated 56 scenarios, 61 reference enquiries and the clean demo. The original generator and new evaluator suites passed **210 tests and 106 subtests**. The demo ZIP reproduced the folder analysis and the saved run bundle passed its hash checks. Two original scenario tests now check the expanded lifecycle outcomes and the separation of expected answers from the exports directory.

## Pilot demonstration update, 19 November 2026

- The full local suite passed: **89 tests and 106 subtests**, including decision gates and the Streamlit workflow with an adjusted critical failure limit.
- Chrome verified ZIP upload, all five dashboard views, the critical limit change, decision download controls, and a prepared source extract through case review. See the [decision view](qa/decision.png) and [linked enquiry](qa/company-enquiry.png).
- Four synthetic import rehearsals cover complete, duplicate/partial, missing and malformed records. See [the scripted checks and their expected outputs](qa/pilot_readiness.md).
- Reproduced the [sample decision brief](pilot_prospect/DEMO_DECISION.html) from the clean demo. It proposes review and retest at the illustrative 1% limit. At 25%, the illustration still requires evidence for the supplied business value. This establishes expected application behavior on the tested records only.

## Pilot data preparation, 18 November 2026

| Check | Observed result |
| --- | --- |
| Automated checks | 81 tests and 106 subtests passed. The environment reported no broken dependencies. |
| File preparation | The original scenario was mapped from renamed CSV, JSON and JSONL inputs. The command line and browser saved byte-identical preparation bundles. The converter preserved file hashes, row references and the original extracts. |
| Dashboard | Chrome exercised the canonical ZIP and the separate company source ZIP and mapping-profile upload. The checked workflow covered preview, save, evaluation, evidence inspection and download controls. See the [readiness](qa/company-readiness.png) and [enquiry evidence](qa/company-enquiry.png) views. |
| Enquiry verification | The mapped S32 case resolved after a verified human correction. The initial critical failure was preserved, and the linked work record supplied 300 active seconds. No requests were eligible for an attribution comparison because assignment was unavailable. |
| Incomplete data | Focused tests verified that partial history constrains first-answer and case checks, work can produce a documented subtotal without a complete total, and incomplete metering cannot establish complete costs. |
| API collection | Mocked requests covered supported pagination, retries and failure behavior. The example configuration passed a local validation check. No live company endpoint was used. |
| Compatibility | All six revised bulk datasets and the demonstration produced finite JSON and retained their previous enquiry and eligibility counts. Confounded and staged inputs kept their unsupported-design status. The demonstration retained 1,108 eligible initial requests. This checks compatibility and population sizing. |

## Upgrade value follow-up

The updated suite passed 52 tests and 93 subtests. The calculation checks cover missing outcomes, cost coverage, the time target, break-even, and the case where a cheaper policy loses verified successes. The Streamlit test confirms that switching from one-hour resolution to resolution by seven days changes the threshold from $9.73 to $24.35. Browser review verified the new tab on the uploaded demo. [Dashboard screenshot](qa/upgrade-value.png)

## Original meeting release

Executed on 17 November 2026 in a dedicated Windows environment with Python 3.11.9. The package check detected no dependency conflicts. The [dependency lock](requirements-lock.txt) records the versions used.

| Check | Result |
| --- | --- |
| Automated suite | 45 tests and 90 subtests passed, including the original 20 tests. The meeting release stored the transcript locally as `meeting_release/test_transcript.txt`. |
| Scenario and dictionary integrity | The dictionary passed. All 56 scenario exports produced one result per enquiry. The library contains 61 expected enquiry results. Current-policy assertions cover the specified scenarios. Historical expectations remain separately versioned. |
| Independent examples | Hand-specified tests cover checkpoint reconstruction, cutoff-crossing work, elapsed versus active time, continuation work, missing evidence, zero denominators, negative economic trade-offs, and invoice reconciliation. |
| Ground truth isolation | Instrumented reads were confined to the recognized files inside `exports/`. The application rejected archive traversal, links, answer files and excessive expansion in tests. |
| Bootstrap calibration | The individual 95% resolution interval excluded zero in 7 of 200 independent known-null simulations with 500 customers per arm. The predeclared exact binomial acceptance range was 4 to 16. Retained seeds: 6, 27, 37, 103, 151, 155, 177. This check uses a simple null and gives no coverage guarantee for a real rollout. |
| User flow | Streamlit tests exercised evaluation, enquiry review, changing the observation setting, rerunning and download availability. Chrome confirmed the packaged ZIP upload, all four rendered views and preparation of the downloadable files. |
| Reproduction | The full demo ZIP, bundled folder and command line with the saved settings yielded equal analyses. Publishing the same run resolved to the same immutable bundle, and each saved artifact matched its recorded SHA-256 digest. The command line rejected invalid settings with a nonzero exit status. |

## Compatibility runs

All six revised bulk datasets loaded and produced valid JSON. Running `python -m qa.package_meeting_release --bulk` regenerates the machine-readable run record at `meeting_release/bulk_validation.json`. Issue counts reflect validation notices in the exports. These results establish compatibility with the published fields. They do not score agreement with older reference labels.

| Dataset | Contacts | Eligible initial requests | Input issues | Design handling |
| --- | ---: | ---: | ---: | --- |
| Tiny | 49 | 32 | 0 | Recorded random assignment. Limited size for inference. |
| Dev | 9,154 | 6,960 | 2 | Recorded random assignment. |
| Damaged | 9,154 | 6,960 | 11 | Recorded random assignment. Evidence gaps are reported. |
| Null effect | 9,255 | 6,960 | 1 | Recorded random assignment. Sampling can produce a nonzero point estimate. |
| Confounded | 9,767 | 7,316 | 1 | Descriptive before/after trends. Causal attribution unsupported. |
| Staged | 9,228 | 6,960 | 1 | Descriptive regional trends. Causal attribution unsupported. |

## Evidence still needed

Independently review the historical bulk expectations against the applied verification rules before scoring them. Freeze this evaluator before the held-out answers are released. Validate the supported text, evidence joins, service rules, active-work measurements, cost parameters and comparison design against authorized company records. Validate any pilot estimates separately before interpreting them as market or company results.

The bootstrap preserves requests from the same customer together. The 2,000 resamples and threshold of 50 observed customers per arm are release defaults. Regional rollouts require inference that reflects their allocation design. Costing uses documented work, billed units and explicit assumptions about fixed costs and practical capacity. [Cameron and Miller](https://cameron.econ.ucdavis.edu/research/Cameron_Miller_JHR_2015.pdf) · [HM Treasury evaluation methods](https://www.gov.uk/government/publications/the-magenta-book/magenta-book-annex-a-analytical-methods-for-use-within-an-evaluation-html) · [Kaplan and Anderson](https://www.hbs.edu/ris/Publication%20Files/04-045_d62528d4-7931-4ea1-a205-d9683c639d6e.pdf)
