"""Open a paper run's shared monitoring store at its declared capacity."""

from __future__ import annotations

# standard library imports
from pathlib import Path

# third party library imports
import msgspec

# project library imports
from configuration import PaperServiceConfiguration, PaperTelemetryRetention
from telemetry import TelemetryStore


class MonitoringStore:
    """Every writer of one run's store uses the same capacity, so none refuses another."""

    @staticmethod
    def retention(configuration: PaperServiceConfiguration) -> PaperTelemetryRetention | None:
        """Return the run's declared retention, or None for the store's defaults."""
        return None if configuration.telemetry is msgspec.UNSET else configuration.telemetry

    @staticmethod
    def open(root: Path, retention: PaperTelemetryRetention | None) -> TelemetryStore:
        """Open ``root``'s monitoring store at the declared capacity, or the default."""
        if retention is None:
            return TelemetryStore(root / "telemetry.sqlite3")
        return TelemetryStore(root / "telemetry.sqlite3", max_events=retention.max_events)
