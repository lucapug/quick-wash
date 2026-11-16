"""Issue #24 (the deterministic fault trigger and the eight-machine demo seed), read as outcomes.

`tests/integration/test_deterministic_fault_trigger.py` arrives byte-identical and is never adjusted. It runs
as supplied and answers 202, `maintenance` and two incidents for the same trigger on the same machine —
everything but its reading of the incident's `machine` key, which contradicts the file issue #18 (R7)
supplies: that file, and the three others that read the incident list, pin `machine` as the machine code the
seam answers with (`M3`), while this file reads it as the number the request named (`3`). Both files are
pinned, so the contradiction is recorded in `tests/fixtures.py` rather than resolved by bending `src/`. What
this file pins is the rest of the issue's criteria as externally observable HTTP outcomes, so each rule stays
verified as an outcome while the contradiction stays visible.

What is asserted here, criterion by criterion:

- **AC1** — the switch is configuration (`src/config.py`, default empty, read at startup) and the panel action
  puts a named machine out of use immediately; the same call on the same machine gives the same result twice.
  No randomness anywhere in the path.
- **AC2** — the trigger is not a fourth core. It runs `apply_report`, the function the claim surface runs, and
  `Application.apply_fault` stays the only writer of the hop into `maintenance`; the handler writes no state of
  its own, so the demo, the reviewer's commands and the test cannot drift.
- **AC3** — the seed is the pack's inventory: 8 machines, 4 standard + 2 family + 2 quick, written from
  `src/config.py` on an empty database, idempotently.
- **AC4** — the tariffs (60/4, 75/6, 30/3), the opening hours (07:00-22:00, closed Sunday) and the two buffers
  (turnover 10, cleaning 30, addendum patch 2) are seed data read back over HTTP.
- **AC5** — the chain is reproducible with two commands: the start, then one trigger call, and the state change
  plus the incident are both readable without a session. The alert half of the chain is not: nothing alerts and
  nobody is paged in this repository (`docs/deployment.md`, the honest half), so this issue earns the state
  change and the incident, not the page-out.
- **AC6** — running the seed twice produces the same inventory and no duplicates.

Nothing is mocked: the client posts over 127.0.0.1, the repository is a real database, and the startup path is
exercised on its own database, the way a reviewer's start exercises it.
"""

import ast
import pathlib
import tempfile
from datetime import datetime

from src import app as backend
from src import faults
from src import machine_states
from src.config import SEED
from src.db import connect
from tests.conftest import SEAM_PATHS

TRIGGER_PATH = "/api/owner/faults/trigger"
ROOT = pathlib.Path(__file__).resolve().parents[2]


def trigger(client, machine, headers=None) -> dict:
    """The panel action, as the reviewer calls it: one request, one machine named."""
    answer = client.post(TRIGGER_PATH, json={"machine": machine}, headers=headers)
    assert answer.status_code == 202, answer.text
    return answer.json()


def state_of(client, named) -> str:
    """The machine read live, by the number the request named or by the code the board spells."""
    return client.get(f"/api/machines/{named}").json()["state"]


def fault_incidents(client, machine=None) -> list:
    rows = client.get("/api/incidents").json()
    return [row for row in rows if row["kind"] == "fault" and (machine is None or row["machine"] == machine)]


# --- AC1: the switch and the action, and the same result twice ------------------------------------

def test_the_trigger_names_the_machine_and_answers_as_an_accepted_report(client, seed):
    # The number and the code name the same machine: `machine_named` is the one resolution the panel and the
    # public per-machine read share, so the reviewer's trigger call and the reviewer's read speak about one
    # object.
    answer = trigger(client, 3)
    assert answer["machine"] == "M3" and answer["outcome"] == "maintenance", answer
    assert state_of(client, 3) == "maintenance"
    assert state_of(client, "M3") == "maintenance"
    recorded = fault_incidents(client, "M3")
    assert len(recorded) == 1, recorded
    assert recorded[0]["machine"] == "M3"
    # The seam's incident shape is the code, the way issue #18's supplied file pins it: this is the one
    # assertion the supplied file of this issue cannot reach, and it is recorded in tests/fixtures.py.
    assert recorded[0]["booking"] is None, recorded      # no record to read the entitlement against


def test_the_same_trigger_on_the_same_machine_gives_the_same_result(client, seed):
    """No randomness: the demo has to be runnable twice and read the same way twice."""
    first = trigger(client, 5)
    second = trigger(client, 5)
    assert first == second, (first, second)
    assert state_of(client, 5) == "maintenance"
    assert len(fault_incidents(client, "M5")) == 2
    # The second call writes no second hop: `TRANSITIONS` declares no self-entry for `maintenance`, so the
    # state stands — the same reading as the repeat cleaning claim (US35) — and the incident is the second fact.
    assert "maintenance" not in {state for state, hops in machine_states.TRANSITIONS.items() if state in hops}
    assert machine_states.declares("available", "maintenance") and not machine_states.declares("maintenance",
                                                                                              "maintenance")


def test_the_switch_is_configuration_with_an_empty_default_and_is_read_at_startup(client, seed):
    assert SEED["fault_trigger_machine"] == "", SEED["fault_trigger_machine"]
    assert not fault_incidents(client), "an empty switch puts nothing out of use"
    assert client.app.repo.settings()["fault_trigger_machine"] == ""
    assert client.app.fault_trigger == ""
    # The application reads exactly two variables (`docs/deployment.md`), so the switch is seed data, not a
    # third variable: the capitals the issue writes are the key's name.


def test_the_switch_at_startup_puts_the_named_machine_out_of_use_before_the_first_request():
    """Open decision 1, accepted as signed: the fault exists in the running system, not only in a test."""
    with tempfile.TemporaryDirectory() as folder:
        db = connect(path=f"{folder}/issue-24-startup.db")
        try:
            startup = backend.Application(db, clock=backend.Clock(datetime(2026, 11, 12, 9, 0)),
                                         config={**SEED, "fault_trigger_machine": "M7"})
            rows = startup.repo.incidents()
            assert [row["kind"] for row in rows] == ["fault"], rows
            assert startup.repo.machine("M7")["state"] == "maintenance"
            # AC6 on the same database: the seed run a second time writes the same eight machines and the
            # same one fact, not a duplicate of either.
            startup.repo.seed()
            assert startup.repo.machine_counts() == SEED["types"]
            assert len(startup.repo.incidents()) == 1
        finally:
            db.close()


# --- AC2: one implementation, not a fourth core ----------------------------------------------------

def test_the_trigger_runs_the_report_core_and_writes_no_state_of_its_own(client, seed):
    tree = ast.parse((ROOT / "src" / "app.py").read_text(encoding="utf-8"))
    handler = next(node for node in ast.walk(tree)
                   if isinstance(node, ast.FunctionDef) and node.name == "handle_owner_trigger")
    calls = [call for call in ast.walk(handler) if isinstance(call, ast.Call)]
    assert not [call for call in calls if getattr(call.func, "attr", None) == "transition"], calls
    assert any(getattr(call.func, "attr", None) == "apply_report" for call in calls), calls

    # And the residue is the report's residue: the pass runs on the machine the trigger names, so a turn
    # attached to it is moved by the same pass R8 defines — same order, same code, same notification.
    anna = client.session("anna@example.com")
    booked = client.post("/api/bookings", json={"type": "family", "start": "11:00"}, headers=anna).json()
    assert booked["machine"] == "M5", booked
    answer = trigger(client, 5)
    assert answer["reassigned"], answer
    assert answer["reassigned"][0]["machine"] == "M6" and answer["reassigned"][0]["start"] == "11:00", answer
    # The customer's own report path answers the same shape from the same core.
    bob = client.session("bob@example.com")
    other = client.post("/api/bookings", json={"type": "quick", "start": "12:00"}, headers=bob).json()
    claim = client.post(f"/api/machines/{other['machine']}/report", json={"kind": "fault"}, headers=bob)
    assert claim.status_code == 202 and claim.json()["outcome"] == "maintenance", claim.text
    assert claim.json()["incident"] == faults.incident_kind(faults.CLAIM) == "fault"
    assert claim.json()["kept"], "the claim keeps the record it is read against; the trigger has none"
    # A refusal on the trigger path writes nothing, exactly as a refusal on the panel path.
    carl = client.session("carl@example.com")
    refused = client.post(TRIGGER_PATH, json={"machine": 1}, headers=carl)
    assert refused.status_code == 403 and refused.json() == backend.entitlements.panel_refusal(), refused.text
    assert state_of(client, 1) == "available", "a refusal writes nothing"
    assert len(fault_incidents(client, "M1")) == 0
    # A caller with no session has no identity to be entitled with; what it has is the switch, and AC5 asks for
    # the reviewer to reach the trigger without a sign-in between the two commands.
    owner = client.session(seed["owner_email"])
    assert client.post(TRIGGER_PATH, json={"machine": 1}, headers=owner).status_code == 202
    assert state_of(client, 1) == "maintenance"
    assert client.post(TRIGGER_PATH, json={"machine": "M99"}, headers=owner).status_code == 404
    # A token that does not resolve is not an identity: the trigger answers it as the panel answers it, 401.
    assert client.post(TRIGGER_PATH, json={"machine": 2},
                       headers={"Authorization": "Bearer not-a-session"}).status_code == 401
    assert state_of(client, 2) == "available"


# --- AC3 and AC4: the seed, read back as data -------------------------------------------------------

def test_the_seed_is_the_pack_s_inventory_written_from_configuration(client, seed):
    assert seed["machines"] == 8 and seed["types"] == {"standard": 4, "family": 2, "quick": 2}
    assert seed["cycle_minutes"] == {"standard": 60, "family": 75, "quick": 30}
    assert seed["tokens_required"] == {"standard": 4, "family": 6, "quick": 3}
    assert seed["opening_hours"] == {"open": "07:00", "close": "22:00"}
    assert seed["closed_days"] == ["Sunday"]
    assert seed["buffers"] == {"turnover_minutes": 10, "cleaning_minutes": 30}
    # The seed read over HTTP is the same data the reviewer's health check reads (docs/deployment.md).
    config = client.get("/api/availability").json()["config"]
    assert config["machines"] == 8 and config["types"] == seed["types"]
    assert config["opening_hours"] == {"open": "07:00", "close": "22:00"}
    assert config["turnover_buffer_minutes"] == 10 and config["cleaning_buffer_minutes"] == 30


def test_running_the_seed_twice_gives_the_same_inventory_and_no_duplicates(client, seed):
    before = sorted(row["code"] for row in client.db.rows("SELECT code FROM machines"))
    settings = dict(client.app.repo.settings())
    client.app.repo.seed()
    client.app.repo.seed()
    assert sorted(row["code"] for row in client.db.rows("SELECT code FROM machines")) == before
    assert len(before) == 8 and len(set(before)) == 8, before
    assert client.app.repo.machine_counts() == SEED["types"]
    assert client.app.repo.settings() == settings
    # The codes the seed writes are the ones the number is read off: M1-M4 standard, M5-M6 family, M7-M8 quick,
    # in the order `src/config.py` lists the types, each one `available` before anything is reported.
    rows = client.app.repo.machines()
    assert [row["code"] for row in rows] == [f"M{n}" for n in range(1, 9)], rows
    assert [row["type"] for row in rows] == ["standard"] * 4 + ["family"] * 2 + ["quick"] * 2, rows
    assert all(row["state"] == "available" for row in rows), rows


# --- AC5: the reviewer's two commands --------------------------------------------------------------

def test_the_chain_is_reproducible_with_one_read_and_one_call_and_no_session(client, seed):
    # Command 1 is the start, read as the health check the deployment doc names: the seed is read from the
    # database, so the 200 is the process, the layer and the inventory.
    start = client.get("/api/availability")
    assert start.status_code == 200 and start.json()["config"]["machines"] == 8, start.text
    # Command 2 is the trigger call, with no sign-in between the two.
    answer = trigger(client, 3)
    assert state_of(client, 3) == "maintenance"
    incidents = client.get("/api/incidents").json()
    assert [row["kind"] for row in incidents] == ["fault"], incidents
    # The observer's read carries no customer: the incident names the machine, not the identity behind it.
    assert all("email" not in row for row in incidents), incidents
    entries = client.get("/api/logs/recent").json()["entries"]
    lines = [entry for entry in entries if entry["event"] == "owner_trigger"]
    assert len(lines) == 1 and lines[0]["status"] == 202, entries
    # The honest half of the chain: nothing alerts in this repository, so this demo earns the instrumentation
    # and the incident, not the page-out (`docs/deployment.md`).
    assert not [entry for entry in entries if entry["event"] == "alert"], entries
    assert not [name for name in dir(backend) if "alert" in name.lower()]


def test_the_trigger_path_is_a_pattern_and_the_contract_stays_the_contract(client, seed):
    assert sorted(f"{method} {path}" for method, path in backend.ROUTES) == sorted(SEAM_PATHS)
    assert backend.OWNER_TRIGGERS == ("faults",) and backend.TRIGGER_WRITE == "trigger"
    assert client.post(TRIGGER_PATH, json={"machine": 3}).status_code == 202
    assert client.post("/api/owner/faults", json={"machine": 3}).status_code == 404
