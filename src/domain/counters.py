"""The no-show counter and its block expiry (R9): the pure counter helper a unit test covers.

docs/spec.md (Testing Decisions) reserves unit tests for exactly three pure pieces — valid start times
per type, the grace window of a booking, the no-show counter and its block expiry — and this module is
the third. Data in, data out: no repository, no clock object, no mock. The occurrences are the fact the
repository stores (a no-show with the moment it happened), passed in as data; `now` is an argument, not
a clock the test has to mock.

The two decisions this issue records are the issue's:

1. **The window is rolling, not calendar.** Each no-show counts for `no_show_window_days` from its own
   day, so a customer cannot escape by timing the second one against a month boundary. The window is
   read on the day, not on the instant, because the window is the customer's view of the fact: a no-show
   of 1 October is still inside the window at noon on 31 October and outside it on 1 November. Measured
   as instants it would leave the window at 10:01 on 31 October, inside the very day the counter is read.
2. **The block starts at the moment the second no-show is recorded** and expires `block_days` later at
   the same local time, so the customer is shown a concrete moment (`block_expiry`), not a count of days.

`is_blocked` is the counter read at an instant: the threshold reached inside the rolling window, and the
block of that crossing not yet expired. When more occurrences than the threshold are inside the window
the block runs from the most recent one — the last crossing the customer is serving — because a block is
never extended backwards over a fact that already served its own block.

Occurrence inputs accept a date or a datetime: the repository stores a no-show as an instant
(`occurred_at`), a unit test can write a bare day, and `instant` reads both as the same fact.

The single reading this module owns is what the seam answers with. `rules.no_show_block` is the day-level
adapter tests/test_rules.py pins (the expiry counted from the day the counter is read); the two agree
whenever the counter is read at the moment of the crossing — which is what happens at the seam, because
the crossing is recorded in the request that reads it — and diverge when the crossing is in the past.
The divergence is recorded in that module, not resolved here: a pinned test cannot be adjusted and the
same rule cannot be written twice.
"""

from datetime import date, datetime, timedelta

from src.config import SEED

# AC4: the block reason the seam names. The counter, never a decision somebody takes by hand.
REASON = "no_show"


def instant(value) -> datetime:
    """A no-show as an instant. A bare day is read at midnight, so a date and a datetime are one fact."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    raise ValueError(f"a no-show is a moment, not {value!r}")


def window(occurrences, at, config: dict = SEED) -> list[datetime]:
    """The no-shows still inside the rolling window at `at`, ascending (AC7: rolling, not calendar)."""
    span = timedelta(days=config["no_show_window_days"])
    day = at.date() if isinstance(at, datetime) else at
    return sorted(instant(occurrence) for occurrence in occurrences
                  if day - instant(occurrence).date() <= span)


def block_expiry(occurrence, config: dict = SEED) -> datetime:
    """The moment the block ends: `block_days` after the no-show that crossed the threshold, same local time."""
    return instant(occurrence) + timedelta(days=config["block_days"])


def is_blocked(occurrences, now, config: dict = SEED) -> bool:
    """The counter read at `now`: threshold reached inside the rolling window, block not yet expired (AC6)."""
    inside = window(occurrences, now, config)
    if len(inside) < config["no_show_threshold"]:
        return False
    return bool(instant(now) < block_expiry(inside[-1], config))


def block_view(occurrences, now, config: dict = SEED) -> dict:
    """The block as the customer sees it: the reason, the count that caused it, the expiry, in Italian.

    The same shape answers the customer's own view (US51) and the 403 that refuses a booking attempt, so
    the copy is written once and the two cannot disagree about what the customer is blocked for or until
    when. When the counter has not crossed the threshold the same shape answers with `blocked: None` — the
    view a customer reads before booking is one shape, blocked or not.
    """
    inside = window(occurrences, now, config)
    threshold = config["no_show_threshold"]
    view = {
        "reason": REASON,
        "blocked": None,
        "no_shows": len(inside),
        "window_days": config["no_show_window_days"],
        "block_days": config["block_days"],
        "until": None,
        "expires_at": None,
    }
    if len(inside) < threshold:
        view["message"] = (f"Non sei bloccato: {len(inside)} mancate presentenze negli ultimi "
                           f"{view['window_days']} giorni, la soglia è {threshold}")
        return view
    expiry = block_expiry(inside[-1], config)
    # AC6: the block is lifted automatically on the expiry date, so at that moment the counter is read clear.
    if instant(now) >= expiry:
        view["message"] = (f"Blocco scaduto il {expiry.strftime('%d/%m/%Y')}: "
                           f"{len(inside)} mancate presentenze negli ultimi {view['window_days']} giorni")
        return view
    view["blocked"] = True
    view["until"] = expiry.date().isoformat()
    view["expires_at"] = expiry.isoformat()
    view["message"] = (f"Sei bloccato: {len(inside)} mancate presentenze negli ultimi "
                       f"{view['window_days']} giorni. Puoi prenotare di nuovo dal "
                       f"{expiry.strftime('%d/%m/%Y %H:%M')}")
    return view
