"""EvaluateRunner — canonical evaluation and report persistence for backtests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import apps.research.reporting.writer as report_writer_mod
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field

import alpha_core.evaluation.evaluator as evaluator_mod
import alpha_core.research.artifact_store as artifact_store_mod
import alpha_core.research.backtest_runner as backtest_runner_mod
import alpha_core.research.manifest as manifest_mod
import alpha_core.research.run_context as run_context_mod

MetricsProfile = Literal["default", "pm_core", "microstructure", "minimal"]

_EPSILON = 1e-12


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
    """Computes an EvaluationReport and derives the requested metrics profile."""

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
        backtest_run_id: str,
        metrics_profile: MetricsProfile = "pm_core",
        *,
        config_payload: dict[str, Any] | None = None,
        parent_run_id: str | None = None,
        session_id: str | None = None,
    ) -> EvaluateManifest:
        backtest_manifest = self._load_backtest_manifest(backtest_run_id)
        trades_df, equity_df = self._load_backtest_frames(backtest_run_id)

        effective_payload = (
            config_payload
            if config_payload is not None
            else {
                "backtest_run_id": backtest_run_id,
                "metrics_profile": metrics_profile,
            }
        )
        run_context = run_context_mod.make_run_context(
            "evaluate",
            config_payload=effective_payload,
            session_id=session_id,
        )

        report = evaluator_mod.BacktestEvaluator().evaluate(
            backtest_id=backtest_run_id,
            strategy_name=backtest_manifest.strategy_id,
            trades_df=trades_df,
            equity_df=equity_df,
            starting_cash=backtest_manifest.starting_cash,
            parent_run_id=parent_run_id or backtest_run_id,
            feature_run_id=backtest_manifest.parent_run_id,
        )
        report_path = report_writer_mod.ReportWriter(self._storage_root).write(
            report,
            run_context.run_id,
        )

        metrics = _profile_metrics(
            report=report,
            trades_df=trades_df,
            profile=metrics_profile,
            starting_cash=backtest_manifest.starting_cash,
        )

        metrics_json_path = report_path.with_name("metrics.json")
        metrics_parquet_path = self._store.prepare_path(run_context.run_id, "metrics.parquet")
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
            "report_json": str(report_path),
            "backtest_run_id": backtest_run_id,
            "metrics_profile": metrics_profile,
        }
        evaluate_manifest = EvaluateManifest(
            run_id=run_context.run_id,
            backtest_run_id=backtest_run_id,
            metrics_profile=metrics_profile,
            built_at=built_at,
            metrics=metrics,
            artifacts=artifact_map,
            parent_run_id=parent_run_id or backtest_run_id,
        )

        manifest_path = self._store.prepare_path(run_context.run_id, "evaluate_manifest.json")
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

    def _load_backtest_manifest(
        self,
        backtest_run_id: str,
    ) -> backtest_runner_mod.BacktestManifest:
        try:
            manifest_path = self._store.path_for(backtest_run_id, "backtest_manifest.json")
            return backtest_runner_mod.BacktestManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
        except artifact_store_mod.ArtifactNotFoundError as exc:
            raise EvaluateRunError(
                f"Backtest artifact not found for run '{backtest_run_id}': {exc}. "
                "Ensure the backtest run completed successfully."
            ) from exc
        except Exception as exc:
            raise EvaluateRunError(
                f"Backtest run '{backtest_run_id}' has an invalid backtest manifest: {exc}."
            ) from exc

    def _load_backtest_frames(
        self,
        backtest_run_id: str,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        try:
            trades_path = self._store.path_for(backtest_run_id, "trades.parquet")
            equity_path = self._store.path_for(backtest_run_id, "equity.parquet")
        except artifact_store_mod.ArtifactNotFoundError as exc:
            raise EvaluateRunError(
                f"Backtest artifact not found for run '{backtest_run_id}': {exc}. "
                "Ensure the backtest run completed successfully."
            ) from exc
        return pq.read_table(trades_path).to_pandas(), pq.read_table(equity_path).to_pandas()


def _compute_metrics(
    *,
    trades_df: pd.DataFrame,
    equity_df: pd.DataFrame,
    profile: MetricsProfile,
    starting_cash: float,
) -> dict[str, float]:
    report = evaluator_mod.BacktestEvaluator().evaluate(
        backtest_id="adhoc",
        strategy_name="adhoc",
        trades_df=trades_df,
        equity_df=equity_df,
        starting_cash=starting_cash,
    )
    return _profile_metrics(
        report=report,
        trades_df=trades_df,
        profile=profile,
        starting_cash=starting_cash,
    )


def _resample_equity(
    *,
    equity_frame: pd.DataFrame,
    starting_cash: float,
) -> pd.Series:
    if equity_frame.empty:
        return pd.Series([starting_cash], dtype=float)

    frame = equity_frame.loc[:, ["ts_event", "equity"]].copy()
    frame["ts_event"] = pd.to_datetime(frame["ts_event"], utc=True, errors="coerce")
    frame["equity"] = pd.to_numeric(frame["equity"], errors="coerce")
    frame = frame.dropna(subset=["ts_event", "equity"]).sort_values("ts_event", kind="stable")
    if frame.empty:
        return pd.Series([starting_cash], dtype=float)

    indexed = frame.set_index("ts_event")["equity"]
    resampled = indexed.resample("1h").last().ffill()
    if resampled.empty:
        return pd.Series([starting_cash], dtype=float)

    step = pd.to_timedelta("1h")
    if float(resampled.iloc[0]) != float(starting_cash):
        seed = pd.Series([starting_cash], index=[resampled.index[0] - step], dtype=float)
        resampled = pd.concat([seed, resampled]).sort_index(kind="stable")
    return resampled.astype(float)


def _profile_metrics(
    *,
    report: evaluator_mod.EvaluationReport,
    trades_df: pd.DataFrame,
    profile: MetricsProfile,
    starting_cash: float,
) -> dict[str, float]:
    metrics: dict[str, float] = {
        "total_return": float(report.financial.total_return),
        "trade_count": float(report.financial.total_trades),
    }
    if profile == "minimal":
        return metrics

    metrics.update(
        {
            "annualized_return": float(report.financial.annualised_return),
            "sharpe_ratio": report.financial.sharpe_ratio,
            "max_drawdown": float(report.financial.max_drawdown),
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


__all__ = [
    "EvaluateManifest",
    "EvaluateRunError",
    "EvaluateRunner",
    "MetricsProfile",
]
