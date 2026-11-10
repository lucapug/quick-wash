"""The machine state machine, asserted through the seam (R6, AC 2, 3, 4, 7, 8).

The three tests the issue supplies are in tests/integration/test_r06_state_machine.py and run as
given. What this module adds is the rest of R6: that the table is one machine-readable dict read
from one place, that it agrees with the section of docs/spec.md the mirror is written from, that
`maintenance` is reachable only from the four declared states and never assignable, that
`cleaning_required` comes back after the 30-minute buffer, that `expired` is never a machine state,
and that the state can be watched live per machine.

Every assertion is an HTTP outcome, with the one exception AC 7 needs: the table itself, because a
mirror can only be checked against the thing it mirrors. The mirror is written by the docs owner, so
what is checked here is the invariant that keeps it honest: the file and its AGENTS.md index line
arrive together, and when the file exists it renders this table.
"""
import pathlib
import re

from src import machine_states
from src import app as backend
from src.config import SEED

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC = ROOT / "docs" / "spec.md"
MIRROR = ROOT / "docs" / "machine-states.md"


def spec_section() -> str:
    text = SPEC.read_text(encoding="utf-8")
    start = text.index("### Machine state machine")
    rest = text[start:]
    end = rest.find("\n### ")
    return rest[:end]


def backticks(line: str) -> list:
    return re.findall(r"`([^`]+)`", line)


# --- AC 7: one machine-readable table, and the two agree --------------------------------

def test_the_table_is_a_single_dict_and_the_http_layer_does_not_hold_a_second_one():
    assert isinstance(machine_states.TRANSITIONS, dict)
    second_tables = {name: value for name, value in vars(backend).items()
                     if isinstance(value, dict) and any(isinstance(hops, set) for hops in value.values())}
    assert not second_tables, second_tables


def test_the_code_table_agrees_with_the_spec_it_mirrors():
    section = spec_section()
    chain_line = next(line for line in section.splitlines() if "→" in line)
    assert [hop.strip() for hop in backticks(chain_line)[0].split("→")] == list(machine_states.HAPPY_PATH)

    for line in (line for line in section.splitlines() if line.startswith("- `")):
        state = backticks(line)[0]
        if state in machine_states.NOT_STATES:
            continue  # the spec says these are not states: `expired` for a booking, `idle_open` as an event
        clause = line.split("reachable from")[1].split(";")[0].split(".")[0]
        spec_sources = set(backticks(clause))
        declared = machine_states.sources_of(state)
        if state == "cleaning_required":
            # R10's branch is the one documented extension: the customer the machine is assigned to
            # reports it as still occupied, so `reserved` is added to the spec's source.
            assert declared == spec_sources | machine_states.R10_ENTRY, (state, declared, spec_sources)
        else:
            assert declared == spec_sources, (state, declared, spec_sources)
        assert state in machine_states.STATES, state


def test_the_mirror_and_the_context_index_are_added_together():
    # The mirror is generated from this table, so the two cannot disagree: the file is written from
    # `table_view`, and AGENTS.md indexes every modular doc under docs/. The mirror is a docs-owner
    # step — the executor's scope is src/ and tests/ — so the invariant checked here is that the file
    # and its index line arrive together, and that when the file exists it renders this table.
    indexed = "`docs/machine-states.md`" in (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert MIRROR.is_file() == indexed
    view = machine_states.table_view(SEED)
    assert view["buffers"] == {"finished": 10, "cleaning_required": 30}      # addendum patch 2
    assert view["states"] == list(machine_states.STATES)
    assert view["not_states"] == ["idle_open", "expired"]
    if not MIRROR.is_file():
        return
    rendered = MIRROR.read_text(encoding="utf-8")
    for state, hops in view["transitions"].items():
        line = next((row for row in rendered.splitlines() if row.startswith(f"- `{state}`")), "")
        assert line, state
        assert all(f"`{hop}`" in line for hop in hops), state


def test_idle_open_and_expired_are_not_states_of_a_machine():
    assert "idle_open" not in machine_states.STATES
    assert "expired" not in machine_states.STATES
    assert "idle_open" in machine_states.DEVICE_EVENTS
    assert "expired" in machine_states.BOOKING_TERMINAL_STATES
    assert not any("idle_open" in hops for hops in machine_states.TRANSITIONS.values())


def test_every_hop_of_the_happy_path_is_one_http_call_on_the_seam():
    hops = list(zip(machine_states.HAPPY_PATH, machine_states.HAPPY_PATH[1:]))
    assert hops == [("available", "reserved"), ("reserved", "unlocked"), ("unlocked", "running"),
                    ("running", "finished"), ("finished", "available")]
    assert all(machine_states.declares(*hop) for hop in hops)
    assert all(hop in machine_states.SEAM_CALL for hop in hops)


# --- AC 2: maintenance is reachable only from the four, and never assignable ------------

def test_a_hop_into_maintenance_from_undeclared_state_is_refused(client, seed):
    ada = client.session("ada@example.com")
    booking = client.post("/api/bookings", json={"type": "quick", "start": "10:00"}, headers=ada.headers).json()
    machine = booking["machine"]
    client.post("/api/lock/redeem", json={"code": booking["code"]}, headers=ada.headers)
    client.post("/api/lock/reports", json={"machine": machine, "event": "cycle_started"}, headers=ada.headers)

    refused = client.post("/api/lock/reports", json={"machine": machine, "event": "fault"}, headers=ada.headers)
    assert refused.status_code == 409, refused.text
    assert refused.json()["from"] == "running" and refused.json()["to"] == "maintenance"
    assert client.get(f"/api/machines/{machine}").json()["state"] == "running"  # not coerced


def test_a_machine_in_maintenance_is_never_assignable(client, seed):
    ada = client.session("ada@example.com")
    booking = client.post("/api/bookings", json={"type": "quick", "start": "10:00"}, headers=ada.headers).json()
    machine = booking["machine"]
    report = client.post("/api/lock/reports", json={"machine": machine, "event": "fault"}, headers=ada.headers)
    assert report.status_code == 200 and report.json()["outcome"] == "maintenance"
    assert client.get(f"/api/machines/{machine}").json()["state"] == "maintenance"

    # R8 moved ada onto the other machine of the type, so the only machine that could take a later
    # slot is the one in maintenance — and it is refused, not assigned.
    bruno = client.session("bruno@example.com")
    refused = client.post("/api/bookings", json={"type": "quick", "start": "11:00"}, headers=bruno.headers)
    assert refused.status_code == 409 and refused.json()["error"] == "no_machine_free", refused.text
    quick = [row for row in client.get("/api/availability").json()["types"] if row["type"] == "quick"][0]
    assert quick["free"] == 0


# --- AC 3: cleaning_required comes back to available after the 30-minute buffer ----------

def test_cleaning_required_returns_to_available_after_the_thirty_minute_buffer(client, seed):
    ada = client.session("ada@example.com")
    booking = client.post("/api/bookings", json={"type": "quick", "start": "10:00"}, headers=ada.headers).json()
    machine = booking["machine"]
    client.post("/api/lock/redeem", json={"code": booking["code"]}, headers=ada.headers)
    client.post("/api/lock/reports", json={"machine": machine, "event": "cycle_started"}, headers=ada.headers)
    client.post("/api/lock/reports", json={"machine": machine, "event": "cycle_finished"}, headers=ada.headers)

    client.clock.advance(minutes=seed["buffers"]["turnover_minutes"])          # R10, then the hop
    assert client.get(f"/api/machines/{machine}").json()["state"] == "available"
    assert client.post("/api/bookings", json={"type": "quick", "start": "10:15"}, headers=ada.headers).json()["machine"] == machine

    report = client.post("/api/lock/reports", json={"machine": machine, "event": "occupied"}, headers=ada.headers)
    assert report.status_code == 200 and report.json()["outcome"] == "cleaning_required"
    assert client.get(f"/api/machines/{machine}").json()["state"] == "cleaning_required"

    client.clock.advance(minutes=seed["buffers"]["cleaning_minutes"])          # addendum patch 2
    assert client.get(f"/api/machines/{machine}").json()["state"] == "available"


# --- AC 4: `expired` is terminal for a booking, never for a machine ----------------------

def test_an_expired_booking_leaves_its_machine_available_not_expired(client, seed):
    ada = client.session("ada@example.com")
    booking = client.post("/api/bookings", json={"type": "family", "start": "10:00"}, headers=ada.headers).json()
    machine = booking["machine"]
    client.clock.advance(minutes=71)   # past the grace window: 10:11
    expired = client.post("/api/lock/redeem", json={"code": booking["code"]}, headers=ada.headers)
    assert expired.status_code == 409 and expired.json()["outcome"] == "expired"

    assert client.get("/api/bookings", headers=ada.headers).json()["bookings"][0]["state"] == "expired"
    assert client.get(f"/api/machines/{machine}").json()["state"] == "available"


# --- AC 8: the state is reported per machine, live ----------------------------------------

def test_the_state_of_one_machine_is_read_live_without_a_session(client, seed):
    ada = client.session("ada@example.com")
    booking = client.post("/api/bookings", json={"type": "quick", "start": "10:00"}, headers=ada.headers).json()
    machine = booking["machine"]
    assert client.get(f"/api/machines/{machine}").json()["state"] == "reserved"
    client.post("/api/lock/redeem", json={"code": booking["code"]}, headers=ada.headers)
    assert client.get(f"/api/machines/{machine}").json()["state"] == "unlocked"

    # The board stays the owner panel: it is the one that lists the bookings attached to a machine.
    assert client.get("/api/machines", headers=ada.headers).status_code == 403
    board = client.get("/api/machines", headers=client.session(seed["owner_email"]).headers).json()
    row = {entry["machine"]: entry for entry in board["machines"]}[machine]
    assert row["state"] == "unlocked" and row["bookings"][0]["code"] == booking["code"]
