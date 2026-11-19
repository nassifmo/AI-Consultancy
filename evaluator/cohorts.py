"""Build fixed initial-request cohorts and reconstruct their follow-up."""

from collections import Counter, defaultdict
from datetime import timedelta

from .exports import reference

ARMS = ("human_baseline", "agent_v1", "agent_v2")
METHODS = {"randomized", "before_after", "regional_rollout"}


def _refs(results):
    return list(dict.fromkeys(ref for result in results for ref in result["outcome"]["refs"]))


def _outcome(root, later):
    outcome = root["outcome"]
    details = root.get("verification", {})
    resolved_at = details.get("resolved_at")
    required = details.get("escalation", {}).get("required")
    recovered = details.get("human_recovery")
    # A routine request can be repaired by a verified continuation on the
    # same shipment. A later answer cannot discharge an older open CRM case.
    if later and required is False and not details.get("case_ids"):
        final = later[-1]
        final_details = final.get("verification", {})
        if final["outcome"]["state"] == "resolved" and outcome["state"] in {"failed", "unknown", "awaiting_customer"}:
            outcome = {"state": "resolved", "refs": _refs([root, final])}
            resolved_at = final_details.get("resolved_at")
            if root.get("initial_failure") is True:
                reply = final_details.get("last_reply") or {}
                recovered = reply.get("actor_type") == "human"
    return outcome, resolved_at, recovered


def _members(verifier):
    data = verifier.data
    received = {
        row["enquiry_id"]: data.time("enquiries", row.get("received_at"))
        for row in verifier.enquiries
    }
    continuations, disputed = defaultdict(list), defaultdict(list)
    for row in verifier.enquiries:
        if row.get("contact_relation") != "continuation":
            continue
        key = row["enquiry_id"]
        root_id = row.get("root_enquiry_id")
        parent_id = row.get("related_enquiry_id")
        root = verifier.enquiries_by_id.get(root_id)
        parent = verifier.enquiries_by_id.get(parent_id)
        at, root_at, parent_at = received[key], received.get(root_id), received.get(parent_id)
        if (root and parent and at and root_at and parent_at and root_at <= parent_at < at
                and root.get("contact_relation") in {"initial", "new_request"}
                and root.get("root_enquiry_id") == root_id
                and parent.get("root_enquiry_id") == root_id
                and row.get("customer_id") == parent.get("customer_id") == root.get("customer_id")
                and row.get("assigned_arm") == root.get("assigned_arm")
                and row.get("assignment_unit_id") == root.get("assignment_unit_id")
                and row.get("assignment_method") == root.get("assignment_method")
                and data.time("enquiries", row.get("assignment_at")) == data.time("enquiries", root.get("assignment_at"))):
            continuations[root_id].append(row)
        elif root_id:
            disputed[root_id].append(at)
    for rows in continuations.values():
        rows.sort(key=lambda row: (received[row["enquiry_id"]], row["enquiry_id"]))
    return received, continuations, disputed


def assemble_episodes(verifier, latest, days, overlap_ids):
    data = verifier.data
    received, continuations, disputed = _members(verifier)
    episodes, snapshots = [], {}
    unknown_links = []
    actual_linked = {row["enquiry_id"] for members in continuations.values() for row in members}

    for row in verifier.enquiries:
        enquiry_id = row["enquiry_id"]
        relation = row.get("contact_relation")
        if relation == "continuation":
            if enquiry_id not in actual_linked:
                unknown_links.append(enquiry_id)
            continue
        initial = latest[enquiry_id]
        at = received[enquiry_id]
        intended = at + timedelta(days=days) if at else None
        checkpoint = min(data.cutoff, intended) if data.cutoff and intended else None
        reasons = []
        if not initial["in_scope"]:
            reasons.append("out_of_scope")
        if initial["in_study_period"] is not True:
            reasons.append("outside_study_period" if initial["in_study_period"] is False else "unknown_study_period")
        if at is None or checkpoint is None or checkpoint < intended:
            reasons.append("incomplete_followup")
        if relation not in {"initial", "new_request"} or row.get("root_enquiry_id") != enquiry_id:
            reasons.append("missing_or_invalid_root")
        method = row.get("assignment_method")
        arm = row.get("assigned_arm")
        assigned_at = data.time("enquiries", row.get("assignment_at"))
        unit = row.get("assignment_unit_id")
        if (arm not in ARMS or method not in METHODS or not unit or not assigned_at or not at or assigned_at > at
                or not row.get("customer_id", "").strip()
                or (method == "randomized" and unit != enquiry_id)
                or ("enquiries" in data.unscoped)):
            reasons.append("missing_or_invalid_assignment")
        initial_reply = initial.get("verification", {}).get("initial_reply") or {}
        reply_time = data.time("responses", initial_reply.get("sent_at"))
        if assigned_at and reply_time and assigned_at > reply_time:
            reasons.append("assignment_after_handling")
        contacts = [row]
        reviews = [initial]
        all_continuations = continuations.get(enquiry_id, [])
        if checkpoint and at <= checkpoint and initial["in_scope"]:
            contacts.extend(other for other in all_continuations if received[other["enquiry_id"]] <= checkpoint)
            reviews = [verifier.evaluate_at(contact, checkpoint, overlap_ids) for contact in contacts]
            snapshots.update((contact["enquiry_id"], review) for contact, review in zip(contacts, reviews))
        root, *later = reviews
        # Confirm a shared shipment before using a later contact's service
        # evidence. Allocation and effort remain tied to the recorded episode.
        target = verifier.tracking.for_request(row, checkpoint) if checkpoint else None
        comparable = []
        for contact, assessment in zip(contacts[1:], later):
            candidate = verifier.tracking.for_request(contact, checkpoint)
            if (target and candidate and target.shipment["booking_ref"] == candidate.shipment["booking_ref"]
                    and (not target.container or not candidate.container or target.container == candidate.container)):
                comparable.append(assessment)
        outcome, resolved_at, recovered = _outcome(root, comparable)
        conflicting_link = any(when is None or checkpoint is None or when <= checkpoint
                               for when in disputed.get(enquiry_id, []))
        if conflicting_link:
            outcome = {"state": "unknown", "refs": outcome["refs"], "reason": "Conflicting episode link"}
            resolved_at, recovered = None, None
        details = root.get("verification", {})
        records = [review.get("verification", {}).get("human_work", {}) for review in reviews]
        total = [record.get("active_seconds") for record in records]
        known = [record["recorded_seconds"] for record in records if record.get("recorded_seconds") is not None]
        only_ai = [record.get("ai_only_handling") for record in records]
        resolved = data.time("responses", resolved_at)
        episodes.append({
            "root_enquiry_id": enquiry_id,
            "customer_id": row.get("customer_id") or None,
            "enquiry_type": row.get("enquiry_type"),
            "assigned_arm": arm if arm in ARMS else None,
            "assignment_method": method or None,
            "assignment_unit_id": unit or None,
            "assignment_at": assigned_at.isoformat() if assigned_at else None,
            "received_at": at.isoformat() if at else None,
            "checkpoint": checkpoint.isoformat() if checkpoint else None,
            "contacts": [contact["enquiry_id"] for contact in contacts],
            "all_contacts": [enquiry_id] + [contact["enquiry_id"] for contact in all_continuations],
            "eligible": not reasons,
            "exclusion_reasons": reasons,
            "outcome": outcome,
            "initial_failure": root.get("initial_failure"),
            "human_recovery": recovered,
            "first_answer_correct": (details.get("initial_reply") or {}).get("matches_record"),
            "criteria": root.get("criteria", {}),
            "repeat_contact": details.get("repeat_contact", {}).get("same_unresolved_request") if not conflicting_link else None,
            "active_seconds": sum(total) if not conflicting_link and all(value is not None for value in total) else None,
            "recorded_seconds": sum(known) if known else None,
            "work_refs": list(dict.fromkeys(ref for record in records for ref in record.get("refs", []))),
            "ai_only_handling": False if False in only_ai else True if all(value is True for value in only_ai) else None,
            "resolved_at": resolved_at,
            "elapsed_resolution_seconds": (resolved - at).total_seconds() if resolved and at and resolved >= at else None,
            "assignment_ref": reference("enquiries", row),
        })

    exclusions = Counter(reason for item in episodes for reason in item["exclusion_reasons"])
    return episodes, snapshots, dict(exclusions), sorted(unknown_links)
