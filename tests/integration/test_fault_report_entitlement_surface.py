"""The fault-report entitlement and its maintenance residue — what the two provided assertions alone
cannot show.

`tests/integration/test_fault_report_maintenance.py` is the file issue #10 slice b provides and it runs
byte-identical. What this file pins is the rest of the same three acceptance criteria: the two refusals
that must stay externally distinguishable (401 for a missing session, 403 for a wrong entitlement) on the
report surface, the entitlement read as a fact about a past booking as well as a current one, and the
refusal writing nothing — which is what "enforced at the seam, not by the UI hiding a control" means for
a caller who already holds the machine code.

Nothing is mocked: the client posts over 127.0.0.1 and the repository is a real database.

The machine code on the wire is the string the assignment shows, so the report is addressed to the machine
the caller was given, and the same decision answers on both report paths — `POST /api/lock/reports` and
`POST /api/machines/<code>/report`.
"""

from datetime import datetime

from src import app as backend
from src import entitlements
from tests.conftest import SEAM_PATHS


def booked(client, who, type_key, start) -> dict:
    """A booking created by `who`, as the response that names it."""
    created = client.post("/api/bookings", json={"type": type_key, "start": start}, headers=who)
    assert created.status_code == 201, created.text
    return created.json()


def reported(client, who, machine, kind="fault"):
    """The report as the issue writes it: addressed to the machine, on the report surface."""
    return client.post(f"/api/machines/{machine}/report", json={"kind": kind}, headers=who)


# --- AC1: the two refusals, on the report surface ----------------------------------------------

def test_a_missing_session_and_a_wrong_entitlement_are_still_two_outcomes_on_a_report(client, seed):
    carl = client.session("carl@example.com")
    eve = client.session("eve@example.com")
    booking = booked(client, carl, "family", "11:00")
    machine = booking["machine"]

    # A caller with no session has no name on any booking to be entitled with: it is answered "accedi",
    # never "non è tuo" — the report entitlement is read against a booking, and a booking needs an identity.
    anonymous = reported(client, None, machine)
    assert anonymous.status_code == entitlements.MISSING_SESSION, anonymous.text
    assert anonymous.json() == entitlements.missing_session(), anonymous.text

    # A session that never had a turn on this machine is answered "non è tua".
    denied = reported(client, eve, machine)
    assert denied.status_code == entitlements.NOT_ENTITLED, denied.text
    assert denied.json() == entitlements.report_refusal(), denied.text
    assert (entitlements.MISSING_SESSION, entitlements.NOT_ENTITLED) == (401, 403)

    # The same decision answers the device path: one predicate, one gate, no per-path copy of the rule.
    assert client.post("/api/lock/reports", json={"machine": machine, "event": "fault"},
                       headers=eve).status_code == entitlements.NOT_ENTITLED
    assert client.post("/api/lock/reports", json={"machine": machine, "event": "fault"}).status_code == 401
    # And the same decision is pure: it reads the fact, it does not decide a status.
    row = client.app.repo.machine(machine)
    assert entitlements.may_report(client.app.repo.get_or_create_identity(eve.email, False),
                                   client.app.repo.bookings_on_machine(row["id"], eve.email)) is False
    assert entitlements.may_report(client.app.repo.get_or_create_identity(carl.email, False),
                                   client.app.repo.bookings_on_machine(row["id"], carl.email)) is True


def test_a_past_booking_entitles_the_report_as_much_as_a_current_one(client, seed):
    carl = client.session("carl@example.com")
    booking = booked(client, carl, "standard", "12:00")
    machine = booking["machine"]

    # R7 says "has or had": the turn is what entitles, not the booking still being live. Carl gives the
    # slot back, and he is still the one who can say what happened on that machine.
    assert client.post(f"/api/bookings/{booking['id']}/cancel", headers=carl).status_code == 200
    accepted = reported(client, carl, machine)
    assert accepted.status_code == entitlements.REPORT_ACCEPTED, accepted.text
    assert accepted.json()["outcome"] == "maintenance"
    assert client.get(f"/api/machines/{machine}").json()["state"] == "maintenance"


# --- AC3: enforcement at the seam, not in a control the front-end hides -------------------------

def test_the_refused_report_writes_nothing_and_is_refused_on_the_request_the_caller_can_still_make(client, seed):
    carl = client.session("carl@example.com")
    eve = client.session("eve@example.com")
    booking = booked(client, carl, "family", "11:00")
    machine = booking["machine"]

    # Eve can read the machine: the state of a machine is public (US42), so the machine code is not a
    # secret she has to be given. What she cannot do is report it.
    read = client.get(f"/api/machines/{machine}")
    assert read.status_code == 200 and read.json()["state"] == "reserved", read.text
    assert reported(client, eve, machine).status_code == 403
    assert reported(client, eve, machine, kind="occupied").status_code == 403

    # Nothing is written for a refusal: the machine keeps the state the table had for it, Carl's booking
    # is still on it, and no incident is recorded. The empty button is not the enforcement; the 403 is.
    assert client.get(f"/api/machines/{machine}").json()["state"] == "reserved"
    owner = client.session(seed["owner_email"])
    assert [row["kind"] for row in client.get("/api/incidents", headers=owner).json()] == []
    board = {row["machine"]: row for row in client.get("/api/machines", headers=owner).json()["machines"]}
    assert board[machine]["bookings"][0]["id"] == booking["id"]

    # The report is a claim about a machine, so the machine is the only thing the caller can be entitled
    # on: an unknown kind is not a permission problem, it is a bad request, and it still writes nothing.
    unknown = client.post(f"/api/machines/{machine}/report", json={"kind": "broken"}, headers=carl)
    assert unknown.status_code == 400 and unknown.json()["error"] == "unknown_kind", unknown.text
    assert sorted(unknown.json()["accepted"]) == sorted(["fault", "occupied"])
    assert client.get(f"/api/machines/{machine}").json()["state"] == "reserved"


# --- AC2: the residue is a declared hop, not a coercion -----------------------------------------

def test_an_accepted_report_reaches_maintenance_through_the_declared_hop_only(client, seed):
    carl = client.session("carl@example.com")
    booking = booked(client, carl, "quick", "10:00")
    machine = booking["machine"]
    client.clock.set(datetime(2026, 11, 12, 10, 5))
    client.post("/api/lock/redeem", json={"code": booking["code"]}, headers=carl)
    client.post("/api/lock/redeem", json={"code": booking["code"]})  # already_redeemed, the fact stands
    client.post("/api/lock/reports", json={"code": booking["code"], "event": "cycle_started"}, headers=carl)

    # Running is not a source of maintenance (R6): the entitlement does not buy a hop, so an entitled
    # report is refused with the transition it attempted and the machine keeps its state.
    refused = reported(client, carl, machine)
    assert refused.status_code == 409 and refused.json()["error"] == "invalid_transition", refused.text
    assert refused.json()["from"] == "running" and refused.json()["to"] == "maintenance"
    assert client.get(f"/api/machines/{machine}").json()["state"] == "running"

    # From a state the table declares, the same entitled report is the residue: maintenance, and the
    # machine is visibly unavailable for the next customer (US42).
    client.clock.set(datetime(2026, 11, 12, 10, 35))
    client.post("/api/lock/reports", json={"code": booking["code"], "event": "cycle_finished"}, headers=carl)
    assert reported(client, carl, machine).status_code == entitlements.REPORT_ACCEPTED
    state = client.get(f"/api/machines/{machine}").json()
    assert state["state"] == "maintenance" and state["assignable"] is False


# --- the contract stays the contract --------------------------------------------------------------

def test_the_report_surface_is_a_pattern_not_a_ninth_contract_path(client, seed):
    assert sorted(f"{method} {path}" for method, path in backend.ROUTES) == sorted(SEAM_PATHS)
    carl = client.session("carl@example.com")
    eve = client.session("eve@example.com")
    first = booked(client, carl, "standard", "12:00")
    second = booked(client, carl, "standard", "13:00")

    # The contract entry still answers for the device and the pattern for the person, and both read the
    # same decision: the same caller, on the same kind of machine, is refused with the same body.
    foreign = client.post("/api/lock/reports", json={"machine": first["machine"], "event": "fault"},
                          headers=eve)
    assert foreign.status_code == 403 and foreign.json() == entitlements.report_refusal(), foreign.text
    assert reported(client, eve, first["machine"]).json() == foreign.json()

    # And the same core: a device fact is answered 200, an accepted claim is acknowledged 202, and the
    # state both drive is the one the table declares. A report that is not entitled never reaches the
    # core on either path, so the pattern is not a looser gate than the contract.
    device = client.post("/api/lock/reports", json={"machine": first["machine"], "event": "fault"},
                         headers=carl)
    assert device.status_code == entitlements.ALLOWED and device.json()["outcome"] == "maintenance", device.text
    person = reported(client, carl, second["machine"])
    assert person.status_code == entitlements.REPORT_ACCEPTED and person.json()["outcome"] == "maintenance", person.text
    assert {client.get(f"/api/machines/{m}").json()["state"] for m in (first["machine"], second["machine"])} == {"maintenance"}
    assert reported(client, eve, second["machine"]).status_code == 403
    assert client.get(f"/api/machines/{second['machine']}").json()["state"] == "maintenance"
