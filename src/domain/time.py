"""Valid start times for a type (R1, R2): the pure time helper a unit test covers.

Three conditions decide whether the shop can honour a start, and they are reported in this order:

1. the day is open — a closed day answers `closed_day` (R2);
2. the start is inside opening hours — otherwise `outside_opening_hours` (R2);
3. `start + cycle_minutes` does not overrun closing — otherwise `would_overrun_closing` (R1).

Those three values are the fixed vocabulary of issue AC4: they are the only reasons a start is
refused, and `REFUSAL_REASONS` is exactly that set.

The 15-minute grid is not a refusal cause, it is the shape of the set. It is anchored at opening
time, not at the top of the hour, because "quantised on a 15-minute grid" needs a fixed origin to
be testable: with origin 07:00 the first slot of the day is 07:00 and no slot starts at 07:07. A
request that lands between two grid points is quantised up to the next grid point, and that is the
first alternative the answer names — the code is `off_grid`, deliberately outside the fixed
vocabulary, because such a request is adjusted rather than refused for one of the three causes.

Pure: inputs and outputs are data. No repository, no clock object, no mock
(tests/unit/test_start_times.py, docs/spec.md Testing Decisions).
"""

from datetime import date, datetime, timedelta

from src.config import SEED

# AC4: the fixed vocabulary of refusal reasons. Exactly these three.
REFUSAL_REASONS = ("outside_opening_hours", "closed_day", "would_overrun_closing")

# The grid case is a quantisation, not one of the three causes (see the module docstring).
GRID_REASON = "off_grid"

# How far the answer looks for alternatives: enough to cross a closed day, not a calendar.
LOOKAHEAD_DAYS = 14
DEFAULT_ALTERNATIVES = 8


def hhmm(moment: datetime) -> str:
    return moment.strftime("%H:%M")


def slot(moment: datetime, origin: date | None = None) -> str:
    """A slot on the day being asked about reads as an hour; a slot on another day reads as a date.

    That is what makes an alternative on the next open day unambiguous: `07:15` is still today,
    `2026-11-10T07:00` is a different day.
    """
    if origin is None or moment.date() == origin:
        return hhmm(moment)
    return moment.strftime("%Y-%m-%dT%H:%M")


def open_at(day: date, config: dict = SEED) -> datetime:
    return datetime.combine(day, datetime.strptime(config["opening_hours"]["open"], "%H:%M").time())


def close_at(day: date, config: dict = SEED) -> datetime:
    close = datetime.strptime(config["opening_hours"]["close"], "%H:%M").time()
    return datetime.combine(day, close)


def is_open_day(day: date, config: dict = SEED) -> bool:
    return day.strftime("%A") not in config["closed_days"]


def cycle_minutes(type_key: str, config: dict = SEED) -> int:
    tariff = config["tariffs"].get(type_key)
    if tariff is None:
        raise KeyError(f"unknown machine type: {type_key}")
    return tariff["cycle_minutes"]


def parse_requested(value, day: date, config: dict = SEED) -> datetime:
    """The requested start as data: `HH:MM` on `day`, or a full ISO datetime."""
    if isinstance(value, datetime):
        return value
    if not value:
        raise ValueError("a requested start time is needed")
    try:
        if len(value) == 5:
            return datetime.combine(day, datetime.strptime(value, "%H:%M").time())
        return datetime.fromisoformat(value)
    except ValueError as bad:
        raise ValueError(f"requested start is not a time: {value}") from bad


def on_grid(moment: datetime, config: dict = SEED) -> bool:
    """True when `moment` is a grid point, measured from opening time of its own day."""
    grid = timedelta(minutes=config["grid_minutes"])
    return (moment - open_at(moment.date(), config)) % grid == timedelta(0)


def valid_start_times(day: date, type_key: str, config: dict = SEED) -> list[datetime]:
    """Every start on `day` a cycle of `type_key` can actually honour (R1, R2), ascending.

    Open day, inside opening hours, on the grid anchored at opening time, and with the cycle
    finishing before closing time. A closed day has no start at all.
    """
    if not is_open_day(day, config):
        return []
    grid = timedelta(minutes=config["grid_minutes"])
    cycle = timedelta(minutes=cycle_minutes(type_key, config))
    close = close_at(day, config)

    starts = []
    moment = open_at(day, config)  # the grid origin: the first slot of the day is opening time
    while moment + cycle <= close:
        starts.append(moment)
        moment += grid
    return starts


def last_start(day: date, type_key: str, config: dict = SEED) -> str | None:
    """The last start the shop can honour for `type_key` on `day` (R1): 21:30 / 21:00 / 20:45."""
    starts = valid_start_times(day, type_key, config)
    return hhmm(starts[-1]) if starts else None


def refusal_reason(day: date, type_key: str, requested: datetime, config: dict = SEED) -> str | None:
    """Why `requested` cannot be honoured, named from the fixed vocabulary. None when it can.

    The three AC4 causes come first; a request that is otherwise admissible but lands between two
    grid points is named `GRID_REASON`, outside the fixed vocabulary, because it is quantised.
    """
    if not is_open_day(day, config):
        return "closed_day"
    if not open_at(day, config) <= requested <= close_at(day, config):
        return "outside_opening_hours"
    if requested + timedelta(minutes=cycle_minutes(type_key, config)) > close_at(day, config):
        return "would_overrun_closing"
    if not on_grid(requested, config):
        return GRID_REASON
    return None


def next_valid_starts(day: date, type_key: str, requested, config: dict = SEED,
                      limit: int = DEFAULT_ALTERNATIVES) -> dict:
    """The refusal answer: the reason, and the next valid alternatives, earliest first (AC5, AC6).

    Alternatives are strictly later than the request, ascending, and cross to the next open day when
    the day is exhausted. The same-day alternatives read as hours, the ones on another day as a
    date, so the day change is visible in the string.
    """
    moment = parse_requested(requested, day, config)
    reason = refusal_reason(day, type_key, moment, config)

    alternatives: list[str] = []
    cursor = day
    for _ in range(LOOKAHEAD_DAYS):
        for start in valid_start_times(cursor, type_key, config):
            if start > moment:
                alternatives.append(slot(start, day))
                if len(alternatives) >= limit:
                    break
        if len(alternatives) >= limit:
            break
        cursor += timedelta(days=1)

    return {
        "type": type_key,
        "day": day.isoformat(),
        "cycle_minutes": cycle_minutes(type_key, config),
        "grid_minutes": config["grid_minutes"],
        "requested": slot(moment, day),
        "on_grid": on_grid(moment, config),
        "refused": reason is not None,
        "reason": reason,
        "alternatives": alternatives,
    }
