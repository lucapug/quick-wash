"""What the five acceptance criteria of issue #45 (slice a of #11) need beyond the file the issue gives.

The provided file pins one booking: the quantisation of 14:07 and the record it answers with. It cannot
pin the rest of the same criteria, and the gap is what this file covers —

- AC1 per type: `end` is `start + cycle_minutes` of the chosen type (60/4, 75/6, 30/3), never one grid;
- AC2: the machine named at booking time is a machine of that type, committed to the customer;
- AC4: the record carries its status and is read back on `GET /api/bookings`, filtered to the owner;
- AC5: the numeric code is created at booking time, one per booking, and reaches only the owner.

Through the seam only: no repository call, no internal function, no mock other than the clock the
application is given as a dependency (docs/spec.md, Testing Decisions).

The last test is the one a human has to read: the two numbers the provided file asserts for a
`standard` booking — end 15:30 and token_count 6 — are the `family` tariff (75 minutes, 6 tokens), not
the `standard` one (60 minutes, 4 tokens), which is what AC1 of the same issue states and what
`src/config.py` seeds. The same request with `type` set to `family` answers exactly those two numbers,
so the file and AC1 cannot both be right. Nothing in `src/` is bent to make the provided file pass.
"""

from datetime import datetime, timedelta


def hhmm(moment) -> str:
    return moment.strftime("%H:%M")


def book(client, email, type_key, start):
    who = client.session(email)
    response = client.post("/api/bookings", json={"type": type_key, "start": start}, headers=who)
    return who, response


def test_end_and_token_count_are_the_type_s_real_duration_and_tariff(client, seed):
    """AC1: three durations, three tariffs, read per type at the seam (R1)."""
    for type_key in ("standard", "family", "quick"):
        _, response = book(client, f"{type_key}.probe@example.com", type_key, "12:00")
        assert response.status_code == 201, response.text
        booking = response.json()
        start = datetime.strptime(booking["start"], "%H:%M").replace(year=2026, month=11, day=12)
        assert booking["end"] == hhmm(start + timedelta(minutes=seed["cycle_minutes"][type_key]))
        assert booking["token_count"] == seed["tokens_required"][type_key]


def test_the_machine_named_at_booking_time_is_a_machine_of_that_type_committed_to_the_customer(client, seed):
    """AC2: the assignment is made at booking time, on a machine that can honour the quantised slot."""
    _, response = book(client, "bea@example.com", "quick", "13:07")   # quantised to 13:15
    booking = response.json()
    assert booking["start"] == "13:15"

    machine = client.get(f"/api/machines/{booking['machine']}").json()
    assert machine["type"] == "quick", "the machine named must be of the type asked for"
    assert machine["state"] == "reserved", "the slot is committed at booking time, not at arrival"
    assert not machine["assignable"], "a machine already committed for that slot is not free for another"

    # A second customer for the same type and slot is named on another machine (R5, slice b).
    _, second = book(client, "cid@example.com", "quick", "13:15")
    assert second.status_code == 201, second.text
    named = client.get(f"/api/machines/{second.json()['machine']}").json()
    assert named["type"] == "quick" and named["state"] == "reserved", "two slots, two machines"
    assert named["machine"] != machine["machine"], "the assignment is per machine, never shared"


def test_the_record_created_by_post_is_read_back_by_the_owner_on_get(client, seed):
    """AC4: the record carries its status, and the list is the caller's own."""
    who, created = book(client, "annalisa@example.com", "family", "10:00")
    booking = created.json()
    assert booking["state"] == "confirmed", "the record carries its status (AC4)"

    listed = client.get("/api/bookings", headers=who).json()["bookings"]
    assert [row["id"] for row in listed] == [booking["id"]], "the list is the caller's own"
    row = listed[0]
    for key in ("machine", "start", "end", "token_count", "unlock_code", "state"):
        assert row[key] == booking[key], f"the same record read back: {key}"
    assert row["unlock_code"].isdigit()


def test_the_unlock_code_is_created_at_booking_time_and_reaches_only_the_owner(client):
    """AC5: one code per booking, and nowhere the caller is not entitled to read it."""
    anna, mine = book(client, "dina@example.com", "standard", "15:00")
    bob, theirs = book(client, "edi@example.com", "standard", "15:15")
    code = mine.json()["unlock_code"]

    assert code.isdigit(), "the unlock code is numeric, as the machine keypad reads it"
    assert theirs.json()["unlock_code"] != code, "one code per booking, never shared"

    # Bob's own list is Bob's, and the read of a booking that is not his cannot say whether it exists,
    # so it cannot carry the code either.
    assert code not in client.get("/api/bookings", headers=bob).text
    refused = client.get(f"/api/bookings/{mine.json()['id']}", headers=bob)
    assert refused.status_code == 403
    assert code not in refused.text
    assert code not in client.get("/api/availability").text  # US22: never in a public view


def test_the_two_numbers_the_provided_file_asserts_are_the_family_tariff_not_the_standard_one(client, seed):
    """The contradiction the provided file carries, recorded as an outcome rather than as a patch.

    tests/integration/test_booking_creation_happy_path.py posts `standard` at 14:07 and asserts
    `end == "15:30"` and `token_count == 6`. Those are the family numbers (75 minutes, 6 tokens): the
    same request with `family` answers them exactly, while `standard` answers 15:15 and 4 — the
    60 minutes and 4 tokens AC1 of the same issue states. The file cannot pass without changing the
    tariff table, which is what `tests/test_seed_configuration.py` pins, so the file has to be corrected
    (either its `type` or its two numbers) by the human who wrote it.
    """
    _, as_family = book(client, "fabrizio@example.com", "family", "14:07")
    family = as_family.json()
    assert family["start"] == "14:15", "the quantisation is the same for every type"
    assert family["end"] == "15:30" and family["token_count"] == 6

    _, as_standard = book(client, "giulia@example.com", "standard", "14:07")
    standard = as_standard.json()
    assert standard["start"] == "14:15"
    assert standard["end"] == "15:15" and standard["token_count"] == 4
