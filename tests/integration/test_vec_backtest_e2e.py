"""Integration tests for the vectorized backtest engine end-to-end.

These tests exercise the full path from dataset → VecBacktestEngine → BacktestResult
without mocking internal components.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import apps.research.backtester.result as result_mod
import apps.research.backtester.vec_engine as vec_engine_mod
import apps.research.backtester.vec_strategy as vec_strategy_mod
import pandas as pd
import pyarrow as pa

from alpha_core.portfolio.sizing import EqualWeightSizer

_ZERO = Decimal("0")
_T0 = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
_T1 = datetime(2024, 1, 2, 12, 0, tzinfo=UTC)
_T2 = datetime(2024, 1, 3, 12, 0, tzinfo=UTC)
_T3 = datetime(2024, 1, 4, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ts_range(start: datetime, n: int) -> list[datetime]:
    return [start + timedelta(days=i) for i in range(n)]


def _make_trades_table(
    timestamps: list[datetime],
    instruments: list[str],
    price: float = 0.5,
) -> pa.Table:
    rows = [(ts, inst, price) for ts, inst in zip(timestamps, instruments)]
    return pa.table(
        {
            "ts_event": pa.array([r[0] for r in rows], type=pa.timestamp("us", tz="UTC")),
            "instrument_id": pa.array([r[1] for r in rows], type=pa.string()),
            "price": pa.array([r[2] for r in rows], type=pa.float64()),
        }
    )


class _MockDataset:
    def __init__(self, table: pa.Table) -> None:
        self._table = table

    def trades(self) -> pa.Table:
        return self._table


class _BuyAndHoldStrategy(vec_strategy_mod.VecStrategy):
    """Buys all instruments equally on every rebalance bar."""

    name = "buy_and_hold_vec"

    def generate_signals(
        self,
        features: pd.DataFrame,
        universe: list[str],
    ) -> pd.DataFrame:
        del features
        return pd.DataFrame({"instrument_id": universe, "signal": [1.0] * len(universe)})

    def size_positions(
        self,
        signals: pd.DataFrame,
        portfolio_value: Decimal,
        max_positions: int,
    ) -> pd.DataFrame:
        return EqualWeightSizer().size(signals, portfolio_value, max_positions)


class _FlatStrategy(vec_strategy_mod.VecStrategy):
    """Never takes positions."""

    name = "flat_vec"

    def generate_signals(
        self,
        features: pd.DataFrame,
        universe: list[str],
    ) -> pd.DataFrame:
        del features
        return pd.DataFrame({"instrument_id": universe, "signal": [0.0] * len(universe)})

    def size_positions(
        self,
        signals: pd.DataFrame,
        portfolio_value: Decimal,
        max_positions: int,
    ) -> pd.DataFrame:
        del signals, portfolio_value, max_positions
        return pd.DataFrame({"instrument_id": [], "target_weight": []})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestVecBacktestE2E:
    def test_full_run_returns_backtest_result(self) -> None:
        """A complete engine run produces a valid BacktestResult."""
        ts = _ts_range(_T0, 4)
        table = _make_trades_table(ts, ["a", "a", "b", "b"], price=0.5)
        config = vec_engine_mod.VecBacktestConfig(
            dataset_id="e2e_test",
            initial_cash=Decimal("1000"),
        )
        result = vec_engine_mod.VecBacktestEngine(config).run(
            _BuyAndHoldStrategy(), _MockDataset(table)
        )
        assert isinstance(result, result_mod.BacktestResult)
        assert result.event_count == 4

    def test_buy_and_hold_creates_fills_and_reduces_cash(self) -> None:
        """Strategy that buys all should produce fills and reduce cash below initial.

        Uses a single persistent instrument so the held position is maintained
        across rebalance bars without triggering a sell-rebuy that nets to zero.
        """
        ts = _ts_range(_T0, 3)
        # Same instrument on all bars — BuyAndHold keeps it long throughout.
        table = _make_trades_table(ts, ["a", "a", "a"], price=0.5)
        config = vec_engine_mod.VecBacktestConfig(
            dataset_id="e2e_test",
            initial_cash=Decimal("1000"),
        )
        result = vec_engine_mod.VecBacktestEngine(config).run(
            _BuyAndHoldStrategy(), _MockDataset(table)
        )
        assert len(result.trades) >= 1
        assert result.final_portfolio.cash < Decimal("1000")

    def test_flat_strategy_no_trades_cash_preserved(self) -> None:
        """A zero-signal strategy should produce no trades and preserve cash."""
        ts = _ts_range(_T0, 3)
        table = _make_trades_table(ts, ["a", "b", "c"], price=0.7)
        config = vec_engine_mod.VecBacktestConfig(
            dataset_id="e2e_test",
            initial_cash=Decimal("2000"),
        )
        result = vec_engine_mod.VecBacktestEngine(config).run(
            _FlatStrategy(),
            _MockDataset(table),
        )
        assert result.trades == []
        assert result.final_portfolio.cash == Decimal("2000")

    def test_zero_fee_fills_have_zero_fee(self) -> None:
        """With fee_bps=0, all fills should have fee=0."""
        ts = _ts_range(_T0, 2)
        table = _make_trades_table(ts, ["a", "b"], price=0.5)
        config = vec_engine_mod.VecBacktestConfig(
            dataset_id="e2e_test",
            initial_cash=Decimal("1000"),
            fee_bps=Decimal("0"),
        )
        result = vec_engine_mod.VecBacktestEngine(config).run(
            _BuyAndHoldStrategy(), _MockDataset(table)
        )
        for fill in result.trades:
            assert fill.fee == _ZERO

    def test_result_is_json_serializable(self) -> None:
        """BacktestResult.model_dump(mode='json') should not raise."""
        ts = _ts_range(_T0, 2)
        table = _make_trades_table(ts, ["a", "b"], price=0.5)
        config = vec_engine_mod.VecBacktestConfig(
            dataset_id="e2e_test",
            initial_cash=Decimal("1000"),
        )
        result = vec_engine_mod.VecBacktestEngine(config).run(
            _BuyAndHoldStrategy(), _MockDataset(table)
        )
        import json
        serialized = result.model_dump(mode="json")
        assert isinstance(json.dumps(serialized), str)

    def test_equity_curve_grows_correctly(self) -> None:
        """equity_curve should have >= 1 entry and equity should be > 0."""
        ts = _ts_range(_T0, 4)
        table = _make_trades_table(ts, ["a", "a", "b", "b"], price=0.5)
        config = vec_engine_mod.VecBacktestConfig(
            dataset_id="e2e_test",
            initial_cash=Decimal("1000"),
        )
        result = vec_engine_mod.VecBacktestEngine(config).run(
            _BuyAndHoldStrategy(), _MockDataset(table)
        )
        assert len(result.equity_curve) >= 1
        final_equity = result.equity_curve[-1][1]
        assert final_equity > _ZERO

    def test_strategy_name_preserved(self) -> None:
        """result.strategy_name must match the strategy's name property."""
        ts = _ts_range(_T0, 2)
        table = _make_trades_table(ts, ["a", "b"], price=0.5)
        strategy = _BuyAndHoldStrategy()
        result = vec_engine_mod.VecBacktestEngine(
            vec_engine_mod.VecBacktestConfig(dataset_id="e2e_test")
        ).run(strategy, _MockDataset(table))
        assert result.strategy_name == "buy_and_hold_vec"
