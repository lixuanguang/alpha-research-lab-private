"""EvaluateRunner — computes financial and PM metrics from backtest artifacts.

Evaluate build steps (see :meth:`EvaluateRunner.build`)
---------------------------------------------------------
1. Locate backtest trades/equity artifacts from the parent backtest run.
2. Fail fast when artifacts are absent.
3. Compute ``pm_core`` or other metrics profile.
4. Write ``metrics.parquet`` and ``metrics.json`` artifacts.
5. Persist ``evaluate_manifest.json`` and a ``RunManifest``.

Metrics profiles
----------------
- **pm_core** (default): total_return, annualized_return, sharpe_ratio,
  max_drawdown, trade_count, win_rate, avg_trade_return, profit_factor.
- **minimal**: total_return, trade_count.
- **default**: alias for pm_core.
- **microstructure**: pm_core + avg_spread_cost_bps (stub).
"""

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

# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class EvaluateRunError(RuntimeError):
    """Raised when evaluation cannot proceed (e.g. missing backtest artifacts)."""


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class EvaluateRunner:
    """Computes metrics from backtest artifacts.

    Parameters
    ----------
    storage_root:
        Shared run artifact root.
    """

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
        """Compute and persist metrics for *backtest_run_id*.

        Parameters
        ----------
        backtest_run_id:
            The run id of the completed backtest whose artifacts to evaluate.
        metrics_profile:
            Named metrics preset (default ``"pm_core"``).
        config_payload:
            Optional config dict for run-manifest hashing.
        parent_run_id:
            Set to *backtest_run_id* for lineage tracking (auto-set by CLI).

        Raises
        ------
        EvaluateRunError
            When backtest artifacts are missing.
        """
        trades_path = artifact_paths.artifact_key_path(
            self._storage_root, backtest_run_id, "trades.parquet"
        )
        equity_path = artifact_paths.artifact_key_path(
            self._storage_root, backtest_run_id, "equity.parquet"
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
        run_context = run_context_mod.make_run_context(
            "evaluate", config_payload=effective_payload
        )
        run_id = run_context.run_id

        trades_df = pq.read_table(trades_path).to_pandas()
        equity_df = pq.read_table(equity_path).to_pandas()
        starting_cash = _load_starting_cash(self._storage_root, backtest_run_id)
        metrics = _compute_metrics(
            trades_df,
            equity_df,
            metrics_profile,
            starting_cash=starting_cash,
        )

        # Write metrics.json and metrics.parquet
        metrics_json_path = artifact_paths.artifact_key_path(
            self._storage_root, run_id, "metrics.json"
        )
        metrics_parquet_path = artifact_paths.artifact_key_path(
            self._storage_root, run_id, "metrics.parquet"
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
        metrics_df = pd.DataFrame([{"metric": k, "value": v} for k, v in metrics.items()])
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

        ev_manifest = EvaluateManifest(
            run_id=run_id,
            backtest_run_id=backtest_run_id,
            metrics_profile=metrics_profile,
            built_at=built_at,
            metrics=metrics,
            artifacts=artifact_map,
            parent_run_id=parent_run_id or backtest_run_id,
        )

        ev_manifest_path = artifact_paths.artifact_key_path(
            self._storage_root, run_id, "evaluate_manifest.json"
        )
        ev_manifest_path.write_text(ev_manifest.model_dump_json(indent=2), encoding="utf-8")
        artifact_map["evaluate_manifest"] = str(ev_manifest_path)

        manifest_mod.persist_run_record(
            storage_root=self._storage_root,
            run_context=completed_context,
            config_payload=effective_payload,
            artifacts=artifact_map,
            parent_run_id=parent_run_id or backtest_run_id,
        )

        return ev_manifest


# ---------------------------------------------------------------------------
# Metrics computation
# ---------------------------------------------------------------------------

_TRADING_BARS_PER_YEAR = 252 * 48  # ~30 min bars; scales gracefully for any granularity


def _compute_metrics(
    trades_df: pd.DataFrame,
    equity_df: pd.DataFrame,
    profile: MetricsProfile,
    *,
    starting_cash: float,
) -> dict[str, float]:
    """Compute named metrics from trades and equity DataFrames."""
    minimal = _minimal_metrics(trades_df, equity_df, starting_cash=starting_cash)
    if profile == "minimal":
        return minimal

    pm = _pm_core_metrics(
        trades_df,
        equity_df,
        minimal,
        starting_cash=starting_cash,
    )
    if profile in ("pm_core", "default"):
        return pm

    if profile == "microstructure":
        return {**pm, "avg_spread_cost_bps": 0.0}

    return minimal


def _minimal_metrics(
    trades_df: pd.DataFrame,
    equity_df: pd.DataFrame,
    *,
    starting_cash: float,
) -> dict[str, float]:
    trade_count = float(len(trades_df))
    final_equity = starting_cash
    if not equity_df.empty and "equity" in equity_df.columns:
        final_equity = float(equity_df["equity"].iloc[-1])
    total_return = (final_equity - starting_cash) / max(abs(starting_cash), 1e-9)
    return {"total_return": round(total_return, 8), "trade_count": trade_count}


def _pm_core_metrics(
    trades_df: pd.DataFrame,
    equity_df: pd.DataFrame,
    base: dict[str, float],
    *,
    starting_cash: float,
) -> dict[str, float]:
    metrics = dict(base)
    equity_values = equity_df["equity"].tolist() if "equity" in equity_df.columns else []
    equity_series = pd.Series([starting_cash, *equity_values], dtype=float)
    period_returns = equity_series.pct_change().dropna()

    n_periods = len(period_returns)
    if n_periods >= 1 and starting_cash > 0:
        ending_equity = float(equity_series.iloc[-1])
        equity_ratio = max(ending_equity / starting_cash, 0.0)
        metrics["annualized_return"] = round(
            equity_ratio ** (_TRADING_BARS_PER_YEAR / n_periods) - 1.0,
            8,
        )
    else:
        metrics["annualized_return"] = 0.0

    if n_periods >= 2:
        mean_r = period_returns.mean()
        std_r = period_returns.std(ddof=1)
        if std_r > 1e-12:
            metrics["sharpe_ratio"] = round(
                mean_r / std_r * math.sqrt(_TRADING_BARS_PER_YEAR), 4
            )
        else:
            metrics["sharpe_ratio"] = 0.0
    else:
        metrics["sharpe_ratio"] = 0.0

    if len(equity_series) >= 2:
        rolling_max = equity_series.cummax()
        drawdowns = (equity_series - rolling_max) / rolling_max.replace(0, float("nan"))
        metrics["max_drawdown"] = round(float(drawdowns.min()), 8)
    else:
        metrics["max_drawdown"] = 0.0

    if n_periods >= 1:
        positive_returns = period_returns[period_returns > 0]
        negative_returns = period_returns[period_returns < 0]
        metrics["win_rate"] = round(float((period_returns > 0).mean()), 6)
        metrics["avg_trade_return"] = round(base["total_return"] / max(len(trades_df), 1), 8)
        metrics["profit_factor"] = round(
            float(positive_returns.sum() / abs(negative_returns.sum()))
            if not negative_returns.empty and abs(float(negative_returns.sum())) > 1e-12
            else 0.0,
            4,
        )
    else:
        metrics["win_rate"] = 0.0
        metrics["avg_trade_return"] = 0.0
        metrics["profit_factor"] = 0.0

    return metrics


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
