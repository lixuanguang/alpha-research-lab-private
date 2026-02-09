"""
lab.eval.metrics
~~~~~~~~~~~~~~~~
Performance and risk metrics for strategy evaluation.

All functions accept a ``pd.Series`` of daily (log or simple) returns and
return scalar metrics.  Convention: annualisation factor = 252 trading days.

The ``summary()`` function computes the full standardised metric set from
**post-cost** returns, with optional turnover and cost series for
operational metrics (average turnover, total costs paid).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

ANN_FACTOR = 252


# ── Return / risk metrics ────────────────────────────────────────────────────


def cumulative_return(returns: pd.Series) -> float:
    """Total cumulative return (e.g. 1.35 means +135%)."""
    return float((1 + returns).prod() - 1)


def cagr(returns: pd.Series) -> float:
    """Compound annual growth rate from simple daily returns."""
    cum = (1 + returns).prod()
    n_years = len(returns) / ANN_FACTOR
    if n_years <= 0:
        return 0.0
    return float(cum ** (1 / n_years) - 1)


def annualised_vol(returns: pd.Series) -> float:
    """Annualised volatility (σ√252)."""
    return float(returns.std() * np.sqrt(ANN_FACTOR))


def sharpe_ratio(returns: pd.Series, rf: float = 0.0) -> float:
    """Annualised Sharpe ratio (excess return / vol).

    Parameters
    ----------
    returns : pd.Series
        Daily simple returns.
    rf : float
        Annualised risk-free rate (default 0).
    """
    excess = returns.mean() * ANN_FACTOR - rf
    vol = annualised_vol(returns)
    if vol == 0:
        return 0.0
    return float(excess / vol)


def sortino_ratio(returns: pd.Series, rf: float = 0.0) -> float:
    """Annualised Sortino ratio (excess return / downside vol)."""
    excess = returns.mean() * ANN_FACTOR - rf
    downside = returns[returns < 0].std() * np.sqrt(ANN_FACTOR)
    if downside == 0:
        return 0.0
    return float(excess / downside)


def max_drawdown(returns: pd.Series) -> float:
    """Maximum drawdown (as a negative fraction, e.g. -0.25 = -25%)."""
    cum = (1 + returns).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    return float(dd.min())


def calmar_ratio(returns: pd.Series) -> float:
    """Calmar ratio = CAGR / |max drawdown|."""
    mdd = max_drawdown(returns)
    if mdd == 0:
        return 0.0
    return float(cagr(returns) / abs(mdd))


def hit_rate(returns: pd.Series) -> float:
    """Fraction of days with positive returns."""
    if len(returns) == 0:
        return 0.0
    return float((returns > 0).mean())


def profit_factor(returns: pd.Series) -> float:
    """Gross profit / gross loss."""
    gains = returns[returns > 0].sum()
    losses = abs(returns[returns < 0].sum())
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return float(gains / losses)


def tail_ratio(returns: pd.Series, quantile: float = 0.05) -> float:
    """Ratio of right tail (95th pctl) to left tail (5th pctl)."""
    right = np.percentile(returns, 100 * (1 - quantile))
    left = abs(np.percentile(returns, 100 * quantile))
    if left == 0:
        return 0.0
    return float(right / left)


# ── Operational metrics ──────────────────────────────────────────────────────


def average_turnover(turnover: pd.Series) -> float:
    """Mean one-way turnover on rebalance dates (non-zero entries only).

    Parameters
    ----------
    turnover : pd.Series
        One-way turnover fraction (0 on non-rebalance days).

    Returns
    -------
    float
        Average turnover on days where a rebalance occurred.
    """
    rebal = turnover[turnover > 0]
    if len(rebal) == 0:
        return 0.0
    return float(rebal.mean())


def total_costs_paid(
    gross_returns: pd.Series,
    net_returns: pd.Series,
) -> float:
    """Total costs paid over the full backtest, expressed in return space.

    ``total_costs = Σ(gross_returns − net_returns)``

    Parameters
    ----------
    gross_returns : pd.Series
        Daily gross portfolio returns (before costs).
    net_returns : pd.Series
        Daily net portfolio returns (after costs).

    Returns
    -------
    float
        Cumulative cost drag (positive number).
    """
    diff = gross_returns - net_returns.reindex(gross_returns.index, fill_value=0.0)
    return float(diff.sum())


# ── Summary ──────────────────────────────────────────────────────────────────


def summary(
    returns: pd.Series,
    rf: float = 0.0,
    turnover: pd.Series | None = None,
    gross_returns: pd.Series | None = None,
) -> dict[str, float]:
    """Return a dict of all standard metrics computed from **post-cost** returns.

    Parameters
    ----------
    returns : pd.Series
        Daily net (post-cost) simple returns.
    rf : float
        Annualised risk-free rate.
    turnover : pd.Series | None
        Optional turnover series — adds ``avg_turnover``.
    gross_returns : pd.Series | None
        Optional gross-return series — adds ``total_costs``.

    Returns
    -------
    dict[str, float]
        Standardised metric dictionary.
    """
    d: dict[str, float] = {
        "cumulative_return": cumulative_return(returns),
        "cagr": cagr(returns),
        "ann_vol": annualised_vol(returns),
        "sharpe": sharpe_ratio(returns, rf),
        "sortino": sortino_ratio(returns, rf),
        "max_dd": max_drawdown(returns),
        "calmar": calmar_ratio(returns),
        "hit_rate": hit_rate(returns),
        "profit_factor": profit_factor(returns),
        "tail_ratio": tail_ratio(returns),
    }
    if turnover is not None:
        d["avg_turnover"] = average_turnover(turnover)
    if gross_returns is not None:
        d["total_costs"] = total_costs_paid(gross_returns, returns)
    return d
