"""Observation-lag utilities for macro feature panels."""

from __future__ import annotations

import pandas as pd


def _coerce_macro_panel(macro: pd.DataFrame) -> pd.DataFrame:
    out = macro.copy()
    out.index = pd.DatetimeIndex(out.index)
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out


def apply_observation_lag(
    macro: pd.DataFrame,
    *,
    lag_days: int = 30,
    per_series_lag_days: dict[str, int] | None = None,
    calendar_index: pd.DatetimeIndex | None = None,
    backfill_limit: int = 2,
) -> pd.DataFrame:
    """Build a known-at-time macro panel with explicit release lag.

    Rules
    -----
    1. Shift each series by its lag (calendar days) so a value observed on day
       ``d`` is first available on ``d + lag``.
    2. Align to ``calendar_index`` (or the macro index by default).
    3. Optional short-gap backward fill after lagging only.
    """
    if macro.empty:
        target = calendar_index if calendar_index is not None else pd.DatetimeIndex([])
        return pd.DataFrame(index=pd.DatetimeIndex(target), columns=list(macro.columns), dtype=float)

    if lag_days < 0:
        raise ValueError("lag_days must be >= 0.")
    if backfill_limit < 0:
        raise ValueError("backfill_limit must be >= 0.")

    base = _coerce_macro_panel(macro)
    target_idx = (
        pd.DatetimeIndex(calendar_index)
        if calendar_index is not None
        else pd.DatetimeIndex(base.index)
    )
    target_idx = target_idx.sort_values().unique()

    lags = {col: int(lag_days) for col in base.columns}
    for col, value in (per_series_lag_days or {}).items():
        if col in lags:
            lags[col] = int(value)

    out_cols: dict[str, pd.Series] = {}
    for col in base.columns:
        series = pd.to_numeric(base[col], errors="coerce")
        shift_days = lags[col]
        if shift_days < 0:
            raise ValueError(f"per-series lag for {col} must be >= 0.")
        effective_idx = series.index + pd.to_timedelta(shift_days, unit="D")
        known = pd.Series(series.to_numpy(dtype=float), index=effective_idx, name=col)
        known = known[~known.index.duplicated(keep="last")].sort_index()
        aligned = known.reindex(target_idx)
        if backfill_limit > 0:
            aligned = aligned.bfill(limit=backfill_limit)
        out_cols[col] = aligned

    panel = pd.DataFrame(out_cols, index=target_idx).reindex(columns=list(base.columns))
    panel.index.name = base.index.name
    return panel
