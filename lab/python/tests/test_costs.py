"""
tests.test_costs
~~~~~~~~~~~~~~~~
Acceptance tests for ``lab.costs.daily``.

Criteria
--------
1. Cost increases with turnover.
2. If ``bps=0``, result matches pre-cost (i.e. cost == 0).
3. ``apply_costs(w_new, w_old, bps)`` returns a scalar cost in return-space.
4. ``estimate_turnover`` is symmetric and non-negative.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lab.costs.daily import apply_costs, apply_linear_costs, estimate_turnover

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def tickers() -> list[str]:
    return ["A", "B", "C"]


@pytest.fixture()
def w_old(tickers: list[str]) -> pd.Series:
    return pd.Series([0.4, 0.3, 0.3], index=tickers)


@pytest.fixture()
def w_new(tickers: list[str]) -> pd.Series:
    return pd.Series([0.2, 0.5, 0.3], index=tickers)


# ── estimate_turnover ────────────────────────────────────────────────────────


class TestEstimateTurnover:
    def test_nonnegative(self, w_old: pd.Series, w_new: pd.Series) -> None:
        assert estimate_turnover(w_old, w_new) >= 0.0

    def test_symmetric(self, w_old: pd.Series, w_new: pd.Series) -> None:
        assert estimate_turnover(w_old, w_new) == pytest.approx(estimate_turnover(w_new, w_old))

    def test_zero_when_identical(self, w_old: pd.Series) -> None:
        assert estimate_turnover(w_old, w_old) == pytest.approx(0.0)

    def test_value_known(self, w_old: pd.Series, w_new: pd.Series) -> None:
        # Δ = |−0.2| + |+0.2| + |0| = 0.4;  turnover = 0.4 / 2 = 0.2
        assert estimate_turnover(w_old, w_new) == pytest.approx(0.2)


# ── apply_costs ──────────────────────────────────────────────────────────────


class TestApplyCosts:
    def test_returns_scalar(self, w_old: pd.Series, w_new: pd.Series) -> None:
        cost = apply_costs(w_new, w_old, bps=10.0)
        assert isinstance(cost, float)

    def test_zero_bps_zero_cost(self, w_old: pd.Series, w_new: pd.Series) -> None:
        """If bps=0, cost is exactly zero → pre-cost == post-cost."""
        assert apply_costs(w_new, w_old, bps=0.0) == pytest.approx(0.0)

    def test_cost_increases_with_turnover(self, tickers: list[str]) -> None:
        """Higher turnover → higher cost at the same bps."""
        w_prev = pd.Series([0.5, 0.3, 0.2], index=tickers)
        w_small_change = pd.Series([0.48, 0.32, 0.20], index=tickers)
        w_big_change = pd.Series([0.1, 0.6, 0.3], index=tickers)

        cost_small = apply_costs(w_small_change, w_prev, bps=10.0)
        cost_big = apply_costs(w_big_change, w_prev, bps=10.0)
        assert cost_big > cost_small

    def test_cost_increases_with_bps(self, w_old: pd.Series, w_new: pd.Series) -> None:
        """Higher bps → higher cost for the same trade."""
        cost_5 = apply_costs(w_new, w_old, bps=5.0)
        cost_20 = apply_costs(w_new, w_old, bps=20.0)
        assert cost_20 > cost_5

    def test_known_value(self, w_old: pd.Series, w_new: pd.Series) -> None:
        """turnover=0.2, bps=10 → cost = 0.2 * 10/10000 = 0.0002."""
        assert apply_costs(w_new, w_old, bps=10.0) == pytest.approx(0.0002)

    def test_no_trade_zero_cost(self, w_old: pd.Series) -> None:
        """No change in weights → zero cost regardless of bps."""
        assert apply_costs(w_old, w_old, bps=100.0) == pytest.approx(0.0)


# ── apply_linear_costs (vectorised) ─────────────────────────────────────────


class TestApplyLinearCosts:
    def test_zero_bps_matches_gross(self) -> None:
        dates = pd.bdate_range("2020-01-01", periods=10)
        gross = pd.Series(np.random.default_rng(0).normal(0, 0.01, 10), index=dates)
        turnover = pd.Series(0.1, index=dates)  # non-zero turnover
        net = apply_linear_costs(gross, turnover, cost_bps=0.0)
        pd.testing.assert_series_equal(net, gross)

    def test_positive_bps_reduces_returns(self) -> None:
        dates = pd.bdate_range("2020-01-01", periods=10)
        gross = pd.Series(0.001, index=dates)  # constant positive return
        turnover = pd.Series(0.1, index=dates)
        net = apply_linear_costs(gross, turnover, cost_bps=10.0)
        assert (net < gross).all()

    def test_cost_proportional_to_turnover(self) -> None:
        dates = pd.bdate_range("2020-01-01", periods=5)
        gross = pd.Series(0.001, index=dates)
        to_lo = pd.Series(0.05, index=dates)
        to_hi = pd.Series(0.20, index=dates)
        net_lo = apply_linear_costs(gross, to_lo, cost_bps=10.0)
        net_hi = apply_linear_costs(gross, to_hi, cost_bps=10.0)
        # Higher turnover → lower net return
        assert (net_lo > net_hi).all()
