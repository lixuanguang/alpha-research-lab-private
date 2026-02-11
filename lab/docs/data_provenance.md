# Data Provenance

## Price Data (Yahoo Finance)

- Adapter: `python/lab/data/adapters/yfinance.py`
- Download mode: `yf.download(..., auto_adjust=True, group_by="ticker", threads=False)`
- Canonical OHLCV schema (lowercase): `close, open, high, low, volume`
- Canonical tradable close panel: extracted from adjusted `close` and written to
  `LAB_DATA_ROOT/prices/close.parquet`.
- Raw adjusted OHLCV (for analytics/audit) is persisted separately to
  `LAB_DATA_ROOT/prices/raw/*_ohlcv.parquet`.

Why `auto_adjust=True`:
- We standardize on split/dividend-adjusted tradable series to keep return math
  consistent across tickers and avoid duplicate corporate-action adjustments
  downstream.
- Corporate actions are still fetched separately and stored for diagnostics.

Missing-data handling for prices:
- Align to a single date index across requested tickers.
- Conservative forward-fill only (`limit=3`) to handle short exchange-calendar
  mismatches.
- Rows still incomplete after that step are dropped to avoid lookahead or
  synthetic backfills.

## Macro Data (FRED)

- Ingestion script: `scripts/ingest_macro_fred.py`
- Adapter/loader: `python/lab/data/adapters/fred.py`
- API auth: `FRED_API_KEY` environment variable is required; no keys are stored
  in-repo.
- Storage location: `LAB_DATA_ROOT/macro/fred/*.parquet` (one file per series).
- Default Week-3 set:
  - `CPIAUCSL` (CPI)
  - `UNRATE` (unemployment)
  - `INDPRO` (industrial production)
  - `DFF` (effective fed funds)
  - `DGS10` (10y yield)
  - `BAA10Y` (credit-spread proxy)

## Macro Observation Lag Policy

- Feature utility: `python/lab/features/macro/macro_lag.py`
- Default lag: `30` calendar days (configurable per-series).
- Known-at-time panel rule: value at date `t` must come from observation date
  `<= t - lag_days`.
- Alignment fill rule: no forward-looking fills; optional short backward fill
  after lagging only (`backfill_limit`, default `2`).
