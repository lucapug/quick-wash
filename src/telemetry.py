"""Telemetry: the structured log lines, the journey trace and the one metric — never a credential.

The shape is docs/spec.md, Observability shape: the key journey (booking → redeem → cycle start →
cycle finish) instrumented end to end, one metric of customer-blocked events, and a trace identifier
shared by every log line and every metric attached to that journey. The trace is hashed from the
*internal booking id*, so it names the journey without naming the customer or a code, and it is
letters-only so it can never read as one of the two codes.

The invariant is the one issue #25 defines and this issue depends on: no customer email, no unlock
code, no one-time code and no credential may appear in telemetry. Two things make it hold rather than
being a promise:

1. `record` takes the request line, the status, the event name and the journey — never the body. A
   credential arrives in a body, so a body is never an input here, and the logged path is the path
   without its query.
2. `guard` is the assertion on what is recorded: no field named like a credential, and no recorded
   value shaped like one — four digits or more is the shape of both codes (both are 6 digits,
   `src/identity.py`), an `@` is the shape of an email. It refuses rather than
   redacts: a redacted credential is still a credential that got into a log line, so nothing is stored
   and nothing is printed when it fires.

The read (`GET /api/logs/recent`) is the reviewer's view of these lines. It answers to a caller with no
session because what it can answer with is the request line: the recorder never saw a body, so there is
nothing customer-shaped to read back.
"""

import hashlib
import json
import re

from src.clock import Clock

# The field names that are credentials. They are never arguments of `record`.
CREDENTIAL_KEYS = ("email", "otp", "code", "password", "token", "secret", "pin")

# The shapes: the numeric code (both codes are 6 digits, `src/identity.py`) and the email.
CODE_SHAPE = re.compile(r"\d{4,}")
EMAIL_SHAPE = re.compile(r"@")

# Only the values that come from a request can carry a credential. The trace and the timestamp are the
# recorder's own: the trace is hashed from an internal id and carries no digit.
CHECKED_FIELDS = ("event", "path", "detail", "message", "metric")

RECENT_LIMIT = 50

# 0-9 to a-j, so a trace identifier can never read as a numeric code.
LETTERS = str.maketrans("0123456789", "abcdefghij")


class CredentialInTelemetry(Exception):
    """A line that would carry a credential. It is refused: nothing is stored and nothing is printed."""

    def __init__(self, field: str, value) -> None:
        super().__init__(f"telemetry refuses {field}: {value!r} is a credential")
        self.field = field
        self.value = value


def guard(entry: dict) -> dict:
    """The assertion, on the fields that could carry a credential."""
    for field, value in entry.items():
        if field in CREDENTIAL_KEYS:
            raise CredentialInTelemetry(field, value)
        text = str(value)
        if field in CHECKED_FIELDS and (CODE_SHAPE.search(text) or EMAIL_SHAPE.search(text)):
            raise CredentialInTelemetry(field, value)
    return entry


class Telemetry:
    def __init__(self, clock: Clock | None = None, limit: int = RECENT_LIMIT, emit=None) -> None:
        self.clock = clock or Clock()
        self.limit = limit
        self.emit = emit if emit is not None else self._print
        self.entries: list[dict] = []
        self.journeys: dict[str, str] = {}
        self.metrics = {"customer_blocked_total": 0}

    def journey(self, key) -> str:
        """The trace identifier for one journey, shared by every line and metric attached to it.

        Idempotent, because the identifier is resolved once and then carried: `Application.trace` resolves it
        from the booking, the application hands it back to the recorder for the lines of the same journey, and
        the device carries it from the redemption answer to every report it sends (issue #13, AC 7). Hashing a
        value that is already an identifier would name a second journey for the same booking, so an identifier
        is taken as it is and a key — the internal booking id, or the request line — is hashed to one.
        """
        name = str(key)
        if name.startswith("t-"):
            return name
        if name not in self.journeys:
            self.journeys[name] = "t-" + hashlib.sha256(name.encode()).hexdigest()[:10].translate(LETTERS)
        return self.journeys[name]

    def record(self, method: str, path: str, status: int, event: str = "request", journey=None,
               detail: str | None = None) -> dict:
        entry = {"event": event, "method": method, "path": path.split("?")[0], "status": status,
                 "at": self.clock.now().isoformat(),
                 "trace": self.journey(journey if journey is not None else f"{method} {path}")}
        if detail:
            entry["detail"] = detail
        return self._append(entry)

    def count(self, name: str, journey=None) -> int:
        """The metric of customer-blocked events. It carries the same trace as the lines of its journey."""
        self.metrics[name] = self.metrics.get(name, 0) + 1
        self._append({"event": "metric", "metric": name, "value": self.metrics[name],
                      "at": self.clock.now().isoformat(),
                      "trace": self.journey(journey if journey is not None else f"metric {name}")})
        return self.metrics[name]

    def recent(self, limit: int | None = None) -> list[dict]:
        return self.entries[-(limit or self.limit):]

    def view(self) -> dict:
        return {"entries": self.recent(), "metrics": dict(self.metrics)}

    def _append(self, entry: dict) -> dict:
        guard(entry)
        self.entries.append(entry)
        if len(self.entries) > self.limit:
            del self.entries[:len(self.entries) - self.limit]
        self.emit(entry)
        return entry

    def _print(self, entry: dict) -> None:
        print(json.dumps(entry))
