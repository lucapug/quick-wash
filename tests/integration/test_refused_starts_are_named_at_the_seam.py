"""The refusal answer at the HTTP seam (issue R1+R2, AC4, AC5, AC6).

The pure helper is unit-tested in tests/unit/test_start_times.py. What belongs to the seam is the
response: a cycle the shop cannot honour is refused as an HTTP outcome, the reason comes from the
fixed vocabulary, and the alternatives are the next valid slots, earliest first, crossing to the
next open day when the day is exhausted. Nothing here mocks anything: the client posts over
127.0.0.1 and the repository is a real database.
"""

from datetime import datetime


def refused(client, email, type_key, start):
    session = client.session(email)
    response = client.post("/api/bookings", {"type": type_key, "start": start}, headers=session.headers)
    assert response.status_code == 409, response.text
    assert response.json()["error"] == "slot_not_valid", response.text
    return response.json()


def test_an_overrunning_cycle_names_the_reason_and_offers_the_next_open_day(client, seed):
    # The clock fixture is Thursday 2026-11-12, so family at 21:00 ends at 22:15, past closing.
    payload = refused(client, "ada@example.com", "family", "21:00")
    assert payload["reason"] == "would_overrun_closing"
    assert payload["alternatives"][0] == "2026-11-13T07:00"  # the day is exhausted, Friday earliest


def test_a_closed_day_and_a_time_outside_opening_hours_name_their_reasons(client, seed):
    # Thursday 23:30 is outside 07:00-22:00: the day is exhausted, so the answer crosses to Friday.
    payload = refused(client, "bruno@example.com", "quick", "23:30")
    assert payload["reason"] == "outside_opening_hours"
    assert payload["alternatives"][0] == "2026-11-13T07:00"

    client.clock.set(datetime(2026, 11, 15, 10, 0))  # Sunday
    payload = refused(client, "bruno@example.com", "quick", "10:00")
    assert payload["reason"] == "closed_day"
    assert payload["alternatives"][0] == "2026-11-16T07:00"  # Monday, earliest first


def test_an_off_grid_request_is_answered_with_the_grid_slot_it_rounds_up_to(client, seed):
    # 07:07 cannot be honoured as given: the grid is anchored at opening time, so 07:15 is the slot.
    payload = refused(client, "carla@example.com", "quick", "07:07")
    assert payload["alternatives"][0] == "07:15"
    assert payload["reason"] == "off_grid"  # quantised, not refused by one of the three AC4 causes


def test_the_board_never_offers_a_cycle_it_cannot_honour(client, seed):
    # 21:30 is the last quick start: standard and family can no longer finish before closing.
    client.clock.set(datetime(2026, 11, 12, 21, 30))
    board = client.get("/api/availability").json()
    rows = {row["type"]: row for row in board["types"]}
    assert rows["quick"]["earliest_start"] == "21:30"
    assert rows["standard"]["earliest_start"] is None
    assert rows["family"]["earliest_start"] is None
    assert board["grid_minutes"] == seed["grid_minutes"]


def test_the_board_offers_the_grid_anchored_at_opening_time(client, seed):
    # Just after opening the first slot a customer can be offered is 07:15, never 07:07.
    client.clock.set(datetime(2026, 11, 16, 7, 7))
    rows = {row["type"]: row for row in client.get("/api/availability").json()["types"]}
    assert {row["earliest_start"] for row in rows.values()} == {"07:15"}
