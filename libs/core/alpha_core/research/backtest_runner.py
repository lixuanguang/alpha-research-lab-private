"""BacktestRunner — delayed-fill simulation over gold feature artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import pandas as pd  # type: ignore[import-untyped]
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, field_validator

import alpha_core.research.artifact_paths as artifact_paths
import alpha_core.research.manifest as manifest_mod
import alpha_core.research.run_context as run_context_mod
import alpha_core.strategy_framework.models as strategy_models
import alpha_core.utils.time as time_utils
from alpha_core.research.artifact_store import ArtifactNotFoundError, FilesystemArtifactStore

_EPSILON = 1e-9
_DEFAULT_PRICE = 0.5

_TRADES_SCHEMA = pa.schema(
    [
        pa.field("ts_event", pa.timestamp("us", tz="UTC")),
        pa.field("signal_ts", pa.timestamp("us", tz="UTC")),
        pa.field("instrument_id", pa.string()),
        pa.field("direction", pa.string()),
        pa.field("size", pa.float64()),
        pa.field("price", pa.float64()),
        pa.field("cash_impact", pa.float64()),
        pa.field("realized_pnl", pa.float64()),
        pa.field("trade_return", pa.float64()),
        pa.field("position_after", pa.float64()),
    ]
)

_EQUITY_SCHEMA = pa.schema(
    [
        pa.field("ts_event", pa.timestamp("us", tz="UTC")),
        pa.field("equity", pa.float64()),
        pa.field("cash", pa.float64()),
        pa.field("positions_value", pa.float64()),
    ]
)

EngineType = Literal["event", "vectorized"]


class BacktestConfig(BaseModel):
    """Configuration for a backtest run."""

    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(min_length=1)
    feature_set_version: str = Field(min_length=1)
    strategy_id: str = Field(min_length=1)
    engine: EngineType = "event"
    starting_cash: float = Field(default=100_000.0, gt=0)
    strategy_params: dict[str, float] = Field(
        default_factory=dict,
        description="Optional per-trial overrides for strategy parameters (threshold, target_weight).",
    )

    @field_validator("dataset_id", "feature_set_version", "strategy_id")
    @classmethod
    def _strip(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("field must not be blank")
        return cleaned


class BacktestManifest(BaseModel):
    """Persistent metadata for a completed backtest run."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1)
    run_id: str
    dataset_id: str
    feature_set_version: str
    strategy_id: str
    engine: str
    starting_cash: float
    built_at: datetime
    trade_count: int
    final_equity: float
    total_return: float
    artifacts: dict[str, str]
    parent_run_id: str | None = None


class BacktestRunError(RuntimeError):
    """Raised when the backtest cannot proceed."""


@dataclass(slots=True, frozen=True)
class StrategySpec:
    strategy_id: str
    family: Literal["zscore_mean_reversion", "zscore_momentum"]
    threshold: float
    target_weight: float


@dataclass(slots=True, frozen=True)
class PendingTarget:
    direction: strategy_models.SignalDirection
    signal_ts: datetime


class _FeatureMarketState(strategy_models.MarketState):
    feature_row: dict[str, float] = Field(default_factory=dict)


class _ZScoreStrategy:
    def __init__(self, spec: StrategySpec) -> None:
        self._spec = spec

    def direction(
        self,
        *,
        instrument_id: str,
        price: float,
        zscore: float,
        position_size: float,
        as_of: datetime,
    ) -> strategy_models.SignalDirection:
        state = _FeatureMarketState(
            as_of_utc=as_of,
            universe=[instrument_id],
            instruments={
                instrument_id: strategy_models.InstrumentState(
                    instrument_id=instrument_id,
                    last_trade_price=Decimal(str(price)),
                    mid_price=Decimal(str(price)),
                )
            },
            portfolio=(
                {instrument_id: Decimal(str(position_size))}
                if abs(position_size) > _EPSILON
                else {}
            ),
            feature_row={"zscore": zscore},
        )
        state.universe = self.select(state)
        targets = self.apply(self.targets(self.generate(state), state), state)
        if not targets:
            return strategy_models.SignalDirection.FLAT
        return targets[0].direction

    def select(self, state: strategy_models.MarketState) -> list[str]:
        if state.universe:
            return state.universe
        return list(state.instruments)

    def generate(self, state: strategy_models.MarketState) -> list[strategy_models.Signal]:
        instrument_id = state.universe[0] if state.universe else next(iter(state.instruments), None)
        if instrument_id is None:
            return []
        zscore = _coerce_float(getattr(state, "feature_row", {}).get("zscore"), default=0.0)
        threshold = max(self._spec.threshold, _EPSILON)
        conviction = min(abs(zscore) / threshold, 1.0)
        return [
            strategy_models.Signal(
                instrument_id=instrument_id,
                direction=_direction_from_zscore(zscore, self._spec),
                strength=Decimal(str(conviction)),
                confidence=Decimal(str(conviction)),
                metadata={"strategy_id": self._spec.strategy_id},
            )
        ]

    def targets(
        self,
        signals: list[strategy_models.Signal],
        state: strategy_models.MarketState,
    ) -> list[strategy_models.Target]:
        del state
        if not signals:
            return []
        signal = signals[0]
        target_weight = 0.0
        if signal.direction != strategy_models.SignalDirection.FLAT:
            target_weight = self._spec.target_weight
        return [
            strategy_models.Target(
                instrument_id=signal.instrument_id,
                target_weight=Decimal(str(target_weight)),
                direction=signal.direction,
                source_signal_id=signal.instrument_id,
            )
        ]

    def apply(
        self,
        targets: list[strategy_models.Target],
        state: strategy_models.MarketState,
    ) -> list[strategy_models.Target]:
        del state
        return targets


class BacktestRunner:
    """Simulates a strategy over feature artifacts from a prior feature-build run."""

    def __init__(
        self,
        storage_root: Path,
        store: FilesystemArtifactStore | None = None,
    ) -> None:
        self._storage_root = storage_root
        self._store = store if store is not None else FilesystemArtifactStore(storage_root)

    def build(
        self,
        config: BacktestConfig,
        *,
        config_payload: dict[str, Any] | None = None,
        parent_run_id: str | None = None,
    ) -> BacktestManifest:
        if parent_run_id is None:
            raise BacktestRunError(
                "A feature-build run id is required to locate features artifacts. "
                "Pass --parent-run-id pointing to a completed build-features run."
            )

        try:
            features_path = self._store.path_for(parent_run_id, "features.parquet")
        except ArtifactNotFoundError as exc:
            raise BacktestRunError(
                f"Feature artifact not found for run '{parent_run_id}': {exc}. "
                "Ensure the feature-build run completed successfully."
            ) from exc

        effective_payload = (
            config_payload if config_payload is not None else config.model_dump(mode="json")
        )
        run_context = run_context_mod.make_run_context("backtest", config_payload=effective_payload)
        run_id = run_context.run_id
        strategy = _ZScoreStrategy(_resolve_strategy_spec(config.strategy_id, config.strategy_params))
        trades_table, equity_table = _simulate(
            features_df=pq.read_table(features_path).to_pandas(),
            config=config,
            strategy=strategy,
        )

        trades_path = self._store.prepare_path(run_id, "trades.parquet")
        equity_path = self._store.prepare_path(run_id, "equity.parquet")
        pq.write_table(trades_table, trades_path, compression="zstd")
        pq.write_table(equity_table, equity_path, compression="zstd")

        completed_context = run_context_mod.close_run_context(run_context)
        built_at = completed_context.completed_at_utc or datetime.now(tz=UTC)
        final_equity = config.starting_cash
        if equity_table.num_rows > 0:
            final_equity = float(equity_table.column("equity").to_pylist()[-1])

        artifact_map: dict[str, str] = {
            "trades": str(trades_path),
            "equity": str(equity_path),
            "dataset_id": config.dataset_id,
            "feature_set_version": config.feature_set_version,
            "strategy_id": config.strategy_id,
        }
        backtest_manifest = BacktestManifest(
            run_id=run_id,
            dataset_id=config.dataset_id,
            feature_set_version=config.feature_set_version,
            strategy_id=config.strategy_id,
            engine=config.engine,
            starting_cash=config.starting_cash,
            built_at=built_at,
            trade_count=trades_table.num_rows,
            final_equity=final_equity,
            total_return=(final_equity - config.starting_cash) / config.starting_cash,
            artifacts=artifact_map,
            parent_run_id=parent_run_id,
        )

        manifest_path = self._store.prepare_path(run_id, "backtest_manifest.json")
        manifest_path.write_text(backtest_manifest.model_dump_json(indent=2), encoding="utf-8")
        artifact_map["backtest_manifest"] = str(manifest_path)

        manifest_mod.persist_run_record(
            storage_root=self._storage_root,
            run_context=completed_context,
            config_payload=effective_payload,
            artifacts=artifact_map,
            parent_run_id=parent_run_id,
        )
        return backtest_manifest


def _simulate(
    *,
    features_df: pd.DataFrame,
    config: BacktestConfig,
    strategy: _ZScoreStrategy,
) -> tuple[pa.Table, pa.Table]:
    frame = _prepare_features(
        features_df=features_df,
        engine=config.engine,
        strategy_spec=strategy._spec,
    )
    if frame is None:
        return _empty_simulation()

    cash = config.starting_cash
    positions: dict[str, float] = {}
    average_costs: dict[str, float] = {}
    last_prices: dict[str, float] = {}
    pending_targets: dict[str, PendingTarget] = {}
    trades: list[dict[str, object]] = []
    equity_rows: list[dict[str, object]] = []

    for row in frame.itertuples(index=False):
        instrument_id = str(row.instrument_id)
        execution_ts = _coerce_timestamp(row.execution_ts)
        price = _coerce_price(row.execution_price)
        last_prices[instrument_id] = price

        pending = pending_targets.pop(instrument_id, None)
        if pending is not None:
            cash, trade = _rebalance_to_target(
                instrument_id=instrument_id,
                signal_ts=pending.signal_ts,
                execution_ts=execution_ts,
                direction=pending.direction,
                target_weight=strategy._spec.target_weight,
                price=price,
                cash=cash,
                positions=positions,
                average_costs=average_costs,
                last_prices=last_prices,
            )
            if trade is not None:
                trades.append(trade)

        positions_value = _mark_to_market(positions, last_prices)
        equity_rows.append(
            {
                "ts_event": execution_ts,
                "equity": cash + positions_value,
                "cash": cash,
                "positions_value": positions_value,
            }
        )

        if config.engine == "event":
            direction = strategy.direction(
                instrument_id=instrument_id,
                price=price,
                zscore=_coerce_float(row.zscore, default=0.0),
                position_size=positions.get(instrument_id, 0.0),
                as_of=execution_ts,
            )
        else:
            direction = strategy_models.SignalDirection(str(row.planned_direction))

        pending_targets[instrument_id] = PendingTarget(
            direction=direction,
            signal_ts=execution_ts,
        )

    return _finalize_simulation(trades, equity_rows)


def _prepare_features(
    *,
    features_df: pd.DataFrame,
    engine: EngineType,
    strategy_spec: StrategySpec,
) -> pd.DataFrame | None:
    if features_df.empty:
        return None

    zscore_col = next((col for col in features_df.columns if col.startswith("price_zscore_")), None)
    price_col = (
        "price"
        if "price" in features_df.columns
        else next(
            (col for col in features_df.columns if col.startswith("price_mean_")),
            None,
        )
    )
    if zscore_col is None or price_col is None or "instrument_id" not in features_df.columns:
        return None

    sequence_col = "ts_available" if "ts_available" in features_df.columns else "ts_event"
    if sequence_col not in features_df.columns:
        return None

    prepared = features_df.copy()
    prepared["instrument_id"] = prepared["instrument_id"].astype(str)
    prepared["execution_ts"] = pd.to_datetime(prepared[sequence_col], utc=True, errors="coerce")
    prepared["event_ts"] = pd.to_datetime(
        prepared.get("ts_event", prepared["execution_ts"]),
        utc=True,
        errors="coerce",
    )
    prepared = prepared.dropna(subset=["instrument_id", "execution_ts"])
    prepared = prepared.sort_values(
        ["execution_ts", "instrument_id", "event_ts"],
        kind="stable",
    ).reset_index(drop=True)
    prepared["zscore"] = prepared[zscore_col].map(lambda value: _coerce_float(value, default=0.0))
    prepared["execution_price"] = prepared[price_col].map(_coerce_price)

    columns = ["instrument_id", "execution_ts", "zscore", "execution_price"]
    if engine == "vectorized":
        prepared["planned_direction"] = _vectorized_directions(
            prepared["zscore"],
            strategy_spec,
        )
        columns.append("planned_direction")
    return prepared.loc[:, columns]


def _rebalance_to_target(
    *,
    instrument_id: str,
    signal_ts: datetime,
    execution_ts: datetime,
    direction: strategy_models.SignalDirection,
    target_weight: float,
    price: float,
    cash: float,
    positions: dict[str, float],
    average_costs: dict[str, float],
    last_prices: dict[str, float],
) -> tuple[float, dict[str, object] | None]:
    current_equity = cash + _mark_to_market(positions, last_prices)
    current_quantity = positions.get(instrument_id, 0.0)
    desired_quantity = _target_notional(current_equity, target_weight, direction) / max(
        price,
        _EPSILON,
    )
    quantity_delta = desired_quantity - current_quantity
    if abs(quantity_delta) <= _EPSILON:
        return cash, None

    realized_pnl, trade_return, updated_quantity, updated_avg_cost = _apply_fill(
        current_quantity=current_quantity,
        current_avg_cost=average_costs.get(instrument_id, price),
        trade_quantity=quantity_delta,
        execution_price=price,
    )
    if abs(updated_quantity) <= _EPSILON:
        positions.pop(instrument_id, None)
        average_costs.pop(instrument_id, None)
    else:
        positions[instrument_id] = updated_quantity
        average_costs[instrument_id] = updated_avg_cost

    cash_impact = -(quantity_delta * price)
    cash += cash_impact
    trade_direction = (
        strategy_models.SignalDirection.LONG
        if quantity_delta > 0
        else strategy_models.SignalDirection.SHORT
    )
    return cash, {
        "ts_event": execution_ts,
        "signal_ts": signal_ts,
        "instrument_id": instrument_id,
        "direction": trade_direction.value,
        "size": abs(quantity_delta),
        "price": price,
        "cash_impact": cash_impact,
        "realized_pnl": realized_pnl,
        "trade_return": trade_return,
        "position_after": updated_quantity,
    }


def _apply_fill(
    *,
    current_quantity: float,
    current_avg_cost: float,
    trade_quantity: float,
    execution_price: float,
) -> tuple[float, float | None, float, float]:
    if abs(current_quantity) <= _EPSILON:
        return 0.0, None, trade_quantity, execution_price

    if (current_quantity > 0) == (trade_quantity > 0):
        new_quantity = current_quantity + trade_quantity
        new_avg_cost = (
            abs(current_quantity) * current_avg_cost + abs(trade_quantity) * execution_price
        ) / max(abs(new_quantity), _EPSILON)
        return 0.0, None, new_quantity, new_avg_cost

    closed_quantity = min(abs(current_quantity), abs(trade_quantity))
    if current_quantity > 0:
        realized_pnl = closed_quantity * (execution_price - current_avg_cost)
    else:
        realized_pnl = closed_quantity * (current_avg_cost - execution_price)

    closed_notional = closed_quantity * max(current_avg_cost, _EPSILON)
    trade_return = realized_pnl / closed_notional if closed_notional > _EPSILON else None
    new_quantity = current_quantity + trade_quantity
    if abs(new_quantity) <= _EPSILON:
        return realized_pnl, trade_return, 0.0, 0.0
    if (new_quantity > 0) == (current_quantity > 0):
        return realized_pnl, trade_return, new_quantity, current_avg_cost
    return realized_pnl, trade_return, new_quantity, execution_price


def _resolve_strategy_spec(strategy_id: str, params: dict[str, float] | None = None) -> StrategySpec:
    normalized = strategy_id.strip().lower()
    params = params or {}
    threshold = float(params.get("threshold", 1.5))
    target_weight = float(params.get("target_weight", 0.02))
    if normalized.startswith("zscore") and "momentum" in normalized:
        return StrategySpec(
            strategy_id=strategy_id,
            family="zscore_momentum",
            threshold=threshold,
            target_weight=target_weight,
        )
    if normalized.startswith("zscore"):
        return StrategySpec(
            strategy_id=strategy_id,
            family="zscore_mean_reversion",
            threshold=threshold,
            target_weight=target_weight,
        )
    raise BacktestRunError(
        f"Unsupported strategy_id '{strategy_id}'. "
        "Built-in support currently covers the zscore_* strategy family."
    )


def _direction_from_zscore(
    zscore: float,
    strategy_spec: StrategySpec,
) -> strategy_models.SignalDirection:
    if strategy_spec.family == "zscore_momentum":
        if zscore >= strategy_spec.threshold:
            return strategy_models.SignalDirection.LONG
        if zscore <= -strategy_spec.threshold:
            return strategy_models.SignalDirection.SHORT
        return strategy_models.SignalDirection.FLAT

    if zscore <= -strategy_spec.threshold:
        return strategy_models.SignalDirection.LONG
    if zscore >= strategy_spec.threshold:
        return strategy_models.SignalDirection.SHORT
    return strategy_models.SignalDirection.FLAT


def _vectorized_directions(zscores: pd.Series, strategy_spec: StrategySpec) -> pd.Series:
    directions = pd.Series(
        strategy_models.SignalDirection.FLAT.value,
        index=zscores.index,
        dtype="object",
    )
    if strategy_spec.family == "zscore_momentum":
        directions.loc[zscores >= strategy_spec.threshold] = (
            strategy_models.SignalDirection.LONG.value
        )
        directions.loc[zscores <= -strategy_spec.threshold] = (
            strategy_models.SignalDirection.SHORT.value
        )
        return directions

    directions.loc[zscores <= -strategy_spec.threshold] = strategy_models.SignalDirection.LONG.value
    directions.loc[zscores >= strategy_spec.threshold] = strategy_models.SignalDirection.SHORT.value
    return directions


def _finalize_simulation(
    trades: list[dict[str, object]],
    equity_rows: list[dict[str, object]],
) -> tuple[pa.Table, pa.Table]:
    trades_table = (
        pa.Table.from_pylist(trades, schema=_TRADES_SCHEMA)
        if trades
        else pa.table({name: [] for name in _TRADES_SCHEMA.names}, schema=_TRADES_SCHEMA)
    )
    equity_table = (
        pa.Table.from_pylist(equity_rows, schema=_EQUITY_SCHEMA)
        if equity_rows
        else pa.table({name: [] for name in _EQUITY_SCHEMA.names}, schema=_EQUITY_SCHEMA)
    )
    return trades_table, equity_table


def _empty_simulation() -> tuple[pa.Table, pa.Table]:
    return (
        pa.table({name: [] for name in _TRADES_SCHEMA.names}, schema=_TRADES_SCHEMA),
        pa.table({name: [] for name in _EQUITY_SCHEMA.names}, schema=_EQUITY_SCHEMA),
    )


def _mark_to_market(
    positions: dict[str, float],
    last_prices: dict[str, float],
) -> float:
    return sum(
        quantity * last_prices.get(instrument_id, 0.0)
        for instrument_id, quantity in positions.items()
    )


def _target_notional(
    equity: float,
    target_weight: float,
    direction: strategy_models.SignalDirection,
) -> float:
    if direction == strategy_models.SignalDirection.LONG:
        return equity * target_weight
    if direction == strategy_models.SignalDirection.SHORT:
        return -equity * target_weight
    return 0.0


def _coerce_float(value: object, *, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, float):
        if pd.isna(value):
            return default
        return value
    if isinstance(value, int | Decimal):
        return float(value)
    if not isinstance(value, str):
        return default
    try:
        converted = float(value)
    except ValueError:
        return default
    if pd.isna(converted):
        return default
    return converted


def _coerce_price(value: object) -> float:
    price = _coerce_float(value, default=_DEFAULT_PRICE)
    if price <= 0:
        return _DEFAULT_PRICE
    return price


def _coerce_timestamp(value: object) -> datetime:
    if isinstance(value, pd.Timestamp):
        return time_utils.ensure_utc(value.to_pydatetime())
    if isinstance(value, datetime):
        return time_utils.ensure_utc(value)
    raise BacktestRunError(f"Backtest encountered a non-datetime timestamp value: {value!r}")


__all__ = ["BacktestConfig", "BacktestManifest", "BacktestRunError", "BacktestRunner"]
