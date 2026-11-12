def test_booking_creation_happy_path_quantizes_and_returns_full_record(client):
    anna = client.session("anna@example.com")
    r = client.post("/api/bookings", json={"type": "standard", "start": "14:07"}, headers=anna)
    assert r.status_code == 201
    b = r.json()
    assert b["start"] == "14:15"
    assert b["end"] == "15:30"
    assert b["token_count"] == 6
    assert b["machine"], "assignment at booking time: a specific machine must be named"
    assert b["unlock_code"]

def test_past_slot_refused(client):
    anna = client.session("anna@example.com")
    r = client.post("/api/bookings", json={"type": "quick", "start": "09:00"}, headers=anna)
    assert r.status_code == 422
