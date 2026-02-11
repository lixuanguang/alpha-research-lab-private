#!/usr/bin/env python
"""Ingest a fixed Week-3 macro set from FRED into local parquet files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from lab.core.logging import get_logger, setup_logging
from lab.data.adapters.fred import ingest_fred_series, require_fred_api_key

log = get_logger("scripts.ingest_macro_fred")

DEFAULT_SERIES: dict[str, str] = {
    "cpi": "CPIAUCSL",
    "unemployment": "UNRATE",
    "industrial_production": "INDPRO",
    "effective_fed_funds": "DFF",
    "us_10y_yield": "DGS10",
    "credit_spread_proxy": "BAA10Y",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest macro series from FRED.")
    parser.add_argument("--start", type=str, default="2000-01-01")
    parser.add_argument("--end", type=str, default=str(pd.Timestamp.utcnow().date()))
    parser.add_argument(
        "--series",
        type=str,
        default=",".join(DEFAULT_SERIES.values()),
        help="Comma-separated FRED series IDs.",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args()


def _parse_series_ids(raw: str) -> list[str]:
    ids = [token.strip() for token in raw.split(",")]
    return [series_id for series_id in ids if series_id]


def main() -> None:
    args = _parse_args()
    setup_logging(level=args.log_level)

    try:
        api_key = require_fred_api_key()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

    series_ids = _parse_series_ids(args.series)
    if not series_ids:
        raise SystemExit("No FRED series IDs provided.")

    start = str(pd.Timestamp(args.start).date())
    end = str(pd.Timestamp(args.end).date())
    out_paths = ingest_fred_series(
        series_ids=series_ids,
        start=start,
        end=end,
        api_key=api_key,
    )

    log.info("Ingested %d FRED series for %s..%s", len(out_paths), start, end)
    for series_id, path in out_paths.items():
        log.info("%s -> %s", series_id, path)


if __name__ == "__main__":
    main()
