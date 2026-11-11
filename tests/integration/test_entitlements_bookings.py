def test_customer_cannot_touch_another_customers_booking(client):
    a = client.session("carl@example.com")
    b = client.session("dani@example.com")
    booking = client.post("/api/bookings", json={"type": "family", "start": "11:00"}, headers=a)
    other = client.get(f"/api/bookings/{booking.json()['id']}", headers=b)
    assert other.status_code == 403
    assert client.post(f"/api/bookings/{booking.json()['id']}/cancel", headers=b).status_code == 403
    assert booking.json()["id"] not in other.text()
