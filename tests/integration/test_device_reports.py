def test_running_comes_from_the_device_not_from_a_timer(client, clock):
    booking = client.post("/api/bookings", json={"type": "family", "start": "16:00"})
    machine = booking.json()["machine"]
    client.post("/api/lock/redeem", json={"code": booking.json()["code"]})
    clock.advance(minutes=90)  # past the 75-minute nominal cycle
    assert client.get(f"/api/machines/{machine}").json()["state"] == "unlocked"
    client.post("/api/lock/reports", json={"machine": machine, "event": "cycle_started"})
    assert client.get(f"/api/machines/{machine}").json()["state"] == "running"
    assert client.get(f"/api/bookings/{booking.json()['id']}").json()["state"] == "running"

def test_idle_open_after_15_minutes_releases_the_machine_and_records_an_incident(client, clock):
    booking = client.post("/api/bookings", json={"type": "standard", "start": "17:00"})
    machine = booking.json()["machine"]
    client.post("/api/lock/redeem", json={"code": booking.json()["code"]})
    clock.advance(minutes=14)
    assert client.get(f"/api/machines/{machine}").json()["state"] == "unlocked"
    clock.advance(minutes=1)
    client.post("/api/lock/reports", json={"machine": machine, "event": "idle_open"})
    assert client.get(f"/api/machines/{machine}").json()["state"] == "available"
    assert client.get("/api/bookings/1").json()["state"] == "closed"
    incidents = client.get("/api/incidents").json()
    assert any(i["kind"] == "idle_open" and i["machine"] == machine for i in incidents)
    assert client.get("/api/customers/me").json()["no_show_count"] == 1
