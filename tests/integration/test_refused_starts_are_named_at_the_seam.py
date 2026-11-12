"""The refusal answer at the HTTP seam (issue R1+R2, AC4, AC5, AC6).

The pure helper is unit-tested in tests/unit/test_start_times.py. What belongs to the seam is the
response: a cycle the shop cannot honour is refused as an HTTP outcome, the reason comes from the
fixed vocabulary, and the alternatives are the next valid slots, earliest first, crossing to the
next open day when the day is exhausted. Nothing here mocks anything: the client posts over
127.0.0.1 and the repository is a real database.

Issue #45 (slice a of #11) changes two things here, and the tests read as it says:
- an off-grid request is no longer refused, it is quantised up to the grid point it rounds up to (AC1);
- `outside_opening_hours` answers 422 with the reason, together with the slot that has already begun
  (AC3). The other two causes of the fixed vocabulary keep the 409 this file established.
Every request below is therefore a slot that has not begun yet, so the refusal is the calendar cause
and not the past.
"""

from datetime import datetime


def refused(client, email, type_key, start, status=409):
    session = client.session(email)
    response = client.post("/api/bookings", {"type": type_key, "start": start}, headers=session.headers)
    assert response.status_code == status, response.text
    assert response.json()["error"] == "slot_not_valid", response.text
    return response.json()


def test_an_overrunning_cycle_names_the_reason_and_offers_the_next_open_day(client, seed):
    # The clock fixture is Thursday 2026-11-12, so family at 21:00 ends at 22:15, past closing. The
    # clock is put before the request: a slot already begun is refused for that cause (AC3), and this
    # test is about the cycle, not about the past.
    client.clock.set(datetime(2026, 11, 12, 20, 30))
    payload = refused(client, "ada@example.com", "family", "21:00")
    assert payload["reason"] == "would_overrun_closing"
    assert payload["alternatives"][0] == "2026-11-13T07:00"  # the day is exhausted, Friday earliest


def test_a_closed_day_and_a_time_outside_opening_hours_name_their_reasons(client, seed):
    # Thursday 23:30 is outside 07:00-22:00: AC3 answers that cause with 422, and the day is
    # exhausted, so the answer crosses to Friday.
    client.clock.set(datetime(2026, 11, 12, 20, 30))
    payload = refused(client, "bruno@example.com", "quick", "23:30", status=422)
    assert payload["reason"] == "outside_opening_hours"
    assert payload["alternatives"][0] == "2026-11-13T07:00"

    client.clock.set(datetime(2026, 11, 15, 10, 0))  # Sunday
    # A slot on a later day, so the cause named is the closed day (409): a slot of the current
    # moment would be refused as already begun instead.
    payload = refused(client, "bruno@example.com", "quick", "2026-11-15T11:00")
    assert payload["reason"] == "closed_day"
    assert payload["alternatives"][0] == "2026-11-16T07:00"  # Monday, earliest first


def test_an_off_grid_request_is_quantised_up_to_the_grid_slot_it_rounds_up_to(client, seed):
    # AC1 (issue #45): 07:07 is not refused, it is adjusted. The grid is anchored at opening time, so
    # the booking is the grid point the request rounds up to, and `off_grid` stays the helper's word
    # for the board (tests/unit/test_start_times_vocabulary.py), never an answer to a booking request.
    client.clock.set(datetime(2026, 11, 16, 7, 0))
    carla = client.session("carla@example.com")
    response = client.post("/api/bookings", {"type": "quick", "start": "07:07"}, headers=carla)
    assert response.status_code == 201, response.text
    assert response.json()["start"] == "07:15"
    assert response.json()["end"] == "07:45"  # the type's real duration from the quantised start


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
