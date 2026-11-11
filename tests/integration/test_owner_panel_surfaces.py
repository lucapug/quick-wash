"""The owner-panel access control (issue #10, slice c) — what the two provided assertions do not show alone.

`tests/integration/test_owner_panel_access.py` is the file the issue provides and it runs
byte-identical. What this file pins is the rest of the same three acceptance criteria, each as an
externally observable HTTP outcome: the owner flag as the thing that opens the panel, the two statuses
that must stay distinguishable, enforcement at the seam rather than in a control the front-end hides,
and the fact that a refusal writes nothing.

Nothing is mocked: the client posts over 127.0.0.1 and the repository is a real database.

The five surfaces the panel owns are the ones the acceptance criteria name — status board, machine list,
incident list, the maintenance toggle, the manual cancellation — and each answers for the owner, so the
refusal is shown to be an entitlement and not an empty view.

"""

from src import app as backend
from src import entitlements
from tests.conftest import SEAM_PATHS

SURFACES = ["/api/owner/machines", "/api/owner/status-board", "/api/owner/incidents"]
WRITES = ["/api/owner/machines/M1/maintenance", "/api/owner/bookings/b1/cancel"]


def panel(client, headers):
    """Every surface of the panel, as the responses a caller gets on each of them."""
    answers = {path: client.get(path, headers=headers) for path in SURFACES}
    for path in WRITES:
        answers[path] = client.post(path, headers=headers)
    return answers


def booked(client, who, type_key, start) -> dict:
    created = client.post("/api/bookings", json={"type": type_key, "start": start}, headers=who)
    assert created.status_code == 201, created.text
    return created.json()


# --- AC1: the owner flag is what opens the panel ------------------------------------------------

def test_the_owner_reaches_every_surface_the_panel_owns(client, seed):
    owner = client.session(seed["owner_email"]).headers
    for path in SURFACES:
        assert client.get(path, headers=owner).status_code == 200, client.last_response.text

    board = client.get("/api/owner/status-board", headers=owner).json()
    assert len(board["status_board"]) == seed["machines"]
    assert {row["type"] for row in board["status_board"]} == set(seed["types"])
    assert {row["state"] for row in board["status_board"]} == {"available"}

    # US54 in both directions, through the panel the owner is entitled to.
    out = client.post("/api/owner/machines/M1/maintenance", json={"state": "maintenance"}, headers=owner)
    assert out.status_code == 200 and out.json()["outcome"] == "maintenance", out.text
    back = client.post("/api/owner/machines/M1/maintenance", headers=owner)   # the toggle flips the state it is in
    assert back.status_code == 200 and back.json()["outcome"] == "available", back.text
    assert [row["kind"] for row in client.get("/api/owner/incidents", headers=owner).json()] == [
        "maintenance", "maintenance_lifted"]

    # US56: the manual cancellation, on the booking the owner is entitled to know exists.
    booking = booked(client, client.session("carl@example.com").headers, "quick", "10:00")
    cancelled = client.post(f"/api/owner/bookings/{booking['id']}/cancel", headers=owner)
    assert cancelled.status_code == 200 and cancelled.json()["outcome"] == "cancelled", cancelled.text
    assert cancelled.json()["booking"]["state"] == "cancelled"


def test_the_gate_is_the_pure_decision_and_the_owner_flag_is_the_whole_of_it(client, seed):
    customer = client.session("carl@example.com")
    owner = client.session(seed["owner_email"])
    assert entitlements.may_enter_panel(client.app.repo.get_or_create_identity(customer.email, False)) is False
    assert entitlements.may_enter_panel(client.app.repo.get_or_create_identity(owner.email, True)) is True
    assert entitlements.may_enter_panel(None) is False          # no session, no identity to be entitled with
    assert client.app.owner_gate(customer.headers) == (403, entitlements.panel_refusal())
    assert client.app.owner_gate(owner.headers) == (entitlements.ALLOWED, None)
    # A caller with no session is not an entitlement: it is the absence of one, so the gate answers 401.
    assert client.app.owner_gate({}) == (401, entitlements.missing_session())


# --- the decision: 401 for a missing session, 403 for a wrong entitlement ----------------------

def test_a_missing_session_and_a_wrong_entitlement_stay_two_different_outcomes(client, seed):
    customer = client.session("carl@example.com")
    for path in SURFACES + WRITES:
        anonymous = client.get(path) if path in SURFACES else client.post(path)
        assert anonymous.status_code == 401, anonymous.text
        assert anonymous.json() == entitlements.missing_session()
        denied = client.get(path, headers=customer) if path in SURFACES else client.post(path, headers=customer)
        assert denied.status_code == 403, denied.text
        assert denied.json() == entitlements.panel_refusal()
        # The two outcomes must be distinguishable from outside: different status, different copy.
        assert anonymous.json() != denied.json()
        assert "non è tuo" in denied.json()["message"].lower()      # the entitlement copy
        assert "non è tuo" not in anonymous.json()["message"].lower()  # the sign-in copy: entra / accedi


# --- AC2: a customer cannot reach any surface the panel owns ----------------------------------

def test_the_surfaces_stay_closed_to_a_customer_who_holds_real_ids(client, seed):
    carla = client.session("carla@example.com")
    booking = booked(client, carla, "family", "11:00")
    machine = booking["machine"]

    # She already holds the machine code (it is public, US42) and her own booking id — a copied link,
    # a shared screen. Nothing depends on what a front-end would show her: the seam decides.
    assert client.get("/api/owner/machines", headers=carla).status_code == 403
    assert client.get("/api/owner/status-board", headers=carla).status_code == 403
    assert client.get("/api/owner/incidents", headers=carla).status_code == 403
    assert client.post(f"/api/owner/machines/{machine}/maintenance", headers=carla).status_code == 403
    assert client.post(f"/api/owner/bookings/{booking['id']}/cancel", headers=carla).status_code == 403

    # A refusal writes nothing: the booking is still hers and still cancellable, the machine is still
    # reserved, and no incident was recorded for an action she was not entitled to take.
    assert client.get("/api/owner/machines", headers=client.session(seed["owner_email"]).headers)\
        .status_code == 200
    assert client.get(f"/api/bookings/{booking['id']}", headers=carla).json()["booking"]["state"] == "confirmed"
    assert client.get(f"/api/machines/{machine}", headers=carla).json()["state"] == "reserved"
    # Nothing was recorded either: a refusal is a decision, not a write. Only the panel reads the list.
    owner = client.session(seed["owner_email"]).headers
    assert [row["kind"] for row in client.get("/api/owner/incidents", headers=owner).json()] == []
    assert client.get("/api/owner/incidents", headers=carla).status_code == 403


# --- AC3: enforcement at the seam, not in a control the front-end hides ------------------------

def test_the_api_refuses_even_when_the_front_end_would_allow_the_click(client, seed):
    customer = client.session("carl@example.com")
    booking = booked(client, customer, "family", "11:00")
    assert booking["state"] == "confirmed"          # the state a UI would render as a cancellable control

    # The customer is not shown a control for her; that is not the enforcement. The enforcement is the
    # 403 on the request she can still make, decided before the lookup — so the panel cannot be used to
    # find out which ids are real either.
    refused = client.post(f"/api/owner/bookings/{booking['id']}/cancel", headers=customer)
    missing = client.post("/api/owner/bookings/b999/cancel", headers=customer)
    assert refused.status_code == 403 and missing.status_code == 403, (refused.text, missing.text)
    assert refused.json() == missing.json() == entitlements.panel_refusal()

    # Only the owner is entitled to know that a booking exists, so only the owner gets the 404.
    owner = client.session(seed["owner_email"]).headers
    assert client.post("/api/owner/bookings/b999/cancel", headers=owner).status_code == 404
    assert client.post("/api/owner/machines/m999/maintenance", headers=owner).status_code == 404
    assert client.post(f"/api/owner/bookings/{booking['id']}/cancel", headers=owner).status_code == 200


# --- the contract stays the contract ----------------------------------------------------------

def test_the_panel_surfaces_are_patterns_not_extra_contract_paths(client, seed):
    assert sorted(f"{method} {path}" for method, path in backend.ROUTES) == sorted(SEAM_PATHS)
    # The two contract entries the panel is built over still answer on their own paths.
    owner = client.session(seed["owner_email"]).headers
    assert client.get("/api/machines", headers=owner).status_code == 200
    assert client.get("/api/incidents", headers=owner).status_code == 200
    # Same core behind both paths: the same rows, so the two cannot drift.
    assert client.get("/api/machines", headers=owner).json()["machines"] == \
        client.get("/api/owner/machines", headers=owner).json()["machines"]
    assert client.get("/api/incidents", headers=owner).json() == client.get("/api/owner/incidents",
                                                                           headers=owner).json()
    # The observer keeps its reads and still has no entitlement to lose: it is not the owner.
    assert client.get("/api/incidents").status_code == 200
    assert client.get("/api/owner/incidents").status_code == 401
