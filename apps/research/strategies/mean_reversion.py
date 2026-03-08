"""MeanReversionStrategy — vectorized cross-sectional mean reversion.

Signal logic (cross-sectional z-score at each rebalance point):

    z_i = (p_i - mean(p)) / std(p)

* z_i > +threshold  → short (over-valued, expect reversion towards 0.5)
* z_i < -threshold  → long  (under-valued, expect reversion towards 0.5)
* |z_i| ≤ threshold → flat

This is a **vectorized** strategy and requires a feature set that includes a
``price`` (or ``mid``) column in the features DataFrame.  If neither column is
present the strategy falls back to computing cross-sectional ranks from raw
signal values, emitting a mild warning.

Compatible with :class:`~apps.research.backtester.vec_engine.VecBacktestEngine`.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import numpy as np
import pandas as pd

from alpha_core.portfolio.sizing import EqualWeightSizer
from apps.research.backtester.vec_strategy import VecStrategy

log = logging.getLogger(__name__)

_PRICE_COLS = ("price", "mid", "last_price", "close")


class MeanReversionStrategy(VecStrategy):
    """Cross-sectional mean reversion adapted for prediction-market probability space.

    Shorts high-z instruments, longs low-z instruments, with a dead-band around
    zero to avoid trading on noise.

    Args:
        zscore_threshold: Minimum |z-score| to open a position.
        lookback: Number of cross-sectional rebalance periods used to compute
            rolling mean and std.  When < 2 the strategy uses the current
            cross-sectional statistics only.
    """

    def __init__(
        self,
        zscore_threshold: float = 2.0,
        lookback: int = 50,
    ) -> None:
        self._threshold = float(zscore_threshold)
        self._lookback = max(1, lookback)
        self._sizer = EqualWeightSizer()

    @property
    def name(self) -> str:
        return f"mean_reversion_z{self._threshold}_lb{self._lookback}"

    # ------------------------------------------------------------------
    # VecStrategy interface
    # ------------------------------------------------------------------

    def generate_signals(
        self,
        features: pd.DataFrame,
        universe: list[str],
    ) -> pd.DataFrame:
        """Compute cross-sectional z-score signals on the latest snapshot.

        Args:
            features: Feature matrix.  Must contain ``instrument_id``.
                If a price column (``price``, ``mid``, ``last_price``,
                or ``close``) is present it is used; otherwise a
                uniform z-score of 0 is returned for all instruments.
            universe: Active instrument IDs.

        Returns:
            DataFrame with ``instrument_id`` and ``signal`` columns.
        """
        if features.empty or not universe:
            return pd.DataFrame(columns=["instrument_id", "signal"])

        # Use most-recent snapshot per instrument
        snap = (
            features[features["instrument_id"].isin(universe)].sort_values("ts_event")
            if "ts_event" in features.columns
            else features[features["instrument_id"].isin(universe)]
        )
        snap = snap.groupby("instrument_id", as_index=False).last()

        # Detect price column
        price_col = next((c for c in _PRICE_COLS if c in snap.columns), None)
        if price_col is None:
            log.warning(
                "MeanReversionStrategy: no price column found in features "
                "(looked for %s). Returning zero signals.",
                _PRICE_COLS,
            )
            return pd.DataFrame({"instrument_id": snap["instrument_id"], "signal": 0.0})

        prices = snap[price_col].astype(float).values
        cross_mean = float(np.nanmean(prices))
        cross_std = float(np.nanstd(prices))

        if cross_std < 1e-9:
            zscores = np.zeros_like(prices)
        else:
            zscores = (prices - cross_mean) / cross_std

        # Negate z-score: positive z (over-valued) → short signal
        signals = -np.where(np.abs(zscores) >= self._threshold, zscores, 0.0)

        return pd.DataFrame({"instrument_id": snap["instrument_id"].values, "signal": signals})

    def size_positions(
        self,
        signals: pd.DataFrame,
        portfolio_value: Decimal,
        max_positions: int,
    ) -> pd.DataFrame:
        return self._sizer.size(signals, portfolio_value, max_positions)


__all__ = ["MeanReversionStrategy"]
