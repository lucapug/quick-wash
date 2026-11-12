"""Integration tests: the whole journey, driven through the HTTP seam.

Every assertion is an externally observable HTTP outcome. No service is started by hand, nothing
leaves the machine, no repository is mocked: the client fixture runs the backend over 127.0.0.1 and
the repository runs on a real relational database.
"""

import threading
from datetime import datetime

from tests.seam import SeamClient


def board(client, headers=None):
    return client.get("/api/availability", headers=headers).json()


def type_row(client, type_key, headers=None):
    return {row["type"]: row for row in board(client, headers)["types"]}[type_key]


def test_availability_is_readable_without_signing_in(client, seed):
    board_data = board(client)
    assert board_data["opening_hours"] == seed["opening_hours"]
    assert board_data["closed_days"] == seed["closed_days"]
    assert {row["type"]: row["machines"] for row in board_data["types"]} == seed["types"]
    quick = type_row(client, "quick")
    assert quick["earliest_start"] == "09:00" and quick["free"] == 2
    family = type_row(client, "family")
    assert family["cycle_minutes"] == 75 and family["tokens"] == 6  # US2 before choosing


def test_booking_then_redeem_then_cycle_then_turnover(client, seed):
    ada = client.session("ada@example.com")
    created = client.post("/api/bookings", {"type": "quick", "start": "09:30"}, headers=ada.headers)
    assert created.status_code == 201
    booking = created.json()["booking"]
    assert booking["machine"] and booking["tokens"] == 3 and booking["expected_end"] == "10:00"
    assert booking["grace_window"] == {"from": "09:20", "to": "09:40"}

    # US24: the code works from 10 minutes before start, not before.
    assert client.post("/api/lock/redeem", {"code": booking["code"]}).status_code == 403

    client.clock.set(datetime(2026, 11, 12, 9, 25))
    assert client.post("/api/lock/redeem", {"code": booking["code"]}).json()["outcome"] == "unlocked"
    # US26: a code is usable only once.
    assert client.post("/api/lock/redeem", {"code": booking["code"]}).json()["outcome"] == "already_redeemed"

    client.clock.set(datetime(2026, 11, 12, 9, 40))
    assert client.post("/api/lock/reports", {"code": booking["code"], "event": "cycle_started"}).json()["outcome"] == "running"

    client.clock.set(datetime(2026, 11, 12, 10, 0))
    finished = client.post("/api/lock/reports", {"code": booking["code"], "event": "cycle_finished"}).json()
    assert finished["turnover_minutes"] == seed["buffers"]["turnover_minutes"]
    assert type_row(client, "quick")["free"] == 1  # R10: the finished machine is not bookable yet

    client.clock.set(datetime(2026, 11, 12, 10, 10))
    assert type_row(client, "quick")["free"] == 2


def test_a_machine_reported_still_occupied_is_cleaned_and_the_customer_is_moved(client, seed):
    ada = client.session("ada@example.com")
    bruno = client.session("bruno@example.com")
    first = client.post("/api/bookings", {"type": "quick", "start": "09:30"}, headers=ada.headers).json()["booking"]

    # The turn is honoured: the cycle finishes, the turnover buffer passes, the next customer is
    # assigned to that same machine (R10).
    client.clock.set(datetime(2026, 11, 12, 9, 25))
    client.post("/api/lock/redeem", {"code": first["code"]})
    client.post("/api/lock/reports", {"code": first["code"], "event": "cycle_started"})
    client.clock.set(datetime(2026, 11, 12, 10, 0))
    client.post("/api/lock/reports", {"code": first["code"], "event": "cycle_finished"})

    client.clock.set(datetime(2026, 11, 12, 10, 15))
    # The slot has to be one that has not begun yet (issue #45, AC3): at 10:15 the 10:15 slot is
    # already under way, so the first slot bruno can take is 10:30 — still the same machine, released
    # by the turnover buffer at 10:10.
    second = client.post("/api/bookings", {"type": "quick", "start": "10:30"}, headers=bruno.headers).json()["booking"]
    assert second["machine"] == first["machine"]  # the machine the report is about

    report = client.post("/api/lock/reports", {"machine": second["machine"], "event": "occupied"}, headers=bruno.headers)
    payload = report.json()

    assert report.status_code == 200
    assert payload["outcome"] == "cleaning_required"
    assert payload["cleaning_minutes"] == seed["buffers"]["cleaning_minutes"]
    assert payload["clean_until"] == "10:45"
    assert payload["reassigned"]["machine"] != second["machine"]  # US34: immediate reassignment
    assert payload["reassigned"]["code"] != second["code"]         # US20: the code is tied to the booking


def test_grace_expiry_closes_the_booking_and_releases_the_machine(client, seed):
    ada = client.session("ada@example.com")
    booking = client.post("/api/bookings", {"type": "family", "start": "10:00"}, headers=ada.headers).json()["booking"]
    machine = booking["machine"]

    client.clock.set(datetime(2026, 11, 12, 10, 11))
    outcome = client.post("/api/lock/redeem", {"code": booking["code"]}).json()
    assert outcome["outcome"] == "expired" and outcome["grace_window"] == {"from": "09:50", "to": "10:10"}

    board_data = board(client)
    row = {m["machine"]: m for m in client.get("/api/machines", headers=client.session(seed["owner_email"]).headers).json()["machines"]}[machine]
    assert row["state"] == "available"
    assert board_data["types"] and row["type"] == "family"


def test_two_no_shows_block_new_bookings_for_seven_days(client, seed):
    ada = client.session("ada@example.com")
    for start in ("10:00", "11:00"):
        booking = client.post("/api/bookings", {"type": "quick", "start": start}, headers=ada.headers).json()["booking"]
        client.clock.set(datetime(2026, 11, 12, 10, 11) if start == "10:00" else datetime(2026, 11, 12, 11, 11))
        assert client.post("/api/lock/redeem", {"code": booking["code"]}).json()["outcome"] == "expired"

    client.clock.set(datetime(2026, 11, 12, 12, 0))
    refused = client.post("/api/bookings", {"type": "quick", "start": "12:30"}, headers=ada.headers)
    assert refused.status_code == 403 and refused.json()["error"] == "blocked"
    assert refused.json()["until"] == "2026-11-19"  # addendum: block_days 7 from today


def test_the_daily_limit_is_visible_to_the_customer(client, seed):
    ada = client.session("ada@example.com")
    for start in ("10:00", "11:00"):
        assert client.post("/api/bookings", {"type": "quick", "start": start}, headers=ada.headers).status_code == 201
    third = client.post("/api/bookings", {"type": "quick", "start": "12:00"}, headers=ada.headers)
    assert third.status_code == 409 and third.json()["error"] == "daily_limit"
    limit = client.get("/api/bookings", headers=ada.headers).json()["limit"]
    assert limit["max_per_day"] == 2 and limit["used"] == 2 and limit["remaining"] == 0


def test_the_race_for_a_slot_is_refused_by_the_persistence_layer_with_alternatives(client, seed):
    ada = client.session("ada@example.com")
    bruno = client.session("bruno@example.com")
    carla = client.session("carla@example.com")
    # Take the first family machine so both racers must fight for the same one.
    assert client.post("/api/bookings", {"type": "family", "start": "12:00"}, headers=ada.headers).status_code == 201

    results = {}
    barrier = threading.Barrier(2)

    def book(name, session):
        barrier.wait()
        results[name] = client.post("/api/bookings", {"type": "family", "start": "12:00"}, headers=session.headers)

    threads = [threading.Thread(target=book, args=(name, session)) for name, session in (("bruno", bruno), ("carla", carla))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    statuses = sorted(results[name].status_code for name in ("bruno", "carla"))
    assert statuses == [201, 409], {name: results[name].text for name in results}
    loser = results["bruno"] if results["bruno"].status_code == 409 else results["carla"]
    assert loser.json()["alternatives"], loser.text
    winners = [name for name in ("bruno", "carla") if results[name].status_code == 201]
    one_booking = [name for name in ("bruno", "carla") if client.get("/api/bookings", headers=(bruno if name == "bruno" else carla).headers).json()["bookings"]]
    assert one_booking == winners, one_booking  # R5: never two bookings on one machine for one slot


def test_idle_open_closes_the_booking_and_counts_as_a_no_show(client, seed):
    ada = client.session("ada@example.com")
    booking = client.post("/api/bookings", {"type": "standard", "start": "10:00"}, headers=ada.headers).json()["booking"]
    machine = booking["machine"]

    client.clock.set(datetime(2026, 11, 12, 9, 55))
    assert client.post("/api/lock/redeem", {"code": booking["code"]}).json()["outcome"] == "unlocked"
    too_early = client.post("/api/lock/reports", {"code": booking["code"], "event": "idle_open"})
    assert too_early.status_code == 409, too_early.text

    client.clock.set(datetime(2026, 11, 12, 10, 16))
    closed = client.post("/api/lock/reports", {"code": booking["code"], "event": "idle_open"}).json()
    assert closed["outcome"] == "closed" and closed["incident"] == "idle_open"
    owner = client.session(seed["owner_email"]).headers
    row = {m["machine"]: m for m in client.get("/api/machines", headers=owner).json()["machines"]}[machine]
    assert row["state"] == "available" and row["bookings"] == []
    assert client.get("/api/bookings", headers=ada.headers).json()["block"]["blocked"] is None  # one no-show

    second = client.post("/api/bookings", {"type": "standard", "start": "11:00"}, headers=ada.headers).json()["booking"]
    client.clock.set(datetime(2026, 11, 12, 11, 11))
    client.post("/api/lock/redeem", {"code": second["code"]})
    blocked = client.post("/api/bookings", {"type": "standard", "start": "12:00"}, headers=ada.headers)
    assert blocked.status_code == 403 and blocked.json()["until"] == "2026-11-19"  # R9, idle_open counted


def test_invalid_transitions_are_rejected_not_coerced(client, seed):
    ada = client.session("ada@example.com")
    booking = client.post("/api/bookings", {"type": "quick", "start": "10:00"}, headers=ada.headers).json()["booking"]
    # R6: a cycle cannot jump straight to finished — it must pass through running.
    refused = client.post("/api/lock/reports", {"code": booking["code"], "event": "cycle_finished"})
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"] == "invalid_transition"
    assert refused.json()["from"] == "reserved" and refused.json()["to"] == "finished"


def test_only_a_customer_with_a_booking_on_the_machine_can_report_a_fault(client, seed):
    ada = client.session("ada@example.com")
    carla = client.session("carla@example.com")
    booking = client.post("/api/bookings", {"type": "family", "start": "11:00"}, headers=ada.headers).json()["booking"]
    machine = booking["machine"]

    assert client.post("/api/lock/reports", {"machine": machine, "event": "fault"}, headers=carla.headers).status_code == 403

    report = client.post("/api/lock/reports", {"machine": machine, "event": "fault"}, headers=ada.headers)
    payload = report.json()
    assert report.status_code == 200 and payload["outcome"] == "maintenance"
    assert payload["reassigned"][0]["machine"] != machine and payload["reassigned"][0]["code"] != booking["code"]
    assert payload["reassigned"][0]["tokens"] == 6

    # R8: no booking may stay attached to a machine in maintenance.
    row = {m["machine"]: m for m in client.get("/api/machines", headers=client.session(seed["owner_email"]).headers).json()["machines"]}[machine]
    assert row["state"] == "maintenance" and row["bookings"] == []


def test_the_owner_panel_stays_closed_to_customers(client, seed):
    ada = client.session("ada@example.com")
    assert client.get("/api/machines", headers=ada.headers).status_code == 403
    owner = client.session(seed["owner_email"]).headers
    board_data = client.get("/api/machines", headers=owner).json()
    assert len(board_data["machines"]) == seed["machines"]
    assert {row["type"] for row in board_data["machines"]} == set(seed["types"])
    assert client.get("/api/incidents", headers=owner).status_code == 200
    assert client.get("/api/incidents", headers=ada.headers).status_code == 403
