"""R11's pure half (issue #21): the shop's own day, the reset instant, and the seat the day can still give.

Unit test only, no repository and no clock object (docs/spec.md, Testing Decisions): data in, data out. The
half of R11 that is not pure — that the UNIQUE `(email, day, seat)` index and not `next_seat` is what decides
two concurrent requests, and that the count the customer reads is the count the layer wrote — cannot be
asserted here, so it is asserted at the HTTP seam in
`tests/integration/test_r11_daily_limit_coverage.py` (AC7).
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from src import daily_limit
from src.config import SEED

THURSDAY = date(2026, 11, 12)


def test_the_day_is_the_shop_s_own_day_and_not_the_utc_one():
    # The decision the issue records: 23:30 UTC on 12 November is 00:30 local on the 13th, so the UTC day has
    # already rolled over while the shop's day has not been reached. The two readings give two different days,
    # and R11 reads the shop's — the shop is open 07:00-22:00 local and closed Sunday, so a UTC day would cut
    # a shop evening in two.
    moment = datetime(2026, 11, 12, 23, 30, tzinfo=ZoneInfo("UTC"))
    assert moment.date() == THURSDAY
    assert daily_limit.local_day(moment, SEED) == date(2026, 11, 13)

    # The clock hands the application the shop's local time, so a naive instant is already the shop's own
    # reading of it: the last turn of the 12th belongs to the 12th.
    assert daily_limit.local_day(datetime(2026, 11, 12, 23, 30), SEED) == THURSDAY
    assert daily_limit.local_day(datetime(2026, 11, 13, 0, 1), SEED) == date(2026, 11, 13)


def test_the_reset_is_the_rollover_of_the_local_day_not_the_last_minute_of_it():
    reset = daily_limit.resets_at(THURSDAY, SEED)
    assert reset == datetime(2026, 11, 13, 0, 0)
    assert reset.strftime("%H:%M") == "00:00"          # the copy names an instant, never 23:59
    # The number is configuration, like every other number in this project (issue #5, AC7).
    assert SEED["timezone"] == "Europe/Rome" and SEED["bookings_per_day"] == 2


def test_the_seat_is_the_smallest_free_one_of_the_day_not_the_next_number():
    assert daily_limit.next_seat([], SEED) == 1
    assert daily_limit.next_seat([1], SEED) == 2
    # A cancelled booking gives its seat back (R4, US45): the free seat is the one the day lost, not the
    # number the count would have produced. This is what makes the refund the right to rebook at once.
    assert daily_limit.next_seat([2], SEED) == 1
    assert daily_limit.next_seat([1, 2], SEED) is None          # the day is full
    assert daily_limit.next_seat([1, 2, 3], SEED) is None       # never a seat outside the day's allowance


def test_the_view_and_the_refusal_state_the_limit_the_count_used_and_the_reset():
    rows = [{"seat": 1}, {"seat": 2}]                    # the day's rows, as data, not as a repository call
    seen = daily_limit.view(rows, THURSDAY, SEED)
    assert seen["max_per_day"] == 2 and seen["used"] == 2 and seen["remaining"] == 0
    assert seen["resets_at"] == "2026-11-13T00:00:00" and seen["timezone"] == "Europe/Rome"

    refused = daily_limit.refusal(rows, THURSDAY, SEED)
    assert refused["error"] == "daily_limit"
    assert refused["limit"] == seen["max_per_day"] and refused["used"] == seen["used"]
    assert refused["resets_at"] == seen["resets_at"]
    # One shape, so the view read before the refusal and the refusal itself cannot state two different days;
    # the interface is Italian, the keys stay English.
    for shape in (seen, refused):
        assert "2" in shape["message"] and "00:00" in shape["message"]
    assert "già 2" in refused["message"] and "riparte" in refused["message"]
