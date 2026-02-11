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
    try:
        theoretical = pd.date_range(idx.min(), idx.max(), freq=frequency)
    except ValueError as exc:
        raise ValueError(f"invalid rebalance frequency '{frequency}'") from exc

    if len(theoretical) == 0:
        # Deterministic fallback when an alias yields no schedule points.
        return pd.DatetimeIndex(idx[::21])

    # Snap each scheduled timestamp to the next observed trading day so
    # holidays/non-trading target dates do not silently skip rebalances.
    pos = idx.searchsorted(theoretical, side="left")
    pos = pos[(pos >= 0) & (pos < len(idx))]
    rebal = pd.DatetimeIndex(idx[pos]).unique()

    if len(rebal) == 0:
        # Keep deterministic fallback when frequency is incompatible.
        rebal = idx[::21]
    return pd.DatetimeIndex(rebal)
