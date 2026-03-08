"""Integration tests for the event-driven backtest pipeline (R3 end-to-end)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pyarrow as pa
from apps.research.backtester.engine import EventBacktestConfig, EventBacktestEngine
from apps.research.backtester.result import make_backtest_id
from apps.research.backtester.strategy import Strategy, StrategyState

from alpha_core.execution.models import BacktestOrderIntent, FeeSchedule
from alpha_core.portfolio.models import Side

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_T0 = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
_T1 = datetime(2024, 1, 1, 12, 0, 1, tzinfo=UTC)
_T2 = datetime(2024, 1, 1, 12, 0, 2, tzinfo=UTC)
_ZERO = Decimal("0")


def _trades_table(rows: list[tuple[datetime, str, float]]) -> pa.Table:
    return pa.table(
        {
            "ts_event": pa.array(
                [r[0] for r in rows], type=pa.timestamp("us", tz="UTC")
            ),
            "instrument_id": pa.array([r[1] for r in rows], type=pa.string()),
            "price": pa.array([r[2] for r in rows], type=pa.float64()),
        }
    )


class _MockDataset:
    def __init__(self, table: pa.Table) -> None:
        self._table = table

    def trades(self) -> pa.Table:
        return self._table


def _zero_slippage_config(**kwargs: Any) -> EventBacktestConfig:
    base: dict[str, Any] = {
        "dataset_id": "e2e_test",
        "initial_cash": Decimal("1000"),
        "slippage_model": "fixed",
        "slippage_params": {"bps": 0},
    }
    base.update(kwargs)
    return EventBacktestConfig(**base)


class _BuyAllStrategy(Strategy):
    """Buys 10 contracts of the first instrument on the very first event."""

    name = "buy_all"

    def __init__(self, instrument_id: str = "a", size: Decimal = Decimal("10")) -> None:
        self._instr = instrument_id
        self._size = size
        self._done = False

    def on_init(self, universe: list[str]) -> None:
        pass

    def on_data(self, ts: datetime, state: StrategyState) -> list[BacktestOrderIntent]:
        if self._done:
            return []
        self._done = True
        return [
            BacktestOrderIntent(
                instrument_id=self._instr,
                side=Side.LONG,
                size=self._size,
                order_type="market",
            )
        ]

    def on_resolution(self, instrument_id: str, resolved_price: Decimal) -> None:
        pass


# ---------------------------------------------------------------------------
# Integration scenarios
# ---------------------------------------------------------------------------


class TestBuyAndResolveWinner:
    """Buy 10 contracts at 0.30, resolve at 1.0 — expect full payoff."""

    def test_pnl_after_long_resolution_at_one(self) -> None:
        rows = [(_T0, "a", 0.3), (_T1, "a", 0.3)]
        dataset = _MockDataset(_trades_table(rows))
        config = _zero_slippage_config(initial_cash=Decimal("1000"))
        strategy = _BuyAllStrategy("a", Decimal("10"))
        resolution = {"a": (Decimal("1"), _T1)}

        result = EventBacktestEngine(config).run(strategy, dataset, resolution_prices=resolution)

        # Cash: 1000 - 10*0.3 = 997; after resolution: 997 + 10*1 = 1007
        assert result.final_portfolio.cash == Decimal("1007.000000") or \
            result.final_portfolio.cash.quantize(Decimal("0.01")) == Decimal("1007.00")
        assert len(result.trades) == 1

    def test_pnl_after_long_resolution_at_zero(self) -> None:
        """Lose the full stake — resolved at 0."""
        rows = [(_T0, "a", 0.7), (_T1, "a", 0.7)]
        dataset = _MockDataset(_trades_table(rows))
        config = _zero_slippage_config(initial_cash=Decimal("1000"))
        strategy = _BuyAllStrategy("a", Decimal("10"))
        resolution = {"a": (Decimal("0"), _T1)}

        result = EventBacktestEngine(config).run(strategy, dataset, resolution_prices=resolution)

        # Cash: 1000 - 10*0.7 = 993; after resolution at 0: 993 + 0 = 993
        cash = result.final_portfolio.cash.quantize(Decimal("0.01"))
        assert cash == Decimal("993.00")


class TestEmptyStrategy:
    def test_zero_trades_zero_pnl(self) -> None:
        class _Passive(Strategy):
            name = "passive"

            def on_init(self, universe: list[str]) -> None:
                pass

            def on_data(self, ts: datetime, state: StrategyState) -> list[BacktestOrderIntent]:
                return []

            def on_resolution(self, instrument_id: str, resolved_price: Decimal) -> None:
                pass

        rows = [(_T0, "a", 0.5), (_T1, "a", 0.6)]
        result = EventBacktestEngine(_zero_slippage_config()).run(
            _Passive(), _MockDataset(_trades_table(rows))
        )
        assert result.trades == []
        assert result.final_portfolio.total_pnl == _ZERO


class TestJsonSerialisation:
    def test_result_serialises_to_json(self) -> None:
        rows = [(_T0, "a", 0.5)]
        result = EventBacktestEngine(_zero_slippage_config()).run(
            _BuyAllStrategy(), _MockDataset(_trades_table(rows))
        )
        raw = result.model_dump(mode="json")
        # Should be round-trippable through json.dumps / json.loads
        json_str = json.dumps(raw)
        parsed = json.loads(json_str)
        assert parsed["strategy_name"] == "buy_all"
        assert "backtest_id" in parsed
        assert isinstance(parsed["event_count"], int)


class TestBacktestIdStability:
    def test_identical_configs_same_id(self) -> None:
        rows = [(_T0, "a", 0.5)]
        dataset = _MockDataset(_trades_table(rows))
        config = _zero_slippage_config()

        r1 = EventBacktestEngine(config).run(_BuyAllStrategy(), dataset)
        r2 = EventBacktestEngine(config).run(_BuyAllStrategy(), dataset)

        assert r1.backtest_id == r2.backtest_id

    def test_different_strategy_name_different_id(self) -> None:
        config = _zero_slippage_config()
        cid_a = make_backtest_id(config.model_dump(mode="json"), "strategy_a")
        cid_b = make_backtest_id(config.model_dump(mode="json"), "strategy_b")
        assert cid_a != cid_b

    def test_different_config_different_id(self) -> None:
        cfg_1000 = _zero_slippage_config(initial_cash=Decimal("1000"))
        cfg_2000 = _zero_slippage_config(initial_cash=Decimal("2000"))
        cid1 = make_backtest_id(cfg_1000.model_dump(mode="json"), "s")
        cid2 = make_backtest_id(cfg_2000.model_dump(mode="json"), "s")
        assert cid1 != cid2


class TestFeeIntegration:
    def test_fee_reduces_available_cash(self) -> None:
        schedule = FeeSchedule(taker_fee_bps=Decimal("100"))  # 1% taker fee
        config = _zero_slippage_config(
            initial_cash=Decimal("1000"),
            fee_schedule=schedule,
        )
        rows = [(_T0, "a", 0.5)]
        strategy = _BuyAllStrategy("a", Decimal("10"))
        result = EventBacktestEngine(config).run(strategy, _MockDataset(_trades_table(rows)))

        assert len(result.trades) == 1
        fill = result.trades[0]
        # fee = 10 * 0.5 * (100/10000) = 0.05
        assert fill.fee.quantize(Decimal("0.0001")) == Decimal("0.0500")
        # cash = 1000 - (10*0.5 + 0.05) = 1000 - 5.05 = 994.95
        assert result.final_portfolio.cash.quantize(Decimal("0.01")) == Decimal("994.95")
