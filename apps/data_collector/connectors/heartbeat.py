"""Heartbeat monitoring for streaming connectors."""

from __future__ import annotations

import time
from collections.abc import Callable


class HeartbeatMonitor:
    """Detects stale streams that have not received data within a timeout.

    Args:
        timeout_seconds: Maximum seconds of silence before a connector is
                         considered stale. Must be > 0.
        time_func:       Callable returning current monotonic time (injectable
                         for deterministic testing).
    """

    def __init__(
        self,
        timeout_seconds: float = 120.0,
        *,
        time_func: Callable[[], float] = time.monotonic,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("`timeout_seconds` must be > 0")
        self._timeout = timeout_seconds
        self._now = time_func
        self._last_beat: dict[str, float] = {}

    def record_heartbeat(self, connector_id: str) -> None:
        """Record that *connector_id* is still alive."""
        self._last_beat[connector_id] = self._now()

    def check_stale(self) -> list[str]:
        """Return IDs of connectors that have not beaten within the timeout."""
        now = self._now()
        return [
            cid
            for cid, last in self._last_beat.items()
            if (now - last) > self._timeout
        ]

    def remove(self, connector_id: str) -> None:
        """Remove tracking for *connector_id* (e.g. on clean shutdown)."""
        self._last_beat.pop(connector_id, None)

    def tracked(self) -> list[str]:
        """Return all currently tracked connector IDs."""
        return list(self._last_beat)


__all__ = ["HeartbeatMonitor"]
