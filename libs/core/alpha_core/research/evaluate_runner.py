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
    """Raised when evaluation cannot proceed (e.g. missing backtest artifacts)."""


class EvaluateRunner:
    """Computes metrics from backtest artifacts."""

    def __init__(self, storage_root: Path) -> None:
        self._storage_root = storage_root

    def build(
        self,
        backtest_run_id: str,
        metrics_profile: MetricsProfile = "pm_core",
        *,
        config_payload: dict[str, Any] | None = None,
        parent_run_id: str | None = None,
    ) -> EvaluateManifest:
        trades_path = artifact_paths.artifact_key_path(
            self._storage_root,
            backtest_run_id,
            "trades.parquet",
        )
        equity_path = artifact_paths.artifact_key_path(
            self._storage_root,
            backtest_run_id,
            "equity.parquet",
        )
        if not trades_path.exists():
            raise EvaluateRunError(
                f"Backtest trades artifact not found at '{trades_path}'. "
                f"Ensure run '{backtest_run_id}' completed successfully."
            )
        if not equity_path.exists():
            raise EvaluateRunError(
                f"Backtest equity artifact not found at '{equity_path}'. "
                f"Ensure run '{backtest_run_id}' completed successfully."
            )

        effective_payload = config_payload if config_payload is not None else {
            "backtest_run_id": backtest_run_id,
            "metrics_profile": metrics_profile,
        }
        run_context = run_context_mod.make_run_context("evaluate", config_payload=effective_payload)
        run_id = run_context.run_id

        trades_df = pq.read_table(trades_path).to_pandas()
        equity_df = pq.read_table(equity_path).to_pandas()
        starting_cash = _load_starting_cash(self._storage_root, backtest_run_id)
        metrics = _compute_metrics(
            trades_df=trades_df,
            equity_df=equity_df,
            profile=metrics_profile,
            starting_cash=starting_cash,
        )

        metrics_json_path = artifact_paths.artifact_key_path(
            self._storage_root,
            run_id,
            "metrics.json",
        )
        metrics_parquet_path = artifact_paths.artifact_key_path(
            self._storage_root,
            run_id,
            "metrics.parquet",
        )
        metrics_json_path.parent.mkdir(parents=True, exist_ok=True)
        metrics_json_path.write_text(
            json.dumps(
                {"metrics_profile": metrics_profile, "metrics": metrics},
                indent=2,
                sort_keys=True,
                allow_nan=False,
            ),
            encoding="utf-8",
        )
        metrics_df = pd.DataFrame(
            [{"metric": key, "value": value} for key, value in metrics.items()]
        )
        pq.write_table(
            pa.Table.from_pandas(metrics_df, preserve_index=False),
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

        manifest_path = artifact_paths.artifact_key_path(
            self._storage_root,
            run_id,
            "evaluate_manifest.json",
        )
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
    minimal = _minimal_metrics(
        trades_df=trades_df,
        equity_df=equity_df,
        starting_cash=starting_cash,
    )
    if profile == "minimal":
        return minimal

    pm_core = _pm_core_metrics(
        trades_df=trades_df,
        equity_df=equity_df,
        base=minimal,
        starting_cash=starting_cash,
    )
    if profile in ("pm_core", "default"):
        return pm_core
    if profile == "microstructure":
        return {**pm_core, "avg_spread_cost_bps": 0.0}
    return minimal


def _minimal_metrics(
    *,
    trades_df: pd.DataFrame,
    equity_df: pd.DataFrame,
    starting_cash: float,
) -> dict[str, float]:
    final_equity = starting_cash
    if not equity_df.empty and "equity" in equity_df.columns:
        final_equity = float(equity_df["equity"].iloc[-1])
    total_return = (final_equity - starting_cash) / max(abs(starting_cash), _EPSILON)
    return {
        "total_return": round(total_return, 8),
        "trade_count": float(len(trades_df)),
    }


def _pm_core_metrics(
    *,
    trades_df: pd.DataFrame,
    equity_df: pd.DataFrame,
    base: dict[str, float],
    starting_cash: float,
) -> dict[str, float]:
    metrics = dict(base)
    equity_frame = _sorted_equity_frame(equity_df)
    equity_series = pd.Series([starting_cash, *equity_frame["equity"].tolist()], dtype=float)
    period_returns = equity_series.pct_change().dropna()
    periods_per_year = _infer_periods_per_year(equity_frame)
    annualized_return = _annualized_return(equity_frame, starting_cash=starting_cash)

    metrics["annualized_return"] = round(annualized_return, 8)
    if len(period_returns) >= 2 and periods_per_year > 0:
        mean_return = float(period_returns.mean())
        std_return = float(period_returns.std(ddof=1))
        metrics["sharpe_ratio"] = (
            round(mean_return / std_return * math.sqrt(periods_per_year), 4)
            if std_return > _EPSILON
            else 0.0
        )
    else:
        metrics["sharpe_ratio"] = 0.0

    if len(equity_series) >= 2:
        rolling_max = equity_series.cummax()
        drawdowns = (equity_series - rolling_max) / rolling_max.replace(0, float("nan"))
        metrics["max_drawdown"] = round(float(drawdowns.min()), 8)
    else:
        metrics["max_drawdown"] = 0.0

    trade_statistics = _trade_statistics(trades_df, starting_cash=starting_cash)
    metrics.update(trade_statistics)
    return metrics


def _sorted_equity_frame(equity_df: pd.DataFrame) -> pd.DataFrame:
    if equity_df.empty or "ts_event" not in equity_df.columns:
        return equity_df.copy()
    frame = equity_df.copy()
    frame["ts_event"] = pd.to_datetime(frame["ts_event"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["ts_event"]).sort_values("ts_event", kind="stable")
    return frame.reset_index(drop=True)


def _annualized_return(equity_df: pd.DataFrame, *, starting_cash: float) -> float:
    if equity_df.empty or "equity" not in equity_df.columns or "ts_event" not in equity_df.columns:
        return 0.0

    ending_equity = float(equity_df["equity"].iloc[-1])
    if starting_cash <= 0:
        return 0.0
    equity_ratio = max(ending_equity / starting_cash, 0.0)
    if equity_ratio == 0.0:
        return -1.0

    timestamps = pd.to_datetime(equity_df["ts_event"], utc=True, errors="coerce").dropna()
    if len(timestamps) < 2:
        return 0.0
    elapsed_seconds = float((timestamps.iloc[-1] - timestamps.iloc[0]).total_seconds())
    if elapsed_seconds <= 0:
        return 0.0
    annualized_return = equity_ratio ** (_SECONDS_PER_YEAR / elapsed_seconds) - 1.0
    return float(annualized_return)


def _infer_periods_per_year(equity_df: pd.DataFrame) -> float:
    if equity_df.empty or "ts_event" not in equity_df.columns:
        return 0.0
    timestamps = pd.to_datetime(equity_df["ts_event"], utc=True, errors="coerce").dropna()
    if len(timestamps) < 2:
        return 0.0
    deltas = timestamps.diff().dropna().dt.total_seconds()
    positive_deltas = deltas[deltas > 0]
    if positive_deltas.empty:
        return 0.0
    median_delta = float(positive_deltas.median())
    if median_delta <= 0:
        return 0.0
    return _SECONDS_PER_YEAR / median_delta


def _trade_statistics(
    trades_df: pd.DataFrame,
    *,
    starting_cash: float,
) -> dict[str, float]:
    if trades_df.empty or "realized_pnl" not in trades_df.columns:
        return {"win_rate": 0.0, "avg_trade_return": 0.0, "profit_factor": 0.0}

    realized = pd.to_numeric(trades_df["realized_pnl"], errors="coerce").fillna(0.0)
    closed_mask = realized.abs() > _EPSILON
    if not bool(closed_mask.any()):
        return {"win_rate": 0.0, "avg_trade_return": 0.0, "profit_factor": 0.0}

    closed_pnl = realized[closed_mask]
    trade_returns = _closed_trade_returns(trades_df, closed_mask, starting_cash=starting_cash)
    winning = closed_pnl[closed_pnl > 0]
    losing = closed_pnl[closed_pnl < 0]
    win_rate = float((closed_pnl > 0).mean())
    avg_trade_return = float(trade_returns.mean()) if not trade_returns.empty else 0.0
    if losing.empty:
        profit_factor = 0.0
    else:
        gross_loss = abs(float(losing.sum()))
        profit_factor = float(winning.sum()) / gross_loss if gross_loss > _EPSILON else 0.0
    return {
        "win_rate": round(win_rate, 6),
        "avg_trade_return": round(avg_trade_return, 8),
        "profit_factor": round(profit_factor, 4),
    }


def _closed_trade_returns(
    trades_df: pd.DataFrame,
    closed_mask: pd.Series,
    *,
    starting_cash: float,
) -> pd.Series:
    if "trade_return" in trades_df.columns:
        trade_returns = pd.to_numeric(trades_df.loc[closed_mask, "trade_return"], errors="coerce")
        trade_returns = trade_returns.dropna()
        if not trade_returns.empty:
            return trade_returns.astype(float)
    fallback = pd.to_numeric(
        trades_df.loc[closed_mask, "realized_pnl"],
        errors="coerce",
    ).fillna(0.0)
    return fallback.astype(float) / max(abs(starting_cash), _EPSILON)


def _load_starting_cash(storage_root: Path, backtest_run_id: str) -> float:
    manifest_path = artifact_paths.artifact_key_path(
        storage_root,
        backtest_run_id,
        "backtest_manifest.json",
    )
    if not manifest_path.exists():
        return 100_000.0

    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    starting_cash = raw.get("starting_cash")
    if isinstance(starting_cash, (int, float)) and starting_cash > 0:
        return float(starting_cash)
    return 100_000.0


__all__ = [
    "EvaluateManifest",
    "EvaluateRunError",
    "EvaluateRunner",
    "MetricsProfile",
]
