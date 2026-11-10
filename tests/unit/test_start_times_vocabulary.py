"""The fixed vocabulary of refusals and the order of the alternatives (issue R1+R2, AC4, AC6).

Pure helper only: no repository, no clock object, no mock — that is the seam discipline
(docs/spec.md, Testing Decisions). What the response adds on top of the helper is asserted at the
HTTP seam, in tests/integration/test_refused_starts_are_named_at_the_seam.py.
"""

from datetime import date

from src.domain import time as start_times
from src.domain.time import REFUSAL_REASONS, last_start, next_valid_starts, refusal_reason

MONDAY = date(2026, 11, 9)
SUNDAY = date(2026, 11, 8)


def test_the_fixed_vocabulary_is_exactly_the_three_ac4_reasons():
    assert REFUSAL_REASONS == ("outside_opening_hours", "closed_day", "would_overrun_closing")
    assert refusal_reason(MONDAY, "quick", start_times.parse_requested("22:30", MONDAY)) == \
        "outside_opening_hours"
    assert refusal_reason(SUNDAY, "quick", start_times.parse_requested("10:00", SUNDAY)) == "closed_day"
    assert refusal_reason(MONDAY, "family", start_times.parse_requested("21:00", MONDAY)) == \
        "would_overrun_closing"


def test_a_start_one_grid_step_past_the_last_honourable_slot_is_refused_by_the_cycle():
    for type_key, late in (("quick", "21:45"), ("standard", "21:15"), ("family", "21:00")):
        assert refusal_reason(MONDAY, type_key, start_times.parse_requested(late, MONDAY)) == \
            "would_overrun_closing"
        # The grid is anchored at 07:00, so the last slot is the last grid point that still fits.
        last = start_times.valid_start_times(MONDAY, type_key)[-1]
        assert last_start(MONDAY, type_key) == last.strftime("%H:%M")


def test_the_grid_starts_at_opening_time_and_keeps_to_it():
    starts = start_times.valid_start_times(MONDAY, "quick")
    assert starts[0].strftime("%H:%M") == "07:00"
    assert all(start_times.on_grid(start) for start in starts)
    assert start_times.valid_start_times(SUNDAY, "quick") == []  # a closed day offers nothing


def test_alternatives_are_ascending_earliest_first_and_cross_to_the_next_open_day():
    answer = next_valid_starts(SUNDAY, "standard", requested="18:00")
    assert answer["reason"] == "closed_day"
    assert answer["alternatives"][:1] == ["2026-11-09T07:00"]

    # A slot the shop can still honour keeps the day, then hands over to the next open day.
    answer = next_valid_starts(MONDAY, "family", requested="20:30")
    assert answer["reason"] is None
    assert answer["alternatives"][:2] == ["20:45", "2026-11-10T07:00"]

    # Same-day alternatives read as hours, another day reads as a date: the day change is visible.
    answer = next_valid_starts(MONDAY, "quick", requested="07:07")
    assert answer["on_grid"] is False and answer["refused"] is True
    assert answer["alternatives"][:2] == ["07:15", "07:30"]
