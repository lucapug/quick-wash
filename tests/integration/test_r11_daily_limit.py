from concurrent.futures import ThreadPoolExecutor

def test_two_bookings_per_day_independent_of_overlap(client, clock):
    anna = client.session("frank@example.com")
    first = client.post("/api/bookings", json={"type": "quick", "start": "08:00"}, headers=anna)
    second = client.post("/api/bookings", json={"type": "family", "start": "18:00"}, headers=anna)
    assert first.status_code == 201 and second.status_code == 201
    third = client.post("/api/bookings", json={"type": "standard", "start": "13:00"}, headers=anna)
    assert third.status_code == 409
    assert third.json()["limit"] == 2
    assert third.json()["used"] == 2
    assert third.json()["resets_at"] is not None

def test_reset_happens_at_midnight_local_and_cancelled_bookings_do_not_count(client, clock):
    anna = client.session("gina@example.com")
    first = client.post("/api/bookings", json={"type": "quick", "start": "21:30"}, headers=anna)
    client.post(f"/api/bookings/{first.json()['id']}/cancel", headers=anna)
    for _ in range(2):
        assert client.post("/api/bookings", json={"type": "quick", "start": "20:00"}, headers=anna).status_code == 201
    clock.set("2026-11-10T00:01")
    assert client.post("/api/bookings", json={"type": "quick", "start": "07:00"}, headers=anna).status_code == 201
