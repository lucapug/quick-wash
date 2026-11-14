"""Controllable clock.

The clock is a dependency of the application, so time control lives behind the seam: the test
hands the application the same clock it controls and then drives the HTTP boundary. Nothing
inside a unit test mocks the clock (docs/spec.md, Testing Decisions).

An instant is either a datetime or the hour the test writes as text — `clock.set("09:50")` is the
same instant as the datetime for that hour on the clock's own day, which is what lets a rule test
name a time of day without naming a date. `resolve` is the one reading of that, shared with the
booking handler's `parse_start`, so the clock and the booking cannot disagree on which day an hour
belongs to.
"""

from datetime import datetime, timedelta


class Clock:
    def __init__(self, now: datetime | None = None) -> None:
        self._now = now or datetime.now()

    def now(self) -> datetime:
        return self._now

    def resolve(self, instant) -> datetime:
        """The instant as the clock reads it: a datetime, `HH:MM` on its own day, or a full ISO string."""
        if isinstance(instant, datetime):
            return instant
        if not isinstance(instant, str):
            raise TypeError(f"the clock cannot read an instant: {instant!r}")
        try:
            if len(instant) == 5:
                return datetime.combine(self._now.date(), datetime.strptime(instant, "%H:%M").time())
            return datetime.fromisoformat(instant)
        except ValueError as bad:
            raise ValueError(f"the clock cannot read an instant: {instant}") from bad

    def set(self, instant) -> datetime:
        self._now = self.resolve(instant)
        return self._now

    def advance(self, minutes: int) -> datetime:
        self._now = self._now + timedelta(minutes=minutes)
        return self._now

    def day(self):
        return self._now.date()
