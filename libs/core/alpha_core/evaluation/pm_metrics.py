"""Prediction-market-specific evaluation metrics.

These metrics complement standard financial metrics (:mod:`alpha_core.evaluation.financial`)
with PM-native signals:

* **Brier score** — mean squared error between entry probability and resolution.
* **Log-loss** — binary cross-entropy of entry probability vs outcome.
* **Calibration error (ECE)** — weighted mean |predicted - actual| across bins.
* **Resolution PnL** — attributed PnL from markets that resolved during run.
* **Category breakdown** — per-category Sharpe + Brier + trade count.

All monetary values use :class:`~decimal.Decimal`.  Float fields are standard
Python ``float``.

Input contract (``trades_df``)
-------------------------------
Expected columns produced by :class:`~alpha_core.research.backtest_runner.BacktestRunner`:

* ``instrument_id``   — canonical market ID
* ``direction``       — ``"long"`` / ``"short"``
* ``price``           — fill price (probability space, 0-1)
* ``size``            — number of contracts
* ``realized_pnl``    — closed PnL (0 for open positions)
* ``ts_event``        — fill timestamp (UTC)

Optional columns (enriched by dataset metadata):

* ``resolution_outcome``  — ``0.0`` or ``1.0`` for resolved markets
* ``category``            — market category string
"""

from __future__ import annotations

import math
from decimal import Decimal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from alpha_core.evaluation.calibration import (
    brier_score,
    calibration_curve,
    expected_calibration_error,
    log_loss_score,
)

_EPSILON = 1e-12
_ZERO_D = Decimal("0")


class PMMetrics(BaseModel):
    """Prediction-market-specific evaluation metrics."""

    model_config = ConfigDict(extra="forbid")

    # Probabilistic scoring
    brier_score: float = Field(
        description="Mean (forecast - outcome)^2; 0 = perfect, 0.25 = uniform random on binary"
    )
    log_loss: float = Field(
        description="Binary cross-entropy; 0 = perfect, ln(2) ≈ 0.693 = uniform random"
    )
    calibration_error: float = Field(
        description="Expected Calibration Error (ECE); 0 = perfectly calibrated"
    )
    calibration_bins: list[dict] = Field(
        default_factory=list,
        description="Per-bin calibration data: {bin_start, bin_end, avg_predicted, avg_actual, count}",  # noqa: E501
    )

    # Resolution attribution
    resolution_pnl: Decimal = Field(
        default=_ZERO_D,
        description="Total PnL from markets that resolved during the backtest",
    )
    resolution_count: int = Field(default=0, ge=0, description="Number of resolved positions")
    resolution_accuracy: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Fraction of resolved positions where strategy was on the correct side",
    )

    # Entry/exit probability summary
    avg_prob_at_entry: Decimal = Field(
        default=_ZERO_D,
        description="Mean implied probability at position entry",
    )
    avg_prob_at_exit: Decimal = Field(
        default=_ZERO_D,
        description="Mean implied probability at position exit / close",
    )

    # Category breakdown
    category_breakdown: dict[str, dict[str, float]] = Field(
        default_factory=dict,
        description="Per-category metrics: {category: {sharpe, brier, trade_count}}",
    )


def compute_pm_metrics(
    trades_df: pd.DataFrame,
    starting_cash: float = 100_000.0,
) -> PMMetrics:
    """Compute :class:`PMMetrics` from backtest trades DataFrame.

    Parameters
    ----------
    trades_df:
        One row per fill.  See module docstring for expected columns.
    starting_cash:
        Initial cash for return normalisation in category Sharpe.
    """
    if trades_df.empty:
        return PMMetrics(brier_score=0.0, log_loss=0.0, calibration_error=0.0)

    # ------------------------------------------------------------------ #
    # Compute probabilistic metrics when resolution_outcome is available
    # ------------------------------------------------------------------ #
    bs = 0.0
    ll = 0.0
    ece = 0.0
    cal_bins: list[dict] = []

    if "resolution_outcome" in trades_df.columns and "price" in trades_df.columns:
        resolved_mask = trades_df["resolution_outcome"].notna()
        resolved = trades_df[resolved_mask].copy()
        if not resolved.empty:
            preds = pd.to_numeric(resolved["price"], errors="coerce").fillna(0.5).to_numpy().copy()
            raw_outcomes = pd.to_numeric(resolved["resolution_outcome"], errors="coerce").to_numpy()
            # For short positions, flip the prediction direction
            if "direction" in resolved.columns:
                short_mask = resolved["direction"].str.lower() == "short"
                preds[short_mask.to_numpy()] = 1.0 - preds[short_mask.to_numpy()]
            valid = ~np.isnan(raw_outcomes)
            if valid.sum() > 0:
                preds_v = preds[valid]
                outcomes_v = raw_outcomes[valid]
                bs = brier_score(preds_v, outcomes_v)
                ll = log_loss_score(preds_v, outcomes_v)
                ece = expected_calibration_error(preds_v, outcomes_v)
                cal_bins = calibration_curve(preds_v, outcomes_v)

    # ------------------------------------------------------------------ #
    # Resolution PnL and accuracy
    # ------------------------------------------------------------------ #
    res_pnl = _ZERO_D
    res_count = 0
    res_accuracy = 0.0

    if "resolution_outcome" in trades_df.columns and "realized_pnl" in trades_df.columns:
        res_df = trades_df[trades_df["resolution_outcome"].notna()]
        if not res_df.empty:
            pnl_series = pd.to_numeric(res_df["realized_pnl"], errors="coerce").fillna(0.0)
            res_pnl = Decimal(str(round(float(pnl_series.sum()), 8)))
            res_count = len(res_df)
            res_accuracy = round(float((pnl_series > _EPSILON).mean()), 6)

    # ------------------------------------------------------------------ #
    # Average entry/exit probability
    # ------------------------------------------------------------------ #
    avg_entry = _ZERO_D
    avg_exit = _ZERO_D

    if "price" in trades_df.columns and "direction" in trades_df.columns:
        prices = pd.to_numeric(trades_df["price"], errors="coerce").dropna()
        if not prices.empty:
            avg_entry = Decimal(str(round(float(prices.mean()), 8)))
        # Heuristic: longs close at high price, shorts close at low price
        if "realized_pnl" in trades_df.columns:
            _pnl_abs = pd.to_numeric(trades_df["realized_pnl"], errors="coerce").abs()
            _closed_mask = _pnl_abs > _EPSILON
            closed = trades_df[_closed_mask]
            if not closed.empty and "price" in closed.columns:
                exit_prices = pd.to_numeric(closed["price"], errors="coerce").dropna()
                if not exit_prices.empty:
                    avg_exit = Decimal(str(round(float(exit_prices.mean()), 8)))

    # ------------------------------------------------------------------ #
    # Category breakdown
    # ------------------------------------------------------------------ #
    cat_breakdown: dict[str, dict[str, float]] = {}

    if "category" in trades_df.columns:
        for cat, grp in trades_df.groupby("category", sort=False):
            cat_sharpe = _category_sharpe(grp, starting_cash)
            cat_brier = 0.0
            if "resolution_outcome" in grp.columns and "price" in grp.columns:
                r_grp = grp[grp["resolution_outcome"].notna()]
                if not r_grp.empty:
                    p = pd.to_numeric(r_grp["price"], errors="coerce").fillna(0.5).to_numpy()
                    o = pd.to_numeric(r_grp["resolution_outcome"], errors="coerce").to_numpy()
                    valid = ~np.isnan(o)
                    if valid.sum() > 0:
                        cat_brier = brier_score(p[valid], o[valid])
            cat_breakdown[str(cat)] = {
                "sharpe": round(cat_sharpe, 4),
                "brier": round(cat_brier, 6),
                "trade_count": float(len(grp)),
            }

    return PMMetrics(
        brier_score=round(bs, 6),
        log_loss=round(ll, 6),
        calibration_error=round(ece, 6),
        calibration_bins=cal_bins,
        resolution_pnl=res_pnl,
        resolution_count=res_count,
        resolution_accuracy=res_accuracy,
        avg_prob_at_entry=avg_entry,
        avg_prob_at_exit=avg_exit,
        category_breakdown=cat_breakdown,
    )


def _category_sharpe(grp: pd.DataFrame, starting_cash: float) -> float:
    """Compute a simple per-trade Sharpe for a category group."""
    if "realized_pnl" not in grp.columns or len(grp) < 2:
        return 0.0
    returns = pd.to_numeric(grp["realized_pnl"], errors="coerce").fillna(0.0) / max(
        abs(starting_cash), _EPSILON
    )
    std_r = float(returns.std(ddof=1))
    if std_r < _EPSILON:
        return 0.0
    # Annualise assuming each trade is ≈ 1 h (conservative but consistent)
    ann_factor = math.sqrt(365.25 * 24.0)
    return float(returns.mean()) / std_r * ann_factor


__all__ = ["PMMetrics", "compute_pm_metrics"]
