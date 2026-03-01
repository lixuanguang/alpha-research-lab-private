"""Token-bucket rate limiter for connector polling."""

from __future__ import annotations

import asyncio
import time


class TokenBucketRateLimiter:
    """Per-venue rate limiter respecting venue_config.rate_limit_rpm."""

    def __init__(self, rpm: int) -> None:
        if rpm <= 0:
            raise ValueError("`rpm` must be > 0")
        self._capacity = float(rpm)
        self._tokens = float(rpm)
        self._refill_rate_per_second = float(rpm) / 60.0
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Block until a token is available."""
        while True:
            async with self._lock:
                self._refill_locked()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return

                missing_tokens = 1.0 - self._tokens
                wait_seconds = missing_tokens / self._refill_rate_per_second

            await asyncio.sleep(wait_seconds)

    def available(self) -> bool:
        """Return whether at least one token is currently available."""
        now = time.monotonic()
        elapsed = max(0.0, now - self._last_refill)
        projected_tokens = min(
            self._capacity,
            self._tokens + elapsed * self._refill_rate_per_second,
        )
        return projected_tokens >= 1.0

    def _refill_locked(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._last_refill = now
        self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_rate_per_second)


__all__ = ["TokenBucketRateLimiter"]
