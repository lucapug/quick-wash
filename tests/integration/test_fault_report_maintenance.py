def test_fault_report_only_from_someone_who_had_a_booking_on_that_machine(client):
    a = client.session("carl@example.com")
    booking = client.post("/api/bookings", json={"type": "standard", "start": "12:00"}, headers=a)
    machine = booking.json()["machine"]
    stranger = client.session("eve@example.com")
    assert client.post(f"/api/machines/{machine}/report", json={"kind": "fault"}, headers=stranger).status_code == 403
    assert client.post(f"/api/machines/{machine}/report", json={"kind": "fault"}, headers=a).status_code == 202

def test_accepted_report_drives_maintenance_state(client):
    a = client.session("carl@example.com")
    booking = client.post("/api/bookings", json={"type": "standard", "start": "12:00"}, headers=a)
    machine = booking.json()["machine"]
    client.post(f"/api/machines/{machine}/report", json={"kind": "fault"}, headers=a)
    assert client.get(f"/api/machines/{machine}").json()["state"] == "maintenance"
