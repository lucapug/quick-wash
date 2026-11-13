"""The three pure helpers a unit test is allowed to cover.

docs/spec.md (Testing Decisions) reserves unit tests for exactly these three pure pieces:
valid start times per type, the grace window of a booking, the no-show counter and its block
expiry. Anything else that would need the repository or the clock is asserted through the HTTP
seam instead. No I/O here, no database, no clock object: inputs and outputs are data.

The first of the three lives in src/domain/time.py, where the grid, the refusal vocabulary and the
next valid alternatives are defined (issue R1+R2). This module delegates to it so the grid has one
source: the unit test for the helper and the booking handler read the same function.
"""

from datetime import date, datetime, timedelta

from src.config import SEED
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


def no_show_block(no_shows: list[date], today: date, config: dict = SEED) -> date | None:
    """Block expiry date when the no-show counter reaches the threshold (R9).

    `no_shows` are the dates the customer failed to honour a turn (`idle_open` counts as a
    no-show). Two inside the rolling window block new bookings for `block_days`.
    """
    window = timedelta(days=config["no_show_window_days"])
    inside = [day for day in no_shows if today - day <= window]
    if len(inside) < config["no_show_threshold"]:
        return None
    return today + timedelta(days=config["block_days"])
