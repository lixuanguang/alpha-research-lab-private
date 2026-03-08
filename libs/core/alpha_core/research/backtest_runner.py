"""BacktestRunner — delayed-fill simulation over gold feature artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

import alpha_core.config.paths as config_paths
import alpha_core.features.factor_pack as factor_pack_mod
import alpha_core.research.artifact_store as artifact_store_mod
import alpha_core.research.feature_runner as feature_runner_mod
import alpha_core.research.manifest as manifest_mod
import alpha_core.research.run_context as run_context_mod
import alpha_core.research.strategy_recipe as strategy_recipe_mod
import alpha_core.strategy_framework.models as strategy_models
import alpha_core.utils.time as time_utils

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
        description=(
            "Optional per-trial overrides for strategy parameters (threshold, target_weight)."
        ),
    )
    strategy_recipe_id: str | None = Field(
        default=None,
        description="Optional strategy-recipe ID whose manifest drives configuration.",
    )
    strategy_recipe_version: str | None = Field(
        default=None,
        description="Resolved strategy-recipe version recorded in the backtest manifest.",
    )
    fee_bps: float = Field(default=0.0, ge=0.0)
    slippage_bps: float = Field(default=0.0, ge=0.0)
    max_position_pct: float | None = Field(default=None, gt=0.0, le=1.0)

    @field_validator("dataset_id", "feature_set_version", "strategy_id")
    @classmethod
    def _strip(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("field must not be blank")
        return cleaned

    @field_validator("strategy_recipe_id", "strategy_recipe_version")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("field must not be blank")
        return cleaned


class BacktestManifest(BaseModel):
    """Persistent metadata for a completed backtest run."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=2)
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
    strategy_recipe_id: str | None = None
    strategy_recipe_version: str | None = None


class BacktestRunError(RuntimeError):
    """Raised when the backtest cannot proceed."""


@dataclass(slots=True, frozen=True)
class StrategySpec:
    strategy_id: str
    family: Literal["zscore_mean_reversion", "zscore_momentum"]
    threshold: float
    target_weight: float
    fee_bps: float = 0.0
    slippage_bps: float = 0.0


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
        store: artifact_store_mod.FilesystemArtifactStore | None = None,
    ) -> None:
        self._storage_root = storage_root
        self._store = (
            store if store is not None else artifact_store_mod.FilesystemArtifactStore(storage_root)
        )

    def build(
        self,
        config: BacktestConfig,
        *,
        config_payload: dict[str, Any] | None = None,
        parent_run_id: str | None = None,
        session_id: str | None = None,
    ) -> BacktestManifest:
        required_parent_run_id = self._require_parent_run_id(parent_run_id)
        effective_payload = self._resolve_config_payload(config, config_payload)
        feature_manifest, features_df = self._load_feature_inputs(
            config=config,
            parent_run_id=required_parent_run_id,
        )
        resolved_recipe, recipe_zscore_column, strategy_spec = self._resolve_strategy_runtime(
            config=config,
            parent_run_id=required_parent_run_id,
            feature_manifest=feature_manifest,
            features_df=features_df,
        )
        run_context = run_context_mod.make_run_context(
            "backtest",
            config_payload=effective_payload,
            session_id=session_id,
        )
        run_id = run_context.run_id
        strategy = _ZScoreStrategy(strategy_spec)
        trades_table, equity_table = _simulate(
            features_df=features_df,
            config=config,
            strategy=strategy,
            zscore_column=recipe_zscore_column,
        )
        artifact_map = self._persist_output_tables(
            run_id=run_id,
            config=config,
            trades_table=trades_table,
            equity_table=equity_table,
            resolved_recipe=resolved_recipe,
        )

        completed_context = run_context_mod.close_run_context(run_context)
        backtest_manifest = self._build_manifest(
            run_id=run_id,
            config=config,
            parent_run_id=required_parent_run_id,
            completed_context=completed_context,
            trades_table=trades_table,
            equity_table=equity_table,
            artifact_map=artifact_map,
            resolved_recipe=resolved_recipe,
        )
        self._persist_run_record(
            run_context=completed_context,
            effective_payload=effective_payload,
            parent_run_id=required_parent_run_id,
            backtest_manifest=backtest_manifest,
        )
        return backtest_manifest

    @staticmethod
    def _require_parent_run_id(parent_run_id: str | None) -> str:
        if parent_run_id is None:
            raise BacktestRunError(
                "A feature-build run id is required to locate features artifacts. "
                "Pass --parent-run-id pointing to a completed build-features run."
            )
        return parent_run_id

    @staticmethod
    def _resolve_config_payload(
        config: BacktestConfig,
        config_payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if config_payload is not None:
            return config_payload
        return config.model_dump(mode="json")

    def _load_feature_inputs(
        self,
        *,
        config: BacktestConfig,
        parent_run_id: str,
    ) -> tuple[feature_runner_mod.FeatureManifest, pd.DataFrame]:
        features_path = self._require_feature_artifact(parent_run_id)
        feature_manifest = _load_feature_manifest(store=self._store, run_id=parent_run_id)
        _validate_feature_manifest_contract(
            config=config,
            parent_run_id=parent_run_id,
            feature_manifest=feature_manifest,
        )
        return feature_manifest, pq.read_table(features_path).to_pandas()

    def _require_feature_artifact(self, parent_run_id: str) -> Path:
        try:
            return self._store.path_for(parent_run_id, "features.parquet")
        except artifact_store_mod.ArtifactNotFoundError as exc:
            raise BacktestRunError(
                f"Feature artifact not found for run '{parent_run_id}': {exc}. "
                "Ensure the feature-build run completed successfully."
            ) from exc

    def _resolve_strategy_runtime(
        self,
        *,
        config: BacktestConfig,
        parent_run_id: str,
        feature_manifest: feature_runner_mod.FeatureManifest,
        features_df: pd.DataFrame,
    ) -> tuple[strategy_recipe_mod.StrategyRecipeManifest | None, str | None, StrategySpec]:
        resolved_recipe = resolve_strategy_recipe(
            config.strategy_recipe_id,
            expected_version=config.strategy_recipe_version,
        )
        effective_strategy_params = dict(config.strategy_params)
        effective_fee_bps = config.fee_bps
        effective_slippage_bps = config.slippage_bps
        effective_max_position_pct = config.max_position_pct
        recipe_zscore_column = None
        if resolved_recipe is not None:
            (
                effective_strategy_params,
                effective_fee_bps,
                effective_slippage_bps,
                effective_max_position_pct,
            ) = _merge_recipe_defaults(config=config, recipe=resolved_recipe)
            recipe_zscore_column = _validate_recipe_feature_contract(
                parent_run_id=parent_run_id,
                recipe=resolved_recipe,
                feature_manifest=feature_manifest,
                features_df=features_df,
            )
        strategy_spec = _resolve_strategy_spec(
            config.strategy_id,
            effective_strategy_params,
            max_position_pct=effective_max_position_pct,
            fee_bps=effective_fee_bps,
            slippage_bps=effective_slippage_bps,
        )
        return resolved_recipe, recipe_zscore_column, strategy_spec

    def _persist_output_tables(
        self,
        *,
        run_id: str,
        config: BacktestConfig,
        trades_table: pa.Table,
        equity_table: pa.Table,
        resolved_recipe: strategy_recipe_mod.StrategyRecipeManifest | None,
    ) -> dict[str, str]:
        trades_path = self._store.prepare_path(run_id, "trades.parquet")
        equity_path = self._store.prepare_path(run_id, "equity.parquet")
        pq.write_table(trades_table, trades_path, compression="zstd")
        pq.write_table(equity_table, equity_path, compression="zstd")

        artifact_map: dict[str, str] = {
            "trades": str(trades_path),
            "equity": str(equity_path),
            "dataset_id": config.dataset_id,
            "feature_set_version": config.feature_set_version,
            "strategy_id": config.strategy_id,
        }
        if resolved_recipe is not None:
            artifact_map["strategy_recipe_id"] = resolved_recipe.recipe_id
            artifact_map["strategy_recipe_version"] = resolved_recipe.version
        return artifact_map

    def _build_manifest(
        self,
        *,
        run_id: str,
        config: BacktestConfig,
        parent_run_id: str,
        completed_context: run_context_mod.RunContext,
        trades_table: pa.Table,
        equity_table: pa.Table,
        artifact_map: dict[str, str],
        resolved_recipe: strategy_recipe_mod.StrategyRecipeManifest | None,
    ) -> BacktestManifest:
        built_at = completed_context.completed_at_utc or datetime.now(tz=UTC)
        final_equity = self._resolve_final_equity(config.starting_cash, equity_table)
        return BacktestManifest(
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
            strategy_recipe_id=(
                resolved_recipe.recipe_id
                if resolved_recipe is not None
                else config.strategy_recipe_id
            ),
            strategy_recipe_version=(
                resolved_recipe.version
                if resolved_recipe is not None
                else config.strategy_recipe_version
            ),
        )

    @staticmethod
    def _resolve_final_equity(starting_cash: float, equity_table: pa.Table) -> float:
        if equity_table.num_rows == 0:
            return starting_cash
        return float(equity_table.column("equity").to_pylist()[-1])

    def _persist_run_record(
        self,
        *,
        run_context: run_context_mod.RunContext,
        effective_payload: dict[str, Any],
        parent_run_id: str,
        backtest_manifest: BacktestManifest,
    ) -> None:
        manifest_path = self._store.prepare_path(backtest_manifest.run_id, "backtest_manifest.json")
        backtest_manifest.artifacts["backtest_manifest"] = str(manifest_path)
        manifest_path.write_text(backtest_manifest.model_dump_json(indent=2), encoding="utf-8")
        manifest_mod.persist_run_record(
            storage_root=self._storage_root,
            run_context=run_context,
            config_payload=effective_payload,
            artifacts=backtest_manifest.artifacts,
            parent_run_id=parent_run_id,
        )


def _simulate(
    *,
    features_df: pd.DataFrame,
    config: BacktestConfig,
    strategy: _ZScoreStrategy,
    zscore_column: str | None = None,
) -> tuple[pa.Table, pa.Table]:
    frame = _prepare_features(
        features_df=features_df,
        engine=config.engine,
        strategy_spec=strategy._spec,
        zscore_column=zscore_column,
    )
    if frame.empty:
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

        pending = pending_targets.get(instrument_id)
        if pending is not None and execution_ts > pending.signal_ts:
            pending_targets.pop(instrument_id, None)
            cash, trade = _rebalance_to_target(
                instrument_id=instrument_id,
                signal_ts=pending.signal_ts,
                execution_ts=execution_ts,
                direction=pending.direction,
                target_weight=strategy._spec.target_weight,
                price=price,
                fee_bps=strategy._spec.fee_bps,
                slippage_bps=strategy._spec.slippage_bps,
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
    zscore_column: str | None = None,
) -> pd.DataFrame:
    if features_df.empty:
        columns = ["instrument_id", "execution_ts", "zscore", "execution_price"]
        if engine == "vectorized":
            columns.append("planned_direction")
        return pd.DataFrame(columns=columns)

    zscore_col = zscore_column
    if zscore_col is None:
        zscore_col = next(
            (col for col in features_df.columns if col.startswith("price_zscore_")),
            None,
        )
    price_col = (
        "price"
        if "price" in features_df.columns
        else next(
            (col for col in features_df.columns if col.startswith("price_mean_")),
            None,
        )
    )

    sequence_col = "ts_available" if "ts_available" in features_df.columns else "ts_event"
    missing_columns: list[str] = []
    if zscore_col is None:
        missing_columns.append("price_zscore_*")
    elif zscore_col not in features_df.columns:
        missing_columns.append(zscore_col)
    if price_col is None:
        missing_columns.append("price|price_mean_*")
    if "instrument_id" not in features_df.columns:
        missing_columns.append("instrument_id")
    if sequence_col not in features_df.columns:
        missing_columns.append("ts_available|ts_event")
    if missing_columns:
        raise BacktestRunError(
            "Feature artifact does not satisfy the backtest input contract. "
            f"Missing columns: {missing_columns}."
        )

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
    fee_bps: float,
    slippage_bps: float,
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

    execution_price = _apply_slippage(
        price,
        quantity_delta=quantity_delta,
        slippage_bps=slippage_bps,
    )
    realized_pnl, trade_return, updated_quantity, updated_avg_cost = _apply_fill(
        current_quantity=current_quantity,
        current_avg_cost=average_costs.get(instrument_id, price),
        trade_quantity=quantity_delta,
        execution_price=execution_price,
    )
    if abs(updated_quantity) <= _EPSILON:
        positions.pop(instrument_id, None)
        average_costs.pop(instrument_id, None)
    else:
        positions[instrument_id] = updated_quantity
        average_costs[instrument_id] = updated_avg_cost

    fee = abs(quantity_delta) * execution_price * (fee_bps / 10_000.0)
    cash_impact = -(quantity_delta * execution_price) - fee
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
        "price": execution_price,
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


def _resolve_strategy_spec(
    strategy_id: str,
    params: dict[str, float] | None = None,
    *,
    max_position_pct: float | None = None,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> StrategySpec:
    normalized = strategy_id.strip().lower()
    params = params or {}
    threshold = float(params.get("threshold", 1.5))
    target_weight = float(params.get("target_weight", 0.02))
    if max_position_pct is not None:
        target_weight = min(target_weight, max_position_pct)
    if normalized.startswith("zscore") and "momentum" in normalized:
        return StrategySpec(
            strategy_id=strategy_id,
            family="zscore_momentum",
            threshold=threshold,
            target_weight=target_weight,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
    if normalized.startswith("zscore"):
        return StrategySpec(
            strategy_id=strategy_id,
            family="zscore_mean_reversion",
            threshold=threshold,
            target_weight=target_weight,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
    raise BacktestRunError(
        f"Unsupported strategy_id '{strategy_id}'. "
        "Built-in support currently covers the zscore_* strategy family."
    )


def _apply_slippage(
    price: float,
    *,
    quantity_delta: float,
    slippage_bps: float,
) -> float:
    if slippage_bps <= 0:
        return price

    slip_fraction = slippage_bps / 10_000.0
    adjusted = price * (1.0 + slip_fraction if quantity_delta > 0 else 1.0 - slip_fraction)
    return min(max(adjusted, _EPSILON), 1.0)


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


def resolve_strategy_recipe(
    strategy_recipe_id: str | None,
    *,
    expected_version: str | None = None,
) -> strategy_recipe_mod.StrategyRecipeManifest | None:
    if strategy_recipe_id is None:
        return None

    recipe_dir = config_paths.find_project_root(__file__) / "config" / "research" / "recipes"
    available_recipes = _discover_strategy_recipes(recipe_dir)
    recipe = _resolve_recipe(
        strategy_recipe_id,
        available=available_recipes,
        expected_version=expected_version,
    )
    available_packs = _discover_factor_pack_ids()
    try:
        strategy_recipe_mod.validate_recipe(recipe, available_pack_ids=available_packs)
    except ValueError as exc:
        raise BacktestRunError(str(exc)) from exc
    return recipe


def _discover_strategy_recipes(
    recipe_dir: Path,
) -> list[strategy_recipe_mod.StrategyRecipeManifest]:
    if not recipe_dir.exists():
        raise BacktestRunError(f"Strategy-recipe config directory does not exist: {recipe_dir}")

    recipes: list[strategy_recipe_mod.StrategyRecipeManifest] = []
    for path in sorted(recipe_dir.glob("*.yaml")) + sorted(recipe_dir.glob("*.yml")):
        recipes.append(strategy_recipe_mod.load_strategy_recipe(path))
    for path in sorted(recipe_dir.glob("*.json")):
        recipes.append(strategy_recipe_mod.load_strategy_recipe(path))
    return recipes


def _resolve_recipe(
    recipe_id: str,
    *,
    available: list[strategy_recipe_mod.StrategyRecipeManifest],
    expected_version: str | None,
) -> strategy_recipe_mod.StrategyRecipeManifest:
    matches = [recipe for recipe in available if recipe.recipe_id == recipe_id]
    if expected_version is not None:
        matches = [recipe for recipe in matches if recipe.version == expected_version]
    if not matches:
        version_msg = f" version '{expected_version}'" if expected_version is not None else ""
        raise BacktestRunError(f"Strategy recipe '{recipe_id}'{version_msg} was not found.")
    if len(matches) > 1:
        versions = sorted(recipe.version for recipe in matches)
        raise BacktestRunError(
            f"Strategy recipe '{recipe_id}' is ambiguous across versions {versions}. "
            "Pass an explicit strategy_recipe_version."
        )
    return matches[0]


def _discover_factor_pack_ids() -> set[str]:
    packs_dir = config_paths.find_project_root(__file__) / "config" / "research" / "factor_packs"
    if not packs_dir.exists():
        return set()

    pack_ids: set[str] = set()
    for path in sorted(packs_dir.glob("*.yaml")) + sorted(packs_dir.glob("*.yml")):
        pack_ids.add(factor_pack_mod.load_factor_pack(path).pack_id)
    for path in sorted(packs_dir.glob("*.json")):
        pack_ids.add(factor_pack_mod.load_factor_pack(path).pack_id)
    return pack_ids


def normalize_recipe_strategy_params(params: dict[str, Any]) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for key, value in params.items():
        if not isinstance(value, int | float):
            continue
        normalized[str(key)] = float(value)
    if "threshold" not in normalized and "zscore_threshold" in normalized:
        normalized["threshold"] = normalized["zscore_threshold"]
    return normalized


def _merge_recipe_defaults(
    *,
    config: BacktestConfig,
    recipe: strategy_recipe_mod.StrategyRecipeManifest,
) -> tuple[dict[str, float], float, float, float | None]:
    provided_fields = config.model_fields_set
    strategy_params = normalize_recipe_strategy_params(recipe.strategy_params)
    strategy_params.update(config.strategy_params)

    fee_bps = config.fee_bps if "fee_bps" in provided_fields else recipe.execution_template.fee_bps
    slippage_bps = (
        config.slippage_bps
        if "slippage_bps" in provided_fields
        else recipe.execution_template.slippage_bps
    )
    max_position_pct = (
        config.max_position_pct
        if "max_position_pct" in provided_fields
        else recipe.risk_template.max_position_pct
    )
    return strategy_params, fee_bps, slippage_bps, max_position_pct


def _validate_recipe_feature_contract(
    *,
    parent_run_id: str,
    recipe: strategy_recipe_mod.StrategyRecipeManifest,
    feature_manifest: feature_runner_mod.FeatureManifest,
    features_df: pd.DataFrame,
) -> str | None:
    if not recipe.factor_pack_ids:
        return None
    if len(recipe.factor_pack_ids) != 1:
        raise BacktestRunError(
            "BacktestRunner currently supports strategy recipes with exactly one "
            "top-level factor pack."
        )

    required_pack_id = recipe.factor_pack_ids[0]
    if feature_manifest.factor_pack_id != required_pack_id:
        raise BacktestRunError(
            f"Feature run '{parent_run_id}' has feature_manifest.json "
            f"factor_pack_id={feature_manifest.factor_pack_id!r}, but strategy "
            f"recipe '{recipe.recipe_id}' requires factor_pack_id={required_pack_id!r}."
        )
    if feature_manifest.factor_pack_version is None:
        raise BacktestRunError(
            f"Feature run '{parent_run_id}' does not declare a factor_pack_version in "
            "'feature_manifest.json'."
        )

    factor_packs = feature_runner_mod.resolve_factor_pack_chain(
        feature_manifest.factor_pack_id,
        expected_version=feature_manifest.factor_pack_version,
    )
    required_columns = {column_name for pack in factor_packs for column_name in pack.output_schema}
    feature_columns = set(features_df.columns)
    missing_columns = sorted(required_columns - feature_columns)
    if missing_columns:
        raise BacktestRunError(
            f"Feature run '{parent_run_id}' is missing strategy-recipe columns: {missing_columns}."
        )
    zscore_column = _select_recipe_zscore_column(
        factor_packs=factor_packs,
        feature_columns=feature_columns,
    )
    if zscore_column is None:
        raise BacktestRunError(
            f"Strategy recipe '{recipe.recipe_id}' does not expose a "
            "'price_zscore_*' feature required by the built-in zscore strategies."
        )
    return zscore_column


def _load_feature_manifest(
    *,
    store: artifact_store_mod.FilesystemArtifactStore,
    run_id: str,
) -> feature_runner_mod.FeatureManifest:
    try:
        manifest_path = store.path_for(run_id, "feature_manifest.json")
    except artifact_store_mod.ArtifactNotFoundError as exc:
        raise BacktestRunError(
            f"Feature run '{run_id}' is missing 'feature_manifest.json'. "
            "Strategy recipes require upstream factor-pack metadata."
        ) from exc

    try:
        return feature_runner_mod.FeatureManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
    except ValidationError as exc:
        raise BacktestRunError(
            f"Feature run '{run_id}' has an invalid 'feature_manifest.json': {exc}."
        ) from exc


def _validate_feature_manifest_contract(
    *,
    config: BacktestConfig,
    parent_run_id: str,
    feature_manifest: feature_runner_mod.FeatureManifest,
) -> None:
    if feature_manifest.dataset_id != config.dataset_id:
        raise BacktestRunError(
            f"Feature run '{parent_run_id}' was built for dataset_id "
            f"'{feature_manifest.dataset_id}', not '{config.dataset_id}'."
        )
    if feature_manifest.feature_set_version != config.feature_set_version:
        raise BacktestRunError(
            f"Feature run '{parent_run_id}' was built for feature_set_version "
            f"'{feature_manifest.feature_set_version}', not '{config.feature_set_version}'."
        )


def _select_recipe_zscore_column(
    *,
    factor_packs: list[factor_pack_mod.FactorPackManifest],
    feature_columns: set[str],
) -> str | None:
    for pack in reversed(factor_packs):
        for param_name in ("short_lookback", "lookback", "zscore_window"):
            raw_window = pack.parameters.get(param_name)
            if isinstance(raw_window, int | float):
                candidate = f"price_zscore_{int(raw_window)}"
                if candidate in feature_columns:
                    return candidate

    manifest_columns = [
        column_name
        for pack in factor_packs
        for column_name in pack.output_schema
        if column_name.startswith("price_zscore_") and column_name in feature_columns
    ]
    if manifest_columns:
        return manifest_columns[0]
    return None


__all__ = ["BacktestConfig", "BacktestManifest", "BacktestRunError", "BacktestRunner"]
