"""The notification, and where it lives: inside the app, and nowhere else.

docs/spec.md puts every notification outside the app out of scope — no email, no SMS, no push — so a
notification is a row the customer reads back on the app's own read, `GET /api/notifications`. That read is
a pattern, not a ninth contract entry (the eight `tests/conftest.py` pins stay the eight), and it is
entitlement-gated the same way the booking surface is: a notification belongs to the customer the booking
belongs to, so a caller with no session has nothing to read (401) and a customer reads only her own.

Two words name the same fact, and the mapping is here, in one place, so the two tests that pin the two
spellings cannot drift:

- `reassignment` is the incident word, the noun the incident list and the answer of the report carry — the
  word `tests/integration/test_r10_turnover_and_cleaning_coverage.py` pins on the response of a claim;
- `reassigned` is the word the customer reads in the app, the word
  `tests/integration/test_r08_reassignment.py` pins on the read.

One row stores the fact; the mapping is the only place the second word exists. Nothing in the row is a
credential: the notification names the machine and the booking, and the unlock code appears only in the copy
shown to the customer the booking belongs to — the code lives inside that booking and inside her own
notification, never in a public view and never in telemetry.

No I/O: `row` is the persisted notification, `machine_code` is the machine the customer has to walk to.
"""

# The fact as it is stored, in the incident vocabulary, and the word the app shows the customer.
# `reassignment` and `cancellation` are the words the incident list and the answer of a report carry; the
# app shows the customer the participle, which is the word she reads on her own notification read.
APP_WORD = {"reassignment": "reassigned", "cancellation": "cancelled"}

# Two spellings of one stored fact: the incident word the seam answers with on the report, and the word the
# customer reads on her own notification read. Which one a view carries is chosen here, once.
INCIDENT = "incident"
APP = "app"

# The vocabulary the read answers with, in the app's words. Nothing else is a notification.
APP_KINDS = ("reassigned", "cancelled")


def app_word(kind: str) -> str:
    """The word the customer reads, in one line."""
    return APP_WORD.get(kind, kind)


def message(kind: str, machine_code: str, code: str | None = None) -> str:
    """The copy, in Italian, naming the machine the customer has to walk to.

    US38 is the reason the machine is in the sentence: a notification that does not name the machine would
    send her to the one the report was about. The refund copy says the honest thing — nothing of the type is
    free, the turn is given back, she can book again at once — because there is no money in this product and
    the refund is the right to rebook, not a sum.
    """
    if kind == "reassignment":
        return f"Sei spostato su {machine_code}: nuovo codice {code}"
    return f"Nessuna macchina libera di questo tipo su {machine_code}: prenotazione cancellata, " \
           "il turno è rimborsato e puoi prenotare di nuovo subito"


def view(row, machine_code: str, spelling: str = APP) -> dict:
    """One notification as the app reads it, or as the report that wrote it answers with."""
    return {
        "id": str(row["id"]),
        "kind": row["kind"] if spelling == INCIDENT else app_word(row["kind"]),
        "booking": str(row["booking_id"]),
        "machine": machine_code,
        "message": row["message"],
        "created_at": row["created_at"],
    }
