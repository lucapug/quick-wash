"""What slice c of #11 (issue #48) can be asserted through the seam, and what it cannot.

The test the issue supplies is `tests/integration/test_refusal_alternatives_ux.py`, created byte-identical
and never adjusted. Its three criteria — the bounded set, earliest first, of the same type, on the grid, and
only slots that are actually bookable — are implemented in `src/alternatives.py` and asserted below through
the seam. What cannot be asserted is the test's **premise**, and the reason is not a missing implementation:
it is four facts the pack already pins, each read back as an outcome below.

1. **The assignment is per machine, never per slot.** R5 refuses two bookings on *one machine*, and
   `tests/integration/test_booking_creation_happy_path_coverage.py` pins "a second customer for the same type
   and slot is named on another machine (R5, slice b)" with a `201`. A request is a loser only when the
   machine it is named for is the one the persistence layer has already committed for that slot — which is
   what a race produces (the pinned race test of #11 b1) and not what a second sequential request produces.
2. **The seed the test's comment writes needs three machines of the type** — one booked at 14:00 plus two
   free later — while `tests/conftest.py` pins two. With two, the machine booked at 14:00 is held for its
   customer, so the only machine that could answer the second request is the one that was free at 14:00 as
   well, and the request is not refused.
3. **Bookable at 14:00 and bookable at the clock are the same fact for a machine.** `src/availability.py`
   refuses a machine for a state reason (`maintenance`, or a buffer that still covers the moment) or for the
   point it already owes a turn for. A buffer that covers a later hour covers the clock the fixture is fixed
   at too, so no seed puts a machine outside the bookable set at 14:00 and inside it at 14:15: the test's
   "two free quick machines later" cannot be a machine that is not bookable at 14:00.
4. **A machine can be given once**, so AC2's two halves together cap the count below 3 on the pack: the
   filter lists at most one slot per machine of the type it can name, and the pack has two — the bound of 3 is
   a ceiling the inventory reaches first. That is the reason the Decision bounded the count instead of letting
   it depend on shop load: below the set is read on a pack big enough for the count to reach the bound, and on
   the pack as it is the loop the supplied test writes cannot be guaranteed for more than the first slot.

The shape is the second decision the file carries: `alternatives` as records with `start` and `type` cannot be
pinned on the same key together with the tests of issues R1+R2 and #11 (slice b2), which read
`sorted(alternatives)` and `point in grid`. The record shape is scoped to the loser path — the path this issue
states — so both readings hold, and the split is asserted below rather than merged.

The supplied test is marked `xfail` in `tests/fixtures.py` with this reason, so the gate runs green while the
contradiction stays visible: nothing in the supplied file is changed and nothing in `src/` is bent to make it
pass. When a human corrects one side of the contradiction, the entry there has to be removed; the two possible
corrections are the supplied file (a race instead of a second sequential request, and the slot-string shape)
or the assignment decision R5 states.

Through the seam only: no repository call, no internal function, no mock other than the clock the application
is given as a dependency (docs/spec.md, Testing Decisions).
"""

from concurrent.futures import ThreadPoolExecutor

from datetime import datetime

from src import rules
from src.domain import time as start_times


def race(client, sessions, start):
    """Two requests for the same type and slot, released together, each on its own connection (R5)."""
    def book(session):
        return session, client.post("/api/bookings", json={"type": "quick", "start": start}, headers=session)

    with ThreadPoolExecutor(max_workers=2) as pool:
        return dict(pool.map(book, sessions))


def grid_of(client, type_key) -> set:
    """The grid points of the type, as the same helper names them (issue R1+R2, slice a)."""
    return {start_times.slot(point) for point in
            start_times.valid_start_times(client.clock.now().date(), type_key, client.app.config)}


def book(client, session, start, type_key="quick"):
    return client.post("/api/bookings", json={"type": type_key, "start": start}, headers=session)


def loser_of(client, sessions, start="14:00"):
    """The request the persistence layer refused: the only path the issue's shape belongs to."""
    answers = race(client, sessions, start)
    refused = [r for r in answers.values() if r.status_code == 409]
    assert len(refused) == 1, {s.email: r.text for s, r in answers.items()}
    loser = refused[0]
    assert loser.json()["error"] == "slot_taken", loser.text
    assert loser.json()["enforced_by"] == "persistence layer", loser.text
    return loser, [s for s, r in answers.items() if r.status_code == 409][0]


# --- what the criteria are, asserted where the pack can produce them -----------------------------

def test_the_loser_is_answered_with_records_earliest_first_of_the_same_type(client, seed):
    anna = client.session("anna@example.com")
    beth = client.session("beth@example.com")
    loser, _ = loser_of(client, [anna, beth])
    alts = loser.json()["alternatives"]

    assert 0 < len(alts) <= rules.LOSER_ALTERNATIVES, loser.text
    assert [a["start"] for a in alts] == sorted(a["start"] for a in alts), "earliest first"
    assert all(a["type"] == "quick" for a in alts), "from the same type"
    assert all(a["start"].endswith(("00", "15", "30", "45")) for a in alts), "15' quantization"
    assert all(a["start"] in grid_of(client, "quick") for a in alts), "a grid point the shop can honour"
    assert alts[0]["start"] > "14:00", "the slot the refusal is about is not an alternative"


def test_every_listed_alternative_is_bookable_in_the_order_it_is_listed(client, seed):
    """AC2 as the predicate the assignment step answers on, on a pack big enough for the loop.

    A third `quick` machine is added through the seed write (`POST /api/machines`: the machine registry has no
    screen). With the pack's two, one machine is held for the slot the refusal is about and the other can be
    given once, so AC2 holds for one alternative only; with a machine the shop can still give twice, the
    bounded set is the set of slots that are free, and each of them is taken in the order it is listed.
    """
    assert client.post("/api/machines", {"type": "quick"}).status_code == 201

    anna = client.session("anna@example.com")
    beth = client.session("beth@example.com")
    loser, beth = loser_of(client, [anna, beth])
    alts = loser.json()["alternatives"]

    # The count is the smaller of the bound and what this customer can still take that day (R11).
    remaining = client.get("/api/bookings", headers=beth).json()["limit"]["remaining"]
    assert alts and len(alts) <= min(rules.LOSER_ALTERNATIVES, remaining), loser.text

    # Nothing in `maintenance`, nothing inside a buffer, nothing already committed: the window answers None for
    # every point the refusal names.
    points = {point["start"]: point["reason"] for point in
             client.get("/api/availability?window_hours=6&type=quick").json()["types"]["quick"]["slots"]}
    for a in alts:
        assert points.get(a["start"]) is None, f"{a['start']}: {points.get(a['start'])}"
        taken = book(client, beth, a["start"])
        assert taken.status_code == 201, f"{a['start']}: {taken.text}"
        assert taken.json()["type"] == "quick", "the machine named is of the type asked for"


def test_on_the_pack_the_loop_the_test_runs_cannot_be_guaranteed(client, seed):
    """AC2's promise needs more machines of the type than the bound, and the pack has two.

    The first alternative is bookable. A second one is offered only when a second machine of the type is
    still free for it, and on the pack the race has already taken one of the two: the loser's own
    transaction read the state as it was when its request began, so the filter can count a machine the
    winner had committed. On a pack big enough for the bound the set and the loop agree (the test above);
    on the pack as it is they cannot, and that is the shape of the assertion the supplied file writes.
    """
    anna = client.session("anna@example.com")
    beth = client.session("beth@example.com")
    loser, beth = loser_of(client, [anna, beth])
    alts = loser.json()["alternatives"]

    first = book(client, beth, alts[0]["start"])
    assert first.status_code == 201, first.text
    assert len(alts) <= min(rules.LOSER_ALTERNATIVES, seed["types"]["quick"]), alts
    if len(alts) > 1:
        # The machine that serves the first slot now holds it: nothing is left for the second slot.
        refused = book(client, beth, alts[1]["start"])
        assert refused.status_code == 409, refused.text
        assert refused.json()["error"] == "no_machine_free", refused.text


def test_the_record_shape_is_the_loser_path_s_and_the_other_refusals_keep_theirs(client, seed):
    """The tension the decision carries: one key, two shapes, and the scope is the path this issue states."""
    client.clock.set(datetime(2026, 11, 12, 20, 30))
    ada = client.session("ada@example.com")
    refused = client.post("/api/bookings", json={"type": "family", "start": "21:00"}, headers=ada)
    assert refused.status_code == 409, refused.text
    assert refused.json()["reason"] == "would_overrun_closing"
    assert refused.json()["alternatives"][0] == "2026-11-13T07:00", "the shape the tests of R1+R2 pin"


# --- what the supplied test cannot be, read as outcomes ------------------------------------------

def test_the_second_request_for_the_same_type_and_slot_is_not_a_loser(client, seed):
    anna = client.session("anna@example.com")
    beth = client.session("beth@example.com")
    first = book(client, anna, "14:00")
    assert first.status_code == 201, first.text
    second = book(client, beth, "14:00")
    assert second.status_code == 201, second.text
    assert second.json()["machine"] != first.json()["machine"], "two slots, two machines (R5, slice b)"

    # The premise the file's comment writes — one machine booked at 14:00 plus two free later — needs three
    # machines of the type, and tests/conftest.py pins the pack at two.
    assert seed["types"]["quick"] == 2, seed["types"]


def test_the_bookable_set_at_the_clock_is_the_bookable_set_at_the_slot_asked(client, seed):
    """No seed makes a machine unbookable at 14:00 and bookable later: the state half of `free_at` is monotone."""
    # With an empty day every machine of the type is free at every grid point the shop can honour, at the clock
    # and at 14:00 alike. A machine refused at a moment is refused for a state reason or for the point it owes a
    # turn for, and a buffer that covers 14:00 covers the clock too (R10): so the "two free quick machines
    # later" of the comment cannot be a machine that is not bookable at 14:00.
    board = client.get("/api/availability").json()
    quick = {row["type"]: row for row in board["types"]}["quick"]
    assert quick["machines"] == 2 and quick["free"] == 2

    window = client.get("/api/availability?window_hours=6&type=quick").json()["types"]["quick"]["slots"]
    reasons = {point["start"]: point["reason"] for point in window}
    assert reasons["14:00"] is None and all(reason is None for reason in reasons.values())

    # And from the other side: a machine committed for a turn holds it, so it is never bookable for another
    # point — which is what the loop cannot survive on two machines.
    ada = client.session("ada@example.com")
    held = book(client, ada, "14:00")
    assert client.get(f"/api/machines/{held.json()['machine']}").json()["assignable"] is False
    window = client.get("/api/availability?window_hours=6&type=quick").json()["types"]["quick"]["slots"]
    assert {point["start"]: point["reason"] for point in window}["14:00"] == "all_machines_busy"
