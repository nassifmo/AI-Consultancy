"""Layer 9: inject realistic defects into the rendered exports and record every one.

Runs after the clean exports are validated and after ground truth is computed, so the truth
never sees the damage. Each defect is logged in `ground_truth/injected_defects.csv`. Where a
defect removes evidence a correct evaluator needs, the enquiry's `expected_evaluator_state`
becomes "unknown"; recoverable defects (duplicates, retries, out-of-order rows, offsets that
can be restored from export metadata, IDs recoverable through another link) leave it unchanged.

| Defect | Files | Recoverable? | Effect on expected state |
|---|---|---|---|
| duplicate_row | enquiries, responses, agent_work, tracking_events | yes (dedupe) | none |
| retry_row | agent_runs | yes (technical retry, not a handling) | none |
| late_record | enquiries, responses, agent_work | yes (sort by time) | none |
| timezone_shift | local-time files | yes (offset from export_metadata.json) | none |
| orphan_record | agent_work | yes (ignore unknown enquiry) | none |
| id_typo | cases.enquiry_id, agent_work.enquiry_id | cases via responses.case_id; work rows only partly | none (human time may be undercounted) |
| missing_field | responses claimed ETA/status | no | unknown if it hits the final answer |
| missing_field | agent_work.active_seconds | no | none (human time unknown for that row) |
| missing_field | cases.closed_at | yes (case history) | none |
| missing_snapshot | tracking_events (whole shipment) | no | unknown for in-scope enquiries on it |
| conflicting_closure | case_history vs cases | no | unknown if that case decides the outcome |
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from datagen.config_schema import GeneratorConfig

from . import ids
from .handling import Handled
from .sampling import layer_rng

UNKNOWN = "unknown"


class Injector:
    def __init__(self, cfg: GeneratorConfig, tables: dict, handled: Handled):
        self.cfg, self.t, self.h = cfg, tables, handled
        self.rates = cfg.defects.rates
        self.rng = layer_rng(cfg.seed, "defects")
        self.log: list[dict] = []
        self.unknown: set[str] = set()
        self.in_scope = {r["enquiry_id"] for r in tables["true_outcome"] if r["true_outcome"] != "out_of_scope"}
        # Final answer (answer or correction) per enquiry, from the clean export.
        final: dict[str, dict] = {}
        for r in sorted(tables["responses"], key=lambda r: r["sent_at"]):
            if r["purpose"] in ("answer", "correction"):
                final[r["enquiry_id"]] = r
        self.final_response = {eid: r["response_id"] for eid, r in final.items()}
        # Cases that decide the outcome (required escalation that met the rules) -> enquiry.
        self.deciding_case: dict[str, str] = {}
        for t in handled.truths:
            if t.true_outcome in ("resolved", "escalated_open"):
                for e in t.qualifying_cases:
                    self.deciding_case[e.row["_id"]] = t.enquiry.enquiry_id

    def hit(self, kind: str) -> bool:
        return self.rng.random() < self.rates.get(kind, 0.0)

    def record(self, kind, file, record_id, field=None, detail=None, affected=()):
        affected = sorted(set(affected) & self.in_scope)
        self.unknown.update(affected)
        self.log.append({"defect_type": kind, "file": file, "record_id": record_id, "field": field,
                         "detail": detail, "affected_enquiries": ";".join(affected) or None})

    # ------------------------------------------------------------ evidence-removing defects

    def missing_snapshot(self):
        enquiries_by_ship = defaultdict(list)
        for r in self.t["true_outcome"]:
            enquiries_by_ship[r["true_booking_ref"]].append(r["enquiry_id"])
        targets = [b for b in sorted(enquiries_by_ship) if self.hit("missing_snapshot")]
        drop = set(targets)
        self.t["tracking_events"] = [e for e in self.t["tracking_events"] if e["booking_ref"] not in drop]
        for b in targets:
            self.record("missing_snapshot", "tracking_events.json", b,
                        detail="whole tracking history missing from export", affected=enquiries_by_ship[b])
        return drop

    def conflicting_closure(self):
        history = self.t["case_history"]
        for c in self.t["cases"]:
            if not c["closed_at"] or c["reason"] != "delay_investigation" or not self.hit("conflicting_closure"):
                continue
            closed = datetime.fromisoformat(c["closed_at"])
            history.append({"history_id": c["case_id"] + "-H", "case_id": c["case_id"],
                            "changed_at": (closed + timedelta(hours=1)).isoformat(), "field": "status",
                            "old_value": "closed", "new_value": "open", "changed_by": "system"})
            eid = self.deciding_case.get(c["case_id"])
            self.record("conflicting_closure", "case_history.csv", c["case_id"], "status",
                        "cases says closed; history shows reopened after closure", [eid] if eid else [])

    def missing_field(self):
        for r in self.t["responses"]:
            if r["purpose"] in ("answer", "correction") and r["claimed_eta"] and self.hit("missing_field"):
                fld = self.rng.choice(["claimed_eta", "claimed_status"])
                r[fld] = None
                is_final = self.final_response.get(r["enquiry_id"]) == r["response_id"]
                self.record("missing_field", "responses.csv", r["response_id"], fld, "blanked",
                            [r["enquiry_id"]] if is_final else [])
        for r in self.t["agent_work"]:
            if self.hit("missing_field"):
                r["active_seconds"] = None
                self.record("missing_field", "agent_work.csv", r["work_id"], "active_seconds", "blanked")
        for c in self.t["cases"]:
            if c["closed_at"] and self.hit("missing_field"):
                c["closed_at"] = None
                self.record("missing_field", "cases.csv", c["case_id"], "closed_at",
                            "blanked; closure still visible in case_history")

    # ------------------------------------------------------------ recoverable defects

    def id_typo(self):
        known = {q["enquiry_id"] for q in self.t["enquiries"]}
        for key, file in (("cases", "cases.csv"), ("agent_work", "agent_work.csv")):
            pk = "case_id" if key == "cases" else "work_id"
            for r in self.t[key]:
                if self.hit("id_typo"):
                    old, new = r["enquiry_id"], r["enquiry_id"]
                    while new in known:
                        new = ids.typo(old, self.rng)
                    r["enquiry_id"] = new
                    self.record("id_typo", file, r[pk], "enquiry_id", f"{old} -> {new}")

    def timezone_shift(self, local_files: list[str], dt_fields: dict[str, list[str]]):
        for key in local_files:
            pk = {"cases": "case_id", "case_history": "history_id", "agent_work": "work_id"}.get(key)
            for r in self.t.get(key, []):
                if self.hit("timezone_shift"):
                    for f in dt_fields[key]:
                        if r.get(f):
                            r[f] = datetime.fromisoformat(r[f]).replace(tzinfo=None).isoformat()
                    self.record("timezone_shift", f"{key}.csv", r[pk], None,
                                "UTC offset dropped; local time per export_metadata.json")

    def orphan_record(self):
        known = {q["enquiry_id"] for q in self.t["enquiries"]}
        extra = []
        for r in self.t["agent_work"]:
            if self.hit("orphan_record"):
                ghost = ids.enquiry_id(900000 + self.rng.randint(0, 99999))
                while ghost in known:
                    ghost = ids.enquiry_id(900000 + self.rng.randint(0, 99999))
                new = {**r, "work_id": r["work_id"] + "-O", "enquiry_id": ghost, "case_id": None}
                extra.append(new)
                self.record("orphan_record", "agent_work.csv", new["work_id"], "enquiry_id",
                            f"work row for enquiry {ghost} not in export")
        self.t["agent_work"].extend(extra)

    def retry_row(self):
        extra = []
        for r in self.t["agent_runs"]:
            if self.hit("retry_row"):
                start = datetime.fromisoformat(r["started_at"])
                retry = {**r, "run_id": r["run_id"] + "-R",
                         "started_at": (start - timedelta(seconds=round(self.rng.uniform(5, 30)))).isoformat(),
                         "ended_at": (start - timedelta(seconds=2)).isoformat(),
                         "steps": [{"step_no": 1, "tool_name": "lookup_shipment",
                                    "tool_input": r["steps"][0]["tool_input"], "tool_output": "timeout",
                                    "snapshot_time": None, "success": False}],
                         "claimed_status": None, "claimed_eta": None, "response_text": "",
                         "self_reported_outcome": "failed", "handoff_flag": False,
                         "tokens_in": None, "tokens_out": None, "voice_seconds": None}
                extra.append(retry)
                self.record("retry_row", "agent_runs.json", retry["run_id"], None,
                            f"technical retry before {r['run_id']}; not a separate handling")
        self.t["agent_runs"].extend(extra)
        self.t["agent_runs"].sort(key=lambda r: r["started_at"])

    def duplicate_row(self):
        pks = {"enquiries": "enquiry_id", "responses": "response_id", "agent_work": "work_id",
               "tracking_events": "event_id"}
        for key, pk in pks.items():
            rows = self.t[key]
            dups = [dict(r) for r in rows if self.hit("duplicate_row")]
            for d in dups:
                self.record("duplicate_row", _file(key), d[pk], None, "exact duplicate row")
            rows.extend(dups)

    def late_record(self):
        pks = {"enquiries": "enquiry_id", "responses": "response_id", "agent_work": "work_id"}
        for key, pk in pks.items():
            rows = self.t[key]
            late = [r for r in rows if self.hit("late_record")]
            ids_late = {id(r) for r in late}
            self.t[key] = [r for r in rows if id(r) not in ids_late] + late
            for r in late:
                self.record("late_record", _file(key), r[pk], None, "row moved out of time order (later batch)")


def _file(key: str) -> str:
    return {"tracking_events": "tracking_events.json", "agent_runs": "agent_runs.json"}.get(key, f"{key}.csv")


def inject(cfg: GeneratorConfig, tables: dict, handled: Handled, dt_fields: dict[str, list[str]]) -> list[dict]:
    """Mutate `tables` in place. Returns the defect log and updates true_outcome expectations."""
    if not cfg.defects.enabled:
        return []
    inj = Injector(cfg, tables, handled)
    snapshot_ships = inj.missing_snapshot()
    inj.conflicting_closure()
    inj.missing_field()
    inj.id_typo()
    inj.timezone_shift(cfg.rendering.local_time_files, dt_fields)
    inj.orphan_record()
    inj.retry_row()
    inj.duplicate_row()
    inj.late_record()

    for r in tables["true_outcome"]:
        if r["enquiry_id"] in inj.unknown:
            r["expected_evaluator_state"] = UNKNOWN
            if r["true_booking_ref"] in snapshot_ships:
                r["scenario_id"] = "S9"
    for n, d in enumerate(inj.log, start=1):
        d["defect_id"] = f"DEF-{n:05d}"
    return [{k: d[k] for k in ("defect_id", "file", "record_id", "defect_type", "field", "detail",
                                "affected_enquiries")} for d in inj.log]
