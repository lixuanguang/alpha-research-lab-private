"""
tests.test_engine
~~~~~~~~~~~~~~~~~
Acceptance tests for ``lab.backtest.daily_engine``.

Criteria
--------
1. Runs end-to-end on toy data with deterministic output.
2. Output contains: pnl series, positions/weights, turnover, summary metrics dict.
3. Weights update only on rebalance dates.
4. ``returns = Σ(w[t-1] · r[t]) − costs[t]``.
5. If costs=0, net returns == gross returns.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lab.backtest.daily_engine import BacktestResult, run_daily_backtest
from lab.core.config import ExperimentConfig

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_config(**overrides) -> ExperimentConfig:
    """Create a minimal config for testing."""
    defaults = dict(
        exp="test",
        universe=("A", "B"),
        start_date="2020-01-01",
        end_date="2020-12-31",
        rebalance="monthly",
        signal=20,
        costs=0.0,
        initial_capital=1_000_000,
        strategy="test.equal_weight",
    )
    defaults.update(overrides)
    return ExperimentConfig(**defaults)


def _toy_prices(seed: int = 42) -> pd.DataFrame:
    """Deterministic 2-asset price panel: ~252 days of 2020."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-02", "2020-12-31")
    n = len(dates)
    # Cumulative random walk → prices
    log_ret = rng.normal(0.0003, 0.01, size=(n, 2))
    prices = 100 * np.exp(np.cumsum(log_ret, axis=0))
    return pd.DataFrame(prices, index=dates, columns=["A", "B"])


def _equal_weight_signal(config: ExperimentConfig, prices: pd.DataFrame) -> pd.Series:
    """Simple 50/50 equal-weight signal for testing."""
    return pd.Series(0.5, index=prices.columns)


# ── Core acceptance tests ────────────────────────────────────────────────────


class TestDailyEngine:
    """Acceptance: runs end-to-end on toy data with deterministic output."""

    @pytest.fixture()
    def result(self) -> BacktestResult:
        config = _make_config(costs=0.0)
        prices = _toy_prices(seed=42)
        return run_daily_backtest(config, prices, _equal_weight_signal)

    def test_returns_backtest_result(self, result: BacktestResult) -> None:
        assert isinstance(result, BacktestResult)

    def test_output_has_pnl_series(self, result: BacktestResult) -> None:
        """Output contains daily pnl (returns) series."""
        assert isinstance(result.returns, pd.Series)
        assert len(result.returns) > 0
        assert result.returns.name == "net_return"

    def test_output_has_gross_returns(self, result: BacktestResult) -> None:
        assert isinstance(result.gross_returns, pd.Series)
        assert len(result.gross_returns) > 0

    def test_output_has_weights(self, result: BacktestResult) -> None:
        """Output contains positions/weights over time."""
        assert isinstance(result.weights, pd.DataFrame)
        assert not result.weights.empty
        assert isinstance(result.weights_daily, pd.DataFrame)
        assert not result.weights_daily.empty

    def test_output_has_turnover(self, result: BacktestResult) -> None:
        """Output contains turnover over time."""
        assert isinstance(result.turnover, pd.Series)
        assert len(result.turnover) > 0

    def test_output_has_summary_metrics(self, result: BacktestResult) -> None:
        """Output contains a summary metrics dict."""
        assert isinstance(result.summary_metrics, dict)
        expected_keys = {"cagr", "ann_vol", "sharpe", "max_dd"}
        assert expected_keys.issubset(result.summary_metrics.keys())

    def test_deterministic(self) -> None:
        """Same inputs → same outputs (determinism)."""
        config = _make_config(costs=0.0)
        prices = _toy_prices(seed=42)
        r1 = run_daily_backtest(config, prices, _equal_weight_signal)
        r2 = run_daily_backtest(config, prices, _equal_weight_signal)
        pd.testing.assert_series_equal(r1.returns, r2.returns)

    def test_zero_costs_net_eq_gross(self) -> None:
        """If bps=0, net returns == gross returns."""
        config = _make_config(costs=0.0)
        prices = _toy_prices(seed=42)
        result = run_daily_backtest(config, prices, _equal_weight_signal)
        pd.testing.assert_series_equal(result.returns, result.gross_returns, check_names=False)

    def test_positive_costs_reduce_returns(self) -> None:
        """Positive costs → net returns ≤ gross returns on rebalance days."""
        config = _make_config(costs=50.0)  # 50 bps
        prices = _toy_prices(seed=42)
        result = run_daily_backtest(config, prices, _equal_weight_signal)
        # Net cumulative should be less than or equal to gross cumulative
        cum_net = (1 + result.returns).prod()
        cum_gross = (1 + result.gross_returns).prod()
        assert cum_net <= cum_gross

    def test_weights_update_only_on_rebalance(self) -> None:
        """Weights change only on rebalance dates, held constant between."""
        config = _make_config(rebalance="monthly", costs=0.0)
        prices = _toy_prices(seed=42)
        result = run_daily_backtest(config, prices, _equal_weight_signal)
        # Weight records should be much fewer than trading days
        n_trading_days = len(prices)
        n_weight_records = len(result.weights)
        assert n_weight_records < n_trading_days

    def test_empty_prices(self) -> None:
        """Engine handles empty DataFrame gracefully."""
        config = _make_config()
        prices = pd.DataFrame()
        result = run_daily_backtest(config, prices, _equal_weight_signal)
        assert len(result.returns) == 0
        assert result.weights.empty

    def test_short_history_no_crash(self) -> None:
        """Short histories should run (no warmup index crash)."""
        config = _make_config(rebalance="weekly", costs=0.0)
        dates = pd.bdate_range("2024-01-02", periods=50)
        prices = pd.DataFrame(
            {
                "A": 100 + np.linspace(0, 2, len(dates)),
                "B": 100 + np.linspace(0, 1, len(dates)),
            },
            index=dates,
        )
        result = run_daily_backtest(config, prices, _equal_weight_signal)
        assert len(result.returns) == len(prices)

    def test_rebalance_applies_next_day_not_same_day(self) -> None:
        """Signal computed on day t must not affect day t return."""
        config = _make_config(rebalance="daily", costs=0.0)
        dates = pd.bdate_range("2024-01-02", periods=40)

        # Alternate returns: +1%, -1%, +1%, ...
        alternating = np.where(np.arange(len(dates)) % 2 == 0, 0.01, -0.01)
        prices = pd.DataFrame(
            {"A": 100.0 * np.cumprod(1.0 + alternating)},
            index=dates,
        )

        def _same_day_sign_signal(_config: ExperimentConfig, p: pd.DataFrame) -> pd.Series:
            if len(p) < 2:
                return pd.Series({"A": 0.0})
            today_ret = p["A"].iloc[-1] / p["A"].iloc[-2] - 1.0
            return pd.Series({"A": 1.0 if today_ret >= 0 else -1.0})

        result = run_daily_backtest(config, prices, _same_day_sign_signal)
        active = result.returns[result.returns != 0]

        # With correct causality this strategy is anti-predictive on alternating returns.
        assert len(active) > 0
        assert (active <= 0).all()

    def test_weights_daily_are_causal_pre_return_positions(self) -> None:
        """Daily weights should represent holdings active for same-day return booking."""
        config = _make_config(rebalance="daily", costs=0.0)
        dates = pd.bdate_range("2024-01-02", periods=20)
        prices = pd.DataFrame(
            {
                "A": 100.0 * np.cumprod(np.full(len(dates), 1.001)),
                "B": 100.0 * np.cumprod(np.full(len(dates), 1.002)),
            },
            index=dates,
        )

        def _constant_signal(_config: ExperimentConfig, p: pd.DataFrame) -> pd.Series:
            return pd.Series(0.5, index=p.columns)

        result = run_daily_backtest(config, prices, _constant_signal)

        pd.testing.assert_index_equal(result.weights_daily.index, prices.index)
        assert (result.weights_daily.iloc[0] == 0.0).all()
        observed = result.weights_daily.iloc[1].reindex(["A", "B"])
        pd.testing.assert_series_equal(
            observed,
            pd.Series({"A": 0.5, "B": 0.5}),
            check_names=False,
        )
        assert (result.weights_daily.iloc[1:].sum(axis=1) == 1.0).all()

    def test_weekly_rebalance_with_missing_fridays(self) -> None:
        """Weekly schedules should still rebalance when Friday data is absent."""
        config = _make_config(rebalance="weekly", costs=0.0)

        all_days = pd.bdate_range("2024-01-02", periods=180)
        no_fridays = all_days[all_days.weekday != 4]
        prices = pd.DataFrame(
            {
                "A": 100 + np.linspace(0, 5, len(no_fridays)),
                "B": 100 + np.linspace(0, 3, len(no_fridays)),
            },
            index=no_fridays,
        )

        result = run_daily_backtest(config, prices, _equal_weight_signal)

        # Previously this degraded to coarse fallback frequency when W-FRI dates
        # were missing from the panel; a weekly-like cadence should produce many
        # more rebalance records over ~9 months.
        assert len(result.weights) >= 20

    def test_non_finite_signal_weights_are_sanitized(self) -> None:
        """NaN/inf signal outputs should be coerced to flat weights, not NaN PnL."""
        config = _make_config(rebalance="weekly", costs=0.0)
        dates = pd.bdate_range("2024-01-02", periods=80)
        prices = pd.DataFrame(
            {
                "A": 100 + np.linspace(0, 2, len(dates)),
                "B": 100 + np.linspace(0, 1, len(dates)),
            },
            index=dates,
        )

        def _bad_signal(_config: ExperimentConfig, _p: pd.DataFrame) -> pd.Series:
            return pd.Series({"A": np.nan, "B": np.inf})

        result = run_daily_backtest(config, prices, _bad_signal)

        assert np.isfinite(result.returns.to_numpy()).all()
        assert np.isfinite(result.gross_returns.to_numpy()).all()
        assert (result.weights.abs().sum(axis=1) == 0.0).all()

    def test_rejects_unsorted_price_index(self) -> None:
        config = _make_config(costs=0.0)
        prices = _toy_prices(seed=7).sort_index(ascending=False)
        with pytest.raises(ValueError, match="strictly increasing"):
            run_daily_backtest(config, prices, _equal_weight_signal)

    def test_rejects_non_positive_prices(self) -> None:
        config = _make_config(costs=0.0)
        prices = _toy_prices(seed=11)
        prices.iloc[5, 0] = 0.0
        with pytest.raises(ValueError, match="non-positive"):
            run_daily_backtest(config, prices, _equal_weight_signal)

    def test_rejects_negative_transaction_costs(self) -> None:
        config = _make_config(costs=-5.0)
        prices = _toy_prices(seed=42)
        with pytest.raises(ValueError, match="must be >= 0"):
            run_daily_backtest(config, prices, _equal_weight_signal)

    def test_rejects_non_finite_transaction_costs(self) -> None:
        config = _make_config(costs={"per_asset_bps": {"A": np.inf}})
        prices = _toy_prices(seed=42)
        with pytest.raises(ValueError, match="must be finite"):
            run_daily_backtest(config, prices, _equal_weight_signal)
