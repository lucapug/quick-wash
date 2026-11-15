"""The customer frontend: the screens the customer reads, and the one place the copy lives.

The issue's Decision names React (Vite) with Bootstrap CSS and **no backend-for-frontend layer**, because
the frontend talks to the backend over the same HTTP seam the tests use. Two facts about this repository's
boundary decide the shape of this module:

- nothing outside `src/` and `tests/` can be written here, so there is no `package.json` install, no
  `node_modules` and no build step; what is inside the boundary is the app shell (`src/frontend/`) and the
  Bootstrap markup the screens are marked up with. The shell owns no copy: it shows what the seam answers.
- the issue's own test reads a customer page as text at the seam (`GET /api/views/availability`,
  `GET /api/views/bookings`). A static bundle cannot answer that, so the screens are rendered. The render is
  a **presentation read**, not a second layer that decides: every number, every reason and every
  entitlement on a page comes from the module that already owns the decision — `src/availability.py`,
  `src/domain/time.py`, `src/daily_limit.py`, `src/domain/counters.py`, `src/cancellation.py`,
  `src/entitlements.py`, `src/notifications.py`. No rule is written twice, and the tested seam is not put
  behind anything: the view reads are patterns, so `ROUTES` stays the eight entries `tests/conftest.py` pins.

**Language, and the one conflict the issue carries.** AC1 asks for an Italian interface; the issue's
Decision overrides it — the reviewers who evaluate and use the app read English — so the static copy here
is English (`COPY`, `REASON_COPY`) and the documentation stays English. AC4 asks for a reason for every gap
"using the vocabulary from issue #10": that vocabulary is the seven pinned tokens of
`src/availability.py::REASONS` (`all_machines_busy`, `machine_in_maintenance`, `would_overrun_closing`,
`closed_day`, `outside_opening_hours`, `turnover_buffer`, `cleaning_buffer`), which the tests read as data
and which stays exactly as pinned. What the Decision moves is the *sentence around the token*: the gap line
shows the token and its English sentence from `REASON_COPY`, one entry per token, no other word. Domain
copy the tests pin in the API's language (`entitlements`, `daily_limit`, `counters`, `notifications`) is
shown as-is where it occurs; it is not part of `strings()`. That is the whole language rule, stated once so
the code, the tests and the reviewer read the same thing.

The four screens, and the criterion each one carries:

1. **availability** — readable without signing in (issue #10, US8): per type the cycle duration and the
   token count (60/4, 75/6, 30/3), the earliest valid start offered first so the common case is one tap,
   and a reason in the pinned vocabulary for every slot the type cannot give. It names no machine, no
   customer and no code (issue #8, AC2 and AC6): the page answers per type, never per machine.
2. **sign-in** — email plus the one-time code shown in-app (issue #11, addendum patch 1): no password field
   anywhere, and no field name that reads as one.
3. **book** — machine number, start time, expected end time and tokens required, stated *before* the
   customer commits. It is the first screen where a machine is named, because it is the customer's own turn.
4. **my bookings** — state, the R4 cutoff (15 minutes), the R11 limit and its reset, the R9 block with its
   expiry, the reassignment with the new machine number (issue #19), and the two report actions on the
   customer's own machine only (R7, narrowed by R10). The unlock code appears inside the customer's own
   booking and nowhere else: no page answered to another caller carries it.

The gate on the two customer pages is the same decision as the booking surface — 401 for a caller with no
session — so a UI control is never the enforcement: the read is refused at the seam.
"""

import html
from datetime import timedelta

from src import availability, cancellation, daily_limit, entitlements, notifications
from src.domain import counters
from src.domain import time as start_times
from src.repository import parse

# The language split as data: the interface in English (the issue's Decision, which overrides AC1), the
# documentation in English. `strings()` is checked against this, so the split is an assertion and not a
# statement.
LANGUAGE = "en"
DOCUMENTATION_LANGUAGE = "en"

# The words that would read as Italian. They are here so the language rule can be tested on the copy table
# as data; the as-is domain copy the tests pin is outside `strings()` and is not affected by them.
ITALIAN_MARKERS = ("macchina", "prenotazione", "prenotazioni", "codice", "cliente", "minuti", "giorni",
                   "libera", "puoi", "sei", "hai", "può", "della", "delle", "quando", "è", "é", "à",
                   "ò", "ì", "ù")

# The single stylesheet the screens are marked up with (Bootstrap CSS, as the Decision names it).
BOOTSTRAP = "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"

# The four screens, in the spelling the URL segment reads.
SCREENS = ("availability", "sign-in", "book", "bookings")
NAV = (("availability", "Availability"), ("sign-in", "Sign in"), ("book", "Book a machine"),
       ("bookings", "My bookings"))

# Every customer-facing string, in English, in one place. The as-is domain copy is not here: it is the
# pinned decision's own language and is shown as-is where it occurs.
COPY = {
    "brand": "quick-wash",
    "title_availability": "Availability",
    "title_sign_in": "Sign in",
    "title_book": "Book a machine",
    "title_bookings": "My bookings",
    "availability_note": "You can read this page without signing in.",
    "hours_note": "Open {open} to {close}, closed {closed_days}. Slots on a {grid}-minute grid. {state}",
    "open_now": "Open now",
    "closed_now": "Closed",
    "type_row": "{type}: {cycle} minutes, {tokens} tokens, {machines} machines, {free} free now",
    "type_note": "Availability is answered per type, never per machine: this page names no machine, no customer and no code.",
    "earliest_first": "Earliest start you can take: {start}",
    "take": "Take {start}",
    "slot_unavailable": "{start} - {reason}: {why}",
    "no_slot": "Nothing this type can give you in the window.",
    "sign_in_note": "Sign in with your email and the one-time code shown here in the app: no email, no SMS, no password field.",
    "code_shown": "The code is shown in-app when you ask for it ({ttl} minutes, used once).",
    "email_field": "Email",
    "sign_in_button": "Ask for the code",
    "gate_note": "This page needs the sign-in: the read is refused at the seam, not hidden by the page.",
    "book_note": "Check these four things before you commit.",
    "machine": "Machine: {machine}",
    "start": "Start: {start}",
    "expected_end": "Expected end: {end}",
    "tokens": "Tokens required: {tokens}",
    "commit": "Commit booking",
    "no_machine": "No machine of this type can be given for that slot, so there is nothing to commit.",
    "unknown_type": "Unknown machine type.",
    "slot_refused": "That slot cannot be honoured: {reason}: {why}. Next starts: {alternatives}.",
    "state": "State: {state}",
    "code": "Unlock code: {code} (shown only inside your own booking)",
    "cutoff": "Free cancellation up to {cutoff} minutes before start. Last minute: {until}. {situation}",
    "cancellable": "You can still cancel.",
    "past_cutoff": "You can no longer cancel this booking.",
    "limit": "Daily limit {limit} bookings: {used} used, {remaining} left. Resets at {resets_at}.",
    "block": "No-show counter: {no_shows} in the last {window_days} days. {situation}",
    "blocked": "Blocked until {until}.",
    "not_blocked": "Not blocked.",
    "reassignment": "Moved to machine {machine} ({at}) - this is the machine you have to walk to.",
    "report_note": "You can report only a machine that is or was yours. The gate is the same on the seam.",
    "report_fault": "Report a fault",
    "report_occupied": "Report still occupied",
    "not_your_machine": "not your machine",
    "no_booking": "You have no booking to show.",
    "booking_row": "{machine} - {start} to {end}, {tokens} tokens, {state}",
}

# AC4, read together with the Decision: the token is the pinned vocabulary of issue #10 and the sentence
# that reads it is English. One entry per token, exactly `availability.REASONS`, no other word.
REASON_COPY = {
    "all_machines_busy": "every machine of this type is already committed for that slot",
    "machine_in_maintenance": "every machine of this type is out of service",
    "would_overrun_closing": "the cycle would end after closing time",
    "closed_day": "the shop is closed on that day",
    "outside_opening_hours": "the slot is outside opening hours",
    "turnover_buffer": "the machines of this type are inside their turnover buffer",
    "cleaning_buffer": "the machines of this type are inside their cleaning buffer",
}

# One cause the public window never names: a slot that has already begun cannot be a gap in a window, so
# it is outside `REASONS`. It is kept apart on purpose, so `REASON_COPY` stays exactly the pinned seven.
EXTRA_REASON_COPY = {"in_the_past": "that slot has already begun"}

# The two report actions, and the seam path each one posts to. The shell has no copy of its own: this is
# the pair it reads.
REPORT_ACTIONS = (("fault", COPY["report_fault"]), ("occupied", COPY["report_occupied"]))


def strings() -> dict:
    """The customer-facing strings, so the language split is readable as data."""
    return {**COPY, **REASON_COPY, **EXTRA_REASON_COPY}


def italian_markers(text: str) -> list:
    """Which Italian markers a string would read as. Empty for copy that follows the Decision."""
    lower = str(text).lower()
    return [marker for marker in ITALIAN_MARKERS if marker in lower]


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def copy(key: str, **values) -> str:
    """One customer-facing string, from the one place they live."""
    text = COPY[key] if key in COPY else EXTRA_REASON_COPY[key]
    return text.format(**{name: esc(value) for name, value in values.items()})


def reason(word: str) -> str:
    """The English sentence for a reason named by the pinned vocabulary."""
    return REASON_COPY.get(word) or EXTRA_REASON_COPY.get(word) or COPY["no_slot"]


# --- the page shell -----------------------------------------------------------

def page(screen: str, content: str) -> str:
    title = COPY[f"title_{screen.replace('-', '_')}"]
    links = "".join(
        '<li class="nav-item"><a class="nav-link{active}" href="/api/views/{segment}">{label}</a></li>'.format(
            active=" active" if segment == screen else "", segment=segment, label=esc(label))
        for segment, label in NAV)
    return (f'<!doctype html><html lang="{LANGUAGE}"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{esc(COPY["brand"])} - {esc(title)}</title>'
            f'<link rel="stylesheet" href="{BOOTSTRAP}"></head><body>'
            '<nav class="navbar navbar-expand border-bottom"><div class="container">'
            f'<span class="navbar-brand">{esc(COPY["brand"])}</span><ul class="nav">{links}</ul></div></nav>'
            f'<main class="container py-4" data-screen="{esc(screen)}"><h2>{esc(title)}</h2>{content}'
            '</main></body></html>')


def gate(screen: str) -> tuple[int, str]:
    """401 for a caller with no session: the same decision the booking surface uses (issue #10, AC2)."""
    denial = entitlements.missing_session()
    body = ('<p>{note}</p><p class="text-danger">{denial}</p>'
            '<p><a class="btn btn-primary" href="/api/views/sign-in">{button}</a></p>').format(
        note=copy("gate_note"), denial=esc(denial["message"]), button=copy("sign_in_button"))
    return entitlements.MISSING_SESSION, page(screen, body)


# --- 1. availability: open to a caller with no session -----------------------------------------

def slot_line(point, type_key: str, earliest: bool = False) -> str:
    word = point["reason"]
    classes = "slot available" if word is None else "slot unavailable"
    if word is None:
        inner = (f'<a class="btn btn-primary" data-action="take" data-type="{esc(type_key)}" '
                 f'data-start="{esc(point["start"])}" '
                 f'href="/api/views/book?type={esc(type_key)}&start={esc(point["start"])}">'
                 f'{copy("take", start=point["start"])}</a>')
    else:
        inner = copy("slot_unavailable", start=point["start"], reason=word, why=reason(word))
    marker = ' data-earliest="1"' if earliest else ""
    return (f'<li class="list-group-item {classes}" data-start="{esc(point["start"])}" '
            f'data-reason="{esc(word or "")}"{marker}>{inner}</li>')


def type_card(type_key: str, entry: dict, grid, inventory: dict) -> str:
    row = copy("type_row", type=type_key, cycle=entry["cycle_minutes"], tokens=entry["tokens_required"],
               machines=inventory[type_key], free=entry["count"])
    offered = [point for point in grid if point["reason"] is None]
    earliest = offered[0] if offered else None
    parts = [f'<p class="fw-bold" data-type="{esc(type_key)}">{row}</p>']
    if earliest:
        # AC3: the earliest valid start is offered first, so the common case is one tap.
        parts.append(f'<p data-earliest="{esc(earliest["start"])}">{copy("earliest_first", start=earliest["start"])}</p>')
    if grid:
        parts.append(f'<ul class="list-group" data-type="{esc(type_key)}">'
                     + "".join(slot_line(point, type_key, point is earliest) for point in grid) + "</ul>")
    else:
        parts.append(f'<p>{copy("no_slot")}</p>')
    parts.append(f'<p class="small text-muted">{copy("type_note")}</p>')
    return f'<section class="card mb-3"><div class="card-body">{"".join(parts)}</div></section>'


def screen_availability(app, body, headers) -> tuple[int, str]:
    now = app.clock.now()
    hours = availability.window_hours({**body, "window_hours": body.get("window_hours")
                                      or availability.DEFAULT_WINDOW_HOURS})
    window = availability.window_view(app.repo, app.config, now, hours)
    inventory = app.repo.machine_counts()
    open_now = start_times.is_open_day(now.date(), app.config) and app.is_inside_hours(now)
    hours_note = copy("hours_note", open=app.config["opening_hours"]["open"],
                      close=app.config["opening_hours"]["close"],
                      closed_days=", ".join(app.config["closed_days"]),
                      grid=app.config["grid_minutes"],
                      state=copy("open_now") if open_now else copy("closed_now"))
    parts = [f'<p data-open="{esc(now.strftime("%H:%M"))}">{copy("availability_note")}</p>',
             f'<p>{hours_note}</p>']
    for type_key in sorted(window):
        rows = [row for row in app.repo.machines() if row["type"] == type_key]
        taken = availability.taken_turns(app.repo, rows)
        # The grid is the same predicate the seam answers on (`src/availability.py`), so the page cannot
        # offer a point the shop would refuse, and it is rendered in the order the seam answers: the
        # earliest point the type can give first, then every gap with its reason. It is rendered for every
        # type, not only for a type with a gap, because AC3 asks for the earliest start on every type.
        parts.append(type_card(type_key, window[type_key],
                               availability.slot_grid(type_key, rows, app.config, now, hours, taken),
                               inventory))
    return 200, page("availability", "".join(parts))


# --- 2. sign-in: email and the code shown in-app, never a password -----------------------------

def screen_sign_in(app, body, headers) -> tuple[int, str]:
    """AC5: the only field is the email. There is no password field, and nothing to recover."""
    form = ('<div class="mb-3"><label class="form-label" for="email">{label}</label>'
            '<input class="form-control" id="email" name="email" type="email"></div>'
            '<button class="btn btn-primary" data-action="sign-in" type="submit">{button}</button>').format(
        label=copy("email_field"), button=copy("sign_in_button"))
    content = f'<p>{copy("sign_in_note")}</p><form method="post" action="/api/session">{form}</form>'
    content += f'<p class="small text-muted">{copy("code_shown", ttl=app.config["otp_ttl_minutes"])}</p>'
    return 200, page("sign-in", content)


# --- 3. book: the four things stated before the commit -----------------------------------------

def book_facts(machine_code: str, start, end, tokens) -> str:
    lines = [copy("machine", machine=machine_code), copy("start", start=start),
             copy("expected_end", end=end), copy("tokens", tokens=tokens)]
    return '<ul class="list-group mb-3">' + "".join(
        f'<li class="list-group-item" data-fact="{esc(name)}">{line}</li>'
        for name, line in zip(("machine", "start", "end", "tokens"), lines)) + "</ul>"


def screen_book(app, body, headers) -> tuple[int, str]:
    who = app.customer(headers)
    if who is None:
        return gate("book")
    now = app.clock.now()
    type_key = body.get("type") or sorted(app.config["tariffs"])[0]
    if type_key not in app.config["tariffs"]:
        return 400, page("book", f'<p class="text-danger">{copy("unknown_type")}</p>')
    tariff = app.config["tariffs"][type_key]
    requested = app.parse_start(body.get("start"))
    if requested is None:
        # No slot named: the page shows the earliest point the type can actually give — the same one the
        # availability screen linked to (AC3) — not the moment the request arrived, which the seam refuses
        # as already begun.
        usable = [point for point in start_times.valid_start_times(now.date(), type_key, app.config) if point > now]
        requested = usable[0] if usable else now
    start = start_times.quantize(requested, app.config)
    word = "in_the_past" if start_times.in_the_past(requested, now) else start_times.refusal_reason(
        start.date(), type_key, start, app.config)
    machine = None if word else app.pick_machine(type_key, start)
    parts = [f'<p>{copy("book_note")}</p>']
    if word:
        answer = start_times.next_valid_starts(start.date(), type_key, start, app.config)
        line = copy("slot_refused", reason=word, why=reason(word), alternatives=", ".join(answer["alternatives"]))
        parts.append(f'<p class="text-danger" data-reason="{esc(word)}">{line}</p>')
    if machine is None:
        parts.append(f'<p class="text-danger">{copy("no_machine")}</p>')
        return (200 if word is None else 409), page("book", "".join(parts))
    # The four things, stated before the commit (AC6), and in the order AC6 lists them.
    parts.append(book_facts(machine["code"], start_times.slot(start),
                            start_times.slot(start + timedelta(minutes=tariff["cycle_minutes"])),
                            tariff["tokens"]))
    commit = (f'<button class="btn btn-success" data-action="commit" data-type="{esc(type_key)}" '
              f'data-start="{esc(start_times.slot(start))}">{copy("commit")}</button>')
    parts.append(f'<p>{commit}</p>')
    limit = app.daily_limit(who, daily_limit.local_day(now, app.config))
    parts.append(f'<p class="small text-muted" data-rule="R11">{copy("limit", limit=limit["max_per_day"], used=limit["used"], remaining=limit["remaining"], resets_at=limit["resets_at"])}</p>')
    return 200, page("book", "".join(parts))


# --- 4. my bookings: state, the cutoff, the limit and its reset, the block, the reassignment ----

def report_actions(app, who, machine) -> str:
    """The two report actions, on the customer's own machine only (R7, narrowed by R10).

    The page does not decide the entitlement: it renders what `src/entitlements.py` decides, and the same
    decision is what refuses the request at the seam when the control is clicked on a machine that is not
    the customer's.
    """
    held = app.repo.bookings_on_machine(machine["id"], who["email"])
    asked = (("fault", entitlements.may_report(who, held)),
             ("occupied", entitlements.may_report_still_occupied(
                 who, held, machine["state"], bool(app.repo.reports_on_machine(machine["id"], who["email"])))))
    buttons = []
    for kind, allowed in asked:
        label = copy(f"report_{kind}")
        buttons.append(
            f'<button class="btn btn-outline-danger" data-action="report" data-machine="{esc(machine["code"])}" '
            f'data-kind="{esc(kind)}">{label}</button>' if allowed
            else f'<span class="small text-muted" data-entitlement="refused">{label} - {copy("not_your_machine")}</span>')
    return '<p class="report-actions">' + " ".join(buttons) + "</p>"


def cutoff_line(app, booking, now) -> str:
    start = parse(booking["start_time"])
    allowed = cancellation.may_cancel(start, now, app.config)
    situation = copy("cancellable") if allowed else copy("past_cutoff")
    until = cancellation.cutoff_at(start, app.config).strftime("%H:%M")
    return f'<p data-rule="R4" data-cancellable="{esc("1" if allowed else "0")}">{copy("cutoff", cutoff=cancellation.cutoff_minutes(app.config), until=until, situation=situation)}</p>'


def booking_card(app, who, booking, now) -> str:
    view = app.booking_view(booking)
    machine = app.repo.machine_by_id(booking["machine_id"])
    head = copy("booking_row", machine=view["machine"], start=view["start"], end=view["end"],
                tokens=view["token_count"], state=view["state"])
    # AC7: the code lives inside the customer's own booking, and this is that booking.
    lines = [f'<p class="fw-bold" data-booking="{esc(view["id"])}" data-state="{esc(view["state"])}">{head}</p>',
             f'<p data-state="{esc(view["state"])}">{copy("state", state=view["state"])}</p>',
             f'<p class="unlock-code" data-code="{esc(view["code"])}">{copy("code", code=view["code"])}</p>',
             cutoff_line(app, booking, now)]
    if machine is not None:
        lines.append(report_actions(app, who, machine))
    return f'<article class="card mb-2"><div class="card-body">{"".join(lines)}</div></article>'


def screen_bookings(app, body, headers) -> tuple[int, str]:
    who = app.customer(headers)
    if who is None:
        return gate("bookings")
    now = app.clock.now()
    limit = app.daily_limit(who, daily_limit.local_day(now, app.config))
    block = counters.block_view(app.repo.no_shows(who["email"]), now, app.config)
    situation = copy("blocked", until=block["until"]) if block["blocked"] else copy("not_blocked")
    limit_line = copy("limit", limit=limit["max_per_day"], used=limit["used"],
                      remaining=limit["remaining"], resets_at=limit["resets_at"])
    block_line = copy("block", no_shows=block["no_shows"], window_days=block["window_days"],
                      situation=situation)
    parts = [f'<p class="daily-limit" data-rule="R11" data-reset="{esc(limit["resets_at"])}">{limit_line}</p>',
             f'<p class="no-show-block" data-rule="R9" data-until="{esc(block["until"] or "")}">{block_line}</p>']
    rows = [app.resolve_expiry(row) for row in app.repo.bookings_for(who["email"])]
    if not rows:
        parts.append(f'<p>{copy("no_booking")}</p>')
    for booking in rows:
        parts.append(booking_card(app, who, booking, now))
    # AC9 (issue #19): the reassignment is visible, with the new machine number.
    notes = [notifications.view(row, (app.repo.machine_by_id(row["machine_id"]) or {}).get("code"))
             for row in app.repo.notifications_for(who["email"])]
    if notes:
        lines = "".join('<li class="list-group-item" data-kind="{kind}" data-machine="{machine}">{line}</li>'.format(
            kind=esc(note["kind"]), machine=esc(note["machine"]),
            line=copy("reassignment", machine=note["machine"], at=note["created_at"])) for note in notes)
        parts.append('<ul class="list-group">' + lines + "</ul>")
    parts.append(f'<p class="small text-muted">{copy("report_note")}</p>')
    return 200, page("bookings", "".join(parts))


SCREEN_PAGE = {"availability": screen_availability, "sign-in": screen_sign_in,
              "book": screen_book, "bookings": screen_bookings}


def render(app, screen: str, body, headers) -> tuple[int, str | dict]:
    """The screen as the seam answers it: the page, or the gate the same decision gives."""
    build = SCREEN_PAGE.get(screen)
    if build is None:
        return 404, {"error": "unknown_screen", "screens": list(SCREENS)}
    return build(app, body or {}, headers)
