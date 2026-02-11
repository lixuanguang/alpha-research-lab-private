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
_EPS = 1e-12


def _clean_series(values: pd.Series) -> pd.Series:
    s = values.astype(float)
    s = s.replace([np.inf, -np.inf], np.nan).dropna()
    return s


def _finite_or_zero(value: float) -> float:
    v = float(value)
    return v if np.isfinite(v) else 0.0


# ── Return / risk metrics ────────────────────────────────────────────────────


def cumulative_return(returns: pd.Series) -> float:
    """Total cumulative return (e.g. 1.35 means +135%)."""
    r = _clean_series(returns)
    if r.empty:
        return 0.0
    return _finite_or_zero((1.0 + r).prod() - 1.0)


def cagr(returns: pd.Series) -> float:
    """Compound annual growth rate from simple daily returns."""
    r = _clean_series(returns)
    n_years = len(r) / ANN_FACTOR
    if n_years <= 0:
        return 0.0
    cum = float((1.0 + r).prod())
    if not np.isfinite(cum) or cum < 0:
        return 0.0
    return _finite_or_zero(cum ** (1.0 / n_years) - 1.0)


def annualised_vol(returns: pd.Series) -> float:
    """Annualised volatility (σ√252)."""
    r = _clean_series(returns)
    if len(r) < 2:
        return 0.0
    return _finite_or_zero(r.std() * np.sqrt(ANN_FACTOR))


def sharpe_ratio(returns: pd.Series, rf: float = 0.0) -> float:
    """Annualised Sharpe ratio (excess return / vol).

    Parameters
    ----------
    returns : pd.Series
        Daily simple returns.
    rf : float
        Annualised risk-free rate (default 0).
    """
    r = _clean_series(returns)
    if r.empty:
        return 0.0
    excess = r.mean() * ANN_FACTOR - rf
    vol = annualised_vol(returns)
    if vol <= _EPS:
        return 0.0
    return _finite_or_zero(excess / vol)


def sortino_ratio(returns: pd.Series, rf: float = 0.0) -> float:
    """Annualised Sortino ratio (excess return / downside vol)."""
    r = _clean_series(returns)
    if r.empty:
        return 0.0
    excess = r.mean() * ANN_FACTOR - rf
    downside_series = r[r < 0]
    if len(downside_series) < 2:
        return 0.0
    downside = downside_series.std() * np.sqrt(ANN_FACTOR)
    if downside <= _EPS:
        return 0.0
    return _finite_or_zero(excess / downside)


def max_drawdown(returns: pd.Series) -> float:
    """Maximum drawdown (as a negative fraction, e.g. -0.25 = -25%)."""
    r = _clean_series(returns)
    if r.empty:
        return 0.0
    cum = (1.0 + r).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak.replace(0.0, np.nan)
    if dd.empty:
        return 0.0
    return _finite_or_zero(dd.min())


def calmar_ratio(returns: pd.Series) -> float:
    """Calmar ratio = CAGR / |max drawdown|."""
    mdd = max_drawdown(returns)
    if abs(mdd) <= _EPS:
        return 0.0
    return _finite_or_zero(cagr(returns) / abs(mdd))


def hit_rate(returns: pd.Series) -> float:
    """Fraction of days with positive returns."""
    r = _clean_series(returns)
    if len(r) == 0:
        return 0.0
    return _finite_or_zero((r > 0).mean())


def profit_factor(returns: pd.Series) -> float:
    """Gross profit / gross loss."""
    r = _clean_series(returns)
    if r.empty:
        return 0.0
    gains = float(r[r > 0].sum())
    losses = abs(float(r[r < 0].sum()))
    if losses <= _EPS:
        return 1_000_000.0 if gains > _EPS else 0.0
    return _finite_or_zero(gains / losses)


def tail_ratio(returns: pd.Series, quantile: float = 0.05) -> float:
    """Ratio of right tail (95th pctl) to left tail (5th pctl)."""
    if not 0 < quantile < 0.5:
        raise ValueError("quantile must be in (0, 0.5)")
    r = _clean_series(returns)
    if r.empty:
        return 0.0
    arr = r.to_numpy()
    right = float(np.nanpercentile(arr, 100 * (1.0 - quantile)))
    left = abs(float(np.nanpercentile(arr, 100 * quantile)))
    if left <= _EPS:
        return 0.0
    return _finite_or_zero(right / left)


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
    t = _clean_series(turnover)
    if t.empty:
        return 0.0
    rebal = t[t > 0]
    if len(rebal) == 0:
        return 0.0
    return _finite_or_zero(rebal.mean())


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
    gross = gross_returns.astype(float).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    net = (
        net_returns.astype(float)
        .replace([np.inf, -np.inf], np.nan)
        .reindex(gross.index, fill_value=0.0)
    )
    net = net.fillna(0.0)
    diff = gross - net
    return _finite_or_zero(diff.sum())


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
    return {k: _finite_or_zero(v) for k, v in d.items()}
