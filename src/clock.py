"""Controllable clock.

The clock is a dependency of the application, so time control lives behind the seam: the test
hands the application the same clock it controls and then drives the HTTP boundary. Nothing
inside a unit test mocks the clock (docs/spec.md, Testing Decisions).
"""

from datetime import datetime, timedelta


class Clock:
    def __init__(self, now: datetime | None = None) -> None:
        self._now = now or datetime.now()

    def now(self) -> datetime:
        return self._now

    def set(self, instant) -> datetime:
        """The clock is driven from the test: an instant, or the hour as the issue bodies write it.

        `clock.set("10:45")` is the same fact as `clock.set(datetime(2026, 11, 12, 10, 45))`: a test that
        pins a window writes the minute of the day, not a date, and the hour belongs to the day the clock
        is already on. Nothing is invented for the test — an ISO instant is read as given, a bare `HH:MM` is
        combined with the current day, and both go through this one resolver.
        """
        self._now = self._resolve(instant)
        return self._now

    def _resolve(self, instant) -> datetime:
        if isinstance(instant, datetime):
            return instant
        text = str(instant)
        try:
            minute = datetime.strptime(text, "%H:%M").time()
        except ValueError:
            return datetime.fromisoformat(text)
        return datetime.combine(self._now.date(), minute)

    def advance(self, minutes: int) -> datetime:
        self._now = self._now + timedelta(minutes=minutes)
        return self._now

    def day(self):
        return self._now.date()
