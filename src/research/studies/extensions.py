"""Evaluate selected study metrics and charts from exact, retained ledger evidence."""

from __future__ import annotations

# standard library imports
import hashlib
import html
from fractions import Fraction
from typing import Literal

# project library imports
from financial_units import ExactRatio
from research.experiments import AttemptStore, Fingerprint
from research.reports import (
    ChartDefinition,
    ChartSpec,
    MetricDefinition,
    MetricValue,
    ReportContext,
    ReportObservation,
)
from research.studies.results import ResultManifest
from serialization import DomainCodec, WireRecord


class StudyReport(WireRecord, frozen=True, kw_only=True):
    """Preserve selected extension identities beside their exact report output."""

    study_identity: str
    fold_ids: tuple[str, ...]
    selected_metrics: tuple[Fingerprint, ...]
    selected_charts: tuple[Fingerprint, ...]
    metrics: tuple[MetricValue, ...]
    charts: tuple[ChartSpec, ...]
    limitations: tuple[str, ...] = ()
    schema_version: Literal["study-report"] = "study-report"

    def __post_init__(self) -> None:
        """Reject any report that replaced, omitted or duplicated selected outputs."""
        if self.schema_version != "study-report":
            raise ValueError("unsupported study report schema")
        Fingerprint(name="study", sha256=self.study_identity)
        if (
            type(self.fold_ids) is not tuple
            or not self.fold_ids
            or any(type(fold_id) is not str or not fold_id.strip() for fold_id in self.fold_ids)
            or len(set(self.fold_ids)) != len(self.fold_ids)
        ):
            raise ValueError("report requires distinct fold identities")
        for selected, produced, kind in (
            (self.selected_metrics, self.metrics, MetricValue),
            (self.selected_charts, self.charts, ChartSpec),
        ):
            if type(selected) is not tuple or type(produced) is not tuple or not selected:
                raise ValueError("study report requires selected metric and chart outputs")
            if len(selected) != len(produced):
                raise ValueError("selected report definitions and outputs differ")
            for identity, output in zip(selected, produced, strict=True):
                if type(identity) is not Fingerprint or type(output) is not kind:
                    raise TypeError("report output requires typed definition and value")
                identity.__post_init__()
                output.__post_init__()
                if identity != output.definition:
                    raise ValueError("report output replaced a selected definition")
            if len({item.name for item in selected}) != len(selected):
                raise ValueError("duplicate selected report definition name")
        fold_ids = set(self.fold_ids)
        for metric in self.metrics:
            if any(observation.fold_id not in fold_ids for observation in metric.observations):
                raise ValueError("metric observation references an unknown fold")
        for chart in self.charts:
            if any(observation.fold_id not in fold_ids for observation in chart.observations):
                raise ValueError("chart observation references an unknown fold")
        if type(self.limitations) is not tuple or any(
            type(item) is not str or not item.strip() for item in self.limitations
        ):
            raise ValueError("report limitations must be authored text")

    def render(self) -> bytes:
        """Render escaped, deterministic, dependency-free HTML with exact values visible."""
        self.__post_init__()
        parts = [
            '<!doctype html><html lang="en"><head><meta charset="utf-8">',
            "<title>Study report</title><style>body{font:16px system-ui;max-width:72rem;",
            "margin:2rem auto;padding:0 1rem;color:#18212b}table{border-collapse:collapse;",
            "width:100%;margin:1rem 0 2rem}th,td{border:1px solid #c6d1dc;padding:.45rem;",
            "text-align:left}th{background:#eef3f8}code{overflow-wrap:anywhere}</style></head><body>",
            "<h1>Study report</h1>",
            f"<p>Study identity: <code>{html.escape(self.study_identity)}</code></p>",
            "<h2>Metrics</h2><table><thead><tr><th>Metric</th><th>Version</th>",
            "<th>Value</th><th>Units</th><th>Reason</th></tr></thead><tbody>",
        ]
        for metric in self.metrics:
            value = self._display(metric.value)
            parts.append(
                "<tr>"
                f"<td>{html.escape(metric.name)}</td>"
                f"<td><code>{html.escape(metric.version)}</code></td>"
                f"<td>{html.escape(value)}</td>"
                f"<td>{html.escape(metric.units)}</td>"
                f"<td>{html.escape(metric.missing_reason or '')}</td>"
                "</tr>"
            )
        parts.append("</tbody></table><h2>Charts and exact series</h2>")
        for chart in self.charts:
            parts.append(
                f"<section><h3>{html.escape(chart.title)}</h3>"
                f"<p>Type: {html.escape(chart.kind)}; data: "
                f"{html.escape(', '.join(chart.data_references))}</p>"
            )
            parts.append(chart.render_svg())
            parts.append(
                "<table><thead><tr><th>Fold</th><th>Clock (UTC)</th><th>Series</th>"
                "<th>Value</th><th>Units</th><th>Reason</th></tr></thead><tbody>"
            )
            for observation in chart.observations:
                parts.append(self._observation_row(observation))
            parts.append("</tbody></table></section>")
        parts.append("<h2>Metric observations</h2><table><thead><tr><th>Fold</th>")
        parts.append(
            "<th>Clock (UTC)</th><th>Series</th><th>Value</th><th>Units</th>"
            "<th>Reason</th></tr></thead><tbody>"
        )
        for metric in self.metrics:
            for observation in metric.observations:
                parts.append(self._observation_row(observation))
        parts.append("</tbody></table>")
        if self.limitations:
            parts.append("<h2>Limitations</h2><ul>")
            parts.extend(f"<li>{html.escape(item)}</li>" for item in self.limitations)
            parts.append("</ul>")
        parts.append("</body></html>")
        return "".join(parts).encode("utf-8")

    @staticmethod
    def _display(value: ExactRatio | None) -> str:
        """Show exact rational values without a binary float projection."""
        return "missing" if value is None else f"{value.numerator}/{value.denominator}"

    @classmethod
    def _observation_row(cls, observation: ReportObservation) -> str:
        """Escape all extension-supplied labels and reasons before HTML assembly."""
        values = (
            observation.fold_id,
            observation.at.isoformat(),
            observation.name,
            cls._display(observation.value),
            observation.units,
            observation.missing_reason or "",
        )
        return "<tr>" + "".join(f"<td>{html.escape(value)}</td>" for value in values) + "</tr>"


class StudyReportBuilder:
    """Evaluate only implementations whose identities exactly match study selections."""

    @staticmethod
    def build(
        context: ReportContext,
        *,
        expected_metrics: tuple[Fingerprint, ...],
        expected_charts: tuple[Fingerprint, ...],
        metrics: tuple[MetricDefinition, ...],
        charts: tuple[ChartDefinition, ...],
        limitations: tuple[str, ...] = (),
    ) -> StudyReport:
        """Create a report without substituting defaults for missing custom definitions."""
        if type(context) is not ReportContext:
            raise TypeError("report builder requires a typed report context")
        context.__post_init__()
        if (
            type(expected_metrics) is not tuple
            or type(expected_charts) is not tuple
            or type(metrics) is not tuple
            or type(charts) is not tuple
            or not expected_metrics
            or not expected_charts
            or len(expected_metrics) != len(metrics)
            or len(expected_charts) != len(charts)
        ):
            raise ValueError("report definitions must exactly match selected identities")
        for selected in (expected_metrics, expected_charts):
            if any(type(item) is not Fingerprint for item in selected):
                raise TypeError("report selections require fingerprints")
            if len({item.name for item in selected}) != len(selected):
                raise ValueError("duplicate selected report definition")
            for expected in selected:
                expected.__post_init__()
        for expected, metric_definition in zip(expected_metrics, metrics, strict=True):
            if metric_definition.identity != expected:
                raise ValueError("metric implementation differs from selected identity")
        for expected, chart_definition in zip(expected_charts, charts, strict=True):
            if chart_definition.identity != expected:
                raise ValueError("chart implementation differs from selected identity")
        metric_values = tuple(metric_definition.evaluate(context) for metric_definition in metrics)
        chart_specs = tuple(chart_definition.evaluate(context) for chart_definition in charts)
        return StudyReport(
            study_identity=context.study_identity,
            fold_ids=tuple(fold.fold_id for fold in context.folds),
            selected_metrics=expected_metrics,
            selected_charts=expected_charts,
            metrics=metric_values,
            charts=chart_specs,
            limitations=limitations,
        )


class StudyReportReader:
    """Open only a completed attempt's digest-verified typed study report."""

    @staticmethod
    def read(store: AttemptStore, attempt_id: str) -> StudyReport:
        """Refuse incomplete, failed, absent, tampered or cross-run report artifacts."""
        manifest = ResultManifest.read(store, attempt_id)
        if "study-report" not in {artifact.name for artifact in manifest.artifacts}:
            raise ValueError("completed result lacks a study-report artifact")
        report = DomainCodec().decode_json(store.artifact(attempt_id, "study-report"), StudyReport)
        report.__post_init__()
        if report.study_identity != store.read(attempt_id).start.run_identity:
            raise ValueError("study report identity differs from completed attempt")
        return report


class NetReturnMetric:
    """Compute cash-weighted exact net return across compatible independent folds."""

    identity = Fingerprint(
        name="net-return",
        sha256=hashlib.sha256(b"research.studies.NetReturnMetric/v1").hexdigest(),
    )

    def evaluate(self, context: ReportContext) -> MetricValue:
        """Keep per-fold returns and withhold an aggregate when capital or units conflict."""
        observations: list[ReportObservation] = []
        total_initial = Fraction(0)
        total_net = Fraction(0)
        currencies: set[str] = set()
        for fold in context.folds:
            initial = Fraction(fold.ledger.initial_cash.value)
            net = Fraction(fold.terminal_mark.net.value)
            currencies.add(fold.ledger.initial_cash.currency.code)
            observations.append(
                ReportObservation(
                    fold_id=fold.fold_id,
                    name="net-return",
                    at=fold.window.end,
                    units="ratio",
                    value=ExactRatio.from_fraction(net / initial) if initial > 0 else None,
                    missing_reason=None if initial > 0 else "initial cash is zero",
                )
            )
            total_initial += initial
            total_net += net
        reason = None
        if len(currencies) != 1:
            reason = "fold quote currencies differ"
        elif any(observation.value is None for observation in observations):
            reason = "at least one fold has zero initial cash"
        return MetricValue(
            definition=self.identity,
            name="Net return",
            version="1",
            units="ratio",
            value=None
            if reason is not None
            else ExactRatio.from_fraction(total_net / total_initial),
            missing_reason=reason,
            observations=tuple(observations),
        )


class LedgerCurveChart:
    """Describe every available and missing sampled NAV as exact chart observations."""

    identity = Fingerprint(
        name="ledger-curve",
        sha256=hashlib.sha256(b"research.studies.LedgerCurveChart/v1").hexdigest(),
    )

    def evaluate(self, context: ReportContext) -> ChartSpec:
        """Keep all sampled fold marks with their original currencies and missing reasons."""
        observations: list[ReportObservation] = []
        references: list[str] = []
        for fold in context.folds:
            currency = fold.ledger.initial_cash.currency.code
            name = f"net-asset-value ({currency})"
            if name not in references:
                references.append(name)
            for point in fold.curve:
                observations.append(
                    ReportObservation(
                        fold_id=fold.fold_id,
                        name=name,
                        at=point.at,
                        units=currency,
                        value=None
                        if point.mark is None
                        else ExactRatio.from_fraction(Fraction(point.mark.nav.value)),
                        missing_reason=point.missing_reason,
                    )
                )
        return ChartSpec(
            definition=self.identity,
            title="Sampled net asset value",
            kind="line",
            data_references=tuple(references),
            observations=tuple(observations),
        )
