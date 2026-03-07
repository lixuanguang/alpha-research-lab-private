"""EventBacktestEngine — tick-by-tick event-driven backtest engine.

Replays a gold-tier trade dataset event-by-event in timestamp order,
passing world state to a :class:`~apps.research.backtester.strategy.Strategy`
at each step and simulating order execution via
:class:`~alpha_core.execution.simulator.ExecutionSimulator`.

Usage::

    config = EventBacktestConfig(
        dataset_id="my_dataset",
        initial_cash=Decimal("5000"),
    )
    engine = EventBacktestEngine(config)
    result = engine.run(strategy, dataset)
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
from pydantic import BaseModel, ConfigDict, Field, field_validator

import alpha_core.execution.models as exec_models
import alpha_core.execution.simulator as sim_mod
import alpha_core.execution.slippage as slippage_mod
import alpha_core.portfolio.tracker as tracker_mod
from apps.research.backtester.result import BacktestResult, make_backtest_id
from apps.research.backtester.strategy import Strategy, StrategyState

_ZERO = Decimal("0")
_ONE = Decimal("1")


class EventBacktestConfig(BaseModel):
    """Configuration for an event-driven backtest run.

    ``slippage_model`` selects the slippage implementation:

    * ``"fixed"`` — uses ``slippage_params["bps"]`` (default: 10).
    * ``"book_depth"`` — walks the order book; falls back to 15 bps when
      book data is absent.
    """

    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(min_length=1)
    feature_set: str | None = None
    initial_cash: Decimal = Field(default=Decimal("10000"), gt=_ZERO)
    fee_schedule: exec_models.FeeSchedule = Field(default_factory=exec_models.FeeSchedule)
    slippage_model: str = Field(default="fixed", pattern=r"^(fixed|book_depth)$")
    slippage_params: dict[str, Any] = Field(default_factory=lambda: {"bps": 10})
    start: datetime | None = None
    end: datetime | None = None

    @field_validator("dataset_id")
    @classmethod
    def _strip(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("dataset_id must not be blank")
        return s


class EventBacktestEngine:
    """Tick-by-tick event-driven backtester.

    Args:
        config: Backtest configuration (fees, slippage, initial cash, etc.).
    """

    def __init__(self, config: EventBacktestConfig) -> None:
        self._config = config
        self._simulator = self._build_simulator(config)

    @property
    def config(self) -> EventBacktestConfig:
        return self._config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        strategy: Strategy,
        dataset: object,  # GoldDataset — typed loosely to avoid heavy dependency
        features: pa.Table | None = None,
        resolution_prices: dict[str, tuple[Decimal, datetime]] | None = None,
    ) -> BacktestResult:
        """Execute the backtest and return a :class:`BacktestResult`.

        Args:
            strategy: Strategy instance implementing :class:`Strategy`.
            dataset: :class:`~alpha_core.research.dataset.GoldDataset` handle.
            features: Optional pre-computed feature table with columns
                ``ts_event``, ``instrument_id``, plus one column per feature.
                Feature values for each instrument are updated as-of each event.
            resolution_prices: Optional dict mapping ``instrument_id`` →
                ``(resolved_price, resolved_at_utc)``.  When the engine
                processes an event at or after ``resolved_at_utc``, it calls
                ``strategy.on_resolution`` and settles the position.

        Returns:
            :class:`BacktestResult` with full trade history and equity curve.
        """
        t_start = time.monotonic()

        trades_table = dataset.trades()  # type: ignore[attr-defined]
        trades_table = self._apply_time_filter(trades_table)

        if trades_table.num_rows == 0:
            return self._empty_result(strategy, t_start)

        universe = list(
            set(trades_table.column("instrument_id").to_pylist())
        )

        tracker = tracker_mod.PortfolioTracker(self._config.initial_cash)
        features_index = self._build_features_index(features)
        resolved_set: set[str] = set()

        strategy.on_init(universe)

        latest_prices: dict[str, Decimal] = {}
        all_fills: list[exec_models.SimulatedFill] = []

        # Sort by ts_event — gold tables are usually sorted, but enforce.
        sorted_table = trades_table.sort_by("ts_event")

        for row_idx in range(sorted_table.num_rows):
            row = _row_dict(sorted_table, row_idx)
            instr = str(row["instrument_id"])
            price = Decimal(str(row["price"]))
            ts = _to_datetime(row["ts_event"])

            latest_prices[instr] = price

            # --- Resolutions ---
            if resolution_prices:
                for res_instr, (res_price, res_at) in resolution_prices.items():
                    if res_instr not in resolved_set and ts >= res_at:
                        strategy.on_resolution(res_instr, res_price)
                        tracker.apply_resolution(res_instr, res_price)
                        resolved_set.add(res_instr)

            # --- Update feature state ---
            current_features = self._current_features(features_index, instr, ts)

            # --- Strategy callback ---
            port_state = tracker.state()
            state = StrategyState(
                timestamp=ts,
                portfolio=port_state,
                latest_prices=dict(latest_prices),
                features=current_features,
                universe=universe,
            )
            intents = strategy.on_data(ts, state)

            # --- Simulate fills ---
            for intent in intents:
                fill = self._simulator.simulate_fill(
                    intent,
                    last_trade_price=latest_prices.get(intent.instrument_id),
                    timestamp=ts,
                )
                if fill is not None:
                    tracker.apply_fill(fill)
                    all_fills.append(fill)

            # --- Mark to market ---
            tracker.mark_to_market(latest_prices, ts)

        duration = time.monotonic() - t_start
        config_dict = self._config.model_dump(mode="json")

        return BacktestResult(
            backtest_id=make_backtest_id(config_dict, strategy.name),
            config_snapshot=config_dict,
            strategy_name=strategy.name,
            trades=all_fills,
            equity_curve=tracker.equity_curve(),
            final_portfolio=tracker.state(),
            duration_seconds=duration,
            event_count=sorted_table.num_rows,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_simulator(config: EventBacktestConfig) -> sim_mod.ExecutionSimulator:
        if config.slippage_model == "fixed":
            bps = Decimal(str(config.slippage_params.get("bps", 10)))
            slip = slippage_mod.FixedSlippage(bps=bps)
        else:
            slip = slippage_mod.BookDepthSlippage()
        return sim_mod.ExecutionSimulator(
            fee_schedule=config.fee_schedule,
            slippage_model=slip,
        )

    def _apply_time_filter(self, table: pa.Table) -> pa.Table:
        if "ts_event" not in table.schema.names:
            return table
        if self._config.start is not None:
            ts_arr = table.column("ts_event")
            start_ts = pa.scalar(self._config.start, type=pa.timestamp("us", tz="UTC"))
            table = table.filter(pc.greater_equal(ts_arr, start_ts))
        if self._config.end is not None:
            ts_arr = table.column("ts_event")
            end_ts = pa.scalar(self._config.end, type=pa.timestamp("us", tz="UTC"))
            table = table.filter(pc.less_equal(ts_arr, end_ts))
        return table

    @staticmethod
    def _build_features_index(
        features: pa.Table | None,
    ) -> dict[str, list[tuple[datetime, dict[str, float]]]] | None:
        """Pre-index features as {instrument_id -> [(ts, {feat: val}), ...]} sorted by ts."""
        if features is None:
            return None
        if "instrument_id" not in features.schema.names:
            return None

        # Identify feature columns (everything except the index columns).
        skip = {"ts_event", "instrument_id"}
        feat_cols = [c for c in features.schema.names if c not in skip]
        if not feat_cols:
            return None

        df = features.to_pandas()
        index: dict[str, list[tuple[datetime, dict[str, float]]]] = {}

        for instr, grp in df.groupby("instrument_id"):
            grp_sorted = grp.sort_values("ts_event")
            rows: list[tuple[datetime, dict[str, float]]] = []
            for _, r in grp_sorted.iterrows():
                ts = r["ts_event"].to_pydatetime().replace(tzinfo=UTC)
                feats = {c: float(r[c]) for c in feat_cols if not pd.isna(r[c])}
                rows.append((ts, feats))
            index[str(instr)] = rows
        return index

    @staticmethod
    def _current_features(
        index: dict[str, list[tuple[datetime, dict[str, float]]]] | None,
        instrument_id: str,
        ts: datetime,
    ) -> dict[str, dict[str, float]] | None:
        """Return {instrument_id: {feat: val}} for instruments with latest data ≤ ts."""
        if index is None:
            return None
        rows = index.get(instrument_id)
        if not rows:
            return None
        # As-of: find latest row with ts_event <= current ts.
        latest_feats: dict[str, float] | None = None
        for row_ts, feats in rows:
            if row_ts <= ts:
                latest_feats = feats
            else:
                break
        if latest_feats is None:
            return None
        return {instrument_id: latest_feats}

    def _empty_result(self, strategy: Strategy, t_start: float) -> BacktestResult:
        from alpha_core.portfolio.models import PortfolioState
        duration = time.monotonic() - t_start
        dummy_portfolio = PortfolioState(
            timestamp=datetime.now(tz=UTC),
            cash=self._config.initial_cash,
            positions={},
            total_pnl=_ZERO,
            total_fees=_ZERO,
            equity=self._config.initial_cash,
        )
        return BacktestResult(
            backtest_id=make_backtest_id(
                self._config.model_dump(mode="json"), strategy.name
            ),
            config_snapshot=self._config.model_dump(mode="json"),
            strategy_name=strategy.name,
            trades=[],
            equity_curve=[],
            final_portfolio=dummy_portfolio,
            duration_seconds=duration,
            event_count=0,
        )


# ---------------------------------------------------------------------------
# Row-level helpers
# ---------------------------------------------------------------------------


def _row_dict(table: pa.Table, idx: int) -> dict[str, Any]:
    """Extract one row as a plain dict."""
    return {col: table.column(col)[idx].as_py() for col in table.schema.names}


def _to_datetime(value: Any) -> datetime:
    """Convert a PyArrow timestamp scalar to UTC-aware datetime."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
    # Fallback: treat as epoch microseconds.
    from datetime import timezone
    return datetime.fromtimestamp(float(value) / 1e6, tz=timezone.utc)


try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None  # type: ignore[assignment]


__all__ = ["EventBacktestConfig", "EventBacktestEngine"]
