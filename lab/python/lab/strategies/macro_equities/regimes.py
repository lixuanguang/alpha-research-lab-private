"""
lab.strategies.macro_equities.regimes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Market regime detection for conditional strategy switching.

Regime models (week-1 stubs)
-----------------------------
1. **Volatility regime**: VIX / realised-vol regime via simple threshold.
2. **Trend regime**: broad market above/below 200-day SMA.
3. **HMM regime** (stub): Hidden Markov Model on returns + vol.

Each function returns a ``pd.Series`` with integer regime labels
(0 = risk-on, 1 = risk-off, etc.).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def vol_regime(
    prices: pd.Series,
    short_window: int = 21,
    long_window: int = 126,
    threshold: float = 1.0,
) -> pd.Series:
    """Classify regime by comparing short-term vs long-term realised vol.

    Parameters
    ----------
    prices : pd.Series
        Broad market index (e.g. SPX) prices.
    short_window, long_window : int
        Rolling windows in trading days.
    threshold : float
        Ratio above which we flag "high-vol" regime.

    Returns
    -------
    pd.Series
        0 = low-vol (risk-on), 1 = high-vol (risk-off).
    """
    ret = prices.pct_change()
    short_vol = ret.rolling(short_window).std()
    long_vol = ret.rolling(long_window).std()
    ratio = short_vol / long_vol.replace(0, np.nan)
    return (ratio > threshold).astype(int)


def trend_regime(prices: pd.Series, window: int = 200) -> pd.Series:
    """Binary trend regime: market above SMA = 0 (risk-on), below = 1.

    Parameters
    ----------
    prices : pd.Series
        Broad market index prices.
    window : int
        SMA window in trading days.

    Returns
    -------
    pd.Series
        0 = uptrend, 1 = downtrend.
    """
    sma = prices.rolling(window).mean()
    return (prices < sma).astype(int)


def dual_ma_regime(
    prices: pd.Series,
    fast_window: int = 20,
    slow_window: int = 60,
) -> pd.Series:
    """Placeholder macro-like regime: fast MA vs slow MA.

    Computes without look-ahead — only uses trailing data.

    Parameters
    ----------
    prices : pd.Series
        Broad market index prices (e.g. SPY).
    fast_window : int
        Short moving average window (default 20 days).
    slow_window : int
        Long moving average window (default 60 days).

    Returns
    -------
    pd.Series
        0 = risk-on  (fast MA >= slow MA — uptrend),
        1 = risk-off (fast MA < slow MA — downtrend).

    Notes
    -----
    - Time-varying: regime changes as prices evolve.
    - No look-ahead: each value uses only data available up to that date.
    - Week-1 placeholder: replace with real macro data ingestion later.
    """
    fast_ma = prices.rolling(fast_window, min_periods=fast_window).mean()
    slow_ma = prices.rolling(slow_window, min_periods=slow_window).mean()
    # risk-off when fast MA drops below slow MA
    regime = (fast_ma < slow_ma).astype(int)
    regime.name = "regime"
    return regime


def hmm_regime_stub(returns: pd.Series, n_states: int = 2) -> pd.Series:
    """Stub: HMM-based regime detection.

    TODO(week-4): fit Gaussian HMM (hmmlearn / pomegranate) on returns + vol.
    Returns all-zeros for now.
    """
    return pd.Series(0, index=returns.index, name="regime")
