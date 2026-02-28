# Alpha Research Lab — Data Plane MVP Implementation Plan

> **Stage:** 2 of 8 · Entrypoint A: Data Collector  
> **Prerequisite:** Foundation Stage (complete — 138 tests, all quality gates green)  
> **Focus:** Prediction market data collection via `pmxt` — polling + streaming connectors, bronze/silver storage, data quality automation, backfill/replay tooling  
> **Estimated Effort:** 180–320 hours (single engineer)  
> **Environment:** Python 3.11 (conda `py311`)

---

## Table of Contents

1. [Overview & Objectives](#1-overview--objectives)
2. [Foundation Baseline — What We Start With](#2-foundation-baseline--what-we-start-with)
3. [Data Plane MVP Scope](#3-data-plane-mvp-scope)
4. [Architecture — Data Collection Pipeline](#4-architecture--data-collection-pipeline)
5. [Implementation Steps](#5-implementation-steps)
6. [Baseline Targets & Acceptance Criteria](#6-baseline-targets--acceptance-criteria)
7. [Test Requirements](#7-test-requirements)
8. [Codebase Evolution — File-by-File](#8-codebase-evolution--file-by-file)
9. [Dependencies & New Packages](#9-dependencies--new-packages)
10. [Operational Runbook Stubs](#10-operational-runbook-stubs)

---

## 1. Overview & Objectives

The Data Plane MVP delivers the **first operational entrypoint** — a continuously running data collection system that:

1. **Connects** to prediction market venues (Kalshi, Polymarket, Limitless, Baozi, Myriad, Probable) via `pmxt`
2. **Ingests** market data through both streaming (websocket `watch_*` methods) and polling (REST `fetch_*` methods)
3. **Normalises** raw venue data into canonical events using the Foundation's adapter layer
4. **Stores** data in a tiered layout: raw payloads in bronze, canonical events in silver Parquet
5. **Validates** data quality automatically using configurable expectation suites
6. **Supports backfill** — replay historical windows and fill gaps in the collected dataset
7. **Tracks lineage** — every silver record traces back to its raw source with schema version, run ID, and ingestion metadata

### Alignment with Reference Framework

The PDF framework specifies the data plane must deliver:

> *"Pull/stream from venues/vendors → Normalise to canonical schema → Store 'raw bronze' + 'normalised silver' → Emit quality checks + lineage metadata"*

And must support both:
- **Streaming/event ingestion** for tick-by-tick feeds, order books, venue APIs
- **Scheduled/batch ingestion** for reference data, end-of-day datasets, backfills

This stage implements exactly that pattern, adapted for prediction markets via `pmxt`.

---

## 2. Foundation Baseline — What We Start With

The Foundation Stage delivered these components that the Data Plane builds upon:

| Component | Module | What It Provides |
|---|---|---|
| **Canonical event models** | `alpha_core.events.models` | `CanonicalTrade`, `CanonicalBookSnapshot`, `CanonicalOHLCV`, `CanonicalMetadataUpdate` with bitemporal timestamps |
| **Event quality checker** | `alpha_core.events.quality` | `EventQualityChecker` — validates price bounds, bitemporal order, monotonicity |
| **Instrument master** | `alpha_core.instruments.master` | `MarketMaster` — in-memory registry with Parquet persistence, lifecycle tracking |
| **pmxt adapter** | `alpha_core.adapters.pmxt_adapter` | `PmxtAdapter` — maps `pmxt.Exchange` responses to canonical models; supports all 7 venues |
| **Parquet writer** | `alpha_core.storage.parquet_writer` | `ParquetEventWriter` — partitioned writes for trades, books, OHLCV |
| **Parquet reader** | `alpha_core.storage.parquet_reader` | `ParquetEventReader` — partition-pruned reads (trades only; books/OHLCV readers pending) |
| **DuckDB layer** | `alpha_core.storage.duckdb_layer` | `DuckDBAnalytics` — SQL queries over silver Parquet views |
| **Config system** | `alpha_core.config` | Hierarchical YAML + env overrides, per-venue configs, secret resolution |
| **Storage conventions** | `alpha_core.storage.conventions` | Tier definitions, partition schemes, PyArrow schemas |
| **App stub** | `apps.data_collector.main` | Click CLI skeleton (no logic) |

### Foundation Gaps to Address in Data Plane

| Gap | Resolution in Data Plane |
|---|---|
| `ParquetEventReader` only has `read_trades` | Add `read_books()` and `read_ohlcv()` (Step D2) |
| No bronze (raw) storage | Implement bronze tier writer for raw JSON payloads (Step D2) |
| No streaming capabilities | Add `watch_*` connector wrappers with reconnection (Step D1) |
| No scheduling / orchestration | Add polling scheduler with configurable intervals (Step D3) |
| No data quality suites | Build expectation suites for trades, books, OHLCV (Step D4) |
| No backfill tooling | CLI commands for historical window replay (Step D5) |
| No run/lineage tracking | Ingestion metadata per batch/session (Step D2) |
| `PmxtAdapter` has duplicated helpers | Refactor to use `pmxt_mapping` / `pmxt_parsing` modules cleanly (Step D1) |

---

## 3. Data Plane MVP Scope

### In Scope

| Deliverable | Description |
|---|---|
| **Streaming connectors** | Long-running processes using `pmxt` `watch_trades`, `watch_order_book`, `watch_prices` with automatic reconnection and backpressure |
| **Polling connectors** | Scheduled REST calls to `fetch_markets`, `fetch_trades`, `fetch_ohlcv` with configurable intervals per venue |
| **Market metadata refresher** | Periodic `fetch_markets` → update `MarketMaster`, detect new markets, lifecycle changes |
| **Bronze storage** | Raw JSON payloads stored with ingestion metadata (run_id, ts_record, venue, schema_version) |
| **Silver storage enhancements** | Complete the reader for books + OHLCV; add streaming-write mode with file rotation |
| **Data quality suites** | Automated validation on silver data: null rates, price bounds, monotonic timestamps, stale detection, crossed book detection |
| **Gap detection** | Identify missing time windows per venue/outcome and trigger targeted backfills |
| **Backfill CLI** | CLI commands to replay historical windows from venue APIs and fill gaps |
| **Ingestion metrics** | Counters/gauges for: events ingested, events rejected, latency, uptime per connector |
| **Data collector CLI** | Full `apps/data_collector/main.py` with subcommands: `run`, `backfill`, `status`, `validate` |

### Explicitly Out of Scope

- Feature computation (→ Research Plane MVP)
- Model training / backtesting (→ Research Plane MVP)
- Live order execution (→ Live Plane MVP)
- Grafana dashboards / Prometheus setup (→ Observability Baseline)
- Great Expectations integration (deferred; quality suites use custom lightweight validators first)

---

## 4. Architecture — Data Collection Pipeline

### High-Level Data Flow

```
                         ┌─────────────────────────┐
                         │    pmxt Exchanges        │
                         │  (Kalshi, Polymarket,    │
                         │   Limitless, Baozi,      │
                         │   Myriad, Probable)      │
                         └───────┬────────┬─────────┘
                                 │        │
                    ┌────────────▼──┐  ┌──▼────────────┐
                    │   Streaming   │  │   Polling      │
                    │   Connectors  │  │   Connectors   │
                    │ (watch_trades │  │ (fetch_markets │
                    │  watch_books) │  │  fetch_ohlcv)  │
                    └──────┬───────┘  └──────┬─────────┘
                           │                 │
                    ┌──────▼─────────────────▼──────┐
                    │      Connector Manager         │
                    │  (lifecycle, reconnect,         │
                    │   rate limiting, metrics)       │
                    └──────────────┬─────────────────┘
                                   │
                    ┌──────────────▼─────────────────┐
                    │        Normaliser Pipeline      │
                    │  PmxtAdapter._map_* methods     │
                    │  + EventQualityChecker          │
                    └────────┬──────────┬────────────┘
                             │          │
                    ┌────────▼───┐  ┌───▼────────────┐
                    │  Bronze    │  │   Silver        │
                    │  Writer    │  │   Writer        │
                    │ (raw JSON) │  │ (Parquet,       │
                    │            │  │  partitioned)   │
                    └────────────┘  └───┬────────────┘
                                        │
                    ┌───────────────────▼────────────┐
                    │     Quality Validator           │
                    │  (post-write validation suite   │
                    │   on silver partitions)         │
                    └───────────────────┬────────────┘
                                        │
                    ┌───────────────────▼────────────┐
                    │     Gap Detector               │
                    │  (identify missing windows,    │
                    │   trigger backfill requests)    │
                    └────────────────────────────────┘
```

### Connector Architecture

Each venue gets a `VenueConnector` that manages both streaming and polling for that exchange:

```
VenueConnector (per exchange)
├── StreamingWorker(s)
│   ├── TradeStream    → watch_trades(outcome_id)
│   ├── BookStream     → watch_order_book(outcome_id)
│   └── PriceStream    → watch_prices(outcome_id)
├── PollingWorker(s)
│   ├── MarketRefresher   → fetch_markets() every N minutes
│   ├── OHLCVPoller       → fetch_ohlcv(outcome_id) on schedule
│   └── TradePoller       → fetch_trades(outcome_id) for gap-fill
└── Connector state: connected / reconnecting / stopped / error
```

### Storage Layout After Data Plane

```
data/
├── bronze/
│   ├── trades/
│   │   └── venue=kalshi/date=2026-03-01/
│   │       └── run_20260301T120000Z_abc123.jsonl.gz
│   ├── books/
│   │   └── venue=polymarket/date=2026-03-01/
│   │       └── run_20260301T120000Z_def456.jsonl.gz
│   └── metadata/
│       └── venue=kalshi/date=2026-03-01/
│           └── markets_snapshot_20260301T120000Z.json.gz
├── silver/
│   ├── trades/
│   │   └── venue=kalshi/date=2026-03-01/
│   │       └── part-00000.parquet
│   ├── books/
│   │   └── venue=polymarket/date=2026-03-01/hour=12/
│   │       └── part-00000.parquet
│   └── ohlcv/
│       └── venue=kalshi/resolution=1h/date=2026-03-01/
│           └── part-00000.parquet
└── _lineage/
    └── runs/
        └── run_20260301T120000Z_abc123.json   # Run metadata: venue, start, end, counts, errors
```

---

## 5. Implementation Steps

The Data Plane MVP is broken into **6 sequential sub-steps** (D1–D6). Each step produces a testable, runnable increment.

---

### Step D1: Connector Framework & Adapter Cleanup (Est. 25–40 hrs)

**Goal:** Reusable connector framework with lifecycle management, adapter refactoring, and the first working polling connector.

**Actions:**

1. **Refactor `PmxtAdapter`** to delegate to `pmxt_mapping` / `pmxt_parsing` modules:
   - Remove duplicated static helper methods from `pmxt_adapter.py`
   - Route all mapping through the standalone `pmxt_mapping.*` functions
   - Verify all 138 existing tests still pass after refactor

2. **Create connector base classes** in `apps/data_collector/connectors/`:
   ```python
   # base.py
   class ConnectorState(StrEnum):
       IDLE = "idle"
       RUNNING = "running"
       RECONNECTING = "reconnecting"
       STOPPED = "stopped"
       ERROR = "error"

   class BaseConnector(ABC):
       """Lifecycle-managed connection to a venue."""
       state: ConnectorState
       venue: str
       
       @abstractmethod
       async def start(self) -> None: ...
       @abstractmethod
       async def stop(self) -> None: ...
       @abstractmethod
       def metrics(self) -> ConnectorMetrics: ...

   class PollingConnector(BaseConnector):
       """Base for scheduled REST-polling connectors."""
       interval_seconds: float
       async def poll_once(self) -> list[CanonicalMarketEvent]: ...
       async def run_loop(self) -> None:
           """Poll → normalise → emit, with sleep between cycles."""

   class StreamingConnector(BaseConnector):
       """Base for websocket/long-poll streaming connectors."""
       async def connect(self) -> None: ...
       async def reconnect(self, backoff: float) -> None: ...
       async def stream_loop(self) -> None:
           """Connect → consume → normalise → emit, with auto-reconnect."""
   ```

3. **Create `ConnectorMetrics`** dataclass:
   ```python
   @dataclass
   class ConnectorMetrics:
       events_received: int = 0
       events_normalised: int = 0
       events_rejected: int = 0
       last_event_ts: datetime | None = None
       uptime_seconds: float = 0.0
       reconnect_count: int = 0
       errors: list[str] = field(default_factory=list)
   ```

4. **Implement `MarketRefreshPoller`** — first concrete connector:
   ```python
   class MarketRefreshPoller(PollingConnector):
       """Periodically fetches all markets and updates the MarketMaster."""
       def __init__(self, adapter: PmxtAdapter, master: MarketMaster,
                    interval_seconds: float = 300.0): ...
       async def poll_once(self) -> list[CanonicalMarketEvent]:
           markets = await self.adapter.fetch_markets()
           for m in markets:
               self.master.register_market(m)
           # Emit metadata-update events for new/changed markets
   ```

5. **Create `ConnectorManager`** — orchestrates multiple connectors:
   ```python
   class ConnectorManager:
       """Manages lifecycle of all connectors for all venues."""
       async def register(self, connector: BaseConnector) -> None
       async def start_all(self) -> None
       async def stop_all(self) -> None
       async def status(self) -> dict[str, ConnectorState]
       async def metrics(self) -> dict[str, ConnectorMetrics]
   ```

**Files Created/Modified:**

| Action | Path |
|---|---|
| Create | `apps/data_collector/connectors/__init__.py` |
| Create | `apps/data_collector/connectors/base.py` |
| Create | `apps/data_collector/connectors/metrics.py` |
| Create | `apps/data_collector/connectors/manager.py` |
| Create | `apps/data_collector/connectors/market_refresh.py` |
| Modify | `libs/core/alpha_core/adapters/pmxt_adapter.py` — remove duplicated helpers, delegate to mapping/parsing |
| Modify | `libs/core/alpha_core/adapters/__init__.py` — update exports |

**Tests Added:**

| Test File | Key Cases | Count |
|---|---|---|
| `tests/unit/test_connector_base.py` | State transitions, lifecycle start/stop, metrics initialization | 8–10 |
| `tests/unit/test_market_refresh.py` | Mock adapter → polls → updates master, detects new markets | 6–8 |
| `tests/unit/test_connector_manager.py` | Register/start/stop multiple connectors, status aggregation | 6–8 |
| `tests/unit/test_adapters.py` | **Verify no regressions** after refactor (all existing tests pass) | 0 new (existing) |

**Targets:**

| Metric | Target |
|---|---|
| Existing tests | 138 still passing (0 regressions) |
| New tests | 20–26 |
| `PmxtAdapter` line count | Reduced from ~640 to ~400 (helpers removed) |
| `ruff check` / `mypy --strict` | 0 errors |
| `MarketRefreshPoller` cycle | < 5s per venue (mocked) |

---

### Step D2: Bronze Storage & Lineage Tracking (Est. 25–40 hrs)

**Goal:** Raw data preservation layer (bronze tier) with ingestion metadata and run-level lineage tracking.

**Actions:**

1. **Implement `BronzeWriter`** in `libs/core/alpha_core/storage/`:
   ```python
   class BronzeWriter:
       """Writes raw venue payloads to bronze tier as compressed JSONL."""
       def __init__(self, storage_root: Path, compression: str = "gzip"):
           ...
       def write_raw_events(self, events: list[dict[str, Any]], *,
                            venue: str,
                            event_type: str,
                            run_id: str) -> Path:
           """Write raw payloads to bronze/{event_type}/venue={venue}/date={date}/run_{id}.jsonl.gz"""
       def write_market_snapshot(self, markets: list[dict[str, Any]], *,
                                  venue: str, run_id: str) -> Path:
           """Write raw market metadata snapshot to bronze/metadata/"""
   ```

2. **Implement `IngestionRun`** — lineage tracking model:
   ```python
   class IngestionRun(BaseModel):
       run_id: str                    # UUID or deterministic hash
       venue: str
       connector_type: str            # "polling" | "streaming"
       event_types: list[str]         # What was collected
       started_at: datetime
       completed_at: datetime | None
       status: Literal["running", "completed", "failed"]
       counts: dict[str, int]         # {"trades_raw": 500, "trades_silver": 498, "rejected": 2}
       errors: list[str]
       schema_version: int
       config_snapshot: dict[str, Any]  # Frozen config at run start
   ```

3. **Implement `LineageStore`** — persists run metadata:
   ```python
   class LineageStore:
       """Tracks ingestion runs for auditability."""
       def __init__(self, storage_root: Path): ...
       def start_run(self, venue: str, connector_type: str, ...) -> IngestionRun
       def complete_run(self, run_id: str, counts: dict, errors: list) -> None
       def fail_run(self, run_id: str, error: str) -> None
       def get_run(self, run_id: str) -> IngestionRun | None
       def list_runs(self, venue: str | None, since: datetime | None) -> list[IngestionRun]
   ```

4. **Complete `ParquetEventReader`** — add missing methods:
   ```python
   # In parquet_reader.py
   def read_books(self, venue: str | None = None,
                  start: datetime | None = None,
                  end: datetime | None = None) -> pa.Table: ...
   
   def read_ohlcv(self, venue: str | None = None,
                  resolution: str | None = None,
                  start: datetime | None = None,
                  end: datetime | None = None) -> pa.Table: ...
   ```

5. **Add streaming-write mode** to `ParquetEventWriter`:
   ```python
   class StreamingParquetWriter:
       """Buffers events and periodically rotates to new Parquet files."""
       def __init__(self, writer: ParquetEventWriter, *,
                    max_buffer_size: int = 10_000,
                    max_buffer_age_seconds: float = 60.0): ...
       def append(self, event: CanonicalMarketEvent) -> None
       def flush(self) -> Path | None
       def close(self) -> None
   ```

**Files Created/Modified:**

| Action | Path |
|---|---|
| Create | `libs/core/alpha_core/storage/bronze_writer.py` |
| Create | `libs/core/alpha_core/storage/streaming_writer.py` |
| Create | `libs/core/alpha_core/storage/lineage.py` |
| Modify | `libs/core/alpha_core/storage/parquet_reader.py` — add `read_books`, `read_ohlcv` |
| Modify | `libs/core/alpha_core/storage/__init__.py` — update exports |

**Tests Added:**

| Test File | Key Cases | Count |
|---|---|---|
| `tests/unit/test_bronze_writer.py` | Write raw events → JSONL.gz created, correct partitions, round-trip decompression | 8–10 |
| `tests/unit/test_lineage.py` | Start/complete/fail runs, list by venue, persistence round-trip | 8–10 |
| `tests/unit/test_streaming_writer.py` | Buffer fills → auto-flush, time-based rotation, manual close | 6–8 |
| `tests/unit/test_storage.py` | **Add** `read_books`, `read_ohlcv` round-trip tests | 6–8 (new) |
| `tests/integration/test_storage_roundtrip.py` | **Extend** with books + OHLCV full pipeline | 4–6 (new) |

**Targets:**

| Metric | Target |
|---|---|
| Bronze write 1K raw events | < 500ms |
| Bronze file compression ratio | ≥ 3:1 (JSONL → gzip) |
| `read_books` / `read_ohlcv` | Partition-pruned reads, correct schema |
| Streaming writer flush latency | < 200ms per flush |
| Lineage store persist + query | < 100ms for 100 runs |
| New tests | 25–35 |

---

### Step D3: Polling Connectors — Trades, OHLCV, Books (Est. 30–50 hrs)

**Goal:** Scheduled polling connectors for all data types across all venues, with rate limiting and error handling.

**Actions:**

1. **Implement `TradePoller`**:
   ```python
   class TradePoller(PollingConnector):
       """Polls fetch_trades for configured outcomes at regular intervals."""
       def __init__(self, adapter: PmxtAdapter, *,
                    outcome_ids: list[str],
                    interval_seconds: float = 30.0,
                    limit_per_poll: int = 100): ...
       async def poll_once(self) -> list[CanonicalTrade]:
           """Fetch trades since last known trade_id, normalise, return."""
   ```

2. **Implement `OHLCVPoller`**:
   ```python
   class OHLCVPoller(PollingConnector):
       """Polls fetch_ohlcv for configured outcomes at regular intervals."""
       def __init__(self, adapter: PmxtAdapter, *,
                    outcome_ids: list[str],
                    resolution: str = "1h",
                    interval_seconds: float = 300.0): ...
       async def poll_once(self) -> list[CanonicalOHLCV]: ...
   ```

3. **Implement `BookSnapshotPoller`**:
   ```python
   class BookSnapshotPoller(PollingConnector):
       """Polls fetch_order_book for configured outcomes."""
       def __init__(self, adapter: PmxtAdapter, *,
                    outcome_ids: list[str],
                    interval_seconds: float = 60.0): ...
       async def poll_once(self) -> list[CanonicalBookSnapshot]: ...
   ```

4. **Implement `RateLimiter`** utility:
   ```python
   class TokenBucketRateLimiter:
       """Per-venue rate limiter respecting venue_config.rate_limit_rpm."""
       def __init__(self, rpm: int): ...
       async def acquire(self) -> None:
           """Block until a token is available."""
       def available(self) -> bool
   ```

5. **Implement `PollingScheduler`** — orchestrator for all polling connectors:
   ```python
   class PollingScheduler:
       """Manages scheduled execution of all polling connectors."""
       def __init__(self, connectors: list[PollingConnector],
                    rate_limiter: TokenBucketRateLimiter): ...
       async def run(self) -> None:
           """Run all pollers concurrently with rate limiting."""
       async def run_once(self) -> dict[str, list[CanonicalMarketEvent]]:
           """Single pass for testing/debugging."""
   ```

6. **Wire polling pipeline** — connector → normaliser → bronze writer → silver writer → quality check:
   ```python
   class PollingPipeline:
       """End-to-end: poll → normalise → store bronze → store silver → validate."""
       def __init__(self, connector: PollingConnector,
                    bronze_writer: BronzeWriter,
                    silver_writer: ParquetEventWriter,
                    quality_checker: EventQualityChecker,
                    lineage_store: LineageStore): ...
       async def execute(self) -> IngestionRun:
           """Run one polling cycle with full pipeline."""
   ```

**Files Created/Modified:**

| Action | Path |
|---|---|
| Create | `apps/data_collector/connectors/trade_poller.py` |
| Create | `apps/data_collector/connectors/ohlcv_poller.py` |
| Create | `apps/data_collector/connectors/book_poller.py` |
| Create | `apps/data_collector/connectors/rate_limiter.py` |
| Create | `apps/data_collector/connectors/scheduler.py` |
| Create | `apps/data_collector/pipeline.py` |

**Tests Added:**

| Test File | Key Cases | Count |
|---|---|---|
| `tests/unit/test_trade_poller.py` | Mock adapter → polls trades, handles empty, deduplicates by trade_id, incremental since | 8–10 |
| `tests/unit/test_ohlcv_poller.py` | Mock adapter → polls OHLCV, correct resolution, handles missing data | 6–8 |
| `tests/unit/test_book_poller.py` | Mock adapter → polls books, handles empty books, correct partitioning | 6–8 |
| `tests/unit/test_rate_limiter.py` | Token refill, blocking when exhausted, concurrent acquire | 5–7 |
| `tests/unit/test_scheduler.py` | Multiple pollers run concurrently, respects rate limits, aggregates results | 6–8 |
| `tests/integration/test_polling_pipeline.py` | Full pipeline: mock exchange → poll → bronze + silver files created → quality passes | 4–6 |

**Targets:**

| Metric | Target |
|---|---|
| Single polling cycle (mock) | < 1s end-to-end |
| Rate limiter accuracy | ≤ 1% overshoot vs configured RPM |
| Deduplication | 0 duplicate trade_ids in silver output |
| Pipeline handles empty responses | No crash, 0 events written |
| New tests | 35–47 |

---

### Step D4: Streaming Connectors (Est. 35–55 hrs)

**Goal:** Long-running websocket-based connectors using `pmxt` `watch_*` methods with auto-reconnection, backpressure, and heartbeat monitoring.

**Actions:**

1. **Implement `TradeStreamConnector`**:
   ```python
   class TradeStreamConnector(StreamingConnector):
       """Streams trades via pmxt.watch_trades with auto-reconnect."""
       def __init__(self, adapter: PmxtAdapter, *,
                    outcome_ids: list[str],
                    reconnect_backoff_base: float = 1.0,
                    reconnect_backoff_max: float = 60.0,
                    heartbeat_timeout: float = 120.0): ...
       
       async def stream_loop(self) -> AsyncGenerator[list[CanonicalTrade], None]:
           """Yield batches of normalised trades. Reconnects on failure."""
   ```

2. **Implement `BookStreamConnector`**:
   ```python
   class BookStreamConnector(StreamingConnector):
       """Streams order book snapshots via pmxt.watch_order_book."""
       # Similar to trade stream but for order book updates
   ```

3. **Implement reconnection logic** with exponential backoff + jitter:
   ```python
   class ReconnectionPolicy:
       """Exponential backoff with jitter for stream reconnection."""
       def __init__(self, base: float = 1.0, max_delay: float = 60.0, jitter: float = 0.5): ...
       def next_delay(self, attempt: int) -> float:
           """Returns delay with exponential backoff + random jitter."""
       def reset(self) -> None
   ```

4. **Implement `StreamingPipeline`** — mirrors polling pipeline but for continuous streams:
   ```python
   class StreamingPipeline:
       """Continuous: stream → buffer → normalise → store bronze → flush silver → validate."""
       def __init__(self, connector: StreamingConnector,
                    bronze_writer: BronzeWriter,
                    streaming_writer: StreamingParquetWriter,
                    quality_checker: EventQualityChecker,
                    lineage_store: LineageStore): ...
       async def run(self) -> None:
           """Run indefinitely, flushing periodically."""
   ```

5. **Implement `HeartbeatMonitor`**:
   ```python
   class HeartbeatMonitor:
       """Detects stale streams (no data for > heartbeat_timeout)."""
       def record_heartbeat(self, connector_id: str) -> None
       def check_stale(self) -> list[str]:
           """Returns connector IDs that haven't received data recently."""
   ```

6. **Implement outcome selection strategy** — which outcomes to stream:
   ```python
   class OutcomeSelector:
       """Selects which outcomes to stream based on volume, liquidity, lifecycle."""
       def __init__(self, master: MarketMaster, *,
                    min_volume: Decimal = Decimal("0"),
                    min_liquidity: Decimal = Decimal("0"),
                    lifecycle_filter: list[MarketLifecycle] = [MarketLifecycle.ACTIVE]): ...
       def select(self, venue: str) -> list[str]:
           """Returns outcome_ids worth streaming for this venue."""
   ```

**Files Created/Modified:**

| Action | Path |
|---|---|
| Create | `apps/data_collector/connectors/trade_stream.py` |
| Create | `apps/data_collector/connectors/book_stream.py` |
| Create | `apps/data_collector/connectors/reconnection.py` |
| Create | `apps/data_collector/connectors/heartbeat.py` |
| Create | `apps/data_collector/connectors/outcome_selector.py` |
| Create | `apps/data_collector/streaming_pipeline.py` |

**Tests Added:**

| Test File | Key Cases | Count |
|---|---|---|
| `tests/unit/test_trade_stream.py` | Mock watch_trades → yields batches, handles disconnection, reconnects | 8–10 |
| `tests/unit/test_book_stream.py` | Mock watch_order_book → yields snapshots, handles errors | 6–8 |
| `tests/unit/test_reconnection.py` | Exponential backoff timing, max cap, jitter bounds, reset | 5–7 |
| `tests/unit/test_heartbeat.py` | Record beats, detect stale, time-based expiry | 4–6 |
| `tests/unit/test_outcome_selector.py` | Filters by volume/liquidity/lifecycle, empty market master | 5–7 |
| `tests/integration/test_streaming_pipeline.py` | Mock stream → bronze + silver files written, rotation triggered | 4–6 |

**Targets:**

| Metric | Target |
|---|---|
| Stream startup time (mock) | < 500ms |
| Reconnection delay (1st attempt) | 1–1.5s (base + jitter) |
| Reconnection delay (10th attempt) | ≤ 60s (capped) |
| Buffer → flush cycle | Triggers at 10K events or 60s, whichever first |
| Heartbeat stale detection | Fires after configurable timeout (default 120s) |
| New tests | 32–44 |

---

### Step D5: Data Quality Suites & Gap Detection (Est. 30–50 hrs)

**Goal:** Automated data quality validation on silver tier partitions, with gap detection and reporting.

**Actions:**

1. **Create quality suite framework** in `libs/core/alpha_core/quality/`:
   ```python
   class QualityExpectation(ABC):
       """Single quality check on a dataset partition."""
       name: str
       severity: Literal["warn", "fail"]  # warn = degraded, fail = block
       
       @abstractmethod
       def validate(self, table: pa.Table) -> QualityResult: ...

   class QualityResult(BaseModel):
       expectation_name: str
       passed: bool
       severity: str
       details: dict[str, Any]    # e.g., {"null_rate": 0.02, "threshold": 0.01}

   class QualitySuite:
       """Collection of expectations run against a dataset."""
       def __init__(self, name: str, expectations: list[QualityExpectation]): ...
       def validate(self, table: pa.Table) -> SuiteReport
   
   class SuiteReport(BaseModel):
       suite_name: str
       passed: bool               # True only if no "fail" severity failures
       degraded: bool             # True if any "warn" severity failures
       results: list[QualityResult]
       validated_at: datetime
       row_count: int
       partition_info: dict[str, str]
   ```

2. **Implement trade quality expectations**:
   ```python
   # In alpha_core/quality/suites/trade_quality.py
   class NullRateExpectation(QualityExpectation):
       """Reject if null rate exceeds threshold for required columns."""
   
   class PriceBoundsExpectation(QualityExpectation):
       """All trade prices must be in [0.0, 1.0]."""
   
   class MonotonicTimestampExpectation(QualityExpectation):
       """ts_event must be non-decreasing within each instrument stream."""
   
   class DuplicateTradeIdExpectation(QualityExpectation):
       """No duplicate trade_ids within a partition."""
   
   class StaleDataExpectation(QualityExpectation):
       """Warn if latest ts_event is older than threshold (e.g., 1 hour)."""
   
   class BitemporalOrderExpectation(QualityExpectation):
       """ts_event <= ts_record for all rows."""

   TRADE_SUITE = QualitySuite("silver_trades", [
       NullRateExpectation(columns=["event_id", "instrument_id", "price", "size"], threshold=0.0, severity="fail"),
       PriceBoundsExpectation(severity="fail"),
       MonotonicTimestampExpectation(severity="warn"),
       DuplicateTradeIdExpectation(severity="fail"),
       StaleDataExpectation(max_age_hours=1, severity="warn"),
       BitemporalOrderExpectation(severity="fail"),
   ])
   ```

3. **Implement book quality expectations**:
   ```python
   # In alpha_core/quality/suites/book_quality.py
   class CrossedBookExpectation(QualityExpectation):
       """Best bid must be < best ask (no crossed books)."""
   
   class EmptyBookExpectation(QualityExpectation):
       """Warn if both bids and asks are empty."""
   
   class PriceLevelOrderExpectation(QualityExpectation):
       """Bids descending, asks ascending."""

   BOOK_SUITE = QualitySuite("silver_books", [...])
   ```

4. **Implement OHLCV quality expectations**:
   ```python
   # In alpha_core/quality/suites/ohlcv_quality.py
   class OHLCVRangeExpectation(QualityExpectation):
       """low <= open,close <= high; all in [0, 1]."""
   
   class VolumeNonNegativeExpectation(QualityExpectation):
       """volume >= 0 for all candles."""
   
   class ResolutionConsistencyExpectation(QualityExpectation):
       """All rows in partition have same resolution value."""

   OHLCV_SUITE = QualitySuite("silver_ohlcv", [...])
   ```

5. **Implement `GapDetector`**:
   ```python
   class GapDetector:
       """Identifies missing time windows in silver data."""
       def __init__(self, reader: ParquetEventReader): ...
       
       def detect_trade_gaps(self, venue: str, outcome_id: str, *,
                             start: datetime, end: datetime,
                             max_gap_seconds: float = 3600.0) -> list[TimeGap]:
           """Returns windows where no trades exist for > max_gap_seconds."""
       
       def detect_ohlcv_gaps(self, venue: str, outcome_id: str, *,
                             resolution: str, start: datetime,
                             end: datetime) -> list[TimeGap]:
           """Returns missing candle periods based on expected resolution."""
   
   class TimeGap(BaseModel):
       venue: str
       outcome_id: str
       gap_start: datetime
       gap_end: datetime
       duration_seconds: float
       event_type: str
   ```

6. **Implement `PartitionValidator`** — runs suites on new partitions:
   ```python
   class PartitionValidator:
       """Validates silver partitions after write and records results."""
       def __init__(self, reader: ParquetEventReader, suites: dict[str, QualitySuite]): ...
       def validate_partition(self, event_type: str, venue: str, date: str,
                              **extra_partitions: str) -> SuiteReport
       def validate_all_recent(self, since: datetime) -> list[SuiteReport]
   ```

**Files Created/Modified:**

| Action | Path |
|---|---|
| Create | `libs/core/alpha_core/quality/__init__.py` |
| Create | `libs/core/alpha_core/quality/base.py` |
| Create | `libs/core/alpha_core/quality/suites/__init__.py` |
| Create | `libs/core/alpha_core/quality/suites/trade_quality.py` |
| Create | `libs/core/alpha_core/quality/suites/book_quality.py` |
| Create | `libs/core/alpha_core/quality/suites/ohlcv_quality.py` |
| Create | `libs/core/alpha_core/quality/gap_detector.py` |
| Create | `libs/core/alpha_core/quality/partition_validator.py` |

**Tests Added:**

| Test File | Key Cases | Count |
|---|---|---|
| `tests/unit/test_quality_base.py` | Suite runs expectations, aggregates pass/fail/degraded, handles empty tables | 8–10 |
| `tests/unit/test_trade_quality.py` | Each expectation: pass case, fail case, edge cases (empty, all null, boundary prices) | 12–15 |
| `tests/unit/test_book_quality.py` | Crossed book detection, empty book, level ordering | 6–8 |
| `tests/unit/test_ohlcv_quality.py` | OHLCV range, volume, resolution consistency | 6–8 |
| `tests/unit/test_gap_detector.py` | No gaps → empty, single gap, multiple gaps, boundary conditions | 8–10 |
| `tests/integration/test_partition_validation.py` | Write silver data → validate → report correct | 4–6 |

**Targets:**

| Metric | Target |
|---|---|
| Validate 10K-row partition | < 1s |
| Gap detection over 30 days | < 2s |
| False positives on clean data | 0% |
| All known-bad samples caught | 100% |
| New tests | 44–57 |

---

### Step D6: Backfill Tools & CLI Wiring (Est. 35–55 hrs)

**Goal:** Complete the data collector CLI with subcommands for running, backfilling, status checking, and validation. Connect all components into a working system.

**Actions:**

1. **Implement `BackfillManager`**:
   ```python
   class BackfillManager:
       """Orchestrates historical data backfills for specific time windows."""
       def __init__(self, adapter: PmxtAdapter,
                    bronze_writer: BronzeWriter,
                    silver_writer: ParquetEventWriter,
                    quality_checker: EventQualityChecker,
                    lineage_store: LineageStore): ...
       
       async def backfill_trades(self, outcome_ids: list[str], *,
                                  start: datetime, end: datetime,
                                  batch_size: int = 500) -> BackfillResult:
           """Fetch historical trades in batches, store bronze + silver."""
       
       async def backfill_ohlcv(self, outcome_ids: list[str], *,
                                 resolution: str, start: datetime,
                                 end: datetime) -> BackfillResult:
           """Fetch historical OHLCV candles."""
       
       async def fill_gaps(self, gaps: list[TimeGap]) -> list[BackfillResult]:
           """Automatically backfill detected gaps."""
   
   class BackfillResult(BaseModel):
       venue: str
       event_type: str
       outcome_ids: list[str]
       window_start: datetime
       window_end: datetime
       events_fetched: int
       events_stored: int
       events_rejected: int
       duration_seconds: float
       run_id: str
   ```

2. **Implement `VenueConnectorFactory`** — creates all connectors for a venue from config:
   ```python
   class VenueConnectorFactory:
       """Creates the right set of connectors for a venue based on config."""
       def __init__(self, config: Settings): ...
       def create_connectors(self, venue: str) -> list[BaseConnector]:
           """Creates market refresh + trade/book/ohlcv pollers/streamers."""
   ```

3. **Wire `apps/data_collector/main.py`** — full CLI:
   ```python
   @click.group()
   def cli(): ...
   
   @cli.command()
   @click.option("--venues", multiple=True, help="Venues to collect (default: all enabled)")
   @click.option("--mode", type=click.Choice(["poll", "stream", "both"]), default="poll")
   @click.option("--config", type=click.Path(), help="Config file override")
   def run(venues, mode, config):
       """Start continuous data collection."""
   
   @cli.command()
   @click.option("--venue", required=True)
   @click.option("--outcomes", multiple=True)
   @click.option("--start", required=True, type=click.DateTime())
   @click.option("--end", required=True, type=click.DateTime())
   @click.option("--event-type", type=click.Choice(["trades", "ohlcv"]), default="trades")
   def backfill(venue, outcomes, start, end, event_type):
       """Backfill historical data for a time window."""
   
   @cli.command()
   def status():
       """Show connector status and recent metrics."""
   
   @cli.command()
   @click.option("--venue", help="Validate specific venue (default: all)")
   @click.option("--since", type=click.DateTime(), help="Validate partitions since date")
   def validate(venue, since):
       """Run data quality validation on silver partitions."""
   
   @cli.command()
   @click.option("--venue", required=True)
   @click.option("--event-type", type=click.Choice(["trades", "ohlcv"]), default="trades")
   @click.option("--start", required=True, type=click.DateTime())
   @click.option("--end", required=True, type=click.DateTime())
   def detect_gaps(venue, event_type, start, end):
       """Detect gaps in collected data."""
   ```

4. **Create venue-specific connector configs** — extend `config/venues/*.yaml`:
   ```yaml
   # config/venues/kalshi.yaml (extended)
   name: kalshi
   exchange_class: Kalshi
   enabled: true
   api_key_env: ALPHA_KALSHI_API_KEY
   private_key_env: ALPHA_KALSHI_PRIVATE_KEY
   rate_limit_rpm: 60
   collection:
     mode: poll               # poll | stream | both
     trade_poll_interval: 30  # seconds
     ohlcv_poll_interval: 300
     book_poll_interval: 60
     market_refresh_interval: 300
     stream_outcomes_max: 50  # max simultaneous streaming outcomes
     heartbeat_timeout: 120
     reconnect_backoff_base: 1.0
     reconnect_backoff_max: 60.0
   ```

5. **Implement config extension** — add collection config to `VenueConfig`:
   ```python
   class CollectionConfig(BaseModel):
       mode: Literal["poll", "stream", "both"] = "poll"
       trade_poll_interval: float = 30.0
       ohlcv_poll_interval: float = 300.0
       book_poll_interval: float = 60.0
       market_refresh_interval: float = 300.0
       stream_outcomes_max: int = 50
       heartbeat_timeout: float = 120.0
       reconnect_backoff_base: float = 1.0
       reconnect_backoff_max: float = 60.0
   
   class VenueConfig(BaseModel):
       # ... existing fields ...
       collection: CollectionConfig = CollectionConfig()
   ```

6. **Create integration smoke test** — end-to-end with mocked pmxt:
   ```python
   # tests/integration/test_data_collector_e2e.py
   async def test_poll_cycle_writes_bronze_and_silver(tmp_path, mock_exchange):
       """Full cycle: config → factory → connectors → poll → pipeline → files exist."""
   
   async def test_backfill_produces_silver_data(tmp_path, mock_exchange):
       """Backfill command → silver parquet files with correct data."""
   
   async def test_gap_detection_and_fill(tmp_path, mock_exchange):
       """Write partial data → detect gaps → backfill → gaps resolved."""
   ```

**Files Created/Modified:**

| Action | Path |
|---|---|
| Create | `apps/data_collector/backfill.py` |
| Create | `apps/data_collector/connectors/factory.py` |
| Modify | `apps/data_collector/main.py` — replace stub with full CLI |
| Modify | `libs/core/alpha_core/config/models.py` — add `CollectionConfig` |
| Modify | `config/venues/*.yaml` — add collection sections |

**Tests Added:**

| Test File | Key Cases | Count |
|---|---|---|
| `tests/unit/test_backfill.py` | Backfill trades/ohlcv, batch pagination, error handling, result counts | 8–10 |
| `tests/unit/test_connector_factory.py` | Factory creates correct connectors per venue config mode | 6–8 |
| `tests/unit/test_cli_commands.py` | CLI --help works, invalid args rejected, config loading | 6–8 |
| `tests/integration/test_data_collector_e2e.py` | Full poll cycle, backfill, gap detection + fill | 6–8 |

**Targets:**

| Metric | Target |
|---|---|
| CLI `--help` for all commands | Works |
| `backfill` 1K trades (mock) | < 5s |
| `validate` 10 partitions | < 10s |
| `detect-gaps` 30-day window | < 2s |
| Config backward compatible | All existing tests pass |
| New tests | 26–34 |
| **Total Data Plane tests** | **≥ 300** (138 foundation + ~162 new) |

---

## 6. Baseline Targets & Acceptance Criteria

### Quantitative Targets

| Category | Metric | Data Plane Target |
|---|---|---|
| **Code quality** | ruff lint errors | 0 |
| | mypy strict errors | 0 |
| | Test coverage (`libs/core/` + `apps/data_collector/`) | ≥ 85% |
| | All tests pass | 100% |
| | Total test count | ≥ 300 |
| **Ingestion performance** | Polling cycle (single venue, mock) | < 1s |
| | Streaming buffer flush | < 200ms |
| | Bronze write 1K events | < 500ms |
| | Silver write 10K events | < 2s |
| **Data quality** | Quality suite on 10K-row partition | < 1s |
| | False positives on clean data | 0% |
| | Detection of known-bad patterns | 100% |
| | Gap detection (30-day window) | < 2s |
| **Reliability** | Connector reconnection | Automatic with exponential backoff |
| | Heartbeat stale detection | Fires within 2× timeout |
| | Backfill handles API errors | Retries with backoff, reports failures |
| | Empty responses | No crashes, 0 events written |
| **Storage** | Bronze compression ratio | ≥ 3:1 |
| | Silver Parquet compression | zstd (default) |
| | Lineage run tracking | Every ingestion run logged |

### Acceptance Criteria (Definition of Done)

The Data Plane MVP is **complete** when all of the following are true:

- [ ] `ruff check . && mypy libs/core --strict` — 0 errors
- [ ] `pytest tests/ -v` — all tests green, ≥ 300 total, ≥ 85% coverage
- [ ] At least 2 venues have working polling connectors (trades + OHLCV + books)
- [ ] `MarketRefreshPoller` updates the `MarketMaster` on schedule
- [ ] Bronze tier stores raw payloads with run_id and compression
- [ ] Silver tier stores normalised events with complete Parquet readers (trades + books + OHLCV)
- [ ] Data quality suites exist for trades, books, and OHLCV
- [ ] Gap detector identifies missing time windows
- [ ] Backfill manager can fill detected gaps
- [ ] Lineage store tracks every ingestion run
- [ ] CLI works: `data_collector run`, `backfill`, `validate`, `status`, `detect-gaps`
- [ ] Streaming writer buffers and rotates correctly
- [ ] All connectors handle errors gracefully (no crashes on API failures)
- [ ] CI pipeline green on GitHub Actions
- [ ] Config system extended for collection settings (backward compatible)

---

## 7. Test Requirements

### Test Pyramid — Data Plane MVP

```
          ┌──────────┐
          │  E2E /   │   4–8 tests
          │  Smoke   │   Full pipeline with mocked pmxt
          ├──────────┤
         │Integration│   16–24 tests
         │  Pipeline │   Polling/streaming → storage → quality
         │  flows    │
         ├───────────┤
        │    Unit     │   ~140 tests
        │ Connectors, │   Pure logic, mocked I/O
        │ quality,    │   Fast (< 10s total)
        │ storage     │
        └─────────────┘
```

### Unit Test Summary by Module

| Module | Test File(s) | Key Test Cases | Min Count |
|---|---|---|---|
| Connector base | `test_connector_base.py` | State machine, lifecycle, metrics | 8 |
| Market refresh | `test_market_refresh.py` | Poll → update master, detect changes | 6 |
| Connector manager | `test_connector_manager.py` | Multi-connector orchestration | 6 |
| Trade poller | `test_trade_poller.py` | Incremental fetch, dedup, edge cases | 8 |
| OHLCV poller | `test_ohlcv_poller.py` | Resolution handling, missing data | 6 |
| Book poller | `test_book_poller.py` | Snapshot capture, empty books | 6 |
| Rate limiter | `test_rate_limiter.py` | Token bucket mechanics | 5 |
| Scheduler | `test_scheduler.py` | Concurrent polling, rate limiting | 6 |
| Trade stream | `test_trade_stream.py` | Stream, disconnect, reconnect | 8 |
| Book stream | `test_book_stream.py` | Stream, error handling | 6 |
| Reconnection | `test_reconnection.py` | Backoff timing, cap, jitter | 5 |
| Heartbeat | `test_heartbeat.py` | Beat recording, stale detection | 4 |
| Outcome selector | `test_outcome_selector.py` | Volume/liquidity/lifecycle filters | 5 |
| Bronze writer | `test_bronze_writer.py` | JSONL.gz creation, partitions | 8 |
| Lineage | `test_lineage.py` | Run lifecycle, persistence | 8 |
| Streaming writer | `test_streaming_writer.py` | Buffer, rotation, flush | 6 |
| Storage readers | `test_storage.py` (extended) | Books + OHLCV readers | 6 |
| Quality base | `test_quality_base.py` | Suite execution, aggregation | 8 |
| Trade quality | `test_trade_quality.py` | All expectations, edges | 12 |
| Book quality | `test_book_quality.py` | Crossed, empty, ordering | 6 |
| OHLCV quality | `test_ohlcv_quality.py` | Range, volume, resolution | 6 |
| Gap detector | `test_gap_detector.py` | Detection, boundaries | 8 |
| Backfill | `test_backfill.py` | Trades/OHLCV, batching | 8 |
| Connector factory | `test_connector_factory.py` | Config → connectors | 6 |
| CLI commands | `test_cli_commands.py` | Help, args, config | 6 |

### Integration Test Summary

| Test File | Scope | Count |
|---|---|---|
| `test_polling_pipeline.py` | Poll → normalise → bronze + silver + quality | 4–6 |
| `test_streaming_pipeline.py` | Stream → buffer → bronze + silver + rotation | 4–6 |
| `test_storage_roundtrip.py` (extended) | Books + OHLCV write → read → DuckDB | 4–6 |
| `test_partition_validation.py` | Write → validate partition → report | 4–6 |
| `test_data_collector_e2e.py` | Full CLI integration smoke tests | 6–8 |

### Test Fixtures — New

| File | Content |
|---|---|
| `tests/data/fixtures/sample_raw_trades.json` | Raw pmxt trade payloads (pre-normalization) |
| `tests/data/fixtures/sample_raw_books.json` | Raw pmxt order book payloads |
| `tests/data/fixtures/bad_trades.json` | Intentionally invalid trades (null prices, future timestamps, out-of-range) |
| `tests/data/fixtures/bad_books.json` | Crossed books, empty books |
| `tests/data/fixtures/gapped_trades.parquet` | Silver trades with intentional time gaps |

---

## 8. Codebase Evolution — File-by-File

### After D1: Connector Framework

```diff
  apps/data_collector/
    __init__.py
-   main.py                              # Was: stub
+   main.py                              # Still stub (wired in D6)
+   connectors/
+     __init__.py
+     base.py                            # BaseConnector, PollingConnector, StreamingConnector, ConnectorState
+     metrics.py                         # ConnectorMetrics dataclass
+     manager.py                         # ConnectorManager orchestrator
+     market_refresh.py                  # MarketRefreshPoller
  libs/core/alpha_core/adapters/
~   pmxt_adapter.py                      # Refactored: ~400 LOC (was ~640), delegates to mapping/parsing
    pmxt_mapping.py                      # Unchanged (already implemented)
    pmxt_parsing.py                      # Unchanged (already implemented)
+
  tests/unit/
+   test_connector_base.py
+   test_market_refresh.py
+   test_connector_manager.py
```

### After D2: Bronze Storage & Lineage

```diff
  libs/core/alpha_core/storage/
+   bronze_writer.py                     # Raw JSONL.gz writer
+   streaming_writer.py                  # Buffered Parquet writer with rotation
+   lineage.py                           # IngestionRun model + LineageStore
~   parquet_reader.py                    # Added: read_books(), read_ohlcv()
+
  tests/unit/
+   test_bronze_writer.py
+   test_lineage.py
+   test_streaming_writer.py
~   test_storage.py                      # Extended with book/OHLCV reader tests
  tests/integration/
~   test_storage_roundtrip.py            # Extended with books + OHLCV
```

### After D3: Polling Connectors

```diff
  apps/data_collector/connectors/
+   trade_poller.py
+   ohlcv_poller.py
+   book_poller.py
+   rate_limiter.py
+   scheduler.py
+ apps/data_collector/pipeline.py        # PollingPipeline
+
  tests/unit/
+   test_trade_poller.py
+   test_ohlcv_poller.py
+   test_book_poller.py
+   test_rate_limiter.py
+   test_scheduler.py
  tests/integration/
+   test_polling_pipeline.py
```

### After D4: Streaming Connectors

```diff
  apps/data_collector/connectors/
+   trade_stream.py
+   book_stream.py
+   reconnection.py
+   heartbeat.py
+   outcome_selector.py
+ apps/data_collector/streaming_pipeline.py
+
  tests/unit/
+   test_trade_stream.py
+   test_book_stream.py
+   test_reconnection.py
+   test_heartbeat.py
+   test_outcome_selector.py
  tests/integration/
+   test_streaming_pipeline.py
```

### After D5: Quality Suites & Gap Detection

```diff
+ libs/core/alpha_core/quality/
+   __init__.py
+   base.py                              # QualityExpectation, QualitySuite, QualityResult, SuiteReport
+   gap_detector.py                      # GapDetector, TimeGap
+   partition_validator.py               # PartitionValidator
+   suites/
+     __init__.py
+     trade_quality.py                   # NullRate, PriceBounds, Monotonic, Duplicate, Stale, Bitemporal
+     book_quality.py                    # CrossedBook, EmptyBook, LevelOrder
+     ohlcv_quality.py                   # OHLCVRange, VolumeNonNeg, ResolutionConsistency
+
  tests/unit/
+   test_quality_base.py
+   test_trade_quality.py
+   test_book_quality.py
+   test_ohlcv_quality.py
+   test_gap_detector.py
  tests/integration/
+   test_partition_validation.py
  tests/data/fixtures/
+   sample_raw_trades.json
+   sample_raw_books.json
+   bad_trades.json
+   bad_books.json
+   gapped_trades.parquet
```

### After D6: Backfill & CLI (Final State)

```diff
+ apps/data_collector/backfill.py        # BackfillManager, BackfillResult
+ apps/data_collector/connectors/factory.py  # VenueConnectorFactory
~ apps/data_collector/main.py            # Full CLI: run, backfill, validate, status, detect-gaps
~ libs/core/alpha_core/config/models.py  # Added CollectionConfig to VenueConfig
~ config/venues/*.yaml                   # Added collection sections
+
  tests/unit/
+   test_backfill.py
+   test_connector_factory.py
+   test_cli_commands.py
  tests/integration/
+   test_data_collector_e2e.py
```

### Complete Post-Data-Plane File Tree (New/Modified Only)

```
alpha-research-lab-private/
├── apps/data_collector/
│   ├── __init__.py
│   ├── main.py                          # Full CLI with subcommands
│   ├── pipeline.py                      # PollingPipeline
│   ├── streaming_pipeline.py            # StreamingPipeline
│   ├── backfill.py                      # BackfillManager
│   └── connectors/
│       ├── __init__.py
│       ├── base.py                      # Connector ABCs + states
│       ├── metrics.py                   # ConnectorMetrics
│       ├── manager.py                   # ConnectorManager
│       ├── factory.py                   # VenueConnectorFactory
│       ├── market_refresh.py            # MarketRefreshPoller
│       ├── trade_poller.py              # TradePoller
│       ├── ohlcv_poller.py              # OHLCVPoller
│       ├── book_poller.py               # BookSnapshotPoller
│       ├── trade_stream.py              # TradeStreamConnector
│       ├── book_stream.py               # BookStreamConnector
│       ├── rate_limiter.py              # TokenBucketRateLimiter
│       ├── scheduler.py                 # PollingScheduler
│       ├── reconnection.py              # ReconnectionPolicy
│       ├── heartbeat.py                 # HeartbeatMonitor
│       └── outcome_selector.py          # OutcomeSelector
├── libs/core/alpha_core/
│   ├── adapters/
│   │   └── pmxt_adapter.py              # Refactored (~400 LOC)
│   ├── config/
│   │   └── models.py                    # + CollectionConfig
│   ├── storage/
│   │   ├── bronze_writer.py             # NEW
│   │   ├── streaming_writer.py          # NEW
│   │   ├── lineage.py                   # NEW
│   │   └── parquet_reader.py            # + read_books, read_ohlcv
│   └── quality/                         # NEW MODULE
│       ├── __init__.py
│       ├── base.py
│       ├── gap_detector.py
│       ├── partition_validator.py
│       └── suites/
│           ├── __init__.py
│           ├── trade_quality.py
│           ├── book_quality.py
│           └── ohlcv_quality.py
├── config/venues/                       # + collection sections
├── tests/
│   ├── unit/                            # +25 new test files
│   ├── integration/                     # +5 new test files
│   └── data/fixtures/                   # +5 new fixture files
└── docs/implementation/
    └── data-plane-mvp.md                # This document
```

---

## 9. Dependencies & New Packages

### New Dependencies for Data Plane

```toml
# Added to pyproject.toml [project] dependencies
dependencies = [
    # ... existing foundation dependencies ...
    "aiofiles>=23.0",          # Async file I/O for bronze writes
    "tenacity>=8.0",           # Retry/backoff utilities for reconnection
]
```

No heavy new frameworks are introduced at this stage. The quality suite framework is custom-built (lightweight) rather than pulling in Great Expectations, which is deferred until the system matures and the overhead is justified.

### Optional Dependencies

```toml
[project.optional-dependencies]
# ... existing dev dependencies ...
dev = [
    # ... existing ...
    "pytest-asyncio>=0.21",    # Already present but now heavily used
    "aioresponses>=0.7",       # Mock aiohttp for integration tests (if needed)
]
```

---

## 10. Operational Runbook Stubs

These are not fully implemented in the Data Plane MVP but are **documented as templates** for the Observability Baseline stage:

### Starting Data Collection

```bash
# Start polling all enabled venues
python -m apps.data_collector.main run --mode poll

# Start with specific venues
python -m apps.data_collector.main run --venues kalshi --venues polymarket --mode poll

# Start streaming + polling
python -m apps.data_collector.main run --mode both
```

### Backfilling Historical Data

```bash
# Backfill trades for specific outcomes
python -m apps.data_collector.main backfill \
    --venue kalshi \
    --start 2026-02-01 \
    --end 2026-03-01 \
    --event-type trades

# Detect and fill gaps automatically
python -m apps.data_collector.main detect-gaps \
    --venue kalshi \
    --event-type trades \
    --start 2026-02-01 \
    --end 2026-03-01
```

### Validating Data Quality

```bash
# Validate all recent silver data
python -m apps.data_collector.main validate

# Validate specific venue since a date
python -m apps.data_collector.main validate --venue polymarket --since 2026-02-28
```

### Checking Status

```bash
# Show all connector states and metrics
python -m apps.data_collector.main status
```

---

## Stage Transition: What Comes Next

After Data Plane MVP, the **Research Plane MVP** builds directly on top:

| Data Plane Provides | Research Plane Consumes |
|---|---|
| Silver trades/books/OHLCV in Parquet | Dataset builder reads silver → gold |
| Quality-validated partitions | Only gold datasets built from valid silver |
| Market master with lifecycle history | Point-in-time universe definitions |
| Gap-free historical data (via backfill) | Continuous time series for backtesting |
| DuckDB query layer | Ad-hoc research queries during exploration |

The Research Plane MVP will add: dataset builders, feature engineering, event-driven backtester, vectorized fast path, and PM-specific evaluation metrics (Brier score, calibration curves).
