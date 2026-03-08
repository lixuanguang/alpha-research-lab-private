"""Unit tests for apps.research.backtester.engine.EventBacktestEngine."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pyarrow as pa
from apps.research.backtester.engine import EventBacktestConfig, EventBacktestEngine
from apps.research.backtester.result import BacktestResult, make_backtest_id
from apps.research.backtester.strategy import Strategy, StrategyState

from alpha_core.execution.models import BacktestOrderIntent
from alpha_core.portfolio.models import Side

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_T0 = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
_T1 = datetime(2024, 1, 1, 12, 0, 1, tzinfo=UTC)
_T2 = datetime(2024, 1, 1, 12, 0, 2, tzinfo=UTC)
_ZERO = Decimal("0")


def _make_trades_table(
    rows: list[tuple[datetime, str, float]],
) -> pa.Table:
    """Build a minimal trade table with ts_event, instrument_id, price columns."""
    return pa.table(
        {
            "ts_event": pa.array([r[0] for r in rows], type=pa.timestamp("us", tz="UTC")),
            "instrument_id": pa.array([r[1] for r in rows], type=pa.string()),
            "price": pa.array([r[2] for r in rows], type=pa.float64()),
        }
    )


def _make_trades_table_with_available(
    rows: list[tuple[datetime, datetime, str, float]],
) -> pa.Table:
    return pa.table(
        {
            "ts_event": pa.array([r[0] for r in rows], type=pa.timestamp("us", tz="UTC")),
            "ts_available": pa.array([r[1] for r in rows], type=pa.timestamp("us", tz="UTC")),
            "instrument_id": pa.array([r[2] for r in rows], type=pa.string()),
            "price": pa.array([r[3] for r in rows], type=pa.float64()),
        }
    )


class _MockDataset:
    """Minimal stand-in for GoldDataset."""

    def __init__(self, table: pa.Table) -> None:
        self._table = table

    def trades(self) -> pa.Table:
        return self._table


def _default_config(**kwargs: Any) -> EventBacktestConfig:
    base: dict[str, Any] = {
        "dataset_id": "test",
        "initial_cash": Decimal("1000"),
        "slippage_model": "fixed",
        "slippage_params": {"bps": 0},  # zero slippage for predictable prices
    }
    base.update(kwargs)
    return EventBacktestConfig(**base)


class _NullStrategy(Strategy):
    """Strategy that never places orders."""

    name = "null"

    def __init__(self) -> None:
        self.init_calls: list[list[str]] = []
        self.data_calls: list[tuple[datetime, StrategyState]] = []
        self.resolution_calls: list[tuple[str, Decimal]] = []

    def on_init(self, universe: list[str]) -> None:
        self.init_calls.append(universe)

    def on_data(self, ts: datetime, state: StrategyState) -> list[BacktestOrderIntent]:
        self.data_calls.append((ts, state))
        return []

    def on_resolution(self, instrument_id: str, resolved_price: Decimal) -> None:
        self.resolution_calls.append((instrument_id, resolved_price))


class _BuyOnceStrategy(Strategy):
    """Buys 5 contracts of the first instrument on the first on_data call."""

    name = "buy_once"

    def __init__(self) -> None:
        self._bought = False

    def on_init(self, universe: list[str]) -> None:
        self._universe = universe

    def on_data(self, ts: datetime, state: StrategyState) -> list[BacktestOrderIntent]:
        if self._bought:
            return []
        self._bought = True
        return [
            BacktestOrderIntent(
                instrument_id=state.universe[0],
                side=Side.LONG,
                size=Decimal("5"),
                order_type="market",
            )
        ]

    def on_resolution(self, instrument_id: str, resolved_price: Decimal) -> None:
        pass


class _AlwaysBuyStrategy(Strategy):
    name = "always_buy"

    def on_init(self, universe: list[str]) -> None:
        del universe

    def on_data(self, ts: datetime, state: StrategyState) -> list[BacktestOrderIntent]:
        del ts, state
        return [
            BacktestOrderIntent(
                instrument_id="a",
                side=Side.LONG,
                size=Decimal("1"),
                order_type="market",
            )
        ]

    def on_resolution(self, instrument_id: str, resolved_price: Decimal) -> None:
        del instrument_id, resolved_price


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmptyDataset:
    def test_empty_table_returns_empty_result(self) -> None:
        table = _make_trades_table([])
        dataset = _MockDataset(table)
        engine = EventBacktestEngine(_default_config())
        strategy = _NullStrategy()
        result = engine.run(strategy, dataset)

        assert isinstance(result, BacktestResult)
        assert result.event_count == 0
        assert result.trades == []
        assert result.equity_curve == []

    def test_empty_table_does_not_call_on_data(self) -> None:
        dataset = _MockDataset(_make_trades_table([]))
        strategy = _NullStrategy()
        EventBacktestEngine(_default_config()).run(strategy, dataset)
        assert strategy.data_calls == []


class TestStrategyCallbacks:
    def test_on_init_called_once_with_universe(self) -> None:
        table = _make_trades_table([(_T0, "abc", 0.5), (_T1, "abc", 0.51)])
        strategy = _NullStrategy()
        EventBacktestEngine(_default_config()).run(strategy, _MockDataset(table))
        assert len(strategy.init_calls) == 1
        assert "abc" in strategy.init_calls[0]

    def test_on_data_called_per_row(self) -> None:
        rows = [(_T0, "a", 0.5), (_T1, "a", 0.6), (_T2, "a", 0.7)]
        table = _make_trades_table(rows)
        strategy = _NullStrategy()
        EventBacktestEngine(_default_config()).run(strategy, _MockDataset(table))
        assert len(strategy.data_calls) == 3

    def test_on_data_receives_correct_timestamp(self) -> None:
        table = _make_trades_table([(_T0, "a", 0.5)])
        strategy = _NullStrategy()
        EventBacktestEngine(_default_config()).run(strategy, _MockDataset(table))
        assert strategy.data_calls[0][0] == _T0

    def test_universe_in_strategy_state(self) -> None:
        table = _make_trades_table([(_T0, "mkt-a", 0.5), (_T0, "mkt-b", 0.6)])
        strategy = _NullStrategy()
        engine = EventBacktestEngine(_default_config())
        engine.run(strategy, _MockDataset(table))
        received_universes = [state.universe for _, state in strategy.data_calls]
        for u in received_universes:
            assert "mkt-a" in u and "mkt-b" in u


class TestResolution:
    def test_resolution_calls_on_resolution(self) -> None:
        table = _make_trades_table([(_T0, "a", 0.5), (_T1, "a", 0.6)])
        strategy = _NullStrategy()
        res = {"a": (Decimal("1"), _T1)}
        EventBacktestEngine(_default_config()).run(
            strategy, _MockDataset(table), resolution_prices=res
        )
        assert ("a", Decimal("1")) in strategy.resolution_calls

    def test_resolution_called_at_most_once_per_instrument(self) -> None:
        table = _make_trades_table([(_T0, "a", 0.5), (_T1, "a", 0.6), (_T2, "a", 0.7)])
        strategy = _NullStrategy()
        res = {"a": (Decimal("1"), _T1)}
        EventBacktestEngine(_default_config()).run(
            strategy, _MockDataset(table), resolution_prices=res
        )
        assert len([c for c in strategy.resolution_calls if c[0] == "a"]) == 1

    def test_resolution_prevents_reentry_in_resolved_instrument(self) -> None:
        table = _make_trades_table([(_T0, "a", 0.5), (_T1, "a", 0.6), (_T2, "a", 0.7)])
        res = {"a": (Decimal("1"), _T1)}

        result = EventBacktestEngine(_default_config()).run(
            _AlwaysBuyStrategy(),
            _MockDataset(table),
            resolution_prices=res,
        )

        assert [fill.timestamp for fill in result.trades] == [_T0]
        assert result.final_portfolio.positions == {}


class TestFills:
    def test_buy_order_reduces_cash(self) -> None:
        table = _make_trades_table([(_T0, "a", 0.5)])
        strategy = _BuyOnceStrategy()
        config = _default_config(initial_cash=Decimal("1000"))
        result = EventBacktestEngine(config).run(strategy, _MockDataset(table))
        # LONG 5 @ 0.5 = 2.5 deducted; cash should be 997.5
        assert result.final_portfolio.cash == Decimal("997.5")

    def test_fill_recorded_in_trades(self) -> None:
        table = _make_trades_table([(_T0, "a", 0.5)])
        strategy = _BuyOnceStrategy()
        result = EventBacktestEngine(_default_config()).run(strategy, _MockDataset(table))
        assert len(result.trades) == 1
        fill = result.trades[0]
        assert fill.order.side == Side.LONG
        assert fill.fill_size == Decimal("5")

    def test_null_strategy_no_fills(self) -> None:
        table = _make_trades_table([(_T0, "a", 0.5)])
        result = EventBacktestEngine(_default_config()).run(_NullStrategy(), _MockDataset(table))
        assert result.trades == []


class TestResultMetadata:
    def test_event_count_matches_rows(self) -> None:
        rows = [(_T0, "a", 0.5), (_T1, "a", 0.6), (_T2, "a", 0.7)]
        result = EventBacktestEngine(_default_config()).run(
            _NullStrategy(), _MockDataset(_make_trades_table(rows))
        )
        assert result.event_count == 3

    def test_equity_curve_non_empty(self) -> None:
        table = _make_trades_table([(_T0, "a", 0.5)])
        result = EventBacktestEngine(_default_config()).run(_NullStrategy(), _MockDataset(table))
        assert len(result.equity_curve) >= 1

    def test_strategy_name_in_result(self) -> None:
        table = _make_trades_table([(_T0, "a", 0.5)])
        result = EventBacktestEngine(_default_config()).run(_NullStrategy(), _MockDataset(table))
        assert result.strategy_name == "null"

    def test_duration_seconds_positive(self) -> None:
        table = _make_trades_table([(_T0, "a", 0.5)])
        result = EventBacktestEngine(_default_config()).run(_NullStrategy(), _MockDataset(table))
        assert result.duration_seconds >= 0


class TestTimeFiltering:
    def test_start_filter_excludes_earlier_events(self) -> None:
        rows = [(_T0, "a", 0.5), (_T1, "a", 0.6), (_T2, "a", 0.7)]
        config = _default_config(start=_T1)
        result = EventBacktestEngine(config).run(
            _NullStrategy(), _MockDataset(_make_trades_table(rows))
        )
        assert result.event_count == 2  # T1 and T2 included

    def test_end_filter_excludes_later_events(self) -> None:
        rows = [(_T0, "a", 0.5), (_T1, "a", 0.6), (_T2, "a", 0.7)]
        config = _default_config(end=_T1)
        result = EventBacktestEngine(config).run(
            _NullStrategy(), _MockDataset(_make_trades_table(rows))
        )
        assert result.event_count == 2  # T0 and T1 included


class TestPointInTimeSemantics:
    def test_ts_available_drives_processing_order(self) -> None:
        table = _make_trades_table_with_available(
            [
                (_T0, _T2, "a", 0.5),
                (_T1, _T1, "a", 0.6),
            ]
        )
        strategy = _NullStrategy()

        EventBacktestEngine(_default_config()).run(strategy, _MockDataset(table))

        assert [ts for ts, _ in strategy.data_calls] == [_T1, _T2]

    def test_late_feature_not_visible_before_ts_available(self) -> None:
        trades = _make_trades_table_with_available(
            [
                (_T0, _T1, "a", 0.5),
                (_T1, _T2, "a", 0.6),
            ]
        )
        features = pa.table(
            {
                "instrument_id": pa.array(["a"], type=pa.string()),
                "price": pa.array([0.5], type=pa.float64()),
                "ts_event": pa.array([_T0], type=pa.timestamp("us", tz="UTC")),
                "ts_available": pa.array([_T2], type=pa.timestamp("us", tz="UTC")),
                "feature_alpha": pa.array([1.0], type=pa.float64()),
            }
        )
        strategy = _NullStrategy()

        EventBacktestEngine(_default_config()).run(
            strategy,
            _MockDataset(trades),
            features=features,
        )

        first_state = strategy.data_calls[0][1]
        second_state = strategy.data_calls[1][1]
        assert first_state.features is None
        assert second_state.features == {"a": {"feature_alpha": 1.0}}

    def test_strategy_state_separates_observed_and_execution_prices(self) -> None:
        table = _make_trades_table([(_T0, "a", 0.5), (_T1, "a", 0.6)])
        strategy = _NullStrategy()

        EventBacktestEngine(_default_config()).run(strategy, _MockDataset(table))

        first_state = strategy.data_calls[0][1]
        second_state = strategy.data_calls[1][1]
        assert first_state.latest_prices == {}
        assert first_state.execution_prices == {"a": Decimal("0.5")}
        assert second_state.latest_prices == {"a": Decimal("0.5")}
        assert second_state.execution_prices == {"a": Decimal("0.6")}


class TestBacktestId:
    def test_backtest_id_deterministic(self) -> None:
        table = _make_trades_table([(_T0, "a", 0.5)])
        dataset = _MockDataset(table)
        config = _default_config()

        e1 = EventBacktestEngine(config)
        e2 = EventBacktestEngine(config)
        r1 = e1.run(_NullStrategy(), dataset)
        r2 = e2.run(_NullStrategy(), dataset)
        assert r1.backtest_id == r2.backtest_id

    def test_backtest_id_length(self) -> None:
        config = _default_config()
        cid = make_backtest_id(config.model_dump(mode="json"), "my_strategy")
        assert len(cid) == 16
