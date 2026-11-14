"""The three pure helpers a unit test is allowed to cover.

docs/spec.md (Testing Decisions) reserves unit tests for exactly these three pure pieces:
valid start times per type, the grace window of a booking, the no-show counter and its block
expiry. Anything else that would need the repository or the clock is asserted through the HTTP
seam instead. No I/O here, no database, no clock object: inputs and outputs are data.

The first of the three lives in src/domain/time.py, where the grid, the refusal vocabulary and the
next valid alternatives are defined (issue R1+R2). This module delegates to it so the grid has one
source: the unit test for the helper and the booking handler read the same function. The third lives in
src/domain/counters.py, which owns the rolling window and the instant-level block expiry the issue
records; `no_show_block` below is the day-level adapter the unit test of issue #18 pins and it delegates
the window to that module, so the two cannot disagree about which facts are inside the window.
"""

from datetime import date, datetime, timedelta

from src.config import SEED
from src.domain import counters
from src.domain import time as start_times

# R5, the loser's answer (the decision #47 preserves): the persistence refusal carries a bounded set of
# alternatives, at most three, so the customer can fix it in one tap. The bound is the loser path's, not
# the general look-ahead of `src/domain/time.py`: the refusal the layer answers is the one that has to be
# short enough to read at the machine.
LOSER_ALTERNATIVES = 3


def valid_start_times(type_key: str, config: dict = SEED, day: date | None = None) -> list[datetime]:
    """Every grid start time on `day` that a cycle of `type_key` can actually honour (R1, R2).

    A start is valid when it is inside opening hours, on an open day, on the 15-minute grid
    anchored at opening time, and `start + cycle_minutes` does not overrun closing time.
    """
    if day is None:
        raise ValueError("valid_start_times needs a day")
    return start_times.valid_start_times(day, type_key, config)


def grace_window(start: datetime, config: dict = SEED) -> tuple[datetime, datetime]:
    """The window in which the unlock code works: 10 minutes before start to 10 after (R3)."""
    grace = timedelta(minutes=config["grace_minutes"])
    return start - grace, start + grace


def in_window(now: datetime, window: tuple[datetime, datetime], config: dict = SEED) -> bool:
    """R3 with both bounds inclusive: the window is `[from, to]`, and an instant on either bound is inside.

    Inclusive is what the rule says and what the test asserts — the code works at the tenth minute before
    start and at the tenth minute after it. One predicate, so the redemption and the read of a booking
    answer on the same boundary and cannot drift.
    """
    return window[0] <= now <= window[1]


def no_show_block(no_shows: list[date], today: date, config: dict = SEED) -> date | None:
    """Block expiry date when the no-show counter reaches the threshold (R9).

    `no_shows` are the dates the customer failed to honour a turn (`idle_open` counts as a
    no-show). Two inside the rolling window block new bookings for `block_days`.

    This is the day-level adapter tests/test_rules.py pins: the expiry counted from the day the counter is
    read. The seam reads `src/domain/counters.py`, which owns the instant-level reading the issue records
    (the block runs from the moment of the crossing and expires at the same local time). The two agree
    whenever the counter is read at the moment of the crossing — which is what happens at the seam, since
    the crossing is written by the request that reads it — and diverge when the crossing is in the past.
    The divergence is recorded here rather than resolved: a pinned test cannot be adjusted, and the same
    rule cannot be written twice. The rolling window itself has one source — `counters.window` — so the
    adapter and the counter cannot disagree about which facts are inside it.
    """
    inside = counters.window(no_shows, today, config)
    if len(inside) < config["no_show_threshold"]:
        return None
    return counters.instant(today).date() + timedelta(days=config["block_days"])
