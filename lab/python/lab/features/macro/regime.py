"""Minimal macro-regime overlay features with explicit lagging."""

from __future__ import annotations

import pandas as pd


def compute_risk_off_regime(
    prices: pd.DataFrame,
    lag_days: int = 30,
    rates_proxy: str = "TLT",
    equity_proxy: str = "SPY",
    lookback_days: int = 63,
) -> pd.Series:
    """Return binary regime series (0=risk-on, 1=risk-off).

    Risk-off rule
    -------------
    - equity proxy has negative trailing return
    - rates proxy volatility is above its trailing median

    The final regime is shifted by ``lag_days`` to avoid implicit lookahead.
    """
    if prices.empty:
        return pd.Series(dtype=int)

    eq = equity_proxy if equity_proxy in prices.columns else prices.columns[0]
    rt = rates_proxy if rates_proxy in prices.columns else prices.columns[0]

    returns = prices.pct_change()
    eq_trend = prices[eq].pct_change(lookback_days)

    rates_vol = returns[rt].rolling(lookback_days, min_periods=lookback_days).std()
    vol_threshold = rates_vol.rolling(lookback_days, min_periods=lookback_days).median()

    raw = ((eq_trend < 0) & (rates_vol > vol_threshold)).astype(int)
    lagged = raw.shift(max(1, lag_days)).fillna(0).astype(int)
    lagged.name = "risk_off"
    return lagged
