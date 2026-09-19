"""Expose bounded process-shared progress for one native collector."""

from __future__ import annotations

# standard library imports
import ctypes
import multiprocessing
import time
from enum import IntEnum


class HealthMetric(IntEnum):
    """Name fixed shared slots; elapsed clocks are monotonic nanoseconds."""

    HEARTBEAT = 0
    INGESTION = 1
    PERSISTENCE = 2
    MARKET = 3
    QUEUE = 4
    RECONNECTS = 5
    INVALID = 6
    FINALIZING = 7
    PERSISTENCE_FAILED = 8


class HealthMetrics:
    """Share nine integers with a separate watchdog, without files or unbounded queues."""

    def __init__(self) -> None:
        """Start elapsed budgets before child startup, using the spawn process context."""
        self._values = multiprocessing.get_context("spawn").Array(
            ctypes.c_longlong, [0] + [time.monotonic_ns()] * 3 + [0] * 5
        )

    def set(self, metric: HealthMetric, value: int) -> None:
        """Update one collector-owned metric with bounded lock acquisition.

        Args:
            metric: Fixed slot owned by the collector.
            value: Trusted integer clock, count or phase flag.

        Raises:
            TimeoutError: A dead or blocked writer prevents safe observation.
        """
        if not self._values.acquire(True, 0.05):
            raise TimeoutError("health observation lock stalled")
        try:
            self._values[metric] = value
        finally:
            self._values.release()

    def snapshot(self) -> tuple[int, ...]:
        """Read a coherent bounded observation without waiting on a lost collector.

        Returns:
            Nine integer clocks, counts and phase flags.

        Raises:
            TimeoutError: The collector died or stalled while holding its observation lock.
        """
        if not self._values.acquire(True, 0.05):
            raise TimeoutError("health observation lock stalled")
        try:
            return tuple(self._values[:])
        finally:
            self._values.release()
