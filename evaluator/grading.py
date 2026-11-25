"""Deterministic grading of normalized, source-linked enquiry evidence."""

from datetime import datetime
from math import isfinite

OUTCOME_STATES = {
    "resolved", "escalated_open", "awaiting_customer", "closed_unresolved",
    "failed", "unknown", "out_of_scope",
}
IMPACTS = ("minor", "material", "critical")
SPECIFICATION_FIELDS = {
    "method", "applies_when", "default_applicability", "critical", "steps", "critical_steps",
    "zero_score_early_seconds", "zero_score_late_seconds", "zero_score_on_cutoff_crossing",
}


def _refs(record: dict) -> list[str]:
    values = record.get("refs")
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(ref.strip() for ref in values if isinstance(ref, str) and ref.strip()))


def _instant(value: object) -> datetime | None:
    if isinstance(value, str):
        try:
            timestamp = datetime.fromisoformat(value)
        except ValueError:
            return None
        if timestamp.utcoffset() is not None:
            return timestamp
    return None


def _unknown(reason: str) -> dict:
    return {"status": "unknown", "severity": "unknown", "reason": reason}


def _impact(record: dict) -> str:
    label = record.get("context_impact")
    return label if label in IMPACTS else "unknown"


def _linear_score(distance: float, zero_at: float | None) -> float | None:
    if zero_at is None:
        return None
    return 100 * max(0.0, 1 - distance / zero_at)


def _binary(specification: dict, record: dict) -> dict:
    passed = record.get("passed")
    if not isinstance(passed, bool):
        return _unknown("No verified pass or failure is recorded.")
    severity = "none" if passed else ("critical" if specification.get("critical") else _impact(record))
    return {"status": "met" if passed else "unmet", "severity": severity, "passed": passed}


def _distance(specification: dict, record: dict) -> dict:
    observed, reference = _instant(record.get("observed_at")), _instant(record.get("reference_at"))
    claim = {key: record[key] for key in ("eta_claim_basis", "eta_display_precision_seconds",
                                         "structured_eta_disagrees", "structured_eta_at") if key in record}
    if observed is None or reference is None:
        reason = {
            "sent_eta_needs_review": "The ETA in the sent message needs review before a timestamp can be assigned.",
            "no_eta_in_sent_message": "The sent message does not supply an identifiable ETA.",
        }.get(record.get("eta_claim_basis"), "The quoted and reference times both need known UTC offsets.")
        if observed is not None:
            reason = "The matching reference timestamp at reply time is unverified."
        return {**_unknown(reason), **claim}
    deviation = (observed - reference).total_seconds()
    cutoff = _instant(record.get("decision_cutoff_at"))
    crosses_cutoff = None if cutoff is None else ((observed <= cutoff) != (reference <= cutoff))
    severity = "none" if deviation == 0 else _impact(record)
    if crosses_cutoff and severity != "critical":
        severity = "material"
    limit = specification.get("zero_score_early_seconds" if deviation < 0 else "zero_score_late_seconds")
    cutoff_penalty = bool(crosses_cutoff and specification.get("zero_score_on_cutoff_crossing"))
    score = 0.0 if cutoff_penalty else _linear_score(abs(deviation), limit)
    reasons = []
    if record.get("structured_eta_disagrees"):
        reasons.append("The sent ETA differs from the structured claim. The score uses the sent ETA.")
    if crosses_cutoff:
        reasons.append("The quoted and reference times fall on opposite sides of the documented decision cutoff.")
    elif severity == "unknown":
        reasons.append("The timing difference is measured. Its operational impact needs more context.")
    return {
        **claim,
        "status": "met" if deviation == 0 else "unmet" if score == 0 else "measured",
        "severity": severity,
        "observed_at": observed.isoformat(),
        "reference_at": reference.isoformat(),
        "eta_error_seconds": deviation,
        "crosses_decision_cutoff": crosses_cutoff,
        "score": score,
        "timing_failure_score": None if score is None else 100 - score,
        **({"reason": " ".join(reasons)} if reasons else {}),
    }


def _deadline(specification: dict, record: dict) -> dict:
    completed, due = _instant(record.get("observed_at")), _instant(record.get("reference_at"))
    if completed is None or due is None:
        return _unknown("The completion time and deadline both need known UTC offsets.")
    overdue = max(0.0, (completed - due).total_seconds())
    return {
        "status": "met" if overdue == 0 else "unmet",
        "severity": "none" if overdue == 0 else _impact(record),
        "on_time": overdue == 0,
        "delay_seconds": overdue,
        "score": _linear_score(overdue, specification.get("zero_score_late_seconds")),
    }


def _checklist(specification: dict, record: dict) -> dict:
    observed = record.get("steps")
    observed = observed if isinstance(observed, dict) else {}
    steps = {}
    for step in specification["steps"]:
        value = observed.get(step)
        steps[step] = "met" if value is True else "unmet" if value is False else "unknown"
    met = sum(state == "met" for state in steps.values())
    critical_miss = any(steps[step] == "unmet" for step in specification.get("critical_steps", []))
    if critical_miss:
        status, severity = "unmet", "critical"
    elif "unknown" in steps.values():
        status, severity = "unknown", "unknown"
    elif met == len(steps):
        status, severity = "met", "none"
    else:
        status, severity = ("partial" if met else "unmet"), _impact(record)
    result = {
        "status": status,
        "severity": severity,
        "steps": steps,
        "score": None if "unknown" in steps.values() else 100 * met / len(steps),
    }
    if "unknown" in steps.values():
        result["reason"] = "Evidence is missing for some required steps."
    return result


METHODS = {"binary": _binary, "distance": _distance, "deadline": _deadline, "checklist": _checklist}


def _validate_specification(criterion_id: str, specification: object) -> None:
    method = specification.get("method") if isinstance(specification, dict) else None
    if not isinstance(method, str) or method not in METHODS:
        raise ValueError(f"{criterion_id}: choose a supported grading method.")
    extra = set(specification) - SPECIFICATION_FIELDS
    if extra:
        raise ValueError(f"{criterion_id}: unrecognized policy fields: {', '.join(sorted(extra))}.")
    if "applies_when" in specification:
        condition = specification["applies_when"]
        if not isinstance(condition, str) or not condition.strip():
            raise ValueError(f"{criterion_id}: applies_when must name an applicability condition.")
    if "default_applicability" in specification and (
        "applies_when" not in specification or specification["default_applicability"] is not False
    ):
        raise ValueError(f"{criterion_id}: default_applicability may only exclude an absent condition.")
    if "critical" in specification and (method != "binary" or not isinstance(specification["critical"], bool)):
        raise ValueError(f"{criterion_id}: use critical only as a boolean on a binary check.")
    if method == "checklist":
        steps = specification.get("steps")
        critical = specification.get("critical_steps", [])
        if not _names(steps) or not steps or len(set(steps)) != len(steps):
            raise ValueError(f"{criterion_id}: provide a list of distinct checklist steps.")
        if not _names(critical) or not set(critical).issubset(steps):
            raise ValueError(f"{criterion_id}: critical steps must come from the checklist.")
    elif "steps" in specification or "critical_steps" in specification:
        raise ValueError(f"{criterion_id}: steps belong to checklist checks.")

    for name, eligible in (("zero_score_early_seconds", {"distance"}), ("zero_score_late_seconds", {"distance", "deadline"})):
        if name in specification:
            value = specification[name]
            if method not in eligible or type(value) not in (int, float) or not isfinite(value) or value <= 0:
                raise ValueError(f"{criterion_id}: {name} must be a positive number on a compatible timing check.")
    if method == "distance" and ("zero_score_early_seconds" in specification) != ("zero_score_late_seconds" in specification):
        raise ValueError(f"{criterion_id}: specify both scoring limits for signed distance.")
    if "zero_score_on_cutoff_crossing" in specification and (
        method != "distance" or not isinstance(specification["zero_score_on_cutoff_crossing"], bool)
        or "zero_score_early_seconds" not in specification
    ):
        raise ValueError(f"{criterion_id}: a cutoff override requires a boolean and configured signed-distance limits.")


def _names(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value)


def _grade_criterion(specification: dict, conditions: dict, record: object) -> dict:
    method = specification["method"]
    missing_steps = ({"steps": dict.fromkeys(specification["steps"], "unknown")}
                     if method == "checklist" else {})
    condition = specification.get("applies_when")
    if condition is not None:
        applies = conditions.get(condition, specification.get("default_applicability"))
        if applies is False:
            return {
                "method": method, "status": "not_applicable", "severity": "none",
                "refs": [], "reason": f"The verified condition is false: {condition}.",
            }
        if applies is not True:
            return {"method": method, "refs": [], **missing_steps, **_unknown(f"Applicability is unverified: {condition}.")}
    evidence = record if isinstance(record, dict) else {}
    sources = _refs(evidence)
    if not sources:
        return {"method": method, "refs": [], **missing_steps, **_unknown("No source evidence was supplied.")}
    return {"method": method, "refs": sources, **METHODS[method](specification, evidence)}


def _critical_failure(specification: dict, finding: dict) -> bool | None:
    if finding["status"] == "not_applicable":
        return False
    if specification.get("critical"):
        passed = finding.get("passed")
        return None if passed is None else not passed
    steps = finding.get("steps", {})
    critical_steps = [steps.get(step, "unknown") for step in specification.get("critical_steps", [])]
    if "unmet" in critical_steps:
        return True
    return None if "unknown" in critical_steps else False


def _outcome(record: object) -> dict:
    if isinstance(record, dict):
        state, sources = record.get("state"), _refs(record)
        if isinstance(state, str) and state in OUTCOME_STATES and sources:
            return {"state": state, "refs": sources}
    return {"state": "unknown", "refs": [], "reason": "No source-linked outcome was verified."}


def grade_enquiry(policy: dict, enquiry: dict) -> dict:
    """Select the request's criteria and grade them with the verified evidence supplied."""
    if not isinstance(policy, dict) or not isinstance(enquiry, dict):
        raise ValueError("Policy and enquiry must be JSON objects.")
    version, criteria, profiles = (policy.get(key) for key in ("version", "criteria", "profiles"))
    if not isinstance(version, str) or not version.strip() or not isinstance(criteria, dict) or not isinstance(profiles, dict):
        raise ValueError("The policy needs a version, criteria, and request profiles.")
    profile, enquiry_id = enquiry.get("profile"), enquiry.get("enquiry_id")
    if not isinstance(enquiry_id, str) or not enquiry_id.strip():
        raise ValueError("Supply an enquiry_id.")
    if not isinstance(profile, str) or profile not in profiles:
        raise ValueError(f"No grading profile is defined for {profile!r}.")
    selected = profiles[profile]
    if not _names(selected) or not selected or len(set(selected)) != len(selected):
        raise ValueError(f"{profile}: supply distinct criterion IDs.")
    conditions, evidence = enquiry.get("conditions", {}), enquiry.get("evidence", {})
    if not isinstance(conditions, dict) or not isinstance(evidence, dict):
        raise ValueError("Conditions and evidence must be JSON objects.")
    findings = {}
    critical_findings = []
    for criterion_id in selected:
        specification = criteria.get(criterion_id)
        _validate_specification(criterion_id, specification)
        finding = _grade_criterion(specification, conditions, evidence.get(criterion_id))
        findings[criterion_id] = finding
        critical_findings.append(_critical_failure(specification, finding))
    return {
        "enquiry_id": enquiry_id,
        "profile": profile,
        "policy_version": version,
        "outcome": _outcome(enquiry.get("outcome")),
        "criteria": findings,
        "initial_failure": True if True in critical_findings else None if None in critical_findings else False,
    }
