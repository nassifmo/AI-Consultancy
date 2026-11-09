"""Layers 4-5: how each enquiry is handled (human baseline or an AI agent version),
escalation cases, human work, rescues of bad AI answers, and repeat contacts.

Each enquiry gets a `Truth` record describing what really happened. Export rows
(agent runs, cases, case history, human work, responses) are what a partner would see.

Judging rule (service_rules.yaml): an answer is correct when it matches what the
carrier's systems showed *at the moment it was given* (`known_state_at`), not what
physically happened.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from datagen.config_schema import AgentBehaviour, GeneratorConfig, ServiceRules

from . import ids
from .model import Enquiry, Shipment, World
from .sampling import choice_weighted, hours, layer_rng, lognormal, uniform_time
from .state import STATUS_ORDER, known_state_at

HUMAN_BASELINE = "human_baseline"
ARRIVED_OR_LATER = set(STATUS_ORDER[STATUS_ORDER.index("arrived") :])
TYPO_LOOKUP_EXTRA_MINUTES = 3.0  # human searches the customer's account when the reference is wrong
HUMAN_SPOTS_OTHER_SHIPMENT = 0.5  # human notices the customer quoted another of their shipments


# ---------------------------------------------------------------- records


@dataclass
class Answer:
    sent_at: datetime
    actor_type: str
    actor_id: str
    linked: Shipment | None
    claimed_status: str | None
    claimed_eta: datetime | None
    correct: bool
    purpose: str = "answer"


@dataclass
class EscalationCase:
    row: dict
    shipment: Shipment
    opened_at: datetime
    first_update_at: datetime | None
    closed_at: datetime | None


@dataclass
class Truth:
    enquiry: Enquiry
    arm: str
    in_scope: bool
    in_population: bool
    answers: list[Answer] = field(default_factory=list)
    escalation_required: bool | None = None
    required_actions_done: bool | None = None
    escalations: list[EscalationCase] = field(default_factory=list)
    handed_off: bool = False
    rescued: bool = False
    stale_snapshot_used: bool = False
    human_seconds: int = 0
    ai_cost: float = 0.0
    self_reported: str | None = None
    service_outcome: str | None = None  # before repeat contacts are considered
    true_outcome: str | None = None
    repeat_contact: bool = False
    scenario_id: str = ""

    @property
    def first_answer(self) -> Answer | None:
        return self.answers[0] if self.answers else None

    @property
    def final_answer(self) -> Answer | None:
        return self.answers[-1] if self.answers else None


@dataclass
class Handled:
    truths: list[Truth] = field(default_factory=list)
    agent_runs: list[dict] = field(default_factory=list)
    cases: list[dict] = field(default_factory=list)
    case_history: list[dict] = field(default_factory=list)
    agent_work: list[dict] = field(default_factory=list)
    responses: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------- handler


class Handler:
    def __init__(self, cfg: GeneratorConfig, rules: ServiceRules, world: World):
        self.cfg, self.rules, self.w = cfg, rules, world
        self.rng = layer_rng(cfg.seed, "handling")
        self.out = Handled()
        self.humans = [f"HUM-{i:03d}" for i in range(1, int(cfg.costs.staffing.baseline_headcount) + 1)]
        self.ref_index: dict[str, Shipment] = {}
        self.by_customer: dict[str, list[Shipment]] = {}
        for s in world.shipments:
            for r in (s.booking_ref, s.bl_ref, *s.container_refs):
                self.ref_index[r] = s
            self.by_customer.setdefault(s.customer_id, []).append(s)
        self.prices = cfg.costs.unit_prices
        self.tol = timedelta(hours=rules.information_check.eta_tolerance_hours)

    # ------------------------------------------------------------ helpers

    def skew(self, spec) -> float:
        return lognormal(self.rng, spec.median, spec.p95)

    def human(self) -> str:
        return self.rng.choice(self.humans)

    def known(self, s: Shipment, t: datetime):
        return known_state_at(self.w.events_for(s.booking_ref), t)

    def is_correct(self, true: Shipment, linked: Shipment | None, status, eta, at: datetime) -> bool:
        if linked is None or linked.booking_ref != true.booking_ref:
            return False
        k = self.known(true, at)
        if self.rules.information_check.status_must_match_latest_recorded and status != k.status:
            return False
        if k.eta is None or eta is None:
            return k.eta is None and eta is None
        return abs(eta - k.eta) <= self.tol

    def needs_escalation(self, s: Shipment, status, eta) -> bool:
        if eta is None or status in ARRIVED_OR_LATER:
            return False
        return (eta - s.planned_arrival) > hours(self.rules.escalation.escalate_if_delay_hours)

    def assign_arm(self, q: Enquiry) -> str:
        d = self.cfg.design
        if q.repeat_of is not None:
            return q.repeat_of.arm
        if d.type == "randomized_split":
            return choice_weighted(self.rng, {a.name: a.share for a in d.arms})
        rollout = datetime.combine(d.rollout_date, datetime.min.time(), tzinfo=q.received_at.tzinfo)
        before, after = d.arms[0].name, d.arms[1].name
        if q.received_at < rollout:
            return before
        if d.type == "staged_rollout":
            countries = sorted({c.country for c in self.w.customers})
            country = next(c.country for c in self.w.customers if c.customer_id == q.customer_id)
            return after if countries.index(country) < len(countries) / 2 else before
        return after  # before_after_confounded

    def work(self, t: Truth, activity: str, start: datetime, active_min: float, case: dict | None = None) -> datetime:
        active = max(30, round(active_min * 60))
        handle = round(active * self.rng.uniform(1.1, 1.5))
        acw = round(self.skew(self.cfg.human.acw_minutes) * 60) if activity == "handle_enquiry" else 0
        closed = start + timedelta(seconds=handle + acw)
        self.out.agent_work.append(
            {
                "_enq": t.enquiry,
                "_case": case,
                "agent_id": self.human(),
                "accepted_at": start,
                "closed_at": closed,
                "active_seconds": active + acw,
                "handle_seconds": handle,
                "acw_seconds": acw,
                "activity": activity,
                "measurement_method": "logged",
            }
        )
        t.human_seconds += active + acw
        return closed

    def respond(self, t: Truth, a: Answer, case: dict | None = None, text: str | None = None) -> None:
        self.out.responses.append(
            {
                "_enq": t.enquiry,
                "_case": case,
                "sent_at": a.sent_at,
                "actor_type": a.actor_type,
                "actor_id": a.actor_id,
                "purpose": a.purpose,
                "shipment_reference": a.linked.booking_ref if a.linked else None,
                "claimed_status": a.claimed_status,
                "claimed_eta": a.claimed_eta,
                "message_text": text or _message(a),
            }
        )
        if a.purpose != "case_update":
            t.answers.append(a)

    def history(self, case: dict, at: datetime, fld: str, old, new, by: str) -> None:
        self.out.case_history.append(
            {"_case": case, "changed_at": at, "field": fld, "old_value": old, "new_value": new, "changed_by": by}
        )

    # ------------------------------------------------------------ cases

    def open_escalation(self, t: Truth, s: Shipment, at: datetime, opened_by: str) -> EscalationCase:
        hc = self.cfg.human
        owner = self.human()
        case = {"_enq": t.enquiry, "opened_at": at, "reason": "delay_investigation", "owner_id": owner,
                "priority": "high", "closed_at": None, "closure_code": None}
        self.out.cases.append(case)
        self.history(case, at, "status", None, "new", opened_by)
        self.history(case, at, "owner", None, owner, "system")
        self.history(case, at + timedelta(minutes=1), "status", "new", "escalated", opened_by)
        esc = EscalationCase(case, s, at, None, None)
        t.escalations.append(esc)

        if self.rng.random() >= hc.case_followup_compliance:
            return esc  # never actioned: no investigation, no update, no closure

        start = at + timedelta(minutes=self.skew(hc.queue_minutes))
        self.work(t, "handle_case", start, self.skew(hc.case_minutes), case)
        deadline = self.rules.follow_up.followup_deadline_hours
        upd = uniform_time(self.rng, at + hours(min(2.0, deadline / 2)), at + hours(deadline))
        k = self.known(s, upd)
        self.work(t, "follow_up", upd - timedelta(minutes=5), self.skew(hc.followup_minutes), case)
        self.respond(t, Answer(upd, "human", owner, s, k.status, k.eta, True, "case_update"), case)
        esc.first_update_at = upd
        self.history(case, upd, "status", "escalated", "open", owner)

        closed = upd + timedelta(days=self.skew(hc.case_resolution_days))
        code = "resolved_after_investigation" if self.rng.random() < 0.9 else "customer_unreachable"
        case.update(closed_at=closed, closure_code=code)
        self.history(case, closed, "status", "open", "closed", owner)
        esc.closed_at = closed
        return esc

    # ------------------------------------------------------------ human handling

    def human_answer(self, t: Truth, start: datetime, via_handoff: bool) -> None:
        q, hc = t.enquiry, self.cfg.human
        true = self.w.shipment(q.true_booking_ref)
        minutes = self.skew(hc.handle_minutes)
        linked = self.ref_index.get(q.stated_reference)
        if linked is None:
            linked, minutes = true, minutes + TYPO_LOOKUP_EXTRA_MINUTES
        elif linked is not true and self.rng.random() < HUMAN_SPOTS_OTHER_SHIPMENT:
            linked = true
        sent = self.work(t, "handle_enquiry", start, minutes)
        actor = self.out.agent_work[-1]["agent_id"]
        if not t.in_scope:
            self.respond(t, Answer(sent, "human", actor, None, None, None, False),
                         text="Your request has been forwarded to the documentation team.")
            return
        k = self.known(linked, sent)
        status, eta = k.status, k.eta
        if eta is not None and self.rng.random() < hc.error_rate:
            eta = eta + hours(self.rng.choice([-1, 1]) * self.rng.uniform(12, 48))
        a = Answer(sent, "human", actor, linked, status, eta, self.is_correct(true, linked, status, eta, sent))
        self.respond(t, a)
        if self.needs_escalation(linked, status, eta) and self.rng.random() < hc.escalation_compliance:
            self.open_escalation(t, linked, sent + timedelta(minutes=1), actor)

    # ------------------------------------------------------------ AI handling

    def ai_answer(self, t: Truth, version: str) -> None:
        q, b = t.enquiry, self.cfg.agents[version]
        true = self.w.shipment(q.true_booking_ref)
        if q.channel == "email":
            start = q.received_at + timedelta(minutes=self.rng.uniform(5, 60))
        else:
            start = q.received_at + timedelta(seconds=self.rng.uniform(0, 60))
        voice = round(self.skew(b.voice_seconds)) if q.channel == "voice" else 0
        end = start + timedelta(seconds=voice or self.rng.uniform(20, 90))
        steps: list[dict] = []
        step = lambda **kw: steps.append({"step_no": len(steps) + 1, "tool_input": None, "tool_output": None,
                                          "snapshot_time": None, **kw})

        lookup_ok = self.rng.random() < b.lookup_success
        linked = self.ref_index.get(q.stated_reference) if lookup_ok else None
        if linked is not None and self.rng.random() < b.wrong_shipment_prob:
            others = [s for s in self.by_customer[q.customer_id] if s is not linked]
            linked = self.rng.choice(others) if others else linked
        step(tool_name="lookup_shipment", tool_input=q.stated_reference,
             tool_output=linked.booking_ref if linked else "not_found", success=lookup_ok)

        answer: Answer | None = None
        escalated = False
        handoff = (not t.in_scope) or linked is None or self.rng.random() < b.handoff_prob
        if not handoff:
            snap = end
            if self.rng.random() < b.stale_cache_prob:
                snap = end - hours(self.rng.uniform(6, 48))
                t.stale_snapshot_used = True
            k = self.known(linked, snap)
            status, eta = k.status, k.eta
            if eta is not None and self.rng.random() < b.unsupported_claim_prob:
                eta = eta + hours(self.rng.choice([-1, 1]) * self.rng.uniform(12, 48))
            step(tool_name="get_tracking_status", tool_input=linked.booking_ref,
                 tool_output=f"status={k.status}; eta={_iso(k.eta)}", snapshot_time=snap, success=True)
            answer = Answer(end, "ai_agent", version, linked, status, eta,
                            self.is_correct(true, linked, status, eta, end))
            step(tool_name="send_message", tool_input=None, tool_output="sent", success=True)
            if self.needs_escalation(linked, status, eta) and self.rng.random() < b.escalation_compliance:
                step(tool_name="create_case", tool_input=linked.booking_ref, tool_output="created", success=True)
                step(tool_name="escalate_case", tool_input=linked.booking_ref, tool_output="escalated", success=True)
                escalated = True
        else:
            step(tool_name="handoff_to_human", tool_input=None, tool_output="queued", success=True)

        tokens_in, tokens_out = round(self.skew(b.tokens_in)), round(self.skew(b.tokens_out))
        t.ai_cost += (tokens_in * self.prices.llm_tokens_in + tokens_out * self.prices.llm_tokens_out
                      + voice / 60 * self.prices.voice_minutes + self.prices.runs)
        run = {"_enq": q, "agent_version": version, "started_at": start, "ended_at": end, "steps": steps,
               "claimed_status": answer.claimed_status if answer else None,
               "claimed_eta": answer.claimed_eta if answer else None,
               "response_text": _message(answer) if answer else "Let me transfer you to a colleague.",
               "self_reported_outcome": None, "handoff_flag": handoff,
               "tokens_in": tokens_in, "tokens_out": tokens_out, "voice_seconds": voice or None}
        self.out.agent_runs.append(run)

        if handoff:
            t.handed_off = True
            run["self_reported_outcome"] = "handed_off"
            self.human_answer(t, end + timedelta(minutes=self.skew(self.cfg.human.queue_minutes)), True)
            return

        self.respond(t, answer)
        if escalated:
            self.open_escalation(t, linked, end + timedelta(seconds=30), "ai_agent")
        self.maybe_rescue(t, true, answer, end)
        run["self_reported_outcome"] = self.self_report(t, b, escalated)

    def maybe_rescue(self, t: Truth, true: Shipment, ai: Answer, at: datetime) -> None:
        bad_answer = not ai.correct
        missing_escalation = t.escalation_required and not any(e.shipment is true for e in t.escalations)
        if not (bad_answer or missing_escalation) or self.rng.random() >= self.cfg.rescue.detection_prob:
            return
        t.rescued = True
        r = self.cfg.rescue
        start = at + hours(self.rng.uniform(r.delay_hours.min, r.delay_hours.max))
        owner = self.human()
        case = {"_enq": t.enquiry, "opened_at": start, "reason": "wrong_information", "owner_id": owner,
                "priority": "normal", "closed_at": None, "closure_code": None}
        self.out.cases.append(case)
        self.history(case, start, "status", None, "new", owner)
        sent = self.work(t, "correct_ai_answer", start, self.skew(r.rescue_minutes), case)
        k = self.known(true, sent)
        self.respond(t, Answer(sent, "human", owner, true, k.status, k.eta, True, "correction"), case)
        case.update(closed_at=sent, closure_code="resolved_info_provided")
        self.history(case, sent, "status", "new", "closed", owner)
        if missing_escalation and self.needs_escalation(true, k.status, k.eta):
            self.open_escalation(t, true, sent + timedelta(minutes=1), owner)

    def self_report(self, t: Truth, b: AgentBehaviour, escalated: bool) -> str:
        if escalated:
            return "escalated"
        failed = not t.first_answer.correct or (t.escalation_required and not t.escalations)
        if failed and self.rng.random() >= b.false_success_report_prob:
            return "failed"
        return "resolved"

    # ------------------------------------------------------------ outcome

    def service_outcome(self, t: Truth) -> str:
        if not t.in_scope:
            return "out_of_scope"
        q = t.enquiry
        true = self.w.shipment(q.true_booking_ref)
        final = t.final_answer
        r = self.rules
        ok = [e for e in t.escalations if e.shipment is true
              and e.opened_at - q.received_at <= hours(r.escalation.max_hours_to_escalate)
              and e.first_update_at is not None
              and e.first_update_at - e.opened_at <= hours(r.follow_up.followup_deadline_hours)]
        t.required_actions_done = bool(ok) if t.escalation_required else True
        if final is None or not final.correct or not t.required_actions_done:
            return "failed"
        if t.escalation_required:
            window_end = q.received_at + timedelta(days=r.follow_up.observation_window_days)
            if all(e.closed_at is None or e.closed_at > window_end for e in ok):
                return "escalated_open"
        return "resolved"

    def handle(self, q: Enquiry, in_population: bool) -> Truth:
        q.arm = self.assign_arm(q)
        t = Truth(q, q.arm, q.enquiry_type in self.rules.in_scope_enquiry_types, in_population)
        true = self.w.shipment(q.true_booking_ref)
        if t.in_scope:
            # Escalation is required if the delay the carrier's systems showed at receipt exceeds the threshold.
            k = self.known(true, q.received_at)
            t.escalation_required = self.needs_escalation(true, k.status, k.eta)
        if q.arm == HUMAN_BASELINE:
            self.human_answer(t, q.received_at + timedelta(minutes=self.skew(self.cfg.human.queue_minutes)), False)
        else:
            self.ai_answer(t, q.arm)
        t.service_outcome = self.service_outcome(t)
        self.out.truths.append(t)
        return t

    def maybe_repeat(self, t: Truth) -> Enquiry | None:
        f = self.cfg.follow_up
        p = {"failed": f.repeat_prob_if_failed, "escalated_open": f.repeat_prob_if_open}.get(
            t.service_outcome, f.repeat_prob_if_resolved)
        if t.service_outcome == "out_of_scope" or self.rng.random() >= p:
            return None
        q = t.enquiry
        after = max([q.received_at] + [a.sent_at for a in t.answers]) + hours(2)
        window = q.received_at + timedelta(days=self.rules.follow_up.repeat_contact_window_days)
        at = uniform_time(self.rng, after, window)
        if at >= self.w.data_cutoff or at <= after:
            return None
        s = self.w.shipment(q.true_booking_ref)
        return Enquiry(enquiry_id="", customer_id=q.customer_id,
                       channel=choice_weighted(self.rng, self.cfg.enquiries.channel_mix),
                       received_at=at, stated_reference=s.booking_ref, enquiry_type=q.enquiry_type,
                       language=q.language, true_booking_ref=s.booking_ref, reference_kind="booking",
                       delay_driven=False, repeat_of=q)


def _iso(dt: datetime | None) -> str:
    return dt.isoformat() if dt else "unknown"


def _message(a: Answer | None) -> str:
    if a is None or a.linked is None:
        return ""
    eta = a.claimed_eta.strftime("%d %b %Y %H:%M UTC") if a.claimed_eta else "not yet available"
    return f"Shipment {a.linked.booking_ref} is currently {a.claimed_status or 'booked'}. Estimated arrival: {eta}."


# ---------------------------------------------------------------- truth finalization


def _mark_repeats(truths: list[Truth], window_days: float) -> None:
    by_key: dict[tuple[str, str], list[Truth]] = {}
    for t in truths:
        by_key.setdefault((t.enquiry.customer_id, t.enquiry.true_booking_ref), []).append(t)
    window = timedelta(days=window_days)
    for group in by_key.values():
        group.sort(key=lambda t: t.enquiry.received_at)
        for i, t in enumerate(group):
            t.repeat_contact = any(
                timedelta(0) < o.enquiry.received_at - t.enquiry.received_at <= window for o in group[i + 1 :]
            )


def _scenario(t: Truth) -> str:
    fa = t.first_answer
    if not t.in_scope:
        return "S12"
    if fa is not None and fa.actor_type == "ai_agent" and fa.linked is not None \
            and fa.linked.booking_ref != t.enquiry.true_booking_ref:
        return "S6"
    if t.self_reported == "resolved" and t.true_outcome != "resolved":
        return "S10"
    if t.rescued:
        return "S7"
    if any(e.first_update_at is None for e in t.escalations):
        return "S11"
    if t.escalation_required and not t.escalations:
        return "S3"
    if fa is not None and not fa.correct:
        return "S4"
    if t.repeat_contact:
        return "S8"
    if t.escalation_required:
        return "S2"
    if t.stale_snapshot_used and fa is not None and fa.correct:
        return "S5"
    return "S1"


def handle_all(cfg: GeneratorConfig, rules: ServiceRules, world: World) -> Handled:
    h = Handler(cfg, rules, world)
    originals = list(world.enquiries)
    repeats = []
    for q in originals:
        t = h.handle(q, world.period_start <= q.received_at < world.period_end)
        r = h.maybe_repeat(t)
        if r is not None:
            repeats.append(r)
    for q in repeats:  # repeat contacts are handled but do not spawn further repeats
        h.handle(q, world.period_start <= q.received_at < world.period_end)

    # Renumber every enquiry in time order, as a real system would.
    world.enquiries = sorted(originals + repeats, key=lambda q: (q.received_at, q.true_booking_ref))
    for n, q in enumerate(world.enquiries, start=1):
        q.enquiry_id = ids.enquiry_id(n)
    h.out.truths.sort(key=lambda t: t.enquiry.received_at)

    _mark_repeats(h.out.truths, rules.follow_up.repeat_contact_window_days)
    runs = {id(r["_enq"]): r for r in h.out.agent_runs}
    for t in h.out.truths:
        o = t.service_outcome
        if t.repeat_contact and o in ("resolved", "escalated_open"):
            o = "failed"
        t.true_outcome = o
        run = runs.get(id(t.enquiry))
        t.self_reported = run["self_reported_outcome"] if run else None
        t.scenario_id = _scenario(t)
    return h.out
