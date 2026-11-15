"""R11: the per-customer daily limit — the decisions, in one place.

Two decisions issue #21 records, written once here so the seam, the customer's view and the refusal read
the same thing:

1. **the day is the local shop day** (`Europe/Rome`, held as configuration like every other number),
   resetting at 00:00 local, because the shop runs on local hours (07:00-22:00, closed Sunday). A UTC day
   would reset in the middle of a shop evening: a turn taken at 23:30 local on 12 November belongs to the
   12th, and a UTC reading would have already moved it to the 13th and handed the customer a new allowance
   while she was still standing in the shop.
2. **the count is the bookings created today, not the bookings active today**, because R11 says
   "independent of overlap": a customer holding two slots must be refused even when both slots are already
   in the past of the day. So the day is read on the moment the booking was created, and a booking made
   today for a slot tomorrow consumes today - which is also the reading that makes the reset an instant the
   customer can act on rather than a sum of active turns.

Cancelled bookings do not count (AC4): there is no money in this product, so the refund is the right to
rebook, and a turn given back gives its seat back. That is also what makes R8's uncoverable cancellation
(issue #19, AC3) real on the read as well as on the write - a turn the customer lost to a fault she did not
cause cannot be the turn that blocks her. A turn lost to a no-show (R9) is not a turn given back: it keeps
its seat.

**The guarantee is not in this file.** The seat is what the request computes from the state as it read it,
and a stale reading can name a seat another request already holds; what decides is the UNIQUE
`(email, day, seat)` index in `src/repository.py`, the same pattern R5 uses for a machine and a slot
(issue #11, slice b1). A refusal writes nothing: the caller's transaction is rolled back, so the loser
leaves no row behind. `next_seat` is the pre-check the copy is built from, never the promise.

`view` is the shape the customer's own read answers with (AC3, US48: the limit and the reset visible before
any refusal happens) and `refusal` is the same shape with the word that names which rule refused. One
shape, so the view and the refusal cannot disagree about the same day.

Pure: data in, data out - no repository, no clock object, no mock (tests/unit/test_daily_limit.py).
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.config import SEED

# Both numbers are the seed's, never literals here: they are read back over HTTP (issue #5, AC7).
LIMIT_KEY = "bookings_per_day"
TIMEZONE_KEY = "timezone"

# The word the seam answers with when the day's allowance is what refused the request.
ERROR = "daily_limit"


def limit_of(config: dict = SEED) -> int:
    return int(config[LIMIT_KEY])


def zone_of(config: dict = SEED) -> ZoneInfo:
    return ZoneInfo(config[TIMEZONE_KEY])


def local_day(moment, config: dict = SEED) -> date:
    """R11's day: the shop's own day, not the UTC one.

    An aware instant is read in the configured zone. A naive one is already the shop's reading of it,
    because the clock hands the application local time (the shop has no other clock), so the two are the
    same fact read the same way: `23:30 on 12 November` belongs to the 12th even when the UTC day has
    already rolled over.
    """
    zone = zone_of(config)
    if getattr(moment, "tzinfo", None) is None:
        return moment.replace(tzinfo=zone).date()
    return moment.astimezone(zone).date()


def resets_at(day, config: dict = SEED) -> datetime:
    """The moment the day's count goes back to zero: 00:00 local on the day that follows `day`.

    Not the last minute of the day: the reset is the rollover of the shop's own day, and the copy the
    customer reads has to name an instant she can act on - the first minute of the next day, which is the
    first minute the count is hers again.
    """
    if isinstance(day, datetime):
        day = day.date()
    return datetime.combine(day, datetime.min.time()) + timedelta(days=1)


def seats(rows) -> list[int]:
    """The seats the day already holds, as the layer has them."""
    return sorted(int(row["seat"]) for row in rows)


def next_seat(taken, config: dict = SEED) -> int | None:
    """The seat this request can take: the smallest free one in 1..limit, None when the day is full.

    The smallest free one, not `count + 1`: a seat released by a cancellation is free again, so the
    ordinal a stale count would pick is not necessarily the seat the day can still give. When the day is
    full the answer is the refusal, and when the reading is stale the seat named here is the seat the
    index collides on - that collision is the guarantee (see the module docstring).
    """
    for seat in range(1, limit_of(config) + 1):
        if seat not in taken:
            return seat
    return None


def view(rows, day, config: dict = SEED) -> dict:
    """The limit as the customer reads it on her own view, before any refusal (AC3, US48).

    `used` is the count of the day's rows, the same count the index decides on: one reading, so the
    customer's list, her own view and the 409 that answers her third attempt cannot state three different
    numbers for the same day.
    """
    limit = limit_of(config)
    used = len(rows)
    reset = resets_at(day, config)
    body = {"max_per_day": limit, "used": used, "remaining": limit - used,
            "day": day.isoformat(), "timezone": config[TIMEZONE_KEY],
            "resets_at": reset.isoformat()}
    body["message"] = (f"Massimo {limit} prenotazioni al giorno: ne hai usate {used}, ne restano "
                       f"{limit - used}. Il conteggio riparte alle {reset.strftime('%H:%M')} del "
                       f"{reset.strftime('%d/%m/%Y')}")
    return body


def refusal(rows, day, config: dict = SEED) -> dict:
    """The 409 (AC2): the limit, the count used, the moment it resets.

    The same shape as the view, plus the word that names which rule refused, and the copy in Italian
    because it is the customer's interface. `limit` is the same number as `max_per_day`, spelled the way
    the refusal has always spelled it.
    """
    body = dict(view(rows, day, config))
    reset = resets_at(day, config)
    body["error"] = ERROR
    body["limit"] = body["max_per_day"]
    body["message"] = (f"Massimo {body['max_per_day']} prenotazioni al giorno: ne hai già {body['used']}. "
                       f"Il conteggio riparte alle {reset.strftime('%H:%M')} del {reset.strftime('%d/%m/%Y')}")
    return body
