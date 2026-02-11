"""Deterministic long/short allocator with explicit gross/net constraints."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd


def _effective_bucket_caps(
    bucket_caps: Mapping[str, float],
    bucket_multipliers: Mapping[str, float] | None,
) -> dict[str, float]:
    if bucket_multipliers is None:
        return {k: float(v) for k, v in bucket_caps.items()}
    return {k: float(v) * float(bucket_multipliers.get(k, 1.0)) for k, v in bucket_caps.items()}


def _apply_bucket_caps(
    weights: pd.Series,
    buckets: pd.Series,
    bucket_caps: Mapping[str, float],
) -> pd.Series:
    w = weights.copy()
    for bucket, cap in bucket_caps.items():
        mask = buckets == bucket
        if not mask.any():
            continue
        if cap <= 0:
            w.loc[mask] = 0.0
            continue
        gross = w.loc[mask].abs().sum()
        if gross > cap and gross > 0:
            w.loc[mask] *= cap / gross
    return w


def _rescale_long_short(weights: pd.Series, target_net: float, target_gross: float) -> pd.Series:
    """Scale long and short sleeves to hit target net/gross when possible."""
    w = weights.copy()
    if target_gross <= 0:
        return w * 0.0

    target_net = float(np.clip(target_net, -target_gross, target_gross))

    long_idx = w[w > 0].index
    short_idx = w[w < 0].index

    long_notional = float(w.loc[long_idx].sum())
    short_notional = float((-w.loc[short_idx]).sum())

    desired_long = (target_gross + target_net) / 2.0
    desired_short = (target_gross - target_net) / 2.0

    if long_notional > 0:
        w.loc[long_idx] *= desired_long / long_notional if desired_long > 0 else 0.0
    elif desired_long > 0 and len(w) > 0:
        # If no long sleeve exists, distribute long notional uniformly.
        w += desired_long / len(w)

    if short_notional > 0:
        w.loc[short_idx] *= desired_short / short_notional if desired_short > 0 else 0.0
    elif desired_short > 0 and len(w) > 0:
        w -= desired_short / len(w)

    return w


def build_weights(
    scores_t: pd.Series,
    vol_t: pd.Series | None,
    meta: pd.DataFrame,
    gross_cap: float,
    net_target: float,
    net_band: float,
    per_asset_cap: float,
    bucket_caps: Mapping[str, float],
    bucket_multipliers: Mapping[str, float] | None = None,
) -> pd.Series:
    """Build constrained long/short portfolio weights for one rebalance timestamp."""
    if len(scores_t) == 0:
        return scores_t.copy()

    tickers = scores_t.index
    meta_idx = meta.set_index("ticker").reindex(tickers)

    caps = meta_idx.get("per_asset_cap", pd.Series(index=tickers, dtype=float)).fillna(
        per_asset_cap
    )
    caps = caps.astype(float)
    buckets = meta_idx.get("bucket", pd.Series(index=tickers, dtype=object)).fillna("other")

    if vol_t is not None:
        vol = vol_t.reindex(tickers).replace(0, np.nan).astype(float)
        raw = scores_t.astype(float).div(vol)
    else:
        raw = scores_t.astype(float).copy()

    raw = raw.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    if raw.abs().sum() == 0:
        return pd.Series(0.0, index=tickers)

    # Initial scaling keeps relative cross-sectional scores and targets gross budget.
    w = raw / raw.abs().sum() * float(gross_cap)

    eff_bucket_caps = _effective_bucket_caps(bucket_caps, bucket_multipliers)

    def _project_once(inp: pd.Series) -> pd.Series:
        out = inp.copy()
        out = out.clip(lower=-caps, upper=caps)
        out = _apply_bucket_caps(out, buckets, eff_bucket_caps)

        gross = out.abs().sum()
        if gross > gross_cap and gross > 0:
            out *= gross_cap / gross

        if abs(out.sum() - net_target) > net_band:
            out = _rescale_long_short(
                out,
                target_net=net_target,
                target_gross=min(float(gross_cap), float(out.abs().sum())),
            )

        return out

    # Iterative projection is deterministic and handles interacting caps.
    for _ in range(10):
        w = _project_once(w)

    # Final hard clamps.
    w = w.clip(lower=-caps, upper=caps)
    w = _apply_bucket_caps(w, buckets, eff_bucket_caps)

    gross = float(w.abs().sum())
    if gross > gross_cap and gross > 0:
        w *= gross_cap / gross

    low = net_target - net_band
    high = net_target + net_band
    net = float(w.sum())
    if net < low or net > high:
        desired = float(np.clip(net_target, -gross_cap, gross_cap))
        w = _rescale_long_short(w, target_net=desired, target_gross=min(gross_cap, w.abs().sum()))
        w = w.clip(lower=-caps, upper=caps)
        w = _apply_bucket_caps(w, buckets, eff_bucket_caps)
        gross = float(w.abs().sum())
        if gross > gross_cap and gross > 0:
            w *= gross_cap / gross

    return w.reindex(tickers).fillna(0.0)
