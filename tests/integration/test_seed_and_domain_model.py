"""The seed and the domain model, read over the seam (issue #5, AC 3, 6, 7, 8).

The numbers are seed data: a reviewer reads them over HTTP, not out of code. Nothing about them is
editable through a screen, no machine row carries a price, no domain object carries a venue, and the
uniqueness of (machine, start time) is a constraint of the persistence layer rather than a pre-check.
The race that the constraint decides is asserted externally in tests/test_journey.py.
"""

from datetime import datetime

from src import domain
from src.repository import TABLES

SEED_KEYS = ("machines", "types", "cycle_minutes", "tokens_required", "turnover_buffer_minutes",
            "cleaning_buffer_minutes", "grid_minutes", "opening_hours", "closed_days")

VENUE_WORDS = ("venue", "site", "branch", "location")


def test_the_availability_payload_returns_the_seed_numbers_verbatim(client, seed):
    payload = client.get("/api/availability").json()["config"]
    assert payload == {key: seed[key] for key in SEED_KEYS}
    assert payload["types"] == {"standard": 4, "family": 2, "quick": 2}
    assert payload["opening_hours"] == {"open": "07:00", "close": "22:00"}
    assert payload["closed_days"] == ["Sunday"]


def test_the_seed_is_configuration_read_over_http_and_never_edited_through_a_screen(client, seed):
    refused = client.post("/api/config", {"opening_hours": {"open": "00:00", "close": "23:00"}})
    assert refused.status_code == 404, refused.text
    # A per-machine override is refused: the write accepts the type and nothing else.
    assert client.post("/api/machines", {"type": "family", "cycle_minutes": 5}).status_code == 400
    assert client.get("/api/availability").json()["config"]["opening_hours"] == seed["opening_hours"]


def test_a_machine_row_stores_only_its_own_fields_and_no_venue(client, seed):
    machine = client.post("/api/machines", json={"type": "quick"}).json()
    assert sorted(machine) == sorted(["id", "code", "type", "state", "capacity_kg",
                                      "cycle_minutes", "tokens_required"])
    row = client.db.one("SELECT * FROM machines WHERE id = ?", (machine["id"],))
    assert sorted(row) == sorted(domain.MACHINE_FIELDS)
    # The tariff and the duration are answered by the type, never read from the row.
    assert machine["cycle_minutes"] == domain.tariff_of(row["type"]).cycle_minutes
    assert machine["tokens_required"] == domain.tariff_of(row["type"]).tokens_required
    offenders = [key for key in list(client.app.repo.settings()) + list(row) + list(machine)
                 if any(word in key.lower() for word in VENUE_WORDS)]
    assert not offenders, offenders
    assert not [schema for variants in TABLES.values() for schema in variants
                if any(word in schema.lower() for word in VENUE_WORDS)]


def test_the_uniqueness_of_machine_and_start_is_the_thing_that_refuses_the_second_insert(client, seed):
    ada = client.session("ada@example.com")
    booking = client.post("/api/bookings", {"type": "quick", "start": "09:30"}, headers=ada.headers).json()["booking"]
    machine_id = client.db.one("SELECT machine_id FROM bookings WHERE id = ?", (booking["id"],))["machine_id"]
    params = (machine_id, "someone-else@example.com", "2026-11-12T09:30:00", "2026-11-12T10:00:00",
             "9999", 3, datetime(2026, 11, 12, 9, 0).isoformat())
    sql = ("INSERT INTO bookings (machine_id, email, start_time, end_time, code, state, tokens, created_at) "
           "VALUES (?, ?, ?, ?, ?, 'confirmed', ?, ?)")
    try:
        client.db.execute(sql, params)
    except Exception as error:
        assert "unique" in str(error).lower() or "duplicate" in str(error).lower(), str(error)
    else:
        raise AssertionError("the persistence layer accepted an overbooked slot")
    # The same fact reaches the seam as an outcome: the booking is refused by the layer, not a pre-check.
    assert client.app.repo.create_booking(machine_id, "third@example.com",
                                          datetime(2026, 11, 12, 9, 30), datetime(2026, 11, 12, 10, 0),
                                          "9998", 3, datetime(2026, 11, 12, 9, 0)) is None
