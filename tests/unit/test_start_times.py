from datetime import date

from src.domain.time import last_start, next_valid_starts

def test_last_start_per_type_follows_real_duration():
    monday = date(2026, 11, 9)
    assert last_start(monday, "quick") == "21:30"      # 30 min
    assert last_start(monday, "standard") == "21:00"   # 60 min
    assert last_start(monday, "family") == "20:45"     # 75 min

def test_family_overrunning_closing_is_refused_with_the_next_valid_slot():
    monday = date(2026, 11, 9)
    refused = next_valid_starts(monday, "family", requested="21:00")
    assert refused["reason"] == "would_overrun_closing"
    assert refused["alternatives"][0] == "2026-11-10T07:00"  # next open day, earliest first

def test_grid_is_anchored_at_opening_and_sunday_is_closed():
    assert next_valid_starts(date(2026, 11, 9), "quick", requested="07:07")["alternatives"][0] == "07:15"
    assert next_valid_starts(date(2026, 11, 8), "quick", requested="10:00")["reason"] == "closed_day"
