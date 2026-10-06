"""Prove exact selected study extensions and completed artifact reading."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from accounting import Fill, Ledger, LedgerState
from financial_units import Currency, Dimension, ExactRatio, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from research.experiments import AttemptStore, ExperimentSpec, Fingerprint, TimeWindow
from research.reports import (
    ChartSpec,
    FoldSummary,
    LedgerPoint,
    MetricValue,
    ReportContext,
    ReportObservation,
)
from research.studies import TrialEvaluation
from research.studies.extensions import (
    LedgerCurveChart,
    NetReturnMetric,
    StudyReport,
    StudyReportBuilder,
    StudyReportReader,
)
from research.studies.monitoring import (
    ReportChartAdapter,
    ReportMetricAdapter,
    ReportMonitoringBridge,
)
from research.studies.results import ResultManifest
from serialization import DomainCodec
from telemetry import (
    MetricInput,
    MetricPoint,
    MetricRegistry,
    MetricResult,
    MetricSpec,
    MonitoringEvent,
    MonitoringIdentity,
    MonitoringQuery,
    TelemetryStore,
)


class _RetainedErrorMetric:
    """Exercise one new metric definition through reports and telemetry queries."""

    spec = MetricSpec(
        name="retained-error",
        version="1",
        implementation_sha256=hashlib.sha256(b"retained-error-test-definition").hexdigest(),
        inputs=(MetricInput(name="error<script>", version="1", units="ratio"),),
        units="ratio",
        modes=("research", "paper"),
        aggregation="custom",
        missingness="preserve gaps; mean observed values",
    )

    def evaluate(self, query: MonitoringQuery, events: tuple[MonitoringEvent, ...]) -> MetricResult:
        """Retain the exact observed mean and each explicit gap for charting."""
        values = tuple(
            Fraction(int(event.value.numerator), int(event.value.denominator))
            for event in events
            if event.value is not None
        )
        points = tuple(
            MetricPoint(
                sample=event.sample,
                at=event.at,
                value=event.value,
                missing_reason=event.missing_reason,
            )
            for event in events
        )
        return MetricResult(
            spec=self.spec,
            query=query,
            value=ExactRatio.from_fraction(sum(values, Fraction()) / len(values))
            if values
            else None,
            status="ok" if values else "missing",
            reason=None if values else "no observed errors",
            input_ids=tuple(event.identity for event in events),
            points=points,
        )


class _ForecastErrorMetric:
    """Exercise a new metric implementation without changing the report builder."""

    identity = Fingerprint(name="forecast-error", sha256="d" * 64)

    def evaluate(self, context: ReportContext) -> MetricValue:
        """Average only the exact diagnostic errors supplied by the study runner."""
        observations = tuple(fold.diagnostics[0] for fold in context.folds)
        values = [
            Fraction(int(observation.value.numerator), int(observation.value.denominator))
            for observation in observations
            if observation.value is not None
        ]
        return MetricValue(
            definition=self.identity,
            name="Forecast error <custom>",
            version="forecast",
            units="ratio",
            value=ExactRatio.from_fraction(sum(values, Fraction(0)) / len(values)),
            observations=observations,
        )


class _ForecastChart:
    """Exercise a fresh chart that carries potentially unsafe user-authored labels."""

    identity = Fingerprint(name="forecast-chart", sha256="e" * 64)

    def evaluate(self, context: ReportContext) -> ChartSpec:
        """Reference exact error observations supplied by the study runner."""
        return ChartSpec(
            definition=self.identity,
            title="Error <script>alert(1)</script>",
            kind="bar",
            data_references=("error<script>",),
            observations=tuple(fold.diagnostics[0] for fold in context.folds),
        )


class _SubstitutedMetric:
    """Identify the selected metric but return an unrelated output identity."""

    identity = _ForecastErrorMetric.identity

    def evaluate(self, context: ReportContext) -> MetricValue:
        """Produce a forged output to prove the builder rejects silent substitution."""
        return MetricValue(
            definition=NetReturnMetric.identity,
            name="wrong output",
            version="1",
            units="ratio",
            value=ExactRatio.from_fraction(Fraction(0)),
        )


class TestStudyReports:
    """Use small posted ledgers, explicit clocks and real retained attempts."""

    start = datetime(2025, 1, 1, tzinfo=UTC)
    currency = Currency(code="TEST", minor_unit=Decimal("0.01"))
    dimension = Dimension(
        instrument_id=InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
        kind=QuantityKind.BASE_UNIT,
    )

    @classmethod
    def _fold(cls, fold_id: str, offset: int) -> FoldSummary:
        """Post one exact buy and retain an unavailable intermediate valuation."""
        start = cls.start + timedelta(hours=offset)
        end = start + timedelta(hours=2)
        price = Price(value=Decimal("100"), currency=cls.currency, per=cls.dimension)
        state = LedgerState(
            initial_cash=Money(value=Decimal("1000"), currency=cls.currency),
            dimension=cls.dimension,
        )
        ledger = Ledger(state)
        initial_mark = ledger.mark(None)
        ledger.apply(
            Fill(
                identity=f"buy-{fold_id}",
                decision_at=start + timedelta(minutes=10),
                filled_at=start + timedelta(minutes=11),
                quantity=Quantity(value=Decimal("1"), dimension=cls.dimension),
                reference=price,
                effective=price,
                fee=Money(value=Decimal("0"), currency=cls.currency),
            )
        )
        terminal = ledger.mark(
            Price(value=Decimal("110"), currency=cls.currency, per=cls.dimension)
        )
        return FoldSummary(
            fold_id=fold_id,
            window=TimeWindow(start=start, end=end),
            ledger=ledger.state,
            terminal_mark=terminal,
            curve=(
                LedgerPoint(at=start, mark=initial_mark),
                LedgerPoint(
                    at=start + timedelta(hours=1),
                    mark=None,
                    missing_reason="quote unavailable <late>",
                ),
                LedgerPoint(
                    at=start + timedelta(minutes=90),
                    mark=ledger.mark(
                        Price(value=Decimal("105"), currency=cls.currency, per=cls.dimension)
                    ),
                ),
                LedgerPoint(at=end, mark=terminal),
            ),
            diagnostics=(
                ReportObservation(
                    fold_id=fold_id,
                    name="error<script>",
                    at=start + timedelta(minutes=10),
                    units="ratio",
                    value=ExactRatio.from_fraction(Fraction(1, 3)),
                ),
            ),
        )

    @classmethod
    def _context(cls, identity: str = "a" * 64) -> ReportContext:
        """Provide two independent fold ledgers under one semantic study identity."""
        return ReportContext(
            study_identity=identity,
            folds=(cls._fold("first", 0), cls._fold("second", 3)),
        )

    @staticmethod
    def _report(context: ReportContext) -> StudyReport:
        """Bind both builtins and new extensions in explicit configured order."""
        return StudyReportBuilder.build(
            context,
            expected_metrics=(NetReturnMetric.identity, _ForecastErrorMetric.identity),
            expected_charts=(LedgerCurveChart.identity, _ForecastChart.identity),
            metrics=(NetReturnMetric(), _ForecastErrorMetric()),
            charts=(LedgerCurveChart(), _ForecastChart()),
            limitations=("Engineering result; <no deployment authority>.",),
        )

    @classmethod
    def _spec(cls) -> ExperimentSpec:
        """Construct a real engineering attempt for the artifact reader."""
        return ExperimentSpec(
            schema_version="experiment-engineering-sample",
            family="typed-report-consumer",
            inputs=(Fingerprint(name="input", sha256="a" * 64),),
            components=(Fingerprint(name="implementation", sha256="b" * 64),),
            parameters=(),
            seeds=(),
            environment_sha256="c" * 64,
            split=None,
            engineering_sample=TimeWindow(start=cls.start, end=cls.start + timedelta(hours=5)),
        )

    def test_custom_extensions_preserve_selection_exact_values_and_escaped_html(self) -> None:
        """Keep custom identities, rational arithmetic, missing marks and safe display text."""
        report = self._report(self._context())
        assert report.selected_metrics == (
            NetReturnMetric.identity,
            _ForecastErrorMetric.identity,
        )
        assert report.selected_charts == (LedgerCurveChart.identity, _ForecastChart.identity)
        assert report.metrics[0].value == ExactRatio.from_fraction(Fraction(1, 100))
        assert report.metrics[1].value == ExactRatio.from_fraction(Fraction(1, 3))
        assert report.charts[0].observations[1].missing_reason == "quote unavailable <late>"
        assert report.charts[0].observations[-1].value == ExactRatio.from_fraction(Fraction(1010))
        assert DomainCodec().decode_json(DomainCodec().encode_json(report), StudyReport) == report
        rendered = report.render().decode()
        assert "1/100" in rendered and "1/3" in rendered
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
        assert "<script>" not in rendered
        assert '<svg viewBox="0 0 760 230"' in rendered
        assert rendered.count("<polyline") == 2
        assert rendered.count("<circle") == 2
        assert "<rect x=" in rendered
        assert "&lt;no deployment authority&gt;" in rendered
        assert "quote unavailable &lt;late&gt;" in rendered

    def test_custom_monitoring_definition_renders_retained_report_and_dashboard(
        self, tmp_path: Path
    ) -> None:
        """Reuse injected metric code and exact units without report or dashboard edits."""
        context = self._context()
        imported_at = self.start + timedelta(days=1)
        metric = _RetainedErrorMetric()
        bridge = ReportMonitoringBridge(metric, scope="research-study", recorded_at=imported_at)
        report_metric = ReportMetricAdapter(bridge)
        report_chart = ReportChartAdapter(bridge, title="Retained errors", kind="line")
        report = StudyReportBuilder.build(
            context,
            expected_metrics=(report_metric.identity,),
            expected_charts=(report_chart.identity,),
            metrics=(report_metric,),
            charts=(report_chart,),
        )
        assert report.metrics[0].definition.sha256 == metric.spec.identity
        assert report.metrics[0].units == "ratio"
        assert report.metrics[0].value == ExactRatio.from_fraction(Fraction(1, 3))
        assert tuple(point.units for point in report.charts[0].observations) == ("ratio", "ratio")
        assert b"Retained errors" in report.render()

        events = bridge.events(context)
        assert len(events) == 2
        assert all(
            event.available_at == imported_at
            and event.recorded_at == imported_at
            and event.clock_quality == "unknown"
            and event.context.study == context.study_identity
            for event in events
        )
        store = TelemetryStore(tmp_path / "research-telemetry.sqlite")
        assert store.append(events) == 2
        query = MonitoringQuery(
            scope="research-study",
            mode="research",
            start=context.folds[0].window.start,
            end=imported_at,
            as_of=imported_at,
        )
        dashboard_result = MetricRegistry((metric,)).evaluate(
            metric.spec.identity, query, store.query(query)
        )
        assert dashboard_result.spec.implementation_sha256 == metric.spec.implementation_sha256
        assert dashboard_result.value == report.metrics[0].value
        assert tuple(point.value for point in dashboard_result.points) == tuple(
            point.value for point in report.charts[0].observations
        )
        earlier = replace(
            query,
            end=imported_at - timedelta(microseconds=1),
            as_of=imported_at - timedelta(microseconds=1),
        )
        assert store.query(earlier) == ()
        paper_event = MonitoringEvent(
            context=MonitoringIdentity(scope="paper-strategy", mode="paper"),
            name="error<script>",
            version="1",
            sample="paper-error-1",
            at=imported_at,
            available_at=imported_at,
            recorded_at=imported_at,
            units="ratio",
            value=ExactRatio.from_fraction(Fraction(2, 3)),
        )
        paper_query = MonitoringQuery(
            scope="paper-strategy",
            mode="paper",
            start=imported_at,
            end=imported_at + timedelta(microseconds=1),
            as_of=imported_at + timedelta(microseconds=1),
        )
        paper_result = MetricRegistry((metric,)).evaluate(
            metric.spec.identity, paper_query, (paper_event,)
        )
        assert paper_result.value == ExactRatio.from_fraction(Fraction(2, 3))
        assert paper_result.spec.identity == report.metrics[0].definition.sha256

    def test_missing_values_and_bad_ledger_marks_are_explicit(self) -> None:
        """Withhold zero-capital returns and reject invented terminal NAV."""
        zero = LedgerState(
            initial_cash=Money(value=Decimal("0"), currency=self.currency),
            dimension=self.dimension,
        )
        window = TimeWindow(start=self.start, end=self.start + timedelta(hours=1))
        mark = Ledger(zero).mark(None)
        fold = FoldSummary(
            fold_id="zero",
            window=window,
            ledger=zero,
            terminal_mark=mark,
            curve=(LedgerPoint(at=window.end, mark=mark),),
        )
        result = NetReturnMetric().evaluate(ReportContext(study_identity="a" * 64, folds=(fold,)))
        assert result.value is None
        assert result.missing_reason == "at least one fold has zero initial cash"
        assert result.observations[0].missing_reason == "initial cash is zero"
        original = self._fold("first", 0)
        assert original.terminal_mark is not None
        forged = replace(
            original.terminal_mark,
            nav=Money(value=Decimal("1020"), currency=self.currency),
        )
        with pytest.raises(ValueError, match="reconcile"):
            replace(
                original,
                terminal_mark=forged,
                curve=(
                    original.curve[0],
                    original.curve[1],
                    original.curve[2],
                    LedgerPoint(at=original.window.end, mark=forged),
                ),
            )
        with pytest.raises(ValueError, match="reason"):
            ReportObservation(
                fold_id="first", name="missing", at=self.start, units="ratio", value=None
            )

    def test_unvalued_fold_withholds_returns_and_still_reports(self) -> None:
        """An open holding without a fresh terminal bid is reported, not valued."""
        reason = "no fresh terminal bid for an open holding"
        valued = self._fold("first", 0)
        held = self._fold("second", 3)
        unvalued = FoldSummary(
            fold_id=held.fold_id,
            window=held.window,
            ledger=held.ledger,
            terminal_mark=None,
            terminal_missing_reason=reason,
            curve=(
                *held.curve[:-1],
                LedgerPoint(at=held.window.end, mark=None, missing_reason=reason),
            ),
            diagnostics=held.diagnostics,
        )
        context = ReportContext(study_identity="a" * 64, folds=(valued, unvalued))
        result = NetReturnMetric().evaluate(context)
        assert result.value is None
        assert result.missing_reason == "at least one fold is unvalued"
        assert result.observations[0].value is not None
        assert result.observations[1].missing_reason == reason
        report = StudyReportBuilder.build(
            context,
            expected_metrics=(NetReturnMetric.identity,),
            expected_charts=(LedgerCurveChart.identity,),
            metrics=(NetReturnMetric(),),
            charts=(LedgerCurveChart(),),
        )
        assert b"at least one fold is unvalued" in report.render()
        with pytest.raises(ValueError, match="open holding and a reason"):
            replace(unvalued, terminal_missing_reason=None)
        valued_end = held.curve[-1]
        with pytest.raises(ValueError, match="terminal mark"):
            replace(unvalued, curve=(held.curve[0], valued_end))
        with pytest.raises(ValueError, match="cannot have a missing reason"):
            replace(valued, terminal_missing_reason=reason)
        flat = LedgerState(
            initial_cash=Money(value=Decimal("1000"), currency=self.currency),
            dimension=self.dimension,
        )
        with pytest.raises(ValueError, match="open holding and a reason"):
            FoldSummary(
                fold_id="flat",
                window=valued.window,
                ledger=flat,
                terminal_mark=None,
                terminal_missing_reason=reason,
                curve=(LedgerPoint(at=valued.window.end, mark=None, missing_reason=reason),),
            )
        with pytest.raises(ValueError, match="requires a reason"):
            TrialEvaluation(net_return=None)
        with pytest.raises(ValueError, match="cannot have a missing reason"):
            TrialEvaluation(
                net_return=ExactRatio.from_fraction(Fraction(1, 2)), missing_reason=reason
            )
        assert TrialEvaluation(net_return=None, missing_reason=reason).net_return is None

    def test_selected_definitions_cannot_be_replaced_or_omitted(self) -> None:
        """Require both implementation and evaluated output identities to match selection."""
        context = self._context()
        with pytest.raises(ValueError, match="exactly match"):
            StudyReportBuilder.build(
                context,
                expected_metrics=(NetReturnMetric.identity,),
                expected_charts=(LedgerCurveChart.identity,),
                metrics=(),
                charts=(LedgerCurveChart(),),
            )
        with pytest.raises(ValueError, match="metric implementation differs"):
            StudyReportBuilder.build(
                context,
                expected_metrics=(_ForecastErrorMetric.identity,),
                expected_charts=(LedgerCurveChart.identity,),
                metrics=(NetReturnMetric(),),
                charts=(LedgerCurveChart(),),
            )
        with pytest.raises(ValueError, match="replaced"):
            StudyReportBuilder.build(
                context,
                expected_metrics=(_ForecastErrorMetric.identity,),
                expected_charts=(LedgerCurveChart.identity,),
                metrics=(_SubstitutedMetric(),),
                charts=(LedgerCurveChart(),),
            )

    def test_chart_rejects_mixed_units_and_reordered_series(self) -> None:
        """A plotted series has one dimensional scale and increasing fold clocks."""
        chart = _ForecastChart().evaluate(self._context())
        with pytest.raises(ValueError, match="incompatible units"):
            replace(
                chart,
                observations=(
                    chart.observations[0],
                    replace(chart.observations[1], units="DIFFERENT"),
                ),
            )
        with pytest.raises(ValueError, match="series clocks"):
            replace(
                chart,
                observations=(chart.observations[0], chart.observations[0]),
            )

    def test_reader_requires_completed_matching_digest_verified_artifact(
        self, tmp_path: Path
    ) -> None:
        """Refuse interrupted, failed, cross-run and mutated committed report bytes."""
        root = tmp_path / "attempts"
        spec = self._spec()
        with AttemptStore(root) as writer:
            incomplete = writer.start(spec, at=self.start, invocation="report incomplete")
            report = self._report(self._context(spec.identity))
            writer.retain(incomplete.attempt_id, "study-report", DomainCodec().encode_json(report))
            with pytest.raises(ValueError, match="completed"):
                StudyReportReader.read(writer, incomplete.attempt_id)
            writer.finish(
                incomplete.attempt_id,
                status="failed",
                at=self.start + timedelta(seconds=1),
                reason="deliberate failure",
            )
            with pytest.raises(ValueError, match="completed"):
                StudyReportReader.read(writer, incomplete.attempt_id)
            completed = writer.start(spec, at=self.start, invocation="report completed")
            manifest = ResultManifest.retain(
                writer,
                completed.attempt_id,
                {"study-report": DomainCodec().encode_json(report), "html": report.render()},
            )
            writer.finish(
                completed.attempt_id,
                status="completed",
                at=self.start + timedelta(seconds=1),
                reason="verified report",
                result=DomainCodec().encode_json(manifest),
            )
        reader = AttemptStore(root)
        assert StudyReportReader.read(reader, completed.attempt_id) == report
        artifact = root / completed.attempt_id / "artifact-study-report.bin"
        artifact.chmod(0o600)
        artifact.write_bytes(b"mutated")
        with pytest.raises(ValueError, match="digest mismatch"):
            StudyReportReader.read(reader, completed.attempt_id)

    def test_reader_rejects_a_report_from_another_semantic_run(self, tmp_path: Path) -> None:
        """A verified artifact still has to match its enclosing attempt identity."""
        spec = self._spec()
        report = self._report(self._context("f" * 64))
        with AttemptStore(tmp_path / "attempts") as writer:
            start = writer.start(spec, at=self.start, invocation="wrong study report")
            manifest = ResultManifest.retain(
                writer, start.attempt_id, {"study-report": DomainCodec().encode_json(report)}
            )
            writer.finish(
                start.attempt_id,
                status="completed",
                at=self.start + timedelta(seconds=1),
                reason="wrong semantic identity",
                result=DomainCodec().encode_json(manifest),
            )
        with pytest.raises(ValueError, match="identity differs"):
            StudyReportReader.read(AttemptStore(tmp_path / "attempts"), start.attempt_id)
