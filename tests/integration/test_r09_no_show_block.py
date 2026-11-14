def test_block_is_enforced_and_shown_with_reason_and_expiry(client, clock):
    anna = client.session("eve@example.com")
    for start in ("09:00", "10:00"):
        booking = client.post("/api/bookings", json={"type": "quick", "start": start}, headers=anna)
        clock.advance(minutes=11)   # past the 10-minute grace window, code never redeemed
        client.post("/api/lock/redeem", json={"code": booking.json()["code"]})
    me = client.get("/api/customers/me", headers=anna).json()
    assert me["no_show_count"] == 2
    assert me["block"]["until"] is not None
    refused = client.post("/api/bookings", json={"type": "quick", "start": "12:00"}, headers=anna)
    assert refused.status_code == 403
    assert refused.json()["block"]["reason"] == "no_show"
    clock.advance(days=7)
    assert client.post("/api/bookings", json={"type": "quick", "start": "12:00"}, headers=anna).status_code == 201
