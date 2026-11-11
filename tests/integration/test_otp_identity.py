def test_otp_is_displayed_in_app_and_never_reaches_telemetry(client):
    sign_in = client.post("/api/session", json={"email": "anna@example.com"})
    assert sign_in.status_code == 200
    otp = sign_in.json()["otp"]
    assert otp                                    # in-app, no email/SMS transport
    telemetry = client.get("/api/logs/recent").text
    assert otp not in telemetry
    assert "anna@example.com" not in telemetry    # no customer data in telemetry either

def test_otp_is_single_use_and_expires_after_10_minutes(client, clock):
    sign_in = client.post("/api/session", json={"email": "beth@example.com"})
    otp = sign_in.json()["otp"]
    assert client.post("/api/session/verify", json={"email": "beth@example.com", "otp": otp}).status_code == 200
    clock.advance(minutes=10)
    assert client.post("/api/session/verify", json={"email": "beth@example.com", "otp": otp}).status_code == 401
    assert client.post("/api/bookings", json={"type": "quick", "start": "10:00"}).status_code == 401
