"""Issue #20 (the customer frontend): the acceptance criteria read as outcomes at the seam.

The file the issue supplies (`tests/integration/test_customer_view_contract.py`) is executed unedited and
pins two facts: the availability page never carries an unlock code, and the code is visible only inside the
customer's own booking. What this file adds is the rest of the criteria, each one read as an HTTP outcome —
the language, the numbers per type, the earliest start first and the order the grid answers in, the reason
for every gap, the sign-in with no password field, the four things stated before the commit, the booking
list (state, the R4 cutoff, the R11 limit and its reset, the R9 block and its expiry), the reassignment, and
the two report actions on the customer's own machine only.

**The language, stated once so a test can read it.** AC1 asks for an Italian interface; the issue's Decision
overrides it to English, because the reviewers who evaluate and use the app read English. The two are not in
conflict once AC4 is read as it is written: AC4 asks for a reason "using the vocabulary from issue #10", and
that vocabulary is the seven pinned tokens of `src/availability.py::REASONS` — which the tests read as data,
in English, and which this implementation does not change. What the Decision moves is the sentence around the
token: every gap line on the page shows the token and its English sentence from `views.REASON_COPY`, one
entry per token. Domain copy the tests pin in the API's language (`entitlements`, `daily_limit`, `counters`)
is shown as-is where it occurs, exactly as the Decision states, and is not part of `views.strings()`.
Documentation stays English.

Nothing is mocked: the client posts over 127.0.0.1, the repository is a real database, and the pages are the
reads `src/views.py` renders on the same decisions the seam answers with.
"""

import re
from datetime import datetime
from pathlib import Path

from src import app as backend
from src import availability, cancellation, daily_limit, entitlements, identity, views
from src.domain import time as start_times

ROOT = Path(__file__).resolve().parents[2]
SHELL = ROOT / "src" / "frontend"

CODE_SHAPE = re.compile(r"\b\d{6}\b")
MACHINE_SHAPE = re.compile(r"\bM\d\b")
TYPE_ROW = re.compile(r'<p class="fw-bold" data-type="([a-z]+)">(.*?)</p>')
GRID = '<ul class="list-group" data-type="{type}">(.*?)</ul>'
SLOT = re.compile(r'<li class="list-group-item slot (available|unavailable)" data-start="(\d\d:\d\d)" '
                  r'data-reason="([a-z_]*)"[^>]*>(.*?)</li>')


def read(client, screen, headers=None, query=""):
    return client.get(f"/api/views/{screen}{query}", headers=headers)


def page(client, screen, headers=None, query=""):
    response = read(client, screen, headers, query)
    assert response.status_code == 200, response.text
    return response.text


def interface(text: str) -> str:
    """The part of the page the customer reads: the shell around it is not interface copy."""
    return text.split("<main", 1)[1]


def rows(text: str) -> dict:
    """One line per type: the type, the duration, the tariff, the inventory, the count."""
    return {match.group(1): match.group(2) for match in TYPE_ROW.finditer(text)}


def grid(text: str, type_key: str) -> list:
    """The slots of one type as the page lists them, in document order: (start, reason, line)."""
    section = re.search(GRID.format(type=type_key), text, re.S)
    assert section, f"no grid for {type_key} on the page: {text}"
    return [(match.group(2), match.group(3) or None, match.group(4))
            for match in SLOT.finditer(section.group(1))]


def book(client, who, type_key: str, start: str) -> dict:
    response = client.post("/api/bookings", json={"type": type_key, "start": start}, headers=who)
    assert response.status_code == 201, response.text
    return response.json()


# --- AC1: the interface is English (the issue's Decision), the documentation stays English ---------

def test_the_static_copy_follows_the_decision_and_reads_as_english(client, seed):
    assert views.LANGUAGE == "en" and views.DOCUMENTATION_LANGUAGE == "en"
    offenders = {key: views.italian_markers(value) for key, value in views.strings().items()}
    assert not {key: found for key, found in offenders.items() if found}, offenders
    text = interface(page(client, "availability"))
    assert "machine" in text.lower()
    assert not [marker for marker in views.ITALIAN_MARKERS if marker in text.lower()]


def test_the_domain_copy_the_tests_pin_is_shown_as_is_and_is_not_part_of_the_static_strings(client, seed):
    """The Decision's two halves, read on the same page: static strings English, domain copy as-is."""
    gate = read(client, "bookings")
    assert gate.status_code == entitlements.MISSING_SESSION          # refused at the seam, not hidden
    assert entitlements.missing_session()["message"] in gate.text
    assert entitlements.missing_session()["message"] not in views.strings()
    assert not any(marker in value for value in views.strings().values()
                   for marker in views.ITALIAN_MARKERS)


# --- AC2: availability is readable without signing in, per type, with the two numbers ---------------

def test_availability_is_readable_without_a_session_and_shows_the_duration_and_the_tariff_per_type(client, seed):
    text = interface(page(client, "availability"))
    assert "You can read this page without signing in." in text
    for type_key, numbers in (("standard", (60, 4)), ("family", (75, 6)), ("quick", (30, 3))):
        assert f"{numbers[0]} minutes, {numbers[1]} tokens" in rows(text)[type_key], text
        assert seed["cycle_minutes"][type_key] == numbers[0]
        assert seed["tokens_required"][type_key] == numbers[1]
        assert "Availability is answered per type, never per machine" in text


# --- AC3: the earliest valid start is offered first, so the common case is one tap ------------------

def test_the_earliest_valid_start_is_offered_first_and_the_page_keeps_the_order_the_seam_answers(client, seed):
    anna = client.session("nina@example.com")
    book(client, anna, "quick", "10:00")                            # the point the type already owes
    text = interface(page(client, "availability"))
    listed = grid(text, "quick")
    answered = client.get("/api/availability?window_hours=4&type=quick").json()["types"]["quick"]["slots"]
    # The page is not a second rule: it lists the same points, in the same order, with the same reasons.
    assert [(p["start"], p["reason"]) for p in answered] == [(start, reason) for start, reason, _ in listed]
    assert listed[0][1] is None and listed[0][0] == "10:15"          # earliest valid first
    assert f'Earliest start you can take: {listed[0][0]}' in text
    # One tap: the first line is a link straight to the booking screen for that start.
    assert f'data-action="take" data-type="quick" data-start="{listed[0][0]}"' in text
    taken = book(client, anna, "quick", listed[0][0])
    assert taken["machine"] and taken["start"] == listed[0][0]


# --- AC4: every unavailable slot shows its reason, in the vocabulary issue #10 fixes ----------------

def test_every_gap_shows_the_pinned_token_and_the_english_sentence_that_reads_it(client, seed):
    ada, bruno = client.session("ada@example.com"), client.session("bruno@example.com")
    for who in (ada, bruno):
        book(client, who, "quick", "10:00")                          # both machines of the type
    text = interface(page(client, "availability"))
    gaps = [(start, reason, line) for start, reason, line in grid(text, "quick") if reason]
    assert gaps and all(reason in availability.REASONS for _, reason, _ in gaps)
    assert any(reason == "all_machines_busy" for _, reason, _ in gaps)
    for _, reason, line in gaps:
        assert views.REASON_COPY[reason] in line                     # the reason is stated, not only named

    client.clock.set("2026-11-15T10:00")                             # Sunday
    assert all(reason == "closed_day" for _, reason, _ in grid(interface(page(client, "availability")), "quick"))


def test_the_buffer_and_the_maintenance_half_of_the_vocabulary_read_on_the_page(client, seed):
    anna, beth = client.session("zoe@example.com"), client.session("yuri@example.com")
    first, second = book(client, anna, "quick", "10:00"), book(client, beth, "quick", "10:00")
    # A cycle the device reported, read inside the turnover buffer (R10, addendum patch 2: 10 minutes).
    client.clock.set(datetime(2026, 11, 12, 9, 55))
    for booking in (first, second):
        client.post("/api/lock/redeem", {"code": booking["code"]})
        client.post("/api/lock/reports", {"code": booking["code"], "event": "cycle_started"})
        client.post("/api/lock/reports", {"code": booking["code"], "event": "cycle_finished"})
    gaps = grid(interface(page(client, "availability")), "quick")
    assert [reason for _, reason, _ in gaps if reason] == ["turnover_buffer"]
    assert views.REASON_COPY["turnover_buffer"] in [line for _, reason, line in gaps if reason][0]

    # R7: a type whose machines are all out of service answers with that word, and the page shows it.
    client.clock.set(datetime(2026, 11, 12, 11, 0))
    for who, booking in ((anna, first), (beth, second)):
        assert client.post("/api/lock/reports", {"machine": booking["machine"], "event": "fault"},
                           headers=who).status_code == 200
    assert all(reason == "machine_in_maintenance" for _, reason, _ in
               grid(interface(page(client, "availability")), "quick"))


# --- AC5: sign-in is email + the code shown in-app, and no password field exists anywhere ----------

def test_no_page_has_a_password_field_and_the_sign_in_shows_the_code_in_app(client, seed):
    for screen in ("availability", "sign-in", "book", "bookings"):
        text = read(client, screen).text
        assert not [field for field in re.findall(r"<input[^>]*>", text) if "password" in field.lower()]
    text = interface(page(client, "sign-in"))
    assert "one-time code shown here in the app" in text and "no password field" in text
    assert '<input class="form-control" id="email" name="email" type="email">' in text
    assert identity.SIGN_IN_FIELDS == ("email",)                     # the seam accepts the email only
    asked = client.post("/api/session", json={"email": "carla@example.com"})
    assert asked.json()["displayed_in_app"] and asked.json()["otp"]  # the answer is the delivery channel


# --- AC6: machine, start, expected end and tokens, all before the commit ---------------------------

def test_the_booking_screen_states_the_four_things_before_the_customer_commits(client, seed):
    anna = client.session("anna@example.com")
    text = interface(page(client, "book", anna, "?type=quick&start=10:00"))
    commit = text.index("Commit booking")
    for line in ("Machine: M", "Start: 10:00", "Expected end: 10:30", "Tokens required: 3"):
        assert line in text, text
        assert text.index(line) < commit, text
    assert MACHINE_SHAPE.search(text)                                # the number the shop would give
    # And the commit is refused at the seam when the slot cannot be honoured, not hidden by the page.
    late = read(client, "book", anna, "?type=quick&start=08:00")
    assert late.status_code == 409 and "in_the_past" in late.text


# --- AC7: the code is inside the customer's own booking, never on the availability page -------------

def test_the_availability_page_names_no_machine_no_customer_and_no_code(client, seed):
    anna = client.session("hana@example.com")
    booking = book(client, anna, "quick", "10:00")
    text = interface(page(client, "availability"))
    assert booking["code"] not in text
    assert not MACHINE_SHAPE.search(text) and "@" not in text        # per type, never per machine
    assert not CODE_SHAPE.search(text)
    # The machine number is the customer's own turn: it appears on her booking screen and on her list.
    assert MACHINE_SHAPE.search(interface(page(client, "book", anna, "?type=quick&start=10:15")))
    assert booking["code"] in interface(page(client, "bookings", anna))


# --- AC8: state, the R4 cutoff, the R11 limit and its reset, the R9 block with its expiry ----------

def test_the_booking_list_shows_state_and_the_r4_cutoff_on_both_sides_of_it(client, seed):
    anna = client.session("nadia@example.com")
    record = book(client, anna, "standard", "11:00")
    text = interface(page(client, "bookings", anna))
    assert 'data-state="confirmed"' in text and "State: confirmed" in text      # the state, as AC8 asks
    assert f"up to {cancellation.cutoff_minutes(client.app.config)} minutes before start" in text
    assert "You can still cancel." in text
    # The other side of the cutoff: the same page, read at 10:46, says the honest thing.
    client.clock.set(datetime(2026, 11, 12, 10, 46))
    later = interface(page(client, "bookings", anna))
    assert 'data-cancellable="0"' in later and "You can no longer cancel this booking." in later
    # The control is not the enforcement: the seam refuses the request, in the API's own copy.
    refused = client.post(f"/api/bookings/{record['id']}/cancel", json={}, headers=anna)
    assert refused.status_code == 409 and refused.json()["cutoff_minutes"] == 15
    assert refused.json()["state"] == "reserved"                      # the state shown, unchanged (US46)


def test_the_limit_and_its_reset_are_on_the_customer_s_own_list_before_any_refusal(client, seed):
    anna = client.session("olga@example.com")
    limit = daily_limit.limit_of(client.app.config)
    book(client, anna, "standard", "10:00")
    text = interface(page(client, "bookings", anna))
    assert f"Daily limit {limit} bookings: 1 used, {limit - 1} left" in text
    assert "Resets at 2026-11-13T00:00:00" in text                  # R11: the shop's own day, 00:00 local
    book(client, anna, "standard", "12:00")
    full = interface(page(client, "bookings", anna))
    assert f"{limit} used, 0 left" in full
    third = client.post("/api/bookings", json={"type": "standard", "start": "14:00"}, headers=anna)
    assert third.status_code == 409                                  # the refusal writes nothing
    assert "Resets at 2026-11-13T00:00:00" in interface(page(client, "bookings", anna))


def test_the_block_and_its_expiry_are_on_the_list_before_any_booking_attempt(client, seed):
    anna = client.session("rita@example.com")
    assert "No-show counter: 0 in the last 30 days. Not blocked." in interface(page(client, "bookings", anna))
    # Two turns lost inside the rolling window, created on slots the shop can still take (R9).
    for start, at in (("10:00", datetime(2026, 11, 12, 10, 11)), ("11:00", datetime(2026, 11, 12, 11, 11))):
        record = book(client, anna, "standard", start)
        client.clock.set(at)
        client.get(f"/api/bookings/{record['id']}", headers=anna)     # the read is where R3 is evaluated
    text = interface(page(client, "bookings", anna))
    assert "No-show counter: 2 in the last 30 days." in text
    assert "Blocked until 2026-11-19." in text and 'data-until="2026-11-19"' in text
    refused = client.post("/api/bookings", json={"type": "standard", "start": "13:00"}, headers=anna)
    assert refused.status_code == 403 and refused.json()["block"]["until"] == "2026-11-19"


# --- AC9: the reassignment is visible, with the new machine number ----------------------------------

def test_a_reassignment_is_visible_on_the_customer_s_own_page_with_the_new_machine(client, seed):
    anna = client.session("eva@example.com")
    record = book(client, anna, "family", "10:00")
    before = record["machine"]
    answer = client.post("/api/lock/reports", json={"machine": before, "event": "fault"}, headers=anna)
    assert answer.status_code == 200, answer.text
    moved = answer.json()["reassigned"][0]["machine"]
    assert moved != before
    text = interface(page(client, "bookings", anna))
    assert f"Moved to machine {moved}" in text, text                 # AC9: the number, in English
    assert f"{moved} - 10:00 to 11:15, 6 tokens" in text, text       # the start is kept, the machine is new
    assert answer.json()["reassigned"][0]["code"] in text and record["code"] not in text
    assert not MACHINE_SHAPE.search(interface(page(client, "availability")))   # and never on the public page


# --- AC10: the two report actions, on the customer's own machine only ------------------------------

def test_the_report_actions_are_on_the_customer_s_own_machine_only(client, seed):
    anna, beth = client.session("mina@example.com"), client.session("uri@example.com")
    mine, hers = book(client, anna, "standard", "10:00"), book(client, beth, "standard", "10:15")

    own = interface(page(client, "bookings", anna))
    assert f'data-machine="{mine["machine"]}"' in own
    assert views.COPY["report_fault"] in own and views.COPY["report_occupied"] in own
    # AC10, read as a scope: the page lists her own bookings, so the only machine it can act on is hers.
    assert sorted(set(re.findall(r'data-machine="(M\d)"', own))) == [mine["machine"]]
    assert hers["machine"] not in own and "@" not in own
    # The copy is the Decision's: English, and the two actions are exactly the kinds the seam accepts.
    assert [kind for kind, label in views.REPORT_ACTIONS if label in own] == ["fault", "occupied"]
    assert [kind for kind, _ in views.REPORT_ACTIONS] == sorted(backend.REPORT_KINDS)

    # Enforcement is at the seam, not in what the page renders: beth can still ask, and she is refused.
    refused = client.post(f"/api/machines/{mine['machine']}/report", json={"kind": "fault"}, headers=beth)
    assert refused.status_code == entitlements.NOT_ENTITLED
    accepted = client.post(f"/api/machines/{mine['machine']}/report", json={"kind": "fault"}, headers=anna)
    assert accepted.status_code == entitlements.REPORT_ACCEPTED, accepted.text
    # A control the page would render as clickable is still refused: a caller who holds the machine code
    # and has never had a turn on it has no entitlement, and the refusal writes nothing.
    stranger = client.session("neo@example.com")
    assert client.post(f"/api/machines/{mine['machine']}/report", json={"kind": "occupied"},
                       headers=stranger).status_code == entitlements.NOT_ENTITLED
    assert f'data-machine="{hers["machine"]}"' in interface(page(client, "bookings", beth))


# --- the shell: React (Vite) + Bootstrap CSS, no copy of its own, no layer in front of the seam -----

def test_the_app_shell_owns_no_copy_of_its_own_and_talks_to_the_seam_only(client, seed):
    shell = (SHELL / "App.jsx").read_text(encoding="utf-8")
    literals = re.findall(r'["\']([^"\n\']*)["\']', shell)
    values = set(views.strings().values())
    assert not [value for value in values if value in literals], "the shell would be a second copy"
    for path in ("/api/session", "/api/session/verify", "/api/bookings", "/api/machines/", "/api/views/"):
        assert path in shell, path
    assert "bootstrap" in (SHELL / "index.html").read_text(encoding="utf-8").lower()
