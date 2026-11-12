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

No I/O: `who` is the identity the sign-in resolves to, `booking` is the row, `surface` names the path the
report arrived on.
"""

# The three surfaces a taken fault can arrive on. `CLAIM` is the only one whose residue is narrower than R8.
DEVICE = "device"
CLAIM = "claim"
PANEL = "panel"


def entitled_booking(who, bookings) -> dict | None:
    """The record the report entitlement is read against (R7): the caller's own booking on that machine.

    `src/entitlements.py` answers `may_report` from the truthiness of this same list; here the record itself
    is what matters, because the rule is about that record and not about its existence, and `may_move` is read
    against it.
    """
    return next((row for row in bookings if row["email"] == who["email"]), None)


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
