"""The answer a refusal is made of: the bounded set of slots the customer can actually take.

Issue #48 (slice c of #11) is the shape of the answer the loser of a race gets, on the path the
persistence layer decided (`error: slot_taken`, `enforced_by: persistence layer`). Everything it states is a
decision that already exists in this codebase, read together in one place:

1. **bounded** — at most `rules.LOSER_ALTERNATIVES` (3), the number `src/rules.py` holds for the loser path,
   so the assertion does not depend on shop load;
2. **earliest first** — ascending, the order `src/domain/time.py` already answers in (AC6 of issue R1+R2),
   crossing to the next open day when the day is exhausted;
3. **from the same type, on the grid** — the slots are grid points of the type the request asked for, taken
   from `valid_start_times`, so every one of them is a point the shop can honour (R1, R2, AC1 of slice a);
4. **actually bookable** (AC2) — a slot is listed only when a machine of the type can be assigned for it at
   that moment: `src/availability.py` is the single predicate the assignment step and the public view both
   answer on, so a machine in `maintenance` (R7, US42), a machine inside its turnover or cleaning buffer
   (R10, addendum patch 2) and a machine already committed for that slot are never listed. A refusal that
   names a slot it cannot give is not a polite refusal, it is a promise the shop cannot keep.

Two things the filter respects because AC2 asks for them as an outcome, not as a shape:

- **`remaining`** — R11 caps a customer at `bookings_per_day` bookings per day, so a slot that would put her
  over the limit is not bookable *for her*. The count is `min(LOSER_ALTERNATIVES, remaining)`: the smaller of
  the bound and what she can still take that day.
- **the bound is a ceiling, not a quota.** A machine holds the slot it is given, so the set lists at most one
  slot per machine of the type it can name — on the pack's inventory (2 `quick` machines, `tests/conftest.py`)
  that is 2 before the bound of 3, and one of those two is already committed for the slot the refusal is
  about. That is exactly why the Decision bounded the count instead of letting the assertion depend on shop
  load; the count is read on a pack big enough for it in
  `tests/integration/test_refusal_alternatives_ux_coverage.py`.

The shape on the wire is the record the UI of issue #22 reads: one entry per alternative, `start` and `type`.
It is scoped to the loser path. The calendar and no-machine refusals keep the slot strings the tests of
issues R1+R2 and #11 (slice b2) pin (`alternatives[0] == "2026-11-13T07:00"`, `point in grid`,
`sorted(alternatives)`), so one key has two shapes depending on which refusal answered — the tension is
recorded, not hidden, in `tests/integration/test_refusal_alternatives_ux_coverage.py`.

What this module cannot do is decide the race. The test issue #48 supplies asks for a `409` on a second
request for a slot the shop can still serve on another machine of the type, which R5 refuses only on the same
machine; the file is recorded as unpassable in that test's coverage file and marked `xfail` in
`tests/fixtures.py`. Nothing here is bent to make it pass.
"""

from datetime import timedelta

from src import availability, rules
from src.domain import time as start_times


def machines_of_type(repo, type_key: str) -> list[dict]:
    """Every machine of the type, not only the ones the assignment step could pick right now."""
    return [row for row in repo.machines() if row["type"] == type_key]


def bookable_at(machine, moment, config: dict, taken: dict) -> bool:
    """AC2: is this machine able to serve the turn that starts at `moment`.

    This is `availability.free_at`, the predicate `Application.is_assignable` and the public window both
    answer on (issue #8): no second definition of "free", so a slot cannot be listed as valid by one reading
    and refused by the request that tries to take it — never `maintenance` (R7, US42), never inside a buffer
    (R10, addendum patch 2), never a point the machine already owes a turn for.
    """
    return availability.free_at(machine, moment, config, taken)


def takeable(repo, config: dict, type_key: str, reference, now, remaining: int | None = None,
            limit: int = rules.LOSER_ALTERNATIVES) -> list[dict]:
    """The bounded set, earliest first, as the UI reads it: one record per alternative.

    Strictly later than the slot the customer was refused for (that slot is what the refusal is about), never
    in the past relative to `now` (AC3 of slice a refuses a slot already begun), grid points of `type_key`
    that a machine of the type is free for, at most `min(limit, remaining)`.
    """
    cap = limit if remaining is None else min(limit, remaining)
    rows = machines_of_type(repo, type_key)
    taken = {machine["id"]: set(availability.taken_turns(repo, rows).get(machine["id"], set()))
             for machine in rows}
    given: set = set()            # a machine holds the slot it is given: it cannot be listed twice

    slots: list[dict] = []
    day = reference.date()
    for _ in range(start_times.LOOKAHEAD_DAYS):
        for start in start_times.valid_start_times(day, type_key, config):
            if start <= reference or start <= now:
                continue
            machine = next((row for row in rows
                            if row["id"] not in given and bookable_at(row, start, config, taken)), None)
            if machine is None:
                continue
            slots.append({"start": start_times.slot(start, reference.date()), "type": type_key})
            taken[machine["id"]].add(start)
            given.add(machine["id"])
            if len(slots) >= cap:
                return slots
        day += timedelta(days=1)
    return slots
