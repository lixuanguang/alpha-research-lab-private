"""Standard financial performance metrics for backtest evaluation.

All metrics work from two DataFrames produced by the backtest engine:

* ``trades_df``  — one row per simulated fill (columns: ``ts_event``,
  ``fill_price``, ``fill_size``, ``fee``, ``realized_pnl``, ``side``,
  ``instrument_id``, ``entry_time`` optional).
* ``equity_df``  — equity-curve snapshots (columns: ``ts_event``, ``equity``).

The ``starting_cash`` scalar (float) is required to normalise return metrics.

All monetary outputs use :class:`~decimal.Decimal` for exact arithmetic.
Computed float fields (ratios, rates) are standard Python ``float``.
"""

from __future__ import annotations

import math
import sys
from decimal import Decimal
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

_EPSILON = 1e-12
_SECONDS_PER_YEAR = 365.25 * 24.0 * 3600.0
_PERIODS_PER_YEAR = 365.25 * 24.0  # hourly resampling
_RESAMPLE_FREQ = "1h"
_MAX_ANNUAL_LOG = math.log(sys.float_info.max)

_ZERO_D = Decimal("0")


class FinancialMetrics(BaseModel):
    """Standard financial performance metrics derived from a backtest result."""

    model_config = ConfigDict(extra="forbid")

    # Return metrics
    total_return: Decimal = Field(description="(final_equity - starting_cash) / starting_cash")
    annualised_return: Decimal = Field(description="Annualised CAGR over the backtest window")
    volatility: float = Field(description="Annualised stddev of hourly returns")

    # Risk-adjusted ratios
    sharpe_ratio: float = Field(description="Annualised Sharpe (excess return / volatility, rf=0)")
    sortino_ratio: float = Field(description="Annualised Sortino (downside deviation denominator)")
    calmar_ratio: float = Field(description="annualised_return / |max_drawdown| (0 if no drawdown)")

    # Drawdown
    max_drawdown: Decimal = Field(description="Maximum peak-to-trough drawdown (negative fraction)")
    max_drawdown_duration_days: int = Field(
        ge=0, description="Longest time to recover from max drawdown (calendar days)"
    )

    # Trade-level summary
    total_trades: int = Field(ge=0)
    win_rate: float = Field(ge=0.0, le=1.0, description="Fraction of closed trades with PnL > 0")
    profit_factor: Decimal = Field(
        description="gross_profit / gross_loss; 0 when no losing trades"
    )
    avg_trade_pnl: Decimal = Field(description="Mean realised PnL per closed trade")
    avg_holding_period_hours: float = Field(
        ge=0.0, description="Average hours between entry and exit fill"
    )


def compute_financial_metrics(
    trades_df: pd.DataFrame,
    equity_df: pd.DataFrame,
    starting_cash: float,
) -> FinancialMetrics:
    """Compute :class:`FinancialMetrics` from backtest output DataFrames.

    Parameters
    ----------
    trades_df:
        One row per simulated fill.  Required columns: ``ts_event``,
        ``fill_price``, ``fill_size``.  Optional: ``realized_pnl``,
        ``entry_time``, ``side``.
    equity_df:
        Equity-curve snapshots.  Required columns: ``ts_event``, ``equity``.
    starting_cash:
        Initial cash balance used to normalise return metrics.
    """
    starting_cash = max(float(starting_cash), _EPSILON)

    eq = _clean_equity(equity_df, starting_cash)
    final_equity = float(eq["equity"].iloc[-1]) if not eq.empty else starting_cash

    total_return = Decimal(str(round((final_equity - starting_cash) / starting_cash, 8)))
    ann_return, vol, sharpe, sortino = _risk_metrics(eq, starting_cash)
    max_dd, max_dd_duration_days = _drawdown_metrics(eq, starting_cash)
    calmar = _safe_divide(ann_return, abs(max_dd)) if max_dd < 0 else 0.0

    trades_stats = _trade_stats(trades_df, starting_cash)

    return FinancialMetrics(
        total_return=total_return,
        annualised_return=Decimal(str(round(ann_return, 8))),
        volatility=round(vol, 6),
        sharpe_ratio=round(sharpe, 4),
        sortino_ratio=round(sortino, 4),
        calmar_ratio=round(calmar, 4),
        max_drawdown=Decimal(str(round(max_dd, 8))),
        max_drawdown_duration_days=max_dd_duration_days,
        total_trades=trades_stats["total_trades"],
        win_rate=round(trades_stats["win_rate"], 6),
        profit_factor=Decimal(str(round(trades_stats["profit_factor"], 4))),
        avg_trade_pnl=Decimal(str(round(trades_stats["avg_trade_pnl"], 8))),
        avg_holding_period_hours=round(trades_stats["avg_holding_period_hours"], 4),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _clean_equity(equity_df: pd.DataFrame, starting_cash: float) -> pd.DataFrame:
    if not {"ts_event", "equity"}.issubset(equity_df.columns):
        return pd.DataFrame(columns=["ts_event", "equity"])
    eq = equity_df[["ts_event", "equity"]].copy()
    eq["ts_event"] = pd.to_datetime(eq["ts_event"], utc=True, errors="coerce")
    eq["equity"] = pd.to_numeric(eq["equity"], errors="coerce")
    eq = eq.dropna().sort_values("ts_event", kind="stable").reset_index(drop=True)
    return eq


def _resample_equity(eq: pd.DataFrame, starting_cash: float) -> pd.Series:
    """Resample equity curve to hourly, forward-filling gaps."""
    if eq.empty:
        return pd.Series([starting_cash], dtype=float)
    indexed = eq.set_index("ts_event")["equity"].sort_index(kind="stable")
    resampled = indexed.resample(_RESAMPLE_FREQ).last().ffill()
    if resampled.empty:
        return pd.Series([starting_cash], dtype=float)
    step = pd.to_timedelta(_RESAMPLE_FREQ)
    if float(resampled.iloc[0]) != starting_cash:
        seed = pd.Series([starting_cash], index=[resampled.index[0] - step], dtype=float)
        resampled = pd.concat([seed, resampled]).sort_index(kind="stable")
    return resampled.astype(float)


def _risk_metrics(eq: pd.DataFrame, starting_cash: float) -> tuple[float, float, float, float]:
    """Return (annualised_return, volatility, sharpe, sortino)."""
    resampled = _resample_equity(eq, starting_cash)
    period_returns = resampled.pct_change().dropna()

    ann_return = 0.0
    if len(eq) >= 2 and starting_cash > 0:
        final_equity = float(eq["equity"].iloc[-1])
        elapsed_sec = float((eq["ts_event"].iloc[-1] - eq["ts_event"].iloc[0]).total_seconds())
        ratio = max(final_equity / starting_cash, 0.0)
        if ratio == 0.0:
            ann_return = -1.0
        elif elapsed_sec > 0:
            log_r = math.log(ratio) * (_SECONDS_PER_YEAR / elapsed_sec)
            if log_r < _MAX_ANNUAL_LOG:
                ann_return = math.exp(log_r) - 1.0
            else:
                ann_return = sys.float_info.max

    vol = 0.0
    sharpe = 0.0
    sortino = 0.0
    if len(period_returns) >= 2:
        std_r = float(period_returns.std(ddof=1))
        vol = std_r * math.sqrt(_PERIODS_PER_YEAR)
        if std_r > _EPSILON:
            sharpe = float(period_returns.mean()) / std_r * math.sqrt(_PERIODS_PER_YEAR)
        down = period_returns[period_returns < 0]
        if len(down) >= 2:
            down_std = float(down.std(ddof=1))
            if down_std > _EPSILON:
                sortino = float(period_returns.mean()) / down_std * math.sqrt(_PERIODS_PER_YEAR)

    return ann_return, vol, sharpe, sortino


def _drawdown_metrics(eq: pd.DataFrame, starting_cash: float) -> tuple[float, int]:
    """Return (max_drawdown_fraction, max_drawdown_duration_days)."""
    series = pd.Series([starting_cash, *eq["equity"].tolist()], dtype=float)
    if len(series) < 2:
        return 0.0, 0

    rolling_max = series.cummax()
    # Avoid division by zero at zero-peak
    denom = rolling_max.replace(0.0, float("nan"))
    dd_fractions = (series - rolling_max) / denom
    max_dd = float(dd_fractions.min())

    # Duration: longest run of consecutive non-zero drawdown periods
    in_dd = (dd_fractions < -_EPSILON).astype(int)
    max_run = 0
    run = 0
    for v in in_dd:
        if v:
            run += 1
            max_run = max(max_run, run)
        else:
            run = 0

    # Each period ≈ 1 h; convert to days
    duration_days = int(max_run / 24) if max_run > 0 else 0
    return max_dd, duration_days


def _trade_stats(trades_df: pd.DataFrame, starting_cash: float) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "total_trades": 0,
        "win_rate": 0.0,
        "profit_factor": 0.0,
        "avg_trade_pnl": 0.0,
        "avg_holding_period_hours": 0.0,
    }
    if trades_df.empty:
        return defaults

    defaults["total_trades"] = len(trades_df)

    if "realized_pnl" in trades_df.columns:
        pnl = pd.to_numeric(trades_df["realized_pnl"], errors="coerce").fillna(0.0)
        closed = pnl[pnl.abs() > _EPSILON]
        if not closed.empty:
            winners = closed[closed > 0]
            losers = closed[closed < 0]
            defaults["win_rate"] = float((closed > 0).mean())
            defaults["avg_trade_pnl"] = float(closed.mean())
            gross_loss = abs(float(losers.sum()))
            if gross_loss > _EPSILON:
                defaults["profit_factor"] = float(winners.sum()) / gross_loss

    if "entry_time" in trades_df.columns and "ts_event" in trades_df.columns:
        t_entry = pd.to_datetime(trades_df["entry_time"], utc=True, errors="coerce")
        t_exit = pd.to_datetime(trades_df["ts_event"], utc=True, errors="coerce")
        holding = (t_exit - t_entry).dt.total_seconds().dropna() / 3600.0
        if not holding.empty:
            defaults["avg_holding_period_hours"] = float(holding.mean())

    return defaults


def _safe_divide(numerator: float, denominator: float) -> float:
    if abs(denominator) < _EPSILON:
        return 0.0
    return numerator / denominator


__all__ = ["FinancialMetrics", "compute_financial_metrics"]
