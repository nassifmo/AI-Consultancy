"""Cost evidence for shipment enquiries, using the same observation window as the analysis."""

from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .exports import MEASURED_WORK_METHODS


AI_ARMS = {"agent_v1", "agent_v2"}
USAGE_ITEMS = ("voice_minutes", "llm_tokens_in", "llm_tokens_out", "runs")
INVOICE_ITEMS = (*USAGE_ITEMS, "platform_fee")
COST_PARAMETERS = "cost_parameters.json"
ZERO = Decimal(0)
CENT = Decimal("0.01")
DECIMAL_DIVISION_RESIDUE = Decimal("0.000000000001")


def _decimal(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    # Finite, bounded amounts can be safely sent back as JSON numbers.
    return number if number.is_finite() and ZERO <= number <= Decimal("1e18") else None


def _day(value):
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _period(value):
    if isinstance(value, str) and re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2])", value) and _day(value + "-01"):
        return value
    return None


def _currency(value):
    return value if isinstance(value, str) and re.fullmatch("[A-Z]{3}", value) else None


def _number(value):
    return float(value) if value is not None else None


def _ref(filename, key):
    return f"{filename}#{key}"


def _rate(params, key):
    return _decimal(params.get(key))


def overlapping_work_ids(data):
    """Map each overlapping work ID to its first overlapping instant."""
    by_actor = defaultdict(list)
    enquiries = {row["enquiry_id"] for row in data.tables.get("enquiries", ())}
    cases = {
        row["case_id"] for row in data.tables.get("cases", ()) if row.get("enquiry_id") in enquiries
    }
    for row in data.tables.get("agent_work", ()):
        if row.get("enquiry_id") not in enquiries and row.get("case_id") not in cases:
            continue  # An orphan cannot invalidate known colleagues' work.
        start = data.time("agent_work", row.get("accepted_at"))
        end = data.time("agent_work", row.get("closed_at"))
        actor, identifier = row.get("agent_id"), row.get("work_id")
        if actor and identifier and start is not None and end is not None and start < end:
            if data.cutoff is None or start <= data.cutoff:
                by_actor[actor].append((start, end, identifier))
    overlapping = {}
    for intervals in by_actor.values():
        furthest = None
        for start, end, identifier in sorted(intervals):
            if furthest is not None and start < furthest[0]:
                overlapping.setdefault(identifier, start)
                overlapping.setdefault(furthest[1], start)
            if furthest is None or end > furthest[0]:
                furthest = (end, identifier)
    return overlapping


def _meter(run):
    voice = _decimal(run.get("voice_seconds"))
    return {
        "voice_minutes": voice / 60 if voice is not None else None,
        "llm_tokens_in": _decimal(run.get("tokens_in")),
        "llm_tokens_out": _decimal(run.get("tokens_out")),
        "runs": Decimal(1),
    }


def _invoice_lines(data, issues):
    """Read a single rate and amount per monthly billing category and currency."""
    lines = defaultdict(list)
    blocked = set()
    for row in data.tables.get("ai_invoice", ()):
        period, item, currency = _period(row.get("period")), row.get("line_item"), _currency(row.get("currency"))
        if period is None or item not in INVOICE_ITEMS or currency is None:
            issues.append({"code": "unsupported_invoice_row", "period": row.get("period"),
                           "line_item": item, "currency": row.get("currency"),
                           "amount": _number(_decimal(row.get("amount")))})
            if period is not None and item in INVOICE_ITEMS:
                blocked.add((period, item))
            continue
        key = (period, item, currency)
        values = tuple(_decimal(row.get(field)) for field in ("quantity", "unit_price", "amount"))
        if values not in lines[key]:
            lines[key].append(values)

    for row in data.conflicts.get("ai_invoice", ()):
        blocked.add((row.get("period"), row.get("line_item")))
        issues.append({"code": "conflicting_invoice_row", "period": row.get("period"),
                       "line_item": row.get("line_item"), "currency": row.get("currency"),
                       "amount": _number(_decimal(row.get("amount")))})

    parsed = {}
    for (period, item, currency), values in sorted(lines.items()):
        key = (period, item)
        source = _ref("ai_invoice.csv", f"{period}/{item}/{currency}")
        if len(values) != 1 or None in values[0] or key in blocked or key in parsed:
            blocked.add(key)
            issues.append({"code": "conflicting_or_invalid_invoice", "source": source})
            continue
        quantity, rate, amount = values[0]
        if abs(quantity * rate - amount) > CENT:
            blocked.add(key)
            issues.append({"code": "invoice_amount_does_not_match_units", "source": source})
            continue
        parsed[key] = {"quantity": quantity, "rate": rate, "amount": amount, "source": source, "currency": currency}
    return {key: line for key, line in parsed.items() if key not in blocked}, blocked


class _CostLedger:
    def __init__(self, data, episodes):
        self.data = data
        self.episodes = {episode["root_enquiry_id"]: episode for episode in episodes}
        self.issues = []
        self.entries = []
        self.reconciliation = []
        self.params = getattr(data, "cost_parameters", None) or {}
        self.labor_currency = _currency(self.params.get("currency"))
        self.labor_rate = _rate(self.params, "labor_rate_per_hour")
        self.valid_from = _day(self.params.get("valid_from"))
        self.rates, self.blocked_invoice_keys = _invoice_lines(data, self.issues)
        self.unrecognized_bill_periods = {
            _period(issue.get("period")) for issue in self.issues
            if issue["code"] == "unsupported_invoice_row"
        }
        currencies = {
            _currency(row.get("currency"))
            for rows in (data.tables.get("ai_invoice", ()), data.conflicts.get("ai_invoice", ()))
            for row in rows
        } - {None}
        if self.labor_currency:
            currencies.add(self.labor_currency)
        self.currency = next(iter(currencies)) if len(currencies) == 1 else None
        if len(currencies) > 1:
            self.issues.append({"code": "mixed_currencies", "currencies": sorted(currencies)})
        self.known = defaultdict(lambda: ZERO)
        self.known_categories = defaultdict(lambda: defaultdict(lambda: ZERO))
        self.reasons = defaultdict(set)
        self.estimated = set()
        self.contacts = {}
        self.work_roots = {}
        for root, episode in self.episodes.items():
            for contact in episode.get("all_contacts", episode["contacts"]):
                if contact in self.contacts and self.contacts[contact] != root:
                    self.reasons[root].add("ambiguous_cost_link")
                    other = self.contacts[contact]
                    if other is not None:
                        self.reasons[other].add("ambiguous_cost_link")
                    self.contacts[contact] = None
                else:
                    self.contacts[contact] = root
            for ref in episode.get("work_refs") or ():
                if ref in self.work_roots and self.work_roots[ref] != root:
                    self.reasons[root].add("ambiguous_human_cost_link")
                    other = self.work_roots[ref]
                    if other is not None:
                        self.reasons[other].add("ambiguous_human_cost_link")
                    self.work_roots[ref] = None
                else:
                    self.work_roots[ref] = root

        timezone = data.metadata.get("billing_timezone", "UTC")
        try:
            self.zone = ZoneInfo(timezone)
        except (TypeError, ValueError, ZoneInfoNotFoundError):
            self.zone = None
            self.issues.append({"code": "invalid_billing_timezone", "value": timezone})
        self.checkpoints = {
            root: data.time("enquiries", episode.get("checkpoint")) for root, episode in self.episodes.items()
        }
        self.received = {
            root: data.time("enquiries", episode.get("received_at")) for root, episode in self.episodes.items()
        }
        self.contact_received = {
            row["enquiry_id"]: data.time("enquiries", row.get("received_at"))
            for row in data.tables.get("enquiries", ())
        }

    def local_date(self, when):
        return when.astimezone(self.zone).date() if when is not None and self.zone is not None else None

    def month(self, when):
        day = self.local_date(when)
        return day.isoformat()[:7] if day is not None else None

    def entry(self, category, period, amount, currency, refs, root, scope, allocation_rule, *, estimated=False):
        self.entries.append({
            "category": category, "period": period, "amount": _number(amount), "currency": currency,
            "root_enquiry_id": root, "scope": scope, "allocation_rule": allocation_rule,
            "refs": refs, "estimated": estimated,
        })
        if root is not None and scope in {"included", "excluded"} and self.currency is not None and currency == self.currency:
            self.known[root] += amount
            self.known_categories[root][category] += amount
            if estimated:
                self.estimated.add(root)

    def scope(self, root):
        if root is None:
            return "unallocated"
        return "included" if self.episodes[root]["eligible"] else "excluded"

    def reconcile(self, category, period, amount, currency, source, known, *, estimated=False, **details):
        included = known.get("included", ZERO)
        excluded = known.get("excluded", ZERO) + known.get("outside_checkpoint", ZERO)
        unallocated = amount - included - excluded
        if abs(unallocated) < DECIMAL_DIVISION_RESIDUE:
            unallocated = ZERO
        self.reconciliation.append({
            "category": category, "period": period, "currency": currency, "source": source,
            "amount": _number(amount), "included": _number(included), "excluded": _number(excluded),
            "unallocated": _number(unallocated), "estimated": estimated, **details,
        })
        return unallocated

    def labor(self):
        by_id = {_ref("agent_work.csv", row["work_id"]): row for row in self.data.tables.get("agent_work", ())}
        for root, episode in self.episodes.items():
            scope = self.scope(root)
            active = _decimal(episode.get("active_seconds"))
            measured = ZERO
            if active is None:
                self.reasons[root].add("incomplete_human_effort")
            for ref in dict.fromkeys(episode.get("work_refs") or ()):
                row = by_id.get(ref)
                if row is None or self.work_roots[ref] != root or self.contacts.get(row.get("enquiry_id")) not in {root, None}:
                    self.reasons[root].add("unverified_human_cost_link")
                    continue
                start = self.data.time("agent_work", row.get("accepted_at"))
                end = self.data.time("agent_work", row.get("closed_at"))
                day = self.local_date(start)
                duration = _decimal(row.get("active_seconds"))
                method = row.get("measurement_method")
                if (
                    duration is None or day is None or end is None or self.checkpoints[root] is None
                    or end > self.checkpoints[root] or duration > Decimal(str((end - start).total_seconds()))
                    or method not in MEASURED_WORK_METHODS or not row.get("agent_id")
                ):
                    self.reasons[root].add("incomplete_human_effort")
                    continue
                measured += duration
                if self.valid_from is None or day < self.valid_from or self.labor_rate is None or self.labor_currency is None:
                    if duration:
                        self.reasons[root].add("missing_labor_rate")
                    continue
                self.entry("human_work", day.isoformat()[:7], duration * self.labor_rate / 3600, self.labor_currency,
                           [ref, _ref(COST_PARAMETERS, "labor_rate_per_hour")], root, scope,
                           method + "_active_seconds")
            if active is not None and measured != active:
                self.reasons[root].add("human_effort_without_matching_records")

    def usage(self):
        meters = defaultdict(list)
        crossing = set()
        run_contacts = set()
        analysis_periods = set()
        for run in sorted(self.data.tables.get("agent_runs", ()), key=lambda row: row["run_id"]):
            contact = run.get("enquiry_id")
            root = self.contacts.get(contact)
            started = self.data.time("agent_runs", run.get("started_at"))
            ended = self.data.time("agent_runs", run.get("ended_at"))
            period = self.month(started)
            cp = self.checkpoints.get(root)
            begin = self.contact_received.get(contact) or self.received.get(root)
            scope = self.scope(root)
            if period is None or ended is None or ended < started:
                self.issues.append({"code": "invalid_billable_run_timing", "run_id": run.get("run_id")})
                if root is not None:
                    self.reasons[root].add("incomplete_ai_metering")
                continue
            if root is not None and (begin is None or started < begin):
                scope = "unallocated"
                self.reasons[root].add("invalid_run_episode_link")
            elif root is not None and (cp is None or ended > cp):
                scope = "outside_checkpoint"
                if cp is not None and started <= cp:
                    crossing.add(root)
            elif root is not None:
                run_contacts.add(root)
                analysis_periods.add((period, root))
            source = _ref("agent_runs.json", run["run_id"])
            for item, quantity in _meter(run).items():
                meters[period, item].append((root, scope, source, quantity))

        for key in sorted(set(meters) | {key for key in self.rates if key[1] in USAGE_ITEMS}):
            period, item = key
            records = meters[key]
            line = self.rates.get(key)
            groups = defaultdict(lambda: ZERO)
            known_quantity = sum((quantity for _, _, _, quantity in records if quantity is not None), ZERO)
            missing_units = sum(quantity is None for _, _, _, quantity in records)
            quantity_tolerance = CENT if item == "voice_minutes" else ZERO
            mismatch = line is not None and bool(
                missing_units or abs(known_quantity - line["quantity"]) > quantity_tolerance
                or abs(known_quantity * line["rate"] - line["amount"]) > CENT
                or known_quantity == ZERO and line["amount"] != ZERO
            )
            remaining = line["amount"] if line is not None else ZERO
            remaining_quantity = known_quantity
            for root, scope, source, quantity in records:
                attributable = root is not None and scope in {"included", "excluded"}
                if quantity is None or (line is None and quantity != ZERO):
                    if attributable:
                        self.reasons[root].add("missing_ai_meter_or_rate")
                    continue
                if line is None:
                    continue
                amount = quantity * line["rate"]
                if not mismatch and quantity != ZERO:
                    amount = remaining if quantity == remaining_quantity else line["amount"] * quantity / known_quantity
                    remaining -= amount
                    remaining_quantity -= quantity
                groups[scope] += amount
                basis = "unreconciled_meter_estimate" if mismatch else "metered_units_with_invoice_rounding"
                self.entry(item, period, amount, line["currency"], [source, line["source"]],
                           root, scope, basis, estimated=mismatch)
                if mismatch and attributable:
                    self.reasons[root].add("ai_usage_invoice_mismatch")
            if line is not None:
                self.reconcile(item, period, line["amount"], line["currency"], line["source"], {} if mismatch else groups,
                               billed_quantity=_number(line["quantity"]), matched_meter_quantity=_number(known_quantity),
                               known_unlinked_meter_cost=_number(groups["unallocated"]),
                               modelled_meter_cost=_number(sum(groups.values(), ZERO)),
                               missing_meter_count=missing_units, matched=not mismatch)

        bad_run_roots = {
            self.contacts.get(row.get("enquiry_id")) for row in self.data.conflicts.get("agent_runs", ())
        }
        for root, episode in self.episodes.items():
            if root in crossing or root in bad_run_roots or "agent_runs" in self.data.unscoped:
                self.reasons[root].add("incomplete_ai_metering")
            if root not in run_contacts:
                if episode["assigned_arm"] in AI_ARMS:
                    self.reasons[root].add("ai_assignment_without_verified_run")
                elif self.data.metadata.get("agent_run_usage_complete") is not True:
                    self.reasons[root].add("zero_ai_usage_unverified")
        return analysis_periods

    def fixed_costs(self, analysis_periods):
        ai_roots = defaultdict(list)
        for root, episode in self.episodes.items():
            period = self.month(self.received[root])
            if episode["assigned_arm"] in AI_ARMS and period is not None:
                ai_roots[period].append(root)
        for period, root in set(analysis_periods) | {(period, root) for period, roots in ai_roots.items() for root in roots}:
            if period in self.unrecognized_bill_periods or None in self.unrecognized_bill_periods:
                self.reasons[root].add("unsupported_invoice_charge")
        # Include months with charges or attributable follow-up even if no newly assigned root exists.
        billed = {period for period, item in self.rates if item == "platform_fee"}
        blocked = {period for period, item in self.blocked_invoice_keys if item == "platform_fee" and _period(period)}
        months = sorted(set(ai_roots) | billed | blocked | {period for period, _ in analysis_periods})
        for period in months:
            roots = sorted(ai_roots[period])
            platform = self.rates.get((period, "platform_fee"))
            maintenance, setup = self.fixed_parameters(period)
            items = [
                ("platform_fee", platform["amount"] if platform else _rate(self.params, "platform_fee_month"),
                 platform["currency"] if platform else self.labor_currency,
                 platform["source"] if platform else _ref(COST_PARAMETERS, "platform_fee_month"), not platform),
                ("maintenance", maintenance, self.labor_currency, _ref(COST_PARAMETERS, "maintenance_month"), True),
                ("amortized_setup", setup, self.labor_currency, _ref(COST_PARAMETERS, "setup_cost"), True),
            ]
            for category, amount, currency, source, estimated in items:
                if category == "platform_fee" and period in blocked:
                    # An absent invoice can use the disclosed estimate. Contradictions need review.
                    amount = None
                if estimated and (
                    self.valid_from is None or self.valid_from.isoformat()[:7] > period
                ):
                    amount = None
                if amount is None or currency is None:
                    for root in roots:
                        self.reasons[root].add("missing_" + category)
                    if roots or category == "platform_fee" and period in blocked:
                        self.issues.append({"code": "unresolved_fixed_cost", "period": period, "category": category})
                    continue
                self.allocate_fixed(period, category, amount, currency, source, estimated, roots)

    def fixed_parameters(self, period):
        months = _rate(self.params, "amortization_months")
        setup = _rate(self.params, "setup_cost")
        maintenance = _rate(self.params, "maintenance_month")
        if months is None or not months or months != months.to_integral_value() or setup is None or self.valid_from is None:
            return maintenance, None
        first = _day(period + "-01")
        months_since_setup = 12 * (first.year - self.valid_from.year) + first.month - self.valid_from.month
        return maintenance, setup / months if 0 <= months_since_setup < months else ZERO

    def allocate_fixed(self, period, category, amount, currency, source, estimated, roots):
        by_scope = defaultdict(lambda: ZERO)
        if roots:
            share = amount / len(roots)
            assigned = ZERO
            for index, root in enumerate(roots):
                value = amount - assigned if index == len(roots) - 1 else share
                scope = self.scope(root)
                by_scope[scope] += value
                assigned += value
                self.entry(category, period, value, currency, [source], root, scope,
                           "ai_root_request_count", estimated=estimated)
        elif amount:
            self.entry(category, period, amount, currency, [source], None, "unallocated",
                       "no_ai_root_volume_for_billing_month", estimated=estimated)
        self.reconcile(category, period, amount, currency, source, by_scope, estimated=estimated,
                       allocation_population=len(roots))

    def result(self):
        self.labor()
        self.fixed_costs(self.usage())
        if "source_completeness" in self.data.metadata:
            actual_ai_roots = {
                self.contacts.get(run.get("enquiry_id")) for run in self.data.tables.get("agent_runs", ())
            }
            for root, episode in self.episodes.items():
                needed = {"enquiries", "agent_work", "agent_runs"}
                if episode["assigned_arm"] in {"agent_v1", "agent_v2"} or root in actual_ai_roots:
                    needed.add("ai_invoice")
                for table in needed:
                    if not self.data.is_complete(table):
                        self.reasons[root].add("incomplete_source_" + table)
        per_episode = {}
        for root in self.episodes:
            if self.episodes[root]["assigned_arm"] is None:
                self.reasons[root].add("assignment_unverified")
            if self.currency is None:
                self.reasons[root].add("consolidated_currency_unavailable")
            reasons = sorted(self.reasons[root])
            per_episode[root] = {
                "total_cost": _number(self.known[root]) if not reasons else None,
                "known_cost": _number(self.known[root]) if self.currency and (root in self.known_categories or not reasons) else None,
                "complete": not reasons,
                "estimated": root in self.estimated,
                "unknown_reasons": reasons,
                "by_category": {category: _number(amount) for category, amount in sorted(self.known_categories[root].items())},
            }
        return {
            "currency": self.currency,
            "labor_rate_per_hour": _number(self.labor_rate) if self.currency == self.labor_currency and self.currency else None,
            "entries": self.entries,
            "per_episode": per_episode,
            "reconciliation": self.reconciliation,
            "issues": self.issues,
            "staffing": self.data.tables.get("staffing", []),
            "realized_cash_savings": None,
            "cash_savings_reason": "Comparable realized spending and the counterfactual spend are unavailable.",
            "full_deployment_scenario": {
                "total_cost": None,
                "reason": "A deployment forecast needs its expected volume, staff capacity and applicable contract rates.",
            },
        }


def build_cost_ledger(data, episodes):
    """Return evidence-based episode costs, monthly reconciliations and financial gaps."""
    return _CostLedger(data, episodes).result()
