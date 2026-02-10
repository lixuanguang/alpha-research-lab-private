"""Time-series trend features for macro allocation."""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_ts_trend_scores(
    prices: pd.DataFrame,
    lookback_days: int = 252,
    method: str = "sign_return",
    fast: int = 20,
    slow: int = 120,
) -> pd.DataFrame:
    """Compute per-asset trend scores in [-1, 1] using only past data.

    Notes
    -----
    A one-day shift is applied so score at time ``t`` uses information through
    ``t-1``.
    """
    if prices.empty:
        return pd.DataFrame(index=prices.index, columns=prices.columns, dtype=float)

    if method == "sign_return":
        trailing = prices.pct_change(lookback_days)
        scores = np.sign(trailing)
    elif method == "ma_cross":
        fast_ma = prices.rolling(fast, min_periods=fast).mean()
        slow_ma = prices.rolling(slow, min_periods=slow).mean()
        scores = np.sign(fast_ma - slow_ma)
    else:
        raise ValueError(f"unknown trend method '{method}'")

    out = scores.shift(1).fillna(0.0).clip(-1.0, 1.0)
    return out.astype(float)
