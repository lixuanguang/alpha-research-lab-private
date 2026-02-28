"""Connector metrics models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class ConnectorMetrics:
    """Lightweight runtime counters for connector health and throughput."""

    events_received: int = 0
    events_normalised: int = 0
    events_rejected: int = 0
    last_event_ts: datetime | None = None
    uptime_seconds: float = 0.0
    reconnect_count: int = 0
    errors: list[str] = field(default_factory=list)
