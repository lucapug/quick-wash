"""Repository: the persistence layer the seam talks to.

Race protection (R5) lives here as a UNIQUE constraint on (machine_id, start_time), not as a
pre-check: a second insert for a machine and slot that is already committed fails and the caller
answers with the alternatives.

Machine rows store id, code, type, state, changed_at — no price, no duration, no venue: the tariff
and the cycle length are read through the type registry in src/domain.py.

The identity tables are the ones this layer owns, and their shape is part of AC1: `identities` holds the
email and the owner flag and nothing else — there is no password column in any table, because there is
no password in the product. `otp` holds the *hash* of the one-time code with its expiry and the moment it
was spent, so a plaintext credential is never readable back out of the database: single-use and expiry
are facts of the row, which is what the tests assert through the seam. `sessions` holds the opaque token
the customer is recognised by on the next visit (US19), so the token is stored as given and never
reconstructed from the email.
"""

import json
from datetime import datetime

from src import identity
from src.config import SEED

TABLES = {
    "settings": ("key TEXT PRIMARY KEY, value TEXT NOT NULL", "key TEXT PRIMARY KEY, value TEXT NOT NULL"),
    "identities": (
        "id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, is_owner INTEGER NOT NULL DEFAULT 0",
        "id SERIAL PRIMARY KEY, email TEXT UNIQUE NOT NULL, is_owner INTEGER NOT NULL DEFAULT 0",
    ),
    "otp": (
        "id INTEGER PRIMARY KEY, email TEXT NOT NULL, code_hash TEXT NOT NULL, created_at TEXT NOT NULL, "
        "expires_at TEXT NOT NULL, used_at TEXT",
        "id SERIAL PRIMARY KEY, email TEXT NOT NULL, code_hash TEXT NOT NULL, created_at TEXT NOT NULL, "
        "expires_at TEXT NOT NULL, used_at TEXT",
    ),
    "sessions": (
        "token TEXT PRIMARY KEY, email TEXT NOT NULL, created_at TEXT NOT NULL",
        "token TEXT PRIMARY KEY, email TEXT NOT NULL, created_at TEXT NOT NULL",
    ),
    "machines": (
        "id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, type TEXT NOT NULL, state TEXT NOT NULL, changed_at TEXT NOT NULL",
        "id SERIAL PRIMARY KEY, code TEXT UNIQUE NOT NULL, type TEXT NOT NULL, state TEXT NOT NULL, changed_at TEXT NOT NULL",
    ),
    "bookings": (
        "id INTEGER PRIMARY KEY, machine_id INTEGER NOT NULL, email TEXT NOT NULL, start_time TEXT NOT NULL, "
        "end_time TEXT NOT NULL, code TEXT UNIQUE NOT NULL, state TEXT NOT NULL, tokens INTEGER NOT NULL, "
        "redeemed_at TEXT, created_at TEXT NOT NULL, UNIQUE (machine_id, start_time)",
        "id SERIAL PRIMARY KEY, machine_id INTEGER NOT NULL, email TEXT NOT NULL, start_time TEXT NOT NULL, "
        "end_time TEXT NOT NULL, code TEXT UNIQUE NOT NULL, state TEXT NOT NULL, tokens INTEGER NOT NULL, "
        "redeemed_at TEXT, created_at TEXT NOT NULL, UNIQUE (machine_id, start_time)",
    ),
    "no_shows": (
        "id INTEGER PRIMARY KEY, email TEXT NOT NULL, occurred_at TEXT NOT NULL, booking_id INTEGER",
        "id SERIAL PRIMARY KEY, email TEXT NOT NULL, occurred_at TEXT NOT NULL, booking_id INTEGER",
    ),
    "incidents": (
        "id INTEGER PRIMARY KEY, kind TEXT NOT NULL, email TEXT, machine_id INTEGER, booking_id INTEGER, "
        "created_at TEXT NOT NULL, detail TEXT NOT NULL",
        "id SERIAL PRIMARY KEY, kind TEXT NOT NULL, email TEXT, machine_id INTEGER, booking_id INTEGER, "
        "created_at TEXT NOT NULL, detail TEXT NOT NULL",
    ),
}


def iso(moment: datetime) -> str:
    return moment.isoformat()


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


class Repository:
    def __init__(self, db, config: dict = SEED) -> None:
        self.db = db
        self.seed_config = config

    def reset(self) -> None:
        for name, variants in TABLES.items():
            self.db.execute(f"DROP TABLE IF EXISTS {name}")
            dialect = 0 if self.db.backend == "sqlite" else 1
            self.db.execute(f"CREATE TABLE {name} ({variants[dialect]})")
        self.seed()

    def seed(self) -> None:
        for key, value in self.seed_config.items():
            self.db.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, json.dumps(value)))
        counter = 0
        now = iso(datetime.now())
        for type_key, count in self.seed_config["types"].items():
            for _ in range(count):
                counter += 1
                self.db.execute(
                    "INSERT INTO machines (code, type, state, changed_at) VALUES (?, ?, ?, ?)",
                    (f"M{counter}", type_key, "available", now),
                )

    def settings(self) -> dict:
        rows = self.db.rows("SELECT key, value FROM settings")
        return {row["key"]: json.loads(row["value"]) for row in rows}

    def machine_counts(self) -> dict:
        rows = self.db.rows("SELECT type, COUNT(*) AS count FROM machines GROUP BY type")
        return {row["type"]: row["count"] for row in rows}

    def machines(self) -> list[dict]:
        return self.db.rows("SELECT * FROM machines ORDER BY code")

    def machine(self, code: str) -> dict | None:
        return self.db.one("SELECT * FROM machines WHERE code = ?", (code,))

    def machine_by_id(self, machine_id: int) -> dict | None:
        if machine_id is None:
            return None
        return self.db.one("SELECT * FROM machines WHERE id = ?", (machine_id,))

    def create_machine(self, type_key: str, at: datetime) -> dict:
        """Insert a machine of a type; nothing else about it can be passed in."""
        used = {row["code"] for row in self.db.rows("SELECT code FROM machines")}
        counter = len(used) + 1
        while f"M{counter}" in used:
            counter += 1
        self.db.execute("INSERT INTO machines (code, type, state, changed_at) VALUES (?, ?, ?, ?)",
                        (f"M{counter}", type_key, "available", iso(at)))
        return self.machine(f"M{counter}")

    def set_machine_state(self, machine_id: int, state: str, at: datetime) -> None:
        self.db.execute("UPDATE machines SET state = ?, changed_at = ? WHERE id = ?", (state, iso(at), machine_id))

    def candidate_machines(self, type_key: str) -> list[dict]:
        return self.db.rows(
            "SELECT * FROM machines WHERE type = ? AND state IN ('available', 'finished', 'cleaning_required') ORDER BY code",
            (type_key,),
        )

    def create_booking(self, machine_id: int, email: str, start: datetime, end: datetime,
                       code: str, tokens: int, now: datetime) -> dict | None:
        """Insert under the UNIQUE constraint; None means the slot was taken (R5)."""
        try:
            self.db.execute(
                "INSERT INTO bookings (machine_id, email, start_time, end_time, code, state, tokens, created_at) "
                "VALUES (?, ?, ?, ?, ?, 'confirmed', ?, ?)",
                (machine_id, email, iso(start), iso(end), code, tokens, iso(now)),
            )
        except Exception:
            self.db.rollback()
            return None
        return self.db.one("SELECT * FROM bookings WHERE code = ?", (code,))

    def booking_by_code(self, code: str) -> dict | None:
        return self.db.one("SELECT * FROM bookings WHERE code = ?", (code,))

    def bookings_for(self, email: str) -> list[dict]:
        return self.db.rows("SELECT * FROM bookings WHERE email = ? ORDER BY start_time", (email,))

    def bookings_on_machine(self, machine_id: int, email: str | None = None) -> list[dict]:
        if email is None:
            return self.db.rows("SELECT * FROM bookings WHERE machine_id = ? ORDER BY start_time", (machine_id,))
        return self.db.rows("SELECT * FROM bookings WHERE machine_id = ? AND email = ? ORDER BY start_time",
                            (machine_id, email))

    def booking_on_machine(self, machine_id: int, start: datetime) -> dict | None:
        return self.db.one(
            "SELECT * FROM bookings WHERE machine_id = ? AND start_time = ?", (machine_id, iso(start))
        )

    def open_booking(self, machine_id: int) -> dict | None:
        """The booking a device report about this machine belongs to: the one still attached to it."""
        return self.db.one(
            "SELECT * FROM bookings WHERE machine_id = ? AND state IN ('confirmed', 'unlocked', 'running') "
            "ORDER BY start_time", (machine_id,)
        )

    def set_booking_state(self, booking_id: int, state: str) -> None:
        self.db.execute("UPDATE bookings SET state = ? WHERE id = ?", (state, booking_id))

    def record_open(self, booking_id: int, now: datetime) -> None:
        """The moment the machine was opened. A device fact: an attempt refused by the grace window is
        still an open, and `idle_open` is measured from it. The code is consumed only by a redemption
        inside the window, which is what the booking state records (US26)."""
        self.db.execute("UPDATE bookings SET redeemed_at = ? WHERE id = ?", (iso(now), booking_id))

    def get_or_create_identity(self, email: str, is_owner: bool) -> dict:
        row = self.db.one("SELECT * FROM identities WHERE email = ?", (email,))
        if row:
            return row
        self.db.execute("INSERT INTO identities (email, is_owner) VALUES (?, ?)", (email, 1 if is_owner else 0))
        return self.db.one("SELECT * FROM identities WHERE email = ?", (email,))

    def issue_otp(self, email: str, code_hash: str, created: datetime, expires: datetime) -> dict:
        """Store the hashed code with its expiry. One live code per identity: the previous one is gone.

        The plaintext code is never passed in, so it is never stored and never readable back: the row is
        the fact the tests assert (single-use, expiry), not a copy of a credential.
        """
        self.db.execute("DELETE FROM otp WHERE email = ?", (email,))
        self.db.execute(
            "INSERT INTO otp (email, code_hash, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (email, code_hash, iso(created), iso(expires)),
        )
        return self.db.one("SELECT * FROM otp WHERE email = ? ORDER BY id DESC", (email,))

    def find_otp(self, email: str, code_hash: str) -> dict | None:
        """Look a code up by its hash: the only way a code can be matched here."""
        return self.db.one("SELECT * FROM otp WHERE email = ? AND code_hash = ? ORDER BY id DESC",
                           (email, code_hash))

    def mark_otp_used(self, otp_id: int, now: datetime) -> None:
        """AC4: the first verify is the only one. The row is spent from this moment."""
        self.db.execute("UPDATE otp SET used_at = ? WHERE id = ?", (iso(now), otp_id))

    def create_session(self, email: str, now: datetime) -> str:
        """The persisted session token (US19): opaque, stored as given, never built from the email."""
        token = identity.new_token()
        self.db.execute("INSERT INTO sessions (token, email, created_at) VALUES (?, ?, ?)", (token, email, iso(now)))
        return token

    def session_owner(self, token: str) -> dict | None:
        return self.db.one("SELECT * FROM sessions WHERE token = ?", (token,))

    def record_no_show(self, email: str, now: datetime, booking_id: int) -> None:
        self.db.execute("INSERT INTO no_shows (email, occurred_at, booking_id) VALUES (?, ?, ?)",
                        (email, iso(now), booking_id))

    def no_shows(self, email: str) -> list:
        return [parse(row["occurred_at"]).date() for row in
                self.db.rows("SELECT occurred_at FROM no_shows WHERE email = ?", (email,))]

    def record_incident(self, kind: str, now: datetime, detail: str, email: str = None,
                        machine_id: int = None, booking_id: int = None) -> dict:
        self.db.execute(
            "INSERT INTO incidents (kind, email, machine_id, booking_id, created_at, detail) VALUES (?, ?, ?, ?, ?, ?)",
            (kind, email, machine_id, booking_id, iso(now), detail),
        )
        return self.db.one("SELECT * FROM incidents ORDER BY id DESC")

    def incidents(self) -> list[dict]:
        return self.db.rows("SELECT * FROM incidents ORDER BY id")

    def next_code(self, now: datetime) -> str:
        used = {row["code"] for row in self.db.rows("SELECT code FROM bookings")}
        candidate = 1000 + len(used) + 1
        while str(candidate) in used:
            candidate += 1
        return str(candidate)

