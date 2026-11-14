from datetime import datetime, timedelta

from src.domain.counters import block_expiry, is_blocked

def test_two_no_shows_in_30_days_block_for_7_days():
    first = datetime(2026, 11, 1, 10, 0)
    second = datetime(2026, 11, 20, 15, 0)
    assert is_blocked([first, second], now=datetime(2026, 11, 21)) is True
    assert block_expiry(second) == second + timedelta(days=7)   # 2026-11-27 15:00
    assert is_blocked([first, second], now=datetime(2026, 11, 27, 15, 1)) is False

def test_rolling_window_drops_the_oldest_no_show_after_30_days():
    old = datetime(2026, 10, 1, 10, 0)
    recent = datetime(2026, 10, 31, 10, 0)
    assert is_blocked([old, recent], now=datetime(2026, 10, 31, 12, 0)) is True
    assert is_blocked([old, recent], now=datetime(2026, 11, 1, 11, 0)) is False  # old left the 30-day window
