"""The public availability window at the HTTP seam (issue #8): the fixed vocabulary, the buffers, the
per-type shape.

Every assertion is an externally observable HTTP outcome, read without a session (US8). Nothing is
mocked: the client posts over 127.0.0.1, the repository is a real database, and the machines are driven
the way a real controller drives them, through the lock API. The pinned test of the issue
(`tests/integration/test_availability_public_view.py`) pins the shape and the earliest-first order; what
this file pins is the rest of the vocabulary, AC7, and the decision that the overrun is measured on the
type's duration.
"""

import json
from datetime import datetime


def window(client, type_key=None, hours=4):
    query = f"?window_hours={hours}" + (f"&type={type_key}" if type_key else "")
    return client.get(f"/api/availability{query}").json()


def entry(client, type_key, hours=4):
    return window(client, type_key, hours)["types"][type_key]


def slot(slots, start):
    return [s for s in slots if s["start"] == start][0]


def booked(client, type_key, start, headers=None):
    response = client.post("/api/bookings", {"type": type_key, "start": start}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


# --- AC2, AC6: per type, never per physical machine, never a customer -------------------------

def test_the_window_is_public_and_never_names_a_machine_a_customer_or_a_code(client, seed):
    response = client.get("/api/availability?window_hours=2&type=quick")   # no session, no token
    assert response.status_code == 200, response.text
    body = response.json()
    assert not any(key in body for key in ("code", "email", "customer", "machine"))
    for name, row in body["types"].items():
        assert not {"code", "email", "machine", "customer", "booking_id"} & set(row)
        for point in row.get("slots", []):
            assert not {"code", "email", "machine", "customer", "booking_id"} & set(point)
    text = json.dumps(body)
    assert "M1" not in text and "@" not in text, text


# --- AC7: a machine inside its turnover buffer is not counted as free -------------------------

def test_a_machine_inside_its_turnover_buffer_is_not_counted_free_and_carries_its_reason(client, seed):
    first = booked(client, "quick", "10:00")
    second = booked(client, "quick", "10:00")          # the second machine of the type
    assert first["machine"] != second["machine"]

    # The journey, driven as a device drives it: redeem, cycle started, cycle finished.
    client.clock.set(datetime(2026, 11, 12, 9, 55))
    for booking in (first, second):
        client.post("/api/lock/redeem", {"code": booking["code"]})
        client.post("/api/lock/reports", {"code": booking["code"], "event": "cycle_started"})
        client.post("/api/lock/reports", {"code": booking["code"], "event": "cycle_finished"})

    client.clock.set(datetime(2026, 11, 12, 10, 0))
    row = entry(client, "quick", hours=2)
    assert row["count"] == 0                            # AC7: both inside the 10-minute buffer
    assert row["tokens_required"] == 3
    assert slot(row["slots"], "10:00")["reason"] == "turnover_buffer"
    assert row["slots"][0]["start"] == "10:15"          # earliest valid first, past the buffer

    client.clock.set(datetime(2026, 11, 12, 10, 10))    # the buffer has run (R10)
    assert entry(client, "quick", hours=2)["count"] == 2


def test_a_machine_inside_the_cleaning_buffer_carries_the_cleaning_reason(client, seed):
    ada = client.session("ada@example.com")
    bruno = client.session("bruno@example.com")
    first = booked(client, "quick", "10:00", ada.headers)
    second = booked(client, "quick", "10:00", bruno.headers)

    # US35: the customer of the next cycle reports the machine as still occupied, and the report is
    # recorded at the moment it arrives (R10's `cleaning_required` hop).
    client.clock.set(datetime(2026, 11, 12, 10, 0))
    for who, booking in ((ada, first), (bruno, second)):
        reported = client.post("/api/lock/reports", {"machine": booking["machine"], "event": "occupied"},
                               headers=who.headers)
        assert reported.status_code == 200, reported.text

    row = entry(client, "quick", hours=2)
    assert row["count"] == 0
    assert slot(row["slots"], "10:15")["reason"] == "cleaning_buffer"   # 30 minutes, patch 2
    assert row["slots"][0]["start"] == "10:30"


def test_a_type_whose_machines_are_all_in_maintenance_names_that_reason(client, seed):
    ada = client.session("ada@example.com")
    bruno = client.session("bruno@example.com")
    first = booked(client, "quick", "10:00", ada.headers)
    second = booked(client, "quick", "10:00", bruno.headers)

    # R7: only a customer who has or had a booking on that machine may report it.
    for who, booking in ((ada, first), (bruno, second)):
        report = client.post("/api/lock/reports", {"machine": booking["machine"], "event": "fault"},
                             headers=who.headers)
        assert report.status_code == 200, report.text

    row = entry(client, "quick", hours=2)
    assert row["count"] == 0
    assert all(point["reason"] == "machine_in_maintenance" for point in row["slots"])  # US42


# --- AC4, AC5: the calendar half of the vocabulary, on the type's own duration ----------------

def test_the_refusal_is_measured_on_the_type_duration_so_family_and_quick_answer_differently(client, seed):
    client.clock.set(datetime(2026, 11, 12, 20, 30))
    family = entry(client, "family", hours=2)
    quick = entry(client, "quick", hours=2)

    # 21:00 is fine for a 30-minute cycle and past closing for a 75-minute one: one cap would be wrong.
    assert slot(quick["slots"], "21:00")["reason"] is None
    assert slot(family["slots"], "21:00")["reason"] == "would_overrun_closing"
    assert family["slots"][0]["start"] == "20:30"           # the earliest valid start, listed first
    assert slot(quick["slots"], "21:45")["reason"] == "would_overrun_closing"
    assert slot(quick["slots"], "22:15")["reason"] == "outside_opening_hours"


def test_a_closed_day_and_the_hours_outside_opening_hours_answer_from_the_vocabulary(client, seed):
    client.clock.set(datetime(2026, 11, 15, 10, 0))         # Sunday
    row = entry(client, "standard", hours=2)
    assert row["count"] == 4                                # the inventory, unchanged by a closed day
    assert all(point["reason"] == "closed_day" for point in row["slots"])

    client.clock.set(datetime(2026, 11, 12, 23, 30))        # Thursday, past closing
    assert all(point["reason"] == "outside_opening_hours" for point in entry(client, "quick", 1)["slots"])


def test_the_type_with_no_gap_is_answered_with_the_three_numbers_only(client, seed):
    row = entry(client, "quick")
    assert sorted(row) == ["count", "cycle_minutes", "slots", "tokens_required"]
    assert all(point["reason"] is None for point in row["slots"])
    assert row["slots"][0]["start"] == "09:00"              # the grid is anchored at opening, earliest first
