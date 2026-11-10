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

    def set(self, instant: datetime) -> datetime:
        self._now = instant
        return self._now

    def advance(self, minutes: int) -> datetime:
        self._now = self._now + timedelta(minutes=minutes)
        return self._now

    def day(self):
        return self._now.date()
