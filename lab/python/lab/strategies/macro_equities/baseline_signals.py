"""
lab.strategies.macro_equities.baseline_signals
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Baseline alpha signals for a macro-equities strategy.

Signals (week-1)
----------------
1. **Momentum (12-1)**: 12-month return, skip most recent month.
2. **Value (E/P)**: Earnings yield (stub — needs fundamental data).
3. **Volatility (inverse)**: 1 / realised 60-day vol → low-vol tilt.
4. **Trend (SMA crossover)**: price > 200-day SMA → 1, else 0.

All signal functions take a prices DataFrame and return a signal DataFrame
(same shape: dates × tickers) with values in ℝ or {0, 1}.

No-leakage guarantee
--------------------
Every signal function receives only ``prices[:rebalance_date]`` — the engine
never passes future data.  Internally, each signal uses backward-looking
windows (``shift``, ``rolling``, ``pct_change``) that cannot access future
rows.  The caller (``strategy.py``) extracts only ``.iloc[-1]`` (the latest
cross-section), reinforcing the causal boundary.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def momentum_12_1(prices: pd.DataFrame, skip: int = 21, lookback: int = 252) -> pd.DataFrame:
    """12-month momentum, skipping the most recent *skip* days.

    Parameters
    ----------
    prices : pd.DataFrame
        Adjusted close prices (DatetimeIndex × tickers).
    skip : int
        Days to skip (≈1 month) to avoid short-term reversal.
    lookback : int
        Total lookback in trading days (≈12 months).

    Returns
    -------
    pd.DataFrame
        Cross-sectional momentum z-scores.
    """
    ret = prices.shift(skip).pct_change(lookback - skip)
    # Cross-sectional z-score each day
    mu = ret.mean(axis=1)
    sigma = ret.std(axis=1)
    z = ret.sub(mu, axis=0).div(sigma.replace(0, np.nan), axis=0)
    return z


def inverse_volatility(prices: pd.DataFrame, window: int = 60) -> pd.DataFrame:
    """Inverse realised volatility signal (low-vol tilt).

    Parameters
    ----------
    prices : pd.DataFrame
        Adjusted close prices.
    window : int
        Rolling window for vol estimation.

    Returns
    -------
    pd.DataFrame
        1 / rolling_vol, cross-sectionally normalised.
    """
    ret = prices.pct_change()
    vol = ret.rolling(window).std() * np.sqrt(252)
    inv = 1.0 / vol.replace(0, np.nan)
    # Normalise cross-sectionally to sum to 1
    row_sum = inv.sum(axis=1)
    return inv.div(row_sum, axis=0)


def trend_sma(prices: pd.DataFrame, window: int = 200) -> pd.DataFrame:
    """Binary trend signal: 1 if price > SMA(window), else 0.

    Parameters
    ----------
    prices : pd.DataFrame
        Adjusted close prices.
    window : int
        Simple moving average window (default 200 days).

    Returns
    -------
    pd.DataFrame
        Binary DataFrame (1 = above trend, 0 = below).
    """
    sma = prices.rolling(window).mean()
    return (prices > sma).astype(float)


def cross_sectional_momentum(
    prices: pd.DataFrame,
    lookback: int = 252,
    rebalance_dates: pd.DatetimeIndex | None = None,
    top_n: int | None = None,
    long_only: bool = True,
) -> pd.DataFrame:
    """Cross-sectional momentum signal → target weights.

    For each rebalance date, compute trailing returns over *lookback*,
    rank assets, and assign equal weights to top-N (and optionally short
    bottom-N).

    Parameters
    ----------
    prices : pd.DataFrame
        Adjusted close prices (DatetimeIndex × tickers).
    lookback : int
        Trailing return window in trading days.
    rebalance_dates : pd.DatetimeIndex | None
        Dates on which to recompute weights.  If *None*, every date is
        treated as a rebalance date.
    top_n : int | None
        Number of assets in each bucket.  Defaults to ``len(tickers) // 5``
        (quintile).
    long_only : bool
        If ``True``, go long top-N with equal weight.
        If ``False``, long top-N and short bottom-N (dollar-neutral).

    Returns
    -------
    pd.DataFrame
        Target weights (DatetimeIndex × tickers).  Rows that are not
        rebalance dates carry forward the previous weights.
    """
    trailing_ret = prices.pct_change(lookback)
    tickers = prices.columns
    n = len(tickers)
    if top_n is None:
        top_n = max(1, n // 5)

    if rebalance_dates is None:
        rebalance_dates = prices.index

    # Only compute on valid rebalance dates present in the index
    valid_dates = prices.index.intersection(rebalance_dates)

    weights = pd.DataFrame(0.0, index=prices.index, columns=tickers)
    prev_w = pd.Series(0.0, index=tickers)

    for dt in prices.index:
        if dt in valid_dates:
            row = trailing_ret.loc[dt].dropna()
            if len(row) < top_n:
                prev_w = pd.Series(0.0, index=tickers)
            else:
                ranked = row.sort_values(ascending=False)
                long_names = ranked.head(top_n).index
                if long_only:
                    w = pd.Series(0.0, index=tickers)
                    w[long_names] = 1.0 / top_n
                else:
                    short_names = ranked.tail(top_n).index
                    w = pd.Series(0.0, index=tickers)
                    w[long_names] = 1.0 / top_n
                    w[short_names] = -1.0 / top_n
                prev_w = w
        weights.loc[dt] = prev_w

    return weights


def earnings_yield_stub(prices: pd.DataFrame) -> pd.DataFrame:
    """Stub: earnings yield signal.

    TODO(week-3): integrate fundamental data source and compute E/P.
    Returns all-zeros for now.
    """
    return pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
