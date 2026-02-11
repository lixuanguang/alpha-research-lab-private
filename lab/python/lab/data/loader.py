"""
lab.data.loader
~~~~~~~~~~~~~~~
Unified data-loading entry-point.

``load_prices_or_make_toy(config)``
    1. If ``LAB_DATA_ROOT/prices.parquet`` exists → load it (filter to config
       universe / date range).
    2. Otherwise → generate toy GBM prices for the tickers in config.

This lets the week-1 pipeline run end-to-end without any external data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from lab.core.logging import get_logger
from lab.core.paths import data_dir
from lab.data.loaders.prices import _coerce_price_panel, _validate_close_panel
from lab.data.synthetic import generate_gbm_prices

if TYPE_CHECKING:
    from lab.core.config import ExperimentConfig

log = get_logger("data.loader")


def load_prices_or_make_toy(
    config: ExperimentConfig,
    *,
    seed: int = 42,
) -> pd.DataFrame:
    """Load real prices or fall back to synthetic GBM toy data.

    Resolution order
    ----------------
    1. ``$LAB_DATA_ROOT/prices.parquet`` — Parquet file with a DatetimeIndex
       and ticker columns.  Filtered to ``config.universe`` and the date window
       ``[config.start_date, config.end_date]``.
    2. Synthetic geometric-Brownian-motion prices for the tickers in
       ``config.universe``.

    Parameters
    ----------
    config : ExperimentConfig
        Must have ``universe``, ``start_date``, ``end_date``.
    seed : int
        RNG seed for the synthetic fallback (default 42).

    Returns
    -------
    pd.DataFrame
        Adjusted close prices (DatetimeIndex × tickers).
    """
    parquet_path = data_dir() / "prices.parquet"

    if parquet_path.exists():
        log.info("Loading real prices from %s", parquet_path)
        df = _coerce_price_panel(pd.read_parquet(parquet_path))

        # Filter to universe tickers that exist in the dataset
        available = [t for t in config.universe if t in df.columns]
        missing = set(config.universe) - set(available)
        if missing:
            log.warning("Tickers not found in prices.parquet (will be dropped): %s", missing)
        if not available:
            log.warning("No universe tickers found in parquet — falling back to toy data.")
            return _make_toy(config, seed=seed)

        df = df.loc[config.start_date : config.end_date, available]
        if df.empty:
            raise ValueError(
                "prices.parquet has no rows in configured window "
                f"{config.start_date}..{config.end_date}"
            )
        _validate_close_panel(df)
        log.info("  Filtered prices: %d days × %d assets", *df.shape)
        return df

    log.info(
        "No prices.parquet found — generating toy GBM data for %d tickers.", len(config.universe)
    )
    return _make_toy(config, seed=seed)


def _make_toy(config: ExperimentConfig, *, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic toy prices from config."""
    return generate_gbm_prices(
        tickers=list(config.universe),
        n_assets=len(config.universe),
        start=config.start_date,
        end=config.end_date,
        seed=seed,
    )
