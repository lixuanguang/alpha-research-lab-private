"""Exponential backoff reconnection policy for streaming connectors."""

from __future__ import annotations

import math
import random


class ReconnectionPolicy:
    """Exponential backoff with jitter for stream reconnection.

    Delay formula:  min(base * 2^attempt, max_delay) * uniform(1 - jitter, 1 + jitter)

    Args:
        base:      Base delay in seconds for the first attempt.
        max_delay: Hard upper cap on delay before jitter is applied.
        jitter:    Relative jitter fraction in [0, 1). 0.5 → ±50 % of the capped delay.
    """

    def __init__(
        self,
        base: float = 1.0,
        max_delay: float = 60.0,
        jitter: float = 0.5,
    ) -> None:
        if base <= 0:
            raise ValueError("`base` must be > 0")
        if max_delay < base:
            raise ValueError("`max_delay` must be >= `base`")
        if not (0.0 <= jitter < 1.0):
            raise ValueError("`jitter` must be in [0, 1)")

        self.base = base
        self.max_delay = max_delay
        self.jitter = jitter

    def next_delay(self, attempt: int) -> float:
        """Return delay (seconds) for *attempt* (0-indexed).

        The delay is capped at ``max_delay`` then jittered so consecutive
        reconnections spread out their retry times.
        """
        if attempt < 0:
            raise ValueError("`attempt` must be >= 0")
        capped = min(self.base * math.pow(2.0, attempt), self.max_delay)
        if self.jitter == 0.0:
            return capped
        lo = capped * (1.0 - self.jitter)
        hi = capped * (1.0 + self.jitter)
        return random.uniform(lo, hi)  # nosec B311 – jitter for backoff, not cryptography

    def reset(self) -> None:
        """No-op; policy is stateless — reset is a hook for subclasses."""


__all__ = ["ReconnectionPolicy"]
