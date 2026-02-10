"""Rebalance schedule helpers."""

from __future__ import annotations

import pandas as pd


def rebalance_dates(index: pd.DatetimeIndex, frequency: str = "W-FRI") -> pd.DatetimeIndex:
    """Return rebalance dates snapped to observed trading dates.

    Parameters
    ----------
    index : pd.DatetimeIndex
        Trading-date index.
    frequency : str
        Pandas offset alias (e.g. ``W-FRI``, ``BMS``).
    """
    if len(index) == 0:
        return index

    idx = pd.DatetimeIndex(index).sort_values().unique()
    theoretical = pd.date_range(idx.min(), idx.max(), freq=frequency)
    rebal = idx.intersection(theoretical)

    if len(rebal) == 0:
        # Keep deterministic fallback when frequency does not align with panel.
        rebal = idx[::21]
    return pd.DatetimeIndex(rebal)
