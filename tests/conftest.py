import pytest

SEAM_PATHS = [
    "POST /api/session",
    "GET /api/availability",
    "POST /api/bookings",
    "GET /api/bookings",
    "POST /api/lock/redeem",
    "POST /api/lock/reports",
    "GET /api/machines",
    "GET /api/incidents",
]

def test_seam_is_the_only_entry_point(client, seed):
    # A rule asserted through the seam must be observable as an HTTP outcome,
    # and the seed must be the pack's inventory, not a fixture invented in code.
    assert seed["machines"] == 8
    assert seed["types"] == {"standard": 4, "family": 2, "quick": 2}
    availability = client.get("/api/availability")
    assert availability.status_code == 200
    assert availability.json()["opening_hours"] == {"open": "07:00", "close": "22:00"}
    assert availability.json()["closed_days"] == ["Sunday"]
