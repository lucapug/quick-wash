def test_turnover_buffer_of_10_minutes_blocks_the_machine(client, clock):
    anna = client.session("anna@example.com")
    booking = client.post("/api/bookings", json={"type": "quick", "start": "18:00"}, headers=anna)
    machine = booking.json()["machine"]            # lowest-numbered quick machine
    client.post("/api/lock/redeem", json={"code": booking.json()["code"]})
    client.post("/api/lock/reports", json={"machine": machine, "event": "cycle_started"})
    clock.advance(minutes=30)
    client.post("/api/lock/reports", json={"machine": machine, "event": "cycle_finished"})
    assert client.get(f"/api/machines/{machine}").json()["state"] == "finished"
    slots = client.get("/api/availability?type=quick&window_hours=2").json()["types"]["quick"]["slots"]
    assert machine not in [s["machine"] for s in slots]
    clock.advance(minutes=10)
    assert client.get(f"/api/machines/{machine}").json()["state"] == "available"

def test_next_assigned_customer_reports_and_is_reassigned_immediately(client, clock):
    anna = client.session("anna@example.com")
    first = client.post("/api/bookings", json={"type": "quick", "start": "19:00"}, headers=anna)
    machine = first.json()["machine"]
    clock.advance(minutes=30)
    client.post("/api/lock/redeem", json={"code": first.json()["code"]})
    client.post("/api/lock/reports", json={"machine": machine, "event": "cycle_finished"})
    clock.advance(minutes=10)                      # turnover buffer ends, machine bookable again
    beth = client.session("beth@example.com")
    second = client.post("/api/bookings", json={"type": "quick", "start": "19:45"}, headers=beth)
    assert second.json()["machine"] == machine     # lowest-numbered free machine
    assert client.post(f"/api/machines/{machine}/report", json={"kind": "still_occupied"}, headers=beth).status_code == 202
    assert client.get(f"/api/machines/{machine}").json()["state"] == "cleaning_required"
    moved = client.get(f"/api/bookings/{second.json()['id']}", headers=beth).json()
    assert moved["machine"] != machine and moved["code"] != second.json()["code"]
    clock.advance(minutes=30)
    assert client.get(f"/api/machines/{machine}").json()["state"] == "available"
