"""The HTTP boundary of the backend: the single seam every test uses.

Handlers return (status, payload). Paths are the contract fixed by tests/conftest.py (SEAM_PATHS)
and mirrored in docs/api-contract.md: POST /api/session, GET /api/availability, POST /api/bookings,
GET /api/bookings, POST /api/lock/redeem, POST /api/lock/reports, GET /api/machines,
GET /api/incidents.

The contract fixes one path per entry, so the seed write for the machine inventory sits on the same
path as its read (`POST /api/machines`, resolved through SEED_WRITE): the machine registry has no
screen, the write accepts a type and nothing else, and the machine answers with the type's tariff
and duration — never with a field of its own.

Keys are English, user-facing copy is Italian. Nothing here logs a customer email, an unlock code
or a one-time code.
"""

import hashlib
from datetime import datetime, timedelta

from src import domain, rules
from src.clock import Clock
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

MACHINE_TRANSITIONS = {
    "available": {"reserved", "maintenance"},
    # R10: the next assigned customer may report the machine as still occupied, so a reserved
    # machine can go to cleaning_required as well as the finished one it came from.
    "reserved": {"unlocked", "available", "maintenance", "cleaning_required"},
    "unlocked": {"running", "available", "maintenance"},
    "running": {"finished"},
    "finished": {"available", "cleaning_required", "maintenance"},
    "cleaning_required": {"available", "maintenance"},
    "maintenance": {"available"},
}

DEVICE_EVENTS = {"cycle_started", "cycle_finished", "idle_open", "fault", "occupied"}


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
        name = ROUTES.get((method, path)) or SEED_WRITE.get(f"{method} {path}")
        if name is None:
            return 404, {"error": "not_found", "message": f"Percorso sconosciuto: {path}"}
        try:
            return getattr(self, f"handle_{name}")(body or {}, headers or {})
        except InvalidTransition as bad:
            # R6: invalid transitions are rejected, never silently coerced.
            return 409, {"error": "invalid_transition", "from": bad.current, "to": bad.to,
                          "message": f"Transizione non valida: {bad.current} -> {bad.to}"}

    # --- identity -----------------------------------------------------------

    def handle_session(self, body, headers):
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
            return None
        session = self.repo.session_owner(token)
        if session is None:
            return None
        return self.repo.get_or_create_identity(session["email"], session["email"] == self.config["owner_email"])

    # --- availability (public, US8) ----------------------------------------

    def handle_availability(self, body, headers):
        now = self.clock.now()
        day = now.date()
        open_day = day.strftime("%A") not in self.config["closed_days"]
        inventory = self.repo.machine_counts()
        types = []
        for type_key, count in inventory.items():
            tariff = domain.tariff_of(type_key, self.config)
            starts = rules.valid_start_times(type_key, self.config, day)
            usable = [start for start in starts if start >= now]
            earliest = usable[0] if usable else now
            free = [machine for machine in self.repo.machines()
                    if machine["type"] == type_key and self.is_assignable(machine, earliest)]
            types.append({
                "type": type_key,
                "capacity_kg": tariff.capacity_kg,
                "cycle_minutes": tariff.cycle_minutes,
                "tokens": tariff.tokens_required,
                "machines": count,
                "free": len(free),
                "earliest_start": hhmm(usable[0]) if usable else None,
                "why": self.why(type_key, now, open_day, usable, len(free)),
            })
        return 200, {
            "open_now": open_day and self.is_inside_hours(now),
            "opening_hours": self.config["opening_hours"],
            "closed_days": self.config["closed_days"],
            "grid_minutes": self.config["grid_minutes"],
            "types": types,
            # AC 7: the seed numbers verbatim, so a reviewer can read them without reading code.
            "config": domain.seed_view(inventory, self.config),
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
        now = self.clock.now()
        state = machine["state"]
        changed = parse(machine["changed_at"])
        # R10: a finished machine stays unbookable for the turnover buffer, and a machine reported
        # still occupied stays out of circulation for the cleaning buffer (addendum patch 2).
        if state == "finished" and now - changed < timedelta(minutes=self.config["turnover_buffer_minutes"]):
            return False
        if state == "cleaning_required" and now - changed < timedelta(minutes=self.config["cleaning_buffer_minutes"]):
            return False
        if state not in ("available", "finished", "cleaning_required"):
            return False
        return self.repo.booking_on_machine(machine["id"], start) is None

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

    def handle_booking(self, body, headers):
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

        valid = rules.valid_start_times(type_key, self.config, start.date())
        alternatives = [hhmm(moment) for moment in valid if moment > start]
        if start not in valid:
            return 409, {
                "error": "slot_not_valid",
                "reason": self.refusal_reason(type_key, start),
                "alternatives": alternatives,
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
                "alternatives": [hhmm(moment) for moment in valid if moment >= now],
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
                "alternatives": [hhmm(moment) for moment in valid if moment > start],
                "message": "Lo slot è stato assegnato a un altro cliente: scegli un orario alternativo",
            }

        self.assign(machine, now)
        return 201, {"booking": self.booking_view(booking, machine["code"])}

    def handle_bookings(self, body, headers):
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

    def refusal_reason(self, type_key: str, start) -> str:
        day = start.date()
        if day.strftime("%A") in self.config["closed_days"]:
            return "closed day"
        if not self.is_inside_hours(start):
            return "outside opening hours"
        cycle = timedelta(minutes=domain.tariff_of(type_key, self.config).cycle_minutes)
        close = datetime.combine(day, self._time_of(self.config["opening_hours"]["close"]))
        if start + cycle > close:
            return "cycle would overrun closing time"
        return "start not on the 15-minute grid"

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

    def handle_redeem(self, body, headers):
        code = body.get("code")
        booking = self.repo.booking_by_code(code) if code else None
        if booking is None:
            return 404, {"outcome": "unknown_code", "message": "Codice sconosciuto"}
        now = self.clock.now()
        start = parse(booking["start_time"])
        grace_from, grace_to = rules.grace_window(start, self.config)

        if booking["state"] == "confirmed" and now < grace_from:
            return 403, {"outcome": "not_your_time", "message": "Il codice funziona dall'orario di inizio, non prima",
                          "valid_from": hhmm(grace_from)}
        if booking["state"] == "confirmed" and now > grace_to:
            self.transition(booking["machine_id"], "available", now)
            self.repo.set_booking_state(booking["id"], "expired")
            self.repo.record_no_show(booking["email"], now, booking["id"])
            incident = self.repo.record_incident("no_show", now, f"code {code} not redeemed within the grace window",
                                                 booking["email"], booking["machine_id"], booking["id"])
            return 409, {"outcome": "expired", "message": "Il codice non funziona più: la finestra di tolleranza è finita",
                         "grace_window": {"from": hhmm(grace_from), "to": hhmm(grace_to)},
                         "incident": incident["kind"]}
        if booking["state"] == "unlocked":
            return 409, {"outcome": "already_redeemed", "message": "Il codice è già stato usato"}

        self.transition(booking["machine_id"], "unlocked", now)
        self.repo.set_booking_state(booking["id"], "unlocked")
        self.repo.record_redeemed(booking["id"], now)
        machine = self.db.one("SELECT * FROM machines WHERE id = ?", (booking["machine_id"],))
        return 200, {"outcome": "unlocked", "machine": machine["code"], "tokens_required": booking["tokens"]}

    def handle_report(self, body, headers):
        event = body.get("event")
        if event not in DEVICE_EVENTS:
            return 400, {"error": "unknown_event", "message": "Evento dispositivo sconosciuto",
                         "accepted": sorted(DEVICE_EVENTS)}
        now = self.clock.now()

        if event == "fault":
            return self.handle_fault(body, headers, now)
        if event == "occupied":
            return self.handle_occupied(body, headers, now)

        booking = self.repo.booking_by_code(body.get("code")) if body.get("code") else None
        if booking is None:
            return 404, {"outcome": "unknown_code", "message": "Codice sconosciuto"}

        if event == "cycle_started":
            self.transition(booking["machine_id"], "running", now)
            self.repo.set_booking_state(booking["id"], "running")
            return 200, {"outcome": "running", "expected_end": hhmm(parse(booking["end_time"]))}

        if event == "cycle_finished":
            self.transition(booking["machine_id"], "finished", now)
            self.repo.set_booking_state(booking["id"], "finished")
            free_at = now + timedelta(minutes=self.config["turnover_buffer_minutes"])
            return 200, {"outcome": "finished", "turnover_minutes": self.config["turnover_buffer_minutes"],
                          "bookable_from": hhmm(free_at)}

        # idle_open: an event, not a state — unlocked with no cycle_started inside 15 minutes.
        if booking["state"] != "unlocked":
            return 409, {"error": "invalid_transition", "message": "idle_open vale solo per una macchina aperta e non avviata"}
        idle = now - parse(booking["redeemed_at"]) if booking["redeemed_at"] else timedelta(0)
        if idle < timedelta(minutes=self.config["idle_open_minutes"]):
            return 409, {"error": "too_early", "message": "idle_open richiede almeno 15 minuti dall'apertura"}
        self.repo.set_booking_state(booking["id"], "closed")
        self.transition(booking["machine_id"], "available", now)
        self.repo.record_no_show(booking["email"], now, booking["id"])
        incident = self.repo.record_incident("idle_open", now, "machine opened, cycle never started",
                                             booking["email"], booking["machine_id"], booking["id"])
        return 200, {"outcome": "closed", "machine": self.machine_code(booking["machine_id"]),
                     "incident": incident["kind"], "message": "Turno perso: macchina liberata"}

    def handle_fault(self, body, headers, now):
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

    def handle_occupied(self, body, headers, now):
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

    def handle_create_machine(self, body, headers):
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

    def handle_machines(self, body, headers):
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

    def handle_incidents(self, body, headers):
        who = self.identity(headers)
        if who is None or not who["is_owner"]:
            return 403, {"error": "owner_only", "message": "Il pannello proprietario è riservato al proprietario"}
        return 200, {"incidents": self.repo.incidents()}

    # --- state machine (R6) -------------------------------------------------

    def transition(self, machine_id: int, to: str, now: datetime) -> None:
        machine = self.db.one("SELECT * FROM machines WHERE id = ?", (machine_id,))
        current = machine["state"]
        if to not in MACHINE_TRANSITIONS.get(current, set()):
            raise InvalidTransition(current, to)
        self.repo.set_machine_state(machine_id, to, now)

    def machine_code(self, machine_id: int) -> str:
        row = self.db.one("SELECT code FROM machines WHERE id = ?", (machine_id,))
        return row["code"] if row else None


class InvalidTransition(Exception):
    def __init__(self, current: str, to: str) -> None:
        super().__init__(f"{current} -> {to}")
        self.current = current
        self.to = to
