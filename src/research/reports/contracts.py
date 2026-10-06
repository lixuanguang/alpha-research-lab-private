"""Define the report contracts a candidate's metric and chart components read and return.

They are shared by research studies and the signed paper runtime, so they depend only
on modules both environments ship.
"""

from __future__ import annotations

# standard library imports
import html
from datetime import datetime, timedelta
from fractions import Fraction
from typing import Literal, Protocol

# project library imports
from accounting import Ledger, LedgerBalance, LedgerMark, LedgerState
from financial_units import ExactRatio
from research.experiments import Fingerprint, TimeWindow
from serialization import WireRecord


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
    terminal_mark: LedgerMark | None
    curve: tuple[LedgerPoint, ...]
    diagnostics: tuple[ReportObservation, ...] = ()
    terminal_missing_reason: str | None = None

    def __post_init__(self) -> None:
        """Reject forged terminal economics, unordered marks and mislabeled diagnostics."""
        if type(self.fold_id) is not str or not self.fold_id.strip():
            raise ValueError("fold summary requires a fold identity")
        if type(self.window) is not TimeWindow or type(self.ledger) is not LedgerState:
            raise TypeError("fold summary requires a window and exact ledger state")
        self.window.__post_init__()
        balance = Ledger(self.ledger).balance
        if self.terminal_mark is None:
            # Only an open holding can lack a terminal valuation, and it must say why.
            if (
                not balance.holding.value
                or type(self.terminal_missing_reason) is not str
                or not self.terminal_missing_reason.strip()
            ):
                raise ValueError("an unvalued fold requires an open holding and a reason")
        elif self.terminal_missing_reason is not None:
            raise ValueError("a valued fold cannot have a missing reason")
        elif type(self.terminal_mark) is not LedgerMark:
            raise TypeError("fold summary requires an exact terminal mark")
        else:
            self.terminal_mark.__post_init__()
            self._check_terminal_mark(balance, self.terminal_mark)
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
        last = self.curve[-1]
        if (
            last.at != self.window.end
            or last.mark != self.terminal_mark
            or (self.terminal_mark is None and last.missing_reason != self.terminal_missing_reason)
        ):
            raise ValueError("ledger curve must end with the reconciled terminal mark")
        if type(self.diagnostics) is not tuple:
            raise TypeError("fold diagnostics must be immutable")
        for observation in self.diagnostics:
            if type(observation) is not ReportObservation:
                raise TypeError("fold diagnostics require report observations")
            observation.__post_init__()
            if observation.fold_id != self.fold_id or not self.window.contains(observation.at):
                raise ValueError("fold diagnostic is outside its decision window")

    def _check_terminal_mark(self, posted: LedgerBalance, mark: LedgerMark) -> None:
        """Reconcile a supplied mark against the replayed posted state without a price guess."""
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
