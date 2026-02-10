"""
test_eval.py
~~~~~~~~~~~~
Acceptance tests for the eval module: metrics, plots, and reports.

Covers:
- §5.1  metrics  — cumulative_return, avg_turnover, total_costs in summary()
- §5.2  plots    — turnover_plot returns Figure; ≥3 figures total
- §5.3  reports  — markdown_report embeds figure filenames + provenance
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────────

_DATES = pd.bdate_range("2020-01-02", periods=504, freq="B")


@pytest.fixture()
def daily_returns() -> pd.Series:
    """Synthetic daily returns (≈2 years)."""
    rng = np.random.default_rng(42)
    return pd.Series(rng.normal(0.0003, 0.01, len(_DATES)), index=_DATES, name="returns")


@pytest.fixture()
def gross_returns(daily_returns: pd.Series) -> pd.Series:
    """Gross returns = net + small positive cost drag each day."""
    rng = np.random.default_rng(99)
    cost_drag = pd.Series(rng.uniform(0.0, 0.0002, len(daily_returns)), index=daily_returns.index)
    return daily_returns + cost_drag


@pytest.fixture()
def turnover_series() -> pd.Series:
    """Turnover series with monthly spikes, 0 elsewhere."""
    t = pd.Series(0.0, index=_DATES)
    # every ~21 business days mark a rebalance
    rebal_idx = t.index[::21]
    rng = np.random.default_rng(7)
    t.loc[rebal_idx] = rng.uniform(0.05, 0.30, len(rebal_idx))
    return t


# ═══════════════════════════════════════════════════════════════════════════════
# §5.1  METRICS
# ═══════════════════════════════════════════════════════════════════════════════


class TestCumulativeReturn:
    def test_positive(self, daily_returns: pd.Series) -> None:
        from lab.eval.metrics import cumulative_return

        cr = cumulative_return(daily_returns)
        assert isinstance(cr, float)
        # synthetic returns have slight positive drift → cum return > 0
        assert cr > 0

    def test_zero_returns(self) -> None:
        from lab.eval.metrics import cumulative_return

        zeros = pd.Series(0.0, index=_DATES[:10])
        assert cumulative_return(zeros) == pytest.approx(0.0)


class TestAverageTurnover:
    def test_basic(self, turnover_series: pd.Series) -> None:
        from lab.eval.metrics import average_turnover

        avg = average_turnover(turnover_series)
        assert isinstance(avg, float)
        assert 0.05 <= avg <= 0.30  # within the uniform range we seeded

    def test_zero_turnover(self) -> None:
        from lab.eval.metrics import average_turnover

        zeros = pd.Series(0.0, index=_DATES[:100])
        assert average_turnover(zeros) == 0.0


class TestTotalCostsPaid:
    def test_positive_costs(self, daily_returns: pd.Series, gross_returns: pd.Series) -> None:
        from lab.eval.metrics import total_costs_paid

        tc = total_costs_paid(gross_returns, daily_returns)
        assert isinstance(tc, float)
        # gross > net → costs are positive
        assert tc > 0

    def test_zero_costs_when_equal(self, daily_returns: pd.Series) -> None:
        from lab.eval.metrics import total_costs_paid

        tc = total_costs_paid(daily_returns, daily_returns)
        assert tc == pytest.approx(0.0)


class TestSummaryWithOperationalMetrics:
    def test_summary_baseline(self, daily_returns: pd.Series) -> None:
        """summary() without turnover/gross should still work (backward compat)."""
        from lab.eval.metrics import summary

        s = summary(daily_returns)
        assert "cagr" in s
        assert "cumulative_return" in s
        # No operational keys when not supplied
        assert "avg_turnover" not in s
        assert "total_costs" not in s

    def test_summary_with_turnover(
        self, daily_returns: pd.Series, turnover_series: pd.Series
    ) -> None:
        from lab.eval.metrics import summary

        s = summary(daily_returns, turnover=turnover_series)
        assert "avg_turnover" in s
        assert s["avg_turnover"] > 0
        # total_costs not added without gross_returns
        assert "total_costs" not in s

    def test_summary_with_all(
        self,
        daily_returns: pd.Series,
        gross_returns: pd.Series,
        turnover_series: pd.Series,
    ) -> None:
        from lab.eval.metrics import summary

        s = summary(daily_returns, turnover=turnover_series, gross_returns=gross_returns)
        assert "cumulative_return" in s
        assert "avg_turnover" in s
        assert "total_costs" in s
        assert s["total_costs"] > 0

    def test_summary_has_all_required_keys(self, daily_returns: pd.Series) -> None:
        from lab.eval.metrics import summary

        s = summary(daily_returns)
        required = {
            "cumulative_return",
            "cagr",
            "ann_vol",
            "sharpe",
            "sortino",
            "max_dd",
            "calmar",
            "hit_rate",
            "profit_factor",
            "tail_ratio",
        }
        assert required.issubset(set(s.keys()))

    def test_summary_handles_all_positive_returns_without_non_finite_values(self) -> None:
        from lab.eval.metrics import summary

        r = pd.Series(0.001, index=_DATES[:80], dtype=float)
        s = summary(r)
        assert np.isfinite(np.array(list(s.values()), dtype=float)).all()

    def test_summary_handles_empty_returns(self) -> None:
        from lab.eval.metrics import summary

        s = summary(pd.Series(dtype=float))
        assert np.isfinite(np.array(list(s.values()), dtype=float)).all()
        assert s["cumulative_return"] == pytest.approx(0.0)


# ═══════════════════════════════════════════════════════════════════════════════
# §5.2  PLOTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestPlots:
    def test_cumulative_returns_figure(self, daily_returns: pd.Series) -> None:
        from matplotlib.figure import Figure

        from lab.eval.plots import cumulative_returns

        fig = cumulative_returns(daily_returns)
        assert isinstance(fig, Figure)

    def test_drawdown_figure(self, daily_returns: pd.Series) -> None:
        from matplotlib.figure import Figure

        from lab.eval.plots import drawdown

        fig = drawdown(daily_returns)
        assert isinstance(fig, Figure)

    def test_turnover_plot_figure(self, turnover_series: pd.Series) -> None:
        from matplotlib.figure import Figure

        from lab.eval.plots import turnover_plot

        fig = turnover_plot(turnover_series)
        assert isinstance(fig, Figure)

    def test_at_least_three_plot_functions(self) -> None:
        """eval.plots exports ≥ 3 figure-generating functions."""
        from lab.eval import plots

        public = [a for a in dir(plots) if not a.startswith("_") and callable(getattr(plots, a))]
        # cumulative_returns, drawdown, rolling_sharpe, turnover_plot
        assert len(public) >= 3

    def test_turnover_plot_savefig(self, turnover_series: pd.Series, tmp_path) -> None:
        from lab.eval.plots import turnover_plot

        fig = turnover_plot(turnover_series)
        path = tmp_path / "turnover.png"
        fig.savefig(path)
        assert path.exists()
        assert path.stat().st_size > 0


# ═══════════════════════════════════════════════════════════════════════════════
# §5.3  REPORTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestMarkdownReport:
    def test_basic_from_returns(self, daily_returns: pd.Series) -> None:
        from lab.eval.reports import markdown_report

        md = markdown_report("test_exp", returns=daily_returns)
        assert "# test_exp" in md
        assert "| sharpe |" in md

    def test_from_prebuilt_metrics(self) -> None:
        from lab.eval.reports import markdown_report

        metrics = {"cagr": 0.12, "sharpe": 1.5, "max_dd": -0.15}
        md = markdown_report("pre", metrics=metrics)
        assert "| cagr |" in md
        assert "| sharpe |" in md

    def test_figure_filenames_embedded(self, daily_returns: pd.Series) -> None:
        from lab.eval.reports import markdown_report

        figs = ["figures/cumulative_returns.png", "figures/drawdown.png", "figures/turnover.png"]
        md = markdown_report("exp", returns=daily_returns, figure_filenames=figs)
        for f in figs:
            assert f in md
        # Should have section headings for each figure
        assert "## Cumulative Returns" in md
        assert "## Drawdown" in md
        assert "## Turnover" in md

    def test_provenance_section(self, daily_returns: pd.Series) -> None:
        from lab.eval.reports import markdown_report

        meta = {
            "config_hash": "abc123",
            "git_commit": "def456",
            "start_time": "now",
            "platform": "mac",
        }
        md = markdown_report("exp", returns=daily_returns, meta=meta)
        assert "## Provenance" in md
        assert "abc123" in md
        assert "def456" in md

    def test_operational_metrics_in_report(
        self,
        daily_returns: pd.Series,
        gross_returns: pd.Series,
        turnover_series: pd.Series,
    ) -> None:
        from lab.eval.reports import markdown_report

        md = markdown_report(
            "exp",
            returns=daily_returns,
            turnover=turnover_series,
            gross_returns=gross_returns,
        )
        assert "avg_turnover" in md
        assert "total_costs" in md

    def test_requires_either_returns_or_metrics(self) -> None:
        from lab.eval.reports import markdown_report

        with pytest.raises(ValueError, match=r"returns.*metrics"):
            markdown_report("nope")


class TestSaveReport:
    def test_writes_file(self, daily_returns: pd.Series, tmp_path) -> None:
        from lab.eval.reports import save_report

        path = save_report("exp", returns=daily_returns, output_dir=tmp_path)
        assert path.exists()
        assert path.name == "report.md"
        content = path.read_text()
        assert "# exp" in content

    def test_save_with_figures(self, daily_returns: pd.Series, tmp_path) -> None:
        from lab.eval.reports import save_report

        figs = ["figures/cumulative_returns.png", "figures/turnover.png"]
        path = save_report("exp", returns=daily_returns, output_dir=tmp_path, figure_filenames=figs)
        content = path.read_text()
        assert "figures/cumulative_returns.png" in content
        assert "figures/turnover.png" in content


class TestMetricsTable:
    def test_returns_dataframe(self, daily_returns: pd.Series) -> None:
        from lab.eval.reports import metrics_table

        df = metrics_table(daily_returns)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1
        assert "cumulative_return" in df.columns

    def test_with_turnover(self, daily_returns: pd.Series, turnover_series: pd.Series) -> None:
        from lab.eval.reports import metrics_table

        df = metrics_table(daily_returns, turnover=turnover_series)
        assert "avg_turnover" in df.columns


# ═══════════════════════════════════════════════════════════════════════════════
# §5  EXPORTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestExports:
    def test_new_symbols_in_all(self) -> None:
        import lab.eval

        for name in ("average_turnover", "total_costs_paid", "cumulative_return", "turnover_plot"):
            assert name in lab.eval.__all__, f"{name} missing from lab.eval.__all__"
            assert hasattr(lab.eval, name), f"{name} not importable from lab.eval"
