def test_reassignment_keeps_the_slot_and_issues_a_new_code(client):
    anna = client.session("anna@example.com")
    beth = client.session("beth@example.com")
    a = client.post("/api/bookings", json={"type": "family", "start": "10:00"}, headers=anna)
    b = client.post("/api/bookings", json={"type": "family", "start": "10:30"}, headers=beth)
    machine = a.json()["machine"]
    client.post(f"/api/machines/{machine}/report", json={"kind": "fault"}, headers=anna)
    moved = client.get(f"/api/bookings/{b.json()['id']}", headers=beth).json()
    assert moved["start"] == "10:30"
    assert moved["machine"] != machine
    assert moved["code"] != b.json()["code"]
    notes = client.get("/api/notifications", headers=beth).json()
    assert any(n["kind"] == "reassigned" and n["machine"] == moved["machine"] for n in notes)

def test_uncoverable_booking_is_cancelled_and_the_turn_can_be_rebooked(client):
    anna = client.session("carl@example.com")
    beth = client.session("dani@example.com")
    # family has 2 machines: anna takes one at 10:00, beth takes the other at 10:30,
    # so when anna's machine goes to maintenance nothing of the type is free at 11:00.
    victim = client.post("/api/bookings", json={"type": "family", "start": "11:00"}, headers=anna)
    machine = victim.json()["machine"]
    client.post(f"/api/machines/{machine}/report", json={"kind": "fault"}, headers=anna)
    cancelled = client.get(f"/api/bookings/{victim.json()['id']}", headers=anna).json()
    assert cancelled["state"] == "cancelled"
    incidents = client.get("/api/incidents").json()
    assert any(i["kind"] == "uncoverable" and i["booking"] == victim.json()["id"] for i in incidents)
    assert client.post("/api/bookings", json={"type": "family", "start": "11:30"}, headers=anna).status_code == 201
