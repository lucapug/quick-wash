def test_owner_endpoints_require_owner_flag(client):
    a = client.session("carl@example.com")
    assert client.get("/api/owner/machines", headers=a).status_code == 403

def test_owner_panel_surfaces_refuse_customers(client):
    a = client.session("carl@example.com")
    for path in ["/api/owner/status-board", "/api/owner/incidents"]:
        assert client.get(path, headers=a).status_code == 403
    for path in ["/api/owner/machines/m1/maintenance", "/api/owner/bookings/b1/cancel"]:
        assert client.post(path, headers=a).status_code == 403
