"""
lab.strategies.macro_equities.portfolio_rules
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Portfolio construction rules: signal → target weights.

Rules (week-1)
--------------
1. **Equal-weight top-N**: rank by composite signal, equal-weight top N.
2. **Signal-proportional**: weights ∝ signal score (long-only, normalised).
3. **Risk-parity (stub)**: inverse-vol weighting across selected assets.

All functions return a ``pd.Series`` of target portfolio weights (summing to 1
for long-only, or net-zero for long/short).
"""

from __future__ import annotations

import pandas as pd


def top_n_equal_weight(
    scores: pd.Series,
    n: int = 50,
    long_only: bool = True,
) -> pd.Series:
    """Select top-N assets by score and equal-weight them.

    Parameters
    ----------
    scores : pd.Series
        Cross-sectional signal scores (index = tickers).
    n : int
        Number of assets to hold.
    long_only : bool
        If True, set all weights ≥ 0; otherwise allow short bottom-N.

    Returns
    -------
    pd.Series
        Target weights (sums to 1 if long-only).
    """
    ranked = scores.dropna().sort_values(ascending=False)
    top = ranked.head(n)

    if long_only:
        weights = pd.Series(1.0 / len(top), index=top.index)
    else:
        bottom = ranked.tail(n)
        weights = pd.Series(0.0, index=ranked.index)
        weights[top.index] = 1.0 / len(top)
        weights[bottom.index] = -1.0 / len(bottom)

    return weights.reindex(scores.index, fill_value=0.0)


def signal_proportional(
    scores: pd.Series,
    long_only: bool = True,
) -> pd.Series:
    """Weights proportional to signal scores (normalised to sum = 1).

    Parameters
    ----------
    scores : pd.Series
        Cross-sectional signal scores.
    long_only : bool
        Clip negative weights to zero if True.

    Returns
    -------
    pd.Series
        Target weights.
    """
    s = scores.dropna().copy()
    if long_only:
        s = s.clip(lower=0)
    total = s.abs().sum()
    if total == 0:
        return pd.Series(0.0, index=scores.index)
    weights = s / total
    return weights.reindex(scores.index, fill_value=0.0)


def apply_regime_overlay(
    weights: pd.Series,
    regime: int,
    risk_off_scale: float = 0.3,
) -> pd.Series:
    """Scale portfolio weights based on the current regime.

    Parameters
    ----------
    weights : pd.Series
        Pre-overlay target weights (index = tickers).
    regime : int
        Current regime label:
        ``0`` = risk-on  -> keep weights at full exposure (1.0x),
        ``1`` = risk-off -> scale gross exposure down by *risk_off_scale*.
    risk_off_scale : float
        Multiplier applied in risk-off regime (default 0.3 -> 30% exposure).

    Returns
    -------
    pd.Series
        Scaled target weights.

    Notes
    -----
    - This is the minimal "macro overlay" concept: in risk-off periods
      the portfolio reduces exposure, which should lower both volatility
      and drawdowns.
    - ``risk_off_scale=1.0`` effectively disables the overlay.
    """
    scale = risk_off_scale if regime == 1 else 1.0
    return weights * scale


def risk_parity_stub(
    scores: pd.Series,
    vol: pd.Series,
) -> pd.Series:
    """Stub: risk-parity weighting across selected assets.

    TODO(week-3): full inverse-vol / risk-budgeting implementation.
    Currently falls back to equal-weight on all assets with positive scores.
    """
    mask = scores > 0
    n_pos = mask.sum()
    if n_pos == 0:
        return pd.Series(0.0, index=scores.index)
    weights = pd.Series(0.0, index=scores.index)
    weights[mask] = 1.0 / n_pos
    return weights
