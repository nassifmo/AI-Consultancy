"""Reconstruct grading evidence from shipment enquiries and their exports."""

from collections import defaultdict
from copy import copy
from dataclasses import replace
from datetime import timedelta
from math import isfinite
import re

from .casework import review_casework
from .claim_checks import historical_benchmark, mentions_action, mentions_status
from .eta_handoff import review_eta_handoff
from .exports import MEASURED_WORK_METHODS, load_exports, reference
from .grading import grade_enquiry
from .replies import ETA_REQUEST, coordination_request, explicit_eta_request, interpret_exchange, review_reply
from .tracking import Tracking


REPEAT = re.compile(r"never arrived|still waiting|same confirmation|not yet received", re.IGNORECASE)
NEW_ESTIMATE = re.compile(r"newly published eta|new schedule update", re.IGNORECASE)
ANSWER_PURPOSES = {"answer", "correction"}


def _index(rows, key):
    result = defaultdict(list)
    for row in rows:
        if row.get(key):
            result[row[key]].append(row)
    return result


def _settings(policy):
    if not isinstance(policy, dict) or not isinstance(policy.get("version"), str) or not policy["version"].strip():
        raise ValueError("Provide a versioned grading policy.")
    settings = policy.get("verification")
    if not isinstance(settings, dict) or not isinstance(settings.get("port_timezones"), dict):
        raise ValueError("Provide verification settings and port_timezones in the policy.")
    for key in ("port_names", "port_timezones"):
        values = settings.get(key, {})
        if not isinstance(values, dict) or any(not isinstance(value, str) or not value.strip() for value in values.values()):
            raise ValueError(f"verification.{key} needs nonempty text values.")
    for key in (
        "delay_hours", "escalation_hours", "followup_hours", "repeat_window_days",
        "routine_eta_minor_seconds", "deadline_minor_seconds",
    ):
        value = settings.get(key)
        if type(value) not in (int, float) or not isfinite(value) or value < 0:
            raise ValueError(f"verification.{key} must be a nonnegative, finite number.")
    return settings


def _work_time(data, rows, actor_ids, replies, runs, received, excluded_work_ids=()):
    """Sum attributable active durations, with incomplete totals left unknown."""
    unknown = not data.is_complete("agent_work") or received is None or data.cutoff is None
    known = 0
    refs = []
    unmeasured_refs = []
    intervals = defaultdict(list)
    observed_work = False
    for row in rows:
        start = data.time("agent_work", row.get("accepted_at"))
        end = data.time("agent_work", row.get("closed_at"))
        if start is not None and data.cutoff is not None and start > data.cutoff:
            continue
        if start is not None and received is not None and data.cutoff is not None and received <= start <= data.cutoff:
            observed_work = True
            if row.get("measurement_method") not in MEASURED_WORK_METHODS:
                unmeasured_refs.append(reference("agent_work", row))
                unknown = True
                continue
        overlap_at = excluded_work_ids.get(row["work_id"]) if excluded_work_ids else None
        if overlap_at is not None and data.cutoff is not None and overlap_at <= data.cutoff:
            unknown = True
            continue
        if start is None or end is None or received is None or data.cutoff is None or not received <= start <= end <= data.cutoff:
            unknown = True
            continue
        try:
            duration = float(row.get("active_seconds") or "")
        except (ValueError, TypeError):
            unknown = True
            continue
        if not isfinite(duration) or not 0 <= duration <= (end - start).total_seconds():
            unknown = True
            continue
        intervals[row["agent_id"]].append((start, end, duration, reference("agent_work", row)))

    for entries in intervals.values():
        last_end = None
        for start, end, duration, ref in sorted(entries):
            if last_end is not None and start < last_end:
                unknown = True
                last_end = max(last_end, end)
                continue
            known += duration
            refs.append(ref)
            last_end = end

    if actor_ids - intervals.keys():
        unknown = True
    human_reply = any(reply["actor_type"] == "human" for reply in replies)
    handoff = any(run.get("handoff_flag") is True for run in runs)
    documented_human = bool(observed_work or actor_ids or human_reply)
    only_ai = None
    if documented_human:
        only_ai = False
    elif (replies and all(reply["actor_type"] == "ai_agent" for reply in replies)
          and runs and all(run.get("handoff_flag") is False for run in runs)
          and not handoff and not unknown and all(data.is_complete(name) for name in ("responses", "agent_runs"))):
        only_ai = True
    total = None if unknown or not (refs or only_ai) else known
    result = {"active_seconds": total, "recorded_seconds": known if refs else None,
              "refs": refs, "ai_only_handling": only_ai}
    if unmeasured_refs:
        result["unmeasured_refs"] = sorted(unmeasured_refs)
    return result


class Verifier:
    def __init__(self, data, policy, *, excluded_work_ids=(), claim_reader=None):
        self.data = data
        self.policy = policy
        self.settings = _settings(policy)
        self.tracking = Tracking(data)
        self.enquiries = data.tables["enquiries"]
        self.responses = _index(data.tables["responses"], "enquiry_id")
        self.response_conflicts = _index(data.conflicts["responses"], "enquiry_id")
        self.responses_by_case = _index(data.tables["responses"], "case_id")
        self.runs = _index(data.tables["agent_runs"], "enquiry_id")
        self.history = _index(data.tables["case_history"], "case_id")
        self.work = _index(data.tables["agent_work"], "enquiry_id")
        self.related = _index(self.enquiries, "related_enquiry_id")
        self.excluded_work_ids = excluded_work_ids
        self.claim_reader = claim_reader
        self.enquiries_by_id = {row["enquiry_id"]: row for row in self.enquiries}
        self.case_candidates = _index(data.tables["cases"], "enquiry_id")
        for case in data.tables["cases"]:
            for enquiry_id in {reply["enquiry_id"] for reply in self.responses_by_case[case["case_id"]]}:
                if enquiry_id != case["enquiry_id"]:
                    self.case_candidates[enquiry_id].append(case)
        self.cases = self._link_cases()

    def evaluate_at(self, enquiry, cutoff, excluded_work_ids):
        """Reuse indexes while reconstructing only evidence visible at this instant."""
        view = copy(self)
        view.data = replace(self.data, cutoff=cutoff, issues=[])
        view.tracking = copy(self.tracking)
        view.tracking.data = view.data
        view.excluded_work_ids = excluded_work_ids
        enquiry_id = enquiry["enquiry_id"]
        view.cases = {enquiry_id: [
            case for case in self.case_candidates[enquiry_id] if view._case_owner(case) == enquiry_id
        ]}
        return view.evaluate(enquiry)

    def _case_owner(self, case):
        known = self.enquiries_by_id
        enquiry_id = case["enquiry_id"]
        cutoff = self.data.cutoff
        linked_replies = [
            row for row in self.responses_by_case[case["case_id"]]
            if (sent := self.data.time("responses", row["sent_at"])) is not None and cutoff is not None and sent <= cutoff
        ]
        corroborated = {row["enquiry_id"] for row in linked_replies if row["enquiry_id"] in known}
        if enquiry_id not in known and len(corroborated) == 1:
            candidate_id = next(iter(corroborated))
            for reply in linked_replies:
                if reply["enquiry_id"] != candidate_id:
                    continue
                sent = self.data.time("responses", reply["sent_at"])
                target = self.tracking.for_request(known[candidate_id], sent)
                reported = self.tracking.resolve(reply.get("shipment_reference"))
                if target and reported and target.shipment["booking_ref"] == reported.shipment["booking_ref"]:
                    enquiry_id = candidate_id
                    break
        if enquiry_id in known and not corroborated.difference({enquiry_id}):
            return enquiry_id
        return None

    def _link_cases(self):
        linked = defaultdict(list)
        for case in self.data.tables["cases"]:
            enquiry_id = self._case_owner(case)
            if enquiry_id:
                linked[enquiry_id].append(case)
            else:
                self.data.issues.append({"table": "cases", "code": "unverified_enquiry_link", "ref": reference("cases", case)})
        return linked

    def _visible(self, table, rows, column, received):
        if received is None or self.data.cutoff is None:
            return []
        visible = []
        for row in rows:
            at = self.data.time(table, row[column])
            if at is None:
                self.data.issues.append({"table": table, "code": "unverified_timestamp", "ref": reference(table, row)})
            elif received <= at <= self.data.cutoff:
                visible.append((at, row))
        return sorted(visible, key=lambda item: item[0])

    def _recontact(self, enquiry, received):
        data = self.data
        if data.cutoff is None or received is None or received > data.cutoff:
            return {"same_unresolved_request": None, "refs": []}
        end = received + timedelta(days=self.settings["repeat_window_days"])
        unknown = data.cutoff < end or not data.is_complete("enquiries") or "related_enquiry_id" not in enquiry
        refs = []
        for related in self.related[enquiry["enquiry_id"]]:
            if related.get("contact_relation") == "new_request":
                continue
            at = data.time("enquiries", related["received_at"])
            if at is None:
                unknown = True
                continue
            if not received < at <= min(end, data.cutoff):
                continue
            first_target = self.tracking.for_request(enquiry, at)
            next_target = self.tracking.for_request(related, at)
            if first_target is None or next_target is None:
                unknown = True
                continue
            if first_target.shipment["booking_ref"] != next_target.shipment["booking_ref"]:
                continue
            if first_target.container != next_target.container and first_target.container and next_target.container:
                continue
            refs.append(reference("enquiries", related))
            message = related.get("customer_message") or ""
            if REPEAT.search(message):
                return {"same_unresolved_request": True, "refs": refs}
            first_snapshot = self.tracking.snapshot(first_target, received)
            next_snapshot = self.tracking.snapshot(next_target, at)
            if not (NEW_ESTIMATE.search(message) and first_snapshot.eta and next_snapshot.eta
                    and next_snapshot.eta != first_snapshot.eta):
                unknown = True
        return {"same_unresolved_request": None if unknown else False, "refs": refs}

    def _study_population(self, received):
        period = self.data.metadata.get("study_period")
        if received is None or not isinstance(period, list) or len(period) != 2:
            return None
        start, end = (self.data.time("enquiries", value) for value in period)
        return start <= received < end if start and end and start <= end else None

    def _contains_update(self, enquiry, row):
        if row["purpose"] != "case_update":
            return False
        if self.claim_reader is None and historical_benchmark(self.data):
            return bool(row.get("claimed_eta") or row.get("claimed_status"))
        text = row.get("message_text") or ""
        if ETA_REQUEST.search(text) or mentions_status(text) or mentions_action(text):
            return True
        reading = interpret_exchange(self.claim_reader, enquiry.get("customer_message") or "", text)
        return bool(reading and reading.state == "classified" and reading.intent == "arrival_time"
                    and reading.response in {"provided", "declared_unavailable"})

    def evaluate(self, enquiry):
        data, settings = self.data, self.settings
        enquiry_id = enquiry["enquiry_id"]
        enquiry_ref = reference("enquiries", enquiry)
        received = data.time("enquiries", enquiry["received_at"])
        in_scope = enquiry["enquiry_type"] in {"status", "delay"}
        group = {"enquiry_id": enquiry_id, "in_scope": in_scope, "in_study_period": self._study_population(received)}
        if not in_scope:
            return {**group, "policy_version": self.policy["version"],
                    "outcome": {"state": "out_of_scope", "refs": [enquiry_ref]}}

        ordered = self._visible("responses", self.responses[enquiry_id], "sent_at", received)
        responses = [row for _, row in ordered]
        runs = [row for _, row in self._visible("agent_runs", self.runs[enquiry_id], "ended_at", received)]
        first_candidates = [(at, row) for at, row in ordered if row["purpose"] in ANSWER_PURPOSES]
        missing_replies = any(data.time("responses", row["sent_at"]) is None for row in self.responses[enquiry_id])
        conflicted_replies = any(
            (at := data.time("responses", row.get("sent_at"))) is None or data.cutoff is None or at <= data.cutoff
            for row in self.response_conflicts[enquiry_id]
        )
        response_order_known = data.is_complete("responses") and not (
            missing_replies or conflicted_replies or "responses" in data.unscoped)
        final_candidates = [
            (at, row) for at, row in ordered
            if response_order_known and (row["purpose"] in ANSWER_PURPOSES or self._contains_update(enquiry, row))
        ]
        first = first_candidates[0][1] if (first_candidates and response_order_known
                and first_candidates[0][1]["purpose"] == "answer"
                and (len(first_candidates) == 1 or first_candidates[0][0] != first_candidates[1][0])) else None
        final = final_candidates[-1][1] if (final_candidates and response_order_known
                and (len(final_candidates) == 1 or final_candidates[-1][0] != final_candidates[-2][0])) else None
        cases = self.cases[enquiry_id]
        histories = [change for case in cases for change in self.history[case["case_id"]]]
        options = {"claim_reader": self.claim_reader, "cases": cases, "histories": histories}
        initial = review_reply(data, self.tracking, enquiry, first, runs, settings, **options) if first else None
        last = initial if final is first else (
            review_reply(data, self.tracking, enquiry, final, runs, settings, **options) if final else None
        )
        for review in (initial,) if last is initial else (initial, last):
            if review:
                self._review_eta_follow_up(enquiry, review, cases, histories, runs)

        required, trigger, trigger_refs = None, None, []
        if received is not None and data.cutoff is not None and received <= data.cutoff:
            target = self.tracking.for_request(enquiry, data.cutoff)
            if target is not None:
                start = received
                if self.tracking.for_request(enquiry, received) is None:
                    start = data.time("enquiries", enquiry.get("reference_confirmed_at"))
                if start is not None and received <= start <= data.cutoff:
                    # A revision after routine handling finished does not retroactively
                    # require escalation on the already answered request.
                    through = data.cutoff
                    if enquiry["enquiry_type"] == "status" and initial and initial.verdict == "supported":
                        through = first_candidates[0][0]
                    required, trigger, trigger_refs = self.tracking.escalation(target, start, through, settings["delay_hours"])

        profile = "shipment_status"
        if coordination_request(enquiry):
            profile = "arrival_coordination"
        elif enquiry["enquiry_type"] == "delay" or required is True:
            profile = "shipment_delay"

        casework = review_casework(
            data, enquiry, cases, histories, responses if response_order_known else [], runs,
            required=required, trigger_at=trigger,
            initial_reply=first, escalation_hours=settings["escalation_hours"], followup_hours=settings["followup_hours"],
            deadline_minor_seconds=settings["deadline_minor_seconds"],
        )
        repeat = self._recontact(enquiry, received)
        outcome = self._outcome(enquiry_ref, responses, last, casework, required, repeat, response_order_known)
        conditions = {
            "escalation_required": required,
            "follow_up_required": casework.follow_up_required,
            "eta_reply_in_scope": initial.eta_in_scope if initial else None,
            "eta_requested": explicit_eta_request(enquiry) or bool(initial and initial.requested_eta),
            "status_reply_in_scope": initial.status_in_scope if initial else None,
            "sent_action_claim_in_scope": bool(initial.action_in_scope) if initial else None,
        }
        evidence = dict(initial.evidence) if initial else {}
        evidence.update(casework.evidence)
        result = grade_enquiry(self.policy, {
            "enquiry_id": enquiry_id, "profile": profile,
            "conditions": conditions, "evidence": evidence, "outcome": outcome,
        })
        actors = casework.human_actor_ids | {row["actor_id"] for row in responses
                                           if row["actor_type"] == "human" and row.get("actor_id")}
        work = [row for row in self.work[enquiry_id] if not row.get("case_id") or row["case_id"] in casework.case_ids]
        resolved = result["outcome"]["state"] == "resolved"
        resolved_at = None
        if resolved:
            delivered_at = data.time("responses", last.reply["sent_at"])
            resolved_at = max(delivered_at, casework.resolved_at or delivered_at).isoformat()
        recovered = None
        if result["outcome"]["state"] != "unknown" and result["initial_failure"] is not None:
            recovered = resolved and result["initial_failure"] and last.reply["actor_type"] == "human"
        result["verification"] = {
            "initial_reply": self._reply_summary(initial),
            "last_reply": self._reply_summary(last),
            "escalation": {"required": required, "trigger_at": trigger.isoformat() if trigger else None, "refs": trigger_refs},
            "case_ids": casework.case_ids,
            "resolved_at": resolved_at,
            "human_recovery": recovered,
            "repeat_contact": repeat,
            "human_work": _work_time(data, work, actors, responses, runs, received, self.excluded_work_ids),
        }
        return {**group, **result}

    def _review_eta_follow_up(self, enquiry, review, cases, histories, runs):
        requested = review.requested_eta or {}
        if requested.get("state") not in {"omitted", "declared_unavailable"}:
            return
        handoff = review_eta_handoff(self.data, enquiry, review.reply, cases, histories, runs)
        requested["handoff"] = handoff
        review.refs = list(dict.fromkeys([*review.refs, *handoff["refs"]]))
        if requested["state"] == "declared_unavailable" and (handoff["state"] == "not_recorded" or handoff["pending"] is False):
            if review.verdict != "failed":
                review.reason = "The reply says the ETA is unavailable and the records show no pending handoff."
            review.verdict = "failed"
            review.matches_record = False

    def _reply_summary(self, review):
        if review is None:
            return None
        summary = {
            "actor_type": review.reply["actor_type"],
            "actor_id": review.reply.get("actor_id") or None,
            "sent_at": self.data.time("responses", review.reply["sent_at"]).isoformat(),
            "verdict": review.verdict,
            "matches_record": review.matches_record,
            "reason": review.reason,
            "refs": review.refs,
        }
        if review.reply_claims is not None:
            summary["reply_claims"] = review.reply_claims
        if review.requested_eta is not None:
            summary["requested_eta"] = review.requested_eta
        if review.eta_interpretation is not None:
            summary["eta_interpretation"] = review.eta_interpretation
        return summary

    def _outcome(self, enquiry_ref, responses, last, casework, required, repeat, order_known):
        if casework.outcome and casework.outcome["state"] != "resolved":
            return casework.outcome
        if last is None:
            if responses and all(row["purpose"] == "clarification" for row in responses) and order_known:
                return {"state": "awaiting_customer", "refs": [enquiry_ref, reference("responses", responses[-1])]}
            return None
        if repeat["same_unresolved_request"] is True:
            return {"state": "failed", "refs": last.refs + repeat["refs"]}
        handoff = (last.requested_eta or {}).get("handoff")
        if handoff:
            if casework.outcome and casework.outcome["state"] == "resolved":
                return {"state": "failed", "refs": last.refs + casework.outcome["refs"]}
            if handoff["pending"] is True:
                return {"state": "escalated_open", "refs": last.refs}
            if handoff["state"] == "unknown" or (handoff["state"] == "verified" and handoff["pending"] is None):
                return None
        if last.verdict == "failed" and "responses" in self.data.available:
            return {"state": "failed", "refs": last.refs}
        if last.verdict == "supported" and casework.outcome:
            return {"state": "resolved", "refs": casework.outcome["refs"] + last.refs}
        if last.verdict == "supported" and required is False:
            return {"state": "resolved", "refs": last.refs}
        escalation = casework.evidence.get("initial_escalation") or {}
        if required is True and not casework.case_ids and False in escalation.get("steps", {}).values():
            return {"state": "failed", "refs": last.refs + escalation["refs"]}
        return None


def verify_exports(exports_path, policy, *, claim_reader=None):
    """Evaluate an exports directory using no benchmark answer files."""
    data = load_exports(exports_path, require_approval=True)
    evaluator = Verifier(data, policy, claim_reader=claim_reader)
    enquiries = [evaluator.evaluate(enquiry) for enquiry in evaluator.enquiries]
    return {
        "policy_version": policy["version"],
        "export_rule_version": data.metadata.get("rule_version"),
        "data_cutoff": data.cutoff.isoformat() if data.cutoff else None,
        "input_issues": data.issues,
        **({"intake_approval": data.intake_approval} if data.intake_approval else {}),
        "enquiries": enquiries,
    }
