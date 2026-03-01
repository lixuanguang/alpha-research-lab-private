"""Shared connector domain types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import alpha_core.events.models as event_models


@dataclass(slots=True)
class PollingBatch:
    """One polling result: canonical events plus bronze-ready raw payloads."""

    events: list[event_models.CanonicalMarketEvent]
    raw_payloads: dict[str, list[dict[str, object]]]


def normalize_outcome_ids(outcome_ids: list[str]) -> list[str]:
    """Normalize and deduplicate outcome ids while preserving order."""
    normalized: list[str] = []
    seen: set[str] = set()
    for outcome_id in outcome_ids:
        cleaned = outcome_id.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


class ConnectorState(StrEnum):
    """Runtime state of a connector lifecycle."""

    IDLE = "idle"
    RUNNING = "running"
    RECONNECTING = "reconnecting"
    STOPPED = "stopped"
    ERROR = "error"


class FatalConnectorError(RuntimeError):
    """Non-recoverable connector error that should not trigger reconnect loops."""


__all__ = [
    "ConnectorState",
    "FatalConnectorError",
    "PollingBatch",
    "normalize_outcome_ids",
]
