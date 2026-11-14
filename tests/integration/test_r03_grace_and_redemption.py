def test_code_works_from_10_minutes_before_start(client, clock):
    booking = client.post("/api/bookings", json={"type": "standard", "start": "10:00"})
    clock.set("09:50")
    assert client.post("/api/lock/redeem", json={"code": booking.json()["code"]}).json()["outcome"] == "unlocked"

def test_redemption_after_the_grace_window_expires_the_booking(client, clock):
    booking = client.post("/api/bookings", json={"type": "quick", "start": "15:00"})
    clock.set("15:11")
    assert client.post("/api/lock/redeem", json={"code": booking.json()["code"]}).json()["outcome"] == "expired"
    assert client.get(f"/api/bookings/{booking.json()['id']}").json()["state"] == "expired"
    assert client.get(f"/api/machines/{booking.json()['machine']}").json()["state"] == "available"

def test_single_use_and_unknown_code(client, clock):
    booking = client.post("/api/bookings", json={"type": "family", "start": "12:00"})
    clock.set("12:05")
    code = booking.json()["code"]
    assert client.post("/api/lock/redeem", json={"code": code}).json()["outcome"] == "unlocked"
    assert client.post("/api/lock/redeem", json={"code": code}).json()["outcome"] == "already_redeemed"
    assert client.post("/api/lock/redeem", json={"code": "000000"}).json()["outcome"] == "unknown_code"
