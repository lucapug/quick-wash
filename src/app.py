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

The customer's own view (issue #18, R9) is the fourth pattern: `GET /api/customers/me` answers the counter,
the block and its expiry before any booking attempt (US51), and it is the same `block_view` the 403 on
`POST /api/bookings` answers with — one decision in `src/domain/counters.py`, so the view and the refusal
cannot disagree about what the customer is blocked for or until when. It needs a session, because a caller
with no identity has no counter to read.

The unlock code and its grace window (issue #14, R3): the code is the booking's own numeric code, six
digits as the machine keypad reads it, tied to one row and redeemed once on `POST /api/lock/redeem` inside
`[start - 10, start + 10]`, inclusive on both bounds. The four outcomes of that path are fixed:
`unlocked`, `expired`, `already_redeemed`, `unknown_code`, and the last two read as the customer's own
situation — a typo, a lost turn — not as a system failure. Expiry is evaluated at redemption and on any
read of the booking, which is what R3's observable outcome is and what keeps the rule testable without a
background scheduler; `running` is never an outcome of this path, because a cycle is the device's
`cycle_started` report. The code has no email or SMS transport, never appears in a public view and never
enters a log line.

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
keeps exactly its entitled pre-report booking (issue #11, slice b2, AC3). The decision is `src/faults.py`, in
one predicate, run by `apply_fault`, and the incident the taken report leaves behind is the same file read per
surface — `fault` on the claim and on the device boundary, the owner's own action on the panel — so the
reviewer's demo and the test run one implementation.

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

R10 (turnover and cleaning, the numbers signed by addendum patch 2 — 10 and 30 minutes, held as
configuration): the turnover buffer starts at the moment the device reports `cycle_finished`, because
issue #15 established that only the device decides when a cycle ends, and the hop a `cycle_finished`
report names from `unlocked` is therefore declared in `src/machine_states.py`. Both buffers are carried
by time, not by a caller, so every request resolves the elapsed buffers before answering — that is what
makes the state read a live read and the window answer `turnover_buffer` for a machine inside it. The
still-occupied claim (`kind` `still_occupied`, the US33 spelling of the `occupied` kind; the published
vocabulary stays the two kinds issue #10 pins) takes the machine to `cleaning_required` for its window and
moves the claimant to a free machine of the same type at the same start time with a new code and the
notification US38 asks for; when nothing of the type is free the booking is cancelled and the turn refunded
so the customer can rebook at once (US39). A claim that arrives while the window is running is accepted and
restarts it (US35) — the state stands, so no hop is attempted and the table declares no self-entry for
`cleaning_required`. Its entitlement is narrower than R7's: the customer currently assigned to the machine
(issue #12, AC6), the repeat being read against the record the first claim left on it.

R8 (issue #19) is the pass `apply_fault` runs: the bookings attached to a machine that goes to `maintenance`
move to a free machine of the same type, earliest start first with ties broken by the order the records were
created, the target being the lowest-numbered free machine of the type — both are decisions in
`src/faults.py`, in one line each, so the reviewer's demo and the test see the same pass. The booking keeps
its start, gets a new code, and the pass writes the notification the customer reads inside the app: there is
no email, no SMS, no push, so `GET /api/notifications` (a pattern, not a ninth contract entry) is the only
delivery channel and it answers a customer's own notifications to that customer. A turn nothing of the type
can cover is cancelled and the refund is the right to rebook — no money, no ledger, so the day's allowance
goes back with the cancelled record and the customer can take a slot at once. The invariant R8 closes is read
after every pass, on every surface, and the answer carries what it found: on the device boundary and on the
panel nothing is left attached, on the claim surface the machine keeps exactly the record the entitlement was
read against (the fork `src/faults.py` records for the human decision). A customer already standing at the
machine is moved immediately rather than sent through a support process, because there is no staff to ask:
when the code was already redeemed the machine is released from her turn and the cycle still ahead moves with
the record.

R11 (issue #21) is the day's allowance, read on the shop's own day: `Europe/Rome`, resetting at 00:00 local,
and counted on the moment a booking was created rather than on the slots it is active in, because R11 says
"independent of overlap" — a customer holding two slots is refused even when both are already in the past of
the day. The two decisions are `src/daily_limit.py`, in one place, and the guarantee is the UNIQUE
`(email, day, seat)` index in `src/repository.py`: the seat a request computes from its own snapshot can be a
seat another request already holds, and the insert is what refuses it, exactly as the slot index refuses the
loser of a race for a machine. A refusal writes nothing. A cancelled booking has no seat row, so the refund is
literally the right to rebook, and the customer's own view (`GET /api/customers/me`, `GET /api/bookings`) and
the 409 that answers her third attempt read the same shape from the same rows — the limit, the count used, the
moment it resets — before any refusal happens. The order is the rule's: the R9 gate answers before the
allowance is read, so a blocked customer is refused for the block and the answer never also names the limit.
"""

from datetime import datetime, timedelta

from src import alternatives, availability, cancellation, daily_limit, domain, entitlements, faults, machine_states, rules
from src import notifications
from src import identity as credentials
from src.clock import Clock
from src.domain import counters
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

# R3 (issue #14): the outcomes the lock API answers a keypad entry with. Exactly these four.
REDEMPTION_OUTCOMES = ("unlocked", "expired", "already_redeemed", "unknown_code")

# The booking states that mean the code has already been spent at the keypad (US26). `expired` is not one
# of them: a code that died with its window was never used, it is dead (issue #14, AC3).
SPENT_STATES = ("unlocked", "running", "finished")

# Three reads are patterns, not contract paths, so `ROUTES` stays exactly the eight entries
# tests/test_seam.py pins: the state of one machine (issue #6, AC8), the verification of a one-time
# code, and the telemetry read. The contract fixes the sign-in request; the code it showed in-app is
# redeemed on its sub-path, and the log lines are read on theirs.
# The customer's own view (issue #18, R9) is the fourth pattern, for the same reason: US51 asks the block
# and its expiry to be visible before any booking attempt, so the read exists on its own sub-path and
# `ROUTES` stays the eight entries tests/test_seam.py pins. It needs a session, because a caller with no
# identity has no counter to read.
PATTERNS = {"POST /api/session/verify": "verify", "GET /api/logs/recent": "logs",
           "GET /api/customers/me": "customer_me",
           # The notification read (issue #19, R8) is the fifth pattern for the same reason: the contract
           # fixes the eight entries tests/conftest.py pins, and the app's own notification is a read of what
           # the pass wrote, not a ninth entry. It is entitlement-gated like the booking surface — a caller
           # with no session has no notifications to read — and it is the only delivery channel there is,
           # because notifications outside the app (email, SMS, push) are out of scope.
           "GET /api/notifications": "notifications"}

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
# The word US33 uses for the second kind: `still_occupied` is the customer's spelling of `occupied`, so the
# claim arrives with it and is read as the same report. The published vocabulary stays the two canonical
# kinds issue #10 (slice b) pins, so the answer to an unknown kind still lists exactly those two.
REPORT_KIND_WORDS = {"still_occupied": "occupied"}

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
            # The idle-open bound is evaluated at report time and on every read (issue #13, Decision). The two
            # are not the same moment: a report the device sends is the fact it observed, and the read is the
            # request that notices the fact for somebody who never sent anything. Running the bound before a
            # report would answer the report with a hop already taken, so a report writes its own fact and the
            # read writes it only when nothing has been reported.
            if method == "GET":
                self.resolve_idle_opens(self.clock.now())
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
        """The reads that are patterns, not contract paths: one machine (AC 8), the code, the logs,
        and the customer's own view (issue #18, R9).

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

    def resolve_idle_opens(self, now) -> None:
        """The same predicate, on the read side (issue #13, Decision).

        There is no scheduler in this project, so the rule has to be evaluated where the facts are read: at
        report time and on every request that reads the shop. The open is the recorded fact, the bound is
        `src/machine_states.py`'s single predicate — the one the device reads too — and the closure is the
        same core a report runs, so the device and the read cannot write the fact twice.
        """
        for machine in self.repo.machines():
            if machine["state"] != "unlocked":
                continue
            booking = self.repo.open_booking(machine["id"])
            if booking is None:
                continue
            opened = parse(booking["redeemed_at"]) if booking["redeemed_at"] else None
            # The machine being `unlocked` is the recorded fact that no cycle was reported on it: a reported
            # cycle would have moved it to `running`, so the open is still an idle open.
            if not machine_states.idle_open_due(opened, now, self.config):
                continue
            self.close_idle_open(machine, booking, now)

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
        # The identifier is the same value on both sides of the seam: what the recorder writes on the request
        # line is what the answer carries, so a device call that carries a journey can be checked against the
        # journey the booking actually has (issue #13, AC7). `self.journey` is therefore the key the recorder
        # resolves, and the returned value is the identifier it resolves to.
        self.journey = booking["id"]
        return self.telemetry.journey(self.journey)

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
        """First machine of the type that can actually be assigned for `start`.

        `faults.lowest_numbered` is the order R8 needs to be demonstrable (issue #13, AC 9): the target of a
        reassignment is the lowest-numbered free machine of the type, so the same fault on the same state
        answers with the same machine in the demo, in the test and on the panel.
        """
        for machine in faults.lowest_numbered(self.repo.candidate_machines(type_key)):
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

        # R9, read through the pure counter (`src/domain/counters.py`): the rolling window, the crossing,
        # the expiry at the same local time. AC4 is what the answer carries — the reason, the count that
        # caused it, the expiry — and the shape is `block_view`, the same one the customer's own view
        # answers with (AC5), so the refusal and the view cannot disagree about what the customer is
        # blocked for or until when. The copy is Italian; the keys stay English. `error: blocked` and the
        # top-level `until`/`no_shows` stay because tests/test_journey.py pins them on the refusal.
        block = counters.block_view(self.repo.no_shows(who["email"]), now, self.config)
        if block["blocked"]:
            self.telemetry.count("customer_blocked_total", journey=self.journey)
            return 403, {"error": "blocked", "block": block,
                          "until": block["until"], "no_shows": block["no_shows"],
                          "message": block["message"]}

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

        # R11 (issue #21), the two decisions in `src/daily_limit.py`: the day is the shop's own day in
        # `Europe/Rome`, and the count is the bookings created on it, not the ones active on it. The block
        # gate has already answered, so what is read here is the allowance of a customer who is not blocked
        # (AC6): a blocked customer is refused for the block and the refusal never also names the limit,
        # because the limit is not the rule that refused her.
        day = daily_limit.local_day(now, self.config)
        rows = self.repo.day_seats(who["email"], day.isoformat())
        allowance = daily_limit.view(rows, day, self.config)
        seat = daily_limit.next_seat(daily_limit.seats(rows), self.config)
        if seat is None:
            # The day is full as this request read it. A refusal is a decision, not a write.
            self.telemetry.count("customer_blocked_total", journey=self.journey)
            return 409, daily_limit.refusal(rows, day, self.config)

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
                                                       remaining=allowance["remaining"]),
                "message": "Lo slot è stato assegnato a un altro cliente: scegli un orario alternativo",
            }

        # R11's guarantee is this insert, not the line above: the seat was computed from the snapshot the
        # request read, so two concurrent requests for the same day can name the same seat and the UNIQUE
        # `(email, day, seat)` index is what refuses one of them (AC7) — the same pattern R5 uses for a
        # machine and a slot. A refusal writes nothing: the rollback takes the booking back with the seat, so
        # the loser leaves neither behind, and `used` in the answer is the count the layer has after the
        # decision rather than the count this request had before it.
        if self.repo.take_seat(who["email"], day.isoformat(), seat, booking["id"], now) is None:
            self.telemetry.count("customer_blocked_total", journey=self.journey)
            return 409, daily_limit.refusal(self.repo.day_seats(who["email"], day.isoformat()), day, self.config)

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
        # R11 read on the shop's own day (issue #21): the same `daily_limit.view` the refusal answers with,
        # so the list and the 409 cannot state two different numbers for the same day.
        today = daily_limit.local_day(now, self.config)
        rows = [self.resolve_expiry(row) for row in self.repo.bookings_for(who["email"])]
        return 200, {
            "bookings": [self.booking_view(row) for row in rows],
            "limit": self.daily_limit(who, today),
            "block": counters.block_view(self.repo.no_shows(who["email"]), now, self.config),
        }

    def handle_customer_me(self, body, headers, path=None):
        """AC5: the customer's own view, read before any booking attempt.

        US51 is the reason this read exists: a customer who is refused without being told why, and until
        when, cannot correct the behaviour, so the counter, the block and its expiry are on the customer's
        view before the booking is attempted — in Italian, and in the same `block_view` the 403 answers
        with, not a second copy of the rule.

        It is the customer's view, so it needs a session: the observer of issue #6, AC8 has no counter to
        read because it has no identity to hold a no-show against (R9 needs a name), and the gate is the
        same one the booking surface uses — 401 for a missing session. The view answers to the identity the
        token resolves to, and to no other caller.
        """
        who = self.customer(headers)
        if who is None:
            return entitlements.MISSING_SESSION, entitlements.missing_session()
        now = self.clock.now()
        occurrences = self.repo.no_shows(who["email"])
        block = counters.block_view(occurrences, now, self.config)
        return 200, {
            "email": who["email"],
            "is_owner": bool(who["is_owner"]),
            "no_show_count": len(occurrences),
            "no_shows_in_window": block["no_shows"],
            "block": block,
            "bookings": [self.booking_view(row) for row in self.repo.bookings_for(who["email"])],
            # AC3 (issue #21): the limit and the moment it resets are on the customer's own view before any
            # refusal happens, for the same reason US51 asks for the block there — a customer who is refused
            # without being told why, and until when, cannot correct the behaviour.
            "limit": self.daily_limit(who, daily_limit.local_day(now, self.config)),
            "message": block["message"],
        }

    def notify(self, kind, booking, machine, now, code: str | None = None) -> dict:
        """The notification, written once for the fact the pass wrote and delivered nowhere.

        The app is the only channel (docs/spec.md, Out of Scope: no email, no SMS, no push), so a notification
        is a row the customer reads back on her own read. It names the machine the customer has to walk to
        (US38) — the one the pass chose, never the one the report was about.
        """
        row = self.repo.record_notification(kind, now, notifications.message(kind, machine["code"], code),
                                            booking["email"], booking["id"], machine["id"])
        return row

    def handle_notifications(self, body, headers, path=None):
        """The customer's own notifications, inside the app.

        The gate is the one the booking surface uses: 401 for a caller with no session, because a caller with
        no identity has no notification to read. The list is filtered by the identity the token resolves to,
        the way the customer's booking list is — a notification belongs to the customer the booking belongs to.
        The `kind` is read in the app's words (`reassigned`), which is the same fact the incident list carries
        as `reassignment`; the mapping is `src/notifications.py`, in one place.
        """
        who = self.customer(headers)
        if who is None:
            return entitlements.MISSING_SESSION, entitlements.missing_session()
        rows = []
        for row in self.repo.notifications_for(who["email"]):
            machine = self.repo.machine_by_id(row["machine_id"])
            rows.append(notifications.view(row, machine["code"] if machine else None))
        return 200, rows

    def daily_limit(self, who, day) -> dict:
        """R11 as the customer reads it (US48): the limit, what is used, what is left, when it resets.

        In one place, so the customer's list, the customer's view and the 409 that answers her third attempt
        cannot disagree about the same day. `used` is the count of the day's rows in the layer — the same
        count the UNIQUE `(email, day, seat)` index decides on — so the rule has one source and the copy is
        built from the fact rather than from a second reading of it.

        A cancelled booking has no row, which is what makes US45 true on the read as well as on the write,
        and what makes R8's refund real: an uncoverable cancellation does not consume the allowance (issue
        #19, AC3) — there is no money in this product, so the refund is the right to rebook, and a turn the
        customer lost to a fault she did not cause cannot be the turn that blocks her. A turn lost to a
        no-show keeps its row: the allowance was consumed by a turn that was not given back.
        """
        return daily_limit.view(self.repo.day_seats(who["email"], day.isoformat()), day, self.config)

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
        return 200, [self.public_booking_view(self.resolve_expiry(row), machine["code"])
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
        # R3, decision 2: the state a read answers with is the state the rule says it is, evaluated at the
        # moment of the read — but only for a caller who is entitled, because a refusal writes nothing.
        booking = self.resolve_expiry(booking)
        self.trace(booking)
        view = self.booking_view(booking)
        # The booking is the payload, the same shape the creation response answers with: readable straight
        # off the body or under its key, so the same record is never spelled two ways by the seam.
        return 200, {**view, "booking": view}

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
        # R11 (issue #21): the seat goes back with the turn. There is no money in this product, so the refund
        # US45 asks for is the right to rebook, and that right is the row this line removes — the same fact the
        # customer's view reads as `used`, so the read and the write cannot disagree about her day.
        self.repo.release_seat(booking["id"])
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
        """The start the request names, read the way the clock reads an instant: one reading, no drift."""
        if not value:
            return None
        try:
            return self.clock.resolve(value)
        except (ValueError, TypeError):
            return None

    # --- lock API (the device boundary, behind the seam) -------------------
    # The grace window and the single use of a code (issue #14, R3) sit on this side of the seam: the
    # machine controller is the caller, so every outcome here is what the keypad shows on the machine.

    def expire(self, booking, window, now) -> dict | None:
        """The three facts a lost turn leaves behind: booking `expired`, machine `available`, code dead.

        The machine hop goes through the R6 table and only from the states an un-honoured turn leaves a
        machine in: `reserved`, or `unlocked` when the customer opened it and never started a cycle. A
        machine already out of circulation is not released by somebody else's lost turn. The no-show is
        recorded because the turn was lost — that is what R9 counts — and the incident is the record the
        owner panel reads (US57). The state guard makes it one fact: the same lost turn read twice is not
        written twice.
        """
        machine = self.repo.machine_by_id(booking["machine_id"])
        if machine is not None and machine["state"] in ("reserved", "unlocked"):
            self.transition(machine["id"], "available", now, event="grace_window_closed")
        self.repo.set_booking_state(booking["id"], "expired")
        self.repo.record_no_show(booking["email"], now, booking["id"])
        self.repo.record_incident("no_show", now, "code not redeemed within the grace window",
                                  booking["email"], booking["machine_id"], booking["id"])
        return self.repo.booking_by_id(booking["id"])

    def lost_turn(self, window) -> str:
        """US25: the customer lost the turn, and the machine is not broken. The copy has to say exactly that."""
        return (f"Hai perso il turno: il codice non funziona più, la finestra di tolleranza era "
                f"{hhmm(window[0])}–{hhmm(window[1])}. La macchina non è guasta: è tornata disponibile.")

    def expired_answer(self, booking, window, now) -> dict:
        """The outcome R3 names, answered on the record as it is after the fact is written."""
        row = self.expire(booking, window, now) or booking
        return {"outcome": "expired", "state": row["state"],
                "grace_window": {"from": hhmm(window[0]), "to": hhmm(window[1])},
                "message": self.lost_turn(window),
                "incident": "no_show"}

    def resolve_expiry(self, booking) -> dict | None:
        """R3 evaluated at the moment of the read (issue #14, decision 2).

        No background scheduler: expiry is evaluated at redemption and on any read of the booking. That is
        what keeps the rule an externally observable outcome — the same three facts whoever notices them —
        and what keeps it testable without a job no test could wait for.
        """
        if booking is None or booking["state"] != "confirmed":
            return booking
        now = self.clock.now()
        window = rules.grace_window(parse(booking["start_time"]), self.config)
        if now <= window[1]:
            return booking  # the window has not closed: the turn is still the customer's, or has not begun
        return self.expire(booking, window, now)

    def handle_redeem(self, body, headers, path=None):
        """R3 at the machine keypad: numeric code, one booking, one use, inside the window.

        The window is inclusive on both bounds (`rules.in_window`), because R3 states both bounds and an
        attempt on either bound is inside. The four outcomes are the vocabulary the device boundary fixes:
        `unlocked`, `expired`, `already_redeemed`, `unknown_code`, and the two refusals read as the
        customer's own situation rather than as a system failure: a typo is `unknown_code` (US27), a lost
        turn is `expired` with the copy that says the turn is gone, not that the machine is broken (US25).

        Nothing here delivers the code: it lives only inside the booking (US21, US22), there is no email or
        SMS transport to send it, and it never enters a log line. Nothing here starts a cycle either:
        `running` is the outcome of the controller's `cycle_started` report, never of a redemption, never of
        a timer and never of an assumption that tokens were inserted (AC8).
        """
        code = body.get("code")
        booking = self.repo.booking_by_code(code) if code else None
        if booking is None:
            # US27: the answer names what happened to the string the keypad sent — it belongs to no booking.
            # `identity.NEVER_ISSUED` is the shape a mistyped entry reads as and it is never generated, so a
            # typo can never land on somebody else's booking and can never read as a real one.
            return 404, {"outcome": "unknown_code", "digits": credentials.CODE_LENGTH,
                          "message": "Codice sconosciuto: controlla le cifre del codice mostrato nella tua prenotazione. La macchina non ha alcun problema."}
        now = self.clock.now()
        window = rules.grace_window(parse(booking["start_time"]), self.config)
        machine = self.repo.machine_by_id(booking["machine_id"])
        journey = self.trace(booking)

        if booking["state"] == "confirmed" and not rules.in_window(now, window, self.config):
            if now < window[0]:
                # R3: the code does not work before the window, so this attempt is refused and the code is
                # not consumed (US26: a code is usable only once). What the controller reports is still a
                # fact — the machine opened — so the declared hop `reserved -> unlocked` is recorded, and
                # the open time is the moment `idle_open` is measured from (AC 5).
                if machine["state"] == "reserved":
                    self.transition(machine["id"], "unlocked", now, event="redeem")
                self.repo.record_open(booking["id"], now)
                return 403, {"outcome": "not_your_time",
                              "message": f"Il codice funziona da {self.config['grace_minutes']} minuti prima dell'orario di inizio, non prima",
                              "valid_from": hhmm(window[0]),
                              "grace_window": {"from": hhmm(window[0]), "to": hhmm(window[1])}}
            # AC3, past the window: the turn is lost, and the answer is the three facts R3 leaves behind.
            return 409, self.expired_answer(booking, window, now)
        if booking["state"] in SPENT_STATES:
            # US26: one code, one use — whatever the machine has done in the meantime.
            return 409, {"outcome": "already_redeemed", "state": booking["state"],
                          "message": "Il codice è già stato usato: ogni codice funziona una volta sola"}
        if booking["state"] in machine_states.BOOKING_TERMINAL_STATES:
            # AC3: the code is dead, and a dead code stays dead. The answer is the same lost turn read
            # again, and it writes nothing, because there is no turn left to honour.
            return 409, {"outcome": "expired", "state": booking["state"],
                          "message": "Il codice non funziona più: il turno non esiste più"}

        # The hop `reserved -> unlocked` is what the device fact records; if the machine was already
        # recorded as open by an out-of-window attempt there is nothing to move, the state stands.
        if machine["state"] != "unlocked":
            self.transition(machine["id"], "unlocked", now, event="redeem")
        self.repo.set_booking_state(booking["id"], "unlocked")
        self.repo.record_open(booking["id"], now)
        # AC7 (issue #13): the answer to the keypad call carries the journey the call belongs to, so the
        # device carries that identifier on every later call instead of inventing one.
        return 200, {"outcome": "unlocked", "machine": machine["code"], "tokens_required": booking["tokens"],
                      "trace": journey,
                      "grace_window": {"from": hhmm(window[0]), "to": hhmm(window[1])}}

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
        journey = self.trace(booking)

        # AC7 (issue #13): the device call carries the journey of the booking it belongs to. A call that
        # carries a foreign one is refused before anything is written, and the answer names the journey the
        # machine is actually on.
        asked = body.get("trace")
        if asked is not None and journey is not None and asked != journey:
            return 400, {"error": "trace_not_this_journey", "journey": journey, "trace": asked,
                         "message": "La chiamata porta un journey che non è quello di questa prenotazione"}

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
            # Nothing to close, so nothing to count: the record the rule would act on is not there (404),
            # and the fact is not written. This is also what stops the same lost turn from being counted
            # twice — a closed booking is no longer a turn attached to the machine.
            return 404, {"error": "booking_not_found", "outcome": "unknown_code",
                         "message": "Nessuna prenotazione aperta su questa macchina"}
        self.trace(booking)
        if machine["state"] != "unlocked":
            raise InvalidTransition(machine["state"], "available", event="idle_open")
        opened = parse(booking["redeemed_at"]) if booking["redeemed_at"] else None
        if not machine_states.idle_open_due(opened, now, self.config):
            idle = now - opened if opened else timedelta(0)
            return 409, {"error": "too_early", "event": "idle_open",
                          "message": "idle_open richiede almeno 15 minuti dall'apertura",
                          "idle_minutes": int(idle.total_seconds() // 60)}
        return 200, self.close_idle_open(machine, booking, now)

    def close_idle_open(self, machine, booking, now) -> dict:
        """The facts the event leaves, written once, from the recorded open.

        The same fact is written by a report and by a read, so it is one function: the closure of the turn,
        the release of the machine through the declared hop, the no-show on the counter of the customer the
        booking belongs to (R9), and the incident. A refusal never reaches these lines.
        """
        self.trace(booking)
        self.repo.set_booking_state(booking["id"], "closed")
        self.transition(machine["id"], "available", now, event="idle_open")
        self.repo.record_no_show(booking["email"], now, booking["id"])
        incident = self.repo.record_incident("idle_open", now, "machine opened, cycle never started",
                                             booking["email"], machine["id"], booking["id"])
        return {"outcome": "closed", "machine": machine["code"], "incident": incident["kind"],
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
        machine = self.repo.machine(body.get("machine", ""))
        # R7: only a customer who has or had a booking on that machine may report it. The gate is the same
        # decision the report surface runs, so the two paths cannot answer differently for one caller.
        status, denial = self.report_gate(who, machine)
        if status != entitlements.ALLOWED:
            return status, denial
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
        machine = self.repo.machine(self.machine_code_of(path))
        asked = body.get("kind") or body.get("event")
        kind = REPORT_KIND_WORDS.get(asked, asked)
        status, denial = self.report_gate(who, machine, kind=kind)
        if status != entitlements.ALLOWED:
            return status, denial
        if kind not in REPORT_KINDS:
            return 400, {"error": "unknown_kind", "message": "Segnalazione sconosciuta",
                          "accepted": list(REPORT_KINDS)}
        # The gate is the same decision on both paths; the US33 spelling is read as the same report, and the
        # claim is the current assignment's, so the kind decides how far the entitlement reaches.
        self.trace(self.repo.open_booking(machine["id"]))
        return self.apply_report(who, machine, kind, self.clock.now())

    def report_gate(self, who, machine, held=None, kind: str | None = None) -> tuple[int, dict | None]:
        """The report gate, in one place, for both paths the report can arrive on.

        401 for a caller with no session, 404 for a machine the seam does not have, 403 for a caller who
        never had a turn on it — decided before anything the report would write, so a refusal leaves the
        machine in the state the table had for it and no incident is recorded. The still-occupied claim is
        the one the gate reads narrower: the customer the machine is held for right now (issue #12, AC6).
        `fault` keeps R7 as it is, so a past booking still entitles it.
        """
        if who is None:
            return entitlements.MISSING_SESSION, entitlements.missing_session()
        if machine is None:
            return entitlements.UNKNOWN_MACHINE, entitlements.unknown_machine()
        held = held if held is not None else self.repo.bookings_on_machine(machine["id"], who["email"])
        if kind == "occupied":
            # R10 narrows R7 here: the claim is the current assignment's, and the repeat (US35) is read
            # against the record the first claim left on the machine, not against the booking the
            # reassignment has already moved.
            if not entitlements.may_report_still_occupied(
                    who, held, machine["state"], bool(self.repo.reports_on_machine(machine["id"], who["email"]))):
                return entitlements.NOT_ENTITLED, entitlements.report_refusal()
        elif not entitlements.may_report(who, held):
            return entitlements.NOT_ENTITLED, entitlements.report_refusal()
        return entitlements.ALLOWED, None

    def machine_code_of(self, path) -> str:
        """The machine the request names, read off the URL segment, report suffix stripped."""
        tail = (path or "").split("/api/machines/", 1)[1]
        return tail.removesuffix("/report")

    def apply_report(self, who, machine, kind, now, held=None) -> tuple[int, dict]:
        """A report that is taken: the kind decides which core runs, and both write through the R6 table.

        The two seam paths differ on the success status, and on one thing that is a fact about the record and
        not about the gate: a device report is a fact the controller observed, is answered 200 and runs R8 in
        full, while a person's report is a claim the seam admits, is acknowledged with 202, and keeps the
        booking the entitlement was read against. A refusal keeps whatever status the decision gave it, and the
        gate is the same decision on both paths.
        """
        status, payload = (self.apply_fault(who, machine, now, faults.CLAIM) if kind == "fault"
                           else self.apply_occupied(who, machine, now, held))
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

        The incident the report leaves behind is read from the same file, in the same call, so the three paths
        cannot write three different things: `fault` on the claim surface and on the device boundary, nothing
        here on the panel, whose own action is recorded by the toggle. The record named on the incident is the
        one the entitlement was read against — the persisted booking, not a session flag — so the incident list
        the reviewer reads is the same fact the gate was answered with. This is also the single code path the
        deterministic trigger of issue #24 uses: the trigger is a request on one of these surfaces, so the demo
        and the test exercise one implementation.

        The pass itself (issue #19): the records are read in the order `faults.pass_order` gives them —
        earliest start first, ties by the order they were created — and each turn still owed is moved to the
        lowest-numbered free machine of the type with a new code and a notification for the customer the
        booking belongs to. A turn already run is a fact, not a turn to move; a turn the customer is standing
        in is moved immediately, and the cycle still ahead of the moment the report arrives goes with the
        record. What nothing of the type can cover is cancelled, the incident is `uncoverable`, and the day's
        allowance goes back with the record because the refund is the right to rebook. The invariant is checked
        after the pass on every surface and the answer carries what it found.
        """
        self.transition(machine["id"], "maintenance", now)
        held = self.repo.bookings_on_machine(machine["id"])
        record = faults.entitled_booking(who, held)
        kind = faults.incident_kind(surface)
        incident = (self.repo.record_incident(kind, now, f"fault reported on {machine['code']}",
                                             who["email"], machine["id"], record["id"] if record else None)
                    if kind else None)
        reassigned, cancelled, kept = [], [], []
        for booking in faults.pass_order(held):
            # AC1: earliest start first, ties broken by the order the records were created.
            if booking["state"] in machine_states.BOOKING_TERMINAL_STATES:
                continue
            start = parse(booking["start_time"])
            standing = faults.standing_at(booking)
            # A turn the machine has already run is not a turn to move; a turn the customer is standing in is
            # hers to move immediately (US40), because there is no staff to ask.
            if start <= now and not standing:
                continue
            if not faults.may_move(booking, surface, record):
                # AC3: the claim keeps the record it is read against, so the machine keeps exactly it.
                kept.append(str(booking["id"]))
                continue
            tariff = domain.tariff_of(machine["type"], self.config)
            replacement = self.pick_machine(machine["type"], start)
            if replacement is None:
                # US39: told honestly, and the turn is given back — the refund is the right to rebook, so the
                # day's count goes back with the booking and she can take a slot at once.
                self.repo.set_booking_state(booking["id"], "cancelled")
                self.repo.release_seat(booking["id"])
                cancelled.append(booking["code"])
                self.repo.record_incident("uncoverable", now, "no machine of the type free, turn refunded",
                                          booking["email"], machine["id"], booking["id"])
                self.notify("cancellation", booking, machine, now)
                continue
            new_code = self.repo.next_code(now)
            self.db.execute("UPDATE bookings SET machine_id = ?, code = ? WHERE id = ?",
                            (replacement["id"], new_code, booking["id"]))
            self.assign(replacement, now)
            entry = {"booking": str(booking["id"]), "machine": replacement["code"], "code": new_code,
                     "start": hhmm(start), "tokens": tariff.tokens_required}
            if standing:
                # US40: the machine she was standing at is released from her turn and the cycle still ahead of
                # the moment the fault was reported goes with the record. The start on the record stays.
                entry["standing"] = True
                entry["remaining_minutes"] = int((parse(booking["end_time"]) - now).total_seconds() // 60)
            reassigned.append(entry)
            self.repo.record_incident("reassignment", now, f"moved off {machine['code']}",
                                      booking["email"], replacement["id"], booking["id"])
            self.notify("reassignment", booking, replacement, now, new_code)
        # AC5: the invariant is checked after every pass, on every surface, and the answer carries what it
        # found. Where R8 runs in full it finds nothing; on the claim surface it names exactly the record the
        # entitlement was read against — the fork `src/faults.py` records for the human decision.
        attached = faults.still_attached(self.repo.bookings_on_machine(machine["id"]))
        return entitlements.ALLOWED, {"outcome": "maintenance", "machine": machine["code"],
                                      "incident": incident["kind"] if incident else None,
                                      "reassigned": reassigned, "cancelled": cancelled, "kept": kept,
                                      "attached": attached,
                                      "message": "Macchina messa fuori servizio"}

    def handle_occupied(self, body, headers, now, path=None):
        """The still-occupied report, gated on the same decision as the fault report and then narrowed.

        R7 gives the entitlement to a machine to anybody who has or had a turn on it; R10 narrows the
        still-occupied claim to the customer the machine is held for right now, because that claim is a
        statement about the machine that customer is standing in front of (issue #12, AC6). The gate runs
        before anything is written, and the refusal body is the same one the report surface answers with,
        so the two paths cannot drift on the permission.
        """
        who = self.customer(headers)
        machine = self.repo.machine(body.get("machine", ""))
        status, denial = self.report_gate(who, machine, kind="occupied")
        if status != entitlements.ALLOWED:
            return status, denial
        return self.apply_occupied(who, machine, now,
                                   self.repo.bookings_on_machine(machine["id"], who["email"]))

    def apply_occupied(self, who, machine, now, held=None) -> tuple[int, dict]:
        """R10's second half: the machine goes out of circulation, the customer is not left standing there.

        Three things the rule says and the seam has to answer with, in one core for both report paths:
        the machine goes to `cleaning_required` for the window the seed holds (30 minutes, addendum patch
        2, never a constant here); the customer the claim is read against is moved to a free machine of
        the same type at the same start time, with a new code and the notification US38 asks for; and when
        nothing of the type is free the booking is cancelled and the turn refunded so they can rebook at
        once (US39), which is also what puts the daily count back (R11 counts live bookings only).

        US35 repeat behaviour: a report that lands on a machine already in `cleaning_required` is accepted
        and the window restarts from the moment it arrives. It is not a hop — the state stands, the buffer
        is measured again — so the table declares no self-entry for it and the seam does not invent one.
        """
        held = held if held is not None else self.repo.bookings_on_machine(machine["id"], who["email"])
        booking = entitlements.current_booking(who, held)
        buffer = machine_states.REPEAT_REPORT["restarts"]
        minutes = self.config[buffer]
        repeated = machine["state"] == machine_states.REPEAT_REPORT["state"]
        if repeated:
            self.restart_window(machine, now)
        else:
            self.transition(machine["id"], "cleaning_required", now)
        self.repo.record_incident("cleaning_required", now, f"reported still occupied on {machine['code']}",
                                  who["email"], machine["id"], booking["id"] if booking else None)
        outcome = {"outcome": "cleaning_required", "machine": machine["code"],
                   "cleaning_minutes": minutes, "clean_until": hhmm(now + timedelta(minutes=minutes)),
                   "repeat": repeated}
        if booking is None:
            # The window restarts for the customer who is not standing in front of it any more: the claim is
            # the record they had, and there is no assignment left here to move.
            outcome["reassigned"] = None
            outcome["message"] = "Macchina in pulizia: la finestra riparte da questo momento"
            return entitlements.ALLOWED, outcome

        start = parse(booking["start_time"])
        replacement = self.pick_machine(machine["type"], start)
        if replacement is None:
            self.repo.set_booking_state(booking["id"], "cancelled")
            self.repo.release_seat(booking["id"])
            self.repo.record_incident("uncoverable", now, "no machine of the type free, turn refunded",
                                      who["email"], machine["id"], booking["id"])
            outcome["reassigned"] = None
            outcome["cancelled"] = booking["code"]
            row = self.notify("cancellation", booking, machine, now)
            outcome["notification"] = notifications.view(row, machine["code"], notifications.INCIDENT)
            outcome["message"] = "Macchina in pulizia: nessuna macchina libera, turno rimborsato"
            return entitlements.ALLOWED, outcome

        new_code = self.repo.next_code(now)
        self.db.execute("UPDATE bookings SET machine_id = ?, code = ? WHERE id = ?",
                        (replacement["id"], new_code, booking["id"]))
        self.assign(replacement, now)
        self.repo.record_incident("reassignment", now, f"moved off {machine['code']}",
                                  who["email"], replacement["id"], booking["id"])
        outcome["reassigned"] = {"booking": str(booking["id"]), "machine": replacement["code"],
                                 "code": new_code, "start": hhmm(start)}
        # US38: the notification carries the new machine number, because the customer would otherwise walk
        # to the machine the report was about. The row is the fact the app shows on her own read; the answer
        # carries the same fact in the incident word the report answers with.
        row = self.notify("reassignment", booking, replacement, now, new_code)
        outcome["notification"] = notifications.view(row, replacement["code"], notifications.INCIDENT)
        outcome["message"] = "Macchina in pulizia: sei stato spostato subito"
        return entitlements.ALLOWED, outcome

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
        """An incident carries the machine it happened on as the reviewer reads it: the machine code.

        `booking` is the record the incident is about, in the spelling the read of the incident answers with;
        `booking_id` stays the spelling the owner's surface was pinned on. The same record, never two values
        for it, and no customer and no code on the observer's read (US22, US42).
        """
        machine = self.repo.machine_by_id(row["machine_id"]) if row["machine_id"] else None
        view = {"id": row["id"], "kind": row["kind"], "machine": machine["code"] if machine else None,
                "booking": str(row["booking_id"]) if row["booking_id"] is not None else None,
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

    def restart_window(self, machine, now) -> None:
        """US35: the window is re-measured, not re-transitioned.

        `transition` stays the only writer of a machine state. A repeat report writes no state — the machine
        is already out of circulation for the cleaning window — it moves the moment the buffer is measured
        from, which is the whole of the repeat behaviour. The table declares no self-hop, so the seam does
        not invent one.
        """
        self.repo.set_machine_state(machine["id"], machine["state"], now)


class InvalidTransition(Exception):
    """A hop the table does not declare. It carries the attempted transition so 409 can name it."""

    def __init__(self, current: str, to: str, event: str | None = None) -> None:
        super().__init__(f"{current} -> {to}")
        self.current = current
        self.to = to
        self.event = event
