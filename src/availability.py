"""The public availability view: what a passer-by reads before deciding to walk in (US1, US2, US3, US8).

Two reads answer the same path, and each shape is pinned by the test of its own issue:

- the **board**, `GET /api/availability`: one row per machine type — the type, the inventory, the
  machines free at the earliest start, the tariff (issue R1+R2 pins this row, and `tests/test_journey.py`,
  `tests/test_machine_states.py` and `tests/integration/test_refused_starts_are_named_at_the_seam.py`
  read it);
- the **window**, `GET /api/availability?window_hours=4`: the counts per type the walk-in chooses on —
  `count`, `cycle_minutes`, `tokens_required` — and, for the type the caller names (`&type=quick`), the
  grid of start times for the window, the earliest valid start first and a reason for every gap
  (issue #8, AC1, AC3, AC4, AC5).

A JSON body cannot be a list of rows and a mapping per type at the same time, so the query decides which
one `types` is. Both reads use the same predicates below — `free_at` is the single source, and
`Application.is_assignable` delegates to it — so the board and the window cannot drift.

The rules the window pins, stated here so the code and the reviewer read the same thing:

1. `count` is the state view at the moment of the request (AC1, AC7): a machine inside its turnover
   buffer (10 min) or its cleaning buffer (30 min), a machine in maintenance and a machine held for the
   customer who booked it are not free.
2. Availability is answered for the **type**, never for a physical machine (AC2): the entry names no
   machine, no customer, no code (AC6). A reason is therefore a statement about the type — it is the
   cause that covers every machine of the type; when the machines of a type are not all in the same
   condition the answer is the type-level phrase `all_machines_busy`, the phrase the booking handler
   already uses when no machine of the type can be committed for a slot (R5).
3. A grid point the type already owes a turn for is not a point the caller can take, so it is refused
   with a reason. The grid runs from the first turn the type has committed inside the window — the first
   gap the walk-in has to be told about — and when the type has no committed turn inside the window it
   runs from the first grid point at or after `now`. It runs `window_hours` long (default 4, AC1) on the
   15-minute grid anchored at opening time (issue R1+R2), and the earliest point the type can actually
   give is listed first (AC4).
4. Only points that can finish before closing are offered, measured on **the type's own duration** (the
   decision of this issue): R1 makes duration type-specific, so one generic cap would name the wrong
   reason for a `family` cycle at 21:00. The calendar causes are read first (closed day, outside opening
   hours, overrun), then the machine causes.

The fixed vocabulary of AC5 is `REASONS`: the three calendar words are `src.domain.time.REFUSAL_REASONS`
and the four machine words are the state half. No other word is answered. Nothing here logs or returns a
customer email, an unlock code or a customer identifier, and the telemetry line stays the request path
without the query.
"""

from datetime import datetime, timedelta

from src import domain, machine_states
from src.config import SEED
from src.domain import time as start_times
from src.repository import parse

# AC5: the fixed vocabulary. Exactly these seven, and no other word is answered.
REASONS = ("all_machines_busy", "machine_in_maintenance", "would_overrun_closing", "closed_day",
           "outside_opening_hours", "turnover_buffer", "cleaning_buffer")

DEFAULT_WINDOW_HOURS = 4

# The two buffer reasons, read from the seed numbers (addendum patch 2: 10 and 30 minutes).
BUFFER_REASON = {"turnover_buffer_minutes": "turnover_buffer", "cleaning_buffer_minutes": "cleaning_buffer"}

# The states a turn can start from: `available`, and the two buffer states once the buffer has run.
OPEN_STATES = ("available", "finished", "cleaning_required")

# The states in which a booking still owes a turn to its customer, so the point is protected (R5).
HELD_BOOKING_STATES = ("confirmed", "unlocked", "running")


def hhmm(moment) -> str:
    return moment.strftime("%H:%M")


def window_hours(body: dict) -> int:
    """AC1: the window the walk-in is answered on — `now` plus the next hours."""
    try:
        return int(body.get("window_hours") or DEFAULT_WINDOW_HOURS)
    except (TypeError, ValueError):
        return DEFAULT_WINDOW_HOURS


def windowed(body: dict) -> bool:
    """The query that asks for the window rather than for the board."""
    return bool(body.get("window_hours") or body.get("type"))


def taken_turns(repo, rows) -> dict:
    """machine id -> the points that machine is already committed for, as the layer has them."""
    taken = {}
    for machine in rows:
        points = set()
        for booking in repo.bookings_on_machine(machine["id"]):
            if booking["state"] in HELD_BOOKING_STATES:
                points.add(parse(booking["start_time"]))
        taken[machine["id"]] = points
    return taken


def inside_buffer(machine, moment, config) -> str | None:
    """The buffer that still covers `moment` for this machine (R10, addendum patch 2)."""
    hop = machine_states.BUFFER_HOPS.get(machine["state"])
    if hop is not None and moment < parse(machine["changed_at"]) + timedelta(minutes=config[hop]):
        return hop
    return None


def free_at(machine, moment, config, taken) -> bool:
    """The state view (AC1, AC7): is this machine free for the turn that starts at `moment`."""
    if inside_buffer(machine, moment, config) is not None:
        return False
    if machine["state"] not in OPEN_STATES:
        return False
    return moment not in taken.get(machine["id"], set())


def machine_cause(machine, moment, config, taken) -> str | None:
    """Why this machine cannot serve the turn that starts at `moment`. None when it can."""
    if machine["state"] == "maintenance":
        return "machine_in_maintenance"
    hop = inside_buffer(machine, moment, config)
    if hop is not None:
        return BUFFER_REASON[hop]
    if moment in taken.get(machine["id"], set()):
        return "all_machines_busy"
    return None


def calendar_reason(type_key: str, moment, config: dict = SEED) -> str | None:
    """The three AC4 causes, in the order the pure helper states them, on the type's own duration."""
    day = moment.date()
    if not start_times.is_open_day(day, config):
        return "closed_day"
    if not start_times.open_at(day, config) <= moment <= start_times.close_at(day, config):
        return "outside_opening_hours"
    cycle = timedelta(minutes=domain.tariff_of(type_key, config).cycle_minutes)
    if moment + cycle > start_times.close_at(day, config):
        # The decision of this issue: the overrun is measured on the type's duration, not on a cap,
        # because a single cap would name the wrong reason for `family` at 21:00.
        return "would_overrun_closing"
    return None


def point_reason(type_key: str, rows, moment, config: dict = SEED, taken: dict | None = None) -> str | None:
    """Why the type cannot give a machine for the turn that starts at `moment`. None when it can.

    Calendar first (AC4, on the type's duration), then the point the type already owes to a customer,
    then the cause that covers every machine of the type: a reason is a statement about the type, so it
    never names one machine (AC2).
    """
    cause = calendar_reason(type_key, moment, config)
    if cause:
        return cause
    taken = taken or {}
    if any(moment in taken.get(machine["id"], set()) for machine in rows):
        return "all_machines_busy"
    causes = [machine_cause(machine, moment, config, taken) for machine in rows]
    if any(c is None for c in causes):
        return None
    named = set(causes)
    return named.pop() if len(named) == 1 else "all_machines_busy"


def grid_anchor(rows, config, now, taken, window) -> datetime:
    """Rule 3: the grid starts at the first committed turn inside the window, else at the first grid point."""
    grid = timedelta(minutes=config["grid_minutes"])
    elapsed = (now - start_times.open_at(now.date(), config)) % grid
    first = now if elapsed == timedelta(0) else now + (grid - elapsed)
    committed = sorted(moment for machine in rows for moment in taken.get(machine["id"], ())
                       if first <= moment <= first + window)
    return committed[0] if committed else first


def slot_grid(type_key: str, rows, config, now, hours, taken) -> list:
    """The window for one type: the earliest point the type can give first, then every gap with its reason."""
    grid = timedelta(minutes=config["grid_minutes"])
    window = timedelta(hours=hours)
    anchor = grid_anchor(rows, config, now, taken, window)
    points = [anchor + grid * step for step in range(int(window / grid))]
    reasons = {point: point_reason(type_key, rows, point, config, taken) for point in points}
    offered = [point for point in points if reasons[point] is None]
    refused = [point for point in points if reasons[point] is not None]
    return [{"start": hhmm(point), "available": reasons[point] is None, "reason": reasons[point]}
            for point in offered + refused]


def window_view(repo, config: dict, now, hours: int, only_type: str | None = None) -> dict:
    """AC2: per machine type, never per physical machine. Nothing here names a machine or a customer.

    The entry is the three numbers the walk-in chooses on before choosing (AC3). The grid is answered for
    the type the caller names, and for any other type only when it has a gap in the window: AC5 asks for
    a reason for every unavailable slot, and where nothing is unavailable the three numbers are the answer.
    """
    view = {}
    for type_key in repo.machine_counts():
        rows = [row for row in repo.machines() if row["type"] == type_key]
        taken = taken_turns(repo, rows)
        tariff = domain.tariff_of(type_key, config)
        entry = {"count": len([machine for machine in rows if free_at(machine, now, config, taken)]),
                 "cycle_minutes": tariff.cycle_minutes,
                 "tokens_required": tariff.tokens_required}
        grid = slot_grid(type_key, rows, config, now, hours, taken)
        if only_type == type_key or any(point["reason"] is not None for point in grid):
            entry["slots"] = grid
        view[type_key] = entry
    return view
