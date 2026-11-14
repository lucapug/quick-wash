def test_cancellation_is_free_up_to_15_minutes_before_start(client, clock):
    anna = client.session("anna@example.com")
    booking = client.post("/api/bookings", json={"type": "standard", "start": "11:00"}, headers=anna)
    clock.set("10:45")
    assert client.post(f"/api/bookings/{booking.json()['id']}/cancel", headers=anna).status_code == 200
    assert client.get(f"/api/machines/{booking.json()['machine']}").json()["state"] == "available"

def test_late_cancellation_is_refused_with_the_state_shown(client, clock):
    beth = client.session("beth@example.com")
    booking = client.post("/api/bookings", json={"type": "family", "start": "12:00"}, headers=beth)
    clock.set("11:46")
    refused = client.post(f"/api/bookings/{booking.json()['id']}/cancel", headers=beth)
    assert refused.status_code == 409
    assert refused.json()["state"] == "reserved"
    assert refused.json()["cutoff_minutes"] == 15

def test_cancelled_slot_is_bookable_by_someone_else_immediately(client, clock):
    anna = client.session("anna@example.com")
    beth = client.session("beth@example.com")
    first = client.post("/api/bookings", json={"type": "quick", "start": "16:00"}, headers=anna)
    client.post(f"/api/bookings/{first.json()['id']}/cancel", headers=anna)
    second = client.post("/api/bookings", json={"type": "quick", "start": "16:00"}, headers=beth)
    assert second.status_code == 201
    assert second.json()["machine"] == first.json()["machine"]
