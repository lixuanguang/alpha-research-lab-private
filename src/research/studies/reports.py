"""Project retained exact economics into bounded, explicitly sampled research reports."""

from __future__ import annotations

# standard library imports
import hashlib
import html
import math
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from importlib.metadata import version

# project library imports
from financial_units import ExactRatio
from serialization import DomainCodec, WireRecord
from simulation import EconomicResult


class BenchmarkPeriod(WireRecord, frozen=True):
    """Bind an explicitly supplied simple return to its UTC period end."""

    end: datetime
    value: ExactRatio

    def __post_init__(self) -> None:
        """Reject unsupported clocks, approximate values and returns below total loss."""
        self._require_utc(self.end, field_name="benchmark end")
        if type(self.value) is not ExactRatio:
            raise TypeError("benchmark requires an exact simple return")
        self.value.__post_init__()
        if Fraction(int(self.value.numerator), int(self.value.denominator)) < -1:
            raise ValueError("benchmark return cannot be below -1")


class ReportPolicy(WireRecord, frozen=True):
    """Declare aligned reporting assumptions and up to 8,192 supplied benchmark periods.

    No data is downloaded or dates aligned implicitly.
    """

    benchmark_name: str
    benchmark: tuple[BenchmarkPeriod, ...]
    cadence_seconds: int
    periods_per_year: int
    annual_risk_free: ExactRatio
    timezone: str = "UTC"
    return_convention: str = "simple-net-nav"
    missing_policy: str = "preserve-and-withhold-aggregates"
    schema_version: str = "economic-report-policy"

    def __post_init__(self) -> None:
        """Require immutable aligned observations and explicitly bounded assumptions."""
        if (
            self.schema_version != "economic-report-policy"
            or self.timezone != "UTC"
            or self.return_convention != "simple-net-nav"
            or self.missing_policy != "preserve-and-withhold-aggregates"
            or type(self.benchmark_name) is not str
            or not self.benchmark_name.strip()
            or type(self.cadence_seconds) is not int
            or self.cadence_seconds <= 0
            or type(self.periods_per_year) is not int
            or not 1 <= self.periods_per_year <= 31_622_400
        ):
            raise ValueError("unsupported report policy")
        if type(self.benchmark) is not tuple or not 1 <= len(self.benchmark) <= 8192:
            raise ValueError("report benchmark must be an immutable tuple of 1 to 8192 periods")
        if type(self.annual_risk_free) is not ExactRatio:
            raise TypeError("risk-free assumption requires an exact ratio")
        self.annual_risk_free.__post_init__()
        previous: datetime | None = None
        for period in self.benchmark:
            if type(period) is not BenchmarkPeriod:
                raise TypeError("benchmark requires typed periods")
            period.__post_init__()
            if previous is not None and period.end - previous != timedelta(
                seconds=self.cadence_seconds
            ):
                raise ValueError("benchmark cadence is incomplete or unordered")
            previous = period.end


class ReportPeriod(WireRecord, frozen=True):
    """Preserve each sampled valuation, missing return and observed quality reason."""

    end: datetime
    net_return: ExactRatio | None
    exposure: ExactRatio | None
    reasons: tuple[str, ...]


class EconomicReport(WireRecord, frozen=True):
    """Retain exact inputs beside analytical QuantStats projections and clear limitations."""

    result_sha256: str
    policy: ReportPolicy
    periods: tuple[ReportPeriod, ...]
    net_return: ExactRatio | None
    turnover_over_initial_cash: ExactRatio | None
    quantstats_return: float | None
    quantstats_drawdown: float | None
    benchmark_return: float | None
    sampled_max_exposure: ExactRatio | None
    winning_periods: int
    losing_periods: int
    flat_periods: int
    limitations: tuple[str, ...]
    quantstats_version: str
    currency: str
    initial_cash: str
    terminal_nav: str
    fees: str
    adverse_slippage: str
    net_profit: str
    schema_version: str = "economic-report"


class QuantStatsReport:
    """Keep approximate reporting downstream of the authoritative reconciled ledger."""

    @staticmethod
    def build(result: EconomicResult, policy: ReportPolicy) -> EconomicReport:
        """Extract costed period returns without filling missing valuations or fetching data.

        Args:
            result: Completed exact economic trace, including original quality limitations.
            policy: Explicit benchmark observations and cadence/annualization assumptions.

        Returns:
            Retainable report; aggregate sampled metrics are absent for incomplete coverage.

        Raises:
            ValueError: Benchmark clocks differ, results are invalid, or projections diverge.
        """
        codec = DomainCodec()
        result = codec.decode_json(codec.encode_json(result), EconomicResult)
        policy = codec.decode_json(codec.encode_json(policy), ReportPolicy)
        spec = result.spec
        cadence = timedelta(seconds=policy.cadence_seconds)
        if policy.cadence_seconds != spec.cadence_seconds or (spec.end - spec.start) % cadence:
            raise ValueError("report requires complete declared economic cadence periods")
        ends = tuple(
            spec.start + cadence * i for i in range(1, (spec.end - spec.start) // cadence + 1)
        )
        if tuple(period.end for period in policy.benchmark) != ends:
            raise ValueError("benchmark must exactly align with economic period ends")
        marks = {
            event.at: event for event in result.checkpoint.state.trace if event.phase == "mark"
        }
        initial = Fraction(spec.initial_cash.value)
        previous: Fraction | None = initial
        periods: list[ReportPeriod] = []
        for end in ends:
            event = marks.get(end)
            nav = None if event is None or event.mark is None else Fraction(event.mark.nav.value)
            value = None if previous is None or previous <= 0 or nav is None else nav / previous - 1
            exposure = None
            if event is not None and nav is not None and nav > 0:
                exposure = ExactRatio.from_fraction(
                    (nav - Fraction(event.balance.cash.value)) / nav
                )
            reasons = tuple(
                sorted(
                    {
                        trace.reason
                        for trace in result.checkpoint.state.trace
                        if end - cadence < trace.at <= end
                        and (
                            (trace.reason != "valued" and trace.phase == "mark")
                            or (trace.observation is not None and trace.observation.point is None)
                        )
                    }
                )
            )
            periods.append(
                ReportPeriod(
                    end=end,
                    net_return=None if value is None else ExactRatio.from_fraction(value),
                    exposure=exposure,
                    reasons=reasons,
                )
            )
            previous = nav
        values = tuple(
            QuantStatsReport._fraction(p.net_return) for p in periods if p.net_return is not None
        )
        complete = len(values) == len(periods)
        net = None if initial <= 0 else Fraction(result.terminal.nav.value) / initial - 1
        compounded: float | None = None
        drawdown: float | None = None
        benchmark: float | None = None
        maximum: ExactRatio | None = None
        if complete:
            compounded, drawdown = QuantStatsReport.project(values)
            benchmark, _ = QuantStatsReport.project(
                tuple(QuantStatsReport._fraction(p.value) for p in policy.benchmark)
            )
            if net is None:
                raise ValueError("QuantStats return disagrees with exact retained economics")
            QuantStatsReport.require_agreement(compounded, values, net)
            exposures = tuple(
                QuantStatsReport._fraction(p.exposure) for p in periods if p.exposure is not None
            )
            if len(exposures) == len(periods):
                maximum = ExactRatio.from_fraction(max(exposures))
        return EconomicReport(
            result_sha256=hashlib.sha256(codec.encode_json(result)).hexdigest(),
            policy=policy,
            periods=tuple(periods),
            net_return=None if net is None else ExactRatio.from_fraction(net),
            turnover_over_initial_cash=None
            if initial <= 0
            else ExactRatio.from_fraction(
                Fraction(result.checkpoint.state.trace[-1].balance.turnover.value) / initial
            ),
            quantstats_return=compounded,
            quantstats_drawdown=drawdown,
            benchmark_return=benchmark,
            sampled_max_exposure=maximum,
            winning_periods=sum(value > 0 for value in values),
            losing_periods=sum(value < 0 for value in values),
            flat_periods=sum(value == 0 for value in values),
            limitations=(
                *result.limitations,
                "Drawdown/exposure describe sampled marks, not intraperiod extrema.",
                "Win/loss counts are valuation periods, not trades; missing periods are excluded.",
                "No annualized performance claim from this bounded sample; risk-free is metadata.",
                "QuantStats uses float projections; exact ledger reconciliation is unchanged.",
            ),
            quantstats_version=version("quantstats"),
            currency=spec.initial_cash.currency.code,
            initial_cash=str(spec.initial_cash.value),
            terminal_nav=str(result.terminal.nav.value),
            fees=str(result.checkpoint.state.trace[-1].balance.fees.value),
            adverse_slippage=str(result.checkpoint.state.trace[-1].balance.slippage.value),
            net_profit=str(result.terminal.net.value),
        )

    @staticmethod
    def require_agreement(compounded: float, values: tuple[Fraction, ...], net: Fraction) -> None:
        """Refuse a projected compound return outside its float error bound from the exact net.

        ``project`` multiplies float64 factors ``1 + float(r)``. Each factor rounds
        once converting ``r`` (relative error ``u * |r| / (1 + r)``, which grows near
        a total loss) and once adding one, and each product rounds once more. With
        unit roundoff ``u = 2**-53`` and ``k`` such roundings, the product lies
        within ``gamma(k) = k*u / (1 - k*u)`` of exact (Higham, Accuracy and
        Stability of Numerical Algorithms, 2nd ed., section 3.1). Subtracting one
        and converting ``net`` add ``u`` times each magnitude. The bound is doubled
        as margin. It grows with the period count, whereas a fixed tolerance
        rejects long correct runs. A total loss is an exact zero factor, so it
        must agree exactly.

        Args:
            compounded: ``project``'s float compound return for ``values``.
            values: The exact simple period returns that were projected.
            net: Exact net return from the reconciled retained economics.

        Raises:
            ValueError: The projection differs from the exact economics.
        """
        unit = 2.0**-53
        if any(value == -1 for value in values):
            bound = 0.0
        else:
            roundings = len(values) + sum(
                2.0 + abs(float(value)) / float(1 + value) for value in values
            )
            if roundings * unit >= 1:
                raise ValueError("QuantStats projection has no meaningful float error bound")
            gamma = roundings * unit / (1 - roundings * unit)
            bound = 2 * (float(1 + net) * gamma + unit * (abs(float(net)) + abs(compounded)))
        if not abs(compounded - float(net)) <= bound:
            raise ValueError("QuantStats return disagrees with exact retained economics")

    @staticmethod
    def project(values: tuple[Fraction, ...]) -> tuple[float, float]:
        """Compute bounded compound return and drawdown with an explicit initial NAV anchor.

        Args:
            values: Complete simple net returns in period order, with no missing values.

        Returns:
            Analytical compound return and signed maximum drawdown.

        Raises:
            ValueError: The sequence or upstream output is invalid or nonfinite.
        """
        # third party library imports
        import pandas as pd
        from quantstats import stats

        if not values or any(type(value) is not Fraction or value < -1 for value in values):
            raise ValueError("report projection requires exact complete simple returns")
        series = pd.Series([0.0, *(float(value) for value in values)], dtype="float64")
        compounded = float(stats.comp(series))
        # Explicit wealth avoids QuantStats' price/return heuristic for large simple returns.
        wealth = [1.0]
        for value in values:
            wealth.append(wealth[-1] * (1 + float(value)))
        index = [datetime(2000, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(len(wealth))]
        drawdown = float(stats.max_drawdown(pd.Series(wealth, index=index, dtype="float64")))
        if not math.isfinite(compounded) or not math.isfinite(drawdown):
            raise ValueError("report projection produced nonfinite values")
        return compounded, drawdown

    @staticmethod
    def render(report: EconomicReport) -> bytes:
        """Render a deterministic self-contained HTML view of the retained report.

        Args:
            report: Typed reporting result, including exact inputs and limitations.

        Returns:
            UTF-8 HTML bytes with escaped content and no external resources.
        """
        metrics = {
            f"Initial cash ({report.currency})": report.initial_cash,
            f"Terminal NAV ({report.currency})": report.terminal_nav,
            f"Net P&L ({report.currency})": report.net_profit,
            f"Fees ({report.currency})": report.fees,
            f"Adverse slippage ({report.currency})": report.adverse_slippage,
            "Exact net return": QuantStatsReport._display(report.net_return),
            "Turnover / initial cash": QuantStatsReport._display(report.turnover_over_initial_cash),
            "QuantStats compound return": str(report.quantstats_return),
            "Sampled maximum drawdown": str(report.quantstats_drawdown),
            "Sampled maximum exposure / NAV": QuantStatsReport._display(
                report.sampled_max_exposure
            ),
            "Aligned benchmark return": str(report.benchmark_return),
        }
        rows = "".join(
            f"<tr><th>{html.escape(name)}</th><td>{html.escape(value)}</td></tr>"
            for name, value in metrics.items()
        )
        periods = "".join(
            f"<tr><td>{period.end.isoformat()}</td>"
            f"<td>{QuantStatsReport._display(period.net_return)}</td>"
            f"<td>{QuantStatsReport._display(period.exposure)}</td>"
            f"<td>{html.escape(', '.join(period.reasons))}</td></tr>"
            for period in report.periods
        )
        limitations = "".join(f"<li>{html.escape(reason)}</li>" for reason in report.limitations)
        assumptions = html.escape(DomainCodec().encode_json(report.policy).decode())
        return (
            '<!doctype html><html lang="en"><meta charset="utf-8">'
            "<title>Costed economic research report</title><style>"
            "body{max-width:72rem;margin:3rem auto;font:16px system-ui;line-height:1.5}"
            "pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f5f7;padding:1rem}"
            "table{border-collapse:collapse;width:100%}"
            "th,td{text-align:left;padding:.5rem;border-bottom:1px solid #ddd}"
            "</style><h1>Costed economic research report</h1>"
            "<p>Exact economics with bounded QuantStats projections. "
            "Period win/loss counts are not trade statistics.</p>"
            f"<p>Exact ledger: {report.result_sha256}. QuantStats {report.quantstats_version}.</p>"
            f"<table>{rows}</table><p>Winning / losing / flat observed periods: "
            f"{report.winning_periods} / {report.losing_periods} / {report.flat_periods}. "
            f"Missing return periods: {sum(p.net_return is None for p in report.periods)}.</p>"
            "<h2>Period observations</h2><p>Returns and exposure are exact reduced ratios; "
            "unavailable values remain missing. Exposure is marked holdings divided by NAV.</p>"
            "<table><tr><th>UTC period end</th><th>Net return</th>"
            "<th>Exposure / NAV</th><th>Quality</th></tr>"
            f"{periods}</table><h2>Limits</h2><ul>{limitations}</ul>"
            f"<h2>Explicit benchmark and assumptions</h2><pre>{assumptions}</pre></html>"
        ).encode()

    @staticmethod
    def _display(value: ExactRatio | None) -> str:
        """Display exact ratios without inventing values for missing observations."""
        return "Unavailable" if value is None else f"{value.numerator}/{value.denominator}"

    @staticmethod
    def _fraction(value: ExactRatio) -> Fraction:
        """Read a validated canonical ratio without decimal or float arithmetic."""
        return Fraction(int(value.numerator), int(value.denominator))
