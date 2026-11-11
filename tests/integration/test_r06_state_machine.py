"""The state machine through the seam (R6, AC8). The assertions are unchanged; only the sign-in is added.

The device reports and the single-machine read need no session — a machine is a machine, and AC8 asks
for a reviewer to watch the hops live. The booking at the top of each test does: a booking request
without a session is refused with 401 (issue #9, AC7), so each test signs in first and then drives the
device exactly as before.
"""


def test_declared_path_is_walked_end_to_end(client, seed, clock):
    ada = client.session("ada@example.com")
    booking = client.post("/api/bookings", json={"type": "standard", "start": "10:00"}, headers=ada.headers)
    machine = booking.json()["machine"]
    assert booking.status_code == 201 and client.get(f"/api/machines/{machine}").json()["state"] == "reserved"
    client.post("/api/lock/redeem", json={"code": booking.json()["code"]})
    assert client.get(f"/api/machines/{machine}").json()["state"] == "unlocked"
    client.post("/api/lock/reports", json={"machine": machine, "event": "cycle_started"})
    assert client.get(f"/api/machines/{machine}").json()["state"] == "running"
    clock.advance(minutes=60)
    client.post("/api/lock/reports", json={"machine": machine, "event": "cycle_finished"})
    clock.advance(minutes=10)  # turnover buffer, R10
    assert client.get(f"/api/machines/{machine}").json()["state"] == "available"

def test_undeclared_transition_is_rejected_not_coerced(client, seed, clock):
    ada = client.session("ada@example.com")
    booking = client.post("/api/bookings", json={"type": "quick", "start": "10:00"}, headers=ada.headers)
    machine = booking.json()["machine"]
    client.post("/api/lock/redeem", json={"code": booking.json()["code"]})
    client.post("/api/lock/reports", json={"machine": machine, "event": "cycle_started"})
    bad = client.post("/api/lock/reports", json={"machine": machine, "event": "cycle_finished_available"})
    assert bad.status_code == 409
    assert client.get(f"/api/machines/{machine}").json()["state"] == "running"  # not coerced

def test_idle_open_is_an_event_not_a_state(client, seed, clock):
    ada = client.session("ada@example.com")
    booking = client.post("/api/bookings", json={"type": "quick", "start": "10:00"}, headers=ada.headers)
    machine = booking.json()["machine"]
    client.post("/api/lock/redeem", json={"code": booking.json()["code"]})
    clock.advance(minutes=15)
    client.post("/api/lock/reports", json={"machine": machine, "event": "idle_open"})
    assert client.get(f"/api/machines/{machine}").json()["state"] == "available"
    incidents = client.get("/api/incidents").json()
    assert any(i["kind"] == "idle_open" and i["machine"] == machine for i in incidents)
