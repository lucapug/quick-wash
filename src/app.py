"""The HTTP boundary of the backend: the single seam every test uses.

Handlers return (status, payload). Paths are the contract fixed by tests/conftest.py (SEAM_PATHS)
and mirrored in docs/api-contract.md: POST /api/session, GET /api/availability, POST /api/bookings,
GET /api/bookings, POST /api/lock/redeem, POST /api/lock/reports, GET /api/machines,
GET /api/incidents. The one addition R6 needs is the per-machine read, `GET /api/machines/<code>`
(AC 8): a reviewer watches the transitions live. It is a pattern, not a ninth contract path, so it
is resolved by `pattern_route` and never added to `ROUTES`.

The contract fixes one path per entry, so the seed write for the machine inventory sits on the same
path as its read (`POST /api/machines`, resolved through SEED_WRITE): the machine registry has no
screen, the write accepts a type and nothing else, and the machine answers with the type's tariff
and duration — never with a field of its own.

The public availability read is shaped in `src/availability.py`: the board for a request that names
nothing, the window for a request that names a window or a type (issue #8). The query parameters of the
public read join the body in `src/server.py`, and the request line telemetry sees stays the path without
them. `is_assignable` is not a second rule: it delegates to the predicate the public view answers on, so
the board and the window cannot drift.

Keys are English, user-facing copy is Italian. Nothing here logs a customer email, an unlock code
or a one-time code.

The identity layer (issue #9): `POST /api/session` takes the email only and shows the one-time code
in-app (addendum patch 1), `POST /api/session/verify` redeems it for the persisted session token, and
the code is stored hashed with its expiry so single-use and expiry are facts of the row (AC4). AC7 is
the gate this module enforces: no booking is created for a caller without a session, so the anonymous
caller is no longer a customer that can book — it is the reviewer's observer, and it keeps its reads.
The telemetry read is the reviewer's view of the request lines; the recorder itself (`src/telemetry.py`)
is what keeps a credential out of them (AC3).

The booking surface of one booking (issue #10, slice a): `GET /api/bookings/<id>` and
`POST /api/bookings/<id>/cancel` are patterns, not extra contract paths, and they are entitlements —
the customer's own booking, or the owner panel. The decision is `src/entitlements.py`: 403 for a wrong
entitlement, 401 for a missing session, and a refusal body identical for a booking that is not yours
and for one that is not there, so the seam is never an existence oracle.

The report surface of one machine (issue #10, slice b): `POST /api/machines/<code>/report` is a pattern
for the same reason — the contract fixes one entry per entry point and `POST /api/lock/reports` is that
entry. It carries R7, the entitlement to report, plus its residue: a report that is taken drives the
machine's `maintenance` state through the R6 table. The gate is the same decision as the booking surface
(401 for a missing session, 403 for a wrong entitlement), so the two paths cannot drift on the permission;
what they can differ on is the residue the report is allowed to write, and that is one decision in
`src/faults.py` read from the surface, not a copy of the rule per path. What an accepted report answers is
202: the report is a claim the seam takes, not a fact a device reports, and its consequence is applied to the
machine. Reassignment (R8) is its own issue, and the claim surface is the one place its residue is narrower:
the claim is admitted by a booking record, so it cannot rewrite the record that admits it, and the machine
keeps exactly its entitled pre-report booking (issue #11, slice b2, AC3). The decision is `src/faults.py`, in one predicate, run by `apply_fault`.

Issue #11, slice b1 is the persistence constraint and the loser path only: the UNIQUE
`(machine_id, start_time)` index is what decides a race for one slot, the loser is answered 409 with the
bounded set of alternatives (at most three, `src/rules.py`), and the fence is the pinned race test run
against a real database on two real connections. Two things the test needs and the layer owns are recorded
in `src/db.py`: one connection per request-thread, so two concurrent requests are two transactions, and one
transaction per request with its snapshot taken at the moment the request begins, so the pre-check can name
the same machine to both and the constraint is what refuses one of them.

Issue #11, slice c is the shape of that loser answer (`src/alternatives.py`): the bounded set, earliest
first, of the type the request asked for, and only slots the customer can actually take — the same
predicate the assignment step answers on, never `maintenance`, never inside a buffer, never a slot the type
already owes a turn for, never a slot that would put her over R11. The record shape is scoped to the loser
path: the calendar and no-machine refusals keep the slot strings the tests of issues R1+R2 and #11 b2 pin.

Issue #11, slice b2 is the maintenance invariant alone: a machine in `maintenance` can never be assigned a
booking, so when it is the only candidate for a slot the seam answers 409 and nothing is created on it. The
fence is the assignment step reading `src/availability.py` — the same predicate the public view answers on,
not a pre-check and not a control the front-end hides — and the machine is read through the machine-scoped
bookings query, `GET /api/bookings?machine=<code>`, which answers the record as a read open to a caller with
no session can answer it: the machine is public information (US42), so the shape carries no customer and no
code (US22), exactly as the incident list answered to the observer.

The owner panel (issue #10, slice c): the five surfaces the panel owns — the status board, the machine
list, the incident list, the maintenance toggle and the manual cancellation of a booking — are the
`/api/owner/` surface, patterns rather than contract paths, so `ROUTES` stays exactly the eight entries
tests/test_seam.py pins. Access to them is the owner flag (US58), decided by `owner_gate` before the
handler runs: 401 for a caller with no session, 403 for a session that is not the owner. The gate is
enforcement at the seam, not a control the front-end hides — a customer who already holds the machine
code or the booking id is refused on the panel path exactly as on the customer path, and a refusal
writes nothing.
"""

from datetime import datetime, timedelta

from src import alternatives, availability, cancellation, domain, entitlements, faults, machine_states, rules
from src import identity as credentials
from src.clock import Clock
from src.domain import time as start_times
from src.config import SEED
from src.repository import Repository, parse
from src.telemetry import Telemetry

ROUTES = {
    ("POST", "/api/session"): "session",
    ("GET", "/api/availability"): "availability",
    ("POST", "/api/bookings"): "booking",
    ("GET", "/api/bookings"): "bookings",
    ("POST", "/api/lock/redeem"): "redeem",
    ("POST", "/api/lock/reports"): "report",
    ("GET", "/api/machines"): "machines",
    ("GET", "/api/incidents"): "incidents",
}

SEAM_PATHS = sorted(f"{method} {path}" for method, path in ROUTES)

# The write that belongs to the seed inventory, on the contract path of its read. It takes `type`
# and nothing else: there is no per-machine price or duration field to override, so the only thing
# a caller can do is add a machine of a type (demo mode, no machine-registry screen).
SEED_WRITE = {"POST /api/machines": "create_machine"}

# R6: the table is not written here. It lives in src/machine_states.py, in one place, so the code and
# the docs mirror can be checked against each other. `Application.transition` is the only writer of a
# machine state and it consults that table for every hop.
PER_MACHINE_READ = ("GET", "/api/machines/")

# Three reads are patterns, not contract paths, so `ROUTES` stays exactly the eight entries
# tests/test_seam.py pins: the state of one machine (issue #6, AC8), the verification of a one-time
# code, and the telemetry read. The contract fixes the sign-in request; the code it showed in-app is
# redeemed on its sub-path, and the log lines are read on theirs.
PATTERNS = {"POST /api/session/verify": "verify", "GET /api/logs/recent": "logs"}

# The booking surface of one booking (issue #10, slice a): the read of a booking and its cancellation.
# Patterns, not contract paths, so `ROUTES` stays exactly the eight entries tests/test_seam.py pins —
# the contract fixes one entry per entry point, and `GET /api/bookings` is the customer's list while
# `GET /api/bookings/<id>` is one booking that belongs to that customer.
BOOKING_SURFACE = ("GET", "/api/bookings/")
BOOKING_CANCEL = ("POST", "/api/bookings/")

# The report surface of one machine (issue #10, slice b): the report read through the machine it is about.
# A pattern, not a ninth contract path. Only the two reports that name a customer are entitlement-gated:
# the machine a device reports on is not the caller's, the machine a person reports on is — R7.
REPORT_SURFACE = ("POST", "/api/machines/")
REPORT_KINDS = ("fault", "occupied")

# The owner panel (issue #10, slice c): the surfaces the panel owns, and the two things it can write.
# Patterns, not contract paths, so `ROUTES` stays exactly the eight entries tests/test_seam.py pins.
# Three reads — the status board (US53), the machine list, the incident list (US57) — and two writes:
# the maintenance toggle (US54) and the manual cancellation of a booking (US56). The two writes are
# addressed to what the URL names, the same way the booking and the report surfaces are.
OWNER_PANEL = "/api/owner/"
OWNER_READS = ("status-board", "machines", "incidents")
OWNER_RESOURCES = ("machines", "bookings")
OWNER_WRITES = ("maintenance", "cancel")
# US54 asks for both directions of the toggle. `maintenance` is reached through the table, `available`
# is the declared hop back out, so the toggle never writes a hop the table does not declare.
TOGGLE_STATES = ("maintenance", "available")

# The reviewer's observer (issue #6, AC8): a caller with no session can still watch the shop live — the
# public availability view, the state of one machine, the incident list. It is not an identity, and that
# is AC7 of this issue: a booking needs a session, and the only thing that mints one is the verification
# of a one-time code. The observer has no bookings of its own, so it has no customer entitlements to
# lose, and it carries no email — the incident list answered to it is the one with no customer in it.
# A signed-in customer keeps its entitlements the other way round: the owner board and the incident list
# stay closed to customers (tests/test_journey.py).
OBSERVER = {"email": None, "is_owner": 0, "is_observer": True}


def hhmm(moment: datetime) -> str:
    return moment.strftime("%H:%M")


class Application:
    def __init__(self, db, clock: Clock | None = None, config: dict = SEED) -> None:
        self.db = db
        self.clock = clock or Clock()
        self.repo = Repository(db, config)
        self.repo.reset()
        self.config = self.repo.settings()
        self.telemetry = Telemetry(clock=self.clock)
        self.journey = None  # the journey the request being handled belongs to (shared trace id)

    # --- seam ---------------------------------------------------------------

    def handle(self, method: str, path: str, body: dict | None = None,
               headers: dict | None = None) -> tuple[int, dict | list]:
        name = (ROUTES.get((method, path)) or SEED_WRITE.get(f"{method} {path}")
                or self.pattern_route(method, path))
        # The journey this request belongs to, resolved by the handler: the trace identifier is shared by
        # every log line and every metric attached to that journey (docs/spec.md, Observability shape).
        self.journey = None
        if name is None:
            self.telemetry.record(method, path, 404)
            return 404, {"error": "not_found", "message": f"Percorso sconosciuto: {path}"}
        # R10 and AC 3: the two buffer hops are carried by time, not by a caller, so a request
        # resolves the elapsed buffers before answering. That is what makes the state read a live read.
        # R5 (issue #11, slice b1): the request reads one snapshot, its own transaction, opened before
        # anything is decided and committed at its end. Two concurrent requests for the same slot then
        # read the same state, so the guarantee is the UNIQUE (machine_id, start_time) index refusing the
        # second insert — not a pre-check that could have been read before the other request wrote.
        with self.db.snapshot():
            self.resolve_buffers(self.clock.now())
            try:
                status, payload = getattr(self, f"handle_{name}")(body or {}, headers or {}, path)
            except InvalidTransition as bad:
                # R6: invalid transitions are rejected, never silently coerced. The attempted hop is in
                # the body, and the machine keeps the state the table had declared for it.
                payload = {"error": "invalid_transition", "from": bad.current, "to": bad.to,
                           "transition": f"{bad.current} -> {bad.to}",
                           "declared": sorted(machine_states.TRANSITIONS.get(bad.current, set())),
                           "message": f"Transizione non valida: {bad.current} -> {bad.to}"}
                if bad.event:
                    payload["event"] = bad.event
                self.telemetry.record(method, path, 409, event=name)
                return 409, payload
            # The request line is all telemetry sees here: the path without its query, the status, the name
            # of the handler and the journey. Never the body, which is where a credential arrives (AC3).
            self.telemetry.record(method, path, status, event=name, journey=self.journey)
            return status, payload

    def pattern_route(self, method: str, path: str) -> str | None:
        """The reads that are patterns, not contract paths: one machine (AC 8), the code, the logs.

        The report surface of one machine is a pattern too: `POST /api/lock/reports` is the contract entry
        for a report, and the machine it is about is the same decision addressed to the machine. So is the
        owner panel (issue #10, slice c): the contract fixes the owner's two reads, and the panel's own
        surfaces are the pattern over them.
        """
        name = PATTERNS.get(f"{method} {path}")
        if name:
            return name
        surface = self.owner_surface(method, path)
        if surface is not None:
            return f"owner_{surface[0].replace('-', '_')}"
        if method == REPORT_SURFACE[0] and path.startswith(REPORT_SURFACE[1]) and path.endswith("/report"):
            return "machine_report"
        if method == PER_MACHINE_READ[0] and path.startswith(PER_MACHINE_READ[1]):
            return "machine"
        if path.startswith(BOOKING_SURFACE[1]):
            tail = path[len(BOOKING_SURFACE[1]):].strip("/")
            if not tail:
                return None
            if method == BOOKING_SURFACE[0]:
                return "booking_read"
            if method == BOOKING_CANCEL[0] and tail.endswith("/cancel"):
                return "cancel"
        return None

    def owner_surface(self, method: str, path: str) -> tuple[str, str | None] | None:
        """Which panel surface the request addresses, and what it names.

        The read surfaces name nothing; the two write surfaces are addressed to a machine or to a
        booking — `POST /api/owner/machines/m1/maintenance`, `POST /api/owner/bookings/b1/cancel` — and
        they are refused before anything the panel would do runs, so a request a UI would render as
        clickable is still refused (AC3).
        """
        if not (path or "").startswith(OWNER_PANEL):
            return None
        tail = path[len(OWNER_PANEL):].strip("/").split("/")
        if method == "GET" and len(tail) == 1 and tail[0] in OWNER_READS:
            return tail[0], None
        if method == "POST" and len(tail) == 3 and tail[0] in OWNER_RESOURCES and tail[2] in OWNER_WRITES:
            return tail[2], tail[1]
        return None

    def resolve_buffers(self, now) -> None:
        """The two hops time triggers: `finished -> available` after the turnover buffer, `cleaning_required
        -> available` after the cleaning buffer (R10, AC 3, addendum patch 2). Both are declared hops."""
        for machine in self.repo.machines():
            key = machine_states.BUFFER_HOPS.get(machine["state"])
            if key is None:
                continue
            if now - parse(machine["changed_at"]) >= timedelta(minutes=self.config[key]):
                self.transition(machine["id"], "available", now)

    # --- identity (issue #9) -------------------------------------------------

    def handle_session(self, body, headers, path=None):
        """AC1, AC2: the sign-in request takes the email only, and the code is the answer.

        There is no password field to read, so any other name in the body is refused rather than
        tolerated — that is what makes "no password exists in the API" a fact a test can check, and not
        a field that is quietly ignored. The code is generated here, hashed for storage, and surfaced in
        the response: patch 1 of the addendum makes in-app display the only delivery channel, so there
        is no transport to write the code to. It is never echoed back in a refusal (AC3).
        """
        extra = credentials.unexpected(body, credentials.SIGN_IN_FIELDS)
        if extra:
            return 400, {"error": "field_not_allowed", "fields": extra,
                         "message": "Il sign-in accetta solo l'email: non c'è una password da recuperare"}
        email = body.get("email")
        if not email:
            return 400, {"error": "email_required", "message": "Serve un'email per entrare"}
        who = self.repo.get_or_create_identity(email, email == self.config["owner_email"])
        now = self.clock.now()
        code = credentials.new_otp()
        row = self.repo.issue_otp(email, credentials.hash_code(code), now, credentials.expires_at(now, self.config))
        return 200, {
            "email": email,
            "otp": code,
            "displayed_in_app": bool(self.config["otp_displayed_in_app"]),
            "expires_in_minutes": credentials.ttl_minutes(self.config),
            "is_owner": bool(who["is_owner"]),
            "token": None,
            "message": "Codice mostrato in-app: nessun'email, nessun SMS",
        }

    def handle_verify(self, body, headers, path=None):
        """AC4, AC5: the code is redeemed once, inside its 10 minutes, for the persisted session token.

        The four outcomes are: the code matches and is granted; the code is spent; the code is expired;
        the code does not match. All three refusals are 401 and none of them repeats the code — the code
        is a credential, and an error message that echoes it is a leak (AC3).
        """
        extra = credentials.unexpected(body, credentials.VERIFY_FIELDS)
        if extra:
            return 400, {"error": "field_not_allowed", "fields": extra,
                         "message": "La verifica accetta l'email e il codice: non c'è una password"}
        email, code = body.get("email"), body.get("otp")
        if not email or not code:
            return 400, {"error": "email_and_code_required", "message": "Serve l'email e il codice mostrato in-app"}
        row = self.repo.find_otp(email, credentials.hash_code(code))
        if row is None:
            return 401, {"error": "code_not_valid", "message": "Codice non valido: chiede un nuovo codice"}
        now = self.clock.now()
        if credentials.is_spent(row):
            return 401, {"error": "code_already_used", "message": "Il codice è già stato usato: chiede un nuovo codice"}
        if credentials.is_expired(parse(row["expires_at"]), now):
            return 401, {"error": "code_expired", "ttl_minutes": credentials.ttl_minutes(self.config),
                         "message": "Il codice è scaduto: chiede un nuovo codice"}
        self.repo.mark_otp_used(row["id"], now)
        who = self.repo.get_or_create_identity(email, email == self.config["owner_email"])
        token = self.repo.create_session(email, now)
        return 200, {"email": email, "token": token, "is_owner": bool(who["is_owner"]),
                      "session_persisted": True,
                      "message": "Entra: il token resta e ti riconosce alla prossima visita"}

    def handle_logs(self, body, headers, path=None):
        """AC3: the telemetry read, and the reason it is safe to answer without a session.

        The recorder never takes a request body, so what this read can show is the request line, the
        trace identifier and the metric. A credential has no path into it: it is refused at the guard in
        `src/telemetry.py`, before anything is stored or printed.
        """
        return 200, self.telemetry.view()

    def trace(self, booking) -> str | None:
        """The journey the request belongs to (docs/spec.md, Observability shape): the internal booking
        id, never the customer and never a code. `src/telemetry.py` turns it into the trace identifier
        shared by every log line and every metric attached to that journey.
        """
        if booking is None:
            return None
        self.journey = self.telemetry.journey(booking["id"])
        return self.journey

    def who_is_asking(self, headers) -> dict:
        """Who the seam is answering: a customer with a session, or the observer without one.

        AC7 lives here. The token is what makes a caller a customer, and the only thing that mints one is
        the verification of a code; the persisted session is what recognises the same customer on the next
        visit (US19). A caller with no token at all is the reviewer watching the shop live (issue #6,
        AC8): it keeps its reads and loses the right to book. A token that does not resolve is nobody.
        """
        token = (headers or {}).get("Authorization", "").removeprefix("Bearer ")
        if not token:
            return dict(OBSERVER)
        session = self.repo.session_owner(token)
        if session is None:
            return None
        return self.repo.get_or_create_identity(session["email"], session["email"] == self.config["owner_email"])

    def customer(self, headers) -> dict | None:
        """A caller that can act as a customer: the observer cannot book, because it has no session."""
        who = self.who_is_asking(headers)
        return None if who is None or who.get("is_observer") else who

    def may_observe(self, who) -> bool:
        """A signed-in customer never reads the owner panel. The observer has no session to begin with,
        and AC 8 asks for that reviewer to watch the state machine live."""
        return who is None or bool(who.get("is_observer")) or bool(who.get("is_owner"))

    # --- entitlements on the booking surface (issue #10, slice a) ------------

    def booking_entitlement(self, who, booking) -> tuple[int, dict | None]:
        """The gate, in one place: 401 for a missing session, 403 for a wrong entitlement.

        AC1 lives here. For a caller who is not entitled the answer is the same body whether the
        booking exists or not, so the seam cannot be used to find out which ids are real by asking
        for one that is not. Only the owner panel — entitled to know a booking exists, because the
        owner cancels or reassigns a booking (US56) — gets the 404.
        """
        if who is None:
            return entitlements.MISSING_SESSION, entitlements.missing_session()
        if entitlements.may_touch(who, booking):
            return entitlements.ALLOWED, None
        if booking is None and who.get("is_owner"):
            return 404, entitlements.not_found()
        return entitlements.NOT_ENTITLED, entitlements.refusal()

    def booking_id_of(self, path) -> int | None:
        """The booking the request names, read off the URL segment. A segment that is not an id is
        answered by the same refusal as a booking that is not there: nothing here says whether it is."""
        tail = (path or "").split(BOOKING_SURFACE[1], 1)
        if len(tail) < 2:
            return None
        segment = tail[1].split("/")[0]
        return int(segment) if segment.isdigit() else None

    # --- availability (public, US8) ----------------------------------------

    def handle_availability(self, body, headers, path=None):
        """US8: the public read, open to a passer-by with no session, answered per type.

        The query decides which shape answers (see `src/availability.py`): the board when the caller names
        nothing, the window when it names a window or a type. Nothing here asks for a session, and nothing
        in either shape names a machine, a customer or a code (AC2, AC6).
        """
        now = self.clock.now()
        open_day = start_times.is_open_day(now.date(), self.config)
        inventory = self.repo.machine_counts()
        only = body.get("type")
        if only is not None and only not in self.config["tariffs"]:
            return 400, {"error": "unknown_type", "message": "Tipo macchina sconosciuto"}
        common = {
            "open_now": open_day and self.is_inside_hours(now),
            "opening_hours": self.config["opening_hours"],
            "closed_days": self.config["closed_days"],
            "grid_minutes": self.config["grid_minutes"],
            # AC 7: the seed numbers verbatim, so a reviewer can read them without reading code.
            "config": domain.seed_view(inventory, self.config),
        }
        if availability.windowed(body):
            hours = availability.window_hours(body)
            return 200, {**common, "window_hours": hours,
                          "types": availability.window_view(self.repo, self.config, now, hours, only)}
        return 200, {**common, "types": [self.board_row(type_key, inventory[type_key], now) for type_key in inventory]}

    def board_row(self, type_key: str, count: int, now) -> dict:
        """One board row: the type, the inventory, the machines free at the earliest start, the tariff.

        The free count goes through `is_assignable`, the same predicate the window answers on (AC7: a
        machine inside its turnover buffer is not free).
        """
        tariff = domain.tariff_of(type_key, self.config)
        usable = [start for start in start_times.valid_start_times(now.date(), type_key, self.config)
                  if start >= now]
        earliest = usable[0] if usable else now
        free = len([machine for machine in self.repo.machines()
                    if machine["type"] == type_key and self.is_assignable(machine, earliest)])
        return {
            "type": type_key,
            "capacity_kg": tariff.capacity_kg,
            "cycle_minutes": tariff.cycle_minutes,
            "tokens": tariff.tokens_required,
            "machines": count,
            "free": free,
            "earliest_start": hhmm(usable[0]) if usable else None,
            "why": self.why(type_key, now, start_times.is_open_day(now.date(), self.config), usable, free),
        }

    def why(self, type_key, now, open_day, usable, free) -> str:
        if not open_day:
            return f"Oggi è {now.date().strftime('%A')}: il negozio è chiuso"
        if not usable:
            return "L'ultimo start valido per questo tipo è già passato rispetto alla chiusura"
        if free == 0:
            return "Nessuna macchina libera di questo tipo per lo slot più vicino"
        return ""

    def is_inside_hours(self, now) -> bool:
        open_time = self._time_of(self.config["opening_hours"]["open"])
        close_time = self._time_of(self.config["opening_hours"]["close"])
        return open_time <= now.time() <= close_time

    def _time_of(self, value: str):
        return datetime.strptime(value, "%H:%M").time()

    def is_assignable(self, machine, start) -> bool:
        """The predicate the public view answers on, in one place (issue #8): `src/availability.py`.

        R10 and addendum patch 2: a machine inside its turnover buffer, or inside its cleaning buffer
        after being reported still occupied, is not free. R5: neither is a machine whose point is already
        committed to a booking, and neither is a machine in `maintenance` (US42).
        """
        return availability.free_at(machine, start, self.config, availability.taken_turns(self.repo, [machine]))

    def pick_machine(self, type_key: str, start) -> dict | None:
        """First machine of the type that can actually be assigned for `start`."""
        for machine in self.repo.candidate_machines(type_key):
            if self.is_assignable(machine, start):
                return machine
        return None

    def assign(self, machine, now) -> None:
        """Move a machine to `reserved`, releasing its buffer first so R6 stays honest."""
        if machine["state"] != "available":
            self.transition(machine["id"], "available", now)
        self.transition(machine["id"], "reserved", now)

    # --- booking ------------------------------------------------------------

    def handle_booking(self, body, headers, path=None):
        """AC7: a booking request without a session is refused here, before anything is decided.

        The observer has no session, so it has no identity to attach a booking to — and R9 needs an
        identity, because a reservation in an unattended shop is only enforceable if it belongs to
        somebody who can be held to it.
        """
        who = self.customer(headers)
        if who is None:
            return 401, {"error": "sign_in_required", "message": "Entra con email e codice per prenotare"}
        now = self.clock.now()

        blocked = rules.no_show_block(self.repo.no_shows(who["email"]), now.date(), self.config)
        if blocked:
            self.telemetry.count("customer_blocked_total", journey=self.journey)
            return 403, {
                "error": "blocked",
                "until": blocked.isoformat(),
                "no_shows": len(self.repo.no_shows(who["email"])),
                "message": f"Prenotazioni bloccate fino al {blocked.isoformat()} per mancate presentenze",
            }

        type_key = body.get("type")
        if type_key not in self.config["tariffs"]:
            return 400, {"error": "unknown_type", "message": "Tipo macchina sconosciuto"}
        tariff = domain.tariff_of(type_key, self.config)

        start = self.parse_start(body.get("start"))
        if start is None:
            return 400, {"error": "start_required", "message": "Serve un orario di inizio"}

        # AC3 (issue #45, slice a): the order the acceptance criteria read in.
        #   1. a slot that has already begun is refused before anything else is decided. It is the one
        #      refusal cause an alternative cannot fix — a slot that has happened cannot be moved — so it
        #      is 422, not the 409 that answers a slot the shop can still honour later. The alternatives
        #      are the next slots measured from `now`, because the requested hour is already gone.
        #   2. AC1: an off-grid request is quantised up to the grid, so 14:07 books 14:15. An off-grid
        #      request is adjusted, not refused: `off_grid` stays the helper's word for a slot the board
        #      cannot offer, and it is never the answer to a booking request.
        #   3. the fixed vocabulary of issue #7 names the cause, in its order; AC3's two causes (already
        #      begun, outside opening hours) answer 422, the other two keep the 409.
        if start_times.in_the_past(start, now):
            reason, reference = "in_the_past", now
        else:
            reference = start = start_times.quantize(start, self.config)
            reason = start_times.refusal_reason(start.date(), type_key, start, self.config)
        if reason:
            answer = start_times.next_valid_starts(reference.date(), type_key, reference, self.config)
            self.telemetry.count("customer_blocked_total", journey=self.journey)
            return start_times.HTTP_STATUS.get(reason, 409), {
                "error": "slot_not_valid",
                "reason": reason,
                "requested": start_times.slot(reference),
                "alternatives": answer["alternatives"],
                "message": "Lo slot scelto non può essere rispettato",
            }

        # R1, R2: the pure helper decides the slot and names the reason from the fixed vocabulary
        # (AC4), with the next valid alternatives earliest first, crossing to the next open day when
        # the day is exhausted (AC5, AC6).
        valid = start_times.valid_start_times(start.date(), type_key, self.config)
        answer = start_times.next_valid_starts(start.date(), type_key, start, self.config)
        if start not in valid:
            return 409, {
                "error": "slot_not_valid",
                "reason": answer["reason"],
                "alternatives": answer["alternatives"],
                "message": "Lo slot scelto non può essere rispettato",
            }

        used = len([row for row in self.repo.bookings_for(who["email"])
                    if parse(row["start_time"]).date() == start.date() and row["state"] != "cancelled"])
        limit = self.config["bookings_per_day"]
        if used >= limit:
            return 409, {
                "error": "daily_limit",
                "limit": limit,
                "used": used,
                "resets_at": f"{start.date().isoformat()} 23:59",
                "message": f"Massimo {limit} prenotazioni al giorno: hai già {used}",
            }

        machine = self.pick_machine(type_key, start)
        if machine is None:
            return 409, {
                "error": "no_machine_free",
                "reason": "all machines of this type are committed for that slot",
                "alternatives": answer["alternatives"],
                "message": "Nessuna macchina libera di questo tipo per lo slot scelto",
            }

        tariff = self.config["tariffs"][type_key]
        booking = self.repo.create_booking(
            machine["id"], who["email"], start, start + timedelta(minutes=tariff["cycle_minutes"]),
            self.repo.next_code(now), tariff["tokens"], now,
        )
        if booking is None:
            # R5: the persistence layer refused the slot, not a pre-check. The pre-check had named the
            # same machine for the same slot to both requests, because both read the state as it was when
            # the request began; the layer is what decided. The loser is answered with the bounded set of
            # alternatives the decision from #47 preserves: at most three, and the refusal writes nothing.
            # Issue #48 (slice c) is the shape of that answer: the bounded set, earliest first, of the type
            # the loser asked for, and only slots she can actually take — `src/alternatives.py` reads the same
            # predicate the assignment step answers on, so no listed slot is one the shop would refuse, and
            # the count is the smaller of the bound and what R11 still lets her take that day.
            return 409, {
                "error": "slot_taken",
                "enforced_by": "persistence layer",
                "alternatives": alternatives.takeable(self.repo, self.config, type_key, start, now,
                                                       remaining=limit - used),
                "message": "Lo slot è stato assegnato a un altro cliente: scegli un orario alternativo",
            }

        self.trace(booking)
        self.assign(machine, now)
        view = self.booking_view(booking, machine["code"])
        # The booking is the payload, and `booking` is the same object under its key: the response can
        # be read either way — straight off it (the machine, the code, the state) or as the booking.
        return 201, {**view, "booking": view}

    def handle_bookings(self, body, headers, path=None):
        """AC5: on the return visit the customer is recognised by the persisted token and reads only
        their own bookings — the list is filtered by the identity the token resolves to.

        The query decides which shape answers, the same rule that shapes the public availability read
        (issue #8): when the request names a machine the answer is the machine-scoped list — the read the
        machine is read through (issue #11, slice b2) — otherwise the caller's own list with its limit and
        its block. A JSON body cannot be a list of records and a mapping at the same time, so one of the two
        answers. The machine-scoped form answers to any caller because the machine is the subject and a
        machine is public information (US42); the caller's own list needs a session, because it is filtered
        by the identity the token resolves to.
        """
        if body.get("machine"):
            return self.machine_bookings(body["machine"])
        who = self.customer(headers)
        if who is None:
            return 401, {"error": "sign_in_required", "message": "Entra con email e codice"}
        now = self.clock.now()
        today = now.date()
        used = len([row for row in self.repo.bookings_for(who["email"])
                    if parse(row["start_time"]).date() == today and row["state"] != "cancelled"])
        return 200, {
            "bookings": [self.booking_view(row) for row in self.repo.bookings_for(who["email"])],
            "limit": {
                "max_per_day": self.config["bookings_per_day"],
                "used": used,
                "remaining": self.config["bookings_per_day"] - used,
                "resets_at": f"{today.isoformat()} 23:59",
            },
            "block": {"blocked": rules.no_show_block(self.repo.no_shows(who["email"]), today, self.config)},
        }

    def machine_bookings(self, code) -> tuple[int, dict | list]:
        """The machine-scoped read: the bookings attached to the machine the request names.

        The machine is the subject, and a machine is public information — US42 asks that a machine in
        `maintenance` be visibly unavailable, which is the same reason `GET /api/machines/<code>` answers
        without a session. So this read answers to any caller, and the shape is the record as a read open to
        a caller with no session can carry it: no customer and no code (US22), the way the incident list
        answered to the observer carries neither (issue #6, AC8).

        For a machine in `maintenance` this list is the record the claim left behind (issue #11, slice b2,
        AC3): the claim keeps the booking the entitlement was read against, the fence keeps any other booking
        off the machine, so the list is that one record and nothing else.
        """
        machine = self.repo.machine(code)
        if machine is None:
            return entitlements.UNKNOWN_MACHINE, entitlements.unknown_machine()
        return 200, [self.public_booking_view(row, machine["code"])
                      for row in self.repo.bookings_on_machine(machine["id"])]

    def public_booking_view(self, booking, machine_code=None) -> dict:
        """One booking in the shape a read that is open to a caller with no session can answer.

        The same record as `booking_view`, with the two spellings of the code taken out: a view answered to a
        caller who is not entitled to the booking cannot carry the code, because the code lives only inside
        that booking (US22), and it cannot carry the customer either. One record shape, so the two views
        cannot drift on anything else.
        """
        view = self.booking_view(booking, machine_code)
        return {key: value for key, value in view.items() if key not in ("unlock_code", "code")}

    def handle_booking_read(self, body, headers, path=None):
        """AC2: one booking is read by the customer it belongs to, and by nobody else.

        A booking is the customer's: the unlock code is displayed only inside that booking (spec,
        Identity), so the read that answers with a booking cannot be answered to another caller. The
        decision is `src/entitlements.py`; the body of the refusal is the one that cannot say whether
        the booking exists.
        """
        booking = self.repo.booking_by_id(self.booking_id_of(path))
        status, denial = self.booking_entitlement(self.customer(headers), booking)
        if status != entitlements.ALLOWED:
            return status, denial
        self.trace(booking)
        return 200, {"booking": self.booking_view(booking)}

    def handle_cancel(self, body, headers, path=None):
        """AC2 and AC3: the entitlement is decided before anything else is checked.

        The refusal is at the seam, not in what the front-end shows: a caller who already holds the
        id is refused even on a booking a UI would render as clickable. Nothing is written for a
        caller who is not entitled. The window (R4, `src/cancellation.py`) is read after that gate, not
        before it: a refusal of the entitlement is the answer to a caller who has no standing on the
        booking at all, and the two statuses must stay distinguishable (issue #12).
        """
        booking = self.repo.booking_by_id(self.booking_id_of(path))
        who = self.customer(headers)
        status, denial = self.booking_entitlement(who, booking)
        if status != entitlements.ALLOWED:
            return status, denial
        return self.cancel_booking(booking)

    def cancel_booking(self, booking) -> tuple[int, dict]:
        """The cancellation core, once: the same write behind the customer's cancel and the panel's.

        The entitlement is decided by the caller's gate before this runs, so the only thing left here is
        R4 — the window, read through `src/cancellation.py` — then the state test, then the write. The
        window is read before the state test because it is the rule that refuses a late request, and both
        refusals show the state as it already is: a refusal is a decision, not a write, so the booking
        keeps its state and the machine keeps the state the booking holds it in (US46).

        Splitting it out is what keeps the two paths from answering differently for the same booking.
        """
        now = self.clock.now()
        start = parse(booking["start_time"])
        self.trace(booking)
        machine = self.repo.machine_by_id(booking["machine_id"])
        if not cancellation.may_cancel(start, now, self.config):
            # The customer is blocked from an action she can still ask for: that is the event the one
            # metric of the instrumented journey counts. It counts the refusal, not the booking: a turn
            # given back before the cutoff is not a turn lost (AC7, R9).
            self.telemetry.count("customer_blocked_total", journey=self.journey)
            return 409, cancellation.refusal(booking, machine, self.config, now, start,
                                             cancellation.WINDOW_REFUSED)
        if booking["state"] not in cancellation.CANCELLABLE_STATES:
            # US46: the state of a booking that can no longer be cancelled is shown. The window has already
            # been read; here the machine is committed to a turn, so the state is the whole of the answer.
            return 409, cancellation.refusal(booking, machine, self.config, now, start, cancellation.STATE_REFUSED)
        self.repo.set_booking_state(booking["id"], "cancelled")
        if machine is not None and machine["state"] == "reserved":
            # US45: the slot becomes bookable by others at once. No buffer is charged for a cancellation —
            # the buffer is the hop that follows a cycle actually run (R10), and this is the declared hop
            # `reserved -> available`, taken at the moment of the request.
            self.transition(machine["id"], "available", now)
        # R9, AC7: nothing here touches the no-show counter. The incident is the cancellation itself.
        self.repo.record_incident("cancellation", now, "cancelled at the seam", booking["email"],
                                  booking["machine_id"], booking["id"])
        # The answer is the booking as the row is now, not as it was when the request arrived.
        return 200, {"outcome": "cancelled", "booking": self.booking_view(self.repo.booking_by_id(booking["id"])),
                      "cutoff_minutes": cancellation.cutoff_minutes(self.config),
                      "message": "Prenotazione cancellata: lo slot torna disponibile"}

    def booking_view(self, booking, machine_code=None):
        start = parse(booking["start_time"])
        grace_from, grace_to = rules.grace_window(start, self.config)
        machine = machine_code
        if machine is None:
            row = self.db.one("SELECT code FROM machines WHERE id = ?", (booking["machine_id"],))
            machine = row["code"] if row else None
        return {
            # The id on the wire is the string the URL segment reads as: `GET /api/bookings/<id>` is
            # the same booking, seen from the seam. The row keeps the integer, the response the name.
            "id": str(booking["id"]),
            "machine": machine,
            "type": booking.get("type") or (self.db.one(
                "SELECT type FROM machines WHERE id = ?", (booking["machine_id"],)) or {}).get("type"),
            "start": hhmm(start),
            # The three names issue #45 (slice a of #11) writes on the record: `end` is the cycle end from
            # the type's real duration (R1: 60/4, 75/6, 30/3), `token_count` is the type's tariff, the
            # numeric code is `unlock_code`. The earlier spellings stay, so the same decision is never
            # written twice and the seam answers both — never two values for the same fact.
            "end": hhmm(parse(booking["end_time"])),
            "expected_end": hhmm(parse(booking["end_time"])),
            "token_count": booking["tokens"],
            "tokens": booking["tokens"],
            "unlock_code": booking["code"],
            "code": booking["code"],
            "state": booking["state"],
            "grace_window": {"from": hhmm(grace_from), "to": hhmm(grace_to)},
        }

    def parse_start(self, value):
        if not value:
            return None
        try:
            if len(value) == 5:
                time = datetime.strptime(value, "%H:%M").time()
                return datetime.combine(self.clock.now().date(), time)
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    # --- lock API (the device boundary, behind the seam) -------------------

    def handle_redeem(self, body, headers, path=None):
        code = body.get("code")
        booking = self.repo.booking_by_code(code) if code else None
        if booking is None:
            return 404, {"outcome": "unknown_code", "message": "Codice sconosciuto"}
        now = self.clock.now()
        start = parse(booking["start_time"])
        grace_from, grace_to = rules.grace_window(start, self.config)
        machine = self.repo.machine_by_id(booking["machine_id"])
        self.trace(booking)

        if booking["state"] == "confirmed" and now < grace_from:
            # R3: the code does not work before the window, so this attempt is refused and the code is
            # not consumed (US26: a code is usable only once). What the controller reports is still a
            # fact — the machine opened — so the declared hop `reserved -> unlocked` is recorded, and
            # the open time is the moment `idle_open` is measured from (AC 5).
            if machine["state"] == "reserved":
                self.transition(machine["id"], "unlocked", now, event="redeem")
            self.repo.record_open(booking["id"], now)
            return 403, {"outcome": "not_your_time", "message": "Il codice funziona dall'orario di inizio, non prima",
                          "valid_from": hhmm(grace_from)}
        if booking["state"] == "confirmed" and now > grace_to:
            self.transition(booking["machine_id"], "available", now, event="redeem")
            self.repo.set_booking_state(booking["id"], "expired")
            self.repo.record_no_show(booking["email"], now, booking["id"])
            incident = self.repo.record_incident("no_show", now, "code not redeemed within the grace window",
                                                 booking["email"], booking["machine_id"], booking["id"])
            return 409, {"outcome": "expired", "message": "Il codice non funziona più: la finestra di tolleranza è finita",
                         "grace_window": {"from": hhmm(grace_from), "to": hhmm(grace_to)},
                         "incident": incident["kind"]}
        if booking["state"] == "unlocked":
            return 409, {"outcome": "already_redeemed", "message": "Il codice è già stato usato"}

        # The hop `reserved -> unlocked` is what the device fact records; if the machine was already
        # recorded as open by an out-of-window attempt there is nothing to move, the state stands.
        if machine["state"] != "unlocked":
            self.transition(machine["id"], "unlocked", now, event="redeem")
        self.repo.set_booking_state(booking["id"], "unlocked")
        self.repo.record_open(booking["id"], now)
        return 200, {"outcome": "unlocked", "machine": machine["code"], "tokens_required": booking["tokens"]}

    def handle_report(self, body, headers, path=None):
        event = body.get("event")
        if not event:
            return 400, {"error": "event_required", "message": "Serve un evento del controller"}
        now = self.clock.now()

        booking = self.repo.booking_by_code(body.get("code")) if body.get("code") else None
        machine = (self.repo.machine(body["machine"]) if body.get("machine")
                   else self.repo.machine_by_id(booking["machine_id"]) if booking else None)
        if machine is None:
            return 404, {"outcome": "unknown_code", "error": "unknown_machine",
                         "message": "Codice o macchina sconosciuta"}
        if booking is None:
            # A device report is about a machine: the booking it belongs to is the one still attached.
            booking = self.repo.open_booking(machine["id"])
        self.trace(booking)

        # The two reports that name a customer are entitlement-gated (R7).
        if event == "fault":
            return self.handle_fault(body, headers, now, path)
        if event == "occupied":
            return self.handle_occupied(body, headers, now, path)

        target = machine_states.DEVICE_EVENTS.get(event)
        if target is None:
            # AC 6: a report names a hop. When the name implies a state the table does not declare from
            # where the machine is, the answer is the attempted transition and nothing is written.
            attempted = machine_states.attempted_target(event)
            if attempted is None:
                return 400, {"error": "unknown_event", "message": "Evento dispositivo sconosciuto",
                             "accepted": sorted(machine_states.DEVICE_EVENTS)}
            raise InvalidTransition(machine["state"], attempted, event=event)

        if event == "idle_open":
            return self.handle_idle_open(machine, booking, now)

        self.transition(machine["id"], target, now, event=event)
        outcome = {"outcome": target, "machine": machine["code"]}
        if booking is not None:
            self.repo.set_booking_state(booking["id"], target)
        if target == "running" and booking is not None:
            outcome["expected_end"] = hhmm(parse(booking["end_time"]))
        if target == "finished":
            free_at = now + timedelta(minutes=self.config["turnover_buffer_minutes"])
            outcome["turnover_minutes"] = self.config["turnover_buffer_minutes"]
            outcome["bookable_from"] = hhmm(free_at)
        return 200, outcome

    def handle_idle_open(self, machine, booking, now):
        """AC 5: `idle_open` is an event, not a state — the table has no `idle_open` key. It closes the
        booking, releases the machine through the declared hop `unlocked -> available`, counts the
        no-show (R9) and records the incident."""
        if booking is None:
            return 404, {"outcome": "unknown_code", "message": "Nessuna prenotazione aperta su questa macchina"}
        self.trace(booking)
        if machine["state"] != "unlocked":
            raise InvalidTransition(machine["state"], "available", event="idle_open")
        opened = parse(booking["redeemed_at"]) if booking["redeemed_at"] else None
        idle = now - opened if opened else timedelta(0)
        if idle < timedelta(minutes=self.config["idle_open_minutes"]):
            return 409, {"error": "too_early", "event": "idle_open",
                          "message": "idle_open richiede almeno 15 minuti dall'apertura",
                          "idle_minutes": int(idle.total_seconds() // 60)}
        self.repo.set_booking_state(booking["id"], "closed")
        self.transition(machine["id"], "available", now, event="idle_open")
        self.repo.record_no_show(booking["email"], now, booking["id"])
        incident = self.repo.record_incident("idle_open", now, "machine opened, cycle never started",
                                             booking["email"], machine["id"], booking["id"])
        return 200, {"outcome": "closed", "machine": machine["code"], "incident": incident["kind"],
                     "message": "Turno perso: macchina liberata"}

    def handle_fault(self, body, headers, now, path=None):
        """The same entitlement as the booking surface, read through the report path.

        A device report answers 200 because the device is not claiming an entitlement, it is naming a fact
        it observed; a person's report on `POST /api/machines/<code>/report` is the claim and is answered
        202. Both paths gate on the same predicate in `src/entitlements.py`, so the gate cannot answer
        differently for the same caller; what they can differ on is which record the report is allowed to
        change, and that is one decision in `src/faults.py` read from the surface, not a per-path copy of the
        rule. A refusal writes nothing: the machine keeps the state the table had for it and no incident is
        recorded.
        """
        who = self.customer(headers)
        if who is None:
            return entitlements.MISSING_SESSION, entitlements.missing_session()
        machine = self.repo.machine(body.get("machine", ""))
        if machine is None:
            return entitlements.UNKNOWN_MACHINE, entitlements.unknown_machine()
        # R7: only a customer who has or had a booking on that machine may report it.
        if not entitlements.may_report(who, self.repo.bookings_on_machine(machine["id"], who["email"])):
            return entitlements.NOT_ENTITLED, entitlements.report_refusal()
        return self.apply_fault(who, machine, now, faults.DEVICE)

    def handle_machine_report(self, body, headers, path=None):
        """AC1, AC2, AC3: the report entitlement and its residue, enforced at the seam.

        The report is addressed to the machine named in the URL, so the entitlement is read against that
        machine: 401 for a caller with no session, 403 for a caller who never had a turn on it. The gate
        is decided before anything else is checked, so a caller who already holds the machine code — the
        code is public, it is what the assignment shows — is refused exactly as a caller who holds a
        booking id is. A refused report writes nothing; an accepted one drives the machine's state, and the
        booking the entitlement was read against stays where it is — the claim is admitted by that record and
        cannot rewrite it (issue #11, slice b2, AC3). The machine can never be assigned a booking from then on
        on the other side of the claim: `src/availability.py` is the predicate the assignment step answers on
        and it never frees a machine in `maintenance`, so a slot only that machine could serve is refused at
        the seam with the alternatives the caller can actually take. The decision on what the claim may change
        is `src/faults.py`; R8 in full is the device boundary's work.
        """
        who = self.customer(headers)
        if who is None:
            return entitlements.MISSING_SESSION, entitlements.missing_session()
        machine = self.repo.machine(self.machine_code_of(path))
        if machine is None:
            return entitlements.UNKNOWN_MACHINE, entitlements.unknown_machine()
        if not entitlements.may_report(who, self.repo.bookings_on_machine(machine["id"], who["email"])):
            return entitlements.NOT_ENTITLED, entitlements.report_refusal()
        kind = body.get("kind") or body.get("event")
        if kind not in REPORT_KINDS:
            return 400, {"error": "unknown_kind", "message": "Segnalazione sconosciuta",
                          "accepted": list(REPORT_KINDS)}
        self.trace(self.repo.open_booking(machine["id"]))
        return self.apply_report(who, machine, kind, self.clock.now())

    def machine_code_of(self, path) -> str:
        """The machine the request names, read off the URL segment, report suffix stripped."""
        tail = (path or "").split("/api/machines/", 1)[1]
        return tail.removesuffix("/report")

    def apply_report(self, who, machine, kind, now) -> tuple[int, dict]:
        """A report that is taken: the kind decides which core runs, and both write through the R6 table.

        The two seam paths differ on the success status, and on one thing that is a fact about the record and
        not about the gate: a device report is a fact the controller observed, is answered 200 and runs R8 in
        full, while a person's report is a claim the seam admits, is acknowledged with 202, and keeps the
        booking the entitlement was read against. A refusal keeps whatever status the decision gave it, and the
        gate is the same decision on both paths.
        """
        status, payload = (self.apply_fault(who, machine, now, faults.CLAIM) if kind == "fault"
                           else self.apply_occupied(who, machine, now))
        return (entitlements.REPORT_ACCEPTED if status == entitlements.ALLOWED else status), payload

    def apply_fault(self, who, machine, now, surface: str = faults.DEVICE) -> tuple[int, dict]:
        """R7's residue: the report drives `maintenance` through the declared hop, and the machine can never
        be assigned a booking while it is in it.

        The fence itself is not a pre-check: `src/availability.py` is the predicate the assignment step and the
        public view both answer on, and a machine in `maintenance` is never free on it, so the refusal is the
        409 on the request and nothing is written on the machine. What the report is allowed to change on the
        records already attached to it is `src/faults.py`: R8 in full on the device boundary and on the panel,
        and on the claim surface the record the entitlement was read against stays (issue #11, slice b2, AC3)
        — the machine keeps exactly that one booking, because every other future booking still runs R8 and
        nothing new can be attached to a machine in `maintenance`. A refusal never reaches this line at all.
        """
        self.transition(machine["id"], "maintenance", now)
        held = self.repo.bookings_on_machine(machine["id"])
        record = faults.entitled_booking(who, held)
        reassigned, cancelled, kept = [], [], []
        for booking in held:
            start = parse(booking["start_time"])
            if start <= now or booking["state"] in ("expired", "cancelled", "closed"):
                continue
            if not faults.may_move(booking, surface, record):
                # AC3: the claim keeps the record it is read against, so the machine keeps exactly it.
                kept.append(str(booking["id"]))
                continue
            tariff = domain.tariff_of(machine["type"], self.config)
            replacement = self.pick_machine(machine["type"], start)
            if replacement is None:
                self.repo.set_booking_state(booking["id"], "cancelled")
                cancelled.append(booking["code"])
                self.repo.record_incident("uncoverable", now, "no machine of the type free, turn refunded",
                                          booking["email"], machine["id"], booking["id"])
                continue
            new_code = self.repo.next_code(now)
            self.db.execute("UPDATE bookings SET machine_id = ?, code = ? WHERE id = ?",
                            (replacement["id"], new_code, booking["id"]))
            self.assign(replacement, now)
            reassigned.append({"booking": booking["id"], "machine": replacement["code"], "code": new_code,
                               "start": hhmm(start), "tokens": tariff.tokens_required})
            self.repo.record_incident("reassignment", now, f"moved off {machine['code']}",
                                      booking["email"], replacement["id"], booking["id"])
        return entitlements.ALLOWED, {"outcome": "maintenance", "machine": machine["code"],
                                      "reassigned": reassigned, "cancelled": cancelled, "kept": kept,
                                      "message": "Macchina messa fuori servizio"}

    def handle_occupied(self, body, headers, now, path=None):
        who = self.customer(headers)
        if who is None:
            return entitlements.MISSING_SESSION, entitlements.missing_session()
        machine = self.repo.machine(body.get("machine", ""))
        if machine is None:
            return entitlements.UNKNOWN_MACHINE, entitlements.unknown_machine()
        if not entitlements.may_report(who, self.repo.bookings_on_machine(machine["id"], who["email"])):
            return entitlements.NOT_ENTITLED, entitlements.report_refusal()
        return self.apply_occupied(who, machine, now)

    def apply_occupied(self, who, machine, now) -> tuple[int, dict]:
        self.transition(machine["id"], "cleaning_required", now)
        booking = next((row for row in self.repo.bookings_for(who["email"])
                        if row["machine_id"] == machine["id"] and row["state"] in ("confirmed", "unlocked", "running")), None)
        if booking is None:
            return entitlements.NOT_ENTITLED, {"error": "no_active_booking", "message": "Nessuna prenotazione attiva su questa macchina"}

        start = parse(booking["start_time"])
        replacement = self.pick_machine(machine["type"], start)
        if replacement is None:
            return entitlements.ALLOWED, {"outcome": "cleaning_required", "machine": machine["code"], "reassigned": None,
                         "message": "Macchina segnata per la pulizia: nessuna macchina libera dello stesso tipo"}
        new_code = self.repo.next_code(now)
        self.db.execute("UPDATE bookings SET machine_id = ?, code = ? WHERE id = ?",
                        (replacement["id"], new_code, booking["id"]))
        self.assign(replacement, now)
        self.repo.record_incident("cleaning_required", now, f"reported still occupied on {machine['code']}",
                                  who["email"], machine["id"], booking["id"])
        cleaned_at = now + timedelta(minutes=self.config["cleaning_buffer_minutes"])
        return entitlements.ALLOWED, {"outcome": "cleaning_required", "machine": machine["code"],
                     "cleaning_minutes": self.config["cleaning_buffer_minutes"], "clean_until": hhmm(cleaned_at),
                     "reassigned": {"booking": booking["id"], "machine": replacement["code"], "code": new_code,
                                    "start": hhmm(start)},
                     "message": "Macchina in pulizia: sei stato spostato subito"}

    # --- seed inventory (the machine registry is configuration, not a screen) ---

    def handle_create_machine(self, body, headers, path=None):
        """Add a machine of a type to the seed inventory.

        Only `type` is accepted. Duration and tariff are answered by the type registry, so there is
        no per-machine price field to override here and the same type always answers the same.
        """
        extra = sorted(key for key in body if key != "type")
        if extra:
            return 400, {"error": "override_not_allowed", "fields": extra,
                          "message": "La macchina non ha un prezzo proprio: si sceglie solo il tipo"}
        type_key = body.get("type")
        if type_key not in self.config["tariffs"]:
            return 400, {"error": "unknown_type", "message": "Tipo macchina sconosciuto"}
        machine = self.repo.create_machine(type_key, self.clock.now())
        return 201, domain.machine_view(machine, self.config)

    # --- owner panel (issue #10, slice c) -----------------------------------

    def owner_gate(self, headers) -> tuple[int, dict | None]:
        """AC1 and AC3: the panel gate, in one place, before any panel surface runs.

        401 for a caller with no session, 403 for a session that is not the owner — the two outcomes
        stay externally distinguishable, and the copy is different: "accedi" for the missing session,
        "non è tuo" for the wrong entitlement. The decision is `src/entitlements.py`. The reviewer with
        no session is answered 401 as well: it is not an identity, so there is nothing to be entitled
        with, and the panel is not one of the reads issue #6, AC 8 leaves it. The gate runs before
        anything the panel would do, so a customer holding a real machine code or a real booking id is
        refused on the panel path too: enforcement is the 403 on the request she can still make, not a
        control the front-end hides.
        """
        who = self.who_is_asking(headers)
        if who is None or who.get("is_observer"):
            return entitlements.MISSING_SESSION, entitlements.missing_session()
        if entitlements.may_enter_panel(who):
            return entitlements.ALLOWED, None
        return entitlements.NOT_ENTITLED, entitlements.panel_refusal()

    def panel_named(self, path) -> str | None:
        """What a panel write names: the machine or the booking carried by the URL segment."""
        return self.owner_surface("POST", path)[1]

    def panel_machine(self, named) -> dict | None:
        """The machine the panel request names: the code as written, or the id the segment reads as."""
        if not named:
            return None
        found = self.repo.machine(named) or self.repo.machine(named.upper())
        return found or self.repo.machine_by_id(int(named) if named.isdigit() else None)

    def panel_booking_id(self, named) -> int | None:
        """The booking the panel request names, the same way `booking_id_of` reads a booking segment."""
        if not named:
            return None
        segment = named[1:] if named[:1].lower() == "b" else named
        return int(segment) if segment.isdigit() else None

    def toggle_target(self, body, machine) -> str:
        """US54 in both directions: the state the toggle is asked for, or the flip of the one it is in."""
        asked = body.get("state")
        if asked in TOGGLE_STATES:
            return asked
        return "available" if machine["state"] == "maintenance" else "maintenance"

    def handle_owner_machines(self, body, headers, path=None):
        """AC1: the panel's machine list, gated on the owner flag."""
        status, denial = self.owner_gate(headers)
        if status != entitlements.ALLOWED:
            return status, denial
        return 200, {"machines": self.owner_board()}

    def handle_owner_status_board(self, body, headers, path=None):
        """AC2: the status board (US53) — every machine, its state live, and what is attached to it.

        The same rows the contract board answers with, read as the panel reads them: the state, the
        buffer the machine is inside, and the bookings the owner sees before taking it out of service
        (US55). Nothing here is a different rule: `is_assignable` and `buffer_of` are the same predicates
        the public view answers on.
        """
        status, denial = self.owner_gate(headers)
        if status != entitlements.ALLOWED:
            return status, denial
        now = self.clock.now()
        rows = []
        for machine in self.repo.machines():
            buffer, bookable_from = self.buffer_of(machine, now)
            rows.append({**self.panel_row(machine), "changed_at": machine["changed_at"],
                         "buffer_minutes": buffer, "bookable_from": bookable_from,
                         "assignable": self.is_assignable(machine, now)})
        counts = {row["state"]: sum(1 for other in rows if other["state"] == row["state"]) for row in rows}
        return 200, {"status_board": rows, "counts": dict(sorted(counts.items())), "as_of": hhmm(now)}

    def handle_owner_incidents(self, body, headers, path=None):
        """AC2: the incident list as the owner's surface, not as the reviewer's read.

        `GET /api/incidents` is the contract entry the observer keeps (issue #6, AC8); the panel path is
        the owner's, so it is closed to a customer and it answers with the list that carries the
        customer — US57 is what the owner reads to see what the shop suffered.
        """
        status, denial = self.owner_gate(headers)
        if status != entitlements.ALLOWED:
            return status, denial
        return 200, self.incident_list(self.who_is_asking(headers))

    def handle_owner_maintenance(self, body, headers, path=None):
        """AC2 and AC3: the maintenance toggle, refused before the write, executed for the owner.

        A refused toggle writes nothing: the machine keeps the state the table had for it and no incident
        is recorded. For the owner both directions are hops the table declares — out of service through the
        R7 core read on the panel surface, where R8 runs in full because the owner is the identity entitled to
        cancel or reassign a booking (US56), and back in service through the declared hop out of
        `maintenance`.
        """
        status, denial = self.owner_gate(headers)
        if status != entitlements.ALLOWED:
            return status, denial
        machine = self.panel_machine(self.panel_named(path))
        if machine is None:
            return entitlements.UNKNOWN_MACHINE, entitlements.unknown_machine()
        now = self.clock.now()
        who = self.who_is_asking(headers)
        target = self.toggle_target(body, machine)
        if target == "maintenance":
            self.repo.record_incident("maintenance", now, f"taken out of service on {machine['code']}",
                                      who["email"], machine["id"], None)
            return self.apply_fault(who, machine, now, faults.PANEL)
        self.transition(machine["id"], "available", now, event="maintenance_lifted")
        self.repo.record_incident("maintenance_lifted", now, f"back in service on {machine['code']}",
                                  who["email"], machine["id"], None)
        return 200, {"outcome": "available", "machine": machine["code"],
                      "message": "Macchina di nuovo disponibile"}

    def handle_owner_cancel(self, body, headers, path=None):
        """AC2 and AC3: the manual cancellation (US56), gated on the owner flag first.

        The gate runs before the lookup, so a customer who already holds a real booking id is refused on
        the panel path exactly as on the customer path. Only after the gate does the panel get the 404 —
        the owner is entitled to know that a booking exists (US56), which is why the refusal body a
        customer gets cannot say whether the booking is there.
        """
        status, denial = self.owner_gate(headers)
        if status != entitlements.ALLOWED:
            return status, denial
        booking = self.repo.booking_by_id(self.panel_booking_id(self.panel_named(path)))
        if booking is None:
            return 404, entitlements.not_found()
        return self.cancel_booking(booking)

    def handle_machines(self, body, headers, path=None):
        """The contract path for the owner board, answered as the identity layer pinned it.

        `GET /api/machines` is one of the eight contract entries, and its answer for a caller that is not
        the owner is the 403 tests/integration/test_identity_layer.py and tests/test_journey.py assert —
        the panel stays closed to a customer, and to the observer that has no session. The core is the
        panel's core: the same `owner_board`, so the two paths cannot drift.
        """
        who = self.who_is_asking(headers)
        if who is None or not who["is_owner"]:
            return 403, {"error": "owner_only", "message": "Il pannello proprietario è riservato al proprietario"}
        return 200, {"machines": self.owner_board()}

    def handle_incidents(self, body, headers, path=None):
        """The contract path for the incident list: the owner's read and the reviewer's read.

        A signed-in customer still cannot read it. The observer has no session to begin with, and AC 8 of
        issue #6 asks for that reviewer to watch the shop live, so the observer's list is the one with no
        customer in it.
        """
        who = self.who_is_asking(headers)
        if not self.may_observe(who):
            return 403, {"error": "owner_only", "message": "Il pannello proprietario è riservato al proprietario"}
        return 200, self.incident_list(who)

    def owner_board(self) -> list[dict]:
        """The board as the panel reads it: every machine, and the bookings attached to it (US55)."""
        return [self.panel_row(machine) for machine in self.repo.machines()]

    def panel_row(self, machine) -> dict:
        """One board row, in one place, so the contract path and the panel path answer the same shape."""
        attached = [row for row in self.repo.bookings_on_machine(machine["id"])
                    if row["state"] in ("confirmed", "unlocked", "running")]
        return {**domain.machine_view(machine, self.config),
                "machine": machine["code"],
                "bookings": [self.booking_view(row, machine["code"]) for row in attached]}

    def incident_list(self, who) -> list[dict]:
        """US57: what the shop suffered, in one place. A customer's name is in it only for the owner."""
        return [self.incident_view(row, observer=bool((who or {}).get("is_observer")))
                for row in self.repo.incidents()]

    def incident_view(self, row, observer: bool = False) -> dict:
        """An incident carries the machine it happened on as the reviewer reads it: the machine code."""
        machine = self.repo.machine_by_id(row["machine_id"]) if row["machine_id"] else None
        view = {"id": row["id"], "kind": row["kind"], "machine": machine["code"] if machine else None,
                "detail": row["detail"], "created_at": row["created_at"]}
        if not observer:
            view["email"] = row["email"]
            view["booking_id"] = row["booking_id"]
        return view

    # --- the state machine, read live (AC 8) ---------------------------------

    def handle_machine(self, body, headers, path=None):
        """`GET /api/machines/<code>`: the state of one machine, live, so a reviewer can watch a hop.

        The state of a machine is public information — a machine in `maintenance` must be visibly
        unavailable (US42) — so the single-machine read answers without a session. The board on
        `GET /api/machines` stays the owner panel: it lists the bookings attached to a machine.
        """
        code = (path or "").split("/api/machines/", 1)[1]
        machine = self.repo.machine(code)
        if machine is None:
            return 404, {"error": "unknown_machine", "message": "Macchina sconosciuta"}
        view = domain.machine_view(machine, self.config)
        buffer, bookable_from = self.buffer_of(machine, self.clock.now())
        return 200, {**view, "machine": machine["code"], "state": machine["state"],
                     "changed_at": machine["changed_at"], "buffer_minutes": buffer,
                     "bookable_from": bookable_from,
                     "assignable": self.is_assignable(machine, self.clock.now())}

    def buffer_of(self, machine, now) -> tuple[int | None, str | None]:
        """The buffer a machine is inside, as the same predicate the board answers on (R10, patch 2).

        One reading, so the per-machine read and the panel's status board cannot disagree about whether a
        machine is inside its turnover buffer or its cleaning buffer.
        """
        key = machine_states.BUFFER_HOPS.get(machine["state"])
        buffer = self.config[key] if key else None
        return buffer, hhmm(now + timedelta(minutes=buffer)) if buffer else None

    # --- state machine (R6) -------------------------------------------------

    def transition(self, machine_id: int, to: str, now: datetime, event: str | None = None) -> None:
        """The only writer of a machine state: the hop must be in the table or nothing is written."""
        machine = self.repo.machine_by_id(machine_id)
        current = machine["state"]
        if not machine_states.declares(current, to):
            raise InvalidTransition(current, to, event=event)
        self.repo.set_machine_state(machine_id, to, now)


class InvalidTransition(Exception):
    """A hop the table does not declare. It carries the attempted transition so 409 can name it."""

    def __init__(self, current: str, to: str, event: str | None = None) -> None:
        super().__init__(f"{current} -> {to}")
        self.current = current
        self.to = to
        self.event = event
