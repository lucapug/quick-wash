"""What issue #14 (R3) needs beyond the file the issue supplies — and the contradiction that file carries.

The supplied file pins three outcomes through the seam: the code working at the tenth minute before
start, a redemption past the window expiring the booking and releasing the machine, single use and the
unknown code. What it cannot pin is the rest of the same criteria: the shape of the code and what it is
tied to, the bounds being inclusive on both sides, the copy AC6 names, the places the code must never
appear, and the fact that a redemption is never what makes a cycle `running`.

The contradiction it carries is one the executor may not resolve by bending `src/`: it books without a
session, while `tests/integration/test_identity_layer.py` (AC7 of issue #9, and `docs/spec.md`, which
excludes fully anonymous booking because it makes no-shows untraceable and R9 impossible) pins exactly
the same request at 401. The gate runs green because the contradiction is recorded as an xfail in
`tests/fixtures.py`: the supplied file is not adjusted and nothing in `src/` is changed to make it pass.
What this file asserts is the same rule read through a session, so the rule stays verified as an
externally observable outcome rather than as a promise.
"""

from src import app as backend
from src import identity


def book(client, email, type_key, start):
    """A booking as the seam answers it to a customer (issue #9, AC7): sign in, then book."""
    who = client.session(email)
    response = client.post("/api/bookings", json={"type": type_key, "start": start}, headers=who)
    assert response.status_code == 201, response.text
    return who, response.json()


def outcome(client, code):
    """The outcome the machine keypad sees: one call on the device boundary, no QR, no reader."""
    return client.post("/api/lock/redeem", json={"code": code}).json()


# --- AC1: numeric, six digits, tied to one booking, redeemed at the keypad ------------------------

def test_the_code_is_six_digits_numeric_and_belongs_to_exactly_one_booking(client, seed):
    ada, first = book(client, "ada@example.com", "standard", "10:00")
    bruno, second = book(client, "bruno@example.com", "standard", "10:15")

    code = first["unlock_code"]
    assert len(code) == 6 and code.isdigit(), code
    assert first["code"] == first["unlock_code"], "one record, one spelling of the code"
    assert second["code"] != code, "one code per booking, never shared"

    # Tied to the booking: the code reads back on its own booking, and nowhere else.
    assert [row["code"] for row in client.get("/api/bookings", headers=ada).json()["bookings"]] == [code]
    assert code not in client.get("/api/bookings", headers=bruno).text


def test_the_outcomes_of_the_keypad_path_are_exactly_the_four_the_device_boundary_fixes(client, seed, clock):
    assert backend.REDEMPTION_OUTCOMES == ("unlocked", "expired", "already_redeemed", "unknown_code")
    _, booking = book(client, "carla@example.com", "quick", "10:00")
    clock.set("09:55")                       # inside the window, so this attempt is the redemption
    answer = outcome(client, booking["code"])
    assert answer["outcome"] == "unlocked"
    assert answer["machine"] == booking["machine"]
    assert answer["tokens_required"] == booking["token_count"]   # US29: the count is known before opening


# --- AC2: the window is inclusive on both bounds ----------------------------------------------------

def test_the_window_is_closed_on_both_bounds_inclusively(client, seed, clock):
    _, early = book(client, "dani@example.com", "standard", "10:00")
    clock.set("09:50")                       # the tenth minute before start: inside, on the bound
    assert outcome(client, early["code"])["outcome"] == "unlocked"

    _, late = book(client, "edo@example.com", "quick", "11:00")
    clock.set("11:10")                       # the tenth minute after start: inside, on the bound
    assert outcome(client, late["code"])["outcome"] == "unlocked"

    _, past = book(client, "fra@example.com", "quick", "12:00")
    clock.set("12:11")                       # one minute past the bound: the turn is lost
    assert outcome(client, past["code"])["outcome"] == "expired"


# --- AC3: outside the window the booking expires, the machine is released, the code is dead -------

def test_the_code_is_dead_after_the_window_and_a_read_shows_the_lost_turn(client, seed, clock):
    """Decision 2: expiry is evaluated at redemption and on any read, so no scheduler is needed.

    Nothing is redeemed here: the read is the request that notices the window has closed, and the three
    facts it writes are the same three facts a redemption at the machine would have written.
    """
    who, booking = book(client, "gina@example.com", "family", "10:00")
    clock.set("10:11")

    read = client.get(f"/api/bookings/{booking['id']}", headers=who).json()
    assert read["state"] == "expired", read
    assert client.get(f"/api/machines/{booking['machine']}").json()["state"] == "available"

    # Dead means dead: the code cannot unlock anything, and the answer is the same lost turn read again.
    assert outcome(client, booking["code"])["outcome"] == "expired"
    assert client.get(f"/api/machines/{booking['machine']}").json()["state"] == "available"

    # The lost turn is the record the owner panel reads (US57) and the fact R9 counts.
    incidents = [i for i in client.get("/api/incidents").json() if i["kind"] == "no_show"]
    assert [i["machine"] for i in incidents] == [booking["machine"]], incidents
    assert "grace window" in incidents[0]["detail"], incidents
    assert client.get("/api/bookings", headers=who).json()["block"]["blocked"] is None   # one no-show


# --- AC4 and AC5: one use, and a typo that is not a system failure ---------------------------------

def test_a_second_redemption_of_the_same_code_is_refused_even_after_the_cycle_started(client, seed, clock):
    _, booking = book(client, "ili@example.com", "quick", "10:00")
    clock.set("10:05")
    assert outcome(client, booking["code"])["outcome"] == "unlocked"
    client.post("/api/lock/reports", json={"code": booking["code"], "event": "cycle_started"})
    assert outcome(client, booking["code"])["outcome"] == "already_redeemed"


def test_an_unknown_code_is_answered_as_a_typo_not_as_a_failure(client, seed):
    answer = client.post("/api/lock/redeem", json={"code": "000000"})
    assert answer.status_code == 404 and answer.json()["outcome"] == "unknown_code", answer.text
    message = answer.json()["message"].lower()
    assert "sconosciuto" in message and "guasto" not in message, message
    assert "000000" not in message, message              # the answer does not echo the code back
    assert len(message) > 0
    # The shape a typo reads as is never generated, so it can never belong to a booking that exists.
    assert identity.NEVER_ISSUED == "000000" and identity.CODE_LENGTH == 6


# --- AC6: the copy says the customer lost the turn, not that the machine is broken ----------------

def test_the_expired_answer_says_the_turn_is_lost_and_the_machine_is_fine(client, seed, clock):
    _, booking = book(client, "mea@example.com", "quick", "10:00")
    clock.set("10:11")
    answer = outcome(client, booking["code"])
    message = answer["message"].lower()
    assert "perso il turno" in message, message
    assert "guasta" in message and "disponibile" in message, message
    assert answer["grace_window"] == {"from": "09:50", "to": "10:10"}


# --- AC7: nowhere the code is not entitled to be, and never in telemetry ---------------------------

def test_the_code_is_never_in_telemetry_never_public_and_never_sent_anywhere(client, seed):
    who, booking = book(client, "nia@example.com", "family", "10:00")
    code = booking["code"]
    outcome(client, code)

    # Telemetry records the request line, never the body: the code arrives in a body, so it has no path
    # into a log line. The read is the reviewer's view of those lines.
    assert code not in client.get("/api/logs/recent").text

    # Public views carry no code (US22): the board, the machine, the machine-scoped list.
    assert code not in client.get("/api/availability?window_hours=4&type=family").text
    assert code not in client.get(f"/api/machines/{booking['machine']}").text
    assert code not in client.get(f"/api/bookings?machine={booking['machine']}").text

    # No transport exists for it: the contract has no email or SMS path, only the keypad redemption.
    assert not [path for path in backend.ROUTES if "sms" in path[1] or "mail" in path[1]]


# --- AC8: `running` is the device's report, never a redemption and never a timer -------------------

def test_a_redemption_never_starts_a_cycle_and_no_timer_does(client, seed, clock):
    _, booking = book(client, "odi@example.com", "standard", "10:00")
    clock.set("10:05")
    assert outcome(client, booking["code"])["outcome"] == "unlocked"
    machine = booking["machine"]
    assert client.get(f"/api/machines/{machine}").json()["state"] == "unlocked"

    # Inside the bound issue #13 sets for `idle_open`, the read shows exactly what the device has reported:
    # nothing. The system never assumes tokens were inserted, and no timer drives the state.
    clock.set("10:14")
    assert client.get(f"/api/machines/{machine}").json()["state"] == "unlocked"
    read = client.get(f"/api/bookings/{booking['id']}", headers=client.session("odi@example.com")).json()
    assert read["state"] == "unlocked", "the booking is open, not running: no timer moved it"

    # The report is what moves it, and only through the declared hop. Past the nominal end of the cycle the
    # state is still the device's alone, because no report named a finish.
    client.post("/api/lock/reports", json={"machine": machine, "event": "cycle_started"})
    assert client.get(f"/api/machines/{machine}").json()["state"] == "running"
    clock.set("11:05")            # 10:00 + the type's 60 minutes: nothing moved it that the device did not name
    assert client.get(f"/api/machines/{machine}").json()["state"] == "running"
