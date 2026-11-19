# Synthetic datasets for the meeting

Run from the shipment benchmark directory in the prepared Python environment. Choose a new release directory when regenerating.

```powershell
python -m datagen.dictionary_tools check
python -m datagen.scenario_library
python -m datagen.build_datasets --out-root datagen/datasets/release_1 demo tiny dev damaged null_effect confounded staged
```

Give the runtime only the selected dataset's `exports/` folder. Generation also writes `ground_truth/`, a separate manifest, and a review sheet for small datasets. These files belong to benchmark preparation and independent scoring.

| Dataset | Intended use |
|---|---|
| `demo` | Clean three-arm demonstration using simulated operations, effort, and rates |
| `tiny` | Row-level walkthrough on a small clean dataset |
| `dev` | Larger randomized three-arm comparison with light data damage |
| `damaged` | The same generated world and assigned policies as dev, with more extensive export damage |
| `null_effect` | Identical v1/v2 behavior parameters, independently simulated outcomes |
| `confounded` | A time-based rollout that coincides with a simulated operational change |
| `staged` | A country-based switch with effective assignment rows in `rollout_log.csv` |

Each initial request carries its recorded assignment. Later contacts created by the simulation inherit the same allocation and root, including the allocation time. English customer wording is scripted for the simulation. A continuation can contain a routine request for a fresh update or an explicit report about an outstanding issue. The recorded relationship alone does not establish service failure.

The new export contract is version 1.0. The bulk reference outcomes still follow historical generator rules under `0.1.0-proposed`. They retain the previous ETA tolerance, closure and repeat-outcome logic, and observation windows. This includes known cases where a closure reason fails the newer service rubric or a new contact was counted as a failure under the historical generator. Treat the bulk reference files as historical until a reference reviewer aligns the population, checkpoint, rule definitions, and expected fields. Use the independently specified current-policy scenarios for matching rule-aware checks. [Original scenario review](../docs/SCENARIO_REVIEW.md) · [Current scoring rules](../RULES_FOR_REVIEW.md)

Human work records in the clean simulation use synthetic staff assignments that avoid overlapping intervals for the same worker. The recorded active time includes after-contact work for handling records. Metering includes explicit zero voice seconds for nonvoice runs. Injected technical retries can have missing usage and fall outside the original invoice snapshot. Those datasets carry an incomplete metering flag. All business assumptions and results are synthetic.
