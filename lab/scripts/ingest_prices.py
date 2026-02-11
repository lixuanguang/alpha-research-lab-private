#!/usr/bin/env python
"""
ingest_prices.py
~~~~~~~~~~~~~~~~
Ingest and persist daily close prices + metadata for the macro allocator.

Features
--------
- Adapter-based sources (`yf`, `local`, `synthetic`)
- Batched downloads
- Exponential backoff retries
- Disk cache keyed by source/tickers/date-range/params
- Stable artifacts:
  - `$LAB_DATA_ROOT/prices/raw/<source>_<date_range>_<hash>.parquet`
  - `$LAB_DATA_ROOT/prices/close.parquet`
  - `$LAB_DATA_ROOT/prices/meta.parquet`
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from lab.core.logging import get_logger, setup_logging
from lab.data.ingestion import RetryConfig, run_price_ingestion

log = get_logger("scripts.ingest_prices")


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
        default="yf",
        choices=["yf", "yfinance", "local", "synthetic"],
        help="Price source adapter.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        help="Tickers per network batch (recommended 10-25 for API hygiene).",
    )
    parser.add_argument("--max-attempts", type=int, default=4)
    parser.add_argument("--backoff-initial", type=float, default=1.0)
    parser.add_argument("--backoff-factor", type=float, default=2.0)
    parser.add_argument("--backoff-max", type=float, default=30.0)
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    setup_logging(level=args.log_level)

    cfg_path = Path(args.config)
    if not cfg_path.is_absolute():
        cfg_path = Path.cwd() / cfg_path

    retry = RetryConfig(
        max_attempts=args.max_attempts,
        backoff_initial_s=args.backoff_initial,
        backoff_factor=args.backoff_factor,
        backoff_max_s=args.backoff_max,
    )

    result = run_price_ingestion(
        config_path=cfg_path,
        start=args.start,
        end=args.end,
        source=args.source,
        batch_size=args.batch_size,
        retry=retry,
        cache_params={
            "batch_size": args.batch_size,
            "max_attempts": args.max_attempts,
            "backoff_initial_s": args.backoff_initial,
            "backoff_factor": args.backoff_factor,
            "backoff_max_s": args.backoff_max,
        },
    )

    log.info("Ingestion completed. cache_hit=%s key=%s", result.cache_hit, result.cache_key_id)
    log.info("Raw panel: %s", result.raw_path)
    log.info("Close panel: %s", result.close_path)
    log.info("Meta: %s", result.meta_path)
    if result.actions_path is not None:
        log.info("Actions: %s", result.actions_path)


if __name__ == "__main__":
    main()
