"""Protect exact dashboard rendering, retention and local alert outcomes."""

from __future__ import annotations

# standard library imports
import socket
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from financial_units import ExactRatio
from telemetry.dashboard import (
    AlertRule,
    DashboardBuilder,
    DashboardConfig,
    DashboardPanel,
    DashboardSnapshot,
    UnavailablePolicy,
)
from telemetry.events import MonitoringEvent, MonitoringIdentity, MonitoringQuery
from telemetry.metrics import MetricInput, MetricRegistry, MetricSpec, SeriesMetric
from telemetry.operations import OperationalAlerts


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
        assert snapshot.results[0].input_ids == tuple(event.identity for event in events)
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
        html_path = snapshot.write(directory)
        before = html_path.stat().st_mtime_ns
        assert DashboardSnapshot.read(directory) == snapshot
        assert snapshot.write(directory) == html_path
        assert html_path.stat().st_mtime_ns == before
        other = DashboardBuilder.build(
            self._config(metric, title="Different"),
            self._query(),
            events,
            MetricRegistry((metric,)),
        )
        with pytest.raises(ValueError, match="different content"):
            other.write(directory)
        html_path.write_bytes(b"changed")
        with pytest.raises(ValueError, match="digest"):
            DashboardSnapshot.read(directory)

    def test_exact_threshold_delivery_and_idempotency(self, tmp_path: Path) -> None:
        """Send one local alert and retain acceptance without a duplicate datagram."""
        metric = self._metric()
        events = (self._event("last", 3, self._ratio(3, 2)),)
        alerts = OperationalAlerts(tmp_path / "alerts.sqlite")
        with TemporaryDirectory(prefix="dashboard-", dir="/private/tmp") as socket_dir:
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
        first.write(tmp_path / "view")
        assert DashboardSnapshot.read(tmp_path / "view") == first

    def test_missing_stale_and_failed_delivery_are_visible(self, tmp_path: Path) -> None:
        """Never classify absent input as clear and retain failed socket delivery."""
        metric = self._metric(stale_after_seconds=60)
        with TemporaryDirectory(prefix="dashboard-", dir="/private/tmp") as socket_dir:
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
            persistence_failed.write(tmp_path / "persistence-failed-view")
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
        assert snapshot.results[0].input_ids == ()
        assert snapshot.events == (newer,)
        legacy = self._event("legacy", 2, self._ratio(1))
        chart = DashboardBuilder.build(
            config, self._query(), (newer, legacy), MetricRegistry((metric,))
        )
        assert chart.results[0].input_ids == (legacy.identity,)
        rendered = chart.render_html().decode()
        title_ids = [item.split('"', maxsplit=1)[0] for item in rendered.split('<title id="')[1:]]
        assert len(title_ids) == 2
        assert len(title_ids) == len(set(title_ids))
        snapshot.write(tmp_path / "versions")
        assert DashboardSnapshot.read(tmp_path / "versions") == snapshot
