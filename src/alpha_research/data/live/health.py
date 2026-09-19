"""Bound process health observation and local syslog delivery for one collector."""

from __future__ import annotations

# standard library imports
import ctypes
import logging
import multiprocessing
import socket
import time
from enum import IntEnum
from logging.handlers import SysLogHandler

# third party library imports
import msgspec


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


class HealthPolicy(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Select finite watchdog budgets and the sole supported protective response."""

    heartbeat_seconds: int
    progress_seconds: int
    freshness_seconds: int
    max_queue: int
    max_reconnects: int
    max_invalid: int
    alert_socket: str
    startup_seconds: int = 10
    response: str = "stop"

    def __post_init__(self) -> None:
        """Reject unsupported responses and malformed or unbounded thresholds."""
        for value, minimum, maximum in (
            (self.startup_seconds, 1, 120),
            (self.heartbeat_seconds, 1, 120),
            (self.progress_seconds, 1, 3600),
            (self.freshness_seconds, 1, 3600),
            (self.max_queue, 1, 4096),
            (self.max_reconnects, 0, 5),
            (self.max_invalid, 0, 1_000_000),
        ):
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError("invalid health threshold")
        if (
            self.response != "stop"
            or not isinstance(self.alert_socket, str)
            or not self.alert_socket.startswith("/")
            or len(self.alert_socket.encode()) > 100
            or "\0" in self.alert_socket
        ):
            raise ValueError("health requires stop response and a bounded local syslog socket")

    def reason(self, values: tuple[int, ...], *, now_ns: int) -> str:
        """Select the first exceeded threshold from trusted shared observations.

        Args:
            values: Complete fixed-slot observation from HealthMetrics.
            now_ns: Parent monotonic observation instant in nanoseconds.

        Returns:
            Empty text when within policy, otherwise a fixed safe failure reason.
        """
        if values[HealthMetric.PERSISTENCE_FAILED]:
            return "persistence_failed"
        if values[HealthMetric.HEARTBEAT] == 0:
            return (
                "startup_stalled"
                if now_ns - values[HealthMetric.INGESTION] > self.startup_seconds * 1_000_000_000
                else ""
            )
        for metric, seconds in (
            (HealthMetric.HEARTBEAT, self.heartbeat_seconds),
            (HealthMetric.PERSISTENCE, self.progress_seconds),
            (HealthMetric.INGESTION, self.progress_seconds),
            (HealthMetric.MARKET, self.freshness_seconds),
        ):
            if values[HealthMetric.FINALIZING] and metric != HealthMetric.HEARTBEAT:
                continue
            if now_ns - values[metric] > seconds * 1_000_000_000:
                return f"{metric.name.lower()}_stalled"
        for metric, maximum in (
            (HealthMetric.QUEUE, self.max_queue),
            (HealthMetric.RECONNECTS, self.max_reconnects),
            (HealthMetric.INVALID, self.max_invalid),
        ):
            if values[metric] > maximum:
                return f"{metric.name.lower()}_limit"
        return ""


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


class HealthAlert(SysLogHandler):
    """Deliver one bounded local syslog alert and expose handler delivery failure."""

    def _connect_unixsocket(self, address: str) -> None:
        """Keep initial connection and the stdlib handler's reconnect nonblocking."""
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.socket.setblocking(False)
        self.socket.connect(address)

    def handleError(self, record: logging.LogRecord) -> None:
        """Propagate handler failure without printing untrusted exception context.

        Args:
            record: Fixed non-secret health alert selected by the supervisor.

        Raises:
            OSError: Local syslog delivery failed; protective behavior already ran.
        """
        raise OSError("health alert delivery failed")

    @classmethod
    def deliver(cls, address: str, reason: str) -> bool:
        """Attempt one local datagram alert, never retrying beyond the handler budget.

        Args:
            address: Validated absolute local syslog socket path.
            reason: Fixed bounded supervisor failure reason.

        Returns:
            Whether the local socket accepted the alert; not remote acknowledgement.
        """
        handler: HealthAlert | None = None
        try:
            handler = cls(address=address, timeout=0.2)
            handler.emit(logging.LogRecord("alpha.collect", logging.ERROR, "", 0, reason, (), None))
            return True
        except OSError:
            return False
        finally:
            if handler is not None:
                handler.close()
