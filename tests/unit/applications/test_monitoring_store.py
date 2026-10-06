"""Bound a paper run's monitoring store and age out its oldest samples."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path

# third party library imports
import pytest

# project library imports
from applications.execute.monitoring_store import MonitoringStore
from applications.execute.service_monitor import PaperServiceMonitor
from configuration import PaperTelemetryRetention
from financial_units import ExactRatio
from telemetry import MonitoringEvent, MonitoringIdentity, MonitoringQuery

_AT = datetime(2026, 10, 7, tzinfo=UTC)


class TestMonitoringStore:
    """The declared capacity applies to every writer; the monitor alone prunes by age."""

    @staticmethod
    def event(sample: str, at: datetime) -> MonitoringEvent:
        """Author one exact diagnostic sample at its own clock."""
        return MonitoringEvent(
            context=MonitoringIdentity(scope="account:one", mode="paper", model="none"),
            name="cash",
            version="v1",
            sample=sample,
            at=at,
            available_at=at,
            recorded_at=at,
            units="USDT",
            value=ExactRatio.from_fraction(Fraction(1)),
            missing_reason=None,
            revision=0,
        )

    def test_declared_capacity_applies_to_every_writer(self, tmp_path: Path) -> None:
        """A writer opened with the declared capacity refuses only past it."""
        retention = PaperTelemetryRetention(max_events=2, retention_days=7)
        store = MonitoringStore.open(tmp_path, retention)
        store.append((self.event("a", _AT), self.event("b", _AT)))
        with pytest.raises(ValueError, match="capacity exhausted"):
            MonitoringStore.open(tmp_path, retention).append((self.event("c", _AT),))

    def test_monitor_prunes_samples_older_than_the_declared_days(self, tmp_path: Path) -> None:
        """Samples past the age bound go before the next append; newer ones stay."""
        retention = PaperTelemetryRetention(max_events=10, retention_days=7)
        MonitoringStore.open(tmp_path, retention).append(
            (
                self.event("old", _AT - timedelta(days=8)),
                self.event("kept", _AT - timedelta(days=6)),
            )
        )
        monitor = PaperServiceMonitor(tmp_path, retention)
        store = monitor._store(_AT)
        selection = store.select(
            MonitoringQuery(
                scope="account:one",
                mode="paper",
                start=_AT - timedelta(days=7),
                end=_AT,
                as_of=_AT,
                limit=10,
            )
        )
        assert tuple(row.sample for row in selection.rows) == ("kept",)
        # Pruning runs at most hourly, so a second open inside the hour leaves the floor.
        assert monitor._store(_AT + timedelta(minutes=30)) is not None
