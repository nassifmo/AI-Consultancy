# Scenario Library Review (for Mohamad)

The scenario library (`datagen/scenarios/library.yaml`) holds hand-written golden cases. Each one is a small
dataset in partner export format with the result a correct evaluator must give. They were written from the
service rules (`datagen/config/service_rules.yaml`, version 0.1.0-proposed), not from the generator code.
They will be the acceptance tests for the evaluator we build next.

**Please review independently.** For each row, read the scenario in `library.yaml`, apply the rules
yourself, and tick the last column if you get the same expected result. Mark anything you disagree with.
Run `python -m datagen.scenario_library` to check the file is valid after any edit.

Shared fixtures (shipments and their tracking timelines) are in `datagen/scenarios/base.yaml`, with
hand-written "what the systems showed at time t" checks that the tests compare against the generator.

## Scenarios

| ID | Situation | Expected | What it tests | Agree? |
|---|---|---|---|---|
| S1 | Normal status enquiry answered correctly by the AI | ENQ-S01: **resolved** | AI-only resolution | |
| S2 | Delay over threshold, AI escalates, human updates customer and closes the case in time | ENQ-S02: **resolved** | required escalation done; human case work counted | |
| S2B | Same as S2 but the case is still open at the end of the 14-day observation window | ENQ-S02B: **escalated_open** | escalated_open state | |
| S3 | Delay over threshold, AI gives correct information but does not escalate | ENQ-S03: **failed** | missing required action; false self-report | |
| S4 | AI answers from an old snapshot (before the delay was announced) | ENQ-S04: **failed** | stale information judged against what systems showed when the answer was given | |
| S5 | AI answer correct at the time; the delay is announced one hour later | ENQ-S05: **resolved** | an answer is not penalized for later changes | |
| S5B | Departure happened but was not yet recorded; AI says "booked" | ENQ-S05B: **resolved** | judged against recorded state, not physical reality | |
| S6 | Customer quotes the right booking, AI links another of the customer's shipments | ENQ-S06: **failed** | wrong-shipment detection (stated reference vs linked reference) | |
| S6B | Customer quotes another of their own bookings by mistake; AI answers about that booking | ENQ-S06B: **resolved** | OPEN QUESTION 2: the exports cannot show what the customer meant; evidence supports 'resolved' | |
| S7 | AI gives a wrong ETA, a human notices and sends a correction the same day | ENQ-S07: **resolved** | rescue makes the enquiry resolved but not AI-only; rescue time counted | |
| S8 | Correct AI answer, but the customer contacts again 5 days later about the same shipment | ENQ-S08A: **failed**; ENQ-S08B: **resolved** | repeat contact fails the first enquiry | |
| S9 | Same as S1 but the shipment's tracking history is missing from the export | ENQ-S09: **unknown** | missing evidence gives unknown, not success | |
| S10 | AI states an unsupported ETA (47 h off), reports success, nobody notices | ENQ-S10: **failed** | agent self-report is not trusted | |
| S11 | AI escalates correctly but the case is never actioned (no update, never closed) | ENQ-S11: **failed** | a created ticket alone is not resolution | |
| S12 | Documents request (out of scope), AI hands off to a human | ENQ-S12: **out_of_scope** | out-of-scope excluded with reason | |
| H1 | Human baseline answers correctly after a queue | ENQ-H01: **resolved** | baseline arm | |
| H2 | AI hands off an in-scope enquiry, human answers correctly | ENQ-H02: **resolved** | handoff is not AI-only and not a false self-report | |
| B1 | Claimed ETA exactly 6 h after the known ETA | ENQ-B01: **resolved** | ETA tolerance is inclusive | |
| B2 | Claimed ETA 6 h 1 min after the known ETA | ENQ-B02: **failed** | just outside tolerance | |
| B3 | Known delay exactly 24 h, no escalation | ENQ-B03: **resolved** | escalation threshold is strict (> 24 h) | |
| B4 | Known delay 24 h 1 min, no escalation | ENQ-B04: **failed** | just over the threshold | |
| B5 | Human opens the escalation case exactly 2 h after the enquiry | ENQ-B05: **resolved** | escalation deadline is inclusive | |
| B6 | Human opens the escalation case 2 h 0 min 1 s after the enquiry | ENQ-B06: **failed** | one second late | |
| B7 | Customer update on the escalated case exactly 48 h after the case opened | ENQ-B07: **resolved** | follow-up deadline is inclusive | |
| B8 | Customer update 48 h 1 min after the case opened | ENQ-B08: **failed** | follow-up just late | |
| B9 | Second contact exactly 7 days after the first | ENQ-B09A: **failed**; ENQ-B09B: **resolved** | repeat window is inclusive | |
| B10 | Second contact 7 days and 1 second after the first | ENQ-B10A: **resolved**; ENQ-B10B: **resolved** | just outside the repeat window | |
| D1 | S1 with the enquiry and the answer exported twice | ENQ-D01: **resolved** | duplicates removed, outcome unchanged | |
| D2 | S1 with a failed technical retry logged seconds before the real run | ENQ-D02: **resolved** | retry is not a separate handling or a failure | |
| D3A | AI answer message lost its ETA, but the agent run still records the claim | ENQ-D03A: **resolved** | OPEN QUESTION 3: recoverable from agent_runs, so not unknown | |
| D3B | Human answer message lost its ETA (no other record of what was said) | ENQ-D03B: **unknown** | missing claim on the final answer gives unknown | |
| D4 | S2 where case history shows the case reopened after the closure in the case table | ENQ-D04: **unknown** | conflicting evidence on the deciding case gives unknown | |
| D5 | Case opened_at exported in Beirut local time without its offset | ENQ-D05: **resolved** | read with the file's declared time zone it is on time (09:01:30 UTC); misread as UTC it would look 2 h late | |
| D6 | H1 plus a human-work row for an enquiry that is not in the export | ENQ-D06: **resolved** | orphan rows ignored; human time not inflated | |
| D7 | S2 where the case row has a mistyped enquiry ID | ENQ-D07: **resolved** | case recovered through the customer update that names both case and enquiry | |

## Open questions (team decision needed)

1. **Rule boundaries.** We assumed: delay must be *strictly* over 24 h to require escalation; the 6 h ETA
   tolerance, 2 h escalation deadline, 48 h follow-up deadline and 7-day repeat window are all *inclusive*.
   This is written in `service_rules.yaml` and tested by B1-B10. Confirm or change.
2. **Customer quotes another of their own shipments by mistake (S6B).** The exports cannot show what the
   customer meant, so the evidence supports "resolved", but the generator's truth says "failed". In the dev
   data this affects 7 of 1,663 in-population enquiries (0.4%). Options: (a) set the expected evaluator result
   to what the evidence supports and keep the true outcome separately, or (b) keep it and report it as
   irreducible evaluator error. Proposal: (a).
3. **Fixed while writing D3A.** If the message to the customer loses its ETA but the AI agent's run log still
   records the claim, the evidence is recoverable, so the expected result is not "unknown". The generator
   was marking these "unknown"; this is now corrected (only human messages lose the evidence).
4. **Unnecessary escalations** (agent escalates when the delay is under the threshold) are not penalised; they
   only add human cost. Confirm.
5. **Late rescue.** When a human rescues a missed escalation after the 2 h deadline, the enquiry still fails.
   Confirm that "done late" counts as not done, rather than a partial outcome.
6. **Repeat contacts.** Any contact by the same customer about the same shipment inside 7 days fails the first
   enquiry, whatever the reason (the generator also adds 5% recontacts after correct answers as noise).
   Confirm this definition, or restrict it (e.g. same enquiry type).
7. **Escalation requirement is judged on the delay known when the enquiry arrived.** If the delay is announced
   while the enquiry waits in a human queue, escalation is not required. Confirm.
8. **Escalated-open** enquiries are reported as a separate state, neither resolved nor failed. Confirm how
   they enter KPIs (e.g. excluded from resolution rate, or counted as not yet resolved).
