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
    all_assets = old_weights.index.union(new_weights.index)
    old = old_weights.reindex(all_assets, fill_value=0.0)
    new = new_weights.reindex(all_assets, fill_value=0.0)
    return float(np.abs(new - old).sum() / 2.0)


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


def annual_bps_to_daily_fraction(bps_annual: float, ann_factor: float = 252.0) -> float:
    """Convert annualized bps drag into daily return-space fraction."""
    if ann_factor <= 0:
        raise ValueError("ann_factor must be > 0.")
    bps = float(bps_annual)
    if not np.isfinite(bps):
        raise ValueError("bps_annual must be finite.")
    if bps < 0:
        raise ValueError("bps_annual must be >= 0.")
    return bps / 1e4 / float(ann_factor)


def carry_costs(
    gross_exposure: pd.Series,
    short_exposure: pd.Series,
    *,
    financing_bps_annual: float = 0.0,
    short_borrow_bps_annual: float = 0.0,
    ann_factor: float = 252.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Compute daily financing + borrow drag in return space.

    Returns
    -------
    tuple[pd.Series, pd.Series, pd.Series]
        ``(total, financing, borrow)`` aligned to ``gross_exposure.index``.
    """
    idx = gross_exposure.index
    gross = gross_exposure.astype(float).reindex(idx).fillna(0.0)
    short = short_exposure.astype(float).reindex(idx).fillna(0.0)

    if (gross < 0).any():
        raise ValueError("gross_exposure must be >= 0.")
    if (short < 0).any():
        raise ValueError("short_exposure must be >= 0.")

    fin_daily = annual_bps_to_daily_fraction(financing_bps_annual, ann_factor=ann_factor)
    borrow_daily = annual_bps_to_daily_fraction(short_borrow_bps_annual, ann_factor=ann_factor)

    financing = gross * fin_daily
    financing.name = "financing_costs"

    borrow = short * borrow_daily
    borrow.name = "borrow_costs"

    total = financing + borrow
    total.name = "carry_costs"
    return total, financing, borrow


def turnover_impact_bps(
    turnover_by_asset: pd.DataFrame,
    *,
    turnover_ref: float,
    coefficient_bps: float,
    exponent: float = 0.5,
) -> pd.DataFrame:
    """Return per-asset impact bps scaled by turnover intensity.

    ``impact_bps = coefficient_bps * (turnover / turnover_ref) ** exponent``
    """
    if turnover_ref <= 0:
        raise ValueError("turnover_ref must be > 0.")
    if coefficient_bps < 0:
        raise ValueError("coefficient_bps must be >= 0.")
    if exponent <= 0:
        raise ValueError("exponent must be > 0.")

    to = turnover_by_asset.astype(float).fillna(0.0).clip(lower=0.0)
    scaled = (to / float(turnover_ref)) ** float(exponent)
    out = scaled * float(coefficient_bps)
    return out.replace([np.inf, -np.inf], 0.0).fillna(0.0)


def adv_participation(
    turnover_by_asset: pd.DataFrame,
    *,
    notional_usd: float,
    adv_usd: pd.Series,
) -> pd.DataFrame:
    """Estimate participation ratio from turnover fractions and ADV (USD)."""
    if notional_usd <= 0:
        raise ValueError("notional_usd must be > 0.")

    adv = adv_usd.astype(float)
    if (adv <= 0).any():
        raise ValueError("adv_usd must be > 0 for all assets.")

    to = turnover_by_asset.astype(float).fillna(0.0).clip(lower=0.0)
    adv_aligned = adv.reindex(to.columns)
    if adv_aligned.isna().any():
        missing = adv_aligned[adv_aligned.isna()].index.tolist()
        raise ValueError(f"adv_usd missing values for assets: {missing}")

    participation = to.mul(float(notional_usd), axis=0).div(adv_aligned, axis=1)
    return participation.replace([np.inf, -np.inf], 0.0).fillna(0.0)
