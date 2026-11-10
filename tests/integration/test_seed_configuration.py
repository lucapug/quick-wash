def test_seed_numbers_match_the_pack(client, seed):
    assert seed["machines"] == 8
    assert seed["types"] == {"standard": 4, "family": 2, "quick": 2}
    assert seed["cycle_minutes"] == {"standard": 60, "family": 75, "quick": 30}
    assert seed["tokens_required"] == {"standard": 4, "family": 6, "quick": 3}
    assert seed["turnover_buffer_minutes"] == 10          # addendum patch 2
    assert seed["cleaning_buffer_minutes"] == 30          # addendum patch 2
    assert seed["grid_minutes"] == 15
    assert seed["opening_hours"] == {"open": "07:00", "close": "22:00"}
    assert seed["closed_days"] == ["Sunday"]

def test_type_is_the_source_of_tariff_and_duration(client, seed):
    machine = client.post("/api/machines", json={"type": "family"}).json()
    assert machine["cycle_minutes"] == 75
    assert machine["tokens_required"] == 6
    # A per-machine override must not exist: the same type always answers the same.
    other = client.post("/api/machines", json={"type": "family"}).json()
    assert other["cycle_minutes"] == machine["cycle_minutes"]
