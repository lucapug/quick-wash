"""What the pinned race test of issue #11 (slice b1) cannot show on its own.

`tests/integration/test_r05_no_overbooking.py` is the file the issue provides and it runs byte-identical:
one behaviour, one test — two concurrent requests for one slot, exactly one booking, the loser answered with
alternatives, and the machine read back through the machine-scoped query. A race test cannot also pin the
*shape* of what the loser is offered, because the shape only matters for the request the persistence layer
refused, and the race decides which request that is.

So this file pins the three things AC2 states and the pinned test only reads:

- **the bound**: the loser's 409 carries at most three alternatives — the decision #47 preserves — and every
  one of them is a slot of the type the loser asked for, on the grid, earliest first: bounded and valid, not
  merely non-empty;
- **the refusal with the race removed from the way**: book the slot once so only one machine of the type is
  left as a candidate, then release the two requests together. Both pre-checks name that one machine,
  because each request reads the state as it was when its own request began, so the answer is the
  persistence refusal whichever request loses. That is the same outcome the pinned test asserts, reached
  without depending on which request the scheduler happens to run first — which is what makes the pinned
  test a fence rather than a coin: the guarantee is the UNIQUE (machine_id, start_time) index;
- **what a refusal leaves behind**: nothing written for the loser, and the machine carrying exactly the
  record the winner's request created.

Through the seam only: no repository call, no internal function, no mock other than the clock the
application is given as a dependency (docs/spec.md, Testing Decisions).
"""

from concurrent.futures import ThreadPoolExecutor

from src import rules
from src.domain import time as start_times


def race(client, sessions, start):
    """Two requests for the same type and slot, released together, each on its own connection."""
    def book(session):
        return session, client.post("/api/bookings", json={"type": "quick", "start": start}, headers=session)

    with ThreadPoolExecutor(max_workers=2) as pool:
        return dict(pool.map(book, sessions))


def grid_of(client, type_key) -> set:
    """The slots of the type the board could answer with, as the same helper names them."""
    return {start_times.slot(point) for point in
            start_times.valid_start_times(client.clock.now().date(), type_key, client.app.config)}


def test_the_loser_is_answered_with_at_most_three_valid_alternatives(client, seed):
    anna = client.session("anna@example.com")
    beth = client.session("beth@example.com")
    answers = race(client, [anna, beth], "14:00")
    codes = sorted(r.status_code for r in answers.values())
    assert codes == [201, 409], {s.email: r.text for s, r in answers.items()}

    loser = [r for r in answers.values() if r.status_code == 409][0].json()
    alternatives = loser["alternatives"]
    assert alternatives, "AC2 asks for alternatives, not only for a refusal"
    assert len(alternatives) <= rules.LOSER_ALTERNATIVES, "at most three, the bound the decision preserves"
    assert alternatives == sorted(alternatives), "the loser is offered them earliest first"
    assert all(point in grid_of(client, "quick") for point in alternatives), \
        "every alternative is a grid slot of the type the loser asked for"


def test_the_refusal_is_the_persistence_layer_s_whenever_one_machine_can_hold_the_slot(client, seed):
    # The slot is already held by one machine of the type, so the second machine is the only candidate left
    # and both racing requests must fight for it: the pre-check cannot be what decides, because the two
    # requests read the same state and name the same machine.
    ada = client.session("ada@example.com")
    held = client.post("/api/bookings", json={"type": "quick", "start": "15:00"}, headers=ada)
    assert held.status_code == 201

    anna = client.session("anna@example.com")
    beth = client.session("beth@example.com")
    answers = race(client, [anna, beth], "15:00")
    codes = sorted(r.status_code for r in answers.values())
    assert codes == [201, 409], {s.email: r.text for s, r in answers.items()}

    loser = [r for r in answers.values() if r.status_code == 409][0].json()
    assert loser["error"] == "slot_taken" and loser["enforced_by"] == "persistence layer", loser
    assert len(loser["alternatives"]) <= rules.LOSER_ALTERNATIVES and loser["alternatives"]


def test_a_refusal_writes_nothing_and_the_machine_keeps_exactly_one_record(client, seed):
    ada = client.session("ada@example.com")
    held = client.post("/api/bookings", json={"type": "quick", "start": "16:00"}, headers=ada)
    first = held.json()

    anna = client.session("anna@example.com")
    beth = client.session("beth@example.com")
    answers = race(client, [anna, beth], "16:00")
    winner = [r for r in answers.values() if r.status_code == 201][0].json()
    loser = [r for r in answers.values() if r.status_code == 409][0]

    # Three machines of the type can hold the same slot on three different machines — the assignment is per
    # machine, never per slot — but the two racing requests fought for one machine, so that machine carries
    # exactly one record: the winner's.
    assert winner["machine"] != first["machine"], "the winner took the machine still free for the slot"
    assert [row["id"] for row in client.get(f"/api/bookings?machine={winner['machine']}").json()] == [winner["id"]]
    for session, response in answers.items():
        own = client.get("/api/bookings", headers=session).json()["bookings"]
        assert (response.status_code == 201) == bool(own), f"{session.email}: {own}"
    assert client.get(f"/api/machines/{winner['machine']}").json()["state"] == "reserved"
    assert client.get(f"/api/machines/{first['machine']}").json()["state"] == "reserved"
