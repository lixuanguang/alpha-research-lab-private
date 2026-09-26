"""Bound private REST requests without implicit retries."""

from __future__ import annotations

# standard library imports
from collections import deque
from time import monotonic, sleep


class VenueRateLimiter:
    """Enforce a conservative per-adapter rolling request budget."""

    def __init__(self, *, requests: int, seconds: float) -> None:
        """Initialize a positive bounded request window."""
        if requests <= 0 or seconds <= 0:
            raise ValueError("invalid venue request budget")
        self.requests = requests
        self.seconds = seconds
        self.timestamps: deque[float] = deque()

    def acquire(self) -> None:
        """Wait only until a local budget slot is available."""
        now = monotonic()
        while self.timestamps and now - self.timestamps[0] >= self.seconds:
            self.timestamps.popleft()
        if len(self.timestamps) >= self.requests:
            sleep(self.seconds - (now - self.timestamps[0]))
            now = monotonic()
            while self.timestamps and now - self.timestamps[0] >= self.seconds:
                self.timestamps.popleft()
        self.timestamps.append(now)
