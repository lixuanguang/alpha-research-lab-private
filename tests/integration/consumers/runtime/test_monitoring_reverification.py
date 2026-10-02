"""Prove the retained-page inspection fails on each property it guards."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from fractions import Fraction

# third party library imports
import pytest
from monitoring_reverification import PageInspection

# project library imports
from financial_units import ExactRatio
from telemetry import (
    DashboardBuilder,
    DashboardConfig,
    DashboardPanel,
    DashboardSnapshot,
    MetricInput,
    MetricRegistry,
    MetricSpec,
    MonitoringEvent,
    MonitoringIdentity,
    MonitoringQuery,
    SeriesMetric,
)


class TestPageInspection:
    """Inspect one small real view and a page altered one way at a time."""

    start = datetime(2026, 9, 1, tzinfo=UTC)

    @classmethod
    def _view(cls) -> DashboardSnapshot:
        """Build a two-panel view over one exact observation."""
        metric = SeriesMetric(
            MetricSpec(
                name="queue",
                version="1",
                implementation_sha256="a" * 64,
                inputs=(MetricInput(name="queue", version="1", units="count"),),
                units="count",
                modes=("paper",),
                aggregation="last",
                missingness="propagate",
                stale_after_seconds=None,
            )
        )
        at = cls.start + timedelta(seconds=1)
        event = MonitoringEvent(
            context=MonitoringIdentity(scope="account:a", mode="paper"),
            name="queue",
            version="1",
            sample="one",
            at=at,
            available_at=at,
            recorded_at=at,
            units="count",
            value=ExactRatio.from_fraction(Fraction(3)),
        )
        query = MonitoringQuery(
            scope="account:a",
            mode="paper",
            start=cls.start,
            end=cls.start + timedelta(minutes=1),
            as_of=cls.start + timedelta(minutes=1),
        )
        config = DashboardConfig(
            title="Inspected",
            panels=(
                DashboardPanel(title="Line", metric_identity=metric.spec.identity, kind="line"),
                DashboardPanel(title="Table", metric_identity=metric.spec.identity, kind="table"),
            ),
        )
        return DashboardBuilder.build(config, query, (event,), MetricRegistry((metric,)))

    def test_rendered_page_passes(self) -> None:
        """The renderer's own page shows the digest, every panel and no outside resource."""
        view = self._view()
        assert all(gate.passed for gate in PageInspection.gates("page", view, view.render_html()))

    @pytest.mark.parametrize(
        ("old", "new", "gate"),
        (
            (b"</main>", b"<script>x</script></main>", "page.self_contained"),
            (b"</main>", b'<img src="http://x"></main>', "page.self_contained"),
            (b'<section class="panel">', b"<section>", "page.every_panel_shown"),
        ),
    )
    def test_altered_page_fails(self, old: bytes, new: bytes, gate: str) -> None:
        """Each altered property fails its own gate."""
        view = self._view()
        altered = view.render_html().replace(old, new, 1)
        failed = {
            item.name for item in PageInspection.gates("page", view, altered) if not item.passed
        }
        assert gate in failed

    def test_missing_selection_digest_fails(self) -> None:
        """A page that does not show the view's selection digest fails."""
        view = self._view()
        page = view.render_html().replace(view.events_sha256.encode(), b"0" * 64)
        failed = {item.name for item in PageInspection.gates("page", view, page) if not item.passed}
        assert failed == {"page.selection_digest_shown"}
