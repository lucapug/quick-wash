"""Entitlements on the booking surface — what one assertion cannot show alone.

`tests/integration/test_entitlements_bookings.py` is the file issue #10 slice a provides and it runs
byte-identical. What this file pins is the rest of the same three acceptance criteria, each as an
externally observable HTTP outcome: the body that cannot tell a foreign booking from a missing one, the
two statuses that must stay distinguishable, and enforcement at the seam rather than in a UI that hides
a control.

Nothing is mocked: the client posts over 127.0.0.1 and the repository is a real database.

The booking id on the wire is the string the URL segment reads as, which is what makes the provided
test able to ask for the same booking by id and to look for that id in the body of a refusal.
"""

from src import app as backend
from src import entitlements
from tests.conftest import SEAM_PATHS


def booked(client, who, type_key, start) -> dict:
    """A booking created by `who`, as the response that names it."""
    created = client.post("/api/bookings", json={"type": type_key, "start": start}, headers=who)
    assert created.status_code == 201, created.text
    return created.json()


# --- AC1: the body cannot say whether the booking exists -------------------------------------

def test_a_foreign_booking_and_a_booking_that_is_not_there_are_answered_the_same_body(client, seed):
    carl = client.session("carl@example.com")
    dani = client.session("dani@example.com")
    booking = booked(client, carl, "family", "11:00")

    foreign = client.get(f"/api/bookings/{booking['id']}", headers=dani)
    missing = client.get("/api/bookings/7", headers=dani)
    assert foreign.status_code == 403 and missing.status_code == 403, (foreign.text, missing.text)
    # The same body for the two cases: no status change, no wording that names which one it is.
    assert foreign.json() == missing.json(), (foreign.text, missing.text)
    assert sorted(foreign.json()) == sorted(["error", "message"])   # nothing that could carry the id
    assert booking["id"] not in foreign.text
    assert booking["code"] not in foreign.text and "carl@example.com" not in foreign.text
    # The body is the pure decision, so the seam cannot be made to name the booking it refused.
    assert foreign.json() == entitlements.refusal()


# --- the decision: 401 for a missing session, 403 for a wrong entitlement ---------------------

def test_a_missing_session_and_a_wrong_entitlement_stay_two_different_outcomes(client, seed):
    carl = client.session("carl@example.com")
    dani = client.session("dani@example.com")
    booking = booked(client, carl, "quick", "10:00")
    path = f"/api/bookings/{booking['id']}"

    # A caller with no session has no identity to be entitled with: it is answered "accedi".
    anonymous = client.get(path)
    assert anonymous.status_code == 401 and anonymous.json()["error"] == "sign_in_required", anonymous.text
    assert client.post(f"{path}/cancel").status_code == 401

    # A session that is not on this booking is answered "non è tua".
    denied = client.get(path, headers=dani)
    refused = client.post(f"{path}/cancel", headers=dani)
    assert denied.status_code == 403 and denied.json()["error"] == "not_your_booking", denied.text
    assert refused.status_code == 403 and refused.json()["error"] == "not_your_booking", refused.text

    # The two are the same decision in one place, and the copy differs: they cannot be confused.
    assert (entitlements.MISSING_SESSION, entitlements.NOT_ENTITLED) == (401, 403)
    row = client.app.repo.booking_by_id(int(booking["id"]))
    assert entitlements.may_touch(client.app.repo.get_or_create_identity(dani.email, False), row) is False
    assert entitlements.may_touch(client.app.repo.get_or_create_identity(carl.email, False), row) is True


# --- AC2: read and cancel, for a non-owner ----------------------------------------------------

def test_read_and_cancel_of_another_customers_booking_are_both_refused_and_write_nothing(client, seed):
    carl = client.session("carl@example.com")
    dani = client.session("dani@example.com")
    booking = booked(client, carl, "family", "11:00")

    assert client.get(f"/api/bookings/{booking['id']}", headers=dani).status_code == 403
    assert client.post(f"/api/bookings/{booking['id']}/cancel", headers=dani).status_code == 403

    # The refusal writes nothing: the booking is still Carl's and still in the state it was in.
    read = client.get(f"/api/bookings/{booking['id']}", headers=carl)
    assert read.status_code == 200 and read.json()["booking"]["state"] == "confirmed", read.text
    assert client.get("/api/bookings", headers=dani).json()["bookings"] == []
    assert client.get("/api/bookings", headers=carl).json()["bookings"][0]["id"] == booking["id"]
    # Nothing is recorded either: a refusal is a decision, not a write.
    owner = client.session(seed["owner_email"])
    assert [row["kind"] for row in client.get("/api/incidents", headers=owner).json()] == []


# --- AC3: enforcement at the seam, not in a control the front-end hides -----------------------

def test_the_api_refuses_even_when_the_front_end_would_allow_the_click(client, seed):
    carl = client.session("carl@example.com")
    dani = client.session("dani@example.com")
    booking = booked(client, carl, "family", "11:00")
    assert booking["state"] == "confirmed"   # the state a UI would render as a cancellable control

    # Dani already holds the id — a copied link, a shared screen. Nothing in the API depends on what
    # she is shown: the seam decides, and the entitlement is decided before anything else is checked.
    assert client.get(f"/api/bookings/{booking['id']}", headers=dani).status_code == 403
    assert client.post(f"/api/bookings/{booking['id']}/cancel", headers=dani).status_code == 403
    # The empty list is not the enforcement; it is what the enforcement leaves her. The enforcement is
    # the 403 on the request she can still make.
    assert client.get("/api/bookings", headers=dani).json()["bookings"] == []

    # The entitlement is the customer's own booking, and the owner panel is the other holder of it.
    owner = client.session(seed["owner_email"])
    read = client.get(f"/api/bookings/{booking['id']}", headers=owner)
    assert read.status_code == 200 and read.json()["booking"]["id"] == booking["id"], read.text
    # Only the owner is entitled to know that a booking exists, so only the owner gets the 404.
    assert client.get("/api/bookings/8", headers=owner).status_code == 404
    assert client.get("/api/bookings/8", headers=dani).json() == entitlements.refusal()
    cancelled = client.post(f"/api/bookings/{booking['id']}/cancel", headers=owner)
    assert cancelled.status_code == 200 and cancelled.json()["outcome"] == "cancelled", cancelled.text
    assert cancelled.json()["booking"]["state"] == "cancelled"
    assert client.get(f"/api/bookings/{booking['id']}", headers=carl).json()["booking"]["state"] == "cancelled"


# --- the contract stays the contract ----------------------------------------------------------

def test_the_two_booking_surface_entries_are_patterns_not_extra_contract_paths(client, seed):
    assert sorted(f"{method} {path}" for method, path in backend.ROUTES) == sorted(SEAM_PATHS)
    carl = client.session("carl@example.com")
    booking = booked(client, carl, "quick", "10:00")
    # The eight contract entries still answer on their own paths, and the two patterns read the same row.
    assert client.get("/api/bookings", headers=carl).json()["bookings"][0]["id"] == booking["id"]
    assert client.get(f"/api/bookings/{booking['id']}", headers=carl).json()["booking"]["id"] == booking["id"]
