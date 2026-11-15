def test_fault_from_an_affected_customer_drives_maintenance_and_an_incident(client):
    anna = client.session("anna@example.com")
    booking = client.post("/api/bookings", json={"type": "standard", "start": "10:00"}, headers=anna)
    machine = booking.json()["machine"]
    report = client.post(f"/api/machines/{machine}/report", json={"kind": "fault"}, headers=anna)
    assert report.status_code == 202
    assert client.get(f"/api/machines/{machine}").json()["state"] == "maintenance"
    incidents = client.get("/api/incidents").json()
    assert any(i["kind"] == "fault" and i["machine"] == machine for i in incidents)
    slots = client.get("/api/availability?type=standard&window_hours=4").json()["types"]["standard"]["slots"]
    assert all(s.get("machine") != machine for s in slots)

def test_no_booking_may_remain_attached_to_a_machine_in_maintenance(client):
    anna = client.session("anna@example.com")
    first = client.post("/api/bookings", json={"type": "family", "start": "11:00"}, headers=anna)
    machine = first.json()["machine"]
    later = client.post("/api/bookings", json={"type": "family", "start": "14:00"}, headers=anna)
    client.post(f"/api/machines/{machine}/report", json={"kind": "fault"}, headers=anna)
    moved = client.get(f"/api/bookings/{later.json()['id']}", headers=anna).json()
    assert moved["machine"] != machine
    assert client.get(f"/api/machines/{machine}").json()["state"] == "maintenance"
