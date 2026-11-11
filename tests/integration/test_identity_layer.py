"""The identity layer through the seam (issue #9, AC1-AC8).

`tests/integration/test_otp_identity.py` is the file the issue provides and it runs exactly as given:
the code shown in-app, and the code single-use and expired at 10 minutes. What this file pins is the
rest of the acceptance criteria, each as an externally observable HTTP outcome — the shape of the
sign-in request, the stored form of the code, the session that survives the next visit, the two codes
that must never be confused, the gate on anonymous booking, and the owner flag.

Nothing is mocked: the client posts over 127.0.0.1, the repository is a real database, and the code is
read back as the row the tests assert (a hash, an expiry, a spent marker) rather than as a credential.
"""

import hashlib
import json
from datetime import datetime, timedelta

from src import app as backend
from src.repository import TABLES, parse
from tests.conftest import SEAM_PATHS


def sign_in(client, email):
    """The two steps of the sign-in: the code is shown in-app, then redeemed for the token."""
    issued = client.post("/api/session", json={"email": email})
    assert issued.status_code == 200, issued.text
    verified = client.post("/api/session/verify", json={"email": email, "otp": issued.json()["otp"]})
    assert verified.status_code == 200, verified.text
    return issued.json(), verified.json()


def as_token(token):
    """A request made with the persisted session: the next visit, no credentials re-entered."""
    return {"Authorization": f"Bearer {token}"}


# --- AC1: no password anywhere --------------------------------------------------------------

def test_the_sign_in_takes_the_email_only_and_no_password_exists_in_the_api_or_the_schema(client, seed):
    refused = client.post("/api/session", json={"email": "clara@example.com", "password": "topsecret"})
    assert refused.status_code == 400 and refused.json()["error"] == "field_not_allowed", refused.text
    assert "password" in refused.json()["fields"]

    # No reset flow either: there is nothing to recover, the caller asks for a new code.
    assert client.post("/api/session/reset", json={"email": "clara@example.com"}).status_code == 404

    # The identity row is the email and the owner flag, and nothing that could be a password.
    offenders = [name for name, variants in TABLES.items()
                 if any("password" in variant.lower() for variant in variants)]
    assert not offenders, offenders
    sign_in(client, "clara@example.com")
    row = client.db.one("SELECT * FROM identities WHERE email = ?", ("clara@example.com",))
    assert sorted(row) == sorted(["id", "email", "is_owner"]), row


# --- AC2, AC3, AC4: the delivery channel is the response, the stored form is a hash ----------

def test_the_code_is_stored_hashed_with_its_expiry_and_read_back_as_a_hash(client, seed):
    issued = client.post("/api/session", json={"email": "dario@example.com"})
    code = issued.json()["otp"]
    assert issued.json()["displayed_in_app"] is True
    assert issued.json()["expires_in_minutes"] == 10                  # AC4, read back over HTTP

    row = client.db.one("SELECT * FROM otp WHERE email = ?", ("dario@example.com",))
    assert sorted(row) == sorted(["id", "email", "code_hash", "created_at", "expires_at", "used_at"]), row
    assert row["code_hash"] == hashlib.sha256(code.encode()).hexdigest()
    assert row["code_hash"] != code                            # no plaintext credential at rest
    assert parse(row["expires_at"]) - parse(row["created_at"]) == timedelta(minutes=10)
    assert row["used_at"] is None

    assert client.post("/api/session/verify", json={"email": "dario@example.com", "otp": code}).status_code == 200
    spent = client.db.one("SELECT * FROM otp WHERE email = ?", ("dario@example.com",))
    assert spent["used_at"]                                    # AC4: the first verify is the only one
    assert code not in client.get("/api/logs/recent").text     # and none in telemetry


def test_an_expired_code_and_a_spent_code_are_refused_and_neither_refusal_echoes_the_code(client, clock):
    issued = client.post("/api/session", json={"email": "yuri@example.com"})
    code = issued.json()["otp"]

    wrong = client.post("/api/session/verify", json={"email": "yuri@example.com", "otp": "000000"})
    assert wrong.status_code == 401 and code not in wrong.text, wrong.text

    clock.advance(minutes=10)                                  # AC4: expired at the tenth minute
    expired = client.post("/api/session/verify", json={"email": "yuri@example.com", "otp": code})
    assert expired.status_code == 401 and expired.json()["error"] == "code_expired", expired.text
    assert code not in expired.text

    # A code spent by the first verify is refused on the second, inside its window (AC4).
    second = client.post("/api/session", json={"email": "karim@example.com"}).json()["otp"]
    assert client.post("/api/session/verify", json={"email": "karim@example.com", "otp": second}).status_code == 200
    reused = client.post("/api/session/verify", json={"email": "karim@example.com", "otp": second})
    assert reused.status_code == 401 and reused.json()["error"] == "code_already_used", reused.text
    assert second not in reused.text


# --- AC5: the session survives the next visit -------------------------------------------------

def test_the_customer_is_recognised_on_the_next_visit_and_reads_only_their_own_bookings(client, seed):
    _, verified = sign_in(client, "annetta@example.com")
    token = verified["token"]
    assert client.db.one("SELECT * FROM sessions WHERE token = ?", (token,))   # persisted, not in memory

    created = client.post("/api/bookings", json={"type": "quick", "start": "10:00"}, headers=as_token(token))
    assert created.status_code == 201, created.text

    # The next visit: the token alone, no credentials re-entered.
    again = client.get("/api/bookings", headers=as_token(token))
    assert again.status_code == 200, again.text
    assert [booking["code"] for booking in again.json()["bookings"]] == [created.json()["booking"]["code"]]

    # The token is what recognises her; naming the email in a body is not a session.
    assert client.post("/api/bookings", json={"type": "quick", "start": "11:00",
                                              "email": "annetta@example.com"}).status_code == 401
    other = sign_in(client, "zoe@example.com")[1]["token"]
    assert client.get("/api/bookings", headers=as_token(other)).json()["bookings"] == []


# --- AC6: two codes, and the booking's code lives only inside the booking ---------------------

def test_the_unlock_code_is_distinct_from_the_sign_in_code_and_never_public(client, seed):
    issued, verified = sign_in(client, "ada@example.com")
    assert "code" not in issued and "code" not in verified     # never in the sign-in response

    booking = client.post("/api/bookings", json={"type": "quick", "start": "10:00"},
                          headers=as_token(verified["token"])).json()["booking"]
    assert booking["code"].isdigit() and booking["code"] != issued["otp"]   # distinct numeric codes
    assert booking["code"] not in client.get("/api/availability?window_hours=4&type=quick").text
    assert booking["code"] not in client.get("/api/machines/M1").text
    # Displayed only inside her own booking.
    mine = client.get("/api/bookings", headers=as_token(verified["token"])).json()["bookings"]
    assert [b["code"] for b in mine] == [booking["code"]], mine


# --- AC7: a booking needs a session, and the observer keeps its reads -------------------------

def test_anonymous_booking_is_refused_and_the_observer_keeps_its_reads(client, seed):
    assert client.post("/api/bookings", json={"type": "quick", "start": "10:00"}).status_code == 401
    assert client.get("/api/bookings").status_code == 401
    assert client.get("/api/bookings", headers=as_token("not-a-session")).status_code == 401

    # What an observer is allowed to do (issue #6, AC8): watch the shop, never book in it.
    assert client.get("/api/availability").status_code == 200
    assert client.get("/api/machines/M1").status_code == 200
    assert client.get("/api/incidents").status_code == 200
    assert client.get("/api/machines").status_code == 403                     # the owner panel stays closed


def test_the_journey_the_observer_cannot_start_shares_one_trace_and_carries_no_customer(client, clock):
    ada = client.session("ada@example.com")
    booking = client.post("/api/bookings", json={"type": "quick", "start": "10:00"},
                          headers=ada.headers).json()["booking"]
    clock.set(datetime(2026, 11, 12, 9, 25))                 # inside the grace window
    client.post("/api/lock/redeem", json={"code": booking["code"]})
    client.post("/api/lock/reports", json={"code": booking["code"], "event": "cycle_started"})
    client.post("/api/lock/reports", json={"code": booking["code"], "event": "cycle_finished"})

    entries = client.get("/api/logs/recent").json()["entries"]
    journey = [entry for entry in entries if entry["event"] in ("booking", "redeem", "report")]
    assert [entry["event"] for entry in journey] == ["booking", "redeem", "report", "report"], journey
    assert len({entry["trace"] for entry in journey}) == 1, journey
    text = client.get("/api/logs/recent").text
    assert booking["code"] not in text and ada.email not in text, text


# --- the contract stays the contract ----------------------------------------------------------

def test_the_two_identity_reads_are_patterns_not_ninth_contract_paths(client, seed):
    assert sorted(f"{method} {path}" for method, path in backend.ROUTES) == sorted(SEAM_PATHS)
    assert "POST /api/session/verify" in backend.PATTERNS and "GET /api/logs/recent" in backend.PATTERNS
    assert client.post("/api/session/verify", json={"email": "ada@example.com", "otp": "000000"}).status_code == 401
    assert client.get("/api/logs/recent").status_code == 200


# --- AC8: the owner signs in the same way, with the owner flag --------------------------------

def test_the_owner_signs_in_with_the_same_mechanism_and_the_owner_flag(client, seed):
    issued, verified = sign_in(client, seed["owner_email"])
    assert verified["is_owner"] is True
    headers = as_token(verified["token"])
    assert client.get("/api/machines", headers=headers).status_code == 200
    assert client.get("/api/incidents", headers=headers).status_code == 200

    customer = sign_in(client, "annetta@example.com")[1]
    assert customer["is_owner"] is False and customer["token"]
    assert client.get("/api/machines", headers=as_token(customer["token"])).status_code == 403
    assert client.get("/api/incidents", headers=as_token(customer["token"])).status_code == 403
