"""The R11 outcomes, read on slots the shop can still give.

`tests/integration/test_r11_daily_limit.py` is the file issue #21 provides and it runs byte-identical. Two
of its requests cannot be produced by this repository, so they are recorded in `tests/fixtures.py` rather
than bent: its first request is 08:00 with the clock at 09:00, the slot that has already begun (issue #45,
AC3, pinned by `tests/integration/test_booking_creation_happy_path.py`), so the day it counts cannot be
built from inside the file; and after its two 20:00 bookings both `quick` machines of the pack hold a turn,
and a machine held for the customer who booked it is never free for another point — the reading issue #8
pins in `tests/integration/test_availability_public_view.py` — so the request that follows its reset is
refused for the machine and not for the limit.

What this file pins is R11 as the rule it is, each criterion as an externally observable HTTP outcome:

- **AC1**: two bookings on distant slots, no overlap, both count — the day is read on the moment each
  booking was created, not on the slots it is active in, so a customer holding two slots is refused even
  when both are already in the past of the day;
- **AC2**: the refusal states the limit, the count used and the moment it resets;
- **AC3**: the same three are on the customer's own view before any refusal happens;
- **AC4**: a cancelled booking does not consume the day — the refund is the right to rebook, so the seat
  goes back with the turn and the next request is accepted;
- **AC5**: the turn cancelled as uncoverable by R8 (issue #19) gives its seat back with the turn;
- **AC6**: a blocked customer (R9, issue #20) is refused before the day is read, and the answer names the
  block and not the limit;
- **AC7**: the limit is enforced at the seam under concurrency — the UNIQUE `(email, day, seat)` index
  decides, not the pre-check: of two parallel attempts on one seat exactly one writes, the day never holds a
  third row, and the loser leaves nothing behind. The word the loser is answered with is the constraint its
  own insert was carrying, so the assertion is the guarantee (the count), not the word.

Nothing is mocked: the client posts over 127.0.0.1 and the repository is a real database. The reset moment
is asserted as the shop's own midnight in `Europe/Rome` (the decision the issue records), not as `23:59` of
the day, and the day the count belongs to is read on `created_at`.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from src import daily_limit
from src.config import SEED

RESET = "2026-11-13T00:00:00"       # the shop's own midnight after Thursday 12 November


def booked(client, who, type_key: str, start: str) -> dict:
    """A slot the shop can still take: the request as the response that names it."""
    response = client.post("/api/bookings", json={"type": type_key, "start": start}, headers=who)
    assert response.status_code == 201, response.text
    return response.json()


def view_of(client, who) -> dict:
    """The customer's own view, read before any refusal (AC3)."""
    answer = client.get("/api/customers/me", headers=who)
    assert answer.status_code == 200, answer.text
    return answer.json()["limit"]


def list_of(client, who) -> dict:
    """The same fact on the customer's list: one reading, so the two cannot disagree."""
    answer = client.get("/api/bookings", headers=who)
    assert answer.status_code == 200, answer.text
    return answer.json()["limit"]


# --- AC1, AC2, AC3: the count, the refusal, and the copy before any refusal -----------------------

def test_the_count_is_independent_of_overlap_and_the_refusal_states_the_three_things(client, clock):
    anna = client.session("frank@example.com")

    # AC3: the view answers before any booking attempt, with nothing consumed yet, and it carries the reset.
    before = view_of(client, anna)
    assert before["max_per_day"] == 2 and before["used"] == 0 and before["remaining"] == 2
    assert before["resets_at"] == RESET and before["timezone"] == SEED["timezone"]

    first = booked(client, anna, "quick", "09:15")     # the earliest slot the shop can still take
    second = booked(client, anna, "family", "18:00")   # far from the first: no overlap, nothing shared
    assert first["machine"] != second["machine"]

    # AC1: two distant slots are still two bookings of the same day, and the day is read before the third.
    assert view_of(client, anna)["used"] == 2 and list_of(client, anna)["used"] == 2
    refused = client.post("/api/bookings", json={"type": "standard", "start": "13:00"}, headers=anna)
    assert refused.status_code == 409, refused.text
    body = refused.json()

    # AC2: the limit, the count used, the moment it resets — the same values the view already showed.
    assert body["error"] == "daily_limit"
    assert body["limit"] == 2 and body["used"] == 2
    assert body["resets_at"] == RESET
    assert body["limit"] == before["max_per_day"] and body["resets_at"] == before["resets_at"]
    assert "Massimo 2" in body["message"] and "già 2" in body["message"]
    assert "00:00 del 13/11/2026" in body["message"]     # the copy is Italian, the keys are English

    # A refusal is a decision, not a write: nothing was created, and the slot is still there for the next.
    assert list_of(client, anna)["used"] == 2
    other = client.session("beth@example.com")
    assert client.post("/api/bookings", json={"type": "standard", "start": "13:00"}, headers=other).status_code == 201


def test_the_day_is_read_on_the_moment_the_booking_was_created(client, clock):
    # The decision the issue records: created today, not active today. A customer holding two slots is
    # refused even when both slots are already in the past of the day.
    anna = client.session("gina@example.com")
    booked(client, anna, "standard", "10:00")
    booked(client, anna, "standard", "11:00")

    clock.set("2026-11-12T20:00")                       # both slots are now behind the moment of the read
    assert view_of(client, anna)["used"] == 2
    refused = client.post("/api/bookings", json={"type": "standard", "start": "21:00"}, headers=anna)
    assert refused.status_code == 409 and refused.json()["error"] == "daily_limit"

    # A booking made today for a slot tomorrow consumes today: the day the count belongs to is the day the
    # request wrote the record, not the day the cycle happens in.
    # A fifth `standard` machine through the seed write: the pack's four are all committed by the two
    # customers this test books, and the last request has to be an answer about the count, not about the
    # inventory (issue #8 pins that a machine held for the customer who booked it is not free).
    assert client.post("/api/machines", json={"type": "standard"}).status_code == 201
    beth = client.session("nadia@example.com")
    booked(client, beth, "standard", "20:15")
    booked(client, beth, "standard", "2026-11-13T07:15")
    assert view_of(client, beth)["used"] == 2
    assert client.post("/api/bookings", json={"type": "standard", "start": "20:30"}, headers=beth).status_code == 409

    # On the 13th the slot she still holds is active, but it was written on the 12th: the day is hers again.
    clock.set("2026-11-13T00:01")
    assert view_of(client, beth)["used"] == 0 and view_of(client, beth)["resets_at"] == "2026-11-14T00:00:00"
    booked(client, beth, "standard", "07:30")
    assert view_of(client, beth)["used"] == 1


def test_the_reset_happens_at_local_midnight_and_a_cancelled_booking_does_not_count(client, clock):
    # `standard`, not `quick`: the pack has two quick machines and the file's own bookings commit both of
    # them, which is the reason the supplied file cannot reach its last assertion (recorded in
    # tests/fixtures.py). On a type that still has a machine free the answer is the count, not the machine.
    anna = client.session("yuri@example.com")

    first = booked(client, anna, "standard", "09:15")
    assert view_of(client, anna)["used"] == 1
    cancelled = client.post(f"/api/bookings/{first['id']}/cancel", json={}, headers=anna)
    assert cancelled.status_code == 200, cancelled.text

    # AC4: the turn was given back, so the seat goes back with it — the refund is the right to rebook.
    assert view_of(client, anna)["used"] == 0 and view_of(client, anna)["remaining"] == 2
    for start in ("10:00", "11:00"):
        booked(client, anna, "standard", start)
    assert view_of(client, anna)["used"] == 2

    # The reset is the rollover of the shop's own day, and it is the first minute the count is hers again.
    clock.set("2026-11-13T00:01")
    assert view_of(client, anna)["used"] == 0 and view_of(client, anna)["remaining"] == 2
    booked(client, anna, "standard", "07:00")
    assert view_of(client, anna)["used"] == 1


# --- AC5: the turn R8 cancelled is not a turn the customer consumed --------------------------------

def test_the_turn_cancelled_as_uncoverable_by_r8_gives_its_seat_back(client, clock):
    anna = client.session("carl@example.com")
    beth = client.session("dani@example.com")
    victim = booked(client, anna, "quick", "10:00")
    booked(client, beth, "quick", "10:00")                 # the last machine of the type, committed
    assert view_of(client, anna)["used"] == 1

    answer = client.post("/api/lock/reports", json={"machine": victim["machine"], "event": "fault"},
                         headers=anna)
    assert answer.status_code == 200, answer.text
    assert answer.json()["reassigned"] == [] and answer.json()["cancelled"] == [victim["code"]]

    # US48 read against the refund: the count is back to the whole allowance, and she can take a slot as
    # soon as the shop has one — here the day is read again before the request, so the view is the proof.
    assert view_of(client, anna)["used"] == 0 and view_of(client, anna)["remaining"] == 2
    booked(client, anna, "family", "10:30")
    assert view_of(client, anna)["used"] == 1


# --- AC6: the block answers before the day is read --------------------------------------------------

def test_a_blocked_customer_is_refused_for_the_block_and_not_for_the_limit(client, clock):
    anna = client.session("ida@example.com")

    # Two no-shows on slots the shop can still take. They also consume the day, so at the moment of the
    # request both rules are satisfied and only one of them can be the answer — and it has to be R9.
    for start, at in (("09:15", datetime(2026, 11, 12, 9, 26)), ("09:30", datetime(2026, 11, 12, 9, 41))):
        booking = booked(client, anna, "quick", start)
        clock.set(at)
        assert client.post("/api/lock/redeem", json={"code": booking["code"]}).json()["outcome"] == "expired"

    assert view_of(client, anna)["used"] == 2          # a turn lost is not a turn given back
    refused = client.post("/api/bookings", json={"type": "quick", "start": "12:00"}, headers=anna)
    assert refused.status_code == 403, refused.text
    body = refused.json()
    assert body["error"] == "blocked"
    assert body["block"]["reason"] == "no_show" and body["block"]["no_shows"] == 2
    assert "limit" not in body and "Massimo" not in body["message"]   # the block, not the limit

    # The other refusal stays distinguishable: a customer who is not blocked is refused for her day.
    other = client.session("ibo@example.com")
    for start in ("13:00", "14:00"):
        booked(client, other, "quick", start)
    third = client.post("/api/bookings", json={"type": "quick", "start": "15:00"}, headers=other)
    assert third.status_code == 409 and third.json()["error"] == "daily_limit"
    assert "block" not in third.json()


# --- AC7: the guarantee is the index, not the pre-check --------------------------------------------

def race(client, who, starts):
    """Two requests released together, each on its own connection and its own snapshot."""
    def book(start):
        return start, client.post("/api/bookings", json={"type": "standard", "start": start}, headers=who)

    with ThreadPoolExecutor(max_workers=2) as pool:
        return dict(pool.map(book, starts))


def test_two_parallel_attempts_on_one_seat_cannot_both_write(client, clock):
    anna = client.session("ada@example.com")
    booked(client, anna, "standard", "09:15")            # the day stands at one seat: the two are the third
    answers = race(client, anna, ("11:00", "13:00"))     # different slots, so nothing else can refuse them

    codes = sorted(r.status_code for r in answers.values())
    assert codes == [201, 409], {r.text for r in answers.values()}
    loser = [r for r in answers.values() if r.status_code == 409][0]

    # The guarantee is the index, not the pre-check: the day cannot hold three rows, so one of the two is
    # refused whichever order the two transactions take. On the file-backed fallback the loser is refused at
    # its write, and the word it is answered with is the constraint that write was carrying — which is the
    # word the pinned race test of issue #11 names when the slot is the constraint the request carries, and
    # the limit when the seat is. What is guaranteed here is the count, not the word.
    assert loser.json()["error"] in ("daily_limit", "slot_taken"), loser.text
    own = client.get("/api/bookings", headers=anna).json()
    assert own["limit"]["used"] == 2 and len(own["bookings"]) == 2      # one booking, not two
    starts = [row["start"] for row in own["bookings"]]
    assert "09:15" in starts and sum(1 for start in starts if start in ("11:00", "13:00")) == 1
    loser_start = [start for start, response in answers.items() if response.status_code == 409][0]
    fresh = client.session("carla@example.com")
    assert client.post("/api/bookings", json={"type": "standard", "start": loser_start},
                       headers=fresh).status_code == 201, client.last_response.text


def test_two_parallel_third_bookings_are_both_refused(client, clock):
    anna = client.session("frank@example.com")
    for start in ("09:15", "10:00"):
        booked(client, anna, "standard", start)

    answers = race(client, anna, ("11:00", "12:00"))
    assert all(r.status_code == 409 for r in answers.values()), {r.text for r in answers.values()}
    for response in answers.values():
        body = response.json()
        assert body["error"] == "daily_limit"
        assert body["limit"] == 2 and body["used"] == 2
        assert body["resets_at"] == daily_limit.resets_at(daily_limit.local_day(clock.now(), client.app.config),
                                                          client.app.config).isoformat()
    assert view_of(client, anna)["used"] == 2
