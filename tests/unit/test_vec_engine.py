"""Unit tests for apps.research.backtester.vec_engine.VecBacktestEngine."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pandas as pd
import pyarrow as pa
import pytest

from alpha_core.portfolio.sizing import EqualWeightSizer
from apps.research.backtester.result import BacktestResult
from apps.research.backtester.vec_engine import VecBacktestConfig, VecBacktestEngine
from apps.research.backtester.vec_strategy import VecStrategy

_T0 = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
_T1 = datetime(2024, 1, 2, 12, 0, tzinfo=UTC)
_T2 = datetime(2024, 1, 3, 12, 0, tzinfo=UTC)
_T3 = datetime(2024, 1, 4, 12, 0, tzinfo=UTC)
_ZERO = Decimal("0")


def _make_trades_table(rows: list[tuple[datetime, str, float]]) -> pa.Table:
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


def _default_config(**kwargs: Any) -> VecBacktestConfig:
    base: dict[str, Any] = {
        "dataset_id": "test",
        "initial_cash": Decimal("1000"),
        "fee_bps": Decimal("0"),
        "rebalance_frequency": "1D",
    }
    base.update(kwargs)
    return VecBacktestConfig(**base)


class _NullStrategy(VecStrategy):
    name = "null_vec"

    def generate_signals(self, features, universe):
        return pd.DataFrame({"instrument_id": universe, "signal": [0.0] * len(universe)})

    def size_positions(self, signals, portfolio_value, max_positions):
        return pd.DataFrame({"instrument_id": [], "target_weight": []})


class _BuyAllStrategy(VecStrategy):
    name = "buy_all_vec"

    def generate_signals(self, features, universe):
        return pd.DataFrame({"instrument_id": universe, "signal": [1.0] * len(universe)})

    def size_positions(self, signals, portfolio_value, max_positions):
        return EqualWeightSizer().size(signals, portfolio_value, max_positions)


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


class TestVecBacktestConfig:
    def test_default_config(self) -> None:
        c = VecBacktestConfig(dataset_id="myds")
        assert c.initial_cash == Decimal("10000")
        assert c.fee_bps == _ZERO
        assert c.position_sizing == "equal_weight"
        assert c.max_positions == 50

    def test_blank_dataset_id_raises(self) -> None:
        with pytest.raises(Exception):
            VecBacktestConfig(dataset_id="  ")

    def test_negative_fee_bps_raises(self) -> None:
        with pytest.raises(Exception):
            VecBacktestConfig(dataset_id="ds", fee_bps=Decimal("-1"))

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(Exception):
            VecBacktestConfig(dataset_id="ds", bad_field=True)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Empty dataset
# ---------------------------------------------------------------------------


class TestEmptyDataset:
    def test_empty_table_returns_empty_result(self) -> None:
        engine = VecBacktestEngine(_default_config())
        result = engine.run(_NullStrategy(), _MockDataset(_make_trades_table([])))
        assert isinstance(result, BacktestResult)
        assert result.event_count == 0
        assert result.trades == []

    def test_empty_table_initial_cash_preserved(self) -> None:
        engine = VecBacktestEngine(_default_config(initial_cash=Decimal("5000")))
        result = engine.run(_NullStrategy(), _MockDataset(_make_trades_table([])))
        assert result.final_portfolio.cash == Decimal("5000")


# ---------------------------------------------------------------------------
# Null strategy
# ---------------------------------------------------------------------------


class TestNullStrategy:
    def test_null_strategy_no_fills(self) -> None:
        rows = [(_T0, "a", 0.5), (_T1, "a", 0.6)]
        engine = VecBacktestEngine(_default_config())
        result = engine.run(_NullStrategy(), _MockDataset(_make_trades_table(rows)))
        assert result.trades == []

    def test_event_count_matches_rows(self) -> None:
        rows = [(_T0, "a", 0.5), (_T1, "a", 0.6), (_T2, "a", 0.7)]
        engine = VecBacktestEngine(_default_config())
        result = engine.run(_NullStrategy(), _MockDataset(_make_trades_table(rows)))
        assert result.event_count == 3

    def test_strategy_name_in_result(self) -> None:
        rows = [(_T0, "a", 0.5)]
        result = VecBacktestEngine(_default_config()).run(
            _NullStrategy(), _MockDataset(_make_trades_table(rows))
        )
        assert result.strategy_name == "null_vec"


# ---------------------------------------------------------------------------
# Buy-all strategy
# ---------------------------------------------------------------------------


class TestBuyAllStrategy:
    def test_buy_all_creates_fills(self) -> None:
        rows = [(_T0, "a", 0.5), (_T1, "a", 0.6)]
        result = VecBacktestEngine(_default_config()).run(
            _BuyAllStrategy(), _MockDataset(_make_trades_table(rows))
        )
        assert len(result.trades) >= 1

    def test_buy_reduces_cash(self) -> None:
        rows = [(_T0, "a", 0.5)]
        result = VecBacktestEngine(
            _default_config(initial_cash=Decimal("1000"))
        ).run(_BuyAllStrategy(), _MockDataset(_make_trades_table(rows)))
        assert result.final_portfolio.cash < Decimal("1000")

    def test_equity_curve_non_empty(self) -> None:
        rows = [(_T0, "a", 0.5), (_T1, "a", 0.6)]
        result = VecBacktestEngine(_default_config()).run(
            _BuyAllStrategy(), _MockDataset(_make_trades_table(rows))
        )
        assert len(result.equity_curve) >= 1


# ---------------------------------------------------------------------------
# Fees
# ---------------------------------------------------------------------------


class TestFeeApplication:
    def test_fee_reduces_cash(self) -> None:
        rows = [(_T0, "a", 0.5)]
        config = _default_config(fee_bps=Decimal("100"), initial_cash=Decimal("1000"))
        result = VecBacktestEngine(config).run(
            _BuyAllStrategy(), _MockDataset(_make_trades_table(rows))
        )
        # Without fee: cash = 1000 - 1000*0.5 = 500
        # With 1% fee on notional 500: fee = 5; cash = 500 - 5 = 495
        # The exact value depends on sizing, but cash should be less than with 0 fee.
        no_fee_result = VecBacktestEngine(
            _default_config(fee_bps=Decimal("0"), initial_cash=Decimal("1000"))
        ).run(_BuyAllStrategy(), _MockDataset(_make_trades_table(rows)))
        assert result.final_portfolio.cash < no_fee_result.final_portfolio.cash


# ---------------------------------------------------------------------------
# Time filtering
# ---------------------------------------------------------------------------


class TestTimeFiltering:
    def test_start_filter(self) -> None:
        rows = [(_T0, "a", 0.5), (_T1, "a", 0.6), (_T2, "a", 0.7)]
        config = _default_config(start=_T1)
        result = VecBacktestEngine(config).run(
            _NullStrategy(), _MockDataset(_make_trades_table(rows))
        )
        assert result.event_count == 2

    def test_end_filter(self) -> None:
        rows = [(_T0, "a", 0.5), (_T1, "a", 0.6), (_T2, "a", 0.7)]
        config = _default_config(end=_T1)
        result = VecBacktestEngine(config).run(
            _NullStrategy(), _MockDataset(_make_trades_table(rows))
        )
        assert result.event_count == 2


# ---------------------------------------------------------------------------
# Backtest ID
# ---------------------------------------------------------------------------


class TestBacktestId:
    def test_backtest_id_deterministic(self) -> None:
        rows = [(_T0, "a", 0.5)]
        dataset = _MockDataset(_make_trades_table(rows))
        config = _default_config()
        r1 = VecBacktestEngine(config).run(_NullStrategy(), dataset)
        r2 = VecBacktestEngine(config).run(_NullStrategy(), dataset)
        assert r1.backtest_id == r2.backtest_id

    def test_backtest_id_length(self) -> None:
        rows = [(_T0, "a", 0.5)]
        result = VecBacktestEngine(_default_config()).run(
            _NullStrategy(), _MockDataset(_make_trades_table(rows))
        )
        assert len(result.backtest_id) == 16
