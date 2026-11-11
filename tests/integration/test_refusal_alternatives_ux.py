def test_409_lists_valid_alternatives_earliest_first_same_type(client, seed):
    # seed: one machine booked at 14:00 (quick), two free quick machines later
    anna = client.session("anna@example.com")
    beth = client.session("beth@example.com")
    winner = client.post("/api/bookings", json={"type": "quick", "start": "14:00"}, headers=anna)
    assert winner.status_code == 201
    loser = client.post("/api/bookings", json={"type": "quick", "start": "14:00"}, headers=beth)
    assert loser.status_code == 409
    alts = loser.json()["alternatives"]
    assert 0 < len(alts) <= 3
    assert alts == sorted(alts, key=lambda a: a["start"]), "earliest first"
    assert all(a["type"] == "quick" for a in alts), "from the same type"
    assert all(a["start"].endswith(("00", "15", "30", "45")) for a in alts), "15' quantization"
    for a in alts:
        r = client.post("/api/bookings", json={"type": "quick", "start": a["start"]}, headers=beth)
        assert r.status_code == 201, "every listed alternative must be bookable"
