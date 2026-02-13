"""Snapshot-keyed feature store for macro allocator experiments."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from lab.core.paths import data_dir
from lab.data.cache import write_parquet_if_changed
from lab.features.macro.ts_trend import compute_ts_trend_scores


def feature_store_path(
    snapshot_id: str,
    *,
    namespace: str = "macro_allocator",
    root: Path | None = None,
) -> Path:
    base = root if root is not None else data_dir() / "features" / namespace
    base.mkdir(parents=True, exist_ok=True)
    sid = str(snapshot_id).strip()
    if not sid:
        raise ValueError("snapshot_id must be non-empty.")
    return base / f"{sid}.parquet"


def _flatten(feature_name: str, panel: pd.DataFrame) -> pd.DataFrame:
    out = panel.copy()
    out.columns = [f"{feature_name}__{col!s}" for col in out.columns]
    return out


def _value_scores(prices: pd.DataFrame, lookback: int = 252) -> pd.DataFrame:
    logp = np.log(prices.replace(0.0, np.nan))
    mean = logp.rolling(lookback, min_periods=max(20, lookback // 4)).mean()
    std = logp.rolling(lookback, min_periods=max(20, lookback // 4)).std()
    z = (logp - mean).div(std.replace(0.0, np.nan))
    # Contrarian value proxy; lag by one day for causal use.
    return (-z).shift(1).clip(-1.0, 1.0).fillna(0.0).astype(float)


def _defensive_scores(
    *,
    regime_indicator: pd.Series,
    meta: pd.DataFrame,
    tickers: list[str],
) -> pd.DataFrame:
    regime = regime_indicator.reindex(regime_indicator.index).fillna(0).astype(int)
    bucket_map = meta.set_index("ticker").reindex(tickers)["bucket"].fillna("other")
    out = pd.DataFrame(index=regime.index, columns=tickers, dtype=float)
    for ticker in tickers:
        bucket = str(bucket_map.get(ticker, "other")).lower()
        if bucket in {"rates"}:
            risk_on, risk_off = -0.25, 1.0
        elif bucket in {"equities", "credit"}:
            risk_on, risk_off = 0.5, -1.0
        else:
            risk_on, risk_off = 0.0, 0.5
        out[ticker] = np.where(regime == 1, risk_off, risk_on)
    return out.clip(-1.0, 1.0).astype(float)


def build_macro_allocator_feature_frame(
    *,
    prices: pd.DataFrame,
    macro_known: pd.DataFrame,
    meta: pd.DataFrame,
    regime_indicator: pd.Series,
) -> pd.DataFrame:
    """Create analysis-ready, no-lookahead feature panel."""
    tickers = list(prices.columns)
    returns = prices.pct_change().shift(1).fillna(0.0).astype(float)
    realized_vol = (
        prices.pct_change().rolling(21, min_periods=21).std().shift(1).mul(np.sqrt(252.0)).fillna(0.0)
    )
    trend = compute_ts_trend_scores(prices)
    value = _value_scores(prices)
    defensive = _defensive_scores(
        regime_indicator=regime_indicator.reindex(prices.index).fillna(0).astype(int),
        meta=meta,
        tickers=tickers,
    )

    macro_cols = macro_known.reindex(prices.index).copy()
    macro_cols = macro_cols.replace([np.inf, -np.inf], np.nan).ffill().fillna(0.0)
    macro_cols.columns = [f"macro_known__{col!s}" for col in macro_cols.columns]

    frame = pd.concat(
        [
            _flatten("returns", returns),
            _flatten("realized_vol", realized_vol),
            _flatten("trend_score", trend),
            _flatten("value_score", value),
            _flatten("defensive_score", defensive),
            pd.DataFrame({"regime_indicator": regime_indicator.reindex(prices.index).fillna(0).astype(int)}),
            macro_cols,
        ],
        axis=1,
    )
    frame.index = pd.DatetimeIndex(frame.index)
    frame = frame.sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    return frame


def write_macro_allocator_feature_store(
    *,
    snapshot_id: str,
    features: pd.DataFrame,
    root: Path | None = None,
) -> Path:
    path = feature_store_path(snapshot_id, root=root)
    write_parquet_if_changed(features, path, index=True)
    return path


def load_macro_allocator_feature_store(
    *,
    snapshot_id: str,
    root: Path | None = None,
) -> pd.DataFrame:
    path = feature_store_path(snapshot_id, root=root)
    if not path.exists():
        raise FileNotFoundError(f"Feature store not found for snapshot_id={snapshot_id}: {path}")
    out = pd.read_parquet(path)
    out.index = pd.DatetimeIndex(out.index)
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out


def load_or_build_macro_allocator_feature_store(
    *,
    snapshot_id: str,
    prices: pd.DataFrame,
    macro_known: pd.DataFrame,
    meta: pd.DataFrame,
    regime_indicator: pd.Series,
    root: Path | None = None,
) -> tuple[pd.DataFrame, Path, bool]:
    """Return `(features, path, loaded_from_cache)`."""
    path = feature_store_path(snapshot_id, root=root)
    if path.exists():
        return load_macro_allocator_feature_store(snapshot_id=snapshot_id, root=root), path, True

    features = build_macro_allocator_feature_frame(
        prices=prices,
        macro_known=macro_known,
        meta=meta,
        regime_indicator=regime_indicator,
    )
    write_macro_allocator_feature_store(snapshot_id=snapshot_id, features=features, root=root)
    return features, path, False
