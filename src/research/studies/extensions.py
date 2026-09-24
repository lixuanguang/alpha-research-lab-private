"""Evaluate selected study metrics and charts from exact, retained ledger evidence."""

from __future__ import annotations

# standard library imports
import hashlib
import html
from datetime import datetime, timedelta
from fractions import Fraction
from typing import Literal, Protocol

# project library imports
from accounting import Ledger, LedgerBalance, LedgerMark, LedgerState
from financial_units import ExactRatio
from research.experiments import AttemptStore, Fingerprint, TimeWindow
from research.studies.results import ResultManifest
from serialization import DomainCodec, WireRecord


class ReportObservation(WireRecord, frozen=True, kw_only=True):
    """Keep one exact series value or an explicit missing value at its UTC clock."""

    fold_id: str
    name: str
    at: datetime
    units: str
    value: ExactRatio | None
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        """Require a named, dimensioned observation with unambiguous missingness."""
        for value in (self.fold_id, self.name, self.units):
            if type(value) is not str or not value.strip():
                raise ValueError("report observation requires fold, name and units")
        self._require_utc(self.at, field_name="report observation clock")
        if self.value is None:
            if type(self.missing_reason) is not str or not self.missing_reason.strip():
                raise ValueError("missing report observation requires a reason")
        elif self.missing_reason is not None:
            raise ValueError("present report observation cannot have a missing reason")
        elif type(self.value) is not ExactRatio:
            raise TypeError("report observation requires an exact ratio")
        else:
            self.value.__post_init__()


class LedgerPoint(WireRecord, frozen=True, kw_only=True):
    """Retain a sampled mark, preserving a failed or unavailable valuation."""

    at: datetime
    mark: LedgerMark | None
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        """Keep each curve clock UTC and missing marks explained."""
        self._require_utc(self.at, field_name="ledger point clock")
        if self.mark is None:
            if type(self.missing_reason) is not str or not self.missing_reason.strip():
                raise ValueError("missing ledger mark requires a reason")
        elif self.missing_reason is not None:
            raise ValueError("present ledger mark cannot have a missing reason")
        elif type(self.mark) is not LedgerMark:
            raise TypeError("ledger point requires a reconciled mark")
        else:
            self.mark.__post_init__()


class FoldSummary(WireRecord, frozen=True, kw_only=True):
    """Bind one evaluation window to its posted ledger and sampled mark history."""

    fold_id: str
    window: TimeWindow
    ledger: LedgerState
    terminal_mark: LedgerMark
    curve: tuple[LedgerPoint, ...]
    diagnostics: tuple[ReportObservation, ...] = ()

    def __post_init__(self) -> None:
        """Reject forged terminal economics, unordered marks and mislabeled diagnostics."""
        if type(self.fold_id) is not str or not self.fold_id.strip():
            raise ValueError("fold summary requires a fold identity")
        if type(self.window) is not TimeWindow or type(self.ledger) is not LedgerState:
            raise TypeError("fold summary requires a window and exact ledger state")
        self.window.__post_init__()
        balance = Ledger(self.ledger).balance
        if type(self.terminal_mark) is not LedgerMark:
            raise TypeError("fold summary requires an exact terminal mark")
        self.terminal_mark.__post_init__()
        self._check_terminal_mark(balance)
        if type(self.curve) is not tuple or not self.curve:
            raise ValueError("fold summary requires a terminal ledger curve")
        previous: datetime | None = None
        for point in self.curve:
            if type(point) is not LedgerPoint:
                raise TypeError("fold curve requires ledger points")
            point.__post_init__()
            if not self.window.start <= point.at <= self.window.end or (
                previous is not None and point.at <= previous
            ):
                raise ValueError("ledger curve must have ordered points within the fold")
            if point.mark is not None and point.mark.nav.currency != balance.cash.currency:
                raise ValueError("ledger curve currency differs from fold currency")
            previous = point.at
        if self.curve[-1].at != self.window.end or self.curve[-1].mark != self.terminal_mark:
            raise ValueError("ledger curve must end with the reconciled terminal mark")
        if type(self.diagnostics) is not tuple:
            raise TypeError("fold diagnostics must be immutable")
        for observation in self.diagnostics:
            if type(observation) is not ReportObservation:
                raise TypeError("fold diagnostics require report observations")
            observation.__post_init__()
            if observation.fold_id != self.fold_id or not self.window.contains(observation.at):
                raise ValueError("fold diagnostic is outside its decision window")

    def _check_terminal_mark(self, posted: LedgerBalance) -> None:
        """Reconcile a supplied mark against the replayed posted state without a price guess."""
        mark = self.terminal_mark
        currency = self.ledger.initial_cash.currency
        if mark.nav.currency != currency:
            raise ValueError("terminal mark currency differs from fold currency")
        market_value = Fraction(mark.nav.value) - Fraction(posted.cash.value)
        net = Fraction(mark.net.value)
        if (posted.holding.value == 0 and market_value != 0) or (
            posted.holding.value > 0 and market_value <= 0
        ):
            raise ValueError("terminal mark valuation disagrees with posted holdings")
        if (
            net != Fraction(mark.nav.value) - Fraction(self.ledger.initial_cash.value)
            or mark.unrealized.value != market_value - posted.basis.value
            or mark.gross.value
            != posted.reference_realized.value + market_value - posted.reference_basis.value
            or posted.realized.value + mark.unrealized.value - Fraction(posted.fees.value) != net
            or mark.gross.value - Fraction(posted.slippage.value) - Fraction(posted.fees.value)
            != net
        ):
            raise ValueError("terminal mark does not reconcile with posted ledger")


class ReportContext(WireRecord, frozen=True, kw_only=True):
    """Supply selected report extensions with authoritative fold economics."""

    study_identity: str
    folds: tuple[FoldSummary, ...]

    def __post_init__(self) -> None:
        """Require a bounded, distinct set of validated folds for one semantic run."""
        Fingerprint(name="study", sha256=self.study_identity)
        if type(self.folds) is not tuple or not 1 <= len(self.folds) <= 64:
            raise ValueError("report context requires one to 64 immutable folds")
        for fold in self.folds:
            if type(fold) is not FoldSummary:
                raise TypeError("report context requires fold summaries")
            fold.__post_init__()
        if len({fold.fold_id for fold in self.folds}) != len(self.folds):
            raise ValueError("duplicate report fold identity")


class MetricValue(WireRecord, frozen=True, kw_only=True):
    """Retain a selected metric's exact value, units and per-fold evidence."""

    definition: Fingerprint
    name: str
    version: str
    units: str
    value: ExactRatio | None
    missing_reason: str | None = None
    observations: tuple[ReportObservation, ...] = ()

    def __post_init__(self) -> None:
        """Validate the metric identity, exact result and its observed series."""
        if type(self.definition) is not Fingerprint:
            raise TypeError("metric requires a selected definition")
        self.definition.__post_init__()
        for value in (self.name, self.version, self.units):
            if type(value) is not str or not value.strip():
                raise ValueError("metric requires a name, version and units")
        if self.value is None:
            if type(self.missing_reason) is not str or not self.missing_reason.strip():
                raise ValueError("missing metric requires a reason")
        elif self.missing_reason is not None:
            raise ValueError("present metric cannot have a missing reason")
        elif type(self.value) is not ExactRatio:
            raise TypeError("metric requires an exact ratio")
        else:
            self.value.__post_init__()
        if type(self.observations) is not tuple:
            raise TypeError("metric observations must be immutable")
        for observation in self.observations:
            if type(observation) is not ReportObservation:
                raise TypeError("metric requires report observations")
            observation.__post_init__()
            if observation.units != self.units:
                raise ValueError("metric observation units differ from metric units")


class ChartSpec(WireRecord, frozen=True, kw_only=True):
    """Refer to exact named series for a self-contained line, bar or table view."""

    definition: Fingerprint
    title: str
    kind: Literal["line", "bar", "table"]
    data_references: tuple[str, ...]
    observations: tuple[ReportObservation, ...]

    def __post_init__(self) -> None:
        """Reject unresolved series, ambiguous chart kind and untyped plotted data."""
        if type(self.definition) is not Fingerprint:
            raise TypeError("chart requires a selected definition")
        self.definition.__post_init__()
        if type(self.title) is not str or not self.title.strip():
            raise ValueError("chart requires a title")
        if self.kind not in ("line", "bar", "table"):
            raise ValueError("unsupported study chart kind")
        if type(self.data_references) is not tuple or not 1 <= len(self.data_references) <= 16:
            raise ValueError("chart requires named data references")
        if type(self.observations) is not tuple or not 1 <= len(self.observations) <= 4096:
            raise ValueError("chart requires exact observations")
        names: set[str] = set()
        for name in self.data_references:
            if type(name) is not str or not name.strip() or name in names:
                raise ValueError("chart data references must be unique names")
            names.add(name)
        seen: set[str] = set()
        units: set[str] = set()
        previous_clocks: dict[tuple[str, str], datetime] = {}
        for observation in self.observations:
            if type(observation) is not ReportObservation:
                raise TypeError("chart requires report observations")
            observation.__post_init__()
            if observation.name not in names:
                raise ValueError("chart observation is not referenced")
            seen.add(observation.name)
            units.add(observation.units)
            series_key = observation.fold_id, observation.name
            previous = previous_clocks.get(series_key)
            if previous is not None and observation.at <= previous:
                raise ValueError("chart series clocks must increase within each fold")
            previous_clocks[series_key] = observation.at
        if seen != names:
            raise ValueError("chart references have no observations")
        if len(units) != 1:
            raise ValueError("chart cannot combine incompatible units")

    def render_svg(self) -> str:
        """Project exact observations into bounded, static SVG; tables retain exact values."""
        self.__post_init__()
        if self.kind == "table":
            return ""
        present = tuple(
            observation for observation in self.observations if observation.value is not None
        )
        if not present:
            return "<p>No plottable values; see missing reasons below.</p>"
        values = tuple(
            Fraction(int(observation.value.numerator), int(observation.value.denominator))
            for observation in present
            if observation.value is not None
        )
        low = min(values)
        high = max(values)
        if self.kind == "bar":
            low = min(low, Fraction(0))
            high = max(high, Fraction(0))
        colors = ("#1b6b9b", "#b45024", "#4a7a39", "#8155a7", "#9b394b", "#267e76")
        parts = [
            '<svg viewBox="0 0 760 230" role="img" '
            'aria-label="Approximate chart projection; exact values follow in the table" '
            'xmlns="http://www.w3.org/2000/svg">',
            '<rect x="0" y="0" width="760" height="230" fill="#fff"/>',
            '<line x1="45" y1="195" x2="740" y2="195" stroke="#8393a4"/>',
            '<line x1="45" y1="15" x2="45" y2="195" stroke="#8393a4"/>',
        ]
        if self.kind == "line":
            groups: dict[tuple[str, str], list[ReportObservation]] = {}
            for observation in self.observations:
                groups.setdefault((observation.fold_id, observation.name), []).append(observation)
            first_at = min(observation.at for observation in self.observations)
            last_at = max(observation.at for observation in self.observations)
            total_us = self._microseconds(last_at - first_at)
            for index, ((fold_id, name), observations) in enumerate(groups.items()):
                color = colors[index % len(colors)]
                segment: list[str] = []
                for observation in observations:
                    if observation.value is None:
                        parts.extend(self._line_segment(segment, color, fold_id, name))
                        segment = []
                        continue
                    value = Fraction(
                        int(observation.value.numerator),
                        int(observation.value.denominator),
                    )
                    elapsed_us = self._microseconds(observation.at - first_at)
                    x = 395.0 if total_us == 0 else 45 + 695 * float(Fraction(elapsed_us, total_us))
                    y = self._chart_y(value, low, high)
                    segment.append(f"{x:.2f},{y:.2f}")
                parts.extend(self._line_segment(segment, color, fold_id, name))
        else:
            baseline = self._chart_y(Fraction(0), low, high)
            step = 695 / len(self.observations)
            bar_width = min(48.0, step * 0.75)
            for index, observation in enumerate(self.observations):
                if observation.value is None:
                    continue
                value = Fraction(
                    int(observation.value.numerator), int(observation.value.denominator)
                )
                x = 45 + step * (index + 0.5) - bar_width / 2
                y = self._chart_y(value, low, high)
                top = min(y, baseline)
                height = max(abs(y - baseline), 1.0)
                color = colors[self.data_references.index(observation.name) % len(colors)]
                label = html.escape(
                    f"{observation.fold_id}: {observation.name} at "
                    f"{observation.at.isoformat()} = "
                    f"{observation.value.numerator}/{observation.value.denominator} "
                    f"{observation.units}"
                )
                parts.append(
                    f'<rect x="{x:.2f}" y="{top:.2f}" width="{bar_width:.2f}" '
                    f'height="{height:.2f}" fill="{color}"><title>{label}</title></rect>'
                )
        parts.append("</svg>")
        return "".join(parts)

    @staticmethod
    def _microseconds(delta: timedelta) -> int:
        """Convert a datetime difference to an exact nonnegative microsecond offset."""
        return ((delta.days * 86_400 + delta.seconds) * 1_000_000) + delta.microseconds

    @staticmethod
    def _chart_y(value: Fraction, low: Fraction, high: Fraction) -> float:
        """Limit SVG projection to the fixed plotting area without float overflow."""
        return 105.0 if high == low else 15 + 180 * float((high - value) / (high - low))

    @staticmethod
    def _line_segment(points: list[str], color: str, fold_id: str, name: str) -> list[str]:
        """Draw a connected run only until a missing observation breaks the line."""
        if not points:
            return []
        label = html.escape(f"{fold_id}: {name}")
        if len(points) == 1:
            x, y = points[0].split(",", maxsplit=1)
            return [
                f'<circle cx="{x}" cy="{y}" r="3" fill="{color}"><title>{label}</title></circle>'
            ]
        return [
            f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" '
            f'stroke-width="2"><title>{label}</title></polyline>'
        ]


class MetricDefinition(Protocol):
    """Evaluate an explicitly selected versioned metric from exact fold evidence."""

    @property
    def identity(self) -> Fingerprint:
        """Identify the implementation selected by study configuration."""
        ...

    def evaluate(self, context: ReportContext) -> MetricValue:
        """Return an exact metric or its authored inapplicability reason."""
        ...


class ChartDefinition(Protocol):
    """Build a versioned chart specification from exact fold evidence."""

    @property
    def identity(self) -> Fingerprint:
        """Identify the implementation selected by study configuration."""
        ...

    def evaluate(self, context: ReportContext) -> ChartSpec:
        """Return a validated chart with exact observations."""
        ...


class StudyReport(WireRecord, frozen=True, kw_only=True):
    """Preserve selected extension identities beside their exact report output."""

    study_identity: str
    fold_ids: tuple[str, ...]
    selected_metrics: tuple[Fingerprint, ...]
    selected_charts: tuple[Fingerprint, ...]
    metrics: tuple[MetricValue, ...]
    charts: tuple[ChartSpec, ...]
    limitations: tuple[str, ...] = ()
    schema_version: Literal["study-report-v1"] = "study-report-v1"

    def __post_init__(self) -> None:
        """Reject any report that replaced, omitted or duplicated selected outputs."""
        if self.schema_version != "study-report-v1":
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
