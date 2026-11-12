"""What the one pinned test of issue #11 (slice b2) cannot show on its own.

`tests/integration/test_maintenance_never_booked.py` is the file the issue provides and it runs
byte-identical: one behaviour, one test — a machine in `maintenance` can never be assigned a booking, so the
slot only that machine could serve is refused and the machine keeps exactly its entitled pre-report booking.
What this file pins is the rest of the same three acceptance criteria, each as an externally observable HTTP
outcome:

- **AC2 from the other side**: the refusal is the answer to a request the caller can still make, it writes
  nothing on the fenced machine, and the alternatives it carries are the bounded ones #51 pins — every one of
  them a slot of the type on the grid, earliest first. The fence is what refuses: lift the state through the
  owner's toggle and the same machine is a candidate again, so the invariant is about `maintenance`, not about
  a slot that happens to be busy;
- **AC3 as a shape**: the machine-scoped read answers to a caller with no session, because the machine is the
  subject and a machine is public information (US42), so the record it answers with carries no customer and no
  code (US22);
- **the path the decision lives on**: the claim keeps the record the entitlement was read against
  (`src/faults.py`), while the device boundary runs R8 in full on the same call. The two readings are pinned on
  their own paths and the gate answers the same refusal body on both: the fork is the residue, not the
  permission, and it is visible from outside the seam.
- **the shape of the seam itself**: the machine-scoped list is a query on the contract entry, not a ninth
  entry, and the same record read by its own customer still carries the code — the two views differ on the
  two keys and on nothing else.

Nothing is mocked: the client posts over 127.0.0.1 and the repository is a real database.
"""

from src import app as backend
from src import entitlements, faults
from src.domain import time as start_times
from tests.conftest import SEAM_PATHS


def booked(client, who, type_key, start) -> dict:
    """A booking created by `who`, as the response that names it."""
    created = client.post("/api/bookings", json={"type": type_key, "start": start}, headers=who)
    assert created.status_code == 201, created.text
    return created.json()


def reported(client, who, machine, kind="fault"):
    """The report as the issue writes it: a person's claim, addressed to the machine."""
    return client.post(f"/api/machines/{machine}/report", json={"kind": kind}, headers=who)


def on_machine(client, code) -> list:
    """The machine-scoped bookings query: the read the machine is read through."""
    answer = client.get(f"/api/bookings?machine={code}")
    assert answer.status_code == 200, answer.text
    return answer.json()


# --- AC2: the fence, read as an outcome that writes nothing -------------------------------------

def test_the_slot_only_a_maintenance_machine_could_serve_is_refused_and_writes_nothing(client, seed):
    carl = client.session("carl@example.com")
    beth = client.session("beth@example.com")
    first = booked(client, carl, "quick", "10:00")
    machine = first["machine"]
    assert reported(client, carl, machine).status_code == entitlements.REPORT_ACCEPTED
    assert client.get(f"/api/machines/{machine}").json()["state"] == "maintenance"

    # The other machine of the type holds the 11:00 slot, so the fenced one is the only candidate left.
    second = booked(client, beth, "quick", "11:00")
    assert second["machine"] != machine
    eve = client.session("eve@example.com")
    refused = client.post("/api/bookings", json={"type": "quick", "start": "11:00"}, headers=eve)
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"] == "no_machine_free"
    # The bounded alternatives #51 pins, asserted as the shape they must have before any of them can be
    # called valid: a bounded set, every point a grid point of the type, earliest first.
    alternatives = refused.json()["alternatives"]
    assert alternatives and len(alternatives) <= start_times.DEFAULT_ALTERNATIVES, refused.text
    grid = {start_times.slot(point) for point in start_times.valid_start_times(client.clock.now().date(),
                                                                              "quick", client.app.config)}
    assert all(point in grid for point in alternatives), refused.text
    assert alternatives == sorted(alternatives)

    # Enforcement at the seam, not in a control the front-end hides: the refusal writes nothing on the fenced
    # machine, which keeps exactly the record the claim was read against, and it answers as unfree.
    assert [row["id"] for row in on_machine(client, machine)] == [first["id"]]
    assert client.get(f"/api/machines/{machine}").json()["assignable"] is False


def test_the_fence_is_the_state_and_not_the_slot_so_it_lifts_with_the_state(client, seed):
    carl = client.session("carl@example.com")
    ada = client.session("ada@example.com")
    first = booked(client, carl, "quick", "10:00")
    machine = first["machine"]
    assert reported(client, carl, machine).status_code == entitlements.REPORT_ACCEPTED

    # While the machine is fenced a request for the type can only be honoured elsewhere: the assignment step
    # never names the fenced machine, so the fence is what sends ada to the other machine of the type.
    assert booked(client, ada, "quick", "11:00")["machine"] != machine
    owner = client.session(seed["owner_email"])
    assert client.post(f"/api/owner/machines/{machine}/maintenance", json={"state": "available"},
                       headers=owner).status_code == 200
    # The same machine, the same kind of request: "never" is written about the state, so lifting `maintenance`
    # makes the machine a candidate again, and the booking that entitles the report is still attached to it.
    assert client.get(f"/api/machines/{machine}").json()["assignable"] is True
    later = booked(client, ada, "quick", "11:15")
    assert later["machine"] == machine
    assert [row["id"] for row in on_machine(client, machine)] == [first["id"], later["id"]]


# --- AC3: the shape of the read the machine is read through --------------------------------------

def test_the_machine_scoped_read_answers_the_shape_a_read_with_no_session_can_carries(client, seed):
    carl = client.session("carl@example.com")
    first = booked(client, carl, "quick", "10:00")
    machine = first["machine"]
    assert reported(client, carl, machine).status_code == entitlements.REPORT_ACCEPTED

    # The machine is the subject, and a machine is public information (US42): the read answers without a
    # session, so the record it answers with carries neither the customer nor the code (US22).
    records = on_machine(client, machine)
    assert len(records) == 1 and records[0]["id"] == first["id"]
    assert sorted(records[0]) == sorted(["id", "machine", "type", "start", "state", "grace_window", "end",
                                         "expected_end", "token_count", "tokens"])
    body = client.get(f"/api/bookings?machine={machine}").text
    assert first["code"] not in body and carl.email not in body, body

    # The same shape for a caller who is not entitled to the booking: the query is not a way to read a code
    # that lives only inside its own booking.
    eve = client.session("eve@example.com")
    assert client.get(f"/api/bookings?machine={machine}", headers=eve).json() == records

    # An unknown machine is the refusal the decision names, not an empty list, and the caller's own list is
    # unchanged by the machine-scoped shape: the query decides which shape answers, nothing else.
    missing = client.get("/api/bookings?machine=M99", headers=eve)
    assert missing.status_code == entitlements.UNKNOWN_MACHINE and missing.json() == entitlements.unknown_machine()
    assert client.get("/api/bookings", headers=eve).json()["bookings"] == []

    # The fence is the same predicate the public view answers on: with the whole type fenced, every point of
    # the window is refused and the word named is the one the fixed vocabulary reserves for it.
    ada = client.session("ada@example.com")
    other = booked(client, ada, "quick", "10:15")["machine"]
    assert reported(client, ada, other).status_code == entitlements.REPORT_ACCEPTED
    window = client.get("/api/availability?window_hours=1&type=quick").json()["types"]["quick"]
    reasons = {point["start"]: point["reason"] for point in window["slots"]}
    assert window["count"] == 0 and all(reason is not None for reason in reasons.values())
    assert reasons["10:30"] == "machine_in_maintenance"


# --- the fork is the residue, not the gate: pinned on both paths ---------------------------------

def test_the_machine_scoped_shape_is_a_query_on_the_contract_path_not_a_ninth_entry(client, seed):
    # `GET /api/bookings` is the contract entry; the query decides which shape it answers with, exactly as
    # the query of the public availability read decides the board or the window (issue #8). Nothing is added
    # to the eight entries tests/conftest.py pins.
    assert sorted(f"{method} {path}" for method, path in backend.ROUTES) == sorted(SEAM_PATHS), backend.ROUTES
    carl = client.session("carl@example.com")
    record = booked(client, carl, "standard", "12:00")["booking"]
    # The two views are the same record with the two keys taken out, and nothing else: the read a caller with
    # no session can answer cannot carry the code or the customer, the read filtered by the identity can.
    assert client.get("/api/bookings", headers=carl).json()["bookings"] == [record]
    assert client.get(f"/api/bookings?machine={record['machine']}").json() == [
        {key: value for key, value in record.items() if key not in ("code", "unlock_code")}]

def test_the_claim_keeps_the_record_it_is_read_against_and_the_device_boundary_runs_r8_in_full(client, seed):
    carl = client.session("carl@example.com")
    first = booked(client, carl, "quick", "10:00")
    machine = first["machine"]
    claim = reported(client, carl, machine)
    assert claim.status_code == entitlements.REPORT_ACCEPTED
    assert claim.json()["kept"] == [first["id"]] and claim.json()["reassigned"] == []

    # The same call on the path where the fault is the machine's own fact runs R8 in full: the booking the shop
    # can honour elsewhere moves, and a machine in maintenance keeps nothing.
    dani = client.session("dani@example.com")
    second = booked(client, dani, "family", "11:00")
    fact = client.post("/api/lock/reports", json={"machine": second["machine"], "event": "fault"}, headers=dani)
    assert fact.status_code == entitlements.ALLOWED and fact.json()["outcome"] == "maintenance", fact.text
    assert fact.json()["kept"] == [] and len(fact.json()["reassigned"]) == 1
    assert fact.json()["reassigned"][0]["machine"] != second["machine"]
    assert on_machine(client, second["machine"]) == []

    # One gate, one decision, no per-path copy of the rule: a caller who never had a turn on the machine is
    # refused with the same body on both paths, and the decision still reads the record it is made of.
    eve = client.session("eve@example.com")
    assert reported(client, eve, machine).json() == client.post(
        "/api/lock/reports", json={"machine": machine, "event": "fault"}, headers=eve).json()
    row = client.app.repo.machine(machine)
    identity = client.app.repo.get_or_create_identity(carl.email, False)
    held = client.app.repo.bookings_on_machine(row["id"], carl.email)
    strangers = client.app.repo.bookings_on_machine(row["id"], eve.email)
    assert entitlements.may_report(client.app.repo.get_or_create_identity(eve.email, False), strangers) is False
    assert entitlements.may_report(identity, held) is True
    assert faults.entitled_booking(identity, held) == held[0]
    assert faults.may_move(held[0], faults.CLAIM, held[0]) is False
    assert faults.may_move(held[0], faults.DEVICE, held[0]) is True
    assert client.get(f"/api/machines/{machine}").json()["state"] == "maintenance"
