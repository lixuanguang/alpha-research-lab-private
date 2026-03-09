"""BacktestEvaluator — orchestrates all evaluation metrics into EvaluationReport.

:class:`EvaluationReport` is the top-level immutable artifact for a completed
backtest evaluation.  It combines:

* :class:`~alpha_core.evaluation.financial.FinancialMetrics`
* :class:`~alpha_core.evaluation.pm_metrics.PMMetrics`
* Lineage references (backtest run id, dataset run id, parent run id)
* Schema version for downstream compatibility checks

Usage (from DataFrames)::

    evaluator = BacktestEvaluator()
    report = evaluator.evaluate(
        backtest_id="abc123",
        strategy_name="zscore_momentum",
        trades_df=trades_df,
        equity_df=equity_df,
        starting_cash=10_000.0,
    )

Usage (from a BacktestResult object via duck-typing)::

    evaluator = BacktestEvaluator()
    report = evaluator.evaluate_result(result, starting_cash=10_000.0)

"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

import alpha_core.evaluation.financial as financial_mod
import alpha_core.evaluation.pm_metrics as pm_metrics_mod

#: Increment whenever EvaluationReport fields change.
EVALUATION_REPORT_SCHEMA_VERSION: int = 2

_ZERO_D = Decimal("0")


class EvaluationReport(BaseModel):
    """Full evaluation report combining all metrics for a backtest run.

    Immutable once created.  Serialises to JSON via ``model_dump_json()``.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=EVALUATION_REPORT_SCHEMA_VERSION)
    backtest_id: str = Field(min_length=1)
    strategy_name: str
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    # Core metrics blocks
    financial: financial_mod.FinancialMetrics
    pm_specific: pm_metrics_mod.PMMetrics

    # Supplementary summaries
    equity_curve_summary: dict[str, Any] = Field(
        default_factory=dict,
        description="High-level equity stats: start/end equity, peak, trough.",
    )
    monthly_returns: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Monthly return table: [{year, month, return}]",
    )
    equity_curve: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Full equity-curve rows persisted for round-trip reporting.",
    )
    best_trades: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Top 5 trades by realised PnL.",
    )
    worst_trades: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Bottom 5 trades by realised PnL.",
    )

    # Lineage
    parent_run_id: str | None = None
    dataset_run_id: str | None = None
    feature_run_id: str | None = None


class BacktestEvaluator:
    """Orchestrates all evaluation metrics and produces an :class:`EvaluationReport`.

    One evaluator instance is reusable across multiple runs.
    """

    def evaluate(
        self,
        backtest_id: str,
        strategy_name: str,
        trades_df: pd.DataFrame,
        equity_df: pd.DataFrame,
        starting_cash: float = 100_000.0,
        *,
        parent_run_id: str | None = None,
        dataset_run_id: str | None = None,
        feature_run_id: str | None = None,
    ) -> EvaluationReport:
        """Compute and return a full :class:`EvaluationReport`.

        Parameters
        ----------
        backtest_id:
            Stable identifier for the backtest run (e.g. SHA-256 digest).
        strategy_name:
            Human-readable strategy name.
        trades_df:
            One row per completed trade thesis.
        equity_df:
            Equity-curve snapshots with columns ``ts_event`` and ``equity``.
        starting_cash:
            Initial portfolio cash value.
        parent_run_id, dataset_run_id, feature_run_id:
            Optional lineage references for provenance tracking.
        """
        financial = financial_mod.compute_financial_metrics(trades_df, equity_df, starting_cash)
        pm = pm_metrics_mod.compute_pm_metrics(trades_df, starting_cash)
        equity_summary = _equity_curve_summary(equity_df, starting_cash)
        monthly = _monthly_returns(equity_df)
        equity_curve = _equity_curve_rows(equity_df)
        best, worst = _top_trades(trades_df, n=5)

        return EvaluationReport(
            backtest_id=backtest_id,
            strategy_name=strategy_name,
            financial=financial,
            pm_specific=pm,
            equity_curve_summary=equity_summary,
            monthly_returns=monthly,
            equity_curve=equity_curve,
            best_trades=best,
            worst_trades=worst,
            parent_run_id=parent_run_id,
            dataset_run_id=dataset_run_id,
            feature_run_id=feature_run_id,
        )

    def evaluate_result(
        self,
        result: Any,
        starting_cash: float = 100_000.0,
        *,
        parent_run_id: str | None = None,
        dataset_run_id: str | None = None,
        feature_run_id: str | None = None,
    ) -> EvaluationReport:
        """Convenience wrapper: evaluate from a duck-typed BacktestResult object.

        Accepts any object exposing:
        * ``.backtest_id`` (str)
        * ``.strategy_name`` (str)
        * ``.equity_curve``  (list of (datetime, Decimal))
        * Either ``.closed_positions`` (preferred) or ``.trades``.
        * ``.trades``        (list of SimulatedFill-like objects with attributes:
                               order.instrument_id, order.side, fill_price, fill_size,
                               fee, timestamp, slippage)
        """
        if getattr(result, "closed_positions", None):
            trades_df = _positions_to_df(result.closed_positions)
        else:
            trades_df = _fills_to_df(result.trades)
        equity_df = _equity_curve_to_df(result.equity_curve)
        return self.evaluate(
            backtest_id=result.backtest_id,
            strategy_name=result.strategy_name,
            trades_df=trades_df,
            equity_df=equity_df,
            starting_cash=starting_cash,
            parent_run_id=parent_run_id,
            dataset_run_id=dataset_run_id,
            feature_run_id=feature_run_id,
        )

    def compare(self, reports: list[EvaluationReport]) -> pd.DataFrame:
        """Side-by-side comparison of multiple strategies / parameter sets.

        Returns a DataFrame with one row per report and a column per metric.
        """
        if not reports:
            return pd.DataFrame()
        rows = []
        for report in reports:
            row: dict[str, Any] = {
                "backtest_id": report.backtest_id,
                "strategy_name": report.strategy_name,
                "total_return": float(report.financial.total_return),
                "annualised_return": float(report.financial.annualised_return),
                "sharpe_ratio": report.financial.sharpe_ratio,
                "sortino_ratio": report.financial.sortino_ratio,
                "calmar_ratio": report.financial.calmar_ratio,
                "max_drawdown": float(report.financial.max_drawdown),
                "max_drawdown_duration_days": report.financial.max_drawdown_duration_days,
                "volatility": report.financial.volatility,
                "total_trades": report.financial.total_trades,
                "win_rate": report.financial.win_rate,
                "profit_factor": float(report.financial.profit_factor),
                "avg_trade_pnl": float(report.financial.avg_trade_pnl),
                "avg_holding_period_hours": report.financial.avg_holding_period_hours,
                "brier_score": report.pm_specific.brier_score,
                "log_loss": report.pm_specific.log_loss,
                "calibration_error": report.pm_specific.calibration_error,
                "resolution_pnl": float(report.pm_specific.resolution_pnl),
                "resolution_count": report.pm_specific.resolution_count,
                "resolution_accuracy": report.pm_specific.resolution_accuracy,
                "avg_prob_at_entry": float(report.pm_specific.avg_prob_at_entry),
                "avg_prob_at_exit": float(report.pm_specific.avg_prob_at_exit),
            }
            rows.append(row)
        return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _equity_curve_summary(equity_df: pd.DataFrame, starting_cash: float) -> dict[str, Any]:
    if not {"ts_event", "equity"}.issubset(equity_df.columns) or equity_df.empty:
        return {"start_equity": starting_cash, "end_equity": starting_cash}
    eq = pd.to_numeric(equity_df["equity"], errors="coerce").dropna()
    return {
        "start_equity": round(starting_cash, 4),
        "end_equity": round(float(eq.iloc[-1]), 4),
        "peak_equity": round(float(eq.max()), 4),
        "trough_equity": round(float(eq.min()), 4),
        "data_points": len(eq),
    }


def _monthly_returns(equity_df: pd.DataFrame) -> list[dict[str, Any]]:
    if not {"ts_event", "equity"}.issubset(equity_df.columns) or equity_df.empty:
        return []
    eq = equity_df[["ts_event", "equity"]].copy()
    eq["ts_event"] = pd.to_datetime(eq["ts_event"], utc=True, errors="coerce")
    eq["equity"] = pd.to_numeric(eq["equity"], errors="coerce")
    eq = eq.dropna().sort_values("ts_event").set_index("ts_event")
    monthly = eq["equity"].resample("ME").last().ffill()
    monthly_ret = monthly.pct_change().dropna()
    rows = []
    for ts, ret in monthly_ret.items():
        rows.append({"year": ts.year, "month": ts.month, "return": round(float(ret), 6)})
    return rows


def _equity_curve_rows(equity_df: pd.DataFrame) -> list[dict[str, Any]]:
    if equity_df.empty:
        return []

    frame = equity_df.copy()
    if "ts_event" in frame.columns:
        frame["ts_event"] = pd.to_datetime(frame["ts_event"], utc=True, errors="coerce")
    for column in ("equity", "cash", "positions_value"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    sort_columns = [column for column in ("ts_event",) if column in frame.columns]
    if sort_columns:
        frame = frame.sort_values(sort_columns, kind="stable")
    frame = frame.where(pd.notna(frame), None)
    return cast(list[dict[str, Any]], frame.to_dict(orient="records"))


def _top_trades(
    trades_df: pd.DataFrame, n: int = 5
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if trades_df.empty or "realized_pnl" not in trades_df.columns:
        return [], []
    df = trades_df.copy()
    df["_pnl"] = pd.to_numeric(df["realized_pnl"], errors="coerce").fillna(0.0)
    closed = df[df["_pnl"].abs() > 1e-12].copy()
    if closed.empty:
        return [], []

    _all_cols = ["ts_event", "instrument_id", "direction", "price", "size", "_pnl"]
    keep_cols = [c for c in _all_cols if c in closed.columns]
    closed = closed[keep_cols].rename(columns={"_pnl": "realized_pnl"})

    best = closed.nlargest(n, "realized_pnl").to_dict(orient="records")
    worst = closed.nsmallest(n, "realized_pnl").to_dict(orient="records")
    return best, worst


def _fills_to_df(fills: list[Any]) -> pd.DataFrame:
    """Convert a list of SimulatedFill-like objects to a DataFrame."""
    rows = []
    for fill in fills:
        rows.append(
            {
                "ts_event": fill.timestamp,
                "instrument_id": getattr(fill.order, "instrument_id", None),
                "direction": str(getattr(fill.order, "side", "long")).lower(),
                "price": float(fill.fill_price),
                "size": float(fill.fill_size),
                "fee": float(fill.fee),
                "slippage": float(fill.slippage),
                "realized_pnl": 0.0,  # not available at fill level
            }
        )
    return pd.DataFrame(rows)


def _positions_to_df(positions: list[Any]) -> pd.DataFrame:
    rows = []
    for position in positions:
        rows.append(
            {
                "ts_event": position.closed_at or position.last_updated,
                "entry_time": position.opened_at,
                "instrument_id": position.instrument_id,
                "direction": str(position.side).lower(),
                "price": float(position.entry_price),
                "exit_price": float(position.current_price),
                "size": float(position.size),
                "realized_pnl": float(position.realised_pnl),
                "resolution_outcome": (
                    None
                    if position.resolution_outcome is None
                    else float(position.resolution_outcome)
                ),
                "exit_reason": position.exit_reason,
            }
        )
    return pd.DataFrame(rows)


def _equity_curve_to_df(equity_curve: list[tuple[Any, Any]]) -> pd.DataFrame:
    """Convert list of (datetime, Decimal) equity snapshots to DataFrame."""
    return pd.DataFrame(
        [(ts, float(eq)) for ts, eq in equity_curve],
        columns=["ts_event", "equity"],
    )


__all__ = [
    "EVALUATION_REPORT_SCHEMA_VERSION",
    "BacktestEvaluator",
    "EvaluationReport",
]
