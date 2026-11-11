"""Identity: email + one-time code, no password and no reset flow (US18).

Two steps on the seam, and each step accepts its own fields only:

- `POST /api/session` takes the email and issues the code. The code is shown in-app (addendum patch
  1): there is no email or SMS transport to write it to, and no inbox inside the shop to read it in.
  The response is the delivery channel.
- `POST /api/session/verify` redeems that code for the session token the customer is recognised by on
  the next visit (US19). The token is opaque: nothing in it is derived from the email or from the code.

The decision of this issue: the code is stored hashed with its expiry and surfaced only in the sign-in
response. Patch 1 makes in-app display the only delivery channel, and hashing is what lets the tests
assert single-use and expiry without keeping a plaintext credential that could leak into telemetry —
the repository holds a hash, an expiry and a `used_at` marker, never the code, so no read path can hand
a live credential back to a caller or to a log line.

AC3 is a separate promise from AC2: the code is a credential, so it never reaches a log line, a metric,
a trace or an error message. `src/telemetry.py` is the guard on the recording side; the refusals here
name the reason without echoing the code.

Two codes, never the same thing (AC6): the one-time code is the sign-in credential, the unlock code is
the booking's own numeric code, tied to one booking and displayed only inside that booking. They are
different shapes on purpose — 6 digits against 4 — so a test can tell them apart and so they can never
collide.

No password (AC1): the sign-in handler reads the email and nothing else, the identities table has no
password column, and there is no reset flow — a spent or an expired code is refused with 401 and the
caller asks for a new one.
"""

import hashlib
import secrets
from datetime import datetime, timedelta

from src.config import SEED

# The fields each step accepts. A password field does not exist in either (AC1).
SIGN_IN_FIELDS = ("email",)
VERIFY_FIELDS = ("email", "otp")

# The code is numeric because the keypad is numeric: the same shape the unlock code has, one digit
# group longer so the two can never be confused (AC6).
OTP_LENGTH = 6


def unexpected(body: dict, fields: tuple) -> list[str]:
    """The names in a request that are not part of this step's contract (AC1)."""
    return sorted(key for key in body if key not in fields)


def new_otp() -> str:
    """A fresh code. Not derived from the email: a credential that can be recomputed is not a credential."""
    return f"{secrets.randbelow(10 ** OTP_LENGTH):0{OTP_LENGTH}d}"


def hash_code(value: str) -> str:
    """The stored form of a code. What the repository keeps is this, never the code itself."""
    return hashlib.sha256(value.encode()).hexdigest()


def ttl_minutes(config: dict = SEED) -> int:
    """10 minutes, held in the seed configuration like every other number in this project."""
    return config["otp_ttl_minutes"]


def expires_at(created: datetime, config: dict = SEED) -> datetime:
    return created + timedelta(minutes=ttl_minutes(config))


def is_expired(expires_at: datetime, now: datetime) -> bool:
    """Expired at the minute it expires, not after it (AC4): the test advances exactly 10 minutes."""
    return now >= expires_at


def is_spent(row: dict) -> bool:
    """Single-use (AC4, US26 for the unlock code): the first verify is the only one that answers."""
    return bool(row.get("used_at"))


def new_token() -> str:
    """The persisted session token (US19): opaque, so nothing credential-shaped is inside it."""
    return secrets.token_urlsafe(24)


def is_numeric_code(value: str) -> bool:
    return value.isdigit()
