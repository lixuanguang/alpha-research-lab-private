# Gold Dataset Collection And Streaming Guide (Current Architecture)

> Last updated: March 2, 2026  
> Scope: What is implemented in the current codebase today.

---

## 1. Current-State Summary

In the current architecture, the data collector writes:

- `bronze/` (raw payloads, JSONL/JSON gzip)
- `silver/` (canonical Parquet events)
- `_lineage/` (ingestion run metadata)

`gold/` exists as a configured storage tier (`storage.gold_path`, `StorageTier.GOLD`), but there is no built-in gold dataset builder CLI yet.  
So "collect and stream gold datasets" currently means:

1. Collect and stream venue data into silver continuously.
2. Materialize curated gold datasets from silver on a short cadence (micro-batch loop).

---

## 2. End-To-End Flow

```text
pmxt venues
  -> polling/streaming connectors
  -> quality filter
  -> bronze (raw payloads) + silver (canonical parquet)
  -> gold materializer job (batch or micro-batch)
  -> research/strategy consumers
```

---

## 3. Prerequisites

1. Install and validate environment:

```bash
conda activate py311
pip install -e ".[dev]"
python scripts/validate_env.py
```

2. Enable venues in `config/user_settings.yaml` (if using user toggles).
3. Configure required secrets in `secrets/<venue>.secrets` (or env vars) with secure permissions:

```bash
chmod 600 secrets/*.secrets
```

4. Validate config/secrets:

```bash
python -m apps.data_collector.main validate --apply-user-settings
```

---

## 4. Collect And Stream Data (Bronze/Silver)

### 4.1 Plan-only dry run

```bash
python -m apps.data_collector.main run --mode both
```

### 4.2 Execute one polling cycle

```bash
python -m apps.data_collector.main run \
  --mode poll \
  --execute \
  --once \
  --venues polymarket
```

### 4.3 Continuous streaming (recommended for live gold refresh)

```bash
python -m apps.data_collector.main run \
  --mode stream \
  --execute \
  --continuous \
  --venues polymarket \
  --max-outcomes-per-venue 100 \
  --request-timeout-seconds 15
```

### 4.4 Mixed mode (polling + streaming)

```bash
python -m apps.data_collector.main run \
  --mode both \
  --execute \
  --continuous \
  --venues polymarket
```

---

## 5. Validate Runtime Health And Data Quality

```bash
# Runtime summary and last 24h lineage counters
python -m apps.data_collector.main status

# Partition-level quality checks from a time window
python -m apps.data_collector.main validate \
  --venue polymarket \
  --since 2026-03-01T00:00:00Z
```

---

## 6. Detect And Backfill Gaps Before Gold Build

```bash
# Detect trade gaps
python -m apps.data_collector.main detect-gaps \
  --venue polymarket \
  --event-type trades \
  --start 2026-03-01T00:00:00Z \
  --end 2026-03-02T00:00:00Z \
  --max-gap-hours 1

# Backfill trades for missing windows/outcomes
python -m apps.data_collector.main backfill \
  --venue polymarket \
  --outcomes polymarket:market-a:yes \
  --start 2026-03-01T00:00:00Z \
  --end 2026-03-01T06:00:00Z \
  --event-type trades \
  --batch-size 500
```

---

## 7. Materialize Gold Dataset (Batch Pattern)

Use this when you want a deterministic snapshot from validated silver data.

```python
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import json

import pyarrow.parquet as pq

from alpha_core.storage.parquet_reader import ParquetEventReader

storage_root = Path("data")
dataset_id = "pm_gold_20260302"
venue = "polymarket"
start = datetime(2026, 3, 1, 0, 0, tzinfo=UTC)
end = datetime(2026, 3, 2, 0, 0, tzinfo=UTC)

reader = ParquetEventReader(storage_root)
trades = reader.read_trades(venue=venue, start=start, end=end)
books = reader.read_books(venue=venue, start=start, end=end)
ohlcv = reader.read_ohlcv(venue=venue, resolution="1h", start=start, end=end)

gold_root = storage_root / "gold" / "datasets" / dataset_id
(gold_root / "_meta").mkdir(parents=True, exist_ok=True)

if trades.num_rows:
    pq.write_to_dataset(
        trades,
        root_path=str(gold_root / "trades"),
        partition_cols=["venue", "date"],
        compression="zstd",
    )
if books.num_rows:
    pq.write_to_dataset(
        books,
        root_path=str(gold_root / "books"),
        partition_cols=["venue", "date", "hour"],
        compression="zstd",
    )
if ohlcv.num_rows:
    pq.write_to_dataset(
        ohlcv,
        root_path=str(gold_root / "ohlcv"),
        partition_cols=["venue", "resolution", "date"],
        compression="zstd",
    )

manifest = {
    "dataset_id": dataset_id,
    "venue": venue,
    "window_start": start.isoformat(),
    "window_end": end.isoformat(),
    "counts": {
        "trades": trades.num_rows,
        "books": books.num_rows,
        "ohlcv": ohlcv.num_rows,
    },
}
(gold_root / "_meta" / "manifest.json").write_text(
    json.dumps(manifest, indent=2), encoding="utf-8"
)
print(f"gold dataset ready: {gold_root}")
```

---

## 8. Stream Gold Dataset (Micro-Batch Pattern)

Use this while `run --mode stream --execute --continuous` is active.

### Terminal A: continuous silver ingestion

```bash
python -m apps.data_collector.main run \
  --mode stream \
  --execute \
  --continuous \
  --venues polymarket
```

### Terminal B: micro-batch gold refresher

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import time

import pyarrow.parquet as pq

from alpha_core.storage.parquet_reader import ParquetEventReader

storage_root = Path("data")
dataset_id = "pm_gold_live"
venue = "polymarket"
poll_seconds = 30

gold_root = storage_root / "gold" / "datasets" / dataset_id
state_path = gold_root / "_state" / "trades_watermark.txt"
state_path.parent.mkdir(parents=True, exist_ok=True)
reader = ParquetEventReader(storage_root)

def load_watermark() -> datetime | None:
    if not state_path.exists():
        return None
    return datetime.fromisoformat(state_path.read_text(encoding="utf-8").strip()).astimezone(UTC)

def save_watermark(ts: datetime) -> None:
    state_path.write_text(ts.astimezone(UTC).isoformat(), encoding="utf-8")

while True:
    watermark = load_watermark()
    start = watermark + timedelta(microseconds=1) if watermark else None
    trades = reader.read_trades(venue=venue, start=start, end=None)

    if trades.num_rows:
        pq.write_to_dataset(
            trades,
            root_path=str(gold_root / "trades"),
            partition_cols=["venue", "date"],
            compression="zstd",
        )
        max_ts = max(trades.column("ts_event").to_pylist())
        save_watermark(max_ts)
        print(f"appended {trades.num_rows} rows; watermark={max_ts.isoformat()}")

    time.sleep(poll_seconds)
```

---

## 9. Storage Layout Reference

Key paths written by current pipelines:

- Bronze raw payloads:  
  `data/bronze/{event_type}/venue={venue}/date={YYYY-MM-DD}/run_{run_id}.jsonl.gz`
- Silver canonical events:
  - `data/silver/trades/venue={venue}/date={YYYY-MM-DD}/...`
  - `data/silver/books/venue={venue}/date={YYYY-MM-DD}/hour={HH}/...`
  - `data/silver/ohlcv/venue={venue}/resolution={resolution}/date={YYYY-MM-DD}/...`
  - `data/silver/book_deltas/venue={venue}/date={YYYY-MM-DD}/hour={HH}/...`
- Lineage runs:  
  `data/_lineage/runs/run_{run_id}.json`
- Gold datasets (recommended convention for now):  
  `data/gold/datasets/{dataset_id}/{event_type}/...` and `data/gold/datasets/{dataset_id}/_meta/manifest.json`

---

## 10. Operational Recommendations

1. Keep collector as source of truth for ingestion; do not bypass bronze/silver for external feeds.
2. Run `validate` + `detect-gaps` before major gold rebuilds.
3. Treat `event_id` as dedupe key when extending the micro-batch materializer.
4. Version gold outputs by `dataset_id` (timestamp or semantic label), and keep immutable manifests.

