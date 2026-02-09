"""
lab.costs.daily
~~~~~~~~~~~~~~~
Daily transaction-cost models.

Models
------
- **Linear**: spread + commission + slippage, proportional to turnover.
  All expressed as a single total bps number in the config.
- **Square-root** (Almgren–Chriss inspired): market-impact ~ √(turnover / ADV).

Week-1: linear model implemented; sqrt stubbed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from lab.core.logging import get_logger

log = get_logger("costs.daily")


def apply_linear_costs(
    gross_returns: pd.Series,
    turnover: pd.Series,
    cost_bps: float,
) -> pd.Series:
    """Subtract linear transaction costs from gross returns.

    Parameters
    ----------
    gross_returns : pd.Series
        Daily gross portfolio returns.
    turnover : pd.Series
        One-way turnover fraction at each rebalance date (0 on non-rebalance days).
    cost_bps : float
        Total one-way transaction cost in basis points.

    Returns
    -------
    pd.Series
        Net returns after costs.
    """
    cost_fraction = cost_bps / 1e4
    costs = turnover * cost_fraction
    net = gross_returns - costs.reindex(gross_returns.index, fill_value=0.0)
    return net


def apply_sqrt_costs(
    gross_returns: pd.Series,
    turnover: pd.Series,
    adv: pd.Series,
    cost_bps: float,
) -> pd.Series:
    """Subtract square-root market-impact costs (stub).

    Parameters
    ----------
    gross_returns, turnover, adv : pd.Series
        As described.
    cost_bps : float
        Total one-way transaction cost in basis points.

    Returns
    -------
    pd.Series
        Net returns after costs.

    Notes
    -----
    TODO(week-2): implement Almgren–Chriss-style √-impact model.
    """
    log.warning("apply_sqrt_costs is a STUB — falling back to linear model.")
    return apply_linear_costs(gross_returns, turnover, cost_bps)


def estimate_turnover(
    old_weights: pd.Series,
    new_weights: pd.Series,
) -> float:
    """Compute one-way turnover between two weight vectors.

    Definition: ``turnover = Σ|w_new − w_old| / 2``.

    Returns
    -------
    float
        One-way turnover fraction.
    """
    combined = old_weights.reindex(new_weights.index, fill_value=0.0)
    return float(np.abs(new_weights - combined).sum() / 2.0)


def apply_costs(
    weights: pd.Series,
    weights_prev: pd.Series,
    bps: float,
) -> float:
    """Return the transaction cost **in return space** for a single rebalance.

    This is the canonical "one-call" interface used by the daily engine.

    ``cost = turnover × bps / 10_000``

    Parameters
    ----------
    weights : pd.Series
        New target weights (index = tickers).
    weights_prev : pd.Series
        Previous weights (index = tickers).
    bps : float
        Total one-way transaction cost in basis points.

    Returns
    -------
    float
        Cost expressed as a return fraction (e.g. 0.0008 = 8 bps).

    Notes
    -----
    - If ``bps == 0`` the returned cost is exactly ``0.0``.
    - Cost scales linearly with turnover.
    """
    to = estimate_turnover(weights_prev, weights)
    return to * bps / 1e4
