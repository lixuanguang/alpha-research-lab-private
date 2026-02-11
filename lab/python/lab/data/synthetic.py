"""
lab.data.synthetic
~~~~~~~~~~~~~~~~~~
Synthetic price generators for testing the pipeline end-to-end without
real market data.

All generators return a ``pd.DataFrame`` of *adjusted close prices*
(DatetimeIndex × tickers).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def generate_gbm_prices(
    tickers: list[str] | None = None,
    n_assets: int = 100,
    start: str = "2005-01-03",
    end: str = "2025-12-31",
    mu: float = 0.07,
    sigma: float = 0.20,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate synthetic equity prices via correlated Geometric Brownian Motion.

    Parameters
    ----------
    tickers : list[str] | None
        Explicit ticker names.  If *None*, auto-generate ``ASSET_001`` … ``ASSET_N``.
    n_assets : int
        Number of assets (ignored if *tickers* is provided).
    start, end : str
        Date range (business-day frequency).
    mu : float
        Annualised drift (mean return).
    sigma : float
        Annualised volatility (per-asset, before cross-sectional dispersion).
    seed : int
        RNG seed for reproducibility.

    Returns
    -------
    pd.DataFrame
        Adjusted close prices (DatetimeIndex × tickers).
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, end)
    n_days = len(dates)

    if tickers is None:
        tickers = [f"ASSET_{i:03d}" for i in range(1, n_assets + 1)]
    n_assets = len(tickers)

    # Per-asset drift & vol with cross-sectional dispersion
    mus = rng.normal(mu, 0.03, size=n_assets)
    sigmas = rng.uniform(sigma * 0.5, sigma * 1.5, size=n_assets)

    # Generate correlated returns via a random factor structure
    n_factors = min(5, n_assets)
    factor_loadings = rng.normal(0, 1, size=(n_assets, n_factors)) * 0.3
    factor_returns = rng.normal(0, 1, size=(n_days, n_factors)) / np.sqrt(252)
    idio_returns = rng.normal(0, 1, size=(n_days, n_assets)) / np.sqrt(252)

    # daily return = mu/252 + factor + idio, scaled by sigma
    daily_mu = mus / 252 - 0.5 * (sigmas**2) / 252
    log_ret = (
        daily_mu[np.newaxis, :]
        + (factor_returns @ factor_loadings.T) * sigmas[np.newaxis, :]
        + idio_returns * sigmas[np.newaxis, :] * 0.7
    )

    # Accumulate log-returns → prices (start at 100)
    log_prices = np.cumsum(log_ret, axis=0)
    prices = 100.0 * np.exp(log_prices)

    return pd.DataFrame(prices, index=dates, columns=tickers)
