"""The R9 outcomes, read through a slot the shop can still take.

The file issue #18 supplies (`tests/integration/test_r09_no_show_block.py`) books 09:00 with the clock at
09:00 — the slot that has already begun, refused as 422 by issue #45 AC3 and pinned that way by
tests/integration/test_booking_creation_happy_path.py — so the no-show it describes cannot be created, and
its `advance(minutes=11)` closes a grace window only for a slot that has already begun. The supplied file is
recorded as a known contradiction in tests/fixtures.py. Nothing here adjusts either side: this file creates
the same two no-shows on slots the shop can still take and asserts the same outcomes, plus the criteria the
supplied file cannot exercise — AC2 as the second way a turn is lost (`idle_open`), AC3 the cancellation,
AC5 the view read before any booking attempt, and AC7 the rolling window as an outcome rather than as a
helper.

Everything is asserted as an externally observable outcome at the seam: the counter, the block, its reason
and its expiry on the customer's own view before any booking attempt, the 403 that refuses a booking, and
the booking that succeeds the moment the block is lifted. No mock, no internal call.
"""

from datetime import datetime


def book(client, session, type_key: str, start: str) -> dict:
    """A slot the shop can still take: the earliest grid point after the moment the request arrives."""
    response = client.post("/api/bookings", json={"type": type_key, "start": start}, headers=session)
    assert response.status_code == 201, response.text
    return response.json()


def close_grace_without_redemption(client, session, type_key: str, start: str, at: datetime) -> dict:
    """A no-show as the device reports it: the attempt lands after the grace window closes (R3, AC1)."""
    booking = book(client, session, type_key, start)
    client.clock.set(at)
    outcome = client.post("/api/lock/redeem", json={"code": booking["code"]}).json()
    assert outcome["outcome"] == "expired", outcome
    return outcome


def test_the_counter_and_the_block_are_the_same_outcomes_the_supplied_file_asserts(client, clock):
    anna = client.session("eve@example.com")

    # AC5: the customer's own view answers before any booking attempt, with nothing to count yet.
    me = client.get("/api/customers/me", headers=anna).json()
    assert me["no_show_count"] == 0
    assert me["block"]["until"] is None

    # The first no-show: the grace window closes at 09:25 for the 09:15 slot, so the attempt at 09:26
    # records it — the same fact the supplied file describes, on a slot the shop can still take.
    close_grace_without_redemption(client, anna, "quick", "09:15", datetime(2026, 11, 12, 9, 26))
    me = client.get("/api/customers/me", headers=anna).json()
    assert me["no_show_count"] == 1 and me["block"]["until"] is None  # one is not the threshold

    # The second inside the rolling window is the crossing: the block starts at the moment it is recorded.
    close_grace_without_redemption(client, anna, "quick", "09:30", datetime(2026, 11, 12, 9, 41))
    me = client.get("/api/customers/me", headers=anna).json()
    assert me["no_show_count"] == 2
    assert me["block"]["reason"] == "no_show"
    assert me["block"]["blocked"] is True
    assert me["block"]["until"] == "2026-11-19"
    assert me["block"]["expires_at"] == "2026-11-19T09:41:00"  # 7 days later, at the same local time
    assert "Sei bloccato" in me["message"]                     # Italian, read before booking

    # AC4: the refusal names the reason, the count that caused it and the expiry, in one copy of the shape.
    refused = client.post("/api/bookings", json={"type": "quick", "start": "12:00"}, headers=anna)
    assert refused.status_code == 403
    block = refused.json()["block"]
    assert block["reason"] == "no_show"
    assert block["no_shows"] == 2
    assert block["until"] == "2026-11-19"
    assert refused.json()["message"] == block["message"]  # one copy, so the two cannot disagree

    # AC6: on the expiry date the block is lifted automatically, and a booking at that moment succeeds.
    client.clock.set(datetime(2026, 11, 19, 9, 41))
    assert client.get("/api/customers/me", headers=anna).json()["block"]["blocked"] is None
    assert client.post("/api/bookings", json={"type": "quick", "start": "10:00"}, headers=anna).status_code == 201


def test_idle_open_counts_as_a_no_show_for_the_counter(client, clock):
    # AC2, the second of the two ways a turn is lost: the code works, the cycle never starts. The counter
    # reads the same crossing the grace path reads, so the block is the same outcome.
    ada = client.session("ida@example.com")

    close_grace_without_redemption(client, ada, "quick", "09:15", datetime(2026, 11, 12, 9, 26))
    booking = book(client, ada, "quick", "09:30")
    client.clock.set(datetime(2026, 11, 12, 9, 35))            # inside the window: the machine opens
    assert client.post("/api/lock/redeem", json={"code": booking["code"]}).json()["outcome"] == "unlocked"

    client.clock.set(datetime(2026, 11, 12, 9, 51))            # 16 minutes of idle open (issue #13, AC5)
    closed = client.post("/api/lock/reports", json={"code": booking["code"], "event": "idle_open"}).json()
    assert closed["outcome"] == "closed" and closed["incident"] == "idle_open"

    me = client.get("/api/customers/me", headers=ada).json()
    assert me["no_show_count"] == 2
    assert me["block"]["blocked"] is True and me["block"]["reason"] == "no_show"
    assert me["block"]["until"] == "2026-11-19"
    assert me["block"]["expires_at"] == "2026-11-19T09:51:00"  # the crossing was the idle_open, not the grace
    assert client.post("/api/bookings", json={"type": "quick", "start": "11:00"}, headers=ada).status_code == 403


def test_the_view_and_the_refusal_read_the_same_rolling_window(client, clock):
    # AC7: two no-shows on different days. The block is still running on 12 December, but the oldest has
    # left the rolling window on 14 December, so the counter is one and the customer can book again. A
    # calendar month would have kept both, and kept the block — which is the decision this issue records.
    anna = client.session("nadia@example.com")
    close_grace_without_redemption(client, anna, "quick", "10:00", datetime(2026, 11, 12, 10, 11))
    client.clock.set(datetime(2026, 12, 10, 9, 0))
    close_grace_without_redemption(client, anna, "quick", "10:00", datetime(2026, 12, 10, 10, 11))

    client.clock.set(datetime(2026, 12, 12, 11, 0))  # Saturday: the 12 November fact is 30 days old, inside
    me = client.get("/api/customers/me", headers=anna).json()
    assert me["no_show_count"] == 2 and me["block"]["no_shows"] == 2 and me["block"]["blocked"] is True
    assert me["block"]["until"] == "2026-12-17"  # seven days from the crossing, at the same local time

    client.clock.set(datetime(2026, 12, 14, 11, 0))  # Monday: the oldest left the rolling window (32 days)
    me = client.get("/api/customers/me", headers=anna).json()
    assert me["no_show_count"] == 2            # the two facts are still the customer's history
    assert me["block"]["no_shows"] == 1        # one inside the window: the threshold is not reached
    assert me["block"]["until"] is None
    assert client.post("/api/bookings", json={"type": "quick", "start": "11:15"}, headers=anna).status_code == 201


def test_a_cancellation_inside_the_window_is_not_a_no_show(client, clock):
    # AC3: R4's cancellation window must not feed the counter, or the rule would punish a customer who
    # cancelled in time, and not only the one who took a turn and did not honour it.
    anna = client.session("yuri@example.com")
    booking = book(client, anna, "quick", "10:00")
    client.clock.set(datetime(2026, 11, 12, 9, 40))  # 20 minutes before start: inside the 15-minute window
    cancelled = client.post(f"/api/bookings/{booking['id']}/cancel", json={}, headers=anna)
    assert cancelled.status_code == 200, cancelled.text

    me = client.get("/api/customers/me", headers=anna).json()
    assert me["no_show_count"] == 0
    assert me["block"]["until"] is None
    assert client.post("/api/bookings", json={"type": "quick", "start": "11:00"}, headers=anna).status_code == 201


def test_the_customers_view_needs_a_session(client, clock):
    # The view is the customer's, so it is gated the same way the booking surface is: R9 needs an identity
    # to hold a no-show against, and a caller with no session has no counter to read.
    assert client.get("/api/customers/me").status_code == 401
    assert client.get("/api/bookings").status_code == 401
