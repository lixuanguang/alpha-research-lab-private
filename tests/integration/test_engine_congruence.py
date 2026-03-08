"""Integration tests: event-driven vs vectorized engine congruence.

Both engines should agree closely when they are given materially equivalent
strategy logic and the same market data. The tests below check cash
preservation on a no-trade path and compare a rebalance-heavy target schedule
that opens, resizes, flips, closes, and reopens positions.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pyarrow as pa
from apps.research.backtester.engine import EventBacktestConfig, EventBacktestEngine
from apps.research.backtester.strategy import Strategy, StrategyState
from apps.research.backtester.vec_engine import VecBacktestConfig, VecBacktestEngine
from apps.research.backtester.vec_strategy import VecStrategy

import alpha_core.execution.models as exec_models
from alpha_core.execution.models import BacktestOrderIntent
from alpha_core.portfolio.models import PositionState, Side

_ZERO = Decimal("0")
_INITIAL_CASH = Decimal("10000")
_INSTRUMENT = "testmarket:q1"
_INSTRUMENT_A = "testmarket:qa"
_INSTRUMENT_B = "testmarket:qb"
_INSTRUMENT_C = "testmarket:qc"
_T0 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
_T1 = _T0 + timedelta(days=1)
_T2 = _T0 + timedelta(days=2)
_T3 = _T0 + timedelta(days=3)
_T4 = _T0 + timedelta(days=4)
_T5 = _T0 + timedelta(days=5)
_I0_OPEN = _T0 + timedelta(hours=9)
_I0_CLOSE = _T0 + timedelta(hours=15)
_I1_OPEN = _T1 + timedelta(hours=9)
_I1_CLOSE = _T1 + timedelta(hours=15)
_I2_OPEN = _T2 + timedelta(hours=9)
_I2_CLOSE = _T2 + timedelta(hours=15)
_TARGET_SCHEDULE: dict[datetime, Decimal] = {
    _T0: Decimal("4"),
    _T1: Decimal("10"),
    _T2: Decimal("-5"),
    _T3: Decimal("-8"),
    _T4: Decimal("0"),
    _T5: Decimal("3"),
}
_PRICE_PATH = [0.45, 0.55, 0.40, 0.65, 0.35, 0.70]
_INTRADAY_TIMESTAMPS = [_I0_OPEN, _I0_CLOSE, _I1_OPEN, _I1_CLOSE, _I2_OPEN, _I2_CLOSE]
_INTRADAY_PRICE_PATH = [0.40, 0.55, 0.60, 0.35, 0.45, 0.70]
_INTRADAY_TARGET_SCHEDULE: dict[datetime, Decimal] = {
    _I0_OPEN: _ZERO,
    _I0_CLOSE: Decimal("4"),
    _I1_OPEN: Decimal("4"),
    _I1_CLOSE: Decimal("-5"),
    _I2_OPEN: Decimal("-5"),
    _I2_CLOSE: _ZERO,
}
_INTRADAY_CLOSE_TIMESTAMPS = [_I0_CLOSE, _I1_CLOSE, _I2_CLOSE]
_CROSS_SECTIONAL_CLOSE_TIMESTAMPS = [
    _T0 + timedelta(hours=15),
    _T1 + timedelta(hours=15),
    _T2 + timedelta(hours=15),
    _T3 + timedelta(hours=15),
]
_CROSS_SECTIONAL_ROWS = [
    (_T0 + timedelta(hours=13), _INSTRUMENT_A, 0.40),
    (_T0 + timedelta(hours=14), _INSTRUMENT_B, 0.60),
    (_T0 + timedelta(hours=15), _INSTRUMENT_C, 0.25),
    (_T1 + timedelta(hours=13), _INSTRUMENT_A, 0.45),
    (_T1 + timedelta(hours=14), _INSTRUMENT_B, 0.55),
    (_T1 + timedelta(hours=15), _INSTRUMENT_C, 0.30),
    (_T2 + timedelta(hours=13), _INSTRUMENT_A, 0.50),
    (_T2 + timedelta(hours=14), _INSTRUMENT_B, 0.40),
    (_T2 + timedelta(hours=15), _INSTRUMENT_C, 0.35),
    (_T3 + timedelta(hours=13), _INSTRUMENT_A, 0.48),
    (_T3 + timedelta(hours=14), _INSTRUMENT_B, 0.65),
    (_T3 + timedelta(hours=15), _INSTRUMENT_C, 0.28),
]
_CROSS_SECTIONAL_TARGET_SCHEDULE: dict[datetime, dict[str, Decimal]] = {
    _CROSS_SECTIONAL_CLOSE_TIMESTAMPS[0]: {
        _INSTRUMENT_A: Decimal("2000"),
        _INSTRUMENT_B: Decimal("1500"),
    },
    _CROSS_SECTIONAL_CLOSE_TIMESTAMPS[1]: {
        _INSTRUMENT_A: Decimal("1000"),
        _INSTRUMENT_C: Decimal("2500"),
    },
    _CROSS_SECTIONAL_CLOSE_TIMESTAMPS[2]: {
        _INSTRUMENT_B: Decimal("1200"),
        _INSTRUMENT_C: Decimal("2200"),
    },
    _CROSS_SECTIONAL_CLOSE_TIMESTAMPS[3]: {
        _INSTRUMENT_A: Decimal("500"),
        _INSTRUMENT_B: Decimal("800"),
    },
}

# ---------------------------------------------------------------------------
# Shared datasets
# ---------------------------------------------------------------------------

_N = 30


def _make_trades_table(
    prices: list[float] | None = None,
    timestamps: list[datetime] | None = None,
) -> pa.Table:
    """Trade events for a single instrument."""
    price_path = [0.5] * _N if prices is None else prices
    if timestamps is None:
        event_timestamps = [_T0 + timedelta(days=i) for i in range(len(price_path))]
    else:
        if len(timestamps) != len(price_path):
            raise ValueError("timestamps and prices must have the same length")
        event_timestamps = timestamps
    return pa.table(
        {
            "ts_event": pa.array(event_timestamps, type=pa.timestamp("us", tz="UTC")),
            "instrument_id": pa.array([_INSTRUMENT] * len(price_path), type=pa.string()),
            "price": pa.array(price_path, type=pa.float64()),
        }
    )


def _make_trades_table_from_rows(
    rows: Sequence[tuple[datetime, str, float]],
) -> pa.Table:
    return pa.table(
        {
            "ts_event": pa.array([row[0] for row in rows], type=pa.timestamp("us", tz="UTC")),
            "instrument_id": pa.array([row[1] for row in rows], type=pa.string()),
            "price": pa.array([row[2] for row in rows], type=pa.float64()),
        }
    )


class _MockDataset:
    def __init__(self, table: pa.Table) -> None:
        self._table = table

    def trades(self) -> pa.Table:
        return self._table


# ---------------------------------------------------------------------------
# Event strategies
# ---------------------------------------------------------------------------


class _ScheduledTargetsEventStrategy(Strategy):
    """Match an explicit signed-contract target schedule."""

    name = "scheduled_targets_event"

    def __init__(self, targets: dict[datetime, Decimal]) -> None:
        self._targets = targets

    def on_init(self, universe: list[str]) -> None:
        del universe

    def on_data(
        self,
        timestamp: datetime,
        state: StrategyState,
    ) -> list[BacktestOrderIntent]:
        if timestamp not in self._targets or _INSTRUMENT not in state.universe:
            return []
        target = self._targets[timestamp]
        current = _signed_position_size(state.portfolio.positions.get(_INSTRUMENT))
        return _orders_for_target(_INSTRUMENT, current, target)

    def on_resolution(self, instrument_id: str, resolved_price: Decimal) -> None:
        del instrument_id
        del resolved_price


class _CrossSectionalTargetsEventStrategy(Strategy):
    """Match explicit signed-contract targets across multiple instruments."""

    name = "cross_sectional_targets_event"

    def __init__(self, targets: dict[datetime, dict[str, Decimal]]) -> None:
        self._targets = targets

    def on_init(self, universe: list[str]) -> None:
        del universe

    def on_data(
        self,
        timestamp: datetime,
        state: StrategyState,
    ) -> list[BacktestOrderIntent]:
        target_map = self._targets.get(timestamp)
        if target_map is None:
            return []

        instruments = sorted(set(state.portfolio.positions) | set(target_map))
        orders: list[BacktestOrderIntent] = []
        for instrument_id in instruments:
            current = _signed_position_size(state.portfolio.positions.get(instrument_id))
            target = target_map.get(instrument_id, _ZERO)
            orders.extend(_orders_for_target(instrument_id, current, target))
        return orders

    def on_resolution(self, instrument_id: str, resolved_price: Decimal) -> None:
        del instrument_id
        del resolved_price


class _FlatEventStrategy(Strategy):
    """Never trades."""

    name = "flat_event"

    def on_init(self, universe: list[str]) -> None:
        del universe

    def on_data(
        self,
        timestamp: datetime,
        state: StrategyState,
    ) -> list[BacktestOrderIntent]:
        del timestamp
        del state
        return []

    def on_resolution(self, instrument_id: str, resolved_price: Decimal) -> None:
        del instrument_id
        del resolved_price


# ---------------------------------------------------------------------------
# Vec strategies
# ---------------------------------------------------------------------------


class _ScheduledTargetsVecStrategy(VecStrategy):
    """Target the same signed-contract schedule as the event strategy."""

    name = "scheduled_targets_vec"

    def __init__(self, targets: dict[datetime, Decimal]) -> None:
        self._targets = targets

    def generate_signals(self, features: pd.DataFrame, universe: list[str]) -> pd.DataFrame:
        snapshot = features.copy()
        if (
            snapshot.empty
            or "instrument_id" not in snapshot.columns
            or "price" not in snapshot.columns
        ):
            return pd.DataFrame(columns=["instrument_id", "target_contracts", "price"])
        if "ts_event" in snapshot.columns:
            snapshot = snapshot.sort_values("ts_event", kind="stable")
        snapshot = snapshot.groupby("instrument_id", as_index=False).last()
        snapshot = snapshot[snapshot["instrument_id"].isin(universe)]
        if snapshot.empty or "ts_event" not in snapshot.columns:
            return pd.DataFrame(columns=["instrument_id", "target_contracts", "price"])
        bar_ts = pd.Timestamp(snapshot["ts_event"].max()).to_pydatetime()
        target_contracts = self._targets.get(bar_ts, _ZERO)
        return pd.DataFrame(
            {
                "instrument_id": snapshot["instrument_id"].astype(str).values,
                "target_contracts": [float(target_contracts)] * len(snapshot.index),
                "price": snapshot["price"].astype(float).values,
            }
        )

    def size_positions(
        self, signals: pd.DataFrame, portfolio_value: Decimal, max_positions: int
    ) -> pd.DataFrame:
        del max_positions
        if signals.empty or portfolio_value <= _ZERO:
            return pd.DataFrame(columns=["instrument_id", "target_weight"])

        target_contracts = Decimal(str(signals["target_contracts"].iloc[0]))
        price = Decimal(str(signals["price"].astype(float).iloc[0]))
        target_weight = float((target_contracts * price) / portfolio_value)
        return pd.DataFrame(
            {
                "instrument_id": signals["instrument_id"].astype(str).values,
                "target_weight": [target_weight] * len(signals.index),
            }
        )


class _CrossSectionalTargetsVecStrategy(VecStrategy):
    """Target explicit signed-contract positions across multiple instruments."""

    name = "cross_sectional_targets_vec"

    def __init__(self, targets: dict[datetime, dict[str, Decimal]]) -> None:
        self._targets = targets

    def generate_signals(self, features: pd.DataFrame, universe: list[str]) -> pd.DataFrame:
        snapshot = features.copy()
        if (
            snapshot.empty
            or "instrument_id" not in snapshot.columns
            or "price" not in snapshot.columns
            or "ts_event" not in snapshot.columns
        ):
            return pd.DataFrame(columns=["instrument_id", "target_contracts", "price"])
        snapshot = snapshot.sort_values("ts_event", kind="stable")
        snapshot = snapshot.groupby("instrument_id", as_index=False).last()
        snapshot = snapshot[snapshot["instrument_id"].isin(universe)]
        if snapshot.empty:
            return pd.DataFrame(columns=["instrument_id", "target_contracts", "price"])

        bar_ts = pd.Timestamp(snapshot["ts_event"].max()).to_pydatetime()
        target_map = self._targets.get(bar_ts)
        if target_map is None:
            return pd.DataFrame(columns=["instrument_id", "target_contracts", "price"])

        contract_targets = [
            float(target_map.get(str(instrument_id), _ZERO))
            for instrument_id in snapshot["instrument_id"].astype(str).values
        ]
        return pd.DataFrame(
            {
                "instrument_id": snapshot["instrument_id"].astype(str).values,
                "target_contracts": contract_targets,
                "price": snapshot["price"].astype(float).values,
            }
        )

    def size_positions(
        self, signals: pd.DataFrame, portfolio_value: Decimal, max_positions: int
    ) -> pd.DataFrame:
        del max_positions
        if signals.empty or portfolio_value <= _ZERO:
            return pd.DataFrame(columns=["instrument_id", "target_weight"])

        portfolio_value_float = float(portfolio_value)
        target_weights = (
            signals["target_contracts"].astype(float) * signals["price"].astype(float)
        ) / portfolio_value_float
        return pd.DataFrame(
            {
                "instrument_id": signals["instrument_id"].astype(str).values,
                "target_weight": target_weights.values,
            }
        )


class _FlatVecStrategy(VecStrategy):
    """Never trades."""

    name = "flat_vec"

    def generate_signals(self, features: pd.DataFrame, universe: list[str]) -> pd.DataFrame:
        del features
        return pd.DataFrame({"instrument_id": universe, "signal": [0.0] * len(universe)})

    def size_positions(
        self, signals: pd.DataFrame, portfolio_value: Decimal, max_positions: int
    ) -> pd.DataFrame:
        del signals
        del portfolio_value
        del max_positions
        return pd.DataFrame(columns=["instrument_id", "target_weight"])


def _market_order(instrument_id: str, delta: Decimal) -> BacktestOrderIntent:
    if delta == _ZERO:
        raise ValueError("delta must be non-zero")
    side = Side.LONG if delta > _ZERO else Side.SHORT
    return BacktestOrderIntent(
        instrument_id=instrument_id,
        side=side,
        size=abs(delta),
        order_type="market",
    )


def _orders_for_target(
    instrument_id: str,
    current: Decimal,
    target: Decimal,
) -> list[BacktestOrderIntent]:
    if current == target:
        return []
    if current == _ZERO:
        return [_market_order(instrument_id, target)]
    if target == _ZERO:
        return [_market_order(instrument_id, -current)]
    if _same_sign(current, target):
        return [_market_order(instrument_id, target - current)]
    return [
        _market_order(instrument_id, -current),
        _market_order(instrument_id, target),
    ]


def _same_sign(left: Decimal, right: Decimal) -> bool:
    return (left > _ZERO and right > _ZERO) or (left < _ZERO and right < _ZERO)


def _signed_position_size(position: PositionState | None) -> Decimal:
    if position is None:
        return _ZERO
    return position.size if position.side == Side.LONG else -position.size


def _trade_signature(
    result_trades: Sequence[exec_models.SimulatedFill],
) -> list[tuple[datetime, str, str, Decimal, Decimal]]:
    signatures = [
        (
            fill.timestamp,
            fill.order.instrument_id,
            fill.order.side.value,
            fill.fill_size,
            fill.fill_price,
        )
        for fill in result_trades
    ]
    return sorted(signatures)


def _curve_timestamps(curve: list[tuple[datetime, Decimal]]) -> list[datetime]:
    return [timestamp for timestamp, _equity in curve]


def _has_unique_timestamps(curve: list[tuple[datetime, Decimal]]) -> bool:
    timestamps = _curve_timestamps(curve)
    return len(timestamps) == len(set(timestamps))


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
        ).run(_FlatEventStrategy(), dataset)

        vec_result = VecBacktestEngine(
            VecBacktestConfig(
                dataset_id="cong_test",
                initial_cash=_INITIAL_CASH,
                fee_bps=Decimal("0"),
                rebalance_frequency="1D",
            )
        ).run(_FlatVecStrategy(), dataset, _make_trades_table())

        expected_initial_snapshot = (_T0, _INITIAL_CASH, _INITIAL_CASH, _ZERO)
        assert event_result.equity_curve[0] == (_T0, _INITIAL_CASH)
        assert vec_result.equity_curve[0] == (_T0, _INITIAL_CASH)
        assert event_result.equity_snapshots[0] == expected_initial_snapshot
        assert vec_result.equity_snapshots[0] == expected_initial_snapshot
        assert event_result.final_portfolio.cash == _INITIAL_CASH
        assert event_result.final_portfolio.equity == _INITIAL_CASH
        assert vec_result.final_portfolio.cash == _INITIAL_CASH
        assert vec_result.final_portfolio.equity == _INITIAL_CASH
        assert event_result.equity_curve == vec_result.equity_curve
        assert _has_unique_timestamps(vec_result.equity_curve)

    def test_engines_remain_aligned_across_rebalance_transitions(self) -> None:
        """Event and vectorized engines should agree across resize/flip/close branches."""
        trades_table = _make_trades_table(_PRICE_PATH)
        dataset = _MockDataset(trades_table)

        event_result = EventBacktestEngine(
            EventBacktestConfig(
                dataset_id="cong_tol",
                initial_cash=_INITIAL_CASH,
                slippage_model="fixed",
                slippage_params={"bps": 0},
            )
        ).run(_ScheduledTargetsEventStrategy(_TARGET_SCHEDULE), dataset)

        vec_result = VecBacktestEngine(
            VecBacktestConfig(
                dataset_id="cong_tol",
                initial_cash=_INITIAL_CASH,
                fee_bps=Decimal("0"),
                rebalance_frequency="1D",
            )
        ).run(_ScheduledTargetsVecStrategy(_TARGET_SCHEDULE), dataset, trades_table)

        assert len(event_result.trades) == 7
        assert len(vec_result.trades) == 7
        assert _trade_signature(event_result.trades) == _trade_signature(vec_result.trades)

        assert event_result.final_portfolio.cash == vec_result.final_portfolio.cash
        assert event_result.final_portfolio.equity == vec_result.final_portfolio.equity
        assert set(event_result.final_portfolio.positions) == set(
            vec_result.final_portfolio.positions
        )
        event_position = event_result.final_portfolio.positions[_INSTRUMENT]
        vec_position = vec_result.final_portfolio.positions[_INSTRUMENT]
        assert event_position.side == vec_position.side
        assert event_position.size == vec_position.size
        assert event_position.entry_price == vec_position.entry_price
        assert event_position.current_price == vec_position.current_price

        assert event_result.equity_curve == vec_result.equity_curve
        assert _has_unique_timestamps(vec_result.equity_curve)

    def test_engines_align_on_bar_close_outputs_with_intraday_events(self) -> None:
        """Daily vector rebalances should match event outputs at shared bar-close timestamps."""
        trades_table = _make_trades_table(
            _INTRADAY_PRICE_PATH,
            timestamps=_INTRADAY_TIMESTAMPS,
        )
        dataset = _MockDataset(trades_table)

        event_result = EventBacktestEngine(
            EventBacktestConfig(
                dataset_id="cong_intraday",
                initial_cash=_INITIAL_CASH,
                slippage_model="fixed",
                slippage_params={"bps": 0},
            )
        ).run(_ScheduledTargetsEventStrategy(_INTRADAY_TARGET_SCHEDULE), dataset)

        vec_result = VecBacktestEngine(
            VecBacktestConfig(
                dataset_id="cong_intraday",
                initial_cash=_INITIAL_CASH,
                fee_bps=Decimal("0"),
                rebalance_frequency="1D",
            )
        ).run(_ScheduledTargetsVecStrategy(_INTRADAY_TARGET_SCHEDULE), dataset, trades_table)

        close_timestamps = set(_INTRADAY_CLOSE_TIMESTAMPS)
        event_close_curve = [
            point for point in event_result.equity_curve if point[0] in close_timestamps
        ]

        assert len(event_result.trades) == 4
        assert len(vec_result.trades) == 4
        assert _trade_signature(event_result.trades) == _trade_signature(vec_result.trades)
        assert _curve_timestamps(event_close_curve) == _INTRADAY_CLOSE_TIMESTAMPS
        assert _curve_timestamps(vec_result.equity_curve) == _INTRADAY_CLOSE_TIMESTAMPS
        assert event_close_curve == vec_result.equity_curve
        assert event_result.final_portfolio.cash == vec_result.final_portfolio.cash
        assert event_result.final_portfolio.equity == vec_result.final_portfolio.equity
        assert event_result.final_portfolio.positions == vec_result.final_portfolio.positions
        assert _has_unique_timestamps(vec_result.equity_curve)

    def test_engines_align_on_cross_sectional_rebalances(self) -> None:
        """Event and vector engines should agree on multi-instrument portfolio changes."""
        trades_table = _make_trades_table_from_rows(_CROSS_SECTIONAL_ROWS)
        dataset = _MockDataset(trades_table)

        event_result = EventBacktestEngine(
            EventBacktestConfig(
                dataset_id="cong_cross_sectional",
                initial_cash=_INITIAL_CASH,
                slippage_model="fixed",
                slippage_params={"bps": 0},
            )
        ).run(_CrossSectionalTargetsEventStrategy(_CROSS_SECTIONAL_TARGET_SCHEDULE), dataset)

        vec_result = VecBacktestEngine(
            VecBacktestConfig(
                dataset_id="cong_cross_sectional",
                initial_cash=_INITIAL_CASH,
                fee_bps=Decimal("0"),
                rebalance_frequency="1D",
            )
        ).run(
            _CrossSectionalTargetsVecStrategy(_CROSS_SECTIONAL_TARGET_SCHEDULE),
            dataset,
            trades_table,
        )

        close_timestamps = set(_CROSS_SECTIONAL_CLOSE_TIMESTAMPS)
        event_close_curve = [
            point for point in event_result.equity_curve if point[0] in close_timestamps
        ]

        assert len(event_result.trades) == 11
        assert len(vec_result.trades) == 11
        assert _trade_signature(event_result.trades) == _trade_signature(vec_result.trades)
        assert _curve_timestamps(event_close_curve) == _CROSS_SECTIONAL_CLOSE_TIMESTAMPS
        assert _curve_timestamps(vec_result.equity_curve) == _CROSS_SECTIONAL_CLOSE_TIMESTAMPS
        assert event_close_curve == vec_result.equity_curve
        assert event_result.final_portfolio.cash == vec_result.final_portfolio.cash
        assert event_result.final_portfolio.equity == vec_result.final_portfolio.equity
        assert event_result.final_portfolio.positions == vec_result.final_portfolio.positions
        assert _has_unique_timestamps(vec_result.equity_curve)

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
