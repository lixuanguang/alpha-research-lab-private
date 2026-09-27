"""Verify independent paper diagnostic ingestion, causal recovery and exact snapshots."""

from __future__ import annotations

# standard library imports
import threading
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from applications.paper import PaperMonitoringInput, render_paper_monitoring
from applications.paper.monitoring import PaperSourceMonitoring
from financial_units import ExactRatio
from telemetry import (
    DashboardSnapshot,
    HealthRecorder,
    MonitoringEvent,
    MonitoringIdentity,
    MonitoringQuery,
    TelemetryStore,
)


class _BlockedTelemetry:
    """Hold the writer at its I/O boundary without stalling the producer."""

    def __init__(self) -> None:
        """Expose precise worker entry and release synchronization."""
        self.entered = threading.Event()
        self.release = threading.Event()

    def append(self, events: tuple[MonitoringEvent, ...]) -> int:
        """Wait for the bounded test release before returning a simulated write."""
        self.entered.set()
        if not self.release.wait(5):
            raise TimeoutError("test writer release was not signaled")
        return len(events)


class TestPaperMonitoring:
    """Qualify retained receipt and monitoring failure boundaries without account authority."""

    at = datetime(2026, 9, 27, tzinfo=UTC)

    @classmethod
    def _event(cls) -> MonitoringEvent:
        """Author a cumulative losing net result known before a retrospective import."""
        return MonitoringEvent(
            context=MonitoringIdentity(scope="account:paper", mode="paper", account="paper"),
            name="paper.net_pnl.USD",
            version="1",
            sample="report-one",
            at=cls.at,
            available_at=cls.at + timedelta(seconds=1),
            recorded_at=cls.at + timedelta(seconds=10),
            units="USD",
            value=ExactRatio.from_fraction(Fraction(-16, 5)),
            clock_quality="modeled",
        )

    @classmethod
    def _query(cls, cutoff: int) -> MonitoringQuery:
        """Select the economic event window with an independent knowledge cutoff."""
        return MonitoringQuery(
            scope="account:paper",
            mode="paper",
            start=cls.at,
            end=cls.at + timedelta(seconds=2),
            as_of=cls.at + timedelta(seconds=cutoff),
        )

    def test_storage_failure_recovers_from_retained_receipts_without_duplicate_totals(
        self, tmp_path: Path
    ) -> None:
        """A blocked telemetry path loses no retained input and recovery never sums snapshots."""
        root = tmp_path / "paper"
        root.mkdir()
        (root / "cost-report.json").write_text("committed economic report")
        first = self._event()
        second = replace(
            first,
            at=first.at + timedelta(seconds=1),
            available_at=first.available_at,
            sample="report-two",
        )
        input_path = PaperMonitoringInput.retain(root, (first, second), source_clocks=())
        blocked = tmp_path / "blocked.sqlite3"
        blocked.mkdir()
        failed = render_paper_monitoring(
            input_path, journal_path=blocked, output=tmp_path / "failed"
        )
        assert failed.errors and failed.dropped == 2 and failed.failures == 1
        assert (root / "cost-report.json").read_text() == "committed economic report"
        journal = tmp_path / "monitor.sqlite3"
        recovered = render_paper_monitoring(
            input_path, journal_path=journal, output=tmp_path / "recovered"
        )
        assert not recovered.errors and recovered.inserted == 2
        index = (tmp_path / "recovered/index.html").read_text()
        assert 'href="../paper/cost-report.json"' in index
        assert 'href="../paper/monitoring-input.json"' in index
        view = DashboardSnapshot.read(tmp_path / "recovered" / recovered.dashboards[0])
        assert view.results[0].value == first.value
        assert view.results[0].spec.aggregation == "last"
        again = render_paper_monitoring(input_path, journal_path=journal, output=tmp_path / "again")
        assert not again.errors and again.inserted == 0
        assert DashboardSnapshot.read(tmp_path / "again" / again.dashboards[0]) == view
        assert TelemetryStore(journal).query(self._query(9)) == ()
        assert TelemetryStore(journal).query(self._query(10)) == (first, second)

    def test_late_correction_cannot_change_original_dashboard_or_cutoff(
        self, tmp_path: Path
    ) -> None:
        """A received correction updates only later views while saved receipts remain immutable."""
        root = tmp_path / "paper"
        root.mkdir()
        first = self._event()
        path = PaperMonitoringInput.retain(root, (first,), source_clocks=())
        journal = tmp_path / "monitor.sqlite3"
        result = render_paper_monitoring(path, journal_path=journal, output=tmp_path / "initial")
        assert not result.errors
        before = DashboardSnapshot.read(tmp_path / "initial" / result.dashboards[0])
        correction = replace(
            first,
            value=ExactRatio.from_fraction(Fraction(-4)),
            revision=1,
            available_at=self.at + timedelta(seconds=12),
            recorded_at=self.at + timedelta(seconds=20),
        )
        assert TelemetryStore(journal).append((correction,)) == 1
        assert TelemetryStore(journal).query(self._query(19)) == (first,)
        assert TelemetryStore(journal).query(self._query(20)) == (correction,)
        reopen = render_paper_monitoring(path, journal_path=journal, output=tmp_path / "reopen")
        assert not reopen.errors and reopen.inserted == 0
        assert DashboardSnapshot.read(tmp_path / "reopen" / reopen.dashboards[0]) == before

    def test_evidence_mutation_is_visible_before_ingestion(self, tmp_path: Path) -> None:
        """Reopening refuses a changed economic source instead of relabeling old metrics."""
        (tmp_path / "cost-report.json").write_text("original")
        path = PaperMonitoringInput.retain(tmp_path, (self._event(),), source_clocks=())
        (tmp_path / "cost-report.json").write_text("changed")
        result = render_paper_monitoring(
            path, journal_path=tmp_path / "monitor.sqlite3", output=tmp_path / "view"
        )
        assert result.errors and not (tmp_path / "monitor.sqlite3").exists()

    def test_source_gaps_and_actual_callback_measurement_remain_separate(
        self, tmp_path: Path
    ) -> None:
        """Count retained gap records while refusing to manufacture absent clock evidence."""
        events, clocks = PaperSourceMonitoring.project(
            root=tmp_path,
            context=self._event().context,
            observed_at=self.at,
            summary={"gaps": ["disconnect", "invalid_book"], "synchronized": False},
            processing_ns=125_000,
            delivered_count=3,
        )
        facts = {event.name: event for event in events}
        assert not clocks
        assert facts["data.gaps"].value == ExactRatio.from_fraction(Fraction(2))
        assert facts["data.unavailable"].value == ExactRatio.from_fraction(Fraction(1))
        assert facts["runtime.processing_seconds"].value == ExactRatio.from_fraction(
            Fraction(1, 8000)
        )
        assert facts["data.source_clock_drift_seconds"].missing_reason == "not_measured"
        assert facts["data.frames"].missing_reason == "not_measured"

    def test_queue_saturation_is_visible_and_bounded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unavailable writer cannot block the producer or hide dropped observations."""
        blocked = _BlockedTelemetry()
        monkeypatch.setattr(TelemetryStore, "append", blocked.append)
        recorder = HealthRecorder(tmp_path / "monitor.sqlite3", max_batches=1)
        recorder.start()
        try:
            assert recorder.offer((self._event(),))
            assert blocked.entered.wait(1)
            assert recorder.offer((self._event(),))
            assert not recorder.offer((self._event(),))
            pending = recorder.close(wait_seconds=0)
            assert pending.dropped == 1 and pending.pending == 2 and pending.worker_alive
        finally:
            blocked.release.set()
            final = recorder.close(wait_seconds=1)
        assert final.pending == 0 and not final.worker_alive and final.inserted == 2
