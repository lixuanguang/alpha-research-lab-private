"""
lab.data.loaders.prices
~~~~~~~~~~~~~~~~~~~~~~~
Multi-asset close-price and metadata loaders for macro allocators.

Artifacts
---------
- ``$LAB_DATA_ROOT/prices/close.parquet`` : date x ticker close-price panel
- ``$LAB_DATA_ROOT/prices/meta.parquet``  : ticker metadata (bucket, costs, caps)
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import numpy as np
import pandas as pd

from lab.core.logging import get_logger
from lab.core.paths import data_dir
from lab.data.cache import write_parquet_if_changed
from lab.data.synthetic import generate_gbm_prices

log = get_logger("data.loaders.prices")

_REQUIRED_META_COLUMNS = {
    "ticker",
    "bucket",
    "cost_bps",
    "per_asset_cap",
}


def _prices_root() -> Path:
    root = data_dir() / "prices"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _coerce_price_panel(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.index = pd.DatetimeIndex(out.index)
    out = out[~out.index.duplicated(keep="last")]
    out = out.sort_index()
    if not out.columns.is_unique:
        dup = out.columns[out.columns.duplicated()].tolist()
        raise ValueError(f"close-price columns must be unique, duplicates: {dup}")
    return out


def _validate_close_panel(close: pd.DataFrame) -> None:
    if close.empty:
        raise ValueError("close-price panel is empty after loading and alignment.")
    if not close.index.is_monotonic_increasing or not close.index.is_unique:
        raise ValueError("close-price index must be unique and strictly increasing.")
    if not close.columns.is_unique:
        raise ValueError("close-price columns must be unique.")

    arr = close.to_numpy(dtype=float, copy=False)
    if not np.isfinite(arr).all():
        raise ValueError("close-price panel contains NaN/inf values.")
    if (arr <= 0).any():
        raise ValueError("close-price panel contains non-positive prices.")


def _validate_asset_meta(meta: pd.DataFrame) -> pd.DataFrame:
    """Return a cleaned, validated asset-meta table."""
    missing_cols = _REQUIRED_META_COLUMNS - set(meta.columns)
    if missing_cols:
        raise ValueError(f"asset meta missing required columns: {sorted(missing_cols)}")

    out = meta.copy()
    out["ticker"] = out["ticker"].astype(str).str.strip()
    if out["ticker"].eq("").any():
        raise ValueError("asset meta 'ticker' must be non-empty for all rows.")
    out = out.drop_duplicates(subset=["ticker"], keep="last")
    out = out.sort_values("ticker").reset_index(drop=True)
    out["bucket"] = out["bucket"].astype(str).str.strip()
    out["cost_bps"] = pd.to_numeric(out["cost_bps"], errors="coerce")
    out["per_asset_cap"] = pd.to_numeric(out["per_asset_cap"], errors="coerce")
    if not np.isfinite(out["cost_bps"].to_numpy(dtype=float)).all():
        raise ValueError("asset meta 'cost_bps' must be finite.")
    if not np.isfinite(out["per_asset_cap"].to_numpy(dtype=float)).all():
        raise ValueError("asset meta 'per_asset_cap' must be finite.")
    if (out["cost_bps"] < 0).any():
        raise ValueError("asset meta 'cost_bps' must be >= 0.")
    if (out["per_asset_cap"] <= 0).any():
        raise ValueError("asset meta 'per_asset_cap' must be > 0.")
    if out["bucket"].eq("").any():
        raise ValueError("asset meta 'bucket' must be non-empty for all rows.")
    return out


def _synthetic_prices(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    log.warning(
        "Falling back to synthetic prices for %d tickers (%s to %s).",
        len(tickers),
        start,
        end,
    )
    return generate_gbm_prices(
        tickers=tickers,
        start=start,
        end=end,
        seed=42,
    )


def load_close_prices(
    tickers: Iterable[str],
    start: str,
    end: str,
) -> pd.DataFrame:
    """Load close prices for *tickers* in the requested date range.

    Resolution order
    ----------------
    1. ``$LAB_DATA_ROOT/prices/close.parquet``
    2. legacy ``$LAB_DATA_ROOT/prices.parquet``
    3. deterministic synthetic fallback
    """
    requested = list(dict.fromkeys(tickers))
    if not requested:
        return pd.DataFrame()

    root = _prices_root()
    close_path = root / "close.parquet"
    legacy_path = data_dir() / "prices.parquet"

    source_path: Path | None = None
    if close_path.exists():
        source_path = close_path
    elif legacy_path.exists():
        source_path = legacy_path

    if source_path is None:
        return _synthetic_prices(requested, start, end)

    df = _coerce_price_panel(pd.read_parquet(source_path))
    in_window = df.loc[start:end]
    if in_window.empty:
        log.warning(
            "Price source %s has no rows for requested window %s to %s; using synthetic fallback.",
            source_path,
            start,
            end,
        )
        return _synthetic_prices(requested, start, end)

    available = [t for t in requested if t in in_window.columns]

    if not available:
        return _synthetic_prices(requested, start, end)

    out = in_window[available]
    missing = [t for t in requested if t not in out.columns]
    if missing:
        # Align synthetic fallback columns to observed trading dates so we don't
        # accidentally expand the panel index or introduce cross-asset NaNs.
        synth = _synthetic_prices(missing, start, end).reindex(out.index)
        if synth.isna().any().any():
            synth = synth.ffill().bfill()
        out = pd.concat([out, synth], axis=1)

    out = out.reindex(columns=requested)
    out = _coerce_price_panel(out)
    _validate_close_panel(out)
    return out


def load_asset_meta() -> pd.DataFrame:
    """Load asset metadata from ``meta.parquet`` or ``meta.csv``."""
    root = _prices_root()
    parquet_path = root / "meta.parquet"
    csv_path = root / "meta.csv"

    if parquet_path.exists():
        meta = pd.read_parquet(parquet_path)
    elif csv_path.exists():
        meta = pd.read_csv(csv_path)
    else:
        log.warning("No asset metadata found at %s.", root)
        return pd.DataFrame(columns=sorted(_REQUIRED_META_COLUMNS))

    return _validate_asset_meta(meta)


def write_price_artifacts(
    close: pd.DataFrame,
    meta: pd.DataFrame,
    *,
    only_if_changed: bool = False,
) -> None:
    """Write canonical Week-2 price artifacts under ``$LAB_DATA_ROOT/prices``."""
    root = _prices_root()
    close_out = _coerce_price_panel(close)
    _validate_close_panel(close_out)
    meta_out = _validate_asset_meta(meta)

    close_path = root / "close.parquet"
    if only_if_changed:
        write_parquet_if_changed(close_out, close_path, index=True)
    else:
        close_out.to_parquet(close_path)

    meta_path = root / "meta.parquet"
    if only_if_changed:
        write_parquet_if_changed(meta_out, meta_path, index=False)
    else:
        meta_out.to_parquet(meta_path, index=False)
    meta_out.to_csv(root / "meta.csv", index=False)
