# Alpha Research Lab — Foundation Stage Implementation Plan

> **Status: COMPLETE** — All F1–F6 steps implemented and closed.  
> See [main README](../../README.md) for current project status.

> **Focus:** Prediction markets alpha research using the `pmxt` unified API  
> **Environment:** Python 3.11 (conda `py311`)  
> **Baseline Reference:** *Institutional-Grade Multi-Asset Alpha Research Implementation Framework*  
> **Estimated Foundation Effort:** 60–120 hours (single engineer)

---

## Table of Contents

1. [Overview & Objectives](#1-overview--objectives)
2. [Architecture — Prediction Markets Adaptation](#2-architecture--prediction-markets-adaptation)
3. [Foundation Stage Scope](#3-foundation-stage-scope)
4. [Repository Structure (Step-by-Step Evolution)](#4-repository-structure-step-by-step-evolution)
5. [Implementation Steps](#5-implementation-steps)
6. [Baseline Targets & Acceptance Criteria](#6-baseline-targets--acceptance-criteria)
7. [Test Requirements](#7-test-requirements)
8. [Codebase Evolution Roadmap](#8-codebase-evolution-roadmap)
9. [Dependencies & Environment](#9-dependencies--environment)
10. [Conventions & Standards](#10-conventions--standards)
11. [Microstructure Foundation Extension (Completed Addendum)](#11-microstructure-foundation-extension-completed-addendum)
12. [Lean Adoption Foundation Extension (March 2026)](#12-lean-adoption-foundation-extension-march-2026)
13. [Lean + QUANTAXIS Foundation Extension (March 2026, Iteration 2)](#13-lean--quantaxis-foundation-extension-march-2026-iteration-2)

---

## 1. Overview & Objectives

This project implements an institutional-grade alpha research platform **specialised for prediction markets**. It follows the three-entrypoint architecture from the reference framework (Data Plane, Trading Plane, Research Plane) built on a shared core, but applies it specifically to the prediction market asset class using the [`pmxt`](https://github.com/pmxt-dev/pmxt) library (v2.18+) as the unified venue connectivity layer.

### Why Prediction Markets?

Prediction markets (Kalshi, Polymarket, Limitless, Baozi, Myriad, Probable) offer:
- Binary/multi-outcome contracts with natural probability interpretations
- Unique microstructure (event-driven resolution, binary payoffs, time-decaying theta)
- Cross-venue arbitrage and relative-value opportunities
- Rich event metadata (categories, tags, resolution dates) for systematic research

### Foundation Stage Goal

Deliver the **repo scaffold, canonical data model, instrument master, configuration system, CI baseline, and local development environment** — the bedrock that every subsequent stage (Data Plane MVP, Research Plane MVP, Live Plane MVP) builds upon.

### Implementation Status (as of March 2, 2026)

- Current stage: **Foundation complete and closed**
- Completed steps: **F1, F2, F3, F4, F5, F6 + addendum 11.1-11.5**
- Remaining foundation steps: **None**
- Current quality gate snapshot: `ruff check .` and `mypy libs/ apps/ --strict` passing locally; `pytest tests/ -v` is green (`644 passed, 8 skipped`)
- Foundation artifact lock added: `data/schemas/canonical_event_v1.json` and `tests/unit/test_foundation_requirements.py`
- Security hardening update: GitHub Actions workflow pins `actions/checkout`, `actions/setup-python`, and `actions/cache` to immutable commit SHAs
- Post-foundation maintenance note: config loading internals are now split across `alpha_core.config._merge` and `alpha_core.config._overrides`, with `alpha_core.config.loader` kept as the public orchestration entrypoint

---

## 2. Architecture — Prediction Markets Adaptation

The reference framework defines three entrypoints on a shared core. For prediction markets via `pmxt`, the mapping is:

```
┌─────────────────────────────────────────────────────────┐
│                      SHARED CORE                        │
│  ┌─────────────┐ ┌──────────────┐ ┌──────────────────┐  │
│  │ Instruments  │ │  Events /    │ │  Portfolio /     │  │
│  │ (Markets,    │ │  Market Data │ │  Positions /     │  │
│  │  Outcomes,   │ │  (Trades,    │ │  Risk / PnL      │  │
│  │  Contracts)  │ │  Books, OHLCV│ │                  │  │
│  └──────┬───────┘ └──────┬───────┘ └────────┬─────────┘  │
│         │                │                   │           │
│  ┌──────┴───────┐ ┌──────┴───────┐ ┌────────┴─────────┐ │
│  │  Execution   │ │  Features    │ │  Config / Utils  │ │
│  │  Abstractions│ │  Primitives  │ │  Time, IDs, Serde│ │
│  └──────────────┘ └──────────────┘ └──────────────────┘  │
└──────────────┬──────────────┬──────────────┬─────────────┘
               │              │              │
      ┌────────▼───┐  ┌──────▼──────┐  ┌────▼──────────┐
      │ Entrypoint │  │ Entrypoint  │  │ Entrypoint    │
      │ A: Data    │  │ B: Live     │  │ C: Research   │
      │ Collector  │  │ System      │  │ & Backtesting │
      └────────────┘  └─────────────┘  └───────────────┘
```

### Prediction Market → Framework Mapping

| Framework Concept | Prediction Markets via `pmxt` |
|---|---|
| `instrument_id` | `market_id` + `outcome_id` (composite key) |
| `venue_id` | Exchange name: `kalshi`, `polymarket`, `limitless`, `baozi`, `myriad`, `probable` |
| `event_type` | `trade`, `quote_l1` (best bid/ask from OrderBook), `ohlcv_bar`, `book_snapshot`, `market_metadata_update` |
| `ts_event` | Trade/candle timestamp from venue |
| `ts_record` | System ingestion timestamp (bitemporal discipline) |
| Instrument master | `UnifiedMarket` + `MarketOutcome` + `UnifiedEvent` metadata |
| Order/Fill model | `pmxt.Order` → internal `OrderIntent` / `ExecutionReport` |
| Position state | `pmxt.Position` → internal `PositionState` |

---

## 3. Foundation Stage Scope

The Foundation Stage delivers **exactly** the following (no more, no less):

| Deliverable | Description |
|---|---|
| **Repo scaffold** | Monorepo layout with `pyproject.toml`, package structure, `libs/core/`, `apps/` stubs, `tests/` |
| **Canonical event model** | Pydantic v2 models for `CanonicalMarketEvent`, `CanonicalTrade`, `CanonicalBookSnapshot`, `CanonicalOHLCV` with bitemporal timestamps |
| **Instrument master skeleton** | `MarketMaster` registry: normalised market/outcome/event metadata from any `pmxt` exchange, with lifecycle tracking (active / halted / resolved / delisted) |
| **pmxt adapter layer** | Thin wrapper over `pmxt.Exchange` that maps vendor models → canonical models, handling venue-specific quirks |
| **Configuration system** | Hierarchical config (YAML + env overrides) for venues, API keys, storage paths, feature flags |
| **Storage conventions** | Parquet partitioning scheme + DuckDB local query layer; bronze/silver tier definitions |
| **CI test baseline** | pytest suite with unit + integration (mock) tests; pre-commit hooks; GitHub Actions CI |
| **Local Docker environment** | `docker-compose.yml` for optional local services (DuckDB is embedded, but scaffolding for future Prometheus/Grafana) |
| **Documentation** | This README + inline docstrings + architecture decision records (ADRs) |

### Explicitly Out of Scope for Foundation

- Live data collection (→ Data Plane MVP)
- Backtesting engine (→ Research Plane MVP)
- Order execution / paper trading (→ Live Plane MVP)
- ML model training / feature store (→ Robustness Hardening)

---

## 4. Repository Structure (Step-by-Step Evolution)

### End-of-Foundation Target Structure

```
alpha-research-lab-private/
├── README.md
├── pyproject.toml                        # PEP 621 project metadata, dependencies, tool config
├── .pre-commit-config.yaml               # pre-commit hooks (ruff, mypy, pytest)
├── .github/
│   └── workflows/
│       └── ci.yml                        # GitHub Actions: lint + type-check + test
├── config/
│   ├── default.yaml                      # Default configuration
│   ├── venues/
│   │   ├── kalshi.yaml                   # Kalshi-specific config
│   │   ├── polymarket.yaml               # Polymarket-specific config
│   │   └── ...                           # One per venue
│   └── environments/
│       ├── local.yaml                    # Local dev overrides
│       └── ci.yaml                       # CI overrides
├── libs/
│   └── core/
│       └── alpha_core/
│           ├── __init__.py
│           ├── instruments/
│           │   ├── __init__.py
│           │   ├── models.py             # Market, Outcome, Event, ContractSpec
│           │   ├── master.py             # MarketMaster registry
│           │   ├── lifecycle.py          # Market lifecycle states & transitions
│           │   └── symbology.py          # Cross-venue symbol resolution
│           ├── events/
│           │   ├── __init__.py
│           │   ├── models.py             # CanonicalMarketEvent, Trade, Book, OHLCV
│           │   ├── schema_version.py     # Schema versioning constants
│           │   └── quality.py            # Event-level quality checks (null, monotonic ts)
│           ├── adapters/
│           │   ├── __init__.py
│           │   ├── base.py               # Abstract VenueAdapter interface
│           │   ├── pmxt_adapter.py        # pmxt.Exchange → canonical model mapper
│           │   └── venue_configs.py      # Per-venue quirks / normalization rules
│           ├── storage/
│           │   ├── __init__.py
│           │   ├── conventions.py        # Partition schemes, tier definitions
│           │   ├── parquet_writer.py     # Write canonical events → Parquet
│           │   ├── parquet_reader.py     # Read from Parquet with filters
│           │   └── duckdb_layer.py       # DuckDB wrapper for local analytics
│           ├── config/
│           │   ├── __init__.py
│           │   ├── loader.py             # YAML + env var hierarchical loader
│           │   ├── models.py             # Pydantic settings models
│           │   └── secrets.py            # API key resolution (env/file/vault stub)
│           └── utils/
│               ├── __init__.py
│               ├── time.py               # Timestamp normalization, timezone handling
│               └── ids.py                # Deterministic ID generation
├── apps/
│   ├── data_collector/                   # Entrypoint A stub
│   │   ├── __init__.py
│   │   └── main.py                       # Placeholder CLI entry
│   ├── live_system/                      # Entrypoint B stub
│   │   ├── __init__.py
│   │   └── main.py
│   └── research/                         # Entrypoint C stub
│       ├── __init__.py
│       └── main.py
├── tests/
│   ├── conftest.py                       # Shared fixtures (mock exchanges, sample data)
│   ├── unit/
│   │   ├── test_instruments.py           # Market/Outcome model tests
│   │   ├── test_events.py               # Canonical event model tests
│   │   ├── test_adapters.py             # pmxt adapter mapping tests
│   │   ├── test_storage.py              # Parquet write/read roundtrip tests
│   │   ├── test_config.py               # Config loading tests
│   │   └── test_utils.py               # Time, ID, logging tests
│   ├── integration/
│   │   ├── test_adapter_mock.py         # Full adapter flow with mocked pmxt
│   │   └── test_storage_roundtrip.py    # Write → read → DuckDB query flow
│   └── data/
│       └── fixtures/
│           ├── sample_markets.json       # Serialized UnifiedMarket samples
│           ├── sample_trades.json        # Serialized Trade samples
│           └── sample_orderbook.json     # Serialized OrderBook samples
├── infra/
│   └── docker/
│       └── docker-compose.yml            # Local dev services scaffold
├── data/
│   └── schemas/
│       └── canonical_event_v1.json       # JSON Schema for canonical events
├── docs/
│   └── adr/
│       ├── 001-monorepo-structure.md
│       ├── 002-canonical-event-model.md
│       └── 003-bitemporal-timestamps.md
└── scripts/
    ├── bootstrap.sh                      # One-command dev setup
    └── validate_env.py                   # Check py311 env has all deps
```

---

## 5. Implementation Steps

The Foundation Stage is broken into **6 sequential sub-steps**. Each step produces a runnable, testable increment.

---

### Step F1: Repo Scaffold & Tooling (Est. 8–12 hrs)

**Goal:** Empty but fully functional Python project with CI.

**Actions:**
1. Initialize `pyproject.toml` with PEP 621 metadata, dependency groups (`[project.optional-dependencies]`)
2. Configure tooling: `ruff` (lint + format), `mypy` (strict), `pytest`
3. Create `.pre-commit-config.yaml` with ruff, mypy, trailing-whitespace hooks
4. Create `.github/workflows/ci.yml` — install deps, lint, type-check, test
5. Create `scripts/bootstrap.sh` — conda env setup + pip install
6. Create `scripts/validate_env.py` — verify Python 3.11, key packages importable

**Tests Added:**
- `tests/unit/test_scaffold.py` — import `alpha_core`, verify version string

**Codebase After F1:**
```
pyproject.toml, .pre-commit-config.yaml, .github/workflows/ci.yml
libs/core/alpha_core/__init__.py (version only)
tests/unit/test_scaffold.py
scripts/bootstrap.sh, scripts/validate_env.py
```

**Targets:**
| Metric | Target |
|---|---|
| `ruff check .` | 0 errors |
| `mypy libs/` | 0 errors |
| `pytest` | 1 test passing |
| CI pipeline | Green on push |

---

### Step F2: Configuration System (Est. 8–12 hrs)

**Goal:** Hierarchical YAML config with env-var overrides and Pydantic validation.

**Actions:**
1. Define `config/default.yaml` with venue list, storage paths, feature flags
2. Create per-venue YAML files (`config/venues/kalshi.yaml`, etc.)
3. Implement `alpha_core/config/loader.py`:
   - Load `default.yaml` → merge environment overlay → merge env vars (`ALPHA_*`) for known config paths
   - Keep venue credential env vars (`ALPHA_<VENUE>_API_KEY`, `ALPHA_<VENUE>_PRIVATE_KEY`) out of config-override parsing
   - Apply `config/user_settings.yaml` only when explicitly requested (`apply_user_settings=True`)
   - Return validated Pydantic `Settings` model
   - Post-maintenance implementation detail: merge/path and override logic now live in `alpha_core.config._merge` and `alpha_core.config._overrides`
4. Implement `alpha_core/config/models.py`:
   ```python
   class VenueConfig(BaseModel):
       name: str                           # e.g. "kalshi"
       exchange_class: str                 # e.g. "Kalshi"
       enabled: bool = True
       api_key_env: str | None = None      # env var name for API key
       private_key_env: str | None = None
       rate_limit_rpm: int = Field(default=60, ge=1)
       
   class StorageConfig(BaseModel):
       base_path: Path
       bronze_path: str = "bronze"
       silver_path: str = "silver"
       gold_path: str = "gold"
       partition_by: list[str] = ["venue", "date"]
       
   class Settings(BaseModel):
       project_name: str = "alpha-research-lab"
       venues: list[VenueConfig]
       storage: StorageConfig
       log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
   ```
5. Implement `alpha_core/config/secrets.py` — resolve API keys from env vars
   - Fallback to `secrets/<venue>.secrets` (`API_KEY_ENV` / `PRIVATE_KEY_ENV`) when no env var is set

**Tests Added:**
- `tests/unit/test_config.py`:
  - Load default config → validates
  - Environment overlay merges correctly
  - Missing required fields → `ValidationError`
  - Env var override works (`ALPHA_LOG_LEVEL=DEBUG`)
  - Secret resolution returns `None` for unset keys (no crash)

**Codebase After F2:**
```diff
+ config/default.yaml, config/venues/*.yaml, config/environments/*.yaml
+ libs/core/alpha_core/config/{__init__, loader, models, secrets}.py
+ tests/unit/test_config.py
```

**Targets:**
| Metric | Target |
|---|---|
| Config loads in | < 50ms |
| Pydantic validation | Catches all invalid configs |
| Test count | 8–12 config tests |
| `mypy --strict` on config module | 0 errors |

---

### Step F3: Canonical Data Models (Est. 12–20 hrs)

**Goal:** Pydantic v2 models for all canonical market data types with bitemporal timestamps and schema versioning.

**Actions:**
1. Implement `alpha_core/events/models.py`:
   ```python
   class CanonicalMarketEvent(BaseModel):
       """Base for all canonical market data events."""
       event_id: str                       # Deterministic hash
       instrument_id: str                  # "{venue}:{market_id}:{outcome_id}"
       venue_id: str                       # Exchange name (lowercase)
       event_type: EventType               # Enum: TRADE, BOOK_SNAPSHOT, OHLCV, METADATA_UPDATE
       ts_event: datetime                  # When the venue says it happened
       ts_record: datetime                 # When our system recorded it
       schema_version: int = 1
       
   class CanonicalTrade(CanonicalMarketEvent):
       event_type: Literal[EventType.TRADE] = EventType.TRADE
       price: Decimal                      # 0.00 – 1.00 for prediction markets
       size: Decimal                       # Number of contracts
       side: TradeSide                     # BUY / SELL
       trade_id: str                       # Venue-native trade ID
       
   class CanonicalBookSnapshot(CanonicalMarketEvent):
       event_type: Literal[EventType.BOOK_SNAPSHOT] = EventType.BOOK_SNAPSHOT
       bids: list[PriceLevel]
       asks: list[PriceLevel]
       
   class CanonicalOHLCV(CanonicalMarketEvent):
       event_type: Literal[EventType.OHLCV] = EventType.OHLCV
       open: Decimal
       high: Decimal
       low: Decimal
       close: Decimal
       volume: Decimal
       resolution: str                     # "1m", "5m", "1h", "1d"
   ```

2. Implement `alpha_core/events/schema_version.py` — version constant + migration stubs

3. Implement `alpha_core/events/quality.py`:
   ```python
   class EventQualityChecker:
       """Validate individual events against quality rules."""
       def check(self, event: CanonicalMarketEvent) -> QualityReport:
           # - ts_event <= ts_record (no future events)
           # - price in [0.0, 1.0] for prediction markets
           # - no null required fields
           # - monotonic ts_event within same instrument stream
   ```

4. Implement `alpha_core/utils/time.py` — UTC normalization, timezone stripping, nanosecond precision helpers

5. Implement `alpha_core/utils/ids.py` — deterministic `event_id` generation (SHA256 of canonical fields)

**Tests Added:**
- `tests/unit/test_events.py`:
  - Construct each event type → serializes to dict / JSON
  - Round-trip: model → dict → model (lossless)
  - Bitemporal invariant: `ts_event <= ts_record` enforced via validator
  - Price bounds: prediction market prices must be [0, 1]
  - Schema version attached to every event
  - Deterministic `event_id` — same inputs → same ID
- `tests/unit/test_utils.py`:
  - UTC normalization (naive → aware, various TZs → UTC)
  - ID generation determinism and collision resistance

**Codebase After F3:**
```diff
+ libs/core/alpha_core/events/{models, schema_version, quality}.py
+ libs/core/alpha_core/utils/{time, ids}.py
+ tests/unit/test_events.py, tests/unit/test_utils.py
```

**Targets:**
| Metric | Target |
|---|---|
| Model instantiation | < 1ms per event |
| Serialization round-trip | 100% fidelity (Decimal precision preserved) |
| Quality checker | Catches 100% of known invalid patterns |
| Test count | 15–25 event/util tests |

---

### Step F4: Instrument Master & Symbology (Est. 12–18 hrs)

**Goal:** Registry that can load, normalize, and query prediction market metadata from any `pmxt` exchange.

**Actions:**
1. Implement `alpha_core/instruments/models.py`:
   ```python
   class MarketLifecycle(str, Enum):
       ACTIVE = "active"
       HALTED = "halted"
       RESOLVED = "resolved"
       DELISTED = "delisted"
       
   class OutcomeSpec(BaseModel):
       outcome_id: str                     # Venue-native outcome ID
       label: str                          # "Yes" / "No" / "Trump" / "Harris" etc.
       canonical_id: str                   # "{venue}:{market_id}:{outcome_id}"
       
   class MarketSpec(BaseModel):
       market_id: str                      # Venue-native market ID
       venue: str                          # Exchange name
       title: str
       description: str | None
       category: str | None
       tags: list[str]
       outcomes: list[OutcomeSpec]
       resolution_date: datetime | None
       lifecycle: MarketLifecycle = MarketLifecycle.ACTIVE
       volume: Decimal | None
       liquidity: Decimal | None
       url: str | None
       first_seen: datetime                # ts_record for market discovery
       last_updated: datetime              # ts_record for last metadata refresh
       
   class EventGroupSpec(BaseModel):
       """Groups related markets (e.g., 'US Election' event with multiple markets)."""
       event_id: str
       title: str
       description: str | None
       markets: list[str]                  # List of canonical market IDs
       url: str | None
   ```

2. Implement `alpha_core/instruments/master.py`:
   ```python
   class MarketMaster:
       """In-memory registry of known markets + outcomes with persistence."""
       async def load_from_exchange(self, adapter: VenueAdapter) -> int:
           """Fetch & register all markets from an exchange. Returns count."""
       def get_market(self, canonical_id: str) -> MarketSpec | None
       def get_outcome(self, canonical_id: str) -> OutcomeSpec | None
       def search(self, query: str = "", venue: str | None = None,
                  category: str | None = None, lifecycle: MarketLifecycle | None = None) -> list[MarketSpec]
       def update_lifecycle(self, canonical_id: str, new_state: MarketLifecycle) -> None
       def snapshot(self) -> dict:
           """Point-in-time snapshot for reproducibility."""
       def persist(self, path: Path) -> None:
           """Save to Parquet for reloading."""
       def restore(self, path: Path) -> None:
           """Load from persisted Parquet."""
   ```

3. Implement `alpha_core/instruments/symbology.py`:
   - Cross-venue resolution: find "same underlying question" across exchanges
   - Canonical ID format: `{venue}:{market_id}:{outcome_id}`

4. Implement `alpha_core/instruments/lifecycle.py`:
   - State machine for market lifecycle transitions
   - Validation: only valid transitions allowed (ACTIVE → HALTED → RESOLVED, etc.)

**Tests Added:**
- `tests/unit/test_instruments.py`:
  - Create `MarketSpec` from sample data → validates
  - `MarketMaster.search()` filters correctly (by venue, category, lifecycle)
  - Lifecycle transitions: valid transitions succeed, invalid raise
  - Canonical ID format is consistent
  - Persist → restore round-trip preserves all fields
  - Snapshot returns deterministic output

**Codebase After F4:**
```diff
+ libs/core/alpha_core/instruments/{models, master, symbology, lifecycle}.py
+ tests/unit/test_instruments.py
+ tests/data/fixtures/sample_markets.json
```

**Status Update (February 28, 2026):**
- Added registry consistency hardening:
  - Re-registering a market now removes stale outcomes from the in-memory outcome index.
  - `get_market()`, `get_outcome()`, and `search()` now return defensive copies to prevent external mutation of registry state.
- Added model consistency hardening:
  - `MarketSpec` now enforces that each `OutcomeSpec.canonical_id` matches `{venue}:{market_id}:{outcome_id}`.
- Added regression tests for stale-outcome cleanup, defensive-copy behavior, and canonical-id mismatch rejection.

**Targets:**
| Metric | Target |
|---|---|
| Load 1,000 markets into master | < 500ms |
| Search / filter | < 10ms for 1,000-market registry |
| Persist + restore round-trip | 100% fidelity |
| Test count | 12–18 instrument tests |

---

### Step F5: pmxt Adapter Layer (Est. 12–20 hrs)

**Goal:** Abstract adapter interface + concrete `pmxt` implementation that maps vendor models to canonical models.

**Actions:**
1. Implement `alpha_core/adapters/base.py`:
   ```python
   class VenueAdapter(ABC):
       """Abstract interface for venue connectivity."""
       @abstractmethod
       async def fetch_markets(self) -> list[MarketSpec]: ...
       
       @abstractmethod
       async def fetch_trades(self, outcome_id: str, since: datetime | None = None,
                              limit: int = 100) -> list[CanonicalTrade]: ...
       
       @abstractmethod
       async def fetch_order_book(self, outcome_id: str) -> CanonicalBookSnapshot: ...
       
       @abstractmethod
       async def fetch_ohlcv(self, outcome_id: str, resolution: str = "1h",
                             limit: int = 100) -> list[CanonicalOHLCV]: ...
       
       @abstractmethod
       def venue_name(self) -> str: ...
   ```

2. Implement `alpha_core/adapters/pmxt_adapter.py`:
   ```python
   class PmxtAdapter(VenueAdapter):
       """Maps pmxt.Exchange to canonical models."""
       def __init__(self, exchange_name: str, config: VenueConfig):
           self._exchange = getattr(pmxt, config.exchange_class)(
               api_key=resolve_secret(config.api_key_env),
               private_key=resolve_secret(config.private_key_env),
           )
           self._venue = exchange_name
       
       async def fetch_markets(self) -> list[MarketSpec]:
           raw: list[pmxt.UnifiedMarket] = self._exchange.fetch_markets()
           return [self._map_market(m) for m in raw]
       
       def _map_market(self, raw: pmxt.UnifiedMarket) -> MarketSpec:
           """pmxt.UnifiedMarket → canonical MarketSpec"""
           ...
       
       def _map_trade(self, raw: pmxt.Trade, outcome_id: str) -> CanonicalTrade:
           """pmxt.Trade → canonical CanonicalTrade with bitemporal stamps"""
           ...
   ```

3. Implement `alpha_core/adapters/venue_configs.py`:
   - Per-venue normalization quirks (tick sizes, price scaling, side conventions)
   - Venue capability matrix (which methods each exchange supports)

**Tests Added:**
- `tests/unit/test_adapters.py`:
  - Mock `pmxt.Exchange` → adapter produces valid canonical models
  - All 7 venues mapped correctly (parametrized test)
  - Edge cases: empty markets list, missing fields, null prices
  - Timestamp mapping: venue timestamp → `ts_event`, `datetime.now(UTC)` → `ts_record`
- `tests/integration/test_adapter_mock.py`:
  - Full flow: mock exchange → adapter → canonical events → quality check → pass

**Codebase After F5:**
```diff
+ libs/core/alpha_core/adapters/{base, pmxt_adapter, venue_configs}.py
+ tests/unit/test_adapters.py
+ tests/integration/test_adapter_mock.py
+ tests/data/fixtures/{sample_trades.json, sample_orderbook.json}
```

**Targets:**
| Metric | Target |
|---|---|
| Map 100 markets | < 200ms |
| Map 1,000 trades | < 100ms |
| All venue adapters | Importable, instantiable (with mock keys) |
| Canonical output | 100% passes quality checker |
| Test count | 15–20 adapter tests |

---

### Step F6: Storage Layer & Local Docker (Est. 10–18 hrs)

**Goal:** Parquet write/read pipeline, DuckDB query layer, and local dev infrastructure.

**Actions:**
1. Implement `alpha_core/storage/conventions.py`:
   ```python
   class StorageTier(str, Enum):
       BRONZE = "bronze"    # Raw vendor payloads (JSON / bytes)
       SILVER = "silver"    # Canonical normalized events (Parquet)
       GOLD = "gold"        # Derived datasets (features, labels)
       
   PARTITION_SCHEME = {
       "silver_trades": ["venue", "date"],              # venue=kalshi/date=2026-02-28/
       "silver_books": ["venue", "date", "hour"],       # More granular for books
       "silver_ohlcv": ["venue", "resolution", "date"],
       "instrument_master": ["venue"],                  # Snapshot partitioned by venue
   }
   ```

2. Implement `alpha_core/storage/parquet_writer.py`:
   ```python
   class ParquetEventWriter:
       """Write canonical events to partitioned Parquet files."""
       def write_trades(self, trades: list[CanonicalTrade], tier: StorageTier = StorageTier.SILVER) -> Path
       def write_books(self, books: list[CanonicalBookSnapshot], ...) -> Path
       def write_ohlcv(self, candles: list[CanonicalOHLCV], ...) -> Path
   ```

3. Implement `alpha_core/storage/parquet_reader.py`:
   ```python
   class ParquetEventReader:
       """Read canonical events with partition pruning."""
       def read_trades(self, venue: str | None, start: datetime | None,
                       end: datetime | None) -> pa.Table
   ```

4. Implement `alpha_core/storage/duckdb_layer.py`:
   ```python
   class DuckDBAnalytics:
       """DuckDB wrapper for ad-hoc queries over Parquet data."""
       def __init__(self, storage_root: Path):
           self._con = duckdb.connect()
       def query(self, sql: str) -> pa.Table
       def register_silver(self, event_type: str) -> None:
           """Register Parquet partitions as a DuckDB view."""
   ```

5. Create `infra/docker/docker-compose.yml` — placeholder for Prometheus + Grafana (commented out for Foundation)

6. Create skeleton `apps/` entry points:
   - `apps/data_collector/main.py` — CLI stub with `click`
   - `apps/live_system/main.py` — CLI stub
   - `apps/research/main.py` — CLI stub

7. Create `data/schemas/canonical_event_v1.json` — JSON Schema for documentation

8. Create ADR docs:
   - `docs/adr/001-monorepo-structure.md`
   - `docs/adr/002-canonical-event-model.md`
   - `docs/adr/003-bitemporal-timestamps.md`

**Tests Added:**
- `tests/unit/test_storage.py`:
  - Write 100 trades → correct Parquet partitions created
  - Read with date filter → only relevant partitions scanned
  - Schema matches expected columns + types
  - Book snapshots partition by `venue/date/hour` as expected
  - OHLCV bars partition by `venue/resolution/date` as expected
- `tests/integration/test_storage_roundtrip.py`:
  - Generate canonical events → write Parquet → read via DuckDB → compare
  - Bitemporal fields survive the round-trip
  - Empty dataset handling (no crash)
  - `register_silver("books")` and `register_silver("ohlcv")` expose queryable views

**Codebase After F6:** Full foundation structure as shown in Section 4.

**Targets:**
| Metric | Target |
|---|---|
| Write 10K events to Parquet | < 2s |
| DuckDB query over 10K events | < 500ms |
| Parquet file size (10K trades) | < 500KB (compressed) |
| All 3 app entry points | Import + `--help` works |
| Test count | 10–15 storage tests |
| **Total Foundation tests** | **60–90 tests** |

---

## 6. Baseline Targets & Acceptance Criteria

### Quantitative Targets

| Category | Metric | Foundation Target |
|---|---|---|
| **Code quality** | ruff lint errors | 0 |
| | mypy strict errors | 0 |
| | Test coverage (libs/core/) | ≥ 85% |
| | All tests pass | 100% |
| **Performance** | Config load time | < 50ms |
| | Model instantiation (single event) | < 1ms |
| | Map 1,000 markets via adapter | < 1s |
| | Write 10K events to Parquet | < 2s |
| | DuckDB query 10K events | < 500ms |
| **Data integrity** | Serialization round-trip fidelity | 100% |
| | Bitemporal invariant enforcement | 100% |
| | Quality checker false-negative rate | 0% on known bad data |
| **Reliability** | CI pipeline pass rate | 100% on clean code |
| | Pre-commit hook pass rate | Blocks bad commits |

### Acceptance Criteria (Definition of Done)

The Foundation Stage is **complete** when all of the following are true:

- [x] `conda activate py311 && pip install -e ".[dev]"` succeeds
- [x] `ruff check . && mypy libs/ --strict` — 0 errors
- [x] `pytest tests/ -v` — all tests green, ≥ 85% coverage on `libs/core/`
- [x] All 7 `pmxt` venues have adapter stubs that map to canonical models
- [x] `MarketMaster` can load, search, persist, and restore market metadata
- [x] Parquet write → read → DuckDB query pipeline works end-to-end
- [x] Config system loads defaults + venue configs + env overrides
- [x] All 3 app entry points (`data_collector`, `live_system`, `research`) run `--help`
- [x] CI pipeline green on GitHub Actions
- [x] ADR docs explain key architectural decisions

---

## 7. Test Requirements

### Test Pyramid

```
          ┌──────────┐
          │  E2E /   │   (Future: Data Plane MVP)
          │  Smoke   │   0 tests in Foundation
          ├──────────┤
         │Integration│   8–12 tests
         │  (mocked  │   Full-flow with mocked pmxt
         │   pmxt)   │   Storage round-trips
         ├───────────┤
        │    Unit     │   50–75 tests
        │  (models,   │   Pure logic, no I/O
        │  adapters,  │   Fast (< 5s total)
        │  config)    │
        └─────────────┘
```

### Unit Test Requirements

| Module | Test File | Key Test Cases | Min Count |
|---|---|---|---|
| `config` | `test_config.py` | Load/merge/validate/override/secrets | 8 |
| `events` | `test_events.py` | Construct/serialize/validate/quality/ids | 15 |
| `instruments` | `test_instruments.py` | Create/search/lifecycle/persist/symbology | 12 |
| `adapters` | `test_adapters.py` | Map markets/trades/books per venue, edge cases | 15 |
| `storage` | `test_storage.py` | Write/read/partition/schema/empty-set | 10 |
| `utils` | `test_utils.py` | Time normalization, ID generation | 5 |

### Integration Test Requirements

| Test File | Scope | What It Validates |
|---|---|---|
| `test_adapter_mock.py` | Adapter → Models → Quality | Mock pmxt exchange returns data → adapter maps → canonical events → all pass quality checks |
| `test_storage_roundtrip.py` | Events → Parquet → DuckDB | Generate canonical events → write to Parquet → read back via ParquetReader + DuckDB → verify equality |

### Test Fixtures

All fixtures live in `tests/data/fixtures/` and represent realistic `pmxt` output:

| File | Content |
|---|---|
| `sample_markets.json` | 10 `UnifiedMarket` objects across 3 venues (Kalshi, Polymarket, Limitless) |
| `sample_trades.json` | 50 `Trade` objects with various prices/sides |
| `sample_orderbook.json` | 3 `OrderBook` snapshots with varying depth |
| `sample_ohlcv.json` | 24 `PriceCandle` objects (1h resolution, 1 day) |

### Test Conventions

- All tests use `pytest` with `parametrize` for venue-specific variations
- No network calls in CI — all `pmxt` interactions are mocked via `unittest.mock` or `pytest-mock`
- Temporary directories via `tmp_path` fixture for storage tests
- Strict type checking: tests import and use typed models (not raw dicts)

---

## 8. Codebase Evolution Roadmap

How each subsequent stage builds on the Foundation:

### Stage 2: Data Plane MVP (180–320 hrs)

```diff
  Foundation provides:
    ✓ Canonical event models
    ✓ pmxt adapter interface
    ✓ Storage conventions + Parquet writer
    ✓ Config system

  Data Plane MVP adds:
+ apps/data_collector/connectors/        # Live pmxt connectors (websocket + polling)
+   kalshi_connector.py                  # Kalshi-specific: watch_trades, watch_order_book
+   polymarket_connector.py              # Polymarket-specific
+   generic_pmxt_connector.py            # Fallback for other venues
+ apps/data_collector/normalisers/       # Venue → canonical pipeline workers
+ apps/data_collector/jobs/              # Scheduled backfill / replay tools
+ libs/core/alpha_core/quality/          # Great Expectations suites for silver data
+   suites/
+     trade_quality.py                   # Null checks, price bounds, monotonic ts
+     book_quality.py                    # Crossed books, stale detection
+ config/schedules/                      # Cron-like schedules for batch jobs
~ alpha_core/storage/parquet_writer.py   # Enhanced: streaming writes, rotation
~ alpha_core/adapters/pmxt_adapter.py    # Enhanced: streaming methods (watch_*)
```

**Key additions:** Live websocket connectors, scheduled ingestion, data quality suites, bronze tier storage.

### Stage 3: Research Plane MVP (220–420 hrs)

```diff
  Foundation + Data Plane provide:
    ✓ Stored silver-tier canonical events
    ✓ Quality-validated data pipeline
    ✓ Market master with historical snapshots

  Research Plane MVP adds:
+ apps/research/pipelines/
+   build_datasets/                      # Point-in-time dataset assembly (no look-ahead)
+     dataset_builder.py                 # Silver → Gold with as-of joins
+   build_features/                      # Feature engineering pipeline
+     pm_features.py                     # Prediction-market-specific features:
+                                        #   - Implied probability momentum
+                                        #   - Cross-venue spread
+                                        #   - Volume-weighted probability
+                                        #   - Time-to-resolution decay
+                                        #   - Category momentum
+   run_backtests/                       # Backtest execution pipeline
+ apps/research/backtester/
+   engine.py                            # Event-driven backtest engine
+   simulator.py                         # Execution simulator (fills, slippage)
+   vectorized.py                        # Fast-path vectorized backtester
+   accounting.py                        # PnL, fees, funding accounting
+   reports.py                           # Sharpe, drawdown, win rate, Brier score
+ libs/core/alpha_core/features/
~   primitives.py                        # Fleshed out: rolling, ewm, cross-sectional
+   pm_specific.py                       # Prediction market feature library
+ libs/core/alpha_core/portfolio/
~   models.py                            # Full position tracking, PnL attribution
```

**Key additions:** Dataset builder with look-ahead protection, event-driven backtester, PM-specific features (Brier score, implied probability signals), vectorized fast path.

### Stage 4: Live Plane MVP (220–420 hrs)

```diff
  Foundation + Data + Research provide:
    ✓ Validated strategies from backtesting
    ✓ Feature computation code (shared with research)
    ✓ Execution model abstractions

  Live Plane MVP adds:
+ apps/live_system/services/
+   marketdata_gateway/                  # Consumes live pmxt feeds
+   feature_service/                     # Real-time feature computation
+   signal_service/                      # Model inference + throttling
+   risk_service/                        # Pre-trade limits, kill-switch
+     limits.py                          # Max position, max loss, venue exposure
+   execution_gateway/                   # Order routing via pmxt.create_order
+     paper_trader.py                    # Paper trading adapter (no real money)
+     live_adapter.py                    # Real execution via pmxt (gated)
~ libs/core/alpha_core/execution/
~   models.py                            # Full: OrderIntent → Order → Fill → Report
+   risk_checks.py                       # Pre-trade validation
+   routing.py                           # Venue selection logic
```

**Key additions:** Paper trading, real-time feature → signal → execution pipeline, risk gates, position management.

### Stage 5: Observability Baseline (120–220 hrs)

```diff
+ apps/live_system/monitoring/
+   dashboards/                          # Grafana dashboard JSON
+     data_freshness.json
+     pnl_tracking.json
+     latency_metrics.json
+   alerts/                              # Alertmanager rules
+ infra/observability/
+   otel-collector-config.yaml
+   prometheus.yml
+   alertmanager.yml
~ libs/core/alpha_core/utils/logging.py  # OpenTelemetry integration
+ libs/core/alpha_core/telemetry/        # Tracing + metrics instrumentation
```

### Stage 6: Robustness Hardening (180–360 hrs)

```diff
+ libs/core/alpha_core/validation/
+   purged_cv.py                         # Purged/embargoed cross-validation
+   combinatorial_cv.py                  # Combinatorial purged CV
+   deflated_sharpe.py                   # Deflated Sharpe ratio (multiple testing)
+   survivorship.py                      # Time-varying universe enforcement
~ apps/research/backtester/engine.py     # Enforced bias controls (config flags)
+ apps/research/pipelines/train_models/  # MLflow experiment tracking
```

### Evolution Summary

```
F1 ─── F2 ─── F3 ─── F4 ─── F5 ─── F6    ← FOUNDATION (current implementation: F6, hardened as of 2026-02-28)
 │      │      │      │      │      │
 │      │      │      │      │      └──── Storage + Docker + App stubs
 │      │      │      │      └─────────── pmxt Adapter layer
 │      │      │      └────────────────── Instrument Master
 │      │      └───────────────────────── Canonical Data Models
 │      └──────────────────────────────── Config System
 └─────────────────────────────────────── Repo Scaffold + CI
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
   Data Plane   Research    Live Plane
     MVP        Plane MVP     MVP
        │           │           │
        └─────┬─────┘           │
              ▼                 │
        Observability           │
           Baseline             │
              │                 │
              └────────┬────────┘
                       ▼
                  Robustness
                  Hardening
                       │
                       ▼
                  Multi-Asset
                  Expansion
                       │
                       ▼
                  Production
                  Readiness
```

---

## 9. Dependencies & Environment

### Core Dependencies (Foundation)

```toml
[project]
name = "alpha-research-lab"
dynamic = ["version"]          # Version resolved from Git tags via setuptools_scm
requires-python = ">=3.11"
dependencies = [
    "pmxt>=2.18.0",           # Unified prediction market API
    "pydantic>=2.0",          # Data models + config validation
    "pydantic-settings>=2.0", # Settings management
    "pyarrow>=14.0",          # Parquet read/write
    "duckdb>=0.9",            # Local analytical queries
    "pyyaml>=6.0",            # Config file parsing
    "click>=8.0",             # CLI framework
    "structlog>=23.0",        # Structured logging
    "python-dotenv>=1.0",     # .env file loading
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-cov>=4.0",
    "pytest-mock>=3.10",
    "pytest-asyncio>=0.21",
    "ruff>=0.1",
    "mypy>=1.5",
    "pre-commit>=3.0",
    "types-PyYAML",
    "types-python-dateutil",
]
```

### Environment Setup

```bash
# One-time setup
conda activate py311
cd alpha-research-lab-private
pip install -e ".[dev]"
pre-commit install

# Verify
python scripts/validate_env.py
pytest tests/ -v --cov=libs/core/alpha_core
```

---

## 10. Conventions & Standards

### Code Standards

| Aspect | Convention |
|---|---|
| **Formatting** | `ruff format` (Black-compatible, 100 char line length) |
| **Linting** | `ruff check` with `select = ["E", "F", "I", "W", "UP", "RUF"]` |
| **Type checking** | `mypy --strict` on all `libs/` code |
| **Docstrings** | Google style, required on all public classes/methods |
| **Imports** | Absolute imports only within `alpha_core` |
| **Models** | Pydantic v2 `BaseModel` for all data structures |
| **Enums** | `str, Enum` for serialization compatibility |
| **Timestamps** | Always UTC `datetime` with tzinfo; never naive datetimes |
| **Decimals** | `Decimal` for all prices/sizes (not `float`) |
| **IDs** | Deterministic SHA256-based where possible |

### Git Conventions

| Aspect | Convention |
|---|---|
| **Branching** | `main` (protected) ← `feature/F{N}-{description}` |
| **Commits** | Conventional Commits: `feat:`, `fix:`, `test:`, `docs:`, `chore:` |
| **PRs** | One per Foundation sub-step (F1–F6) |
| **Tags** | `v0.1.0-foundation` on completion |

### Versioning & Release Tags

This repository uses **dynamic versioning** via `setuptools_scm`.

- **Single source of truth:** Git tags (no hard-coded `__version__` constants in code)
- **Tag format (stable releases):** `vMAJOR.MINOR.PATCH` (example: `v0.2.0`)
- **Optional milestone tags:** `v0.1.0-foundation` for stage markers
- **Local/dev builds:** version auto-derived from nearest tag + commit distance/hash metadata
- **Runtime metadata:** `alpha_core.__version__` is read from package metadata; `alpha_core.__commit_hash__` is populated when local version metadata includes a Git hash

Recommended release flow:

1. Ensure `main` is green (lint, type-check, tests)
2. Create annotated tag: `git tag -a vX.Y.Z -m "Release vX.Y.Z"`
3. Push tag: `git push origin vX.Y.Z`
4. Let CI build/publish artifacts from the tag

### Architecture Decision Records

All significant decisions are recorded in `docs/adr/` following the format:
- **Status:** Proposed / Accepted / Deprecated
- **Context:** Why the decision is needed
- **Decision:** What was decided
- **Consequences:** Trade-offs and implications

---

## 11. Microstructure Foundation Extension (Completed Addendum)

Foundation is complete; this completed addendum delivers foundational upgrades needed for queue/OFI/Hawkes research quality.

Delivered additional effort: ~20-40 hours.

### 11.1 F3 Extension: Canonical Event Model Enhancements

Add optional event metadata fields that improve microstructure reconstruction:

- `sequence_id: str | None`
- `ts_exchange: datetime | None`
- `ts_receive: datetime | None`
- `source_latency_ms: float | None`

Add optional event type for delta semantics when available:

- `BOOK_DELTA`

Proposed model (if supported by venue payloads):

```python
class CanonicalBookDelta(CanonicalMarketEvent):
    event_type: Literal[EventType.BOOK_DELTA] = EventType.BOOK_DELTA
    side: Literal["bid", "ask"]
    price: Decimal
    delta_size: Decimal
    reason: Literal["add", "cancel", "trade"]
    sequence_id: str | None = None
```

### 11.2 F4 Extension: Outcome Grouping for Simplex Constraints

For cross-contract arbitrage (`sum_i p_i = 1`) ensure instrument metadata can identify outcome sets cleanly.

Add optional grouping field:

- `outcome_group_id: str | None` on `MarketSpec` or derived mapping in symbology

This enables fast retrieval of all mutually exclusive outcomes for one event.

### 11.3 F6 Extension: Storage Conventions for Delta Data

Add optional storage and schema conventions:

- dataset name: `book_deltas`
- partitioning: `venue/date/hour`
- schema includes `reason`, `delta_size`, `sequence_id`, `is_reconstructed`

Expose through:

- `storage/conventions.py`
- `parquet_writer.py` and `parquet_reader.py`
- `duckdb_layer.py` registration map

### 11.4 Foundation Addendum Tests

Add or extend tests:

- `tests/unit/test_events.py`: optional metadata serialization, `BOOK_DELTA` model validation
- `tests/unit/test_storage.py`: `book_deltas` partition/schema round-trip
- `tests/integration/test_storage_roundtrip.py`: delta dataset query via DuckDB

### 11.5 Addendum Completion Criteria

- [x] Canonical models can represent sequence-aware and latency-aware market events.
- [x] Outcome grouping is available for simplex-constrained basket logic.
- [x] Storage conventions and readers support optional `book_deltas`.
- [x] New foundation addendum tests pass without regressing baseline foundation guarantees.

---

## 12. Lean Adoption Foundation Extension (March 2026)

Foundation remains complete and closed. This extension does not reopen F1-F6; it adds cross-stage contracts needed for Lean-style research-to-production continuity.

Reference documents:
- `README.LEAN_ADOPTION.md`
- `docs/implementation/lean-adoption-issue-backlog.md` (primarily LA-001, LA-002, LA-003, LA-014)

### 12.1 Cross-Stage Run Contracts

Define minimal shared contracts in core so downstream stages stop inventing per-stage metadata formats:

- `RunContext` (run identity, type, timing, config hash, git commit/fallback)
- `RunManifest` (links run context to stage outputs and parent lineage IDs)

Recommended field minimum:

```python
class RunContext(BaseModel):
    run_id: str
    run_type: Literal["ingestion", "dataset_build", "feature_build", "backtest", "evaluate", "optimize", "live"]
    config_hash: str
    git_commit: str | None
    started_at_utc: datetime
    completed_at_utc: datetime | None

class RunManifest(BaseModel):
    run: RunContext
    artifacts: dict[str, str]
    parent_run_id: str | None = None
```

**Status Update (March 4, 2026):**

- `RunType` exported as a named `Literal` type alias covering all seven pipeline stages; used as the single source of truth across modules.
- `RunContext.run_type` broadened from `"dataset_build"`-only to the full `RunType` union.
- `capture_git_commit()` added to `run_context.py` — wraps `git rev-parse --short HEAD` with a safe `None` fallback when outside a repo or when `git` is absent.
- `make_run_context()` auto-calls `capture_git_commit()` when no commit is passed explicitly.
- `RunManifest` aligned to the spec-minimal contract: the `dataset_id` top-level field was removed; stage-specific keys (dataset ID, feature-set version, etc.) are stored as entries in `artifacts` instead.
- `DatasetBuilder` updated to write `dataset_id` into `artifact_map` rather than a top-level manifest field — backward-compatible for downstream consumers.
- `alpha_core.research.__init__` now exports module namespaces only (`artifact_paths`, `manifest`, `run_context`, etc.) to avoid flat-symbol re-export indirection.
- `tests/unit/test_research_manifest.py` replaced and expanded: 23 tests covering parametrized `RunType` coverage, hash stability, `close_run_context`, `capture_git_commit` (happy path, `FileNotFoundError`, mock injection, explicit-override guard), manifest round-trip, `parent_run_id` linkage, `extra="forbid"` rejection, and per-`RunType` persistence. All 614 tests green; `mypy --strict` clean on changed files.

### 12.2 Artifact Path Conventions

Define a canonical run-output layout once at Foundation level:

```text
data/runs/{run_id}/
  manifest.json
  config.json
  artifacts.json
  stage_outputs/
```

Rules:
- Artifact paths must be deterministic for identical `(run_id, artifact_key)`.
- Logical artifact key -> path mapping must be stored in `artifacts.json`.
- Stage-specific outputs (dataset/features/backtests/reports) may keep existing layouts, but run manifests must point to them.

**Status Update (March 4, 2026):**

- `artifact_paths.py` fully expanded with the complete canonical layout contract:
  - `run_root`, `run_manifest_path`, `run_config_path`, `run_artifacts_path` — existing fixed-file helpers (unchanged, backward-compatible).
  - `stage_outputs_path` — new helper for the `stage_outputs/` subdirectory.
  - `artifact_key_path(storage_root, run_id, artifact_key)` — the single source of truth for a deterministic per-artifact path under `stage_outputs/`; validates the key (non-empty, relative, no `..` traversal).
  - `write_artifacts_index` / `read_artifacts_index` — atomic write and safe read of `artifacts.json`; `read_artifacts_index` returns `{}` when the file is absent for backward-compatible consumption.
- `IngestionRun` in `storage/lineage.py` gains an optional `downstream_run_ids: list[str]` field (default `[]`) — fully backward-compatible with existing JSON on disk.
- `LineageStore.link_downstream_run(ingestion_run_id, downstream_run_id)` — idempotent method to register bidirectional traceability between an ingestion run and a consuming research run. Pairs with `RunManifest.parent_run_id` on the downstream side.
- Helpers remain available via module namespaces (for example `alpha_core.research.artifact_paths.*`) instead of flat re-exports.
- `docs/guides/notebook-to-modules-cli-migration-guide.md` updated with §9.1 Run Artifact Layout Convention: documents the directory structure, helper usage patterns, and the `link_downstream_run` bridging flow.
- New `tests/unit/test_artifact_paths.py`: 25 tests covering fixed-path layout, `artifact_key_path` determinism and validation, `write/read_artifacts_index` round-trip and edge cases, lineage bridge CRUD (default, register, idempotency, accumulation, error case), and backward-compat loading of old JSON without `downstream_run_ids`. All 644 tests green; `mypy --strict` clean.

### 12.3 Strategy Framework Contract Stubs

Add shared protocol stubs in core (implementation deferred to Research/Live stages):

- `UniverseModel`
- `AlphaModel`
- `PortfolioConstructionModel`
- `RiskModel`
- `ExecutionModel`

These are contract-only at Foundation extension scope and are intended to prevent interface drift between research and live engines.

**Status Update (March 4, 2026):**

- `libs/core/alpha_core/strategy_framework/` package introduced with four modules:
  - `interfaces.py` — five `typing.Protocol` stubs (`UniverseModel`, `AlphaModel`, `PortfolioConstructionModel`, `RiskModel`, `ExecutionModel`) all decorated `@runtime_checkable`, matching the contracts specified in `README.LEAN_ADOPTION.md §6.1`.
  - `models.py` — typed Pydantic v2 datamodels covering the full pipeline data flow: `InstrumentState`, `MarketState` (entry point, `extra="allow"` for runtime extensibility), `Signal` (with `SignalDirection` enum and bounded `strength`/`confidence` fields), `Target` (weighted or absolute sizing), `OrderIntent` (with `OrderType` enum and PM price bounds).
  - `engine.py` — `StrategyEngine` dataclass wiring all five protocols into a single `step(state) -> list[OrderIntent]` cycle with a `cycle_count` counter; no order submission logic (deferred to Research/Live stages).
  - `__init__.py` — module-namespace exports (`engine`, `interfaces`, `models`) so callers import symbols from explicit modules.
- `alpha_core/__init__.py` `__all__` updated to document `strategy_framework` as a top-level sub-package alongside `research`.
- `tests/unit/test_strategy_framework.py` added: 33 tests covering protocol conformance (`isinstance` checks), model validation and field-bound rejection, serialization round-trips for `Signal` and `OrderIntent`, parametrized `SignalDirection` coverage, and `StrategyEngine` orchestration (universe filtering, risk dropping, cycle counting, empty universe). All 677 tests green; `mypy --strict` clean on `libs/core/alpha_core/strategy_framework`.

### 12.4 Schema Regression Policy

Introduce contract stability gates for manifests and reports:

- Add regression test fixtures for run manifest schema.
- Any schema change requires:
  1. schema version bump
  2. migration note in docs
  3. updated regression snapshots

This policy should be enforced in CI once Research CLI is wired.

**Status Update (March 4, 2026):**

- `RUN_MANIFEST_SCHEMA_VERSION: int = 1` constant added to `manifest.py` as the single source of truth; must be bumped whenever any `RunManifest` field changes.
- `schema_version: int = Field(default=RUN_MANIFEST_SCHEMA_VERSION)` added to `RunManifest` — backward-compatible (existing code constructing the model without this field gets the default; existing JSON without the field parses cleanly via the default too). `RUN_MANIFEST_SCHEMA_VERSION` is exported by `alpha_core.research.manifest`.
- Regression snapshot fixtures created:
  - `tests/data/fixtures/schema_snapshots/run_manifest_v1.json` — frozen canonical JSON for `RunManifest` v1 (all 4 top-level fields).
  - `tests/data/fixtures/schema_snapshots/run_context_v1.json` — frozen canonical JSON for the embedded `RunContext` (all 6 fields).
- JSON Schema document `data/schemas/run_manifest_v1.json` added (draft/2020-12), defining the full structure of `RunManifest` v1 with `schema_version` constrained to `1`, `run_type` as an enum, and `additionalProperties: false` for both the top-level object and the nested `run_context` definition.
- `tests/unit/test_schema_regression.py` added: 19 tests across four test classes:
  - `TestRunManifestRegression` — snapshot existence, parse, field-set equality, constant/fixture agreement, round-trip stability, run_type validity, non-empty artifacts.
  - `TestRunContextRegression` — parse, field-set equality, round-trip stability against the separate `RunContext` fixture.
  - `TestRunManifestJsonSchema` — JSON Schema file existence, valid JSON, `const` matches constant, required-field agreement.
  - `TestSchemaRegressionGuards` — self-tests proving the gates fire: extra field rejection, missing required field rejection, invalid run_type rejection, simulated field-drift detection.
- Snapshot update instructions are inlined at the top of `test_schema_regression.py` as a copy-pasteable shell snippet.
- All 696 tests green; `mypy --strict` clean on changed files.

### 12.5 Foundation Extension Acceptance Gates

Extension is complete when:

- [x] Shared run contract models exist in core and are importable by both data and research modules.
- [x] Canonical run artifact path helpers exist and are covered by unit tests.
- [x] Strategy framework protocol stubs are committed in core.
- [x] Manifest schema regression policy is documented and test scaffolding exists.

---

## 13. Lean + QUANTAXIS Foundation Extension (March 2026, Iteration 2)

Foundation remains complete. This iteration adds protocol and operability guardrails so later stages can scale research development without redesigning core boundaries.

Reference documents:
- `README.LEAN_ADOPTION.md`
- `docs/implementation/research-plane-mvp.md`

### 13.1 Provider-Agnostic Runtime Protocols

Add protocol stubs for account/routing surfaces in core:

- `AccountStateProvider` (positions, balances, buying power)
- `MarketStateProvider` (instrument status, top-of-book, lifecycle state)
- `OrderRouter` (submit/cancel/query lifecycle)
- `ExecutionAcknowledger` (acks/rejects/fills)

These are contract-only in foundation scope and should not replace existing adapter implementations yet.

### 13.2 Optional Performance Boundary Contract

Define explicit interfaces for compute-heavy paths (feature transforms, simulation kernels):

- baseline implementation: pure Python
- optional accelerated implementation: same signature and outputs
- parity test rule: accelerated path must match baseline within documented tolerance

This avoids API churn when performance work starts later.

### 13.3 Environment Profile Contract

Standardize named runtime profiles:

- `dev`
- `research`
- `ci`
- `paper`
- `live`

Each profile should define:
- storage roots
- logging verbosity
- safety flags (for example execution disabled in `research`)
- retention policy defaults

### 13.4 Documentation Modularity Rule

Adopt a strict documentation split:

- architecture contracts in implementation docs
- operator procedures in runbooks
- migration mappings in guides
- breaking changes in ADRs

Goal:
- avoid one large document becoming the only source of truth.

### 13.5 Iteration 2 Acceptance Gates

Extension is complete when:

- [ ] Runtime protocol stubs for account/market/router boundaries are present in core.
- [ ] Performance boundary interfaces and parity-test policy are documented.
- [ ] Profile contract (`dev/research/ci/paper/live`) is specified with required keys.
- [ ] Documentation modularity rule is applied to new stage-level updates.

---

## Appendix: pmxt Exchange Capability Matrix

| Exchange | `fetch_markets` | `fetch_trades` | `fetch_ohlcv` | `fetch_order_book` | `create_order` | `watch_*` (streaming) |
|---|---|---|---|---|---|---|
| **Kalshi** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **KalshiDemo** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Polymarket** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Limitless** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Baozi** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Myriad** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Probable** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

> **Note:** All `pmxt` exchanges implement a unified interface. Actual data availability varies per venue — adapter layer handles graceful degradation when a venue returns empty results or errors.
