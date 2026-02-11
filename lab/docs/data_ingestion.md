# Data Ingestion

## Adjustment Policy (Yahoo Finance)

This pipeline uses **dividend/split-adjusted closes** as the canonical price
series:

- Source field: `Adj Close`
- Request mode: `auto_adjust=False`
- Corporate actions (`Dividends`, `Stock Splits`) are fetched separately for
  auditability and diagnostics.

We intentionally do **not** re-apply split/dividend math downstream. The
normalized panel written to `LAB_DATA_ROOT/prices/close.parquet` is already in
adjusted-close space.

## Caching

Cache keys include:

- `source`
- `tickers_hash`
- `start`
- `end`
- `params_hash`

For each key, the cache stores:

- raw panel parquet
- normalized panel parquet

This allows deterministic re-runs with no network calls when inputs match.

