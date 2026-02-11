# Data Ingestion

## Adjustment Policy (Yahoo Finance)

This pipeline uses adjusted tradable series from Yahoo:

- Request mode: `auto_adjust=True`
- Grouping: `group_by="ticker"`
- Canonical OHLCV fields: `close`, `open`, `high`, `low`, `volume`

The canonical close panel at `LAB_DATA_ROOT/prices/close.parquet` is derived
from adjusted `close` values and already reflects split/dividend adjustments.
Corporate actions are persisted separately for diagnostics.

Missing-value handling is conservative:

- single aligned date index across tickers
- short forward-fill only (`limit=3`)
- any still-incomplete rows are dropped

See `docs/data_provenance.md` for full policy and macro-data provenance.

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
