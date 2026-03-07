"""EvaluateRunner — computes financial and PM metrics from backtest artifacts."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd  # type: ignore[import-untyped]
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

import alpha_core.research.artifact_paths as artifact_paths
import alpha_core.research.manifest as manifest_mod
import alpha_core.research.run_context as run_context_mod
from alpha_core.research.artifact_store import ArtifactNotFoundError, FilesystemArtifactStore

MetricsProfile = Literal["default", "pm_core", "microstructure", "minimal"]

_EPSILON = 1e-12
_SECONDS_PER_YEAR = 365.25 * 24.0 * 60.0 * 60.0


class EvaluateManifest(BaseModel):
    """Persistent metadata for a completed evaluation run."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1)
    run_id: str
    backtest_run_id: str
    metrics_profile: str
    built_at: datetime
    metrics: dict[str, float]
    artifacts: dict[str, str]
    parent_run_id: str | None = None


class EvaluateRunError(RuntimeError):
    """Raised when evaluation cannot proceed."""


class EvaluateRunner:
    """Computes metrics from backtest artifacts."""

    def __init__(
        self,
        storage_root: Path,
        store: FilesystemArtifactStore | None = None,
    ) -> None:
        self._storage_root = storage_root
        self._store = store if store is not None else FilesystemArtifactStore(storage_root)

    def build(
        self,
        backtest_run_id: str,
        metrics_profile: MetricsProfile = "pm_core",
        *,
        config_payload: dict[str, Any] | None = None,
        parent_run_id: str | None = None,
    ) -> EvaluateManifest:
        try:
            trades_path = self._store.path_for(backtest_run_id, "trades.parquet")
            equity_path = self._store.path_for(backtest_run_id, "equity.parquet")
        except ArtifactNotFoundError as exc:
            raise EvaluateRunError(
                f"Backtest artifact not found for run '{backtest_run_id}': {exc}. "
                "Ensure the backtest run completed successfully."
            ) from exc

        effective_payload = (
            config_payload
            if config_payload is not None
            else {
                "backtest_run_id": backtest_run_id,
                "metrics_profile": metrics_profile,
            }
        )
        run_context = run_context_mod.make_run_context("evaluate", config_payload=effective_payload)
        run_id = run_context.run_id

        metrics = _compute_metrics(
            trades_df=pq.read_table(trades_path).to_pandas(),
            equity_df=pq.read_table(equity_path).to_pandas(),
            profile=metrics_profile,
            starting_cash=_load_starting_cash(self._storage_root, backtest_run_id),
        )

        metrics_json_path = self._store.prepare_path(run_id, "metrics.json")
        metrics_parquet_path = self._store.prepare_path(run_id, "metrics.parquet")
        metrics_json_path.write_text(
            json.dumps(
                {"metrics_profile": metrics_profile, "metrics": metrics},
                indent=2,
                sort_keys=True,
                allow_nan=False,
            ),
            encoding="utf-8",
        )
        pq.write_table(
            pa.Table.from_pandas(
                pd.DataFrame([{"metric": key, "value": value} for key, value in metrics.items()]),
                preserve_index=False,
            ),
            metrics_parquet_path,
            compression="zstd",
        )

        completed_context = run_context_mod.close_run_context(run_context)
        built_at = completed_context.completed_at_utc or datetime.now(tz=UTC)
        artifact_map: dict[str, str] = {
            "metrics_json": str(metrics_json_path),
            "metrics_parquet": str(metrics_parquet_path),
            "backtest_run_id": backtest_run_id,
            "metrics_profile": metrics_profile,
        }
        evaluate_manifest = EvaluateManifest(
            run_id=run_id,
            backtest_run_id=backtest_run_id,
            metrics_profile=metrics_profile,
            built_at=built_at,
            metrics=metrics,
            artifacts=artifact_map,
            parent_run_id=parent_run_id or backtest_run_id,
        )

        manifest_path = self._store.prepare_path(run_id, "evaluate_manifest.json")
        manifest_path.write_text(evaluate_manifest.model_dump_json(indent=2), encoding="utf-8")
        artifact_map["evaluate_manifest"] = str(manifest_path)

        manifest_mod.persist_run_record(
            storage_root=self._storage_root,
            run_context=completed_context,
            config_payload=effective_payload,
            artifacts=artifact_map,
            parent_run_id=parent_run_id or backtest_run_id,
        )
        return evaluate_manifest


def _compute_metrics(
    *,
    trades_df: pd.DataFrame,
    equity_df: pd.DataFrame,
    profile: MetricsProfile,
    starting_cash: float,
) -> dict[str, float]:
    if {"ts_event", "equity"}.issubset(equity_df.columns):
        equity_frame = equity_df.loc[:, ["ts_event", "equity"]].copy()
        equity_frame["ts_event"] = pd.to_datetime(
            equity_frame["ts_event"],
            utc=True,
            errors="coerce",
        )
        equity_frame["equity"] = pd.to_numeric(equity_frame["equity"], errors="coerce")
        equity_frame = equity_frame.dropna(subset=["ts_event", "equity"]).sort_values(
            "ts_event",
            kind="stable",
        )
        equity_frame = equity_frame.reset_index(drop=True)
    else:
        equity_frame = pd.DataFrame(columns=["ts_event", "equity"])

    final_equity = starting_cash
    if not equity_frame.empty:
        final_equity = float(equity_frame["equity"].iloc[-1])

    metrics = {
        "total_return": round(
            (final_equity - starting_cash) / max(abs(starting_cash), _EPSILON),
            8,
        ),
        "trade_count": float(len(trades_df)),
    }
    if profile == "minimal":
        return metrics

    annualized_return = 0.0
    sharpe_ratio = 0.0
    max_drawdown = 0.0
    equity_series = pd.Series([starting_cash, *equity_frame["equity"].tolist()], dtype=float)
    if len(equity_series) >= 2:
        rolling_max = equity_series.cummax()
        drawdowns = (equity_series - rolling_max) / rolling_max.replace(0, float("nan"))
        max_drawdown = float(drawdowns.min())

    if len(equity_frame) >= 2 and starting_cash > 0:
        elapsed_seconds = float(
            (equity_frame["ts_event"].iloc[-1] - equity_frame["ts_event"].iloc[0]).total_seconds()
        )
        equity_ratio = max(final_equity / starting_cash, 0.0)
        if equity_ratio == 0.0:
            annualized_return = -1.0
        elif elapsed_seconds > 0:
            annualized_return = float(equity_ratio ** (_SECONDS_PER_YEAR / elapsed_seconds) - 1.0)

        period_returns = equity_series.pct_change().dropna()
        deltas = equity_frame["ts_event"].diff().dropna().dt.total_seconds()
        positive_deltas = deltas[deltas > 0]
        if len(period_returns) >= 2 and not positive_deltas.empty:
            periods_per_year = _SECONDS_PER_YEAR / float(positive_deltas.median())
            std_return = float(period_returns.std(ddof=1))
            if std_return > _EPSILON:
                sharpe_ratio = float(
                    period_returns.mean() / std_return * math.sqrt(periods_per_year)
                )

    metrics.update(
        {
            "annualized_return": round(annualized_return, 8),
            "sharpe_ratio": round(sharpe_ratio, 4),
            "max_drawdown": round(max_drawdown, 8),
        }
    )
    metrics.update(_trade_statistics(trades_df=trades_df, starting_cash=starting_cash))
    if profile == "microstructure":
        metrics["avg_spread_cost_bps"] = 0.0
    return metrics


def _trade_statistics(
    *,
    trades_df: pd.DataFrame,
    starting_cash: float,
) -> dict[str, float]:
    if trades_df.empty or "realized_pnl" not in trades_df.columns:
        return {"win_rate": 0.0, "avg_trade_return": 0.0, "profit_factor": 0.0}

    realized = pd.to_numeric(trades_df["realized_pnl"], errors="coerce").fillna(0.0)
    closed_mask = realized.abs() > _EPSILON
    if not bool(closed_mask.any()):
        return {"win_rate": 0.0, "avg_trade_return": 0.0, "profit_factor": 0.0}

    closed_pnl = realized.loc[closed_mask].astype(float)
    trade_returns = closed_pnl / max(abs(starting_cash), _EPSILON)
    if "trade_return" in trades_df.columns:
        explicit_returns = pd.to_numeric(
            trades_df.loc[closed_mask, "trade_return"],
            errors="coerce",
        )
        trade_returns = explicit_returns.where(
            explicit_returns.notna(),
            trade_returns,
        ).astype(float)

    winners = closed_pnl[closed_pnl > 0]
    losers = closed_pnl[closed_pnl < 0]
    profit_factor = 0.0
    if not losers.empty:
        gross_loss = abs(float(losers.sum()))
        if gross_loss > _EPSILON:
            profit_factor = float(winners.sum()) / gross_loss

    return {
        "win_rate": round(float((closed_pnl > 0).mean()), 6),
        "avg_trade_return": round(float(trade_returns.mean()), 8),
        "profit_factor": round(profit_factor, 4),
    }


def _load_starting_cash(storage_root: Path, backtest_run_id: str) -> float:
    manifest_path = artifact_paths.artifact_key_path(
        storage_root,
        backtest_run_id,
        "backtest_manifest.json",
    )
    if not manifest_path.exists():
        return 100_000.0

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    starting_cash = payload.get("starting_cash")
    if isinstance(starting_cash, int | float) and starting_cash > 0:
        return float(starting_cash)
    return 100_000.0


__all__ = [
    "EvaluateManifest",
    "EvaluateRunError",
    "EvaluateRunner",
    "MetricsProfile",
]
