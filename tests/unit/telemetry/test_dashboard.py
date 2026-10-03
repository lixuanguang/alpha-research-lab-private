"""Protect exact dashboard rendering, retention and local alert outcomes."""

from __future__ import annotations

# standard library imports
import hashlib
import os
import socket
import stat
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol

# third party library imports
import pytest
from msgspec.structs import force_setattr, replace

# project library imports
from financial_units import ExactRatio
from telemetry.dashboard import (
    AlertRule,
    DashboardBuilder,
    DashboardConfig,
    DashboardPanel,
    DashboardRenderer,
    DashboardSnapshot,
    UnavailablePolicy,
)
from telemetry.events import MonitoringEvent, MonitoringIdentity, MonitoringQuery
from telemetry.metrics import MetricInput, MetricRegistry, MetricResult, MetricSpec, SeriesMetric
from telemetry.operations import OperationalAlerts

# A short existing root keeps AF_UNIX paths in limits on macOS and Linux.
_SOCKET_ROOT = "/private/tmp" if os.path.isdir("/private/tmp") else "/tmp"


class _RecordedWriter:
    """Run another writer and record its failure instead of losing it in the thread."""

    def __init__(self, target: Callable[[], object]) -> None:
        """Bind the write with no failure yet."""
        self._target = target
        self.errors: list[BaseException] = []

    def __call__(self) -> None:
        """Run the write and keep any failure."""
        try:
            self._target()
        except BaseException as error:
            self.errors.append(error)


class _PathCheck(Protocol):
    """The ``Path.exists`` call shape, called with the path explicitly."""

    def __call__(self, path: Path, /, *, follow_symlinks: bool = ...) -> bool:
        """Report whether the path exists."""
        ...


class _RaceAfterManifestCheck:
    """Let another writer run between the manifest check and the listing, once.

    Installed as ``Path.exists`` it binds the path like a method.
    """

    def __init__(self, exists: _PathCheck, manifest: Path, write: Callable[[], object]) -> None:
        """Bind the original check, the manifest path and the racing write."""
        self._exists = exists
        self._manifest = manifest
        self._write = write
        self._started = threading.Event()
        self.raced: list[tuple[threading.Thread, list[BaseException]]] = []

    def __get__(self, instance: Path, owner: type[Path]) -> partial[bool]:
        """Bind the check to the path it is called on."""
        return partial(self, instance)

    def __call__(self, path: Path, *, follow_symlinks: bool = True) -> bool:
        """Check the path as before, starting the other writer after the manifest check."""
        seen = self._exists(path, follow_symlinks=follow_symlinks)
        if path == self._manifest and not self._started.is_set():
            self._started.set()
            self.raced.append(TestDashboard._race(self._write))
        return seen


class _RaceBeforeRename:
    """Let another writer publish just before this one moves a directory aside, once."""

    def __init__(self, rename: Callable[[Path, Path], None], write: Callable[[], object]) -> None:
        """Bind the original rename and the racing write."""
        self._rename = rename
        self._write = write
        self._started = threading.Event()
        self.raced: list[tuple[threading.Thread, list[BaseException]]] = []

    def __call__(self, source: Path, target: Path) -> None:
        """Start the other writer once, then rename as before."""
        if not self._started.is_set():
            self._started.set()
            self.raced.append(TestDashboard._race(self._write))
        self._rename(source, target)


class _RetainedResultMetric:
    """Retain an injected metric result so a later buggy definition can corrupt it."""

    def __init__(self, metric: SeriesMetric) -> None:
        """Wrap a normal exact definition and keep its most recent result."""
        self.metric = metric
        self.result: MetricResult | None = None

    @property
    def spec(self) -> MetricSpec:
        """Expose the unchanged configured metric definition."""
        return self.metric.spec

    def evaluate(self, query: MonitoringQuery, events: tuple[MonitoringEvent, ...]) -> MetricResult:
        """Return the normal result while retaining its reference for fault injection."""
        self.result = self.metric.evaluate(query, events)
        return self.result


class _MutatingCallbackMetric:
    """Corrupt an admitted input or earlier result inside the injected code boundary."""

    def __init__(self, spec: MetricSpec, prior: _RetainedResultMetric | None = None) -> None:
        """Select which prior admitted exact value the buggy callback will mutate."""
        self.spec, self.prior = spec, prior

    def evaluate(self, query: MonitoringQuery, events: tuple[MonitoringEvent, ...]) -> MetricResult:
        """Return matching input identities after forcing a nested exact value invalid."""
        if self.prior is None:
            value = events[0].value
        else:
            assert self.prior.result is not None
            value = self.prior.result.value
        assert value is not None
        force_setattr(value, "numerator", True)
        return MetricResult(
            spec=self.spec,
            query=query,
            value=ExactRatio(numerator="1", denominator="1"),
            status="ok",
            reason=None,
            input_ids=tuple(event.identity for event in events),
        )


class _FailingRename:
    """Fail every publication rename, as a crash before the commit point would."""

    def __call__(self, source: str | Path, destination: str | Path) -> None:
        """Refuse the rename without touching either path."""
        raise OSError("synthetic rename failure")


class TestDashboard:
    """Use a selected causal series and an isolated Unix socket for delivery proof."""

    start = datetime(2025, 1, 1, tzinfo=UTC)

    @staticmethod
    def _ratio(numerator: int, denominator: int = 1) -> ExactRatio:
        """Keep every configured and observed number exact."""
        return ExactRatio.from_fraction(Fraction(numerator, denominator))

    @classmethod
    def _query(cls, *, as_of_hours: int = 4) -> MonitoringQuery:
        """Select one paper account's bounded UTC observation window."""
        return MonitoringQuery(
            scope="account-a",
            mode="paper",
            start=cls.start,
            end=cls.start + timedelta(hours=4),
            as_of=cls.start + timedelta(hours=as_of_hours),
            limit=20,
        )

    @classmethod
    def _metric(cls, *, stale_after_seconds: int = 7200) -> SeriesMetric:
        """Provide a registered last-value series with exact count units."""
        return SeriesMetric(
            MetricSpec(
                name="queue-depth",
                version="v1",
                implementation_sha256="a" * 64,
                inputs=(MetricInput(name="queue", version="v1", units="count"),),
                units="count",
                modes=("paper",),
                aggregation="last",
                missingness="propagate",
                stale_after_seconds=stale_after_seconds,
            )
        )

    @classmethod
    def _event(
        cls, sample: str, hours: int, value: ExactRatio | None, *, reason: str | None = None
    ) -> MonitoringEvent:
        """Retain one versioned observation and its source clocks."""
        at = cls.start + timedelta(hours=hours)
        return MonitoringEvent(
            context=MonitoringIdentity(scope="account-a", mode="paper", account="a"),
            name="queue",
            version="v1",
            sample=sample,
            at=at,
            available_at=at,
            recorded_at=at,
            units="count",
            value=value,
            missing_reason=reason,
        )

    @classmethod
    def _rule(
        cls,
        metric: SeriesMetric,
        address: Path,
        *,
        on_missing: UnavailablePolicy = "unavailable",
        on_stale: UnavailablePolicy = "unavailable",
        units: str = "count",
    ) -> AlertRule:
        """Select a local route and threshold without trading authority."""
        return AlertRule(
            identity="queue-above-limit",
            metric_identity=metric.spec.identity,
            operator=">=",
            threshold=cls._ratio(3, 2),
            units=units,
            address=str(address),
            on_missing=on_missing,
            on_stale=on_stale,
        )

    @classmethod
    def _config(
        cls, metric: SeriesMetric, *, address: Path | None = None, title: str = "Queue <script>"
    ) -> DashboardConfig:
        """Exercise both real chart kinds and a provenance table."""
        panels = (
            DashboardPanel(title=title, metric_identity=metric.spec.identity, kind="line"),
            DashboardPanel(title="Queue bars", metric_identity=metric.spec.identity, kind="bar"),
            DashboardPanel(title="Queue table", metric_identity=metric.spec.identity, kind="table"),
        )
        alerts = () if address is None else (cls._rule(metric, address),)
        return DashboardConfig(title="Account <health>", panels=panels, alerts=alerts)

    def test_exact_chart_gaps_and_verified_retention(self, tmp_path: Path) -> None:
        """Preserve gaps and exact rows, then refuse tampering or changed snapshots."""
        metric = self._metric()
        events = (
            self._event("first", 1, self._ratio(1, 3)),
            self._event("gap", 2, None, reason="source <late>"),
            self._event("last", 3, self._ratio(2)),
        )
        snapshot = DashboardBuilder.build(
            self._config(metric), self._query(), events, MetricRegistry((metric,))
        )
        assert snapshot.results[0].value == self._ratio(2)
        assert snapshot.results[0].input_count == 3
        assert snapshot.results[0].inputs_sha256 == self._digest(events)
        assert (snapshot.event_count, snapshot.events_sha256) == (3, self._digest(events))
        rendered = snapshot.render_html().decode()
        assert rendered.count('<svg class="chart"') == 2
        assert '<line class="gap"' in rendered
        assert '<path class="series"' not in rendered
        assert "1/3" in rendered and "2/1" in rendered
        assert "source &lt;late&gt;" in rendered
        assert "<script>" not in rendered
        assert "Knowledge cutoff" in rendered
        assert metric.spec.identity in rendered

        directory = tmp_path / "retained"
        with pytest.raises(ValueError, match="provenance differs"):
            snapshot.write(directory, (events[1], events[2]))
        html_path = snapshot.write(directory, events)
        before = html_path.stat().st_mtime_ns
        assert DashboardSnapshot.read(directory) == snapshot
        assert snapshot.write(directory, events) == html_path
        assert html_path.stat().st_mtime_ns == before
        other = DashboardBuilder.build(
            self._config(metric, title="Different"),
            self._query(),
            events,
            MetricRegistry((metric,)),
        )
        with pytest.raises(ValueError, match="different content"):
            other.write(directory, events)
        html_path.write_bytes(b"changed")
        with pytest.raises(ValueError, match="digest"):
            DashboardSnapshot.read(directory)

    def test_interrupted_or_failed_writes_leave_a_retryable_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A view appears whole or not at all, and a retry completes an interrupted write."""
        metric = self._metric()
        events = (self._event("last", 3, self._ratio(2)),)
        snapshot = DashboardBuilder.build(
            self._config(metric), self._query(), events, MetricRegistry((metric,))
        )
        # A writer that died after its first file left an uncommitted directory.
        interrupted = tmp_path / "interrupted"
        interrupted.mkdir()
        (interrupted / "snapshot.json").write_bytes(b'{"partial"')
        assert snapshot.write(interrupted, events) == interrupted / "dashboard.html"
        assert DashboardSnapshot.read(interrupted) == snapshot
        (quarantined,) = tuple(tmp_path.glob(".interrupted.interrupted-*"))
        assert (quarantined / "snapshot.json").read_bytes() == b'{"partial"'
        # A failed publish leaves no partial view behind, and the retry succeeds.
        failed = tmp_path / "failed"
        with monkeypatch.context() as patched:
            patched.setattr("telemetry.dashboard.os.rename", _FailingRename())
            with pytest.raises(OSError, match="synthetic"):
                snapshot.write(failed, events)
        assert not failed.exists()
        assert not tuple(tmp_path.glob(".failed.staging-*"))
        snapshot.write(failed, events)
        assert DashboardSnapshot.read(failed) == snapshot
        empty = tmp_path / "empty"
        empty.mkdir()
        snapshot.write(empty, events)
        assert DashboardSnapshot.read(empty) == snapshot
        shared = tmp_path / "shared"
        shared.mkdir()
        (shared / "notes.txt").write_bytes(b"unrelated")
        with pytest.raises(ValueError, match="unrelated"):
            snapshot.write(shared, events)
        assert sorted(path.name for path in shared.iterdir()) == ["notes.txt"]

    def _view(self, title: str = "Dashboard") -> DashboardSnapshot:
        """Build one small view; a different title makes different content."""
        metric = self._metric()
        return DashboardBuilder.build(
            self._config(metric, title=title),
            self._query(),
            self._view_events(),
            MetricRegistry((metric,)),
        )

    @classmethod
    def _view_events(cls) -> tuple[MonitoringEvent, ...]:
        """Select the single input of every small view."""
        return (cls._event("last", 3, cls._ratio(2)),)

    @staticmethod
    def _digest(events: tuple[MonitoringEvent, ...]) -> str:
        """Hash event identities in order, as a view digests its selection."""
        return hashlib.sha256(
            b"".join(bytes.fromhex(event.identity) for event in events)
        ).hexdigest()

    @staticmethod
    def _race(target: Callable[[], object]) -> tuple[threading.Thread, list[BaseException]]:
        """Start another writer and give it time to finish unless a lock holds it."""
        writer = _RecordedWriter(target)
        thread = threading.Thread(target=writer)
        thread.start()
        thread.join(0.5)
        return thread, writer.errors

    def test_concurrent_writers_of_one_view_both_succeed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A writer that checked for a manifest before another published still verifies."""
        snapshot = self._view()
        directory = tmp_path / "view"
        manifest = directory / "manifest.json"
        exists_then_race = _RaceAfterManifestCheck(
            Path.exists, manifest, partial(snapshot.write, directory, self._view_events())
        )
        raced = exists_then_race.raced
        monkeypatch.setattr(Path, "exists", exists_then_race)
        assert snapshot.write(directory, self._view_events()) == directory / "dashboard.html"
        ((other, errors),) = raced
        other.join(5)
        assert not errors
        assert DashboardSnapshot.read(directory) == snapshot

    def test_concurrent_writer_cannot_replace_a_published_view(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Moving an interrupted write aside never moves another writer's complete view."""
        first, second = self._view("First"), self._view("Second")
        directory = tmp_path / "view"
        directory.mkdir()
        (directory / "snapshot.json").write_bytes(b'{"partial"')
        race_then_rename = _RaceBeforeRename(
            os.rename, partial(first.write, directory, self._view_events())
        )
        raced = race_then_rename.raced
        monkeypatch.setattr("telemetry.dashboard.os.rename", race_then_rename)
        assert second.write(directory, self._view_events()) == directory / "dashboard.html"
        ((other, errors),) = raced
        other.join(5)
        # Exactly one view is published, and the other writer is told so.
        assert DashboardSnapshot.read(directory) == second
        assert len(errors) == 1 and "different content" in str(errors[0])

    def test_published_view_is_readable_as_any_directory_is(self, tmp_path: Path) -> None:
        """A view gets the umask's mode, and a provisioned empty directory keeps its own."""
        snapshot = self._view()
        previous = os.umask(0o022)
        try:
            fresh = tmp_path / "fresh"
            snapshot.write(fresh, self._view_events())
            provisioned = tmp_path / "provisioned"
            provisioned.mkdir()
            provisioned.chmod(0o2775)
            snapshot.write(provisioned, self._view_events())
        finally:
            os.umask(previous)
        assert stat.S_IMODE(fresh.stat().st_mode) == 0o755
        assert stat.S_IMODE((fresh / "dashboard.html").stat().st_mode) == 0o644
        assert stat.S_IMODE(provisioned.stat().st_mode) == 0o2775
        assert DashboardSnapshot.read(provisioned) == snapshot

    def test_exact_threshold_delivery_and_idempotency(self, tmp_path: Path) -> None:
        """Send one local alert and retain acceptance without a duplicate datagram."""
        metric = self._metric()
        events = (self._event("last", 3, self._ratio(3, 2)),)
        alerts = OperationalAlerts(tmp_path / "alerts.sqlite")
        with TemporaryDirectory(prefix="dashboard-", dir=_SOCKET_ROOT) as socket_dir:
            address = Path(socket_dir) / "syslog.sock"
            config = self._config(metric, address=address)
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as receiver:
                receiver.bind(str(address))
                receiver.settimeout(0.2)
                first = DashboardBuilder.build(
                    config, self._query(), events, MetricRegistry((metric,)), alerts
                )
                payload = receiver.recv(512)
                assert first.alert_results[0].state == "triggered"
                assert first.alert_results[0].observed == self._ratio(3, 2)
                assert first.alert_results[0].delivery is not None
                assert first.alert_results[0].delivery.status == "delivered"
                assert first.alert_results[0].delivery.control_sha256.encode() in payload
                second = DashboardBuilder.build(
                    config, self._query(), events, MetricRegistry((metric,)), alerts
                )
                assert second == first
                with pytest.raises(TimeoutError):
                    receiver.recv(512)
        assert alerts.read() == (first.alert_results[0].delivery,)
        first.write(tmp_path / "view", events)
        assert DashboardSnapshot.read(tmp_path / "view") == first

    def test_missing_stale_and_failed_delivery_are_visible(self, tmp_path: Path) -> None:
        """Never classify absent input as clear and retain failed socket delivery."""
        metric = self._metric(stale_after_seconds=60)
        with TemporaryDirectory(prefix="dashboard-", dir=_SOCKET_ROOT) as socket_dir:
            address = Path(socket_dir) / "absent.sock"
            rule = self._rule(metric, address, on_missing="trigger", on_stale="unavailable")
            config = DashboardConfig(
                title="Availability",
                panels=(
                    DashboardPanel(
                        title="Queue", metric_identity=metric.spec.identity, kind="table"
                    ),
                ),
                alerts=(rule,),
            )
            registry = MetricRegistry((metric,))
            missing = DashboardBuilder.build(config, self._query(), (), registry)
            assert missing.results[0].status == "missing"
            assert missing.alert_results[0].state == "triggered"
            assert missing.alert_results[0].delivery is None
            failed = DashboardBuilder.build(
                config, self._query(), (), registry, OperationalAlerts(tmp_path / "failed.sqlite")
            )
            assert failed.alert_results[0].delivery is not None
            assert failed.alert_results[0].delivery.status == "failed"
            assert "failed" in failed.render_html().decode()
            persistence_failed = DashboardBuilder.build(
                config, self._query(), (), registry, OperationalAlerts(tmp_path)
            )
            assert persistence_failed.alert_results[0].state == "triggered"
            assert persistence_failed.alert_results[0].delivery is None
            assert persistence_failed.alert_results[0].delivery_error == "alert_persistence_failed"
            assert "alert persistence failed; delivery unknown" in (
                persistence_failed.render_html().decode()
            )
            persistence_failed.write(tmp_path / "persistence-failed-view", ())
            assert DashboardSnapshot.read(tmp_path / "persistence-failed-view") == (
                persistence_failed
            )
            stale = DashboardBuilder.build(
                config,
                self._query(),
                (self._event("old", 1, self._ratio(3)),),
                registry,
            )
            assert stale.results[0].status == "stale"
            assert stale.alert_results[0].state == "unavailable"
            assert stale.alert_results[0].observed is None
            research_metric = SeriesMetric(replace(metric.spec, modes=("research",)))
            inapplicable_rule = self._rule(research_metric, address, on_missing="trigger")
            inapplicable = DashboardBuilder.build(
                DashboardConfig(
                    title="Applicability",
                    panels=(
                        DashboardPanel(
                            title="Research only",
                            metric_identity=research_metric.spec.identity,
                            kind="table",
                        ),
                    ),
                    alerts=(inapplicable_rule,),
                ),
                self._query(),
                (),
                MetricRegistry((research_metric,)),
            )
            assert inapplicable.results[0].status == "inapplicable"
            assert inapplicable.alert_results[0].state == "inapplicable"

    def test_rejects_units_unknown_definitions_and_excess_selections(self, tmp_path: Path) -> None:
        """Reject configuration drift before it can produce a plausible dashboard."""
        metric = self._metric()
        rule = self._rule(metric, Path("/private/tmp/dashboard-unused.sock"), units="bytes")
        config = DashboardConfig(
            title="Mismatch",
            panels=(
                DashboardPanel(title="Queue", metric_identity=metric.spec.identity, kind="table"),
            ),
            alerts=(rule,),
        )
        with pytest.raises(ValueError, match="units"):
            DashboardBuilder.build(config, self._query(), (), MetricRegistry((metric,)))
        invalid_later = DashboardConfig(
            title="Preflight all rules",
            panels=config.panels,
            alerts=(
                self._rule(metric, Path("/private/tmp/dashboard-unused.sock")),
                replace(rule, identity="different-rule"),
            ),
        )
        alerts_path = tmp_path / "must-remain-absent.sqlite"
        with pytest.raises(ValueError, match="units"):
            DashboardBuilder.build(
                invalid_later,
                self._query(),
                (self._event("alerting", 3, self._ratio(2)),),
                MetricRegistry((metric,)),
                OperationalAlerts(alerts_path),
            )
        assert not alerts_path.exists()
        with pytest.raises(ValueError, match="unregistered"):
            DashboardBuilder.build(config, self._query(), (), MetricRegistry(()))
        with pytest.raises(ValueError, match="32 panels"):
            DashboardConfig(
                title="Too many",
                panels=tuple(
                    DashboardPanel(
                        title=f"Panel {index}", metric_identity=metric.spec.identity, kind="table"
                    )
                    for index in range(33)
                ),
            )

    def test_retains_other_input_versions_without_substitution(self, tmp_path: Path) -> None:
        """Keep newer history visible while an older metric remains missing."""
        metric = self._metric()
        newer = replace(self._event("sample", 1, self._ratio(9)), version="v2")
        config = DashboardConfig(
            title="Versioned source",
            panels=(
                DashboardPanel(
                    title="First line", metric_identity=metric.spec.identity, kind="line"
                ),
                DashboardPanel(
                    title="Second line", metric_identity=metric.spec.identity, kind="line"
                ),
            ),
        )
        snapshot = DashboardBuilder.build(
            config, self._query(), (newer,), MetricRegistry((metric,))
        )
        assert snapshot.results[0].status == "missing"
        assert snapshot.results[0].input_count == 0
        assert (snapshot.event_count, snapshot.events_sha256) == (1, self._digest((newer,)))
        older = self._event("older", 2, self._ratio(1))
        chart = DashboardBuilder.build(
            config, self._query(), (newer, older), MetricRegistry((metric,))
        )
        assert chart.results[0].inputs_sha256 == self._digest((older,))
        rendered = chart.render_html().decode()
        title_ids = [item.split('"', maxsplit=1)[0] for item in rendered.split('<title id="')[1:]]
        assert len(title_ids) == 2
        assert len(title_ids) == len(set(title_ids))
        snapshot.write(tmp_path / "versions", (newer,))
        assert DashboardSnapshot.read(tmp_path / "versions") == snapshot

    def test_public_snapshot_boundaries_revalidate_mutated_points(self, tmp_path: Path) -> None:
        """A frozen snapshot's render, identity and retention reject a forced invalid point."""
        metric = self._metric()
        events = (self._event("sample", 1, self._ratio(2)),)
        snapshot = DashboardBuilder.build(
            self._config(metric), self._query(), events, MetricRegistry((metric,))
        )
        force_setattr(snapshot.results[0].points[0], "at", self.start + timedelta(hours=5))
        with pytest.raises(ValueError, match="selected query"):
            snapshot.render_html()
        with pytest.raises(ValueError, match="selected query"):
            _ = snapshot.identity
        with pytest.raises(ValueError, match="selected query"):
            snapshot.write(tmp_path / "invalid", events)
        assert not (tmp_path / "invalid").exists()

    def test_renderer_reuse_matches_public_snapshots_at_changed_cutoffs_and_revisions(self) -> None:
        """Event-only row reuse cannot freeze metric freshness, knowledge or revision text."""
        metric = self._metric()
        config, registry = self._config(metric), MetricRegistry((metric,))
        renderer = DashboardRenderer(config, registry)
        first = self._event("sample", 3, self._ratio(2))
        query = self._query()
        original = DashboardBuilder.build(config, query, (first,), registry)
        assert renderer.render(query, (first,)) == (original.render_html(), original.identity)
        late_query = self._query(as_of_hours=6)
        stale = DashboardBuilder.build(config, late_query, (first,), registry)
        assert stale.results[0].status == "stale"
        assert renderer.render(late_query, (first,)) == (stale.render_html(), stale.identity)
        correction = replace(
            first,
            value=self._ratio(9),
            revision=1,
            available_at=self.start + timedelta(hours=5),
            recorded_at=self.start + timedelta(hours=5),
        )
        revised = DashboardBuilder.build(config, late_query, (correction,), registry)
        assert renderer.render(late_query, (correction,)) == (
            revised.render_html(),
            revised.identity,
        )
        with pytest.raises(ValueError, match="selected query"):
            renderer.render(query, (correction,))
        force_setattr(first, "recorded_at", self.start + timedelta(hours=5))
        with pytest.raises(ValueError, match="selected query"):
            renderer.render(query, (first,))

    @pytest.mark.parametrize("mutate_prior_result", (False, True))
    def test_renderer_admits_inputs_and_results_after_injected_callbacks(
        self, mutate_prior_result: bool
    ) -> None:
        """A buggy callback cannot poison an input or earlier result after their first admission."""
        metric = self._metric()
        prior = _RetainedResultMetric(metric)
        poisoned = _MutatingCallbackMetric(
            replace(metric.spec, name="callback-fault"), prior if mutate_prior_result else None
        )
        config = DashboardConfig(
            title="Callback boundary",
            panels=(
                DashboardPanel(title="Normal", metric_identity=prior.spec.identity, kind="table"),
                DashboardPanel(
                    title="Injected", metric_identity=poisoned.spec.identity, kind="table"
                ),
            ),
        )
        renderer = DashboardRenderer(config, MetricRegistry((prior, poisoned)))
        with pytest.raises(ValueError):
            renderer.render(self._query(), (self._event("sample", 3, self._ratio(2)),))

    @pytest.mark.parametrize(
        ("field", "value"),
        (("clock_quality", "unsupported"), ("sensitivity", "unsupported"), ("units", "\n")),
    )
    def test_renderer_reuse_rejects_forced_unselected_event_metadata(
        self, field: str, value: str
    ) -> None:
        """A reused row still needs full input admission even when no selected metric uses it."""
        metric = self._metric()
        renderer = DashboardRenderer(self._config(metric), MetricRegistry((metric,)))
        event = replace(self._event("unselected", 1, self._ratio(2)), name="unselected")
        renderer.render(self._query(), (event,))
        force_setattr(event, field, value)
        with pytest.raises(ValueError):
            renderer.render(self._query(), (event,))
