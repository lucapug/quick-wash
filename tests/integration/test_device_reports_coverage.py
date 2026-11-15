"""What issue #13 (the device boundary) asserts as outcomes, and what the file it supplies cannot.

`tests/integration/test_device_reports.py` arrives byte-identical and is never adjusted. It pins two
behavioural facts — `running` comes from `cycle_started` and not from a timer, and a 15-minute idle open
releases the machine and records an incident — and both are implemented. What it cannot do is reach them:
the reasons are recorded as xfail entries in `tests/fixtures.py`, and they are facts of the pack, not of the
implementation (no session, `GET /api/customers/me` is not one of the eight contract paths `tests/conftest.py`
pins, and the read ninety minutes after an open is the request that fires the event the issue's own Decision
puts on every read). This file reads the same criteria through the seam, so each rule stays verified as an
externally observable outcome rather than as a promise.

What is asserted here, criterion by criterion:

- **AC1** — the device is in-process and has exactly two calls, and it holds nothing beyond what it
  observed: no copy of the machine state, no booking, no repository, no field for money. The only thing it
  can write is its own `observed`, and every machine state it names is written by `Application.transition`
  through the R6 table.
- **AC2 and AC3** — `running` and `finished` are the outcome of a report, never of a timer and never of a
  payment assumption. The moment `finished` happens is the moment the report names it, not `start +
  cycle_minutes`: the record keeps the type's duration as data while the state comes from the device.
- **AC4** — the 15-minute rule, on its bound (inclusive), closed as the issue states it: booking `closed`,
  machine `available`, incident `idle_open`, and the no-show on the counter of the customer the turn belongs
  to — read through `GET /api/bookings`, the contract entry that carries it as the R9 block. The two refusals
  the rule has are asserted too: a machine that is not `unlocked` is not a lost turn, and a machine with no
  booking attached has no turn to close.
- **AC5** — a device fault from a customer who has or had a booking on the machine drives `maintenance`, and
  the refusal of a stranger writes nothing.
- **AC6** — the contract is the same two calls a real controller would use: nothing in the device module is a
  protocol, a service or a transport of its own.
- **AC7** — every device call carries the journey trace of the booking it belongs to, and a call that carries
  a foreign one is refused before anything is written.

Nothing is mocked: the client posts over 127.0.0.1, the repository is a real database, and the clock the test
controls is the clock behind the seam that the simulator is handed as a dependency.
"""

import ast
import pathlib

import pytest

from src import app as backend
from src import machine_states, simulator
from src.config import SEED
from src.repository import TABLES
from src.simulator import WasherSimulator

ROOT = pathlib.Path(__file__).resolve().parents[2]

# The words a vendor protocol would bring with it. Nothing in the device module is one of them: the device is
# reached through the two contract calls and has no transport of its own.
PROTOCOL_MARKERS = ("mqtt", "amqp", "modbus", "serial", "gpio", "firmware", "vendor", "broker", "socket",
                    "queue", "topic", "container")

LOCK = {path for _, path in simulator.CONTRACT.values()}
MONEY_MARKERS = ("token", "pay", "paid", "price", "ledger", "amount")


def transport(client):
    """The device's only route: the contract, over HTTP, exactly as a controller makes it."""
    return lambda method, path, body, headers=None: client.post(path, json=body, headers=headers)


def device(client, clock, email, type_key, start):
    """A customer, its booking, and the device standing in front of the machine it was assigned."""
    who = client.session(email)
    response = client.post("/api/bookings", json={"type": type_key, "start": start}, headers=who)
    assert response.status_code == 201, response.text
    return who, response.json(), WasherSimulator(transport(client), clock=clock, config=SEED)


def state(client, machine) -> str:
    """The machine as the seam reports it: the read a reviewer watches live (issue #6, AC 8)."""
    return client.get(f"/api/machines/{machine}").json()["state"]


def device_lines(client) -> list:
    """The device calls, as the seam recorded them: one request line per call, never a call inside code."""
    return [line for line in client.get("/api/logs/recent").json()["entries"] if line["path"] in LOCK]


def incidents_of(client, kind) -> list:
    return [i for i in client.get("/api/incidents").json() if i["kind"] == kind]


# --- AC1: in-process, and reached only through the lock API contract ----------------------------

def test_the_simulator_is_in_process_and_has_exactly_the_two_calls_of_the_contract(client, seed, clock):
    assert simulator.IN_PROCESS is True
    assert sorted(simulator.CONTRACT) == ["redeem", "report"]
    assert sorted(f"{method} {path}" for method, path in simulator.CONTRACT.values()) == [
        "POST /api/lock/redeem", "POST /api/lock/reports"]
    # Both are contract entries, not a path the simulator invented: they are two of the eight the seam pins.
    assert all(f"{method} {path}" in {f"{m} {p}" for m, p in backend.ROUTES}
               for method, path in simulator.CONTRACT.values())

    _, booking, sim = device(client, clock, "ada@example.com", "quick", "10:00")
    clock.set("10:05")
    sim.redeem(booking["code"])
    sim.report("cycle_started")
    sim.report("cycle_finished")
    assert [line["path"] for line in device_lines(client)] == ["/api/lock/redeem",
                                                                "/api/lock/reports", "/api/lock/reports"]
    assert simulator.device_view(sim)["contract"] == {
        "redeem": "POST /api/lock/redeem", "report": "POST /api/lock/reports"}
    assert simulator.device_view(sim)["in_process"] is True


def test_the_device_holds_nothing_beyond_what_it_observed(client, seed, clock):
    """No internal state management: the device's whole memory is the facts it observed at the machine."""
    _, booking, sim = device(client, clock, "bruno@example.com", "quick", "10:00")
    assert sorted(vars(sim)) == ["clock", "config", "observed", "transport"]
    assert sorted(sim.observed) == sorted(simulator.OBSERVED_FIELDS)
    assert sim.observed["machine"] is None and sim.observed["opened_at"] is None
    # It is not a second writer of the domain: it holds no state table, no booking and no repository.
    for name in ("machine_states", "bookings", "booking", "repo", "repository", "state", "states"):
        assert name not in vars(sim), name

    clock.set("10:05")
    sim.redeem(booking["code"])
    assert sorted(sim.observed) == sorted(simulator.OBSERVED_FIELDS)
    assert sim.observed["machine"] == booking["machine"] and sim.observed["opened_at"] == clock.now()
    # A field outside the observed set is not reachable: the device has no memory to read from.
    assert not [field for field in sim.observed if field not in simulator.OBSERVED_FIELDS]
    assert not hasattr(sim, "machine_state") and not hasattr(sim, "booking")
    sim.report("cycle_started")
    assert sim.observed["cycle_started_at"] == clock.now() and sim.observed["cycle_finished_at"] is None
    assert "machine_state" not in sim.observed, "the device never names a state, it names what it observed"


# --- AC2: `running` is the report, never a timer and never a payment assumption ------------------

def test_no_timer_and_no_payment_assumption_move_a_machine_to_running(client, seed, clock):
    who, booking, sim = device(client, clock, "carla@example.com", "family", "16:00")
    machine = booking["machine"]
    clock.set("15:55")                       # inside the grace window, so this call is the redemption
    assert sim.redeem(booking["code"]).json()["outcome"] == "unlocked"

    clock.set("16:09")                       # inside the 15-minute bound: nothing has been reported yet
    assert state(client, machine) == "unlocked"
    assert client.get(f"/api/bookings/{booking['id']}", headers=who).json()["state"] == "unlocked"

    sim.report("cycle_started")
    assert state(client, machine) == "running"
    assert client.get(f"/api/bookings/{booking['id']}", headers=who).json()["state"] == "running"


def test_the_device_has_no_field_for_money_and_the_seam_infers_nothing_about_payment(client, seed, clock):
    assert not [field for field in simulator.OBSERVED_FIELDS
                if any(marker in field for marker in MONEY_MARKERS)], simulator.OBSERVED_FIELDS
    assert not [name for name in TABLES if any(marker in name for marker in MONEY_MARKERS)], TABLES
    assert not [entry for entry in backend.ROUTES if any(marker in entry[1] for marker in MONEY_MARKERS)]

    _, booking, sim = device(client, clock, "dani@example.com", "standard", "10:00")
    clock.set("10:05")
    answer = sim.redeem(booking["code"]).json()
    # The count is data the booking carries, answered at the keypad call: it changes nothing on the machine.
    assert answer["tokens_required"] == booking["token_count"]
    assert answer["outcome"] == "unlocked" and state(client, booking["machine"]) == "unlocked"


# --- AC3: `finished` is the moment the device names, not start + cycle_minutes -------------------

def test_finished_comes_at_the_moment_the_report_names_it_not_at_start_plus_cycle_minutes(client, seed, clock):
    who, booking, sim = device(client, clock, "edo@example.com", "family", "16:00")   # nominal end 17:15
    machine = booking["machine"]
    clock.set("16:05")
    sim.redeem(booking["code"])
    sim.report("cycle_started")

    clock.set("16:40")                        # 35 minutes into a 75-minute cycle: the device has not reported
    assert state(client, machine) == "running"
    sim.report("cycle_finished")              # the machine stopped early: the report is the fact
    row = client.get(f"/api/machines/{machine}").json()
    assert row["state"] == "finished"
    assert row["bookable_from"] == "16:50"    # the 10-minute turnover buffer, from the reported moment
    read = client.get(f"/api/bookings/{booking['id']}", headers=who).json()
    assert read["state"] == "finished"
    assert read["end"] == "17:15", "the record keeps the type's duration as data; the state is the device's"


def test_a_report_the_device_never_observed_is_not_sent_and_the_seam_refuses_the_hop_it_attempts(client, seed, clock):
    _, booking, sim = device(client, clock, "fra@example.com", "quick", "10:00")
    machine = booking["machine"]
    clock.set("10:05")
    sim.redeem(booking["code"])
    with pytest.raises(simulator.NotObserved):
        sim.report("cycle_finished")          # the device cannot invent a cycle it never started
    refused = client.post("/api/lock/reports", json={"machine": machine, "event": "cycle_finished"})
    assert refused.status_code == 409 and refused.json()["error"] == "invalid_transition", refused.text
    assert refused.json()["from"] == "unlocked" and refused.json()["to"] == "finished"
    assert state(client, machine) == "unlocked"   # the refusal wrote nothing
    # And the device cannot name an event the lock API does not accept.
    with pytest.raises(ValueError):
        sim.report("door_open")


# --- AC4: the 15-minute rule, on its bound, and the record it leaves ------------------------------

def test_idle_open_fires_on_the_bound_and_not_before_it(client, seed, clock):
    who, booking, sim = device(client, clock, "gina@example.com", "standard", "17:00")
    machine = booking["machine"]
    clock.set("17:05")
    assert sim.redeem(booking["code"]).json()["outcome"] == "unlocked"

    clock.advance(minutes=14)                 # the fourteenth minute: the bound is not reached
    assert sim.idle_open_due() is False and sim.observe() is None
    assert state(client, machine) == "unlocked"

    clock.advance(minutes=1)                  # the fifteenth minute, inclusive on the bound
    assert sim.idle_open_due() is True
    answer = sim.observe().json()
    assert answer["incident"] == "idle_open" and answer["outcome"] == "closed"
    assert state(client, machine) == "available"
    assert client.get(f"/api/bookings/{booking['id']}", headers=who).json()["state"] == "closed", \
        "closed is what the event leaves; expired is R3's word for a code that never worked"
    incidents = client.get("/api/incidents").json()
    assert any(i["kind"] == "idle_open" and i["machine"] == machine for i in incidents), incidents
    # The event is not a state: nothing in the table has an `idle_open` key.
    assert "idle_open" not in machine_states.STATES
    assert machine_states.DEVICE_EVENTS["idle_open"] == "available"


def test_the_read_of_the_machine_is_what_makes_the_rule_observable_without_a_scheduler(client, seed, clock):
    """The Decision: the rule is evaluated at report time and at every read, from the recorded open.

    No clock is mocked inside a unit test, so the outcome has to come from the seam. Here nothing is
    reported at all: the read is the request that notices the bound, and the facts it writes are the same
    facts a report would have written.
    """
    who, booking, sim = device(client, clock, "ili@example.com", "quick", "10:00")
    machine = booking["machine"]
    clock.set("10:05")
    sim.redeem(booking["code"])
    clock.set("10:21")                        # sixteen minutes after the open: the read is what sees it

    assert state(client, machine) == "available"
    assert client.get(f"/api/bookings/{booking['id']}", headers=who).json()["state"] == "closed"
    incidents = client.get("/api/incidents").json()
    assert any(i["kind"] == "idle_open" and i["machine"] == machine for i in incidents), incidents
    # One fact, not two: the same closure read again writes no second incident and no second no-show.
    state(client, machine)
    assert len([i for i in client.get("/api/incidents").json() if i["kind"] == "idle_open"]) == 1
    assert client.get("/api/bookings", headers=who).json()["block"]["blocked"] is None


def test_the_no_show_is_counted_for_the_customer_the_turn_belongs_to_even_when_a_read_notices_it(client, seed, clock):
    """R9 (issue #20): `idle_open` counts on the customer's counter, not on the caller's.

    The counter is read on `GET /api/bookings`, the contract entry that carries it as the R9 block —
    `GET /api/customers/me` is not one of the eight paths `tests/conftest.py` pins.
    """
    ada, first, sim = device(client, clock, "mea@example.com", "quick", "10:00")
    clock.set("10:05")
    sim.redeem(first["code"])

    # The read that notices the bound is made with no session: the observer. The counter still moves for the
    # customer the booking belongs to, because the fact is attached to the booking, not to the caller.
    clock.set("10:21")
    state(client, first["machine"])
    assert client.get("/api/bookings", headers=ada).json()["bookings"][0]["state"] == "closed"
    assert client.get("/api/bookings", headers=ada).json()["block"]["blocked"] is None    # one no-show

    second = client.post("/api/bookings", json={"type": "quick", "start": "11:00"}, headers=ada).json()
    # The device for that booking is a second device standing in front of a second machine: it carries the
    # journey its own redemption gave it, not the one the first booking's journey has.
    clock.set("11:05")
    WasherSimulator(transport(client), clock=clock, config=SEED).redeem(second["code"])
    clock.set("11:21")
    state(client, second["machine"])
    assert len(incidents_of(client, "idle_open")) == 2, client.get("/api/incidents").json()
    blocked = client.post("/api/bookings", json={"type": "quick", "start": "12:00"}, headers=ada)
    assert blocked.status_code == 403 and blocked.json()["error"] == "blocked", blocked.text
    assert blocked.json()["no_shows"] == 2 and blocked.json()["until"] == "2026-11-19"
    # The incident names the customer only on the owner's surface, never on the observer's read.
    owner = client.session(seed["owner_email"])
    panel = [i for i in client.get("/api/owner/incidents", headers=owner).json() if i["kind"] == "idle_open"]
    assert panel and panel[0]["email"] == "mea@example.com"


def test_idle_open_on_a_machine_that_is_not_unlocked_is_refused_and_writes_nothing(client, seed, clock):
    """AC4 read from the other side: the event belongs to an open that never started a cycle.

    A machine the rule cannot reach from where it stands is not a lost turn. The answer is the attempted
    hop (R6, AC6): the machine keeps the state it had, no booking is closed, no incident is recorded and
    the counter does not move.
    """
    who, booking, sim = device(client, clock, "nin@example.com", "quick", "10:00")
    machine = booking["machine"]
    clock.set("10:05")
    sim.redeem(booking["code"])
    sim.report("cycle_started")                # a cycle started: the open is not an idle open

    clock.set("10:25")                         # past the bound, but the machine is `running`
    refused = client.post("/api/lock/reports", json={"machine": machine, "event": "idle_open"})
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"] == "invalid_transition", refused.text
    assert refused.json()["from"] == "running" and refused.json()["to"] == "available"
    assert state(client, machine) == "running", "the refusal wrote nothing on the machine"
    assert client.get(f"/api/bookings/{booking['id']}", headers=who).json()["state"] == "running"
    assert incidents_of(client, "idle_open") == []
    assert client.get("/api/bookings", headers=who).json()["block"]["blocked"] is None
    # The device reads the same predicate and cannot send what it did not observe: an open it has already
    # reported as started is not an idle open.
    assert sim.observed["cycle_started_at"] is not None and sim.observe() is None


def test_idle_open_on_a_machine_with_no_booking_is_answered_as_not_found_and_writes_nothing(client, seed, clock):
    """A machine the device is standing in front of for no reason: nothing to close, nothing to count.

    The report names a machine, and the booking the rule can close is the one still attached to it. With no
    booking the answer is the record that is not there (404) and the fact is not written: no hop, no incident,
    no no-show — which is also what keeps the same lost turn from being counted twice after its closure.
    """
    # A machine with no booking at all: the registry has no screen, the seed write is the only way to add one.
    created = client.post("/api/machines", {"type": "quick"})
    assert created.status_code == 201, created.text
    lonely = created.json()["code"]
    missing = client.post("/api/lock/reports", json={"machine": lonely, "event": "idle_open"})
    assert missing.status_code == 404, missing.text
    assert missing.json()["error"] == "booking_not_found", missing.text
    assert state(client, lonely) == "available"
    assert incidents_of(client, "idle_open") == []

    # The same report after the closure it belongs to: the turn is already closed, so the fact is one.
    who, booking, sim = device(client, clock, "ola@example.com", "quick", "10:00")
    machine = booking["machine"]
    clock.set("10:05")
    sim.redeem(booking["code"])
    clock.set("10:20")
    closed = sim.observe().json()
    assert closed["outcome"] == "closed", closed
    again = client.post("/api/lock/reports", json={"machine": machine, "event": "idle_open"})
    assert again.status_code == 404, again.text
    assert again.json()["error"] == "booking_not_found", again.text
    assert state(client, machine) == "available"
    assert len(incidents_of(client, "idle_open")) == 1, client.get("/api/incidents").json()
    assert client.get("/api/bookings", headers=who).json()["block"]["blocked"] is None   # one no-show, still


# --- AC5: a device fault from a customer who has or had a booking on the machine ------------------

def test_a_device_fault_report_from_an_entitled_customer_drives_maintenance(client, seed, clock):
    ada, booking, sim = device(client, clock, "nia@example.com", "standard", "12:00")
    machine = booking["machine"]
    clock.set("12:05")
    sim.redeem(booking["code"], headers=ada)

    accepted = sim.report("fault", headers=ada)
    assert accepted.status_code == 200 and accepted.json()["outcome"] == "maintenance", accepted.text
    assert state(client, machine) == "maintenance"

    # R7: the entitlement is the fact the report is read against. A caller who never had a turn on that
    # machine is refused, and the refusal writes nothing on a machine already out of service.
    stranger = client.session("odi@example.com")
    refused = client.post("/api/lock/reports", json={"machine": machine, "event": "fault"}, headers=stranger)
    assert refused.status_code == 403, refused.text
    assert state(client, machine) == "maintenance"
    # And the device reports on the machine, never on a state it chose.
    assert sim.observed["machine"] == machine and "state" not in sim.observed


# --- AC6: the contract is what a real controller would use -----------------------------------------

def test_the_contract_carries_no_protocol_and_no_transport_of_its_own(client, seed):
    text = (ROOT / "src" / "simulator.py").read_text(encoding="utf-8").lower()
    assert not [marker for marker in PROTOCOL_MARKERS if marker in text], \
        [marker for marker in PROTOCOL_MARKERS if marker in text]

    tree = ast.parse((ROOT / "src" / "simulator.py").read_text(encoding="utf-8"))
    imports = sorted({node.name if isinstance(node, ast.Import) else node.module
                      for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))})
    assert imports == ["datetime", "src", "src.clock", "src.config"]
    # No repository, no database: the device reaches the backend only through the two contract calls.
    assert not [name for name in imports if "repository" in name or "db" in name]
    # And the rule it acts on is not a copy: the device reads the same predicate the seam evaluates, so the
    # bound cannot be reached twice, once by the device and once by the read.
    assert simulator.machine_states.idle_open_due is machine_states.idle_open_due
    assert sorted(simulator.REPORTS) == ["cycle_finished", "cycle_started", "fault", "idle_open"]
    assert set(simulator.REPORTS) <= set(machine_states.DEVICE_EVENTS)
    assert "occupied" not in simulator.REPORTS, "that report is a customer's claim (R10, US33), not a device fact"


# --- AC7: every device call carries the journey trace ----------------------------------------------

def test_every_device_call_carries_the_trace_of_the_journey_it_belongs_to(client, seed, clock):
    _, booking, sim = device(client, clock, "pio@example.com", "quick", "10:00")
    machine = booking["machine"]
    clock.set("10:05")
    answer = sim.redeem(booking["code"]).json()

    # A call that carries a journey which is not this booking's is refused before anything is written.
    bad = client.post("/api/lock/reports", json={"machine": machine, "event": "cycle_started",
                                                  "trace": "t-aaaaaaaaaa"})
    assert bad.status_code == 400 and bad.json()["error"] == "trace_not_this_journey", bad.text
    assert bad.json()["journey"] == answer["trace"], bad.text
    assert state(client, machine) == "unlocked", "the refusal wrote nothing"

    sim.report("cycle_started")
    sim.report("cycle_finished")
    lines = device_lines(client)
    assert [line["path"] for line in lines] == ["/api/lock/redeem"] + ["/api/lock/reports"] * 3
    assert {line["trace"] for line in lines} == {answer["trace"]}, lines
    assert sim.observed["trace"] == answer["trace"], "the device carries the identifier, it does not invent one"
    assert answer["trace"].startswith("t-") and not any(char.isdigit() for char in answer["trace"])
    # And no device call can put a code in a log line: the guard in the recorder is what refuses it.
    assert booking["code"] not in client.get("/api/logs/recent").text
