# Run the shipment agent test locally

The replay tools serve synthetic tracking history visible at the time of each enquiry and write test cases only to an isolated scratchpad. Both models get the same prompt, scenario, and tools. Each trial starts with a fresh world. The suite has five smoke cases, five development cases, and four checked-in challenge cases. The challenge cases are visible in the source and are **not** an independently held-out evaluation. None of these cases measures live shipping operations.

## Rehearse without credentials

From the shipment benchmark directory, in the same Python environment as the evaluator:

```powershell
.venv/Scripts/python.exe -m replay --preflight
.venv/Scripts/python.exe -m replay --output runs/replay-rehearsal-01
.venv/Scripts/python.exe -m pytest -q tests/test_replay_world.py tests/test_replay_openai.py tests/test_replay_runner.py
```

The scripted provider deliberately fails some cases. A successful rehearsal means the pipeline recorded all ten attempted trials with no real API requests and can trace executed actions. It is not a quality result for Luna or Terra.

## Test a local Ollama model

With Ollama running, use `ollama list` to find a local model and `ollama show <model>` to confirm it lists `tools` under capabilities. The model already installed for this project is `qwen2.5:7b-instruct`.

```powershell
.venv/Scripts/python.exe -m replay --ollama qwen2.5:7b-instruct --case-id R01 --case-id R02 --output runs/replay-ollama-01
```

R01 checks shipment status and ETA. R02 also checks the required case-opening path. Remove the case selectors to run all five smoke cases. The runner uses the same prompt, test tools, rubric and verifier as the hosted run. It saves the local tool calls, replies, timings, usage when available, and verifier output. This single-model development run uses the Ollama service on this laptop and needs no API key. Local compute costs are unmeasured. The single-model result provides no paired model comparison. [Ollama tool calling](https://docs.ollama.com/capabilities/tool-calling)

## First live run

Set up the funded provider project and give each collaborator their own authorized key. Set `OPENAI_API_KEY` in each local session using your institution-approved secret handling. Keep keys and results private. Set an appropriate provider limit before the run. The initial comparison uses OpenAI GPT-6 Luna and GPT-6.1 Terra with low reasoning effort and standard processing. Claude is a proposed later cross-provider check and has no runner adapter yet.

```powershell
.venv/Scripts/python.exe -m replay --live --output runs/replay-live-01
```

Defaults: 10 trials, at most four model turns each, up to 800 output tokens per call, no automatic network retries, and an approximate USD 2 local spend stop. The call cap is 50; the default smoke schedule can use at most 40. The stop estimates each pending input at 12,000 tokens, then settles from observed usage. It is not a guarantee of the invoice. Provider billing remains authoritative. If output caps lead to incomplete answers, review usage and change the same limit for both models before a new run. Existing run folders are never overwritten. A provider or metering failure stops the batch without reporting missing charges as zero.

Check the first pairs before increasing volume: each received a fully metered trace, the public reply agrees with the structured fields, the right container and as-of records were used, and the operations case exists where required. Review the paired failure and latency counts, including ungraded trials. Check the provider invoice and adjust spend expectations using actual token usage. Expand only after the developer cases behave as expected.

For an independent test, have Mohamad maintain an unseen batch and freeze prompts, models, graders, dates, scope and metrics before evaluation. He can create a JSON file with `{"origin":"synthetic","cases":[...]}` using the row shape in [cases.py](../replay/cases.py). Mark each row `challenge`, with synthetic `TEST-` references and independently written `expected` fields. Keep the file outside the public repo. Run `python -m replay --live --suite <reviewer-file> --output runs/replay-heldout-01`, with call and spend limits sized to that run. The runner sends the enquiry and necessary tool records; answer labels are not included in API requests. Repeated runs of one case are not independent new shipment cases.

## Results and evidence boundaries

- `manifest.json` records configuration, suite/source hash, and trial list. `trials.jsonl` records answers, tool results, case events, usage and elapsed wall time. `summary.json` shows completed pairs, graded and ungraded trials, and descriptive paired differences. Cost is a standard-rate estimate, before cache adjustments and tax. Measured wall time is not the total time a real customer waited.
- Each trial writes an `exports/` folder that the existing verifier reads, plus `verification.json`. Observations stop at the frozen enquiry clock. The adapter does not manufacture delivery after the synthetic exchange, human follow-up, completed escalations beyond the scratchpad, labour, finance or randomized cohort assignments. Precise sandbox checks and the existing operational verifier have different scopes, including intermediate ports and time tolerance. Inspect disagreements rather than treating one output as the other’s reference.
- Share `reviewer_cases.jsonl` by itself for independent checks of customer-facing wording and actions. The model identity and automatic grades are absent. Reviewers can request the matching time-stamped source rows, especially for claims involving records the agent did not request. This file does not establish independent ownership of the checked-in test scenarios.
- A passing replay tests behavior of model-generated replies and sandbox actions. It cannot produce verified carrier revenue, margin, customer savings or operational ROI. For those, use the [pilot economics data contract](PILOT_ECONOMICS_CONTRACT.md) when company records are authorized and reconciled.

[OpenAI function calls](https://developers.openai.com/api/docs/guides/function-calling) · [Anthropic agent evaluation guidance](https://www.anthropic.com/research/demystifying-evals-for-ai-agents) · [OpenAI project access and spend limits](https://help.openai.com/en/articles/9186755-managing-projects-in-the-api-platform)
