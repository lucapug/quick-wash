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
"""

from datetime import datetime, timedelta

from src import availability, domain, entitlements, machine_states, rules
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
               headers: dict | None = None) -> tuple[int, dict]:
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
        # The request line is all telemetry sees here: the path without its query, the status, the name of
        # the handler and the journey. Never the body, which is where a credential arrives (AC3).
        self.telemetry.record(method, path, status, event=name, journey=self.journey)
        return status, payload

    def pattern_route(self, method: str, path: str) -> str | None:
        """The reads that are patterns, not contract paths: one machine (AC 8), the code, the logs."""
        name = PATTERNS.get(f"{method} {path}")
        if name:
            return name
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
            # R5: the persistence layer refused the slot, not a pre-check.
            return 409, {
                "error": "slot_taken",
                "enforced_by": "persistence layer",
                "alternatives": answer["alternatives"],
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
        """
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
        caller who is not entitled. The cancellation window (R4) is issue #15 — this slice carries the
        entitlement, and here only the state that is already committed to a machine is refused.
        """
        booking = self.repo.booking_by_id(self.booking_id_of(path))
        who = self.customer(headers)
        status, denial = self.booking_entitlement(who, booking)
        if status != entitlements.ALLOWED:
            return status, denial
        now = self.clock.now()
        if booking["state"] != "confirmed":
            # US46: the state of a booking that can no longer be cancelled is shown. The window that
            # decides it (R4) is issue #15; here the machine is already committed, so the state is the
            # whole of the answer.
            return 409, {"error": "not_cancellable", "state": booking["state"],
                          "message": f"La prenotazione non è cancellabile: stato {booking['state']}"}
        self.trace(booking)
        machine = self.repo.machine_by_id(booking["machine_id"])
        self.repo.set_booking_state(booking["id"], "cancelled")
        if machine is not None and machine["state"] == "reserved":
            # US45: the slot becomes bookable by others at once.
            self.transition(machine["id"], "available", now)
        self.repo.record_incident("cancellation", now, "cancelled at the seam", booking["email"],
                                  booking["machine_id"], booking["id"])
        # The answer is the booking as the row is now, not as it was when the request arrived.
        return 200, {"outcome": "cancelled", "booking": self.booking_view(self.repo.booking_by_id(booking["id"])),
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
            "expected_end": hhmm(parse(booking["end_time"])),
            "tokens": booking["tokens"],
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
        who = self.customer(headers)
        if who is None:
            return 401, {"error": "sign_in_required", "message": "Entra con email e codice"}
        machine = self.repo.machine(body.get("machine", ""))
        if machine is None:
            return 404, {"error": "unknown_machine", "message": "Macchina sconosciuta"}
        # R7: only a customer who has or had a booking on that machine may report it.
        if not self.repo.bookings_on_machine(machine["id"], who["email"]):
            return 403, {"error": "not_allowed", "message": "Puoi segnalare solo una macchina su cui hai o hai avuto una prenotazione"}

        self.transition(machine["id"], "maintenance", now)
        reassigned, cancelled = [], []
        for booking in self.repo.bookings_on_machine(machine["id"]):
            start = parse(booking["start_time"])
            if start <= now or booking["state"] in ("expired", "cancelled", "closed"):
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
        return 200, {"outcome": "maintenance", "machine": machine["code"], "reassigned": reassigned,
                     "cancelled": cancelled, "message": "Macchina messa fuori servizio"}

    def handle_occupied(self, body, headers, now, path=None):
        who = self.customer(headers)
        if who is None:
            return 401, {"error": "sign_in_required", "message": "Entra con email e codice"}
        machine = self.repo.machine(body.get("machine", ""))
        if machine is None:
            return 404, {"error": "unknown_machine", "message": "Macchina sconosciuta"}
        if not self.repo.bookings_on_machine(machine["id"], who["email"]):
            return 403, {"error": "not_allowed", "message": "Puoi segnalare solo una macchina su cui hai o hai avuto una prenotazione"}

        self.transition(machine["id"], "cleaning_required", now)
        booking = next((row for row in self.repo.bookings_for(who["email"])
                        if row["machine_id"] == machine["id"] and row["state"] in ("confirmed", "unlocked", "running")), None)
        if booking is None:
            return 403, {"error": "no_active_booking", "message": "Nessuna prenotazione attiva su questa macchina"}

        start = parse(booking["start_time"])
        replacement = self.pick_machine(machine["type"], start)
        if replacement is None:
            return 200, {"outcome": "cleaning_required", "machine": machine["code"], "reassigned": None,
                         "message": "Macchina segnata per la pulizia: nessuna macchina libera dello stesso tipo"}
        new_code = self.repo.next_code(now)
        self.db.execute("UPDATE bookings SET machine_id = ?, code = ? WHERE id = ?",
                        (replacement["id"], new_code, booking["id"]))
        self.assign(replacement, now)
        self.repo.record_incident("cleaning_required", now, f"reported still occupied on {machine['code']}",
                                  who["email"], machine["id"], booking["id"])
        cleaned_at = now + timedelta(minutes=self.config["cleaning_buffer_minutes"])
        return 200, {"outcome": "cleaning_required", "machine": machine["code"],
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

    # --- owner panel ---------------------------------------------------------

    def handle_machines(self, body, headers, path=None):
        who = self.who_is_asking(headers)
        if who is None or not who["is_owner"]:
            return 403, {"error": "owner_only", "message": "Il pannello proprietario è riservato al proprietario"}
        board = []
        for machine in self.repo.machines():
            attached = [row for row in self.repo.bookings_on_machine(machine["id"])
                        if row["state"] in ("confirmed", "unlocked", "running")]
            board.append({**domain.machine_view(machine, self.config),
                          "machine": machine["code"],
                          "bookings": [self.booking_view(row, machine["code"]) for row in attached]})
        return 200, {"machines": board}

    def handle_incidents(self, body, headers, path=None):
        who = self.who_is_asking(headers)
        if not self.may_observe(who):
            return 403, {"error": "owner_only", "message": "Il pannello proprietario è riservato al proprietario"}
        # The response is the list itself: the incident list is what a reviewer reads to see what the
        # shop suffered. A signed-in customer still cannot read it, and an observer sees no customer.
        return 200, [self.incident_view(row, observer=bool((who or {}).get("is_observer")))
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
        key = machine_states.BUFFER_HOPS.get(machine["state"])
        buffer = self.config[key] if key else None
        bookable_from = self.clock.now() + timedelta(minutes=buffer) if buffer else None
        return 200, {**view, "machine": machine["code"], "state": machine["state"],
                     "changed_at": machine["changed_at"], "buffer_minutes": buffer,
                     "bookable_from": hhmm(bookable_from) if bookable_from else None,
                     "assignable": self.is_assignable(machine, self.clock.now())}

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
