"""The cancellation window (R4): the decision, kept pure.

docs/spec.md states R4 in one line — free cancellation up to 15 minutes before start, refused after
that, with the booking's current state shown — and this module is that line as data: `start`, `now` and
the seed are inputs, the answer is data, no repository and no clock object. `src/app.py` runs it at the
seam on both paths that can cancel — the customer's `POST /api/bookings/<id>/cancel` and the owner
panel's manual write (US56) — so the two cannot answer differently for the same booking.

**The cutoff is inclusive**: `now <= start - 15 min`. "Up to 15 minutes before start" makes the boundary
minute itself a case, so the minute at `start - 15` has to be cancellable and the minute at `start - 14`
has to be refused; that is what turns the rule into something a test can read rather than a mood. The
number is the seed's `cancel_window_minutes` (issue #5, AC7: every number is read back over HTTP), never
a literal inside a handler.

**What the refusal shows** (US46, AC2, AC5): the state as it already is, unchanged, because a refusal is
a decision and not a write. `state` is the state the booking holds the machine in — `reserved` for a
booking still `confirmed`, which is exactly what the customer is being told the shop has already committed
— and `booking_state` is the word on the booking row. The message states the cutoff in minutes, because
US44 asks for an explanation, not for a status code.

**Two things R4 does not do**, stated here because they are the two things a reviewer checks:

- it applies **no buffer** to a cancellation: the machine is released through the declared hop
  `reserved -> available` at the moment of the request, so the slot is bookable by the next customer
  immediately. The turnover buffer stays the hop that follows a cycle actually run (R10); charging a
  buffer for a turn that was given back would block availability for somebody who never arrived;
- a cancellation is **not a no-show** (R9): nothing is written to the no-show counter, because the turn
  was returned rather than lost, and R9 counts turns lost.

The window is read before the state test, so the refusal names the rule that refused, and both refusals
carry the same shape: the state shown, the cutoff in minutes, the explanation.
"""

from datetime import timedelta

from src.config import SEED

# The number is the seed's, not a literal here: it is the number the seam reads back.
CUTOFF_KEY = "cancel_window_minutes"

# The only booking state a cancellation can still act on. Every other state is shown, not rewritten.
CANCELLABLE_STATES = ("confirmed",)

# The two 409s this rule answers with: the window (R4) and the state the booking is already in.
WINDOW_REFUSED = "cancellation_window"
STATE_REFUSED = "not_cancellable"


def cutoff_minutes(config: dict = SEED) -> int:
    """R4's number, as the seed holds it."""
    return int(config[CUTOFF_KEY])


def cutoff_at(start, config: dict = SEED):
    """The last minute at which a cancellation is still free: `start - 15`."""
    return start - timedelta(minutes=cutoff_minutes(config))


def may_cancel(start, now, config: dict = SEED) -> bool:
    """R4, in one line — inclusive at the boundary, which is what makes the boundary testable."""
    return now <= cutoff_at(start, config)


def minutes_to_start(start, now) -> int:
    """What the refusal has to state: the minutes left, measured backwards from `start`."""
    return int((start - now).total_seconds() // 60)


def state_of(booking, machine) -> str:
    """The booking's current state as the state machine reads it: the state the booking holds the machine in."""
    return machine["state"] if machine is not None else booking["state"]


def refusal(booking, machine, config: dict, now, start, error: str = WINDOW_REFUSED) -> dict:
    """The 409 body: the state shown unchanged, the cutoff in minutes, and the explanation.

    `start` is the parsed start of the booking: this module does no parsing and reads no row, so the
    caller hands it the instant it has already resolved. Nothing is written for a refusal, so the body
    can only show what the tables already said — and both cancellation paths read this one builder, so
    they cannot disagree on it.
    """
    cutoff = cutoff_minutes(config)
    remaining = minutes_to_start(start, now)
    body = {"error": error, "cutoff_minutes": cutoff,
            "state": state_of(booking, machine), "booking_state": booking["state"]}
    if error == WINDOW_REFUSED:
        body["minutes_to_start"] = remaining
        body["message"] = (f"Cancellazione gratuita fino a {cutoff} minuti prima dell'inizio: mancano "
                           f"{remaining} minuti, la macchina è già impegnata")
    else:
        body["message"] = f"La prenotazione non è cancellabile: stato {booking['state']}"
    return body
