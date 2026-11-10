"""Unit tests: restricted to the three pure helpers docs/spec.md names.

Start times per type, the grace window of a booking, the no-show counter and its block expiry.
No repository, no clock object, no mock: these are the only pieces a unit test is allowed to
reach — everything else is asserted through the HTTP seam.
"""

import pathlib
from datetime import date, datetime, timedelta

from src import rules
from src.config import SEED

THURSDAY = date(2026, 11, 12)
SUNDAY = date(2026, 11, 15)


# --- 1. valid start times per type (R1, R2) --------------------------------

def test_last_valid_start_per_type_is_set_by_the_cycle_not_by_a_fixed_grid():
    last = {t: rules.valid_start_times(t, SEED, THURSDAY)[-1] for t in ("quick", "standard", "family")}
    assert last["quick"] == datetime(2026, 11, 12, 21, 30)
    assert last["standard"] == datetime(2026, 11, 12, 21, 00)
    assert last["family"] == datetime(2026, 11, 12, 20, 45)


def test_no_start_is_offered_that_the_shop_cannot_honour_before_closing():
    for type_key, tariff in SEED["tariffs"].items():
        for start in rules.valid_start_times(type_key, SEED, THURSDAY):
            assert start.time() >= datetime.strptime(SEED["opening_hours"]["open"], "%H:%M").time()
            assert start + timedelta(minutes=tariff["cycle_minutes"]) <= datetime(2026, 11, 12, 22, 0)


def test_starts_are_on_the_fifteen_minute_grid_from_opening_time():
    starts = rules.valid_start_times("standard", SEED, THURSDAY)
    assert starts[0] == datetime(2026, 11, 12, 7, 0)
    assert all((start - starts[0]).seconds % (15 * 60) == 0 for start in starts)


def test_a_closed_day_offers_no_start_at_all():
    assert rules.valid_start_times("quick", SEED, SUNDAY) == []


# --- 2. the grace window of a booking (R3) ---------------------------------

def test_the_grace_window_is_ten_minutes_either_side_of_the_start():
    start = datetime(2026, 11, 12, 10, 0)
    window = rules.grace_window(start, SEED)
    assert window == (datetime(2026, 11, 12, 9, 50), datetime(2026, 11, 12, 10, 10))


# --- 3. the no-show counter and its block expiry (R9) ----------------------

def test_one_no_show_in_the_window_does_not_block():
    assert rules.no_show_block([date(2026, 11, 1)], THURSDAY, SEED) is None


def test_two_no_shows_in_thirty_days_block_for_seven_days():
    blocked_until = rules.no_show_block([date(2026, 10, 20), date(2026, 11, 5)], THURSDAY, SEED)
    assert blocked_until == date(2026, 11, 19)


def test_no_shows_outside_the_thirty_day_window_do_not_count():
    assert rules.no_show_block([date(2026, 10, 1), date(2026, 11, 5)], THURSDAY, SEED) is None


# --- the seam discipline ----------------------------------------------------

def test_unit_tests_never_mock_the_repository_or_the_clock():
    tests = pathlib.Path(__file__).resolve().parent
    forbidden = ["unittest.mock", "MagicMock", "mock.", "fakesession", "fake_repository"]
    offenders = {}
    for path in tests.glob("*.py"):
        if path.name == pathlib.Path(__file__).resolve().name:
            continue  # the rule text itself
        text = path.read_text(encoding="utf-8").lower()
        hits = [marker.lower() for marker in forbidden if marker.lower() in text]
        if hits:
            offenders[path.name] = hits
    assert not offenders, offenders
