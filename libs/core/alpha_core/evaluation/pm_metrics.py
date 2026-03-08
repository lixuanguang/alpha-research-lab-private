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
* ``price``           — entry probability for the completed trade thesis
* ``exit_price``      — exit / close probability when available
* ``size``            — number of contracts
* ``realized_pnl``    — closed PnL for the completed trade thesis
* ``entry_time``      — entry timestamp (UTC)
* ``ts_event``        — exit / close timestamp (UTC)

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
    calibration_bins: list[dict[str, float | int]] = Field(
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
        One row per completed trade thesis or resolved position.
    starting_cash:
        Initial cash for return normalisation in category Sharpe.
    """
    if trades_df.empty:
        return PMMetrics(brier_score=0.0, log_loss=0.0, calibration_error=0.0)

    resolved = _resolved_trade_frame(trades_df)

    bs = 0.0
    ll = 0.0
    ece = 0.0
    cal_bins: list[dict[str, float | int]] = []
    if not resolved.empty:
        predictions = resolved["forecast_prob"].to_numpy(dtype=float)
        outcomes = resolved["forecast_outcome"].to_numpy(dtype=float)
        bs = brier_score(predictions, outcomes)
        ll = log_loss_score(predictions, outcomes)
        ece = expected_calibration_error(predictions, outcomes)
        cal_bins = calibration_curve(predictions, outcomes)

    res_pnl = _ZERO_D
    res_count = len(resolved.index)
    res_accuracy = 0.0
    if not resolved.empty:
        correct_side = (resolved["forecast_prob"] >= 0.5) == (
            resolved["forecast_outcome"] >= 0.5
        )
        res_accuracy = round(float(correct_side.mean()), 6)
        if "realized_pnl" in resolved.columns:
            pnl_series = pd.to_numeric(resolved["realized_pnl"], errors="coerce").fillna(0.0)
            res_pnl = Decimal(str(round(float(pnl_series.sum()), 8)))

    avg_entry = _ZERO_D
    avg_exit = _ZERO_D
    entry_probs = _thesis_probability_series(trades_df, price_column="price")
    if not entry_probs.empty:
        avg_entry = Decimal(str(round(float(entry_probs.mean()), 8)))

    exit_probs = _thesis_probability_series(trades_df, price_column="exit_price")
    if not exit_probs.empty:
        avg_exit = Decimal(str(round(float(exit_probs.mean()), 8)))

    cat_breakdown = _category_breakdown(trades_df, starting_cash)

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


def _resolved_trade_frame(trades_df: pd.DataFrame) -> pd.DataFrame:
    required = {"price", "resolution_outcome"}
    if not required.issubset(trades_df.columns):
        return pd.DataFrame()

    frame = trades_df.copy()
    frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
    frame["resolution_outcome"] = pd.to_numeric(frame["resolution_outcome"], errors="coerce")
    if "direction" in frame.columns:
        frame["direction"] = frame["direction"].astype(str).str.lower()
    else:
        frame["direction"] = "long"

    frame = frame.dropna(subset=["price", "resolution_outcome"]).reset_index(drop=True)
    if frame.empty:
        return frame

    shorts = frame["direction"] == "short"
    frame["forecast_prob"] = np.where(shorts, 1.0 - frame["price"], frame["price"]).clip(0.0, 1.0)
    frame["forecast_outcome"] = np.where(
        shorts,
        1.0 - frame["resolution_outcome"],
        frame["resolution_outcome"],
    )
    return frame


def _thesis_probability_series(
    trades_df: pd.DataFrame,
    *,
    price_column: str,
) -> pd.Series:
    if price_column not in trades_df.columns:
        return pd.Series(dtype=float)

    prices = pd.to_numeric(trades_df[price_column], errors="coerce")
    if "direction" not in trades_df.columns:
        return prices.dropna().clip(0.0, 1.0)

    direction = trades_df["direction"].astype(str).str.lower()
    thesis_probs = np.where(direction == "short", 1.0 - prices, prices)
    thesis_series = pd.Series(thesis_probs, index=trades_df.index, dtype=float)
    return thesis_series.dropna().clip(0.0, 1.0)


def _category_breakdown(
    trades_df: pd.DataFrame,
    starting_cash: float,
) -> dict[str, dict[str, float]]:
    if "category" not in trades_df.columns:
        return {}

    breakdown: dict[str, dict[str, float]] = {}
    for category, group in trades_df.groupby("category", sort=False):
        resolved_group = _resolved_trade_frame(group)
        category_brier = 0.0
        if not resolved_group.empty:
            category_brier = brier_score(
                resolved_group["forecast_prob"].to_numpy(dtype=float),
                resolved_group["forecast_outcome"].to_numpy(dtype=float),
            )
        breakdown[str(category)] = {
            "sharpe": round(_category_sharpe(group, starting_cash), 4),
            "brier": round(category_brier, 6),
            "trade_count": float(len(group.index)),
        }
    return breakdown


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
