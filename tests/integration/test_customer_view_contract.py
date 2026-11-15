def test_availability_page_never_exposes_an_unlock_code(client):
    anna = client.session("hana@example.com")
    booking = client.post("/api/bookings", json={"type": "quick", "start": "10:00"}, headers=anna)
    code = booking.json()["code"]
    page = client.get("/api/views/availability", headers=None).text
    assert code not in page
    assert "macchina" not in page.lower() or "machine" in page.lower()  # per type, not per machine

def test_code_is_visible_only_inside_the_own_booking(client):
    anna = client.session("hana@example.com")
    beth = client.session("iris@example.com")
    booking = client.post("/api/bookings", json={"type": "standard", "start": "11:00"}, headers=anna)
    assert booking.json()["code"] in client.get("/api/views/bookings", headers=anna).text
    assert booking.json()["code"] not in client.get("/api/views/bookings", headers=beth).text
    assert booking.json()["tokens_required"] == 4
