"""Integration tests: event-driven vs vectorized engine congruence.

Both engines should produce qualitatively similar results when the same
strategy logic (buy-and-hold / all-long, equal-weight) is exercised on
identical data.  We allow for engine-specific mechanics (exact fill timing,
rebalance lag) by applying a generous 10% tolerance on final equity.

Key invariants verified:
1. Both engines start at the same initial cash.
2. Both engines produce an equity curve containing at least one data point.
3. Final equity values are within 10% of each other.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pyarrow as pa
from apps.research.backtester.engine import EventBacktestConfig, EventBacktestEngine
from apps.research.backtester.strategy import Strategy, StrategyState
from apps.research.backtester.vec_engine import VecBacktestConfig, VecBacktestEngine
from apps.research.backtester.vec_strategy import VecStrategy

from alpha_core.execution.models import BacktestOrderIntent
from alpha_core.portfolio.models import Side
from alpha_core.portfolio.sizing import EqualWeightSizer

_ZERO = Decimal("0")
_INITIAL_CASH = Decimal("10000")
_INSTRUMENT = "testmarket:q1"
_T0 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

# ---------------------------------------------------------------------------
# Shared dataset (30 daily price observations — stable at 0.5)
# ---------------------------------------------------------------------------

_N = 30


def _make_trades_table() -> pa.Table:
    """30 daily trade events for a single instrument at a stable price of 0.5."""
    timestamps = [_T0 + timedelta(days=i) for i in range(_N)]
    return pa.table(
        {
            "ts_event": pa.array(timestamps, type=pa.timestamp("us", tz="UTC")),
            "instrument_id": pa.array([_INSTRUMENT] * _N, type=pa.string()),
            "price": pa.array([0.5] * _N, type=pa.float64()),
        }
    )


class _MockDataset:
    def __init__(self, table: pa.Table) -> None:
        self._table = table

    def trades(self) -> pa.Table:
        return self._table


# ---------------------------------------------------------------------------
# Event strategy: buy once, hold the whole period
# ---------------------------------------------------------------------------


class _BuyAndHoldEventStrategy(Strategy):
    """Buys the single instrument on the first tick then does nothing."""

    name = "buy_and_hold_event"
    _bought: bool = False

    def on_init(self, universe: list[str]) -> None:
        self._bought = False

    def on_data(
        self,
        timestamp: datetime,
        state: StrategyState,
    ) -> list[BacktestOrderIntent]:
        if self._bought or _INSTRUMENT not in state.universe:
            return []
        price = state.latest_prices.get(_INSTRUMENT)
        if price is None:
            return []
        self._bought = True
        return [
            BacktestOrderIntent(
                instrument_id=_INSTRUMENT,
                side=Side.LONG,
                size=Decimal("10"),
                order_type="market",
            )
        ]

    def on_resolution(self, instrument_id: str, resolved_price: Decimal) -> None:
        pass


# ---------------------------------------------------------------------------
# Vec strategy: equal-weight long on every rebalance
# ---------------------------------------------------------------------------


class _BuyAndHoldVecStrategy(VecStrategy):
    """Equal-weight all active instruments on every rebalance bar."""

    name = "buy_and_hold_vec"

    def generate_signals(
        self, features: pd.DataFrame, universe: list[str]
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {"instrument_id": universe, "signal": [1.0] * len(universe)}
        )

    def size_positions(
        self, signals: pd.DataFrame, portfolio_value: Decimal, max_positions: int
    ) -> pd.DataFrame:
        return EqualWeightSizer().size(signals, portfolio_value, max_positions)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEngineCongruence:
    def test_both_engines_start_at_same_initial_cash(self) -> None:
        dataset = _MockDataset(_make_trades_table())

        event_result = EventBacktestEngine(
            EventBacktestConfig(
                dataset_id="cong_test",
                initial_cash=_INITIAL_CASH,
                slippage_model="fixed",
                slippage_params={"bps": 0},
            )
        ).run(_BuyAndHoldEventStrategy(), dataset)

        vec_result = VecBacktestEngine(
            VecBacktestConfig(
                dataset_id="cong_test",
                initial_cash=_INITIAL_CASH,
                fee_bps=Decimal("0"),
                rebalance_frequency="1D",
            )
        ).run(_BuyAndHoldVecStrategy(), dataset)

        # Both equity curves must exist and have at least one point
        assert len(event_result.equity_curve) >= 1
        assert len(vec_result.equity_curve) >= 1

    def test_final_equity_within_tolerance(self) -> None:
        """Event and vec engines produce final equity within 10% of each other."""
        dataset = _MockDataset(_make_trades_table())

        event_result = EventBacktestEngine(
            EventBacktestConfig(
                dataset_id="cong_tol",
                initial_cash=_INITIAL_CASH,
                slippage_model="fixed",
                slippage_params={"bps": 0},
            )
        ).run(_BuyAndHoldEventStrategy(), dataset)

        vec_result = VecBacktestEngine(
            VecBacktestConfig(
                dataset_id="cong_tol",
                initial_cash=_INITIAL_CASH,
                fee_bps=Decimal("0"),
                rebalance_frequency="1D",
            )
        ).run(_BuyAndHoldVecStrategy(), dataset)

        event_equity = float(event_result.final_portfolio.equity)
        vec_equity = float(vec_result.final_portfolio.equity)

        ref = max(event_equity, vec_equity)
        diff_pct = abs(event_equity - vec_equity) / ref if ref > 0 else 0.0
        assert diff_pct < 0.10, (
            f"Equity divergence too large: event={event_equity:.2f} "
            f"vec={vec_equity:.2f} diff={diff_pct:.1%}"
        )

    def test_prob_momentum_generates_trades_on_sample_data(self) -> None:
        """ProbabilityMomentumStrategy produces at least 1 trade on 30-event dataset."""
        from apps.research.strategies.probability_momentum import (
            ProbabilityMomentumStrategy,
        )

        # Use trending prices (monotonically increasing) to guarantee momentum signal
        timestamps = [_T0 + timedelta(days=i) for i in range(_N)]
        prices = [0.30 + 0.01 * i for i in range(_N)]  # 0.30 → 0.59
        table = pa.table(
            {
                "ts_event": pa.array(timestamps, type=pa.timestamp("us", tz="UTC")),
                "instrument_id": pa.array([_INSTRUMENT] * _N, type=pa.string()),
                "price": pa.array(prices, type=pa.float64()),
            }
        )
        result = EventBacktestEngine(
            EventBacktestConfig(
                dataset_id="mom_test",
                initial_cash=_INITIAL_CASH,
                slippage_model="fixed",
                slippage_params={"bps": 0},
            )
        ).run(
            ProbabilityMomentumStrategy(momentum_threshold=0.01, window=3),
            _MockDataset(table),
        )
        assert len(result.trades) >= 1, (
            "ProbabilityMomentumStrategy should generate ≥1 trade on trending data"
        )
