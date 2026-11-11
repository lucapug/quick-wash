"""The public availability window, pinned by the issue (AC1-AC6). The pinned assertions are unchanged.

Only the sign-in is added here: the walk-in still reads the window with no session (US8, the first test
is untouched), but it now books through one. AC7 of issue #9 — and docs/spec.md, which excludes fully
anonymous booking because it makes no-shows untraceable and R9 impossible — refuses a booking request
without a session, which is what the second test used to rely on. Recorded for the reviewer: this is the
one point where the two issues' provided tests disagree, and AC7 is the one the code implements.
"""

def test_availability_is_readable_without_signing_in_and_is_per_type(client, seed):
    body = client.get("/api/availability?window_hours=4").json()
    assert body["types"]["standard"] == {"count": 4, "cycle_minutes": 60, "tokens_required": 4}
    assert body["types"]["family"] == {"count": 2, "cycle_minutes": 75, "tokens_required": 6}
    assert body["types"]["quick"] == {"count": 2, "cycle_minutes": 30, "tokens_required": 3}
    assert "code" not in body and "email" not in body

def test_earliest_valid_slot_is_offered_first_with_a_reason_for_every_gap(client, seed, clock):
    ada = client.session("ada@example.com")               # AC7: a booking needs a session
    booking = client.post("/api/bookings", json={"type": "quick", "start": "10:00"}, headers=ada.headers)
    assert booking.status_code == 201
    body = client.get("/api/availability?type=quick&window_hours=4").json()
    assert body["types"]["quick"]["count"] == 1
    assert body["types"]["quick"]["slots"][0]["start"] == "10:15"
    blocked = [s for s in body["types"]["quick"]["slots"] if s["start"] == "10:00"]
    assert blocked[0]["reason"] == "all_machines_busy"
    assert "code" not in blocked[0]
