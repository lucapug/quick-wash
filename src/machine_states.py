"""The machine state machine as data: the single table R6 asks for (AC 7).

`TRANSITIONS` is the only place a hop exists in the code. Every machine-state write in src/app.py
goes through `Application.transition`, which consults this table; a hop the table does not declare
raises `InvalidTransition` and the seam answers 409 with the attempted hop in the body. The
rejection is externally observable and nothing is coerced: the machine keeps the state it had.

The table is machine-readable so the human mirror can be checked against it. `docs/machine-states.md`
is written from this table; `tests/test_machine_states.py` compares the table with the
"Machine state machine" section of `docs/spec.md` — the source the mirror is written from — so the
code and the documentation cannot drift. (Writing the mirror file itself is a docs-owner step: the
executor's scope is `src/` and `tests/`, and `tests/test_context_files.py` closes `docs/` to the
pack plus the record, the team spec and the tracker until the root index gains a line for it.)

Two names are deliberately absent from `STATES`:

- `idle_open` is an **event**, not a state: `unlocked` with no `cycle_started` inside 15 minutes
  closes the booking, releases the machine (`unlocked → available`) and records an incident.
- `expired` is a terminal state of a **booking**, never of a machine. A booking that expires leaves
  its machine `available`.

The invariant R6 and the device boundary share (issue #13): a hop exists only when the device reported the
fact it names. `cycle_finished` is declared from `running` alone, because the machine got there on a
`cycle_started` report. A report that names the end of a cycle the device never saw begin is not a fact, it
is an assumption, and the table refuses it — the refusal, not a coercion, is what `AC 6` asks for.
"""

from datetime import timedelta

STATES = ("available", "reserved", "unlocked", "running", "finished", "cleaning_required", "maintenance")

# AC 1: the happy path, exactly one hop per HTTP call on the seam.
HAPPY_PATH = ("available", "reserved", "unlocked", "running", "finished", "available")

SEAM_CALL = {
    ("available", "reserved"): "POST /api/bookings",
    ("reserved", "unlocked"): "POST /api/lock/redeem",
    ("unlocked", "running"): "POST /api/lock/reports event=cycle_started",
    ("running", "finished"): "POST /api/lock/reports event=cycle_finished",
    ("finished", "available"): "the turnover buffer elapses (R10), read back on GET /api/machines/{machine}",
}

TRANSITIONS = {
    "available": {"reserved", "maintenance"},
    # `cleaning_required` from `reserved` is R10's branch, the one extension to the spec's declared
    # source: the customer the machine is assigned to reports it as still full of the previous
    # cycle's laundry. The mirror documents the branch; `R10_ENTRY` keeps it machine-readable.
    "reserved": {"unlocked", "available", "maintenance", "cleaning_required"},
    # `available` here is the `idle_open` release: the event is not a state, so its effect is the
    # declared hop out of `unlocked`.
    # `finished` is not declared from here. The device decides when a cycle ends (issue #15), but it can
    # only name the end of a cycle it named the start of: the seam reacts to what the device actually
    # reported, so a report that jumps from the open straight to the end is refused with 409 and writes
    # nothing (issue #13, AC3, `tests/integration/test_device_reports_coverage.py`). The hop R10 measures
    # its turnover buffer from is the one `running -> finished` declares.
    "unlocked": {"running", "available", "maintenance"},
    # AC 6: `running → available` is not declared — a cycle must pass through `finished`.
    "running": {"finished"},
    "finished": {"available", "cleaning_required", "maintenance"},
    # AC 2: `maintenance` is reachable only from `available`, `reserved`, `unlocked`, `finished`. A
    # machine already out of circulation for cleaning is not a second way into maintenance, so this
    # row declares only the buffer hop back to `available`.
    "cleaning_required": {"available"},
    # AC 2: the sources of `maintenance` are exactly the four states the spec lists.
    "maintenance": {"available"},
}

R10_ENTRY = {"reserved"}

# The buffers that carry a machine back to `available`. They are seed numbers, not constants: the
# addendum (patch 2) signs turnover 10 and cleaning 30, held in src/config.py as configuration.
BUFFER_HOPS = {
    "finished": "turnover_buffer_minutes",
    "cleaning_required": "cleaning_buffer_minutes",
}

# US35 repeat behaviour (addendum patch 2): a still-occupied report that lands on a machine already in
# `cleaning_required` is accepted and the window restarts from the moment it arrives. It is not a hop —
# the state stands and the buffer is measured again — so `TRANSITIONS` declares no self-entry for it and
# the seam never coerces a transition that the table does not hold.
REPEAT_REPORT = {"state": "cleaning_required", "restarts": "cleaning_buffer_minutes"}

# Device reports: the event the controller sends, and the state it is allowed to cause.
DEVICE_EVENTS = {
    "cycle_started": "running",
    "cycle_finished": "finished",
    "occupied": "cleaning_required",
    "fault": "maintenance",
    "idle_open": "available",   # an event, not a state: it releases the machine
}

# States a booking can end in. `expired` is one of them and never a machine state.
BOOKING_STATES = ("confirmed", "unlocked", "running", "finished", "closed", "cancelled", "expired")
BOOKING_TERMINAL_STATES = ("closed", "cancelled", "expired")

# The booking states that still hold a turn on a machine. One set, read by two things that must not
# disagree: the public view answers `free` on its complement (issue #8, AC7), and the persistence layer
# enforces R5 on it — the slot is unique among the bookings that still hold a turn. A booking in
# `cancelled` has given its turn back rather than lost it, so the same machine and the same slot are
# bookable again at once (issue #15, AC3): that is why the index is scoped to this set and not to the
# whole table, and it is still the layer deciding, never a pre-check.
HOLDING_STATES = ("confirmed", "unlocked", "running")

# The names that must never appear as a machine state.
NOT_STATES = ("idle_open", "expired")


def idle_open_due(opened_at, now, config: dict, cycle_started=None) -> bool:
    """The 15-minute bound, in one predicate, read by both sides of the device boundary.

    The seam evaluates it on every request that reads a machine (issue #13's Decision: the rule is
    evaluated at report time and at every read, from the recorded open) and the simulator reads the same
    function, so the bound cannot be reached twice — once by the device and once by the read. An open that
    already has a cycle started is not an idle open, and an open that is not recorded is not an open at all.

    Inclusive on the bound, the way R3 and R10 measure theirs: the fifteenth minute is the minute the event
    fires.
    """
    if opened_at is None or cycle_started is not None:
        return False
    return (now - opened_at) >= timedelta(minutes=config["idle_open_minutes"])


def declares(current: str, to: str) -> bool:
    """True when the table declares this hop. This is the whole of R6 in one line."""
    return to in TRANSITIONS.get(current, set())


def sources_of(state: str) -> set:
    """The states this state can be reached from, read out of the table."""
    return {current for current, hops in TRANSITIONS.items() if state in hops}


def attempted_target(event: str) -> str | None:
    """The state an event name implies, so a rejected report can be answered with the hop it tried.

    `cycle_finished_available` says the caller wanted `available`; the table does not declare that
    hop from `running`, so the answer is the attempted transition, not a coercion.
    """
    for token in reversed(str(event).split("_")):
        if token in STATES:
            return token
    return None


def table_view(config: dict) -> dict:
    """The table as it is written in the mirror: one line per state, buffers as the seed numbers."""
    return {
        "states": list(STATES),
        "happy_path": list(HAPPY_PATH),
        "transitions": {state: sorted(hops) for state, hops in TRANSITIONS.items()},
        "sources": {state: sorted(sources_of(state)) for state in STATES},
        "buffers": {state: config[key] for state, key in BUFFER_HOPS.items()},
        "events": dict(DEVICE_EVENTS),
        "not_states": list(NOT_STATES),
    }
