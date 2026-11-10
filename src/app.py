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
"""

import hashlib
from datetime import datetime, timedelta

from src import availability, domain, machine_states, rules
from src.clock import Clock
from src.domain import time as start_times
from src.config import SEED
from src.repository import Repository, parse

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

# Demo mode (addendum patch 1): nothing leaves the machine and the one-time code is shown in-app, so
# the reviewer's session has no token. An unauthenticated caller is the demo identity: it can book and
# it can read the state of a single machine, which is what AC 8 asks for — a reviewer watching the
# transitions live without signing in. A signed-in customer keeps its entitlements: the owner board and
# the incident list stay closed to customers (tests/test_journey.py), and the fallback happens only
# when there is no token at all, never for a token that does not resolve.
DEMO_IDENTITY = {"email": "demo@quickwash.local", "is_owner": 0, "is_demo": True}


def hhmm(moment: datetime) -> str:
    return moment.strftime("%H:%M")


class Application:
    def __init__(self, db, clock: Clock | None = None, config: dict = SEED) -> None:
        self.db = db
        self.clock = clock or Clock()
        self.repo = Repository(db, config)
        self.repo.reset()
        self.config = self.repo.settings()

    # --- seam ---------------------------------------------------------------

    def handle(self, method: str, path: str, body: dict | None = None,
               headers: dict | None = None) -> tuple[int, dict]:
        name = (ROUTES.get((method, path)) or SEED_WRITE.get(f"{method} {path}")
                or self.pattern_route(method, path))
        if name is None:
            return 404, {"error": "not_found", "message": f"Percorso sconosciuto: {path}"}
        # R10 and AC 3: the two buffer hops are carried by time, not by a caller, so a request
        # resolves the elapsed buffers before answering. That is what makes the state read a live read.
        self.resolve_buffers(self.clock.now())
        try:
            return getattr(self, f"handle_{name}")(body or {}, headers or {}, path)
        except InvalidTransition as bad:
            # R6: invalid transitions are rejected, never silently coerced. The attempted hop is in
            # the body, and the machine keeps the state the table had declared for it.
            payload = {"error": "invalid_transition", "from": bad.current, "to": bad.to,
                       "transition": f"{bad.current} -> {bad.to}",
                       "declared": sorted(machine_states.TRANSITIONS.get(bad.current, set())),
                       "message": f"Transizione non valida: {bad.current} -> {bad.to}"}
            if bad.event:
                payload["event"] = bad.event
            return 409, payload

    def pattern_route(self, method: str, path: str) -> str | None:
        """The per-machine read (AC 8): a pattern, not a ninth contract path."""
        if method == PER_MACHINE_READ[0] and path.startswith(PER_MACHINE_READ[1]):
            return "machine"
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

    # --- identity -----------------------------------------------------------

    def handle_session(self, body, headers, path=None):
        email = body.get("email")
        if not email:
            return 400, {"error": "email_required", "message": "Serve un'email per entrare"}
        identity = self.repo.get_or_create_identity(email, email == self.config["owner_email"])
        now = self.clock.now()

        if body.get("code") is None:
            # Patch 1 of the addendum: the code is shown in-app, no email or SMS transport.
            otp = f"{int(hashlib.sha256(email.encode()).hexdigest()[:6], 16) % 1000000:06d}"
            self.repo.issue_otp(email, now, otp)
            return 201, {
                "email": email,
                "otp": otp,
                "displayed_in_app": bool(self.config["otp_displayed_in_app"]),
                "token": None,
                "message": "Codice mostrato in-app: nessun'email, nessun SMS",
            }

        if body.get("code") != self.repo.current_otp(email):
            return 401, {"error": "invalid_code", "message": "Codice non valido"}
        token = self.repo.create_session(email, now)
        return 200, {"email": email, "token": token, "is_owner": bool(identity["is_owner"])}

    def identity(self, headers) -> dict | None:
        token = (headers or {}).get("Authorization", "").removeprefix("Bearer ")
        if not token:
            # No token at all is the demo reviewer, not a signed-in customer (see DEMO_IDENTITY).
            return dict(DEMO_IDENTITY)
        session = self.repo.session_owner(token)
        if session is None:
            return None
        return self.repo.get_or_create_identity(session["email"], session["email"] == self.config["owner_email"])

    def may_observe(self, who) -> bool:
        """A signed-in customer never reads the owner panel. The demo reviewer has no session to
        begin with, and AC 8 asks for that reviewer to watch the state machine live."""
        return who is None or bool(who.get("is_demo")) or bool(who.get("is_owner"))
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
        who = self.identity(headers)
        if who is None:
            return 401, {"error": "sign_in_required", "message": "Entra con email e codice per prenotare"}
        now = self.clock.now()

        blocked = rules.no_show_block(self.repo.no_shows(who["email"]), now.date(), self.config)
        if blocked:
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

        self.assign(machine, now)
        view = self.booking_view(booking, machine["code"])
        # The booking is the payload, and `booking` is the same object under its key: the response can
        # be read either way — straight off it (the machine, the code, the state) or as the booking.
        return 201, {**view, "booking": view}

    def handle_bookings(self, body, headers, path=None):
        who = self.identity(headers)
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

    def booking_view(self, booking, machine_code=None):
        start = parse(booking["start_time"])
        grace_from, grace_to = rules.grace_window(start, self.config)
        machine = machine_code
        if machine is None:
            row = self.db.one("SELECT code FROM machines WHERE id = ?", (booking["machine_id"],))
            machine = row["code"] if row else None
        return {
            "id": booking["id"],
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
        who = self.identity(headers)
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
        who = self.identity(headers)
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
        who = self.identity(headers)
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
        who = self.identity(headers)
        if not self.may_observe(who):
            return 403, {"error": "owner_only", "message": "Il pannello proprietario è riservato al proprietario"}
        # The response is the list itself: the incident list is what a reviewer reads to see what the
        # shop suffered. A signed-in customer still cannot read it, and an observer sees no customer.
        return 200, [self.incident_view(row, observer=who is None or bool(who.get("is_demo")))
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
