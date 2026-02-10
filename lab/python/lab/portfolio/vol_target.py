"""Portfolio-level volatility targeting helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd

ANN_FACTOR = 252.0


def realized_portfolio_vol(
    trailing_returns: pd.DataFrame,
    weights: pd.Series,
    lookback_days: int,
) -> float:
    """Estimate annualised realised volatility for a fixed weight vector."""
    if trailing_returns.empty:
        return 0.0

    window = trailing_returns.tail(max(2, lookback_days)).fillna(0.0)
    aligned_w = weights.reindex(window.columns).fillna(0.0)
    port = (window * aligned_w).sum(axis=1)
    if len(port) < 2:
        return 0.0
    return float(port.std() * np.sqrt(ANN_FACTOR))


def apply_vol_target(
    weights: pd.Series,
    trailing_returns: pd.DataFrame,
    target_vol_annual: float,
    lookback_days: int,
    gross_cap: float,
) -> pd.Series:
    """Scale weights to a target annual vol and re-apply gross cap."""
    if target_vol_annual <= 0:
        return weights

    realized = realized_portfolio_vol(trailing_returns, weights, lookback_days)
    if realized <= 1e-12:
        return weights

    scale = target_vol_annual / realized
    out = weights * scale

    gross = out.abs().sum()
    if gross > gross_cap and gross > 0:
        out *= gross_cap / gross

    return out
