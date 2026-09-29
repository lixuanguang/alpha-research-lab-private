"""Bound private REST requests without implicit retries."""

from __future__ import annotations

# standard library imports
from collections import deque
from collections.abc import Callable
from time import monotonic, sleep


class VenueRateLimiter:
    """Enforce a conservative per-adapter rolling request budget."""

    def __init__(
        self,
        *,
        requests: int,
        seconds: float,
        clock: Callable[[], float] = monotonic,
        pause: Callable[[float], None] = sleep,
    ) -> None:
        """Initialize a positive bounded request window on a monotonic clock in seconds."""
        if requests <= 0 or seconds <= 0:
            raise ValueError("invalid venue request budget")
        self.requests = requests
        self.seconds = seconds
        self.timestamps: deque[float] = deque()
        self._clock, self._pause = clock, pause

    def wait(self) -> None:
        """Wait until a slot is free without taking it, so the next acquire cannot sleep.

        Callers wait here before entering a lock that must not be held while
        sleeping. Only this adapter's own requests consume slots, and its owner
        makes them one at a time.
        """
        now = self._clock()
        self._expire(now)
        if len(self.timestamps) >= self.requests:
            self._pause(self.seconds - (now - self.timestamps[0]))
            self._expire(self._clock())

    def acquire(self) -> None:
        """Wait only until a local budget slot is available."""
        now = self._clock()
        self._expire(now)
        if len(self.timestamps) >= self.requests:
            self._pause(self.seconds - (now - self.timestamps[0]))
            now = self._clock()
            self._expire(now)
        self.timestamps.append(now)

    def _expire(self, now: float) -> None:
        """Forget requests that have left the rolling window."""
        while self.timestamps and now - self.timestamps[0] >= self.seconds:
            self.timestamps.popleft()
