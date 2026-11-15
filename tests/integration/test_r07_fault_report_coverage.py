"""What the two supplied assertions of issue #16 cannot show on their own.

`tests/integration/test_r07_fault_report.py` is the file the issue provides and it runs byte-identical: the
report from a customer who has a booking on the machine drives `maintenance`, records the incident, clears the
machine out of the window, and no booking may remain attached to a machine in `maintenance`. What this file
pins is the rest of the same eight criteria, each as an externally observable outcome:

- **AC4, the reason the entitlement exists**: a machine that has never held a turn cannot be reported at all,
  so the mechanism cannot be used to take a machine out of circulation for somebody else. The entitlement is
  read per machine and not per customer — a caller entitled on one machine is refused on another machine of the
  same type — and a refusal writes nothing;
- **AC2 read as "had"**: the record the entitlement is read against is a persisted booking, in whatever state
  the record is in, not a flag on the session that made it. A turn that is over still entitles the person who
  had it, and a sign-in that remembers nothing is entitled exactly as the one that made the booking;
- **the panel, the only non-customer path**: the owner puts a machine out of service and takes it back, and the
  incident the panel writes is the owner's own decision, never a `fault`. `src/faults.py` decides this per
  surface in one line, so one action is never written twice;
- **AC8**: the four declared sources reach `maintenance` as outcomes and the two undeclared ones are refused
  with the hop they attempted, with nothing written for a refusal — including no incident;
- **one implementation**: the hop into `maintenance` has one writer, so the deterministic trigger of issue #24,
  the reviewer's demo and this file run the same code path.

Nothing is mocked: the client posts over 127.0.0.1 and the repository is a real database.
"""

import ast
import pathlib
from datetime import datetime

from src import entitlements, faults, machine_states

ROOT = pathlib.Path(__file__).resolve().parents[2]

# AC8, read out of the table the seam writes through: the four sources issue #8 declares, and the states a
# report is not allowed to move.
DECLARED_SOURCES = {"available", "reserved", "unlocked", "finished"}
UNDECLARED_SOURCES = ("running", "cleaning_required")


def booked(client, who, type_key, start) -> dict:
    """A booking created by `who`, as the response that names it."""
    created = client.post("/api/bookings", json={"type": type_key, "start": start}, headers=who)
    assert created.status_code == 201, created.text
    return created.json()


def reported(client, who, machine, kind="fault"):
    """The report as the issue writes it: a person's claim, addressed to the machine."""
    return client.post(f"/api/machines/{machine}/report", json={"kind": kind}, headers=who)


def state_of(client, code) -> str:
    """The machine as a reviewer reads it: public, so the read needs no session."""
    return client.get(f"/api/machines/{code}").json()["state"]


def panel_incidents(client, owner, kind: str | None = None) -> list:
    """The incident list as the owner reads it: the only read that carries the customer."""
    rows = client.get("/api/owner/incidents", headers=owner).json()
    return [row for row in rows if kind is None or row["kind"] == kind]


def codes_of(client, owner, type_key) -> list:
    """The machine codes of one type, read off the panel board."""
    return [row["machine"] for row in client.get("/api/owner/machines", headers=owner).json()["machines"]
            if row["type"] == type_key]


def reached(client, who, code) -> str:
    """The report on a machine this caller has a turn on, and the state the declared hop left."""
    answer = reported(client, who, code)
    assert answer.status_code == entitlements.REPORT_ACCEPTED, answer.text
    assert answer.json()["incident"] == "fault", answer.text
    return state_of(client, code)


# --- AC4: a machine that never held a turn cannot be taken out of service -------------------------

def test_a_machine_that_never_had_a_booking_is_refused_and_stays_in_service(client, seed):
    anna = client.session("anna@example.com")
    zoe = client.session("zoe@example.com")
    owner = client.session(seed["owner_email"])

    hers = booked(client, anna, "standard", "10:00")["machine"]
    never = [code for code in codes_of(client, owner, "standard") if code != hers][0]

    # The entitlement is read against a record on *that* machine: it does not travel from one machine of the
    # type to another, and a machine that never held a turn has no record to read it against. This is the
    # abuse R7 exists to stop — a report from somebody with no turn on the machine cannot take it out of
    # circulation for the customer who does.
    assert reported(client, anna, never).status_code == entitlements.NOT_ENTITLED
    assert reported(client, zoe, never).status_code == entitlements.NOT_ENTITLED

    # A refusal writes nothing: the machine is in service, assignable, and no incident names it.
    read = client.get(f"/api/machines/{never}").json()
    assert read["state"] == "available" and read["assignable"] is True
    assert panel_incidents(client, owner, "fault") == []

    # The panel is not a way round the rule either: a customer who already holds the machine code is not the
    # owner, and the refusal is the decision, not a hidden control.
    denied = client.post(f"/api/owner/machines/{never}/maintenance", json={"state": "maintenance"}, headers=anna)
    assert denied.status_code == entitlements.NOT_ENTITLED and denied.json() == entitlements.panel_refusal()
    assert state_of(client, never) == "available"
    assert panel_incidents(client, owner) == []

    # The same caller, the same request, a different answer: the machine she had a turn on is hers to report.
    accepted = reported(client, anna, hers)
    assert accepted.status_code == entitlements.REPORT_ACCEPTED, accepted.text
    assert state_of(client, hers) == "maintenance"
    assert [i["machine"] for i in panel_incidents(client, owner, "fault")] == [hers]


# --- AC2: "or had" is a fact about a persisted booking, not about a session ------------------------

def test_a_turn_that_is_over_still_entitles_the_report_as_much_as_a_live_one(client, seed):
    anna = client.session("anna@example.com")
    owner = client.session(seed["owner_email"])
    booking = booked(client, anna, "quick", "10:00")
    machine = booking["machine"]

    # The grace window closes with no cycle started: the record is `expired`, the machine is back in service,
    # and the person the record belongs to is still the one who can say what happened on that machine.
    client.clock.set(datetime(2026, 11, 12, 10, 20))
    lost = client.get(f"/api/bookings/{booking['id']}", headers=anna).json()
    assert lost["state"] == "expired", lost
    assert state_of(client, machine) == "available"

    # A sign-in that remembers nothing about the booking is entitled, because the fact lives in the row and
    # not in the session that made it.
    fresh = client.session(anna.email)
    accepted = reported(client, fresh, machine)
    assert accepted.status_code == entitlements.REPORT_ACCEPTED, accepted.text
    assert state_of(client, machine) == "maintenance"

    # The incident names the persisted record: the same machine, the same booking, the identity the gate read.
    fault = panel_incidents(client, owner, "fault")
    assert [i["machine"] for i in fault] == [machine]
    assert str(fault[0]["booking_id"]) == str(booking["id"])
    assert fault[0]["email"] == anna.email

    # And the decision itself, with no session in sight: the row in its terminal state is what answers.
    row = client.app.repo.machine(machine)
    held = client.app.repo.bookings_on_machine(row["id"], anna.email)
    assert [r["state"] for r in held] == ["expired"]
    assert entitlements.may_report(client.app.repo.get_or_create_identity(anna.email, False), held) is True
    # The same machine read for a caller with no record of her own: the gate is answered from the rows read
    # for the caller, and there are none.
    strangers = client.app.repo.bookings_on_machine(row["id"], "zoe@example.com")
    assert strangers == []
    assert entitlements.may_report(client.app.repo.get_or_create_identity("zoe@example.com", False), strangers) is False
    assert faults.entitled_booking(client.app.repo.get_or_create_identity(anna.email, False), held) == held[0]


# --- the panel: the only non-customer path, and the incident it writes is its own decision ---------

def test_the_panel_is_the_only_non_customer_path_and_records_the_owner_s_decision_not_a_fault(client, seed):
    anna = client.session("anna@example.com")
    owner = client.session(seed["owner_email"])
    machine = booked(client, anna, "standard", "10:00")["machine"]

    # The customer's path records the fault itself.
    assert reported(client, anna, machine).status_code == entitlements.REPORT_ACCEPTED
    assert [i["kind"] for i in panel_incidents(client, owner)] == ["fault"]

    # A customer cannot reach the toggle, and the refusal writes nothing.
    denied = client.post(f"/api/owner/machines/{machine}/maintenance", json={"state": "available"}, headers=anna)
    assert denied.status_code == entitlements.NOT_ENTITLED and denied.json() == entitlements.panel_refusal()
    assert state_of(client, machine) == "maintenance"
    assert [i["kind"] for i in panel_incidents(client, owner)] == ["fault"]

    # For the owner both directions are declared hops, and the incident is the owner's own action.
    free = [code for code in codes_of(client, owner, "quick") if code != machine][0]
    out = client.post(f"/api/owner/machines/{free}/maintenance", json={"state": "maintenance"}, headers=owner)
    assert out.status_code == 200 and out.json()["outcome"] == "maintenance", out.text
    # The core writes no incident on the panel surface: the toggle records its own decision, once.
    assert out.json()["incident"] is None
    assert [i["kind"] for i in panel_incidents(client, owner)] == ["fault", "maintenance"]

    back = client.post(f"/api/owner/machines/{free}/maintenance", headers=owner)
    assert back.status_code == 200 and back.json()["outcome"] == "available", back.text
    assert [i["kind"] for i in panel_incidents(client, owner)] == ["fault", "maintenance", "maintenance_lifted"]

    # One line per surface is what decides this: the panel's list is the list of the owner's own actions,
    # and one action is never written twice.
    assert faults.incident_kind(faults.CLAIM) == faults.INCIDENT_KIND
    assert faults.incident_kind(faults.DEVICE) == faults.INCIDENT_KIND
    assert faults.incident_kind(faults.PANEL) is None


def test_the_device_boundary_records_the_same_fact_through_the_same_call(client, seed):
    anna = client.session("anna@example.com")
    owner = client.session(seed["owner_email"])
    machine = booked(client, anna, "family", "11:00")["machine"]

    fact = client.post("/api/lock/reports", json={"machine": machine, "event": "fault"}, headers=anna)
    assert fact.status_code == entitlements.ALLOWED and fact.json()["incident"] == "fault", fact.text
    assert state_of(client, machine) == "maintenance"

    # On the device boundary R8 runs in full, so the fact leaves the fault and the move it caused, and the
    # fenced machine keeps nothing — the same invariant the supplied file reads from the other side.
    assert [i["kind"] for i in panel_incidents(client, owner)] == ["fault", "reassignment"]
    assert [i["machine"] for i in panel_incidents(client, owner, "fault")] == [machine]
    assert client.get(f"/api/bookings?machine={machine}").json() == []


# --- AC8: the sources of the hop, asserted as outcomes and as refusals -----------------------------

def test_each_declared_source_of_maintenance_is_reached_through_the_seam(client, seed):
    owner = client.session(seed["owner_email"])
    assert set(machine_states.sources_of("maintenance")) == DECLARED_SOURCES

    # `reserved`: the assignment itself.
    ada = client.session("ada@example.com")
    reserved = booked(client, ada, "quick", "10:00")["machine"]
    assert state_of(client, reserved) == "reserved"
    assert reached(client, ada, reserved) == "maintenance"

    # `unlocked`: the hop is the redemption itself, read inside the grace window.
    beth = client.session("beth@example.com")
    opened = booked(client, beth, "quick", "11:00")
    client.clock.set(datetime(2026, 11, 12, 10, 25))
    client.post("/api/lock/redeem", json={"code": opened["code"]}, headers=beth)
    assert state_of(client, opened["machine"]) == "unlocked"
    assert reached(client, beth, opened["machine"]) == "maintenance"

    # `finished`: a cycle the device saw begin and end.
    carl = client.session("carl@example.com")
    cycle = booked(client, carl, "standard", "12:00")
    client.clock.set(datetime(2026, 11, 12, 11, 25))
    client.post("/api/lock/redeem", json={"code": cycle["code"]}, headers=carl)
    client.post("/api/lock/reports", json={"code": cycle["code"], "event": "cycle_started"}, headers=carl)
    client.post("/api/lock/reports", json={"code": cycle["code"], "event": "cycle_finished"}, headers=carl)
    assert state_of(client, cycle["machine"]) == "finished"
    assert reached(client, carl, cycle["machine"]) == "maintenance"

    # `available`: a turn given back before the window, the machine back in service.
    dani = client.session("dani@example.com")
    returned = booked(client, dani, "standard", "13:00")
    client.post(f"/api/bookings/{returned['id']}/cancel", headers=dani)
    assert state_of(client, returned["machine"]) == "available"
    assert reached(client, dani, returned["machine"]) == "maintenance"

    # Four sources, four incidents, one kind: the hop was taken from each of them and nothing else.
    assert sorted(i["machine"] for i in panel_incidents(client, owner, "fault")) == sorted([
        reserved, opened["machine"], cycle["machine"], returned["machine"]])
    assert [i["kind"] for i in panel_incidents(client, owner) if i["kind"] != "fault"] == ["cancellation"]


def test_an_undeclared_source_is_refused_with_the_hop_it_attempted_and_writes_no_incident(client, seed):
    owner = client.session(seed["owner_email"])
    assert all(not machine_states.declares(source, "maintenance") for source in UNDECLARED_SOURCES)

    # `running`: the entitlement does not buy a hop.
    eli = client.session("eli@example.com")
    cycle = booked(client, eli, "family", "11:00")
    machine = cycle["machine"]
    client.clock.set(datetime(2026, 11, 12, 10, 25))
    client.post("/api/lock/redeem", json={"code": cycle["code"]}, headers=eli)
    client.post("/api/lock/reports", json={"code": cycle["code"], "event": "cycle_started"}, headers=eli)
    assert state_of(client, machine) == "running"
    refused = reported(client, eli, machine)
    assert refused.status_code == 409 and refused.json()["error"] == "invalid_transition", refused.text
    assert refused.json()["from"] == "running" and refused.json()["to"] == "maintenance"
    assert state_of(client, machine) == "running"

    # `cleaning_required`: a machine already out of circulation for cleaning is not a second way into
    # maintenance. The claim moves the claimant where the shop can cover her; here nothing of the type is
    # free, so her record stays attached and the gate still answers for her. The refusal is the table, not
    # the permission.
    gina = client.session("gina@example.com")
    fenced = booked(client, gina, "quick", "12:00")["machine"]
    hal = client.session("hal@example.com")
    booked(client, hal, "quick", "12:00")          # the last machine of the type, taken at the same slot
    claim = client.post(f"/api/machines/{fenced}/report", json={"kind": "occupied"}, headers=gina)
    assert claim.status_code == entitlements.REPORT_ACCEPTED, claim.text
    assert claim.json()["reassigned"] is None and state_of(client, fenced) == "cleaning_required"

    refused = reported(client, gina, fenced)
    assert refused.status_code == 409 and refused.json()["error"] == "invalid_transition", refused.text
    assert refused.json()["from"] == "cleaning_required" and refused.json()["to"] == "maintenance"
    assert state_of(client, fenced) == "cleaning_required"

    # The two refusals write nothing: the incident list holds only what the seam actually took.
    assert sorted(i["kind"] for i in panel_incidents(client, owner)) == sorted(["cleaning_required", "uncoverable"])


# --- one implementation: the hop into `maintenance` has one writer ---------------------------------

def test_the_hop_into_maintenance_has_one_writer_so_the_demo_and_the_test_run_the_same_code_path(client, seed):
    """The deterministic trigger of issue #24 is a request on one of these surfaces, not a fourth core.

    The three surfaces reach `maintenance` through `Application.apply_fault`, and `apply_fault` is the only
    place in `src/app.py` that writes that hop, so the reviewer's demo, the device fact, the customer's claim
    and this test cannot drift into three readings of R7.
    """
    tree = ast.parse((ROOT / "src" / "app.py").read_text(encoding="utf-8"))
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]

    def calls(node, name):
        return [call for call in ast.walk(node) if isinstance(call, ast.Call)
                and getattr(call.func, "attr", None) == name]

    writers = sorted({node.name for node in functions for call in calls(node, "transition")
                      if len(call.args) > 1 and getattr(call.args[1], "value", None) == "maintenance"})
    assert writers == ["apply_fault"], writers

    surfaces = sorted({getattr(call.args[3], "attr", None)
                       for node in functions for call in calls(node, "apply_fault")
                       if len(call.args) > 3})
    assert surfaces == sorted(["CLAIM", "DEVICE", "PANEL"]), surfaces

    # And the surfaces answer the same outcome from that one core, each with the incident its surface is
    # allowed to write: `fault` where the report is a statement about the machine, the owner's own action
    # where it is the owner's decision.
    owner = client.session(seed["owner_email"])
    ivy = client.session("ivy@example.com")
    claim = booked(client, ivy, "family", "13:00")["machine"]
    answer = reported(client, ivy, claim)
    assert answer.status_code == entitlements.REPORT_ACCEPTED and answer.json()["outcome"] == "maintenance"
    assert answer.json()["incident"] == faults.incident_kind(faults.CLAIM)

    other = [code for code in codes_of(client, owner, "standard") if code != claim][0]
    toggle = client.post(f"/api/owner/machines/{other}/maintenance", json={"state": "maintenance"}, headers=owner)
    assert toggle.status_code == 200 and toggle.json()["outcome"] == "maintenance", toggle.text
    assert toggle.json()["incident"] is None            # the panel writes its own decision, in the toggle
    assert [i["kind"] for i in panel_incidents(client, owner)] == ["fault", "maintenance"]
