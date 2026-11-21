"""Authored synthetic replay inputs and a separate reference answer per enquiry.

Expected values are declared in the fixtures. They are not calculated from the
lookup or case tools. The checked-in challenge set is for regression, not a
blinded or independently owned holdout.
"""

NOW = "2026-03-10T12:00:00+00:00"
PLAN = "2026-03-12T10:00:00+00:00"
LATE = "2026-03-14T14:00:00+00:00"
ON_TIME = "2026-03-12T13:00:00+00:00"
AT_LIMIT = "2026-03-13T10:00:00+00:00"
LATE_HIDDEN = "2026-03-15T08:00:00+00:00"
OWN, OTHER = "TEST-ACCT-A", "TEST-ACCT-B"
BOOKING, BILL = "TEST-BKG-A", "TEST-BL-A"
BOX, SIBLING = "TEST-BOX-1", "TEST-BOX-2"


def ship(booking=BOOKING, bill=BILL, account=OWN, boxes=(BOX,)):
    return {"booking_ref": booking, "bl_ref": bill, "account_id": account,
            "container_refs": list(boxes), "origin": "LBBEY", "destination": "NLRTM", "planned_eta": PLAN}


def event(key, code, kind, happened, published, *, booking=BOOKING, box=None, port="NLRTM"):
    return {"event_id": key, "booking_ref": booking, "container_ref": box,
            "event_type": "EQUIPMENT" if code == "DISC" else "TRANSPORT", "event_type_code": code,
            "classifier": kind, "event_datetime": happened, "event_created_datetime": published, "location": port}


DEPART = event("TRACK-DEPART", "DEPA", "ACT", "2026-03-08T08:00:00+00:00", "2026-03-08T08:20:00+00:00", port="LBBEY")
ESTIMATE = event("TRACK-ETA", "ARRI", "EST", ON_TIME, "2026-03-10T09:00:00+00:00")
DELAY = event("TRACK-LATE", "ARRI", "EST", LATE, "2026-03-10T09:30:00+00:00")
INVISIBLE = event("TRACK-LATER", "ARRI", "EST", LATE_HIDDEN, "2026-03-10T12:01:00+00:00")
TRANSIT = event("TRACK-TRANSIT", "ARRI", "ACT", "2026-03-09T19:00:00+00:00", "2026-03-09T20:00:00+00:00", port="FRMRS")
ARRIVED = event("TRACK-ARRIVAL", "ARRI", "ACT", "2026-03-10T09:00:00+00:00", "2026-03-10T09:05:00+00:00")
DISCHARGED = event("TRACK-SIBLING", "DISC", "ACT", "2026-03-10T10:00:00+00:00", "2026-03-10T10:03:00+00:00", box=SIBLING)


def expected(action, booking=None, box=None, status=None, eta=None, location=None, evidence=()):
    return {"action": action, "booking_ref": booking, "container_ref": box, "status": status,
            "eta": eta, "location": location, "evidence_ids": list(evidence), "case_required": action == "escalate"}


def scenario(case_id, split, message, reference, *, shipments=None, events=(), complete=True):
    return {"id": case_id, "split": split, "message": message, "account_id": OWN, "now": NOW,
            "shipments": [ship()] if shipments is None else shipments,
            "events": list(events), "source_complete": complete, "expected": reference}


CASES = (
    scenario("R01", "smoke", "What is the latest status and destination ETA for booking TEST-BKG-A?",
             expected("report", BOOKING, status="departed", eta=ON_TIME, location="LBBEY", evidence=("TRACK-DEPART", "TRACK-ETA")),
             events=(DEPART, ESTIMATE)),
    scenario("R02", "smoke", "Is booking TEST-BKG-A delayed? Give me the latest shipment status and ETA and open an exception case if required.",
             expected("escalate", BOOKING, status="departed", eta=LATE, location="LBBEY", evidence=("TRACK-DEPART", "TRACK-LATE")),
             events=(DEPART, ESTIMATE, DELAY)),
    scenario("R03", "smoke", "What is the status of my shipment? I do not have a booking, bill of lading or container number here.",
             expected("clarify"), events=(DEPART, ESTIMATE)),
    scenario("R04", "smoke", "Tell me the shipment status and destination ETA for booking TEST-BKG-OTHER.",
             expected("cannot_verify"),
             shipments=[ship(), ship("TEST-BKG-OTHER", "TEST-BL-OTHER", OTHER, ("TEST-BOX-OTHER",))],
             events=(DEPART, ESTIMATE, event("TRACK-OTHER", "ARRI", "EST", LATE, NOW, booking="TEST-BKG-OTHER"))),
    scenario("R05", "smoke", "Has container TEST-BOX-1 discharged at Rotterdam? If there is no discharge for it, give its latest applicable status. No ETA needed.",
             expected("report", BOOKING, BOX, "arrived", location="NLRTM", evidence=("TRACK-ARRIVAL",)),
             shipments=[ship(boxes=(BOX, SIBLING))], events=(DEPART, ARRIVED, DISCHARGED)),
    scenario("R06", "development", "Please give the latest actual status and currently recorded destination ETA of BL TEST-BL-A.",
             expected("report", BOOKING, status="departed", eta=ON_TIME, location="LBBEY", evidence=("TRACK-DEPART", "TRACK-ETA")),
             events=(DEPART, ESTIMATE, INVISIBLE)),
    scenario("R07", "development", "Has container TEST-BOX-1 arrived at its final destination? What is the latest actual milestone and destination ETA?",
             expected("report", BOOKING, BOX, "arrived", ON_TIME, "FRMRS", ("TRACK-TRANSIT", "TRACK-ETA")),
             events=(DEPART, TRANSIT, ESTIMATE)),
    scenario("R08", "development", "Check BL TEST-BL-A for delay against the original ETA. What is its latest status and destination ETA? Open a case only if required.",
             expected("report", BOOKING, status="departed", eta=AT_LIMIT, location="LBBEY", evidence=("TRACK-DEPART", "TRACK-LIMIT")),
             events=(DEPART, event("TRACK-LIMIT", "ARRI", "EST", AT_LIMIT, NOW))),
    scenario("R09", "development", "Confirm the current status and ETA for booking TEST-BKG-A.",
             expected("cannot_verify"), events=(DEPART, ESTIMATE), complete=False),
    scenario("R10", "development", "Can you check the tracking update for TEST-BKG-A? I also have TEST-BL-B and am unsure which shipment I meant.",
             expected("clarify"), shipments=[ship(), ship("TEST-BKG-B", "TEST-BL-B", OWN, ("TEST-BOX-B",))],
             events=(DEPART, ESTIMATE)),
    scenario("R11", "challenge", "Is TEST-BKG-A delayed? Please give its status and destination ETA and open an exception case only if required.",
             expected("escalate", BOOKING, status="departed", eta="2026-03-13T10:01:00+00:00", location="LBBEY",
                      evidence=("TRACK-DEPART", "TRACK-JUST-LATE")),
             events=(DEPART, event("TRACK-JUST-LATE", "ARRI", "EST", "2026-03-13T10:01:00+00:00", NOW))),
    scenario("R12", "challenge", "Give me the exact recorded destination ETA and latest actual status for booking TEST-BKG-A.",
             expected("report", BOOKING, status="departed", eta=None, location="LBBEY", evidence=("TRACK-DEPART",)),
             events=(DEPART,)),
    scenario("R13", "challenge", "Please give me the actual discharge status of TEST-BOX-2 at Rotterdam. No ETA needed.",
             expected("report", BOOKING, SIBLING, "discharged", location="NLRTM", evidence=("TRACK-SIBLING",)),
             shipments=[ship(boxes=(BOX, SIBLING))], events=(DEPART, ARRIVED, DISCHARGED)),
    scenario("R14", "challenge", "Can you confirm this shipment's actual arrival? I have booking TEST-BKG-A and no other reference. Give the actual status and still-recorded ETA if available.",
             expected("report", BOOKING, status="departed", eta=ON_TIME, location="LBBEY", evidence=("TRACK-DEPART", "TRACK-ETA")),
             events=(DEPART, ESTIMATE, event("TRACK-HIDDEN-ACTUAL", "ARRI", "ACT", "2026-03-10T11:00:00+00:00", "2026-03-10T12:15:00+00:00"))),
)
