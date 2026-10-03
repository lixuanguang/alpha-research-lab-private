"""Prove the bounded dashboard equals full evaluation over the same matched-cutoff selection."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from typing import Literal

# third party library imports
import msgspec
import pytest
from msgspec.structs import force_setattr, replace

# project library imports
from financial_units import ExactRatio
from serialization import DomainCodec
from telemetry import (
    DashboardBuilder,
    DashboardConfig,
    DashboardPanel,
    DashboardRenderer,
    DashboardSnapshot,
    DelayedLabelError,
    MetricInput,
    MetricPoint,
    MetricRegistry,
    MetricResult,
    MetricSpec,
    MonitoringEvent,
    MonitoringIdentity,
    MonitoringQuery,
    PanelResult,
    SeriesMetric,
    TelemetryStore,
)
from telemetry.dashboard import POINT_LIMIT, DashboardViewSelection

Aggregation = Literal["last", "sum", "mean", "maximum"]


class DashboardSelection:
    """Build bounded dashboard selections."""

    @staticmethod
    def selection(
        query: MonitoringQuery, events: tuple[MonitoringEvent, ...], renderer: DashboardRenderer
    ) -> DashboardViewSelection:
        """Share the renderer's decode cache with a directly built view."""
        return DashboardViewSelection.of(query, events, renderer.codec, renderer._events)


class _Opaque:
    """Wrap an installed series definition so the builder evaluates it in full."""

    def __init__(self, metric: SeriesMetric) -> None:
        """Keep the wrapped definition and its unchanged specification."""
        self.metric = metric

    @property
    def spec(self) -> MetricSpec:
        """Expose the wrapped definition's specification."""
        return self.metric.spec

    def evaluate(self, query: MonitoringQuery, events: tuple[MonitoringEvent, ...]) -> MetricResult:
        """Delegate to the installed implementation over every input."""
        return self.metric.evaluate(query, events)


class TestBoundedDashboard:
    """Compare the bounded installed path with full evaluation and retained provenance."""

    start = datetime(2026, 9, 1, tzinfo=UTC)

    @classmethod
    def _event(
        cls,
        index: int,
        value: Fraction | None,
        *,
        seconds: int | None = None,
        recorded: int = 0,
        revision: int = 0,
        units: str = "count",
    ) -> MonitoringEvent:
        """Author one queue observation; ``seconds`` defaults to the sample index."""
        at = cls.start + timedelta(seconds=index if seconds is None else seconds)
        return MonitoringEvent(
            context=MonitoringIdentity(scope="account:a", mode="paper", account="a"),
            name="queue",
            version="v1",
            sample=f"sample-{index:04d}",
            at=at,
            available_at=at,
            recorded_at=at + timedelta(milliseconds=recorded),
            units=units,
            value=None if value is None else ExactRatio.from_fraction(value),
            missing_reason="source gap" if value is None else None,
            revision=revision,
        )

    @classmethod
    def _query(cls, *, end: int = 3600, as_of: int = 3600, limit: int = 10_000) -> MonitoringQuery:
        """Select the authored hour at an explicit knowledge cutoff."""
        return MonitoringQuery(
            scope="account:a",
            mode="paper",
            start=cls.start,
            end=cls.start + timedelta(seconds=end),
            as_of=cls.start + timedelta(seconds=as_of),
            limit=limit,
        )

    @staticmethod
    def _metric(aggregation: Aggregation, *, stale: int | None = 7200) -> SeriesMetric:
        """Define one installed count series with the selected aggregation."""
        return SeriesMetric(
            MetricSpec(
                name=f"queue-{aggregation}",
                version="1",
                implementation_sha256="a" * 64,
                inputs=(MetricInput(name="queue", version="v1", units="count"),),
                units="count",
                modes=("paper",),
                aggregation=aggregation,
                missingness="propagate",
                stale_after_seconds=stale,
            )
        )

    @staticmethod
    def _config(*identities: str) -> DashboardConfig:
        """Show each selected metric as a line panel."""
        return DashboardConfig(
            title="Bounded",
            panels=tuple(
                DashboardPanel(title=f"Panel {index}", metric_identity=identity, kind="line")
                for index, identity in enumerate(identities)
            ),
        )

    @classmethod
    def _series(
        cls, count: int, *, gap: int | None = None, ties: int = 1
    ) -> tuple[MonitoringEvent, ...]:
        """Author a series whose last ``ties`` samples share one event time."""
        last = count - ties
        return tuple(
            cls._event(
                index,
                None if index == gap else Fraction(index % 7 + 1, 3),
                seconds=min(index, last),
                # Receipt runs backwards, so the latest tied event is not last in order.
                recorded=count - index,
            )
            for index in range(count)
        )

    @pytest.mark.parametrize("aggregation", ("last", "sum", "mean", "maximum"))
    @pytest.mark.parametrize(
        ("count", "gap", "ties", "as_of"),
        (
            (POINT_LIMIT + 37, None, 1, 3600),
            (POINT_LIMIT + 37, 5, 1, 3600),
            (POINT_LIMIT + 37, POINT_LIMIT + 36, 1, 3600),
            (POINT_LIMIT + 37, None, 4, 3600),
            (12, None, 3, 3600),
            (POINT_LIMIT + 37, None, 1, 7300 + POINT_LIMIT),
            (0, None, 1, 3600),
        ),
    )
    def test_installed_series_equals_full_evaluation(
        self, aggregation: Aggregation, count: int, gap: int | None, ties: int, as_of: int
    ) -> None:
        """Value, status, counts, digest and the last points equal evaluation over every input."""
        metric = self._metric(aggregation)
        opaque = _Opaque(metric)
        events = self._series(count, gap=gap, ties=ties)
        query = self._query(as_of=as_of)
        bounded = DashboardBuilder.build(
            self._config(metric.spec.identity), query, events, MetricRegistry((metric,))
        ).results[0]
        full = DashboardBuilder.build(
            self._config(metric.spec.identity), query, events, MetricRegistry((opaque,))
        ).results[0]
        assert bounded == full
        direct = MetricRegistry((metric,)).evaluate(metric.spec.identity, query, events)
        assert (bounded.value, bounded.status, bounded.reason) == (
            direct.value,
            direct.status,
            direct.reason,
        )
        assert bounded.points == direct.points[-POINT_LIMIT:]
        assert (bounded.input_count, bounded.point_count) == (count, count)
        assert (
            bounded.inputs_sha256
            == hashlib.sha256(
                b"".join(bytes.fromhex(item) for item in direct.input_ids)
            ).hexdigest()
        )

    def test_store_selection_equals_event_inputs_at_every_cutoff(self, tmp_path: Path) -> None:
        """Late revisions and receipt cutoffs select the same view through either input."""
        store = TelemetryStore(tmp_path / "telemetry.sqlite3")
        events = self._series(POINT_LIMIT + 10)
        corrected = replace(
            events[-1],
            value=ExactRatio(numerator="99", denominator="1"),
            revision=1,
            available_at=self.start + timedelta(seconds=3000),
            recorded_at=self.start + timedelta(seconds=3100),
        )
        store.append((*events, corrected))
        metrics = (self._metric("last"), self._metric("sum"))
        config = self._config(*(metric.spec.identity for metric in metrics))
        registry = MetricRegistry(metrics)
        renderer = DashboardRenderer(config, registry)
        values = []
        for as_of in (3000, 3099, 3100, 3600):
            query = self._query(end=3000, as_of=as_of)
            selection = store.select(query)
            view = DashboardBuilder.build(config, query, selection, registry)
            assert view == DashboardBuilder.build(config, query, store.query(query), registry)
            assert renderer.render(query, selection) == (view.render_html(), view.identity)
            values.append(view.results[0].value)
        assert values[:2] == [events[-1].value] * 2
        assert values[2:] == [corrected.value] * 2

    def test_undisplayed_input_units_and_query_mismatches_fail(self, tmp_path: Path) -> None:
        """Units are checked beyond the shown points; another query's selection is refused."""
        metric = self._metric("last")
        config, registry = self._config(metric.spec.identity), MetricRegistry((metric,))
        events = self._series(POINT_LIMIT + 5)
        wrong = (replace(events[0], units="bytes"), *events[1:])
        with pytest.raises(ValueError, match="units"):
            DashboardBuilder.build(config, self._query(), wrong, registry)
        store = TelemetryStore(tmp_path / "telemetry.sqlite3")
        store.append(events)
        with pytest.raises(ValueError, match="another query"):
            DashboardBuilder.build(
                config, self._query(end=3599, as_of=3599), store.select(self._query()), registry
            )
        with pytest.raises(ValueError, match="result limit"):
            store.select(self._query(limit=POINT_LIMIT + 4))
        with pytest.raises(ValueError, match="bounded"):
            DashboardBuilder.build(config, self._query(limit=POINT_LIMIT + 4), events, registry)
        duplicate = (
            *events,
            replace(
                events[0], revision=1, recorded_at=events[0].recorded_at + timedelta(seconds=1)
            ),
        )
        with pytest.raises(ValueError, match="one selected revision"):
            DashboardBuilder.build(config, self._query(), duplicate, registry)

    def test_retained_provenance_and_pages_reproduce_the_selection(self, tmp_path: Path) -> None:
        """Retained payloads and store pages reproduce the digest; altered provenance fails."""
        store = TelemetryStore(tmp_path / "telemetry.sqlite3")
        store.append(self._series(POINT_LIMIT + 10))
        metric = self._metric("mean")
        query = self._query()
        selection = store.select(query)
        view = DashboardBuilder.build(
            self._config(metric.spec.identity), query, selection, MetricRegistry((metric,))
        )
        pages: list[MonitoringEvent] = []
        cursor = None
        while True:
            page, cursor = store.page(query, after=cursor, size=7)
            pages.extend(page)
            if cursor is None:
                break
        identities = b"".join(bytes.fromhex(event.identity) for event in pages)
        assert (len(pages), hashlib.sha256(identities).hexdigest()) == (
            view.event_count,
            view.events_sha256,
        )
        directory = tmp_path / "view"
        view.write(directory, selection)
        assert DashboardSnapshot.read(directory) == view
        lines = (directory / "provenance.jsonl").read_bytes().splitlines(keepends=True)
        codec = DomainCodec()
        forged = codec.decode_json(lines[0], MonitoringEvent)
        for changed in (
            b"".join(lines[1:]),
            b"".join((lines[1], lines[0], *lines[2:])),
            codec.encode_json(replace(forged, recorded_at=self.start + timedelta(hours=2)))
            + b"\n"
            + b"".join(lines[1:]),
        ):
            (directory / "provenance.jsonl").write_bytes(changed)
            manifest = msgspec.json.decode(
                (directory / "manifest.json").read_bytes(), type=dict[str, str]
            )
            manifest["provenance_sha256"] = hashlib.sha256(changed).hexdigest()
            (directory / "manifest.json").write_bytes(msgspec.json.encode(manifest))
            with pytest.raises(ValueError, match=r"provenance|selected query"):
                DashboardSnapshot.read(directory)
        # A view consistent with its payloads still needs them inside its query.
        outside = codec.encode_json(replace(forged, recorded_at=self.start + timedelta(hours=2)))
        results: tuple[PanelResult, ...] = tuple(
            self._without_inputs(result) for result in view.results
        )
        consistent = replace(
            view,
            event_count=1,
            events_sha256=hashlib.sha256(hashlib.sha256(outside).digest()).hexdigest(),
            results=results,
        )
        files = {
            "snapshot.json": codec.encode_json(consistent),
            "dashboard.html": consistent.render_html(),
            "provenance.jsonl": outside + b"\n",
        }
        for name, payload in files.items():
            (directory / name).write_bytes(payload)
        manifest_fields: dict[str, str] = {
            "json_sha256": hashlib.sha256(files["snapshot.json"]).hexdigest(),
            "html_sha256": hashlib.sha256(files["dashboard.html"]).hexdigest(),
            "provenance_sha256": hashlib.sha256(files["provenance.jsonl"]).hexdigest(),
            "schema_version": "dashboard-manifest",
        }
        (directory / "manifest.json").write_bytes(msgspec.json.encode(manifest_fields))
        with pytest.raises(ValueError, match="selected query"):
            DashboardSnapshot.read(directory)

    @staticmethod
    def _without_inputs(result: PanelResult) -> PanelResult:
        """Keep a metric's definition and outcome while claiming it selected nothing."""
        no_points: tuple[MetricPoint, ...] = ()
        return replace(result, input_count=0, point_count=0, points=no_points)

    def test_renderer_reuse_cannot_carry_a_mutated_point(self) -> None:
        """A caller mutating a returned point's value cannot change a later read."""
        metric = self._metric("last")
        config, registry = self._config(metric.spec.identity), MetricRegistry((metric,))
        events = self._series(POINT_LIMIT + 3)
        query = self._query()
        renderer = DashboardRenderer(config, registry)
        expected = renderer.render(query, events)
        view = DashboardBuilder._build(
            config,
            DashboardSelection.selection(query, events, renderer),
            registry,
            None,
        )
        value = view.results[0].points[-1].value
        assert value is not None
        force_setattr(value, "numerator", "1000")
        assert renderer.render(query, events) == expected
        force_setattr(value, "numerator", True)
        assert renderer.render(query, events) == expected

    def test_custom_definition_keeps_its_last_points(self) -> None:
        """A custom definition sees every input; its view keeps the last points and digest."""
        spec = MetricSpec(
            name="prediction-error",
            version="v1",
            implementation_sha256="b" * 64,
            inputs=(
                MetricInput(name="prediction", version="v1", units="count"),
                MetricInput(name="outcome", version="v1", units="count"),
            ),
            units="(count)^2",
            modes=("paper",),
            aggregation="custom",
            missingness="pending labels remain gaps; mean uses observed pairs",
        )
        predictions = tuple(
            replace(self._event(index, Fraction(index, 2)), name="prediction")
            for index in range(POINT_LIMIT + 9)
        )
        outcomes = tuple(
            replace(self._event(index, Fraction(index + 1, 2)), name="outcome")
            for index in range(0, POINT_LIMIT + 9, 2)
        )
        registry = MetricRegistry((DelayedLabelError(spec),))
        query = self._query()
        view = DashboardBuilder.build(
            self._config(spec.identity), query, (*predictions, *outcomes), registry
        )
        direct = registry.evaluate(spec.identity, query, (*predictions, *outcomes))
        result = view.results[0]
        assert (result.value, result.point_count) == (direct.value, len(direct.points))
        assert result.points == direct.points[-POINT_LIMIT:]
        assert result.input_count == len(predictions) + len(outcomes)
