"""What the two supplied tests of issue #19 cannot show on their own.

`tests/integration/test_r08_reassignment.py` is the file the issue provides and it runs byte-identical. Two
of its assertions cannot be produced by this repository, so they are recorded in `tests/fixtures.py` rather
than bent: R5 assigns per machine and never per slot, so the second booking of the supplied scenario is not
the one the fault is about, and the comment of the second test describes two bookings the file itself never
makes — with one family booking in the database the other machine of the type is free at 11:00, so that turn
is covered and not uncoverable. What this file pins is R8 as the rule it is, each criterion as an externally
observable HTTP outcome:

- **AC1**: the pass runs earliest-start-first and the target is the lowest-numbered free machine of the type.
  One machine can hold one turn that still owes a cycle (`src/availability.py` refuses a machine held for a
  turn), so the seam never carries two live records on the same machine: the earliest-first order and its
  tie-break are the guarantee the pass is deterministic on, asserted as the decision in `src/faults.py`, and
  the target order is asserted as the machine the move lands on;
- **AC2**: the reassigned booking keeps its start, gets a new machine and a new code, and the notification
  names the new machine on the customer's own read;
- **AC3**: an uncoverable turn is cancelled and the day's count goes back with it — the refund is the right to
  rebook, not money (no token ledger, out of scope), and the customer can take a slot in the same call that
  told her the truth;
- **AC4**: an incident for every move and for every uncoverable cancellation;
- **AC5**: the invariant is checked after every pass, on every surface, and the answer carries what it found;
- **AC6**: the customer already standing at the machine is moved immediately, the machine is released from her
  turn and the cycle still ahead moves with the record;
- **AC7**: one call at the seam — the fault report or the owner's toggle — and the reviewer can watch the
  machine live while it happens;
- **AC8**: the notification exists only inside the app, gated to the customer the booking belongs to.

Nothing is mocked: the client posts over 127.0.0.1 and the repository is a real database.
"""

from datetime import datetime

from src import app as backend
from src import entitlements, faults, notifications
from tests.conftest import SEAM_PATHS


def booked(client, who, type_key, start) -> dict:
    """A booking created by `who`, as the response that names it."""
    created = client.post("/api/bookings", json={"type": type_key, "start": start}, headers=who)
    assert created.status_code == 201, created.text
    return created.json()


def codes_of(client, type_key) -> list:
    """The machine codes of one type, read off the panel board the owner reads."""
    owner = client.session(client.app.config["owner_email"])
    return [row["machine"] for row in client.get("/api/owner/machines", headers=owner).json()["machines"]
            if row["type"] == type_key]


def notes_of(client, who) -> list:
    """The notification as the app shows it: the customer's own read, inside the app."""
    answer = client.get("/api/notifications", headers=who)
    assert answer.status_code == 200, answer.text
    return answer.json()


def on_machine(client, code) -> list:
    """The machine-scoped bookings query: the read the machine is read through."""
    answer = client.get(f"/api/bookings?machine={code}")
    assert answer.status_code == 200, answer.text
    return answer.json()


# --- AC1: the order, and the machine the order names ----------------------------------------------

def test_the_target_is_the_lowest_numbered_free_machine_of_the_type(client, seed):
    anna = client.session("anna@example.com")
    # A third machine of the type, so the target is a choice between two and not the only one left.
    extra = client.post("/api/machines", json={"type": "family"})
    assert extra.status_code == 201, extra.text
    codes = codes_of(client, "family")
    assert len(codes) == 3

    first = booked(client, anna, "family", "10:00")
    machine = first["machine"]
    answer = client.post("/api/lock/reports", json={"machine": machine, "event": "fault"}, headers=anna)
    assert answer.status_code == entitlements.ALLOWED, answer.text
    moved = answer.json()["reassigned"][0]

    # The pass names the lowest-numbered free machine of the type: not the first one the query happened to
    # return, and not the one the booking had. `M2` is lower than `M10`, so the number is read as a number.
    free = [code for code in codes if code != machine]
    assert moved["machine"] == faults.lowest_numbered([{"code": code} for code in free])[0]["code"]
    assert moved["start"] == "10:00"                      # AC2: the slot is kept
    assert moved["code"] != first["code"]                 # AC2: the code is the booking's own, and it is new


def test_the_pass_is_ordered_earliest_start_first_with_the_creation_order_as_the_tie(client, seed):
    """The guarantee R8 needs to be demoable, asserted as the decision in one line.

    The seam cannot build the case: one machine holds one turn that still owes a cycle, so the pass never
    finds two live records on the same machine. What the order decides is what a reviewer would see the
    moment a machine carries more than one record, and it is the order the incidents are written in — the
    order this file can read back on a machine that carries the record of a cycle already run plus the record
    of the turn still owed.
    """
    anna = client.session("anna@example.com")
    bruno = client.session("bruno@example.com")
    first = booked(client, anna, "quick", "10:00")
    machine = first["machine"]

    client.clock.set(datetime(2026, 11, 12, 10, 5))
    client.post("/api/lock/redeem", json={"code": first["code"]}, headers=anna)
    client.post("/api/lock/reports", json={"code": first["code"], "event": "cycle_started"}, headers=anna)
    client.clock.set(datetime(2026, 11, 12, 10, 35))
    client.post("/api/lock/reports", json={"code": first["code"], "event": "cycle_finished"}, headers=anna)
    client.clock.set(datetime(2026, 11, 12, 10, 46))      # the turnover buffer has passed, the machine is back

    owed = booked(client, bruno, "quick", "11:00")
    assert owed["machine"] == machine, client.last_response.text

    row = client.app.repo.machine(machine)
    held = client.app.repo.bookings_on_machine(row["id"])
    assert [r["state"] for r in held] == ["finished", "confirmed"]
    order = faults.pass_order(held)
    # Earliest start first, and the same start twice would be broken by the order the records were created.
    assert [r["id"] for r in order] == [held[0]["id"], held[1]["id"]]
    assert faults.pass_order([held[1], held[0]]) == order

    # What the pass can act on is the turn still owed; the cycle the machine already ran is a fact, not a
    # turn to move, so it stays as the record it is and no incident names it.
    answer = client.post("/api/lock/reports", json={"machine": machine, "event": "fault"}, headers=anna)
    assert [entry["start"] for entry in answer.json()["reassigned"]] == ["11:00"]
    assert [i["kind"] for i in client.get("/api/incidents").json()] == ["fault", "reassignment"]


# --- AC2: the slot is kept, the code is new, the notification names the new machine ---------------

def test_the_move_keeps_the_start_issues_a_new_code_and_leaves_a_notification_the_customer_can_read(client, seed):
    anna = client.session("annita@example.com")
    beth = client.session("beth@example.com")
    first = booked(client, anna, "family", "10:00")
    second = booked(client, beth, "standard", "10:30")
    machine = first["machine"]

    answer = client.post("/api/lock/reports", json={"machine": machine, "event": "fault"}, headers=anna)
    assert answer.status_code == entitlements.ALLOWED, answer.text
    entry = answer.json()["reassigned"][0]
    assert entry["start"] == "10:00" and entry["booking"] == first["id"]

    moved = client.get(f"/api/bookings/{first['id']}", headers=anna).json()
    assert moved["start"] == "10:00"
    assert moved["machine"] == entry["machine"] and moved["machine"] != machine
    assert moved["code"] != first["code"] and moved["code"] == entry["code"]

    notes = notes_of(client, anna)
    assert any(n["kind"] == "reassigned" and n["machine"] == moved["machine"] for n in notes), notes
    assert notes[0]["booking"] == first["id"]

    # The code lives inside the booking and inside her own notification, never in a public view (US22): the
    # machine she has been moved to is read through the machine-scoped query, and that read answers the shape
    # a caller with no session can carry — no customer, no code.
    public = client.get(f"/api/bookings?machine={moved['machine']}").json()
    assert [row["id"] for row in public] == [first["id"]], public
    assert sorted(public[0]) == sorted(["id", "machine", "type", "start", "state", "grace_window", "end",
                                        "expected_end", "token_count", "tokens"]), public
    body = client.get(f"/api/bookings?machine={moved['machine']}").text
    assert first["code"] not in body and moved["code"] not in body and anna.email not in body, body


# --- AC3: the refund is the right to rebook, not money ---------------------------------------------

def test_an_uncoverable_turn_is_cancelled_and_the_day_s_allowance_goes_back_with_it(client, seed):
    anna = client.session("carl@example.com")
    beth = client.session("dani@example.com")
    victim = booked(client, anna, "quick", "10:00")
    other = booked(client, beth, "quick", "10:00")            # the last machine of the type, committed
    assert other["machine"] != victim["machine"]

    machine = victim["machine"]
    answer = client.post("/api/lock/reports", json={"machine": machine, "event": "fault"}, headers=anna)
    assert answer.status_code == entitlements.ALLOWED, answer.text
    assert answer.json()["reassigned"] == [] and answer.json()["cancelled"] == [victim["code"]]

    cancelled = client.get(f"/api/bookings/{victim['id']}", headers=anna).json()
    assert cancelled["state"] == "cancelled", cancelled
    incidents = client.get("/api/incidents").json()
    assert any(i["kind"] == "uncoverable" and i["booking"] == victim["id"] for i in incidents), incidents

    # US48 read against the refund: the cancelled turn does not consume the day, so the count is back to the
    # whole allowance and she is not punished for a fault she did not cause. There is no ledger to credit and
    # no money in this product: the refund is the right to rebook.
    list_read = client.get("/api/bookings", headers=anna).json()
    assert list_read["limit"]["used"] == 0 and list_read["limit"]["remaining"] == 2, list_read
    # A turn given back is not a turn lost: the no-show counter does not move for a cancellation.
    assert client.get("/api/customers/me", headers=anna).json()["no_show_count"] == 0

    # And she can take a slot as soon as the shop has one: beth's cycle is what holds the other machine.
    client.clock.set(datetime(2026, 11, 12, 10, 5))
    client.post("/api/lock/redeem", json={"code": other["code"]}, headers=beth)
    client.post("/api/lock/reports", json={"code": other["code"], "event": "cycle_started"}, headers=beth)
    client.post("/api/lock/reports", json={"code": other["code"], "event": "cycle_finished"}, headers=beth)
    client.clock.set(datetime(2026, 11, 12, 10, 46))          # the turnover buffer has passed
    rebooked = client.post("/api/bookings", json={"type": "quick", "start": "11:00"}, headers=anna)
    assert rebooked.status_code == 201, rebooked.text
    assert rebooked.json()["machine"] == other["machine"]

    # And the honest copy: the notification names the machine she was on and says the turn is given back.
    notes = notes_of(client, anna)
    assert any(n["kind"] == "cancelled" and n["machine"] == machine for n in notes), notes


# --- AC4 and AC5: the incidents, and the invariant checked after every pass ------------------------

def test_the_invariant_is_checked_after_every_pass_and_the_answer_carries_what_it_found(client, seed):
    anna = client.session("elisa@example.com")
    bruno = client.session("bruno@example.com")
    carla = client.session("carla@example.com")
    owner = client.session(seed["owner_email"])
    machine = booked(client, anna, "quick", "10:00")["machine"]

    # The device boundary runs R8 in full: nothing is left attached.
    answer = client.post("/api/lock/reports", json={"machine": machine, "event": "fault"}, headers=anna)
    assert answer.json()["attached"] == [] and on_machine(client, machine) == []
    assert [i["kind"] for i in client.get("/api/incidents").json()] == ["fault", "reassignment"]

    # The panel runs the same core, so the toggle is the same pass with the same invariant.
    second = booked(client, bruno, "standard", "10:15")["machine"]
    toggle = client.post(f"/api/owner/machines/{second}/maintenance", json={"state": "maintenance"},
                         headers=owner)
    assert toggle.status_code == 200, toggle.text
    assert toggle.json()["attached"] == [] and on_machine(client, second) == []

    # The claim is the one surface whose residue is narrower, and it is recorded for the human decision:
    # the claim is admitted by the record it is read against, so the machine keeps exactly that record.
    third = booked(client, carla, "family", "11:00")["machine"]
    claim = client.post(f"/api/machines/{third}/report", json={"kind": "fault"}, headers=carla)
    assert claim.status_code == entitlements.REPORT_ACCEPTED, claim.text
    assert claim.json()["kept"] and claim.json()["attached"] == claim.json()["kept"]


# --- AC6: the customer standing at the machine ------------------------------------------------------

def test_a_customer_already_standing_at_the_machine_is_moved_and_the_remaining_cycle_moves(client, seed):
    anna = client.session("fatima@example.com")
    booking = booked(client, anna, "quick", "10:30")
    machine = booking["machine"]

    client.clock.set(datetime(2026, 11, 12, 10, 35))
    redeemed = client.post("/api/lock/redeem", json={"code": booking["code"]}, headers=anna)
    assert redeemed.status_code == 200, redeemed.text
    assert client.get(f"/api/machines/{machine}").json()["state"] == "unlocked"

    answer = client.post("/api/lock/reports", json={"machine": machine, "event": "fault"}, headers=anna)
    assert answer.status_code == entitlements.ALLOWED, answer.text
    entry = answer.json()["reassigned"][0]
    # There is no staff to ask, so the answer is the move itself: new machine, new code, and the cycle that
    # is still ahead of the moment the fault was reported (25 of the 30 minutes).
    assert entry["standing"] is True and entry["remaining_minutes"] == 25
    assert entry["machine"] != machine and entry["code"] != booking["code"]

    # The machine is released from her turn: it keeps nothing, and it is read as maintenance.
    assert on_machine(client, machine) == []
    assert client.get(f"/api/machines/{machine}").json()["state"] == "maintenance"
    moved = client.get(f"/api/bookings/{booking['id']}", headers=anna).json()
    assert moved["machine"] == entry["machine"] and moved["code"] == entry["code"]
    assert any(n["kind"] == "reassigned" and n["machine"] == moved["machine"] for n in notes_of(client, anna))


# --- AC7: one call at the seam, watched live --------------------------------------------------------

def test_the_pass_is_one_call_and_a_reviewer_watches_the_machine_while_it_happens(client, seed):
    anna = client.session("gina@example.com")
    booking = booked(client, anna, "family", "10:00")
    machine = booking["machine"]

    before = client.get(f"/api/machines/{machine}").json()
    assert before["state"] == "reserved"
    answer = client.post("/api/lock/reports", json={"machine": machine, "event": "fault"}, headers=anna)
    after = client.get(f"/api/machines/{machine}").json()
    assert after["state"] == "maintenance" and after["assignable"] is False
    assert answer.json()["machine"] == machine and answer.json()["incident"] == "fault"
    assert len(answer.json()["reassigned"]) == 1
    # The same booking read through the machine it was attached to: the machine is public information, and
    # the read answers the shape a caller with no session can carry — no customer, no code.
    assert on_machine(client, machine) == []


# --- AC8: the notification is inside the app only ----------------------------------------------------

def test_the_notification_read_is_the_customer_s_own_and_needs_a_session(client, seed):
    anna = client.session("hana@example.com")
    machine = booked(client, anna, "quick", "10:00")["machine"]
    client.post("/api/lock/reports", json={"machine": machine, "event": "fault"}, headers=anna)

    # 401 for a caller with no session: the same gate as the booking surface, because a caller with no
    # identity has no notification to read.
    assert client.get("/api/notifications").status_code == entitlements.MISSING_SESSION
    other = client.session("ibo@example.com")
    assert notes_of(client, other) == []                        # she reads only her own
    assert notes_of(client, anna)

    # No transport: nothing outside the app, and the app read is a pattern, not a ninth contract entry.
    assert sorted(f"{method} {path}" for method, path in backend.ROUTES) == sorted(SEAM_PATHS)
    assert "GET /api/notifications" in backend.PATTERNS
    assert not [path for path in list(backend.ROUTES) + list(backend.PATTERNS)
                if any(word in path for word in ("mail", "sms", "push", "notify"))
                and path != "GET /api/notifications"]
    assert notifications.APP_KINDS == ("reassigned", "cancelled")
    # One stored fact, one mapping: the incident list answers `reassignment`, the app reads `reassigned`.
    assert notifications.app_word("reassignment") == "reassigned"
    assert notifications.app_word("cancellation") == "cancelled"
