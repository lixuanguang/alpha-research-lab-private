"""Rolling risk-contribution diagnostics."""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_risk_contributions(
    weights: pd.DataFrame,
    asset_returns: pd.DataFrame,
    meta: pd.DataFrame,
    window: int = 63,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute asset- and bucket-level risk contributions over time.

    Uses the standard approximation for each timestamp ``t``:
    ``RC_i = w_i * (Sigma_t w)_i / (w' Sigma_t w)``.
    """
    if weights.empty or asset_returns.empty:
        empty = pd.DataFrame(index=weights.index, columns=weights.columns, dtype=float)
        return empty, pd.DataFrame(index=weights.index, dtype=float)

    common_dates = weights.index.intersection(asset_returns.index)
    cols = weights.columns.intersection(asset_returns.columns)

    w_df = weights.reindex(index=common_dates, columns=cols).fillna(0.0)
    r_df = asset_returns.reindex(index=common_dates, columns=cols).fillna(0.0)

    asset_rc = pd.DataFrame(index=common_dates, columns=cols, dtype=float)

    for dt in common_dates:
        hist = r_df.loc[:dt].tail(window)
        if len(hist) < max(5, window // 4):
            continue

        sigma = hist.cov().to_numpy(dtype=float)
        w = w_df.loc[dt].to_numpy(dtype=float)

        port_var = float(w.T @ sigma @ w)
        if not np.isfinite(port_var) or port_var <= 0:
            continue

        mrc = sigma @ w
        rc = (w * mrc) / port_var
        asset_rc.loc[dt] = rc

    bucket_map = meta.set_index("ticker").reindex(cols)["bucket"].fillna("other")
    bucket_names = sorted(bucket_map.unique())
    bucket_rc = pd.DataFrame(index=asset_rc.index, columns=bucket_names, dtype=float)

    for bucket in bucket_names:
        members = bucket_map[bucket_map == bucket].index
        bucket_rc[bucket] = asset_rc[members].sum(axis=1)

    return asset_rc.fillna(0.0), bucket_rc.fillna(0.0)
