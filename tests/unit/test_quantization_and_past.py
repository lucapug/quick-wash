"""The two pure facts issue #45 (slice a of #11) adds to the time helper: the quantisation and the past.

Unit test only, no repository and no clock object (docs/spec.md, Testing Decisions): the quantisation is
data in, data out, and so is the past, because `now` is an argument here rather than a clock the test
has to mock. What the seam does with them — the 422 and the booked slot — is asserted at the HTTP
boundary, in tests/integration/test_booking_creation_happy_path.py.
"""

from datetime import date, datetime

from src.domain import time as start_times
from src.domain.time import in_the_past, parse_requested, quantize

MONDAY = date(2026, 11, 9)


def hhmm(moment) -> str:
    return moment.strftime("%H:%M")


def test_a_request_between_two_grid_points_is_quantised_up_to_the_next_one():
    # AC1: 14:07 books 14:15. Up, never down: the customer cannot be given a slot that has already
    # partly passed, so the rounding goes forward even when the nearest grid point is the previous one.
    assert hhmm(quantize(parse_requested("14:07", MONDAY))) == "14:15"
    assert hhmm(quantize(parse_requested("14:01", MONDAY))) == "14:15"
    assert hhmm(quantize(parse_requested("14:20", MONDAY))) == "14:30"


def test_quantization_is_measured_from_the_same_origin_the_grid_is_anchored_at():
    # The grid runs from opening time, not from the top of the hour: 07:07 belongs to the 07:00 grid
    # point's cell, so it rounds up to 07:15. The helper and the booking handler read one definition.
    quantised = quantize(parse_requested("07:07", MONDAY))
    assert hhmm(quantised) == "07:15"
    assert start_times.on_grid(quantised)
    assert quantize(quantised) == quantised  # a grid point is already quantised: nothing to adjust


def test_a_slot_that_has_already_begun_is_in_the_past_and_an_earlier_slot_also_is():
    now = datetime(2026, 11, 12, 9, 0)
    # AC3, inclusive on the current moment: at 09:00 the 09:00 slot is already under way, so the
    # customer cannot be booked into it. The first slot that can still be taken is the next one.
    assert in_the_past(parse_requested("09:00", now.date()), now)
    assert in_the_past(parse_requested("08:45", now.date()), now)
    assert not in_the_past(parse_requested("09:15", now.date()), now)
