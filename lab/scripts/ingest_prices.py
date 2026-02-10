#!/usr/bin/env python
"""
ingest_prices.py
~~~~~~~~~~~~~~~~
Ingest and persist daily close prices + metadata for the macro allocator.

Usage
-----
    make ingest_prices CONFIG=experiments/macro/configs/universe.yaml

By default this script looks for local CSV files under:
    $LAB_DATA_ROOT/raw/prices/<TICKER>.csv
Each CSV should contain date + close columns.
Missing tickers are deterministically backfilled with synthetic prices.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from lab.core.logging import get_logger, setup_logging
from lab.core.paths import data_dir
from lab.data.loaders.prices import write_price_artifacts
from lab.data.synthetic import generate_gbm_prices

log = get_logger("scripts.ingest_prices")

_CLOSE_COLUMN_CANDIDATES = [
    "adj_close",
    "Adj Close",
    "close",
    "Close",
]

_DATE_COLUMN_CANDIDATES = [
    "date",
    "Date",
    "timestamp",
    "Timestamp",
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest multi-asset daily close prices.")
    parser.add_argument(
        "--config",
        required=True,
        type=str,
        help="Path to universe YAML (tickers + ticker_meta).",
    )
    parser.add_argument("--start", type=str, default="2010-01-01")
    parser.add_argument("--end", type=str, default="2024-12-31")
    parser.add_argument(
        "--source",
        type=str,
        default="local",
        choices=["local", "synthetic"],
        help="Price source adapter.",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args()


def _load_universe(path: Path) -> tuple[list[str], pd.DataFrame]:
    raw = yaml.safe_load(path.read_text()) or {}
    tickers = raw.get("tickers", [])
    if not tickers:
        raise ValueError("universe config must define a non-empty 'tickers' list")

    ticker_meta = raw.get("ticker_meta", {})
    records: list[dict[str, object]] = []
    for ticker in tickers:
        info = ticker_meta.get(ticker, {})
        records.append(
            {
                "ticker": ticker,
                "bucket": info.get("bucket", "other"),
                "cost_bps": float(info.get("cost_bps", 5.0)),
                "per_asset_cap": float(info.get("per_asset_cap", 0.35)),
            }
        )

    meta = pd.DataFrame.from_records(records)
    return tickers, meta


def _load_one_csv(path: Path) -> pd.Series:
    raw = pd.read_csv(path)

    date_col = next((c for c in _DATE_COLUMN_CANDIDATES if c in raw.columns), None)
    close_col = next((c for c in _CLOSE_COLUMN_CANDIDATES if c in raw.columns), None)

    if date_col is None or close_col is None:
        raise ValueError(
            f"CSV {path} must include date and close columns (got {list(raw.columns)})."
        )

    s = pd.Series(raw[close_col].to_numpy(), index=pd.to_datetime(raw[date_col]), name=path.stem)
    s = s[~s.index.duplicated(keep="last")]
    s = s.sort_index()
    return s.astype(float)


def _load_local_prices(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    raw_root = data_dir() / "raw" / "prices"
    raw_root.mkdir(parents=True, exist_ok=True)

    loaded: list[pd.Series] = []
    missing: list[str] = []

    for ticker in tickers:
        path = raw_root / f"{ticker}.csv"
        if not path.exists():
            missing.append(ticker)
            continue
        try:
            s = _load_one_csv(path)
            s.name = ticker
            loaded.append(s)
        except Exception as exc:
            log.warning("Failed to load %s: %s", path, exc)
            missing.append(ticker)

    if loaded:
        panel = pd.concat(loaded, axis=1).sort_index()
        panel = panel.loc[start:end]
    else:
        panel = pd.DataFrame(index=pd.bdate_range(start, end))

    if missing:
        synth = generate_gbm_prices(tickers=missing, start=start, end=end, seed=42)
        panel = pd.concat([panel, synth], axis=1)

    panel = panel.reindex(columns=tickers)
    panel = panel.sort_index()
    panel = panel[~panel.index.duplicated(keep="last")]
    panel = panel.ffill().bfill()
    return panel


def _synthetic_prices(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    return generate_gbm_prices(
        tickers=tickers,
        start=start,
        end=end,
        seed=42,
    )


def main() -> None:
    args = _parse_args()
    setup_logging(level=args.log_level)

    cfg_path = Path(args.config)
    if not cfg_path.is_absolute():
        cfg_path = Path.cwd() / cfg_path

    tickers, meta = _load_universe(cfg_path)
    log.info("Universe loaded: %d tickers", len(tickers))

    if args.source == "synthetic":
        close = _synthetic_prices(tickers, args.start, args.end)
    else:
        close = _load_local_prices(tickers, args.start, args.end)

    write_price_artifacts(close, meta)

    # Keep week-1 loader compatibility
    close.to_parquet(data_dir() / "prices.parquet")

    log.info("Saved prices: %d days x %d assets", *close.shape)
    log.info("Saved metadata rows: %d", len(meta))


if __name__ == "__main__":
    main()
