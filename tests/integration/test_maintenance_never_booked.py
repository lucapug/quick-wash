def test_maintenance_machine_can_never_be_assigned(client, seed):
    carl = client.session("carl@example.com")
    beth = client.session("beth@example.com")
    first = client.post("/api/bookings", json={"type": "quick", "start": "10:00"}, headers=carl)
    assert first.status_code == 201
    machine = first.json()["machine"]
    assert client.post(f"/api/machines/{machine}/report", json={"kind": "fault"}, headers=carl).status_code == 202
    assert client.get(f"/api/machines/{machine}").json()["state"] == "maintenance"
    second = client.post("/api/bookings", json={"type": "quick", "start": "10:00"}, headers=beth)
    assert second.status_code == 201 and second.json()["machine"] != machine
    third = client.post("/api/bookings", json={"type": "quick", "start": "10:00"}, headers=carl)
    assert third.status_code == 409, "only the maintenance machine could serve this slot; assignment must refuse"
    bookings = client.get(f"api/bookings?machine={machine}").json()
    assert len(bookings) == 1 and bookings[0]["id"] == first.json()["id"]
    assert client.get(f"/api/machines/{machine}").json()["state"] == "maintenance"
