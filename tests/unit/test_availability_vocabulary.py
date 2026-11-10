"""The fixed vocabulary of the public availability view (issue #8, AC4, AC5).

Pure data only: no repository, no clock object, no mock — the seam discipline (docs/spec.md, Testing
Decisions). What needs the machine states is asserted at the HTTP seam, in
tests/integration/test_availability_reasons.py.

The decision recorded in the issue is the point here: the overrun is evaluated on the type's duration,
not on a generic cap, because R1 makes duration type-specific and one cap would name the wrong reason
for `family` at 21:00.
"""

from datetime import date, datetime

from src import availability
from src.config import SEED

MONDAY = date(2026, 11, 9)
SUNDAY = date(2026, 11, 8)


def test_the_vocabulary_is_exactly_the_seven_words_of_ac5():
    assert availability.REASONS == ("all_machines_busy", "machine_in_maintenance",
                                    "would_overrun_closing", "closed_day", "outside_opening_hours",
                                    "turnover_buffer", "cleaning_buffer")
    # The three calendar words are the same set the pure helper defines: one vocabulary, two halves.
    assert set(availability.REASONS) >= set(availability.BUFFER_REASON.values())
    assert availability.BUFFER_REASON["turnover_buffer_minutes"] == "turnover_buffer"
    assert availability.BUFFER_REASON["cleaning_buffer_minutes"] == "cleaning_buffer"


def test_the_overrun_is_measured_on_the_type_duration_not_on_a_cap():
    # A generic cap would answer `family` at 21:00 with the wrong reason; the type's own duration does.
    assert availability.calendar_reason("family", datetime(2026, 11, 9, 21, 0)) == "would_overrun_closing"
    assert availability.calendar_reason("standard", datetime(2026, 11, 9, 21, 15)) == "would_overrun_closing"
    assert availability.calendar_reason("quick", datetime(2026, 11, 9, 21, 30)) is None

    assert availability.calendar_reason("quick", datetime(2026, 11, 9, 23, 30)) == "outside_opening_hours"
    assert availability.calendar_reason("quick", datetime(2026, 11, 8, 10, 0)) == "closed_day"


def test_the_calendar_cause_is_read_before_the_machine_cause():
    # A data row, not a mock: the machine is inside its turnover buffer and the day is past closing.
    finished = {"id": 1, "code": "M1", "type": "quick", "state": "finished",
                "changed_at": "2026-11-09T21:30:00"}
    none = {1: set()}
    # Inside the buffer and inside the cycle the type can still honour, the buffer names the reason.
    assert availability.point_reason("quick", [finished], datetime(2026, 11, 9, 21, 30), SEED, none) == \
        "turnover_buffer"
    # The buffer still covers the machine, but the cycle no longer fits: the calendar answers first.
    assert availability.point_reason("quick", [finished], datetime(2026, 11, 9, 21, 35), SEED, none) == \
        "would_overrun_closing"


def test_a_reason_is_a_statement_about_the_type_not_about_one_machine():
    # One machine in maintenance and one free: the type can still give a machine, so no reason.
    maintenance = {"id": 1, "code": "M1", "type": "quick", "state": "maintenance",
                   "changed_at": "2026-11-09T10:00:00"}
    free = {"id": 2, "code": "M2", "type": "quick", "state": "available",
           "changed_at": "2026-11-09T10:00:00"}
    slot = datetime(2026, 11, 9, 10, 0)
    assert availability.point_reason("quick", [maintenance, free], slot, SEED, {1: set(), 2: set()}) is None
    # Only when every machine of the type is in the same condition does the type carry that reason.
    assert availability.point_reason("quick", [maintenance], slot, SEED, {1: set()}) == \
        "machine_in_maintenance"
    # Mixed causes are answered with the type-level phrase, never with a machine name.
    busy = {"id": 3, "code": "M3", "type": "quick", "state": "available",
           "changed_at": "2026-11-09T10:00:00"}
    assert availability.point_reason("quick", [maintenance, busy], slot, SEED,
                                     {1: set(), 3: {slot}}) == "all_machines_busy"
