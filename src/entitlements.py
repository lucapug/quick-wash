"""Entitlements on the booking surface (issue #10, slice a) and on the fault report (issue #10, slice b):
the decision, kept pure.

Two entitlements, both in one line each. The booking entitlement: the booking's own customer, or the
owner panel, which is allowed to cancel or reassign a booking (US56). The report entitlement (R7): the
fact that the caller has or had a booking on that machine — a report cannot be made by somebody who
never had a turn on it, because that is how the mechanism would be abused to take a machine out of
circulation for someone else (US41).

Two facts the tests assert from outside the seam:

- **403 is a wrong entitlement, 401 is a missing session.** They must be externally distinguishable, so
  they cannot be the same status, and the copy differs: "Non è tua" for the entitlement, "Entra con
  email e codice" for the session. A caller with no session has no identity to be entitled with, so it
  cannot be answered with 403 — the observer of issue #6 keeps its reads for exactly this reason.
- **The refusal body cannot say whether the booking exists.** The same body answers "this booking is
  not yours" and "this booking is not there", so the seam cannot be used to find out which ids are
  real by asking for one that is not. Nothing in it names the booking, the customer or a code. Only the
  owner panel — which is entitled to know that a booking exists — gets a 404.

Enforcement lives here, at the seam, and not in a UI that hides a control: a caller who already holds
the id (a copied link, a shared screen) or the machine code is still refused. The cancellation window
(R4) is issue #15: this slice carries the entitlement only. On the report side this slice carries the
entitlement plus its residue — an accepted report drives `maintenance`; the reassignment it triggers
(R8) is its own issue.

The owner-panel entitlement (issue #10, slice c) is the third holder: the panel is open to the
identity the sign-in marks with the owner flag (US58), and to no other caller — not the customer who
holds a booking id, not the reviewer with no session, because the panel is not a read, it is the owner's
own surface. The same decision as the booking surface, so the same two statuses: 403 for a wrong
entitlement, 401 for a missing session.

No I/O here: `who` is the identity the session resolves to, `booking` is the row or None,
`had_booking` is the fact that the caller had a turn on that machine (the rows, or their truthiness).
"""

# The two refusals, as the decision names them.
MISSING_SESSION = 401
NOT_ENTITLED = 403
ALLOWED = 200

# The answer to a report that is entitled: the report is taken and its consequence is applied to the
# machine, so the seam acknowledges it as an accepted request rather than as a plain read. 202 is what
# keeps "accepted" and "refused" two different outcomes a test can read from outside.
REPORT_ACCEPTED = 202
UNKNOWN_MACHINE = 404


def may_touch(who: dict | None, booking: dict | None) -> bool:
    """The booking entitlement, in one line."""
    if who is None or booking is None:
        return False
    return booking["email"] == who["email"] or bool(who.get("is_owner"))


def may_enter_panel(who: dict | None) -> bool:
    """US58, in one line: the owner panel is open to the identity the sign-in marks as the owner.

    Nothing else is read — not a booking, not a machine, not a flag the caller could send in a body.
    A caller with no session has no identity to be entitled with, so it cannot hold this entitlement
    either: it is answered 401, and that is the reason the two statuses must stay two.
    """
    if who is None:
        return False
    return bool(who.get("is_owner"))


def may_report(who: dict | None, had_booking) -> bool:
    """R7, in one line: the entitlement to report a machine is the fact that you have or had a booking on it.

    `had_booking` is the caller's bookings on that machine — current or past. A caller with no session
    cannot hold it, because there is no identity to read the fact against: the report entitlement needs
    a name on the booking, which is the same reason R9 needs one.
    """
    if who is None:
        return False
    return bool(had_booking)


def missing_session() -> dict:
    """401: the caller has no session to be entitled with."""
    return {"error": "sign_in_required", "message": "Entra con email e codice"}


def refusal() -> dict:
    """403, and the same body for a booking that is not yours and for one that does not exist.

    Two fields only, and neither of them can carry an id, an email or a code: a body that could tell
    the two cases apart would be an existence oracle (AC1).
    """
    return {"error": "not_your_booking",
            "message": "Non è tua: puoi leggere e cancellare solo le prenotazioni tue"}


def not_found() -> dict:
    """The one case where the seam may say a booking does not exist: the owner panel."""
    return {"error": "unknown_booking", "message": "Prenotazione sconosciuta"}


def report_refusal() -> dict:
    """403 on the report surface: not your machine, and no report is taken from somebody who never had a turn on it."""
    return {"error": "not_your_machine",
            "message": "Non è tua: puoi segnalare solo una macchina su cui hai o hai avuto una prenotazione"}


def panel_refusal() -> dict:
    """403 on the owner panel: the panel is the owner's, and a customer cannot reach it.

    The copy is the entitlement copy — "non è tuo" — and not the sign-in copy, so a test can tell the
    two outcomes apart from outside the seam. Nothing in the body names the machine or the booking the
    request was addressed to: the refusal is the decision, not a fact about what exists.
    """
    return {"error": "not_the_owner",
            "message": "Non è tuo: il pannello proprietario è riservato al proprietario"}


def unknown_machine() -> dict:
    """A machine the seam does not have. A machine code is public information (US42), so the seam may say this."""
    return {"error": "unknown_machine", "message": "Macchina sconosciuta"}
