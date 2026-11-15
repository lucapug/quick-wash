"""What a fault that is taken is allowed to change, read per seam path (R7, R8).

Three modules hold the three decisions a fault report is made of, and this is the third:
`src/entitlements.py` decides who may report a machine, `src/machine_states.py` declares the hop into
`maintenance`, this module decides which of the bookings attached to that machine the report may move.
`Application.apply_fault` is the only place the decision runs, and it runs it with the surface the report
arrived on, so there is one reading of the rule per path and no copy of it.

R8 as `docs/spec.md` states it: a future booking moves to a free machine of the same type, earliest start
first, with a new code; a booking the shop cannot cover is cancelled with the turn refunded and an incident
recorded, and no booking may remain attached to a machine in `maintenance`. That full reading runs on the
two paths where the fault is not a claim about a record:

- the **device boundary**, `POST /api/lock/reports` — the fault is the machine's own fact as the controller
  names it, so every booking the fact makes unhonourable is moved (pinned by `tests/test_journey.py`);
- the **owner panel**, `POST /api/owner/machines/<code>/maintenance` — the owner is the identity entitled to
  cancel or reassign a booking (US56), so the toggle runs the same core.

The **claim surface**, `POST /api/machines/<code>/report`, is the one place the rule is read narrower, and
the narrowness is a fact about the entitlement rather than a convenience: the claim is admitted by a booking
record — that is what `src/entitlements.py` reads it against — and the seam cannot let the claim rewrite the
record that admits it. The claim carries the gate and the hop, and the booking it was read against stays on
the machine (issue #11, slice b2, AC3). Because `src/availability.py` never frees a machine in
`maintenance`, nothing can be attached to it from then on, so the machine keeps *exactly* that one booking:
the entitled pre-report one.

The tension with R8's closing sentence is recorded here rather than resolved by bending the rule: the two
readings are pinned by tests on the two paths — AC3 of issue #11 slice b2 on the claim surface, R8 in full on
the device boundary — and no test can be satisfied by moving the other's assertion. The fork is visible from
outside the seam (this file is asserted in
`tests/integration/test_maintenance_never_booked_coverage.py`), and it is flagged for the human decision.

The pass itself is deterministic, and determinism is what makes R8 demonstrable (issue #13, AC 9): the
affected records are processed earliest-start-first with ties broken by the order they were created, and the
target is the lowest-numbered free machine of the type. Both are decisions here, in one line each, so the
demo, the test and the reviewer see the same pass and not a coin.

No I/O: `who` is the identity the sign-in resolves to, `booking` is the row, `surface` names the path the
report arrived on.
"""

from src import machine_states
from src.repository import parse


# The three surfaces a taken fault can arrive on. `CLAIM` is the only one whose residue is narrower than R8.
DEVICE = "device"
CLAIM = "claim"
PANEL = "panel"

# The states a standing customer's record can be in: the code has been spent at the keypad, so the turn has
# begun. `confirmed` is not one of them — a turn that has not been opened is still a promise, and the claim
# that admits itself on that promise is the record the claim cannot rewrite.
STANDING_STATES = ("unlocked", "running")

# The incident a taken report leaves behind, per surface, in one line per surface.
#
# `fault` is the fact the report asserts, so it is recorded on the two paths where the report is a statement
# about the machine as such: the customer's claim and the device's own fact. The panel is the third surface
# and the only one that is not a report about a fault — the owner is deciding to take a machine out of
# service, and that decision already records its own incident (`maintenance`) in `handle_owner_maintenance`.
# `None` is therefore not a missing record: it is what keeps one action from being written twice, and it is
# what keeps the panel's incident list the owner reads the list of the owner's own actions.
INCIDENT_KIND = "fault"
INCIDENT_KINDS = {DEVICE: INCIDENT_KIND, CLAIM: INCIDENT_KIND, PANEL: None}


def incident_kind(surface: str) -> str | None:
    """Which incident a taken report records, read from the surface it arrived on.

    The fault incident is written on the claim surface and on the device boundary; the panel reports nothing
    here because its own action is already recorded as the owner's decision. This is the whole of the
    decision, so the incident a report leaves behind cannot depend on which handler ran.
    """
    return INCIDENT_KINDS.get(surface)


def entitled_booking(who, bookings) -> dict | None:
    """The record the report entitlement is read against (R7): the caller's own booking on that machine.

    `src/entitlements.py` answers `may_report` from the truthiness of this same list; here the record itself
    is what matters, because the rule is about that record and not about its existence, and `may_move` is read
    against it.

    The list is every row the machine carries for that identity, whatever state the record is in — live,
    `cancelled`, `expired`, `closed` — because R7's "or had" is a fact about a persisted booking, not a
    session flag: a turn that is over still entitles the person who had it. The earliest row is the record
    named here, so the same reading is what `may_move` is checked against on the claim surface.
    """
    return next((row for row in bookings if row["email"] == who["email"]), None)


def standing_at(booking) -> bool:
    """The customer already standing at the machine (US40): the code was redeemed at the keypad.

    A turn whose code has been spent is a fact at the machine, not a promise in the app, so the person it
    belongs to cannot be sent through a support process — there is no staff in this shop. The pass moves her:
    the machine is released from her turn and the cycle still ahead of the moment the fault is reported goes
    with the record to the machine the pass names.
    """
    return bool(booking["redeemed_at"]) and booking["state"] in STANDING_STATES


def pass_order(bookings) -> list:
    """The order the pass runs in: earliest start first, ties broken by the order the records were created.

    One machine holds one turn that still owes a cycle, so this is the whole of the ordering decision R8
    needs in order to be testable and demoable, and it is the order the incidents are written in.
    """
    return sorted(bookings, key=lambda row: (parse(row["start_time"]), parse(row["created_at"]), row["id"]))


def lowest_numbered(machines) -> list:
    """The target order: the lowest-numbered free machine of the type, so the pass is reproducible."""
    return sorted(machines, key=lambda row: (number_of(row["code"]), row["code"]))


def number_of(code: str) -> int:
    """The machine number read off the code: `M2` is lower than `M10`, which the code order alone is not."""
    digits = "".join(character for character in str(code) if character.isdigit())
    return int(digits) if digits else 0


def still_attached(bookings) -> list:
    """AC5: the records the pass left on the fenced machine, read after every pass on every surface.

    Where R8 runs in full the answer is empty. On the claim surface it is exactly the record the entitlement
    was read against — the fork recorded above, flagged for the human decision, not a second reading of the
    rule.
    """
    return [str(row["id"]) for row in bookings if row["state"] in machine_states.HOLDING_STATES]


def may_move(booking, surface: str, admitted_by: dict | None = None) -> bool:
    """Whether a taken fault report may move `booking` off the machine. In one line per surface.

    `admitted_by` is the record the entitlement was read against, as `entitled_booking` names it. On the claim
    surface the answer is no for that record and yes for every other booking, so the machine keeps exactly the
    one booking AC3 names. On the device boundary and on the panel the answer is R8 as the spec states it.
    """
    if surface == CLAIM:
        # The record that admits the claim is not rewritten by it.
        return admitted_by is None or booking["id"] != admitted_by["id"]
    return True
