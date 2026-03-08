"""VecBacktestEngine — vectorized DataFrame-native backtester.

Runs a cross-sectional strategy at regular rebalance intervals over a gold
trade dataset.  Much faster than the event-driven engine for large universes
because it operates on pandas DataFrames rather than row-by-row callbacks.

Two key operations per rebalance period:
1. **Signal generation** — :meth:`VecStrategy.generate_signals` returns a
   cross-sectional signal for every instrument in the universe.
2. **Position sizing** — :meth:`VecStrategy.size_positions` converts signals
   to target portfolio weights.

Between rebalances, mark-to-market is applied using the latest prices.

Usage::

    config = VecBacktestConfig(dataset_id="my_ds", initial_cash=Decimal("5000"))
    engine = VecBacktestEngine(config)
    result = engine.run(strategy, dataset, feature_table)
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal, cast

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
from pydantic import BaseModel, ConfigDict, Field, field_validator

import alpha_core.execution.models as exec_models
import alpha_core.portfolio.models as portfolio_models
import alpha_core.portfolio.tracker as tracker_mod
import apps.research.backtester.result as result_mod
import apps.research.backtester.vec_strategy as vec_strategy_mod

_ZERO = Decimal("0")
_ONE = Decimal("1")
_PRICE_PREC = Decimal("0.000001")
_SIZE_PREC = Decimal("0.000001")
_BPS = Decimal("10000")


class VecBacktestConfig(BaseModel):
    """Configuration for a vectorized backtest run.

    ``rebalance_frequency`` uses pandas frequency aliases (e.g. ``"1D"``,
    ``"1H"``, ``"15min"``).  The engine resamples the event stream to this
    grid and runs signal/sizing logic at each bar boundary.
    """

    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(min_length=1)
    feature_set: str | None = None
    initial_cash: Decimal = Field(default=Decimal("10000"), gt=_ZERO)
    fee_bps: Decimal = Field(default=_ZERO, ge=_ZERO)
    position_sizing: Literal["equal_weight", "kelly", "fixed_size"] = "equal_weight"
    rebalance_frequency: str = Field(default="1D", min_length=1)
    max_positions: int = Field(default=50, gt=0)
    start: datetime | None = None
    end: datetime | None = None

    @field_validator("dataset_id")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("dataset_id must not be blank")
        return v


class VecBacktestEngine:
    """Vectorized backtester: cross-sectional, DataFrame-native.

    Args:
        config: Backtest configuration (cash, fees, rebalance frequency, etc.).
    """

    def __init__(self, config: VecBacktestConfig) -> None:
        self._config = config

    @property
    def config(self) -> VecBacktestConfig:
        return self._config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        strategy: vec_strategy_mod.VecStrategy,
        dataset: object,  # GoldDataset — typed loosely to avoid heavy dependency
        feature_table: pa.Table | None = None,
        resolution_prices: dict[str, tuple[Decimal, datetime]] | None = None,
    ) -> result_mod.BacktestResult:
        """Execute the vectorized backtest.

        Args:
            strategy: Strategy implementing :class:`VecStrategy`.
            dataset: Gold dataset handle with a ``trades()`` method.
            feature_table: Optional pre-built feature table.
            resolution_prices: Optional ``{instrument_id: (price, resolved_at)}``
                for PM binary resolution handling.

        Returns:
            :class:`~apps.research.backtester.result.BacktestResult`.
        """
        t_start = time.monotonic()

        trades_table = dataset.trades()  # type: ignore[attr-defined]
        trades_table = self._apply_time_filter(trades_table)

        if trades_table.num_rows == 0:
            return self._empty_result(strategy, t_start)

        # Convert to pandas for resampling.
        df = trades_table.to_pandas()
        sequence_col = _sequence_column_from_df(df)
        _normalize_utc_column(df, sequence_col)
        if "ts_event" in df.columns:
            _normalize_utc_column(df, "ts_event")

        sort_columns = [sequence_col]
        if "ts_event" in df.columns and sequence_col != "ts_event":
            sort_columns.append("ts_event")
        df = df.sort_values(sort_columns, kind="stable")
        df["price"] = df["price"].astype(float)

        universe = sorted(df["instrument_id"].unique().tolist())
        features_index = self._build_features_index(feature_table)

        tracker = tracker_mod.PortfolioTracker(self._config.initial_cash)
        all_fills: list[exec_models.SimulatedFill] = []
        resolved_set: set[str] = set()

        # Get rebalance bar boundaries.
        rebalance_bars = self._get_rebalance_bars(df)

        # Track latest prices across the whole run.
        latest_prices: dict[str, Decimal] = {}

        for bar_ts, bar_df in rebalance_bars:
            # Update latest prices from this bar's data.
            for instr, grp in bar_df.groupby("instrument_id"):
                last_price = Decimal(str(grp["price"].iloc[-1])).quantize(_PRICE_PREC)
                latest_prices[str(instr)] = last_price

            # Handle resolutions that occur within this bar.
            if resolution_prices:
                for res_instr, (res_price, res_at) in resolution_prices.items():
                    if res_instr not in resolved_set and bar_ts >= res_at:
                        tracker.apply_resolution(res_instr, res_price, timestamp=res_at)
                        resolved_set.add(res_instr)

            # Build feature snapshot for this bar.
            features_df = self._features_as_of(features_index, bar_ts, universe)

            # Get current portfolio state.
            port_state = tracker.state(timestamp=bar_ts)
            portfolio_value = port_state.equity

            # Strategy signal generation.
            signals_df = strategy.generate_signals(features_df, universe)
            if signals_df is not None and not signals_df.empty:
                # Position sizing.
                weights_df = strategy.size_positions(
                    signals_df,
                    portfolio_value,
                    self._config.max_positions,
                )

                # Compute trades from current → target weights.
                fills = self._compute_rebalance_fills(
                    weights_df=weights_df,
                    latest_prices=latest_prices,
                    portfolio_value=portfolio_value,
                    tracker=tracker,
                    bar_ts=bar_ts,
                )
                for fill in fills:
                    tracker.apply_fill(fill)
                    all_fills.append(fill)

            # Mark-to-market.
            tracker.mark_to_market(latest_prices, bar_ts)

        # Final mark-to-market only when the last processed bar did not already
        # land on the final event timestamp.
        final_ts = _last_ts(df)
        if latest_prices:
            equity_curve = tracker.equity_curve()
            last_snapshot_ts = equity_curve[-1][0] if equity_curve else None
            if last_snapshot_ts != final_ts:
                tracker.mark_to_market(latest_prices, final_ts)

        duration = time.monotonic() - t_start
        config_dict = self._config.model_dump(mode="json")

        return result_mod.BacktestResult(
            backtest_id=result_mod.make_backtest_id(config_dict, strategy.name),
            config_snapshot=config_dict,
            strategy_name=strategy.name,
            trades=all_fills,
            equity_curve=tracker.equity_curve(),
            final_portfolio=tracker.state(timestamp=final_ts),
            closed_positions=tracker.position_history(),
            equity_snapshots=tracker.equity_snapshots(),
            duration_seconds=duration,
            event_count=trades_table.num_rows,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_rebalance_bars(
        self, df: pd.DataFrame
    ) -> list[tuple[datetime, pd.DataFrame]]:
        """Group the trade data by rebalance_frequency bars.

        Returns a list of ``(bar_timestamp, bar_df)`` pairs sorted chronologically.
        ``bar_timestamp`` is the last observed execution timestamp in the bucket,
        so the engine never prices or timestamps a rebalance before the data used
        to build that rebalance is actually available.
        """
        sequence_col = _sequence_column_from_df(df)
        try:
            df["_bar"] = df[sequence_col].dt.floor(self._config.rebalance_frequency)
        except ValueError:
            # Fallback: group by calendar day.
            df["_bar"] = df[sequence_col].dt.floor("1D")

        bars: list[tuple[datetime, pd.DataFrame]] = []
        for _, grp in df.groupby("_bar", sort=True):
            bar_df = grp.drop(columns=["_bar"])
            bar_ts = _to_utc_datetime(bar_df[sequence_col].iloc[-1])
            bars.append((bar_ts, bar_df))
        return bars

    def _compute_rebalance_fills(
        self,
        *,
        weights_df: pd.DataFrame,
        latest_prices: dict[str, Decimal],
        portfolio_value: Decimal,
        tracker: tracker_mod.PortfolioTracker,
        bar_ts: datetime,
    ) -> list[exec_models.SimulatedFill]:
        """Convert target weights → SimulatedFill objects.

        For each instrument in weights_df, compute the delta between current
        position value and target position value.  Create a synthetic market
        order fill for the delta.
        """
        if weights_df is None or weights_df.empty:
            return []

        fills: list[exec_models.SimulatedFill] = []
        current_state = tracker.state()
        current_positions = current_state.positions

        # Build target positions dict: instrument → target_weight.
        target: dict[str, float] = {}
        if "instrument_id" in weights_df.columns and "target_weight" in weights_df.columns:
            for _, row in weights_df.iterrows():
                instr = str(row["instrument_id"])
                w = float(row["target_weight"])
                if w != 0.0:
                    target[instr] = w

        # Also close any open positions that are no longer in the target.
        instr_to_close: set[str] = set(current_positions.keys()) - set(target.keys())
        for instr in instr_to_close:
            pos = current_positions[instr]
            ref_price = latest_prices.get(instr, Decimal("0.5"))
            fill = self._make_fill(
                instrument_id=instr,
                delta_size=pos.size,
                side=(
                    portfolio_models.Side.SHORT
                    if pos.side == portfolio_models.Side.LONG
                    else portfolio_models.Side.LONG
                ),
                ref_price=ref_price,
                ts=bar_ts,
            )
            if fill is not None:
                fills.append(fill)

        # For each target, compute delta vs current holding.
        for instr, weight in target.items():
            ref_price = latest_prices.get(instr, Decimal("0.5"))
            if ref_price == _ZERO:
                continue

            # Target value = |weight| x portfolio_value
            target_value = abs(Decimal(str(weight))) * portfolio_value
            # Target size (number of contracts)
            target_size = (target_value / ref_price).quantize(_SIZE_PREC, ROUND_HALF_UP)
            target_side = (
                portfolio_models.Side.LONG
                if weight > 0
                else portfolio_models.Side.SHORT
            )

            # Current size/side held.
            current_size = _ZERO
            current_side: portfolio_models.Side | None = None
            if instr in current_positions:
                pos = current_positions[instr]
                current_size = pos.size
                current_side = pos.side

            # Determine the fill needed.
            if current_side is None:
                # No position → open.
                if target_size > _ZERO:
                    fill = self._make_fill(
                        instrument_id=instr,
                        delta_size=target_size,
                        side=target_side,
                        ref_price=ref_price,
                        ts=bar_ts,
                    )
                    if fill is not None:
                        fills.append(fill)
            elif current_side == target_side:
                # Same side → adjust size.
                delta = target_size - current_size
                if abs(delta) >= Decimal("0.000001"):
                    adj_side = target_side if delta > _ZERO else (

                            portfolio_models.Side.SHORT
                            if target_side == portfolio_models.Side.LONG
                            else portfolio_models.Side.LONG

                    )
                    fill = self._make_fill(
                        instrument_id=instr,
                        delta_size=abs(delta),
                        side=adj_side,
                        ref_price=ref_price,
                        ts=bar_ts,
                    )
                    if fill is not None:
                        fills.append(fill)
            else:
                # Opposite side → close current, open target.
                close_side = (
                    portfolio_models.Side.SHORT
                    if current_side == portfolio_models.Side.LONG
                    else portfolio_models.Side.LONG
                )
                fill = self._make_fill(
                    instrument_id=instr,
                    delta_size=current_size,
                    side=close_side,
                    ref_price=ref_price,
                    ts=bar_ts,
                )
                if fill is not None:
                    fills.append(fill)
                if target_size > _ZERO:
                    fill = self._make_fill(
                        instrument_id=instr,
                        delta_size=target_size,
                        side=target_side,
                        ref_price=ref_price,
                        ts=bar_ts,
                    )
                    if fill is not None:
                        fills.append(fill)

        return fills

    def _make_fill(
        self,
        *,
        instrument_id: str,
        delta_size: Decimal,
        side: portfolio_models.Side,
        ref_price: Decimal,
        ts: datetime,
    ) -> exec_models.SimulatedFill | None:
        """Create a synthetic market-order fill for a vectorized rebalance trade."""
        if delta_size <= _ZERO:
            return None

        fill_price = max(_ZERO, min(_ONE, ref_price)).quantize(_PRICE_PREC)

        notional = delta_size * fill_price
        fee = (notional * self._config.fee_bps / _BPS).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        )

        order = exec_models.BacktestOrderIntent(
            instrument_id=instrument_id,
            side=side,
            size=delta_size,
            order_type="market",
        )
        return exec_models.SimulatedFill(
            order=order,
            fill_price=fill_price,
            fill_size=delta_size,
            fee=fee,
            timestamp=ts,
            slippage=_ZERO,
        )

    def _apply_time_filter(self, table: pa.Table) -> pa.Table:
        sequence_col = _sequence_column_from_table(table)
        if sequence_col not in table.schema.names:
            return table
        if self._config.start is not None:
            ts_arr = table.column(sequence_col)
            start_ts = pa.scalar(self._config.start, type=pa.timestamp("us", tz="UTC"))
            table = table.filter(pc.greater_equal(ts_arr, start_ts))
        if self._config.end is not None:
            ts_arr = table.column(sequence_col)
            end_ts = pa.scalar(self._config.end, type=pa.timestamp("us", tz="UTC"))
            table = table.filter(pc.less_equal(ts_arr, end_ts))
        return table

    @staticmethod
    def _build_features_index(
        feature_table: pa.Table | None,
    ) -> pd.DataFrame | None:
        """Convert features table to a sorted pandas DataFrame for as-of lookups."""
        if feature_table is None:
            return None
        df = feature_table.to_pandas()
        sequence_col = _sequence_column_from_df(df)
        if sequence_col in df.columns:
            _normalize_utc_column(df, sequence_col)
            if "ts_event" in df.columns:
                _normalize_utc_column(df, "ts_event")
            sort_columns = [sequence_col]
            if "ts_event" in df.columns and sequence_col != "ts_event":
                sort_columns.append("ts_event")
            df = df.sort_values(sort_columns, kind="stable")
        return df

    @staticmethod
    def _features_as_of(
        features_index: pd.DataFrame | None,
        bar_ts: datetime,
        universe: list[str],
    ) -> pd.DataFrame:
        """Return the most recent feature rows for each instrument up to bar_ts."""
        if features_index is None or features_index.empty:
            return pd.DataFrame({"instrument_id": universe})

        sequence_col = _sequence_column_from_df(features_index)
        if sequence_col not in features_index.columns:
            return features_index.copy()

        cutoff = pd.Timestamp(bar_ts)
        if cutoff.tzinfo is None:
            cutoff = cutoff.tz_localize("UTC")
        else:
            cutoff = cutoff.tz_convert("UTC")
        snapshot = features_index[features_index[sequence_col] <= cutoff]

        if snapshot.empty:
            return pd.DataFrame({"instrument_id": universe})

        if "instrument_id" in snapshot.columns:
            snapshot = snapshot.groupby("instrument_id").last().reset_index()

        return snapshot

    def _empty_result(
        self,
        strategy: vec_strategy_mod.VecStrategy,
        t_start: float,
    ) -> result_mod.BacktestResult:
        empty_timestamp = self._config.start or datetime(1970, 1, 1, tzinfo=UTC)
        dummy_portfolio = portfolio_models.PortfolioState(
            timestamp=empty_timestamp,
            cash=self._config.initial_cash,
            positions={},
            total_pnl=_ZERO,
            total_fees=_ZERO,
            equity=self._config.initial_cash,
        )
        config_dict = self._config.model_dump(mode="json")
        return result_mod.BacktestResult(
            backtest_id=result_mod.make_backtest_id(config_dict, strategy.name),
            config_snapshot=config_dict,
            strategy_name=strategy.name,
            trades=[],
            equity_curve=[],
            final_portfolio=dummy_portfolio,
            closed_positions=[],
            equity_snapshots=[],
            duration_seconds=time.monotonic() - t_start,
            event_count=0,
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _sequence_column_from_table(table: pa.Table) -> str:
    return "ts_available" if "ts_available" in table.schema.names else "ts_event"


def _sequence_column_from_df(df: pd.DataFrame) -> str:
    return "ts_available" if "ts_available" in df.columns else "ts_event"


def _normalize_utc_column(df: pd.DataFrame, column_name: str) -> None:
    if column_name not in df.columns:
        return
    series = df[column_name]
    if series.dt.tz is None:
        df[column_name] = series.dt.tz_localize("UTC")
        return
    df[column_name] = series.dt.tz_convert("UTC")


def _to_utc_datetime(ts: Any) -> datetime:
    """Convert pandas Timestamp or datetime to UTC-aware datetime."""
    if isinstance(ts, pd.Timestamp):
        dt = cast(datetime, ts.to_pydatetime())
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=UTC)
        return ts.astimezone(UTC)
    return datetime.fromtimestamp(float(ts) / 1e9, tz=UTC)


def _last_ts(df: pd.DataFrame) -> datetime:
    """Return the last execution timestamp in the DataFrame as UTC-aware datetime."""
    last = df[_sequence_column_from_df(df)].iloc[-1]
    return _to_utc_datetime(last)


__all__ = ["VecBacktestConfig", "VecBacktestEngine"]
