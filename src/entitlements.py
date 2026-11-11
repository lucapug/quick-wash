"""Entitlements on the booking surface (issue #10, slice a): the decision, kept pure.

The whole entitlement in one line: the booking's own customer, or the owner panel, which is allowed to
cancel or reassign a booking (US56). Everything else is refused.

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
the id (a copied link, a shared screen) is still refused. The cancellation window (R4) is issue #15:
this slice carries the entitlement only.

No I/O here: `who` is the identity the session resolves to, `booking` is the row or None.
"""

# The two refusals, as the decision names them.
MISSING_SESSION = 401
NOT_ENTITLED = 403
ALLOWED = 200


def may_touch(who: dict | None, booking: dict | None) -> bool:
    """The entitlement, in one line."""
    if who is None or booking is None:
        return False
    return booking["email"] == who["email"] or bool(who.get("is_owner"))


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
