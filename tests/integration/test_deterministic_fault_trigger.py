def test_fault_trigger_on_a_named_machine_is_reproducible(client, seed):
    assert client.post("/api/owner/faults/trigger", json={"machine": 3}).status_code == 202
    assert client.get("/api/machines/3").json()["state"] == "maintenance"
    incidents = client.get("/api/incidents").json()
    assert any(i["kind"] == "fault" and i["machine"] == 3 for i in incidents)
    # the same machine, the same trigger, the same result — no randomness
    assert client.post("/api/owner/faults/trigger", json={"machine": 3}).status_code == 202
    assert len([i for i in client.get("/api/incidents").json() if i["kind"] == "fault" and i["machine"] == 3]) == 2
