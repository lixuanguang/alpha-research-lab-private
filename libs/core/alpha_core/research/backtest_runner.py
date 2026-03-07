"""BacktestRunner — event-driven simulation over gold feature artifacts.

Backtest build steps (see :meth:`BacktestRunner.build`)
--------------------------------------------------------
1. Locate feature artifacts from the parent feature-build run.
2. Fail fast when ``features.parquet`` is absent.
3. Generate per-bar signals using the configured strategy_id (built-in simple
   z-score threshold strategy, extensible via the strategy framework).
4. Simulate fills at last-trade price with zero slippage scaffold.
5. Write ``trades.parquet`` (simulated fills) and ``equity.parquet`` (equity curve).
6. Persist ``backtest_manifest.json`` and a ``RunManifest``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, field_validator

import alpha_core.research.artifact_paths as artifact_paths
import alpha_core.research.manifest as manifest_mod
import alpha_core.research.run_context as run_context_mod
import alpha_core.strategy_framework.models as strategy_models

# ---------------------------------------------------------------------------
# Schema constants
# ---------------------------------------------------------------------------

_TRADES_SCHEMA = pa.schema(
    [
        pa.field("ts_event", pa.timestamp("us", tz="UTC")),
        pa.field("instrument_id", pa.string()),
        pa.field("direction", pa.string()),
        pa.field("size", pa.float64()),
        pa.field("price", pa.float64()),
        pa.field("cash_impact", pa.float64()),
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

# ---------------------------------------------------------------------------
# Config & Manifest
# ---------------------------------------------------------------------------

EngineType = str  # "event" | "vectorized"


class BacktestConfig(BaseModel):
    """Configuration for a backtest run."""

    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(min_length=1)
    feature_set_version: str = Field(min_length=1)
    strategy_id: str = Field(min_length=1)
    engine: str = Field(default="event", pattern=r"^(event|vectorized)$")
    starting_cash: float = Field(default=100_000.0, gt=0)

    @field_validator("dataset_id", "feature_set_version", "strategy_id")
    @classmethod
    def _strip(cls, v: str) -> str:
        cleaned = v.strip()
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


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class BacktestRunError(RuntimeError):
    """Raised when the backtest cannot proceed (e.g. missing feature artifacts)."""


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class BacktestRunner:
    """Simulates a strategy over feature artifacts from a prior feature-build run.

    Parameters
    ----------
    storage_root:
        Root directory shared with the feature runner and run manifest store.
    """

    def __init__(self, storage_root: Path) -> None:
        self._storage_root = storage_root

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(
        self,
        config: BacktestConfig,
        *,
        config_payload: dict[str, Any] | None = None,
        parent_run_id: str | None = None,
    ) -> BacktestManifest:
        """Run simulation and persist artifacts.

        Parameters
        ----------
        config:
            Backtest configuration.
        config_payload:
            Optional serialised config dict for run-manifest hashing.
        parent_run_id:
            Feature-build run id whose ``features.parquet`` is consumed.
            Required in execute mode.

        Raises
        ------
        BacktestRunError
            When features artifact is missing or required columns are absent.
        """
        if parent_run_id is None:
            raise BacktestRunError(
                "A feature-build run id is required to locate features artifacts. "
                "Pass --parent-run-id pointing to a completed build-features run."
            )

        features_path = artifact_paths.artifact_key_path(
            self._storage_root,
            parent_run_id,
            "features.parquet",
        )
        if not features_path.exists():
            raise BacktestRunError(
                f"Feature artifact not found at '{features_path}'. "
                f"Ensure run '{parent_run_id}' completed successfully."
            )

        effective_payload = (
            config_payload if config_payload is not None else config.model_dump(mode="json")
        )
        run_context = run_context_mod.make_run_context(
            "backtest", config_payload=effective_payload
        )
        run_id = run_context.run_id

        # Load features.
        features_df = pq.read_table(features_path).to_pandas()

        # Simulate strategy.
        sim_trades, equity_curve = _simulate(features_df, config)

        # Write artifacts.
        trades_path = artifact_paths.artifact_key_path(
            self._storage_root, run_id, "trades.parquet"
        )
        equity_path = artifact_paths.artifact_key_path(
            self._storage_root, run_id, "equity.parquet"
        )
        trades_path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(sim_trades, trades_path, compression="zstd")
        pq.write_table(equity_curve, equity_path, compression="zstd")

        completed_context = run_context_mod.close_run_context(run_context)
        built_at = completed_context.completed_at_utc or datetime.now(tz=UTC)
        trade_count = sim_trades.num_rows
        final_equity_val = float(
            equity_curve.column("equity").to_pylist()[-1]
            if equity_curve.num_rows > 0
            else config.starting_cash
        )
        total_return = (final_equity_val - config.starting_cash) / config.starting_cash

        artifact_map: dict[str, str] = {
            "trades": str(trades_path),
            "equity": str(equity_path),
            "dataset_id": config.dataset_id,
            "feature_set_version": config.feature_set_version,
            "strategy_id": config.strategy_id,
        }

        bt_manifest = BacktestManifest(
            run_id=run_id,
            dataset_id=config.dataset_id,
            feature_set_version=config.feature_set_version,
            strategy_id=config.strategy_id,
            engine=config.engine,
            starting_cash=config.starting_cash,
            built_at=built_at,
            trade_count=trade_count,
            final_equity=final_equity_val,
            total_return=total_return,
            artifacts=artifact_map,
            parent_run_id=parent_run_id,
        )

        bt_manifest_path = artifact_paths.artifact_key_path(
            self._storage_root, run_id, "backtest_manifest.json"
        )
        bt_manifest_path.write_text(bt_manifest.model_dump_json(indent=2), encoding="utf-8")
        artifact_map["backtest_manifest"] = str(bt_manifest_path)

        manifest_mod.persist_run_record(
            storage_root=self._storage_root,
            run_context=completed_context,
            config_payload=effective_payload,
            artifacts=artifact_map,
            parent_run_id=parent_run_id,
        )

        return bt_manifest


# ---------------------------------------------------------------------------
# Simulation helpers
# ---------------------------------------------------------------------------


def _simulate(
    features_df: pd.DataFrame,
    config: BacktestConfig,
) -> tuple[pa.Table, pa.Table]:
    """Rebalance to a small long/short target using lag-safe feature rows."""
    if features_df.empty:
        return (
            pa.table({name: [] for name in _TRADES_SCHEMA.names}, schema=_TRADES_SCHEMA),
            pa.table({name: [] for name in _EQUITY_SCHEMA.names}, schema=_EQUITY_SCHEMA),
        )

    zscore_col = next((c for c in features_df.columns if c.startswith("price_zscore_")), None)
    price_col = "price" if "price" in features_df.columns else next(
        (c for c in features_df.columns if c.startswith("price_mean_")),
        None,
    )
    if zscore_col is None or price_col is None:
        return (
            pa.table({name: [] for name in _TRADES_SCHEMA.names}, schema=_TRADES_SCHEMA),
            pa.table({name: [] for name in _EQUITY_SCHEMA.names}, schema=_EQUITY_SCHEMA),
        )

    features_df = features_df.copy()
    sequence_col = "ts_available" if "ts_available" in features_df.columns else "ts_event"
    features_df = features_df.sort_values(
        [sequence_col, "instrument_id", "ts_event"],
        kind="stable",
    ).reset_index(drop=True)
    features_df[zscore_col] = features_df[zscore_col].fillna(0.0)
    features_df[price_col] = features_df[price_col].fillna(0.5)

    cash = config.starting_cash
    positions: dict[str, float] = {}
    last_prices: dict[str, float] = {}
    trades: list[dict[str, object]] = []
    equity_rows: list[dict[str, object]] = []

    long_threshold = -1.5
    short_threshold = 1.5
    target_weight = 0.02

    for _, row in features_df.iterrows():
        instrument_id = str(row.get("instrument_id", "unknown"))
        ts_event = row.get(sequence_col, row.get("ts_event"))
        zscore = float(row[zscore_col])
        price = float(row[price_col])
        if price <= 0:
            price = 0.5

        last_prices[instrument_id] = price
        target_direction = strategy_models.SignalDirection.FLAT
        if zscore < long_threshold:
            target_direction = strategy_models.SignalDirection.LONG
        elif zscore > short_threshold:
            target_direction = strategy_models.SignalDirection.SHORT

        current_equity = cash + _mark_to_market(positions, last_prices)
        current_quantity = positions.get(instrument_id, 0.0)
        current_notional = current_quantity * price
        desired_notional = _target_notional(current_equity, target_weight, target_direction)
        delta_notional = desired_notional - current_notional
        if abs(delta_notional) > 1e-9:
            quantity_delta = delta_notional / max(price, 1e-9)
            updated_quantity = current_quantity + quantity_delta
            positions[instrument_id] = updated_quantity
            if abs(updated_quantity) <= 1e-9:
                positions.pop(instrument_id, None)

            cash_impact = -delta_notional
            cash += cash_impact
            trade_direction = (
                strategy_models.SignalDirection.LONG
                if quantity_delta > 0
                else strategy_models.SignalDirection.SHORT
            )
            trades.append(
                {
                    "ts_event": ts_event,
                    "instrument_id": instrument_id,
                    "direction": trade_direction,
                    "size": abs(quantity_delta),
                    "price": price,
                    "cash_impact": cash_impact,
                }
            )

        positions_value = _mark_to_market(positions, last_prices)
        equity_rows.append(
            {
                "ts_event": ts_event,
                "equity": cash + positions_value,
                "cash": cash,
                "positions_value": positions_value,
            }
        )

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


__all__ = [
    "BacktestConfig",
    "BacktestManifest",
    "BacktestRunError",
    "BacktestRunner",
]
