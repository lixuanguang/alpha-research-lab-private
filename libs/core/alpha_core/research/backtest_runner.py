"""BacktestRunner — canonical engine-backed backtests over feature artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import apps.research.backtester.engine as event_engine_mod
import apps.research.backtester.result as result_mod
import apps.research.backtester.strategy as strategy_mod
import apps.research.backtester.vec_engine as vec_engine_mod
import apps.research.backtester.vec_strategy as vec_strategy_mod
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

import alpha_core.config.paths as config_paths
import alpha_core.execution.models as exec_models
import alpha_core.features.factor_pack as factor_pack_mod
import alpha_core.portfolio.models as portfolio_models
import alpha_core.research.artifact_store as artifact_store_mod
import alpha_core.research.feature_runner as feature_runner_mod
import alpha_core.research.manifest as manifest_mod
import alpha_core.research.run_context as run_context_mod
import alpha_core.research.strategy_recipe as strategy_recipe_mod
import alpha_core.utils.time as time_utils

_DEFAULT_PRICE = 0.5
_EPSILON = 1e-12
_ZERO_D = Decimal("0")

_MARKET_SCHEMA = pa.schema(
    [
        pa.field("ts_event", pa.timestamp("us", tz="UTC")),
        pa.field("instrument_id", pa.string()),
        pa.field("price", pa.float64()),
    ]
)

_TRADES_SCHEMA = pa.schema(
    [
        pa.field("ts_event", pa.timestamp("us", tz="UTC")),
        pa.field("entry_time", pa.timestamp("us", tz="UTC")),
        pa.field("instrument_id", pa.string()),
        pa.field("direction", pa.string()),
        pa.field("size", pa.float64()),
        pa.field("price", pa.float64()),
        pa.field("exit_price", pa.float64()),
        pa.field("realized_pnl", pa.float64()),
        pa.field("trade_return", pa.float64()),
        pa.field("fees_paid", pa.float64()),
        pa.field("resolution_outcome", pa.float64()),
        pa.field("exit_reason", pa.string()),
    ]
)

_FILLS_SCHEMA = pa.schema(
    [
        pa.field("ts_event", pa.timestamp("us", tz="UTC")),
        pa.field("instrument_id", pa.string()),
        pa.field("direction", pa.string()),
        pa.field("size", pa.float64()),
        pa.field("price", pa.float64()),
        pa.field("fee", pa.float64()),
        pa.field("slippage", pa.float64()),
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
    strategy_params: dict[str, float] = Field(default_factory=dict)
    strategy_recipe_id: str | None = Field(default=None)
    strategy_recipe_version: str | None = Field(default=None)
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
    fee_bps: float
    slippage_bps: float
    zscore_column: str


class _FeatureBacktestDataset:
    def __init__(self, market_table: pa.Table) -> None:
        self._market_table = market_table

    def trades(self) -> pa.Table:
        return self._market_table


class _EventZScoreStrategy(strategy_mod.Strategy):
    def __init__(self, spec: StrategySpec) -> None:
        self._spec = spec

    @property
    def name(self) -> str:
        return self._spec.strategy_id

    def on_init(self, universe: list[str]) -> None:
        del universe

    def on_data(
        self,
        timestamp: datetime,
        state: strategy_mod.StrategyState,
    ) -> list[exec_models.BacktestOrderIntent]:
        del timestamp
        if not state.features:
            return []

        orders: list[exec_models.BacktestOrderIntent] = []
        for instrument_id in state.universe:
            feature_row = state.features.get(instrument_id)
            if feature_row is None:
                continue

            price = state.execution_prices.get(
                instrument_id,
                state.latest_prices.get(instrument_id),
            )
            if price is None or price <= _ZERO_D:
                continue

            zscore = _coerce_float(feature_row.get(self._spec.zscore_column), default=0.0)
            current_qty = _signed_position_size(state.portfolio.positions.get(instrument_id))
            target_qty = _target_quantity(
                equity=state.portfolio.equity,
                price=price,
                zscore=zscore,
                spec=self._spec,
            )
            delta = target_qty - current_qty
            if abs(delta) <= Decimal(str(_EPSILON)):
                continue

            side = portfolio_models.Side.LONG if delta > _ZERO_D else portfolio_models.Side.SHORT
            orders.append(
                exec_models.BacktestOrderIntent(
                    instrument_id=instrument_id,
                    side=side,
                    size=abs(delta),
                    order_type="market",
                )
            )
        return orders

    def on_resolution(
        self,
        instrument_id: str,
        resolved_price: Decimal,
    ) -> None:
        del instrument_id
        del resolved_price


class _VectorizedZScoreStrategy(vec_strategy_mod.VecStrategy):
    def __init__(self, spec: StrategySpec) -> None:
        self._spec = spec

    @property
    def name(self) -> str:
        return self._spec.strategy_id

    def generate_signals(
        self,
        features: pd.DataFrame,
        universe: list[str],
    ) -> pd.DataFrame:
        if features.empty or self._spec.zscore_column not in features.columns:
            return pd.DataFrame(columns=["instrument_id", "signal", "strength"])

        snapshot = features[features["instrument_id"].isin(universe)].copy()
        if snapshot.empty:
            return pd.DataFrame(columns=["instrument_id", "signal", "strength"])
        if "ts_available" in snapshot.columns:
            snapshot = snapshot.sort_values(["ts_available", "instrument_id"], kind="stable")
        elif "ts_event" in snapshot.columns:
            snapshot = snapshot.sort_values(["ts_event", "instrument_id"], kind="stable")
        snapshot = snapshot.groupby("instrument_id", as_index=False).last()

        zscores = pd.to_numeric(snapshot[self._spec.zscore_column], errors="coerce").fillna(0.0)
        signal = pd.Series(0.0, index=snapshot.index, dtype=float)
        if self._spec.family == "zscore_momentum":
            signal.loc[zscores >= self._spec.threshold] = 1.0
            signal.loc[zscores <= -self._spec.threshold] = -1.0
        else:
            signal.loc[zscores <= -self._spec.threshold] = 1.0
            signal.loc[zscores >= self._spec.threshold] = -1.0
        strength = zscores.abs()

        return pd.DataFrame(
            {
                "instrument_id": snapshot["instrument_id"].astype(str).values,
                "signal": signal.values,
                "strength": strength.values,
            }
        )

    def size_positions(
        self,
        signals: pd.DataFrame,
        portfolio_value: Decimal,
        max_positions: int,
    ) -> pd.DataFrame:
        del portfolio_value
        if signals.empty:
            return pd.DataFrame(columns=["instrument_id", "target_weight"])

        active = signals[signals["signal"].abs() > _EPSILON].copy()
        if active.empty:
            return pd.DataFrame(columns=["instrument_id", "target_weight"])

        active = active.sort_values("strength", ascending=False, kind="stable").head(max_positions)
        active["target_weight"] = active["signal"] * self._spec.target_weight
        return active[["instrument_id", "target_weight"]].reset_index(drop=True)


class BacktestRunner:
    """Runs a canonical event or vectorized backtest over feature artifacts."""

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
        feature_run_id = self._require_parent_run_id(parent_run_id)
        effective_payload = self._resolve_config_payload(config, config_payload)
        feature_manifest, features_df = self._load_feature_inputs(
            config=config,
            parent_run_id=feature_run_id,
        )
        resolved_recipe, strategy_spec = self._resolve_strategy_runtime(
            config=config,
            parent_run_id=feature_run_id,
            feature_manifest=feature_manifest,
            features_df=features_df,
        )

        market_table = _build_market_table(features_df)
        lagged_feature_table = _build_lagged_feature_table(features_df)
        result = self._run_engine(
            config=config,
            strategy_spec=strategy_spec,
            market_table=market_table,
            feature_table=lagged_feature_table,
        )

        run_context = run_context_mod.make_run_context(
            "backtest",
            config_payload=effective_payload,
            session_id=session_id,
        )

        trades_table = _closed_positions_to_table(result)
        fills_table = _fills_to_table(result.trades)
        equity_table = _equity_to_table(result)
        artifact_map = self._persist_output_tables(
            run_id=run_context.run_id,
            config=config,
            trades_table=trades_table,
            fills_table=fills_table,
            equity_table=equity_table,
            resolved_recipe=resolved_recipe,
        )

        completed_context = run_context_mod.close_run_context(run_context)
        backtest_manifest = self._build_manifest(
            run_id=run_context.run_id,
            config=config,
            parent_run_id=feature_run_id,
            completed_context=completed_context,
            trades_table=trades_table,
            equity_table=equity_table,
            artifact_map=artifact_map,
            resolved_recipe=resolved_recipe,
        )
        self._persist_run_record(
            run_context=completed_context,
            effective_payload=effective_payload,
            parent_run_id=feature_run_id,
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
        feature_table = pq.read_table(features_path)
        return feature_manifest, feature_table.to_pandas()

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
    ) -> tuple[strategy_recipe_mod.StrategyRecipeManifest | None, StrategySpec]:
        resolved_recipe = resolve_strategy_recipe(
            config.strategy_recipe_id,
            expected_version=config.strategy_recipe_version,
        )
        strategy_params = dict(config.strategy_params)
        zscore_column = _select_default_zscore_column(features_df.columns)
        if zscore_column is None:
            raise BacktestRunError(
                "Feature artifact does not satisfy the backtest input contract. "
                "Missing columns: ['price_zscore_*']."
            )

        if resolved_recipe is None:
            strategy_spec = _resolve_strategy_spec(
                config.strategy_id,
                strategy_params,
                max_position_pct=config.max_position_pct,
                fee_bps=config.fee_bps,
                slippage_bps=config.slippage_bps,
                zscore_column=zscore_column,
            )
            return resolved_recipe, strategy_spec

        strategy_params, fee_bps, slippage_bps, max_position_pct = _merge_recipe_defaults(
            config=config,
            recipe=resolved_recipe,
        )
        zscore_column = _validate_recipe_feature_contract(
            parent_run_id=parent_run_id,
            recipe=resolved_recipe,
            feature_manifest=feature_manifest,
            features_df=features_df,
        )

        strategy_spec = _resolve_strategy_spec(
            config.strategy_id,
            strategy_params,
            max_position_pct=max_position_pct,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            zscore_column=zscore_column,
        )
        return resolved_recipe, strategy_spec

    def _run_engine(
        self,
        *,
        config: BacktestConfig,
        strategy_spec: StrategySpec,
        market_table: pa.Table,
        feature_table: pa.Table,
    ) -> result_mod.BacktestResult:
        dataset = _FeatureBacktestDataset(market_table)
        if config.engine == "event":
            event_config = event_engine_mod.EventBacktestConfig(
                dataset_id=config.dataset_id,
                feature_set=config.feature_set_version,
                initial_cash=Decimal(str(config.starting_cash)),
                fee_schedule=exec_models.FeeSchedule(
                    taker_fee_bps=Decimal(str(strategy_spec.fee_bps))
                ),
                slippage_model="fixed",
                slippage_params={"bps": strategy_spec.slippage_bps},
            )
            event_engine = event_engine_mod.EventBacktestEngine(event_config)
            event_strategy = _EventZScoreStrategy(strategy_spec)
            return event_engine.run(event_strategy, dataset, features=feature_table)

        vec_config = vec_engine_mod.VecBacktestConfig(
            dataset_id=config.dataset_id,
            feature_set=config.feature_set_version,
            initial_cash=Decimal(str(config.starting_cash)),
            fee_bps=Decimal(str(strategy_spec.fee_bps)),
            rebalance_frequency=_infer_rebalance_frequency(market_table),
        )
        vec_engine = vec_engine_mod.VecBacktestEngine(vec_config)
        vec_strategy = _VectorizedZScoreStrategy(strategy_spec)
        return vec_engine.run(vec_strategy, dataset, feature_table=feature_table)

    def _persist_output_tables(
        self,
        *,
        run_id: str,
        config: BacktestConfig,
        trades_table: pa.Table,
        fills_table: pa.Table,
        equity_table: pa.Table,
        resolved_recipe: strategy_recipe_mod.StrategyRecipeManifest | None,
    ) -> dict[str, str]:
        trades_path = self._store.prepare_path(run_id, "trades.parquet")
        fills_path = self._store.prepare_path(run_id, "fills.parquet")
        equity_path = self._store.prepare_path(run_id, "equity.parquet")
        pq.write_table(trades_table, trades_path, compression="zstd")
        pq.write_table(fills_table, fills_path, compression="zstd")
        pq.write_table(equity_table, equity_path, compression="zstd")

        artifact_map: dict[str, str] = {
            "trades": str(trades_path),
            "fills": str(fills_path),
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


def _build_market_table(features_df: pd.DataFrame) -> pa.Table:
    if features_df.empty:
        return _empty_table(_MARKET_SCHEMA)

    price_column = _select_price_column(features_df.columns)
    if price_column is None or "instrument_id" not in features_df.columns:
        missing_columns = ["instrument_id"]
        if price_column is None:
            missing_columns.append("price|price_mean_*")
        raise BacktestRunError(
            "Feature artifact does not satisfy the backtest input contract. "
            f"Missing columns: {missing_columns}."
        )

    sequence_column = "ts_available" if "ts_available" in features_df.columns else "ts_event"
    if sequence_column not in features_df.columns:
        raise BacktestRunError(
            "Feature artifact does not satisfy the backtest input contract. "
            "Missing columns: ['ts_available|ts_event']."
        )

    market_df = pd.DataFrame(
        {
            "ts_event": _normalize_timestamps(features_df[sequence_column]),
            "instrument_id": features_df["instrument_id"].astype(str),
            "price": pd.to_numeric(
                features_df[price_column],
                errors="coerce",
            ).fillna(_DEFAULT_PRICE),
        }
    )
    market_df = market_df.dropna(subset=["ts_event"]).sort_values(
        ["ts_event", "instrument_id"],
        kind="stable",
    )
    return _table_from_frame(market_df, _MARKET_SCHEMA)


def _build_lagged_feature_table(features_df: pd.DataFrame) -> pa.Table:
    if features_df.empty:
        return pa.Table.from_pandas(features_df, preserve_index=False)

    if "instrument_id" not in features_df.columns:
        raise BacktestRunError(
            "Feature artifact does not satisfy the backtest input contract. "
            "Missing columns: ['instrument_id']."
        )

    sequence_column = "ts_available" if "ts_available" in features_df.columns else "ts_event"
    if sequence_column not in features_df.columns:
        raise BacktestRunError(
            "Feature artifact does not satisfy the backtest input contract. "
            "Missing columns: ['ts_available|ts_event']."
        )

    lagged = features_df.copy()
    lagged["instrument_id"] = lagged["instrument_id"].astype(str)
    lagged["_sequence_ts"] = _normalize_timestamps(lagged[sequence_column])
    sort_columns = ["instrument_id", "_sequence_ts"]
    if "ts_event" in lagged.columns:
        lagged["ts_event"] = _normalize_timestamps(lagged["ts_event"])
        sort_columns.append("ts_event")
    lagged = lagged.dropna(subset=["_sequence_ts"]).sort_values(sort_columns, kind="stable")
    unique_times = pd.Index(lagged["_sequence_ts"].drop_duplicates().sort_values())
    next_global_time = {
        unique_times[index]: unique_times[index + 1] for index in range(len(unique_times) - 1)
    }
    lagged["ts_available"] = lagged["_sequence_ts"].map(next_global_time)
    lagged = lagged.dropna(subset=["ts_available"]).drop(columns=["_sequence_ts"])
    return pa.Table.from_pandas(lagged.reset_index(drop=True), preserve_index=False)


def _closed_positions_to_table(result: result_mod.BacktestResult) -> pa.Table:
    rows = [_position_row(position, final_timestamp=None) for position in result.closed_positions]
    rows.extend(
        _position_row(position, final_timestamp=result.final_portfolio.timestamp)
        for position in result.final_portfolio.positions.values()
    )
    if not rows:
        return _empty_table(_TRADES_SCHEMA)
    rows.sort(key=lambda row: (row["ts_event"], row["instrument_id"]))
    return pa.Table.from_pylist(rows, schema=_TRADES_SCHEMA)


def _position_row(
    position: portfolio_models.PositionState,
    *,
    final_timestamp: datetime | None,
) -> dict[str, object]:
    closed_at = position.closed_at or final_timestamp or position.last_updated
    exit_reason = position.exit_reason or "end_of_run"
    realized_pnl = position.realised_pnl
    if final_timestamp is not None and position.closed_at is None:
        realized_pnl += position.unrealised_pnl
    entry_notional = position.size * position.entry_price
    trade_return = 0.0
    if entry_notional > _ZERO_D:
        trade_return = float(realized_pnl / entry_notional)
    return {
        "ts_event": time_utils.ensure_utc(closed_at),
        "entry_time": time_utils.ensure_utc(position.opened_at),
        "instrument_id": position.instrument_id,
        "direction": position.side.value,
        "size": float(position.size),
        "price": float(position.entry_price),
        "exit_price": float(position.current_price),
        "realized_pnl": float(realized_pnl),
        "trade_return": trade_return,
        "fees_paid": float(position.fees_paid),
        "resolution_outcome": (
            float(position.resolution_outcome) if position.resolution_outcome is not None else None
        ),
        "exit_reason": exit_reason,
    }


def _fills_to_table(fills: list[exec_models.SimulatedFill]) -> pa.Table:
    if not fills:
        return _empty_table(_FILLS_SCHEMA)
    rows = [
        {
            "ts_event": time_utils.ensure_utc(fill.timestamp),
            "instrument_id": fill.order.instrument_id,
            "direction": fill.order.side.value,
            "size": float(fill.fill_size),
            "price": float(fill.fill_price),
            "fee": float(fill.fee),
            "slippage": float(fill.slippage),
        }
        for fill in fills
    ]
    return pa.Table.from_pylist(rows, schema=_FILLS_SCHEMA)


def _equity_to_table(result: result_mod.BacktestResult) -> pa.Table:
    if result.equity_snapshots:
        rows = [
            {
                "ts_event": time_utils.ensure_utc(ts),
                "equity": float(equity),
                "cash": float(cash),
                "positions_value": float(positions_value),
            }
            for ts, equity, cash, positions_value in result.equity_snapshots
        ]
        return pa.Table.from_pylist(rows, schema=_EQUITY_SCHEMA)

    if not result.equity_curve:
        return _empty_table(_EQUITY_SCHEMA)

    rows = [
        {
            "ts_event": time_utils.ensure_utc(ts),
            "equity": float(equity),
            "cash": float(result.final_portfolio.cash),
            "positions_value": float(result.final_portfolio.equity - result.final_portfolio.cash),
        }
        for ts, equity in result.equity_curve
    ]
    return pa.Table.from_pylist(rows, schema=_EQUITY_SCHEMA)


def _infer_rebalance_frequency(market_table: pa.Table) -> str:
    if market_table.num_rows < 2:
        return "1D"

    ts = pd.to_datetime(market_table.column("ts_event").to_pandas(), utc=True, errors="coerce")
    deltas = ts.sort_values().diff().dropna()
    positive = deltas[deltas > pd.Timedelta(0)]
    if positive.empty:
        return "1D"
    seconds = max(int(positive.min().total_seconds()), 1)
    return f"{seconds}s"


def _normalize_timestamps(values: pd.Series) -> pd.Series:
    timestamps = pd.to_datetime(values, utc=True, errors="coerce")
    return timestamps


def _table_from_frame(frame: pd.DataFrame, schema: pa.Schema) -> pa.Table:
    if frame.empty:
        return _empty_table(schema)
    return pa.Table.from_pandas(frame.reset_index(drop=True), schema=schema, preserve_index=False)


def _empty_table(schema: pa.Schema) -> pa.Table:
    return pa.table({name: [] for name in schema.names}, schema=schema)


def _target_quantity(
    *,
    equity: Decimal,
    price: Decimal,
    zscore: float,
    spec: StrategySpec,
) -> Decimal:
    direction = _direction_from_zscore(zscore, spec)
    if direction == 0 or price <= _ZERO_D:
        return _ZERO_D
    notional = equity * Decimal(str(spec.target_weight)) * Decimal(str(direction))
    return notional / price


def _direction_from_zscore(zscore: float, spec: StrategySpec) -> int:
    if spec.family == "zscore_momentum":
        if zscore >= spec.threshold:
            return 1
        if zscore <= -spec.threshold:
            return -1
        return 0

    if zscore <= -spec.threshold:
        return 1
    if zscore >= spec.threshold:
        return -1
    return 0


def _signed_position_size(
    position: portfolio_models.PositionState | None,
) -> Decimal:
    if position is None:
        return _ZERO_D
    if position.side == portfolio_models.Side.LONG:
        return position.size
    return -position.size


def _select_default_zscore_column(columns: pd.Index | list[str]) -> str | None:
    candidates = sorted(
        column_name for column_name in columns if column_name.startswith("price_zscore_")
    )
    if not candidates:
        return None
    return candidates[0]


def _select_price_column(columns: pd.Index | list[str]) -> str | None:
    if "price" in columns:
        return "price"
    candidates = sorted(
        column_name for column_name in columns if column_name.startswith("price_mean_")
    )
    if not candidates:
        return None
    return candidates[0]


def _coerce_float(value: object, *, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, int | float | Decimal):
        return float(value)
    if not isinstance(value, str):
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _resolve_strategy_spec(
    strategy_id: str,
    params: dict[str, float] | None = None,
    *,
    max_position_pct: float | None = None,
    fee_bps: float,
    slippage_bps: float,
    zscore_column: str,
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
            zscore_column=zscore_column,
        )
    if normalized.startswith("zscore"):
        return StrategySpec(
            strategy_id=strategy_id,
            family="zscore_mean_reversion",
            threshold=threshold,
            target_weight=target_weight,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            zscore_column=zscore_column,
        )
    raise BacktestRunError(
        f"Unsupported strategy_id '{strategy_id}'. "
        "Built-in support currently covers the zscore_* strategy family."
    )


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
        if isinstance(value, int | float):
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
) -> str:
    if not recipe.factor_pack_ids:
        zscore_column = _select_default_zscore_column(features_df.columns)
        if zscore_column is None:
            raise BacktestRunError(
                f"Strategy recipe '{recipe.recipe_id}' does not expose a "
                "'price_zscore_*' feature required by the built-in zscore strategies."
            )
        return zscore_column

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
