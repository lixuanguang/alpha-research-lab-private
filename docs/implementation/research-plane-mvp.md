# Alpha Research Lab — Research Plane MVP Implementation Plan

> **Stage:** 3 of 8 · Entrypoint C: Research & Backtesting  
> **Prerequisites:** Foundation (complete, with all validated baseline work folded into the implementation steps) + Data Plane MVP (complete — 891 passed, 10 skipped; quality gates green)
> **Focus:** Point-in-time dataset assembly, prediction-market feature engineering, event-driven + vectorized backtesting, PM-specific evaluation metrics  
> **Estimated Effort:** 220–420 hours (single engineer)  
> **Environment:** Python 3.11 (conda `py311`)  
> **Lean adoption alignment (March 2, 2026):** This plan incorporates the architecture deltas in `README.LEAN_ADOPTION.md` and issue tracking in `docs/implementation/lean-adoption-issue-backlog.md`.

---

## Table of Contents

1. [Overview & Objectives](#1-overview--objectives)
2. [Foundation & Data Plane Baseline — What We Start With](#2-foundation--data-plane-baseline--what-we-start-with)
3. [Research Plane MVP Scope](#3-research-plane-mvp-scope)
4. [Architecture — Research Pipeline](#4-architecture--research-pipeline)
5. [Implementation Steps](#5-implementation-steps)
6. [Baseline Targets & Acceptance Criteria](#6-baseline-targets--acceptance-criteria)
7. [Test Requirements](#7-test-requirements)
8. [Codebase Evolution — File-by-File](#8-codebase-evolution--file-by-file)
9. [Dependencies & New Packages](#9-dependencies--new-packages)
10. [Operational Runbook Stubs](#10-operational-runbook-stubs)
11. [Future Microstructure Extension (Tick-Resolution)](#11-future-microstructure-extension-tick-resolution)
12. [Future Research Ergonomics Extension (March 2026, Iteration 2)](#12-future-research-ergonomics-extension-march-2026-iteration-2)

---

## 1. Overview & Objectives

The Research Plane MVP delivers the **analytical backbone** — the tooling that turns collected prediction market data into testable, reproducible trading strategies:

1. **Assembles datasets** from silver-tier Parquet into gold-tier research datasets with strict point-in-time discipline (no look-ahead bias)
2. **Engineers features** from canonical market data — both generic time-series features and prediction-market-specific signals (implied probability momentum, cross-venue spread, time-to-resolution decay)
3. **Backtests strategies** using both an event-driven engine (high fidelity, tick-by-tick) and a vectorized fast path (rapid iteration, cross-sectional)
4. **Simulates execution** with realistic fills, slippage, fees, and prediction market microstructure (binary payoffs, resolution events)
5. **Evaluates performance** with standard financial metrics (Sharpe, drawdown, win rate) plus PM-specific metrics (Brier score, calibration curves, log-loss, resolution PnL decomposition)
6. **Enforces reproducibility** — every backtest is deterministic, version-tagged, and can be replayed from the same dataset snapshot

### Alignment with Reference Framework

The PDF framework specifies the research plane must deliver:

> *"Silver → Gold transforms, as-of dataset assembly, feature pipelines, event-driven backtester, vectorized fast path, execution simulator, PnL/risk analytics, and walk-forward/purged-CV harness (deferred to Robustness stage)."*

Prediction market specifics add:

- Binary/multi-outcome resolution events as a first-class data type
- Probability-space features and signals (not just price returns)
- Brier score, log-loss, and calibration as primary evaluation metrics alongside Sharpe
- Market lifecycle awareness: strategies must handle resolution, delisting, and halt events
- Time-to-resolution decay as a structural alpha driver

---

## 2. Foundation & Data Plane Baseline — What We Start With

### From Foundation (complete)

| Component | Module | What It Provides |
|---|---|---|
| Canonical events | `alpha_core.events.models` | `CanonicalTrade`, `CanonicalBookSnapshot`, `CanonicalOHLCV`, `CanonicalMetadataUpdate` with bitemporal timestamps |
| Instrument master | `alpha_core.instruments.master` | `MarketMaster` with lifecycle tracking, Parquet persistence, search |
| Symbology | `alpha_core.instruments.symbology` | Cross-venue market grouping via `find_cross_venue_groups` |
| Storage schemas | `alpha_core.storage.conventions` | `TRADE_PARQUET_SCHEMA`, `BOOK_PARQUET_SCHEMA`, `OHLCV_PARQUET_SCHEMA` |
| DuckDB layer | `alpha_core.storage.duckdb_layer` | `DuckDBAnalytics` for SQL queries over silver Parquet |
| Config system | `alpha_core.config` | Hierarchical YAML + env, `Settings` with `VenueConfig` |
| Event quality | `alpha_core.events.quality` | `EventQualityChecker` for per-event validation |
| Utils | `alpha_core.utils` | `ensure_utc`, `generate_event_id`, `stable_payload_json` |

### From Data Plane MVP (complete)

| Component | Module | What It Provides |
|---|---|---|
| Silver trades/books/OHLCV | `alpha_core.storage.parquet_writer/reader` | Full read/write for all three data types, Hive-partitioned |
| Bronze storage | `alpha_core.storage.bronze_writer` | Raw JSON payload preservation with run_id |
| Streaming writer | `alpha_core.storage.streaming_writer` | Buffered Parquet writes with time/size rotation |
| Quality suites | `alpha_core.quality.suites` | `TRADE_SUITE`, `BOOK_SUITE`, `OHLCV_SUITE` — batch validation on silver partitions |
| Gap detector | `alpha_core.quality.gap_detector` | `GapDetector` — identifies missing time windows in silver data |
| Lineage tracking | `alpha_core.storage.lineage` | `LineageStore` — every ingestion run logged with counts/errors |
| Polling connectors | `apps.data_collector.connectors` | `TradePoller`, `OHLCVPoller`, `BookSnapshotPoller`, `MarketRefreshPoller` |
| Streaming connectors | `apps.data_collector.connectors` | `TradeStreamConnector`, `BookStreamConnector` with reconnection |
| Backfill manager | `apps.data_collector.backfill` | Historical window replay for trades and OHLCV |
| Full CLI | `apps.data_collector.main` | `run`, `backfill`, `validate`, `status`, `detect-gaps` |
| Pipeline orchestration | `apps.data_collector.runtime` | `run_polling_pipelines`, `run_streaming_pipelines`, polling scheduler |

### What the Research Plane Builds On

The critical data flow is:

```
Silver Parquet (trades/books/OHLCV)  ──╮
Market Master (lifecycle snapshots)    ──┤──→  Dataset Builder ──→ Gold Dataset ──→ Feature Engine ──→ Backtester
Quality Suite Reports (pass/fail)      ──┤
Gap Detector (completeness check)      ──╯
```

### Gaps to Address in Research Plane

| Gap | Where Resolved |
|---|---|
| No gold-tier storage | Dataset builder writes gold Parquet (Step R1) |
| No point-in-time joins | As-of join logic prevents look-ahead (Step R1) |
| No feature computation | Feature primitives + PM-specific library (Step R2) |
| No portfolio/position models | Portfolio module in core (Step R3) |
| No backtest engine | Event-driven + vectorized engines (Steps R3–R4) |
| No execution simulation | Fill simulator with PM microstructure (Step R3) |
| No evaluation metrics | Standard + PM-specific metric suite (Step R5) |
| Research CLI exists only as scaffold plumbing | Expand `apps/research/main.py` into the full R6 operator surface with concrete pipeline execution |

---

## 3. Research Plane MVP Scope

### In Scope

| Deliverable | Description |
|---|---|
| **Dataset builder** | Silver → gold assembly with bitemporal as-of joins, universe snapshots, and look-ahead bias protection |
| **Universe manager** | Point-in-time market universe definitions: which markets are tradeable at each timestamp, respecting lifecycle and data quality |
| **Feature primitives** | Generic time-series transforms: rolling, EWM, z-score, rank, lag, diff, cross-sectional normalisation |
| **PM-specific features** | Implied probability momentum, cross-venue spread, volume-weighted probability, time-to-resolution decay, category momentum, book imbalance |
| **Feature registry** | Declarative feature definitions, dependency resolution, caching, versioned computation |
| **Event-driven backtester** | Tick-by-tick simulation: events fed in timestamp order, strategy receives current state, emits order intents |
| **Vectorized backtester** | Fast-path: operate on aligned DataFrames/arrays, cross-sectional, suitable for parameter sweeps |
| **Execution simulator** | Realistic fills: market vs. limit, queue priority, slippage model, fee schedules, PM-specific binary payoff handling |
| **Portfolio tracker** | Position state, cash balance, PnL breakdown (realised/unrealised), per-market attribution, resolution PnL |
| **Evaluation metrics** | Sharpe, Sortino, max drawdown, win rate, profit factor + Brier score, log-loss, calibration error, resolution decomposition |
| **Report generation** | Structured JSON/Parquet backtest reports, summary statistics, equity curve data |
| **Research CLI** | `apps/research/main.py` with: `build-dataset`, `build-features`, `backtest`, `evaluate`, `report`, `optimize` |
| **Strategy framework contracts** | Shared `UniverseModel`, `AlphaModel`, `PortfolioConstructionModel`, `RiskModel`, `ExecutionModel` contracts to keep backtest/live logic consistent |
| **Run context + manifests** | Standard run metadata (`run_id`, `dataset_id`, `feature_set_version`, `strategy_version`, `config_hash`, `git_commit`) persisted for every stage |
| **Artifact store abstraction** | Local filesystem-backed artifact interface so dataset/features/backtests/evaluations use one persistence contract |
| **Optimization workflow** | First-class `optimize` workflow (grid/random sweep with constraints and leaderboard artifacts) |

### Explicitly Out of Scope

- Live/paper trading execution (→ Live Plane MVP)
- Model training / AutoML / hyperparameter search (→ Robustness Hardening)
- Purged/embargoed cross-validation (→ Robustness Hardening)
- Deflated Sharpe ratio / multiple testing correction (→ Robustness Hardening)
- Grafana dashboards / alerting (→ Observability Baseline)
- Advanced walk-forward optimisation and Bayesian/hyperband optimizers (→ Robustness Hardening)
- Feature store / online feature serving (→ Live Plane MVP)

### Embedded Cross-Stage Contracts (March 2026)

To keep this document as the implementation source of truth, the remaining Lean-derived contracts are embedded directly in R1-R6 rather than tracked as a separate refactor pass:

- **R1:** add run context and run manifest contracts while implementing dataset builder.
- **R2:** integrate feature outputs with run/artifact metadata.
- **R3:** align event backtester strategy interfaces with framework contracts.
- **R4:** add first-class optimize runner outputs and trial registry.
- **R5:** add report schema/version regression guardrails.
- **R6:** include `optimize` command and machine-readable CLI output conventions.

Tracking reference:
- `README.LEAN_ADOPTION.md`
- `docs/implementation/lean-adoption-issue-backlog.md`

---

## 4. Architecture — Research Pipeline

### High-Level Data Flow

```
┌──────────────────────────────────────────────────┐
│                Silver Tier (Parquet)              │
│  trades/  books/  ohlcv/  market_master.parquet  │
└──────┬────────┬──────┬──────────┬────────────────┘
       │        │      │          │
┌──────▼────────▼──────▼──────────▼────────────────┐
│              Dataset Builder (R1)                 │
│  • Point-in-time universe snapshot               │
│  • As-of join (no look-ahead)                    │
│  • Quality gate: only validated partitions        │
│  • Gap check: reject incomplete windows           │
│  • Output: gold-tier aligned datasets             │
└──────────────────────┬───────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────┐
│              Feature Engine (R2)                  │
│  • Primitives: rolling, ewm, rank, zscore, lag   │
│  • PM-specific: prob momentum, cross-venue        │
│  •   spread, TTR decay, vol-weighted prob,        │
│  •   book imbalance, category momentum            │
│  • Registry: declarative, cached, versioned       │
│  • Output: feature matrix (gold Parquet)          │
└──────────────────────┬───────────────────────────┘
                       │
       ┌───────────────┼───────────────┐
       │               │               │
┌──────▼──────┐ ┌──────▼──────┐ ┌──────▼──────────┐
│ Event-Driven│ │ Vectorized  │ │  Parameter       │
│ Backtester  │ │ Backtester  │ │  Sweep Runner    │
│ (R3)        │ │ (R4)        │ │  (R4)            │
│             │ │             │ │                   │
│ High fidel- │ │ Fast cross- │ │ Parallel grid /  │
│ ity, tick-  │ │ sectional,  │ │ random search    │
│ by-tick     │ │ DataFrame   │ │ over strategies  │
└──────┬──────┘ └──────┬──────┘ └──────┬───────────┘
       │               │               │
       └───────────────┼───────────────┘
                       │
┌──────────────────────▼───────────────────────────┐
│           Evaluation & Reporting (R5)             │
│  • Financial: Sharpe, Sortino, drawdown, PF      │
│  • PM-specific: Brier, log-loss, calibration     │
│  • Resolution decomposition, category breakdown   │
│  • Equity curve, monthly/weekly PnL tables        │
│  • Structured JSON + Parquet reports              │
└──────────────────────────────────────────────────┘
```

### Lean Adoption Overlay (Architecture)

The R1-R6 flow above is extended with cross-cutting contracts:

```text
RunContext + RunManifest (cross-cutting metadata)
  -> Dataset build
  -> Feature build
  -> Backtest / Evaluate
  -> Optimize
  -> Report

ArtifactStore (filesystem backend in MVP)
  -> canonical write/read interface for all stage artifacts

Strategy Framework Contracts
  -> shared interfaces used by event engine first
  -> reused by live-plane runtime later without strategy rewrites
```

### Dataset Builder — Point-in-Time Discipline

The dataset builder is the most critical component for research integrity. It prevents look-ahead bias at every layer:

```
Time ──────────────────────────────────────────────────────►

Event stream:   T₁   T₂   T₃ ... Tₙ     (silver trades, ordered by ts_event)
Market master:  M₁   M₂   M₃             (lifecycle snapshots, ordered by last_updated)
                │     │     │
As-of join:     At time t, the dataset builder:
                ├─ Uses only events with ts_event ≤ t
                ├─ Uses only market metadata with last_updated ≤ t
                ├─ Feature computation uses only data available at t
                └─ Universe includes only markets with lifecycle == ACTIVE at t

Gold output:    Aligned panels: [timestamp × instrument × feature_columns]
                Each row is strictly computable from information available at that timestamp.
```

### Feature Computation Model

```
Feature Registry
├── PrimitiveFeature
│   ├── RollingMean(window=20)
│   ├── EWM(span=10)
│   ├── ZScore(window=50)
│   ├── Rank(method="cross_sectional")
│   ├── Lag(periods=1)
│   └── Diff(periods=1)
├── PMFeature (prediction-market-specific)
│   ├── ImpliedProbMomentum(window=20)
│   ├── CrossVenueSpread()
│   ├── VolumeWeightedProb(window=50)
│   ├── TimeToResolutionDecay()
│   ├── CategoryMomentum(window=10)
│   ├── BookImbalance()
│   └── ProbAcceleration(fast=5, slow=20)
└── CompositeFeature (combinators)
    ├── FeatureInteraction(f1, f2, op="multiply")
    └── FeatureRatio(numerator, denominator)
```

### Backtester Architecture

Two engines, shared contracts:

```
                    ┌─────────────────┐
                    │   Strategy      │
                    │   (ABC)         │
                    │                 │
                    │ on_data(state)  │
                    │  → OrderIntent[]│
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼                             ▼
    ┌─────────────────┐          ┌─────────────────┐
    │  EventEngine    │          │  VecEngine      │
    │  (tick-by-tick) │          │  (DataFrame)    │
    │                 │          │                 │
    │  SimClock       │          │  Aligned panels │
    │  OrderBook sim  │          │  NumPy/Polars   │
    │  Fill model     │          │  Batch fills    │
    │  Per-event loop │          │  Vectorised PnL │
    └────────┬────────┘          └────────┬────────┘
             │                            │
             ▼                            ▼
    ┌─────────────────────────────────────────────┐
    │          Portfolio Tracker (shared)           │
    │  Positions, cash, PnL, fees, resolution PnL │
    └─────────────────────┬───────────────────────┘
                          ▼
    ┌─────────────────────────────────────────────┐
    │          Evaluator + Report Generator         │
    └─────────────────────────────────────────────┘
```

### Storage Layout After Research Plane

```
data/
├── bronze/     ... (unchanged from Data Plane)
├── silver/     ... (unchanged from Data Plane)
├── gold/
│   ├── datasets/
│   │   └── {dataset_name}/
│   │       ├── _meta.json              # Dataset metadata: params, date range, universe, schema version
│   │       ├── trades.parquet
│   │       ├── books.parquet
│   │       ├── ohlcv.parquet
│   │       └── universe.parquet        # Point-in-time universe membership
│   └── features/
│       └── {feature_set_name}/
│           ├── _meta.json              # Feature definitions, computation params
│           └── features.parquet        # [timestamp × instrument × feature_columns]
├── runs/
│   └── {run_id}/
│       ├── manifest.json               # RunContext + stage metadata
│       ├── config.json                 # Frozen config for reproducibility
│       ├── artifacts.json              # Logical -> physical artifact mapping
│       └── stage_outputs/              # Dataset/feature/backtest/eval/optimize outputs
├── backtests/
│   └── {backtest_id}/
│       ├── config.json                 # Strategy + engine + params frozen
│       ├── trades.parquet              # Simulated fills
│       ├── positions.parquet           # Position time series
│       ├── equity.parquet              # Equity curve
│       ├── metrics.json                # Summary metrics (Sharpe, Brier, etc.)
│       └── report.json                 # Full structured report
└── _lineage/   ... (unchanged from Data Plane ingestion; may link parent run IDs)
```

---

## 5. Implementation Steps

The Research Plane MVP is broken into **6 sequential sub-steps** (R1–R6). Each step produces a testable, runnable increment.
Lean-adoption tasks are embedded in each step so no second refactor pass is required.

If you are currently implementing **R1**, prioritize the R1 contract items below first; they are intentionally low-disruption and unblock R2-R6 reproducibility.

---

### Step R1: Dataset Builder & Universe Manager (Est. 35–55 hrs)

**Goal:** Assemble silver-tier data into gold-tier research datasets with strict point-in-time discipline and look-ahead bias protection.

**Embedded cross-stage contract work for this step (LA-001/LA-002/LA-003):**

- Add `RunContext`/`RunManifest` contracts immediately, even if initially minimal.
- Persist R1 outputs under canonical run paths (`data/runs/{run_id}/...`) with artifact pointers.
- Keep `DatasetManifest` as dataset-specific metadata, but always link it from a run manifest.
- Define strategy-framework interfaces now (protocols only is sufficient in R1) so R3 can plug into stable contracts without churn.

**Actions:**

1. **Implement `UniverseManager`** in `libs/core/alpha_core/research/`:
   ```python
   class UniverseSnapshot(BaseModel):
       """Point-in-time snapshot of tradeable instruments."""
       as_of: datetime
       instruments: list[str]           # Canonical outcome IDs
       markets: list[str]               # Canonical market IDs
       venue_breakdown: dict[str, int]  # Count per venue
       filters_applied: dict[str, Any]  # Lifecycle, volume, quality

   class UniverseManager:
       """Builds point-in-time universes from MarketMaster snapshots."""
       def __init__(self, master: MarketMaster, *,
                    lifecycle_filter: list[MarketLifecycle] = [MarketLifecycle.ACTIVE],
                    min_volume: Decimal | None = None,
                    min_liquidity: Decimal | None = None,
                    venues: list[str] | None = None):
           ...
       def snapshot_at(self, as_of: datetime) -> UniverseSnapshot:
           """Universe as it would have been at `as_of` — no look-ahead."""
       def time_series(self, start: datetime, end: datetime,
                       frequency: str = "1d") -> list[UniverseSnapshot]:
           """Series of universe snapshots for the entire research window."""
   ```

2. **Implement `DatasetBuilder`**:
   ```python
   class DatasetConfig(BaseModel):
       """Configuration for a gold dataset build."""
       name: str
       start: datetime
       end: datetime
       venues: list[str] | None = None
       event_types: list[str] = ["trades", "ohlcv"]  # Which silver data to include
       universe_filters: dict[str, Any] = {}
       require_quality_pass: bool = True
       require_gap_free: bool = False
       max_gap_hours: float = 24.0

   class DatasetManifest(BaseModel):
       """Metadata for a built gold dataset."""
       dataset_id: str                  # Deterministic hash of config
       config: DatasetConfig
       built_at: datetime
       row_counts: dict[str, int]       # Per event type
       instrument_count: int
       date_range: tuple[datetime, datetime]
       quality_summary: dict[str, Any]
       schema_version: int

   class DatasetBuilder:
       """Assembles silver → gold datasets with look-ahead protection."""
       def __init__(self, reader: ParquetEventReader,
                    universe_mgr: UniverseManager,
                    quality_validator: PartitionValidator,
                    gap_detector: GapDetector,
                    storage_root: Path):
           ...
       def build(self, config: DatasetConfig) -> DatasetManifest:
           """Build a gold dataset from silver data.
           
           Steps:
           1. Generate universe time series for [start, end]
           2. Validate quality of all required silver partitions
           3. Check for gaps in required time windows
           4. Load silver data within [start, end] per universe
           5. Apply as-of join discipline (filter by ts_record)
           6. Write gold Parquet + universe.parquet + _meta.json
           """
       def load(self, dataset_id: str) -> GoldDataset:
           """Load a previously built gold dataset."""
       def list_datasets(self) -> list[DatasetManifest]:
           """List all available gold datasets."""
   ```

3. **Implement `GoldDataset`** — the in-memory handle to a built dataset:
   ```python
   class GoldDataset:
       """Handle to a gold-tier research dataset."""
       manifest: DatasetManifest
       
       def trades(self, instrument_id: str | None = None) -> pa.Table: ...
       def ohlcv(self, instrument_id: str | None = None,
                 resolution: str | None = None) -> pa.Table: ...
       def books(self, instrument_id: str | None = None) -> pa.Table: ...
       def universe_at(self, as_of: datetime) -> list[str]: ...
       def instruments(self) -> list[str]: ...
       def date_range(self) -> tuple[datetime, datetime]: ...
       def to_pandas(self, event_type: str = "trades") -> pd.DataFrame: ...
   ```

4. **Implement as-of join helpers**:
   ```python
   def as_of_filter(table: pa.Table, *,
                    as_of_column: str = "ts_record",
                    cutoff: datetime) -> pa.Table:
       """Filter table to only rows with as_of_column <= cutoff.
       Prevents look-ahead by using record time, not event time."""
   
   def align_to_grid(tables: dict[str, pa.Table], *,
                     frequency: str,
                     start: datetime,
                     end: datetime) -> dict[str, pa.Table]:
       """Align multiple tables to a common time grid via as-of join."""
   ```

5. **Add gold-tier storage conventions**:
   ```python
   # In storage/conventions.py
   GOLD_DATASET_SCHEMA = pa.schema([...])  # Extended with dataset_id, build metadata
   ```

6. **Add run-level reproducibility contracts (embedded in R1)**:
   ```python
   class RunContext(BaseModel):
       run_id: str
       run_type: Literal["dataset_build"]
       config_hash: str
       git_commit: str | None
       started_at_utc: datetime
       completed_at_utc: datetime | None

   class RunManifest(BaseModel):
       run: RunContext
       dataset_id: str
       artifacts: dict[str, str]         # Logical artifact name -> path
       parent_run_id: str | None = None
   ```

**Files Created/Modified:**

| Action | Path |
|---|---|
| Create | `libs/core/alpha_core/research/__init__.py` |
| Create | `libs/core/alpha_core/research/universe.py` |
| Create | `libs/core/alpha_core/research/dataset_builder.py` |
| Create | `libs/core/alpha_core/research/dataset.py` |
| Create | `libs/core/alpha_core/research/as_of.py` |
| Create | `libs/core/alpha_core/research/run_context.py` |
| Create | `libs/core/alpha_core/research/manifest.py` |
| Create | `libs/core/alpha_core/research/artifact_paths.py` |
| Modify | `libs/core/alpha_core/storage/conventions.py` — add gold schemas |

**Tests Added:**

| Test File | Key Cases | Count |
|---|---|---|
| `tests/unit/test_universe.py` | Snapshot at time, filters by lifecycle/volume/venue, time series generation | 10–14 |
| `tests/unit/test_dataset_builder.py` | Build from silver, look-ahead rejected, quality gate blocks bad data, gap check | 12–16 |
| `tests/unit/test_gold_dataset.py` | Load dataset, query trades/books/ohlcv, universe at time, to_pandas | 8–10 |
| `tests/unit/test_as_of.py` | as_of_filter removes future records, align_to_grid produces correct timestamps | 8–10 |
| `tests/unit/test_research_manifest.py` | Run context/manifest schema, required fields, serialization round-trip | 8–10 |
| `tests/integration/test_dataset_build_roundtrip.py` | Write silver → build gold → load → verify no look-ahead via ts_record check | 4–6 |

**Targets:**

| Metric | Target |
|---|---|
| Build gold dataset (10K silver events) | < 5s |
| Universe snapshot generation | < 100ms for 1K markets |
| As-of filter correctness | 0 future-leaked records (proven by test) |
| Dataset manifest persistence | Round-trip fidelity |
| New tests | 42–56 |

---

### Step R2: Feature Engine — Primitives & PM-Specific (Est. 40–65 hrs)

**Goal:** Feature computation library with generic time-series primitives and prediction-market-specific signals, plus a declarative feature registry.

**Embedded cross-stage contract work for this step (LA-006/LA-009):**

- Ensure feature builds are run-scoped: every feature artifact must carry `run_id`, `dataset_id`, and `feature_set_version`.
- Route feature persistence through an `ArtifactStore` interface (filesystem backend in MVP).
- Make feature metadata deterministic and hashable to support optimize reproducibility in R4.

**Actions:**

1. **Implement feature primitives** in `libs/core/alpha_core/features/`:
   ```python
   class FeatureResult(BaseModel):
       """Output of a single feature computation."""
       name: str
       values: pa.Array | np.ndarray     # Aligned to input timestamps
       computed_at: datetime
       params: dict[str, Any]

   class Feature(ABC):
       """Base class for all features."""
       name: str
       params: dict[str, Any]
       
       @abstractmethod
       def compute(self, data: pa.Table, *,
                   instrument_id: str | None = None) -> FeatureResult: ...
       
       @property
       def dependencies(self) -> list[str]:
           """Other features this depends on (for dependency resolution)."""
           return []

   # --- Time-series primitives ---
   class RollingMean(Feature): ...      # Rolling arithmetic mean
   class RollingStd(Feature): ...       # Rolling standard deviation
   class EWM(Feature): ...              # Exponentially weighted moving average
   class ZScore(Feature): ...           # (x - rolling_mean) / rolling_std
   class Rank(Feature): ...             # Cross-sectional or time-series rank
   class Lag(Feature): ...              # Shift by N periods
   class Diff(Feature): ...             # x[t] - x[t-N]
   class Return(Feature): ...           # (x[t] - x[t-N]) / x[t-N]
   class Volatility(Feature): ...       # Rolling std of returns
   ```

2. **Implement PM-specific features**:
   ```python
   class ImpliedProbMomentum(Feature):
       """Rate of change in implied probability (mid-price).
       For prediction markets, price ≈ probability, so momentum in price
       is directly interpretable as probability momentum."""
       def __init__(self, window: int = 20): ...

   class CrossVenueSpread(Feature):
       """Spread between the same question on different venues.
       Uses symbology.find_cross_venue_groups to match equivalent markets.
       Signal: large spreads indicate potential arbitrage or information asymmetry."""
       def __init__(self): ...

   class VolumeWeightedProb(Feature):
       """Volume-weighted average probability over a rolling window.
       Heavier volume = stronger conviction signal."""
       def __init__(self, window: int = 50): ...

   class TimeToResolutionDecay(Feature):
       """Days/hours remaining until resolution_date.
       Structural driver: theta-like decay, urgency premium.
       Normalised to [0, 1] where 1 = max time remaining."""
       def __init__(self): ...

   class CategoryMomentum(Feature):
       """Average probability momentum within the same market category.
       Captures sector/thematic trends (e.g., all politics markets moving together)."""
       def __init__(self, window: int = 10): ...

   class BookImbalance(Feature):
       """(bid_volume - ask_volume) / (bid_volume + ask_volume) at best levels.
       Indicates short-term directional pressure."""
       def __init__(self, levels: int = 3): ...

   class ProbAcceleration(Feature):
       """Second derivative of implied probability: momentum of momentum.
       fast_ewm - slow_ewm of probability changes."""
       def __init__(self, fast: int = 5, slow: int = 20): ...
   ```

3. **Implement `FeatureRegistry`**:
   ```python
   class FeatureRegistry:
       """Manages feature definitions, resolves dependencies, caches results."""
       def __init__(self): ...
       
       def register(self, feature: Feature) -> None:
           """Register a feature. Dependencies must be registered first."""
       
       def compute_all(self, data: pa.Table, *,
                       features: list[str] | None = None,
                       instrument_ids: list[str] | None = None) -> pa.Table:
           """Compute requested features (or all), respecting dependency order.
           Returns table with original columns + feature columns."""
       
       def compute_feature(self, name: str, data: pa.Table,
                           instrument_id: str | None = None) -> FeatureResult: ...
       
       @property
       def registered(self) -> list[str]: ...
       
       def dependency_order(self) -> list[str]:
           """Topological sort of features by dependency."""
   ```

4. **Implement `FeatureSetBuilder`** — batch feature computation to gold:
   ```python
   class FeatureSetConfig(BaseModel):
       name: str
       dataset_id: str                  # Which gold dataset to compute on
       features: list[str]              # Feature names from registry
       params_override: dict[str, dict[str, Any]] = {}  # Per-feature param overrides

   class FeatureSetBuilder:
       """Computes a feature set from a gold dataset and persists to gold/features/."""
       def __init__(self, registry: FeatureRegistry, storage_root: Path): ...
       def build(self, config: FeatureSetConfig,
                 dataset: GoldDataset) -> Path:
           """Compute features → write gold/features/{name}/features.parquet + _meta.json."""
       def load(self, feature_set_name: str) -> pa.Table: ...
   ```

5. **Integrate feature-stage run manifests and artifact storage (embedded in R2)**:
   ```python
   class FeatureRunManifest(BaseModel):
       run_id: str
       dataset_id: str
       feature_set_version: str
       config_hash: str
       artifacts: dict[str, str]
   ```

**Files Created/Modified:**

| Action | Path |
|---|---|
| Create | `libs/core/alpha_core/features/__init__.py` |
| Create | `libs/core/alpha_core/features/base.py` |
| Create | `libs/core/alpha_core/features/primitives.py` |
| Create | `libs/core/alpha_core/features/pm_specific.py` |
| Create | `libs/core/alpha_core/features/registry.py` |
| Create | `libs/core/alpha_core/features/feature_set.py` |
| Create | `libs/core/alpha_core/research/artifact_store.py` |

**Tests Added:**

| Test File | Key Cases | Count |
|---|---|---|
| `tests/unit/test_feature_primitives.py` | Each primitive: correct output, NaN handling, window > data, empty input | 20–25 |
| `tests/unit/test_pm_features.py` | Each PM feature: output range, cross-venue matching, TTR decay shape, empty category | 18–22 |
| `tests/unit/test_feature_registry.py` | Register, dependency resolution, topological sort, compute_all, missing dependency error | 10–12 |
| `tests/unit/test_feature_set.py` | Build from gold dataset, persist, reload, param overrides | 6–8 |
| `tests/unit/test_artifact_store.py` | Put/get/list/exists semantics and deterministic path contracts | 8–10 |
| `tests/integration/test_feature_pipeline.py` | Silver → gold → features pipeline, verify no NaN in required columns | 4–6 |

**Targets:**

| Metric | Target |
|---|---|
| Compute 8 features on 10K rows | < 2s |
| Feature registry topological sort | < 10ms for 50 features |
| PM features handle missing data | NaN propagation, no crashes |
| Cross-venue spread matches correct pairs | 100% vs symbology ground truth |
| New tests | 58–73 |

---

### Step R3: Event-Driven Backtester & Execution Simulator (Est. 45–70 hrs)

**Goal:** High-fidelity tick-by-tick backtester with realistic execution simulation tailored to prediction market microstructure.

**Embedded cross-stage contract work for this step (LA-001/LA-011/LA-012 prep):**

- Implement event engine strategy entrypoints in terms of framework contracts (`Universe`, `Alpha`, `Portfolio`, `Risk`, `Execution`).
- Keep order flow explicit (`OrderIntent -> simulated/validated execution result`) so live-plane reuse is direct.
- Add deterministic reject reason codes for invalid intents now, even in research mode, to prevent contract drift later.

**Actions:**

1. **Implement portfolio models** in `libs/core/alpha_core/portfolio/`:
   ```python
   class Side(StrEnum):
       LONG = "long"
       SHORT = "short"

   class PositionState(BaseModel):
       """Current state of a position in one outcome."""
       instrument_id: str
       side: Side
       size: Decimal                     # Number of contracts
       entry_price: Decimal              # Average fill price
       current_price: Decimal
       unrealised_pnl: Decimal
       realised_pnl: Decimal
       fees_paid: Decimal
       opened_at: datetime
       last_updated: datetime

   class PortfolioState(BaseModel):
       """Complete portfolio state at a point in time."""
       timestamp: datetime
       cash: Decimal
       positions: dict[str, PositionState]  # instrument_id → state
       total_pnl: Decimal
       total_fees: Decimal
       equity: Decimal                    # cash + sum(unrealised) - fees

   class PortfolioTracker:
       """Maintains portfolio state through a sequence of events."""
       def __init__(self, initial_cash: Decimal = Decimal("10000")): ...
       def apply_fill(self, fill: SimulatedFill) -> None: ...
       def apply_resolution(self, instrument_id: str, resolved_price: Decimal) -> None:
           """Handle prediction market resolution (0 or 1 payoff)."""
       def mark_to_market(self, prices: dict[str, Decimal], timestamp: datetime) -> None: ...
       def state(self) -> PortfolioState: ...
       def equity_curve(self) -> list[tuple[datetime, Decimal]]: ...
       def position_history(self) -> list[PositionState]: ...
   ```

2. **Implement execution simulation**:
   ```python
   class OrderIntent(BaseModel):
       """Strategy's desired trade."""
       instrument_id: str
       side: Side
       size: Decimal
       order_type: Literal["market", "limit"]
       limit_price: Decimal | None = None
       time_in_force: Literal["ioc", "gtc"] = "ioc"

   class SimulatedFill(BaseModel):
       """Result of simulated execution."""
       order: OrderIntent
       fill_price: Decimal
       fill_size: Decimal
       fee: Decimal
       timestamp: datetime
       slippage: Decimal                 # fill_price - intended_price

   class FeeSchedule(BaseModel):
       """Per-venue fee model."""
       maker_fee_bps: Decimal = Decimal("0")
       taker_fee_bps: Decimal = Decimal("0")
       per_contract_fee: Decimal = Decimal("0")
       resolution_fee_bps: Decimal = Decimal("0")  # PM-specific: fee on resolution payoff

   class ExecutionSimulator:
       """Simulates order execution against historical order book / trade data."""
       def __init__(self, fee_schedule: FeeSchedule,
                    slippage_model: SlippageModel | None = None): ...
       
       def simulate_fill(self, order: OrderIntent, *,
                         book: CanonicalBookSnapshot | None = None,
                         last_trade_price: Decimal | None = None,
                         timestamp: datetime) -> SimulatedFill | None:
           """Simulate fill. Returns None if order cannot be filled (e.g., limit not met)."""

   class SlippageModel(ABC):
       """Pluggable slippage model."""
       @abstractmethod
       def estimate_slippage(self, order: OrderIntent,
                             book: CanonicalBookSnapshot | None) -> Decimal: ...

   class FixedSlippage(SlippageModel):
       """Fixed basis points slippage."""
       def __init__(self, bps: Decimal = Decimal("10")): ...

   class BookDepthSlippage(SlippageModel):
       """Walk the order book to estimate fill price."""
       def __init__(self): ...
   ```

3. **Implement the event-driven backtester**:
   ```python
   class Strategy(ABC):
       """Base class for all trading strategies."""
       @abstractmethod
       def on_init(self, universe: list[str]) -> None:
           """Called once before backtest starts."""
       
       @abstractmethod
       def on_data(self, timestamp: datetime, state: StrategyState) -> list[OrderIntent]:
           """Called on each event. Return desired orders."""
       
       @abstractmethod
       def on_resolution(self, instrument_id: str, resolved_price: Decimal) -> None:
           """Called when a market resolves (PM-specific)."""
       
       @property
       def name(self) -> str: ...

   class StrategyState(BaseModel):
       """State visible to the strategy at each timestamp."""
       timestamp: datetime
       portfolio: PortfolioState
       latest_prices: dict[str, Decimal]
       features: dict[str, dict[str, float]] | None  # instrument → feature → value
       universe: list[str]

   class EventBacktestConfig(BaseModel):
       """Configuration for an event-driven backtest."""
       dataset_id: str
       feature_set: str | None = None
       initial_cash: Decimal = Decimal("10000")
       fee_schedule: FeeSchedule = FeeSchedule()
       slippage_model: str = "fixed"     # "fixed" | "book_depth"
       slippage_params: dict[str, Any] = {"bps": 10}
       start: datetime | None = None
       end: datetime | None = None

   class EventBacktestEngine:
       """Tick-by-tick event-driven backtest engine."""
       def __init__(self, config: EventBacktestConfig): ...
       
       def run(self, strategy: Strategy,
               dataset: GoldDataset,
               features: pa.Table | None = None) -> BacktestResult:
           """Execute the backtest:
           1. Build event timeline from dataset (sorted by ts_event)
           2. For each event:
              a. Update latest prices
              b. Check for resolved markets → call on_resolution
              c. Call strategy.on_data() → collect OrderIntents
              d. Simulate fills → update portfolio
              e. Record state snapshot
           3. Return BacktestResult with full history
           """

   class BacktestResult(BaseModel):
       """Complete result of a backtest run."""
       backtest_id: str                  # Deterministic hash of config + strategy
       config: EventBacktestConfig
       strategy_name: str
       trades: list[SimulatedFill]
       equity_curve: list[tuple[datetime, Decimal]]
       final_portfolio: PortfolioState
       duration_seconds: float
       event_count: int
   ```

4. **Align backtester strategy integration to framework contracts (embedded in R3)**:
   ```python
   class UniverseModel(Protocol): ...
   class AlphaModel(Protocol): ...
   class PortfolioConstructionModel(Protocol): ...
   class RiskModel(Protocol): ...
   class ExecutionModel(Protocol): ...
   ```

**Files Created/Modified:**

| Action | Path |
|---|---|
| Create | `libs/core/alpha_core/portfolio/__init__.py` |
| Create | `libs/core/alpha_core/portfolio/models.py` |
| Create | `libs/core/alpha_core/portfolio/tracker.py` |
| Create | `libs/core/alpha_core/execution/__init__.py` |
| Create | `libs/core/alpha_core/execution/models.py` |
| Create | `libs/core/alpha_core/execution/simulator.py` |
| Create | `libs/core/alpha_core/execution/slippage.py` |
| Create | `libs/core/alpha_core/execution/fees.py` |
| Create | `apps/research/backtester/__init__.py` |
| Create | `apps/research/backtester/strategy.py` |
| Create | `apps/research/backtester/engine.py` |
| Create | `apps/research/backtester/result.py` |
| Create | `libs/core/alpha_core/strategy_framework/interfaces.py` |
| Create | `libs/core/alpha_core/strategy_framework/models.py` |

**Tests Added:**

| Test File | Key Cases | Count |
|---|---|---|
| `tests/unit/test_portfolio_models.py` | PositionState, Side, PnL calculation, resolution payoff (0 or 1) | 10–12 |
| `tests/unit/test_portfolio_tracker.py` | Apply fill updates position, resolution settles at 0/1, equity curve, mark-to-market, short positions | 12–15 |
| `tests/unit/test_execution_models.py` | OrderIntent validation, SimulatedFill fields, fee schedule | 6–8 |
| `tests/unit/test_execution_simulator.py` | Market order fill, limit order reject, slippage applied, fee calculated, PM resolution fee | 10–14 |
| `tests/unit/test_slippage.py` | Fixed slippage, book depth walk, empty book fallback | 6–8 |
| `tests/unit/test_event_engine.py` | Dummy strategy → engine runs, events in order, resolution called, portfolio updated | 12–16 |
| `tests/integration/test_backtest_e2e.py` | Build dataset → compute features → run backtest → verify result integrity | 4–6 |

**Targets:**

| Metric | Target |
|---|---|
| Event engine 10K events | < 5s |
| Resolution payoff correctness | Exact 0/1 settlement, no rounding error |
| Portfolio tracker PnL | Matches manual calculation to 10 decimal places |
| Fill simulation with book data | Respects bid/ask, no fills at impossible prices |
| Short selling handled | Correct PnL for short positions (profit when price drops to 0) |
| New tests | 60–79 |

---

### Step R4: Vectorized Backtester & Parameter Sweep (Est. 35–55 hrs)

**Goal:** Fast-path DataFrame-based backtester for rapid strategy iteration and parameter sweeps.

**Embedded cross-stage contract work for this step (LA-010):**

- Promote sweep execution to a first-class optimize workflow (not just helper loops).
- Persist trial registry artifacts (params, objective, constraints, run links, seed) under run paths.
- Add leaderboard output with stable sorting and explicit tie-break behavior.

**Actions:**

1. **Implement vectorized engine**:
   ```python
   class VecBacktestConfig(BaseModel):
       """Configuration for vectorized backtest."""
       dataset_id: str
       feature_set: str
       initial_cash: Decimal = Decimal("10000")
       fee_bps: Decimal = Decimal("0")
       position_sizing: Literal["equal_weight", "kelly", "fixed_size"] = "equal_weight"
       rebalance_frequency: str = "1d"   # How often to re-evaluate positions
       max_positions: int = 50
       start: datetime | None = None
       end: datetime | None = None

   class VecStrategy(ABC):
       """Vectorized strategy interface — operates on DataFrames."""
       @abstractmethod
       def generate_signals(self, features: pd.DataFrame,
                            universe: list[str]) -> pd.DataFrame:
           """Return DataFrame with columns: instrument_id, signal (float).
           Positive = long, negative = short, 0 = flat."""
       
       @abstractmethod
       def size_positions(self, signals: pd.DataFrame,
                          portfolio_value: Decimal,
                          max_positions: int) -> pd.DataFrame:
           """Return DataFrame with columns: instrument_id, target_weight."""
       
       @property
       def name(self) -> str: ...

   class VecBacktestEngine:
       """Vectorized backtest: cross-sectional, DataFrame-native."""
       def __init__(self, config: VecBacktestConfig): ...
       
       def run(self, strategy: VecStrategy,
               dataset: GoldDataset,
               feature_table: pa.Table) -> BacktestResult:
           """Execute vectorised backtest:
           1. Resample data to rebalance_frequency grid
           2. At each rebalance point:
              a. Compute signals via strategy.generate_signals()
              b. Size positions via strategy.size_positions()
              c. Calculate trades needed (current → target)
              d. Apply fees, update portfolio
           3. Between rebalance points: mark-to-market
           4. Handle resolutions as they occur
           """
   ```

2. **Implement parameter sweep runner**:
   ```python
   class ParameterGrid:
       """Defines a grid of strategy parameters to sweep."""
       def __init__(self, params: dict[str, list[Any]]): ...
       def __iter__(self) -> Iterator[dict[str, Any]]: ...
       def __len__(self) -> int: ...

   class SweepResult(BaseModel):
       """Result of a parameter sweep."""
       sweep_id: str
       strategy_name: str
       parameter_grid: dict[str, list[Any]]
       results: list[tuple[dict[str, Any], BacktestResult]]  # (params, result) pairs
       best_params: dict[str, Any]       # By primary metric
       primary_metric: str               # e.g., "sharpe_ratio"
       completed_at: datetime

   class ParameterSweepRunner:
       """Runs a strategy across a grid of parameters."""
       def __init__(self, engine: VecBacktestEngine | EventBacktestEngine,
                    evaluator: BacktestEvaluator,
                    n_workers: int = 1): ...
       
       def run(self, strategy_factory: Callable[[dict], Strategy | VecStrategy],
               param_grid: ParameterGrid, *,
               dataset: GoldDataset,
               features: pa.Table | None = None,
               primary_metric: str = "sharpe_ratio") -> SweepResult:
           """Run backtest for each parameter combination (sequential or parallel)."""
   ```

3. **Implement position sizing models**:
   ```python
   class PositionSizer(ABC):
       """Maps signals to position sizes."""
       @abstractmethod
       def size(self, signals: pd.DataFrame, portfolio_value: Decimal,
                max_positions: int) -> pd.DataFrame: ...

   class EqualWeightSizer(PositionSizer): ...
   class FixedSizeSizer(PositionSizer): ...
   class KellySizer(PositionSizer):
       """Kelly criterion adapted for binary prediction markets.
       f* = (p * b - q) / b  where p = implied probability, b = odds."""
       ...
   ```

4. **Promote sweep to first-class optimize artifacts (embedded in R4)**:
   - Persist trial-level artifacts: params, objective, constraints, run links, seed.
   - Emit leaderboard artifact sorted by primary metric with deterministic tie-break rules.
   - Add optimize-run manifest schema to support CLI + CI automation.

**Files Created/Modified:**

| Action | Path |
|---|---|
| Create | `apps/research/backtester/vec_engine.py` |
| Create | `apps/research/backtester/vec_strategy.py` |
| Create | `apps/research/backtester/sweep.py` |
| Create | `libs/core/alpha_core/portfolio/sizing.py` |
| Create | `libs/core/alpha_core/research/optimize_runner.py` |

**Tests Added:**

| Test File | Key Cases | Count |
|---|---|---|
| `tests/unit/test_vec_engine.py` | Dummy strategy → vectorised run, rebalance at frequency, handles resolutions, fees applied | 10–14 |
| `tests/unit/test_vec_strategy.py` | Signal generation, position sizing, empty universe, all-flat signals | 6–8 |
| `tests/unit/test_parameter_sweep.py` | Grid generation, sweep runs all combos, best params selected, empty grid | 8–10 |
| `tests/unit/test_position_sizing.py` | Equal weight, Kelly for binary PM (known formula), fixed size, edge cases | 8–10 |
| `tests/unit/test_optimize_runner.py` | Trial registry, leaderboard ranking, deterministic seed behavior | 6–8 |
| `tests/integration/test_vec_backtest_e2e.py` | Feature set → vec strategy → run → result matches expected equity | 3–5 |
| `tests/integration/test_research_optimize.py` | CLI/runner optimize flow persists trials and best-run metadata | 3–5 |

**Targets:**

| Metric | Target |
|---|---|
| Vectorised engine 10K rows × 50 instruments | < 3s |
| Parameter sweep 20 combinations | < 60s |
| Equal-weight sum to 1.0 | Verified (no rounding drift) |
| Kelly sizer clamps to [0, max_leverage] | Verified |
| Vec + event engine produce congruent results | Within 1% on same data/strategy |
| New tests | 35–47 |

---

### Step R5: Evaluation Metrics & Reporting (Est. 30–50 hrs)

**Goal:** Comprehensive evaluation metrics suite including PM-specific metrics, and structured report generation.

**Embedded cross-stage contract work for this step (LA-014 prep):**

- Version report schemas explicitly and add compatibility notes in each report artifact.
- Emit a standard run summary block shared by `evaluate`, `report`, and future live commands.
- Capture run lineage links (`parent_run_id`, source dataset/feature run IDs) in evaluation artifacts.

**Actions:**

1. **Implement financial metrics**:
   ```python
   class FinancialMetrics(BaseModel):
       """Standard financial performance metrics."""
       total_return: Decimal
       annualised_return: Decimal
       sharpe_ratio: float
       sortino_ratio: float
       max_drawdown: Decimal
       max_drawdown_duration_days: int
       win_rate: float                    # % of profitable trades
       profit_factor: Decimal             # gross_profit / gross_loss
       avg_trade_pnl: Decimal
       total_trades: int
       avg_holding_period_hours: float
       calmar_ratio: float               # annualised_return / max_drawdown
       volatility: float                  # Annualised return volatility

   def compute_financial_metrics(result: BacktestResult) -> FinancialMetrics: ...
   ```

2. **Implement PM-specific metrics**:
   ```python
   class PMMetrics(BaseModel):
       """Prediction-market-specific evaluation metrics."""
       brier_score: float                 # Mean (forecast - outcome)²
       log_loss: float                    # -mean(y*log(p) + (1-y)*log(1-p))
       calibration_error: float           # Expected calibration error (ECE)
       calibration_bins: list[dict]       # {bin_start, bin_end, avg_predicted, avg_actual, count}
       resolution_pnl: Decimal            # PnL from markets that resolved during backtest
       resolution_count: int
       resolution_accuracy: float         # % of resolved positions where we were on the right side
       avg_prob_at_entry: Decimal         # Average implied probability when entering positions
       avg_prob_at_exit: Decimal          # Average implied probability when exiting
       category_breakdown: dict[str, dict[str, float]]  # category → {sharpe, brier, trades}

   def compute_pm_metrics(result: BacktestResult,
                          dataset: GoldDataset) -> PMMetrics: ...
   ```

3. **Implement `BacktestEvaluator`**:
   ```python
   class EvaluationReport(BaseModel):
       """Full evaluation report combining all metrics."""
       backtest_id: str
       strategy_name: str
       financial: FinancialMetrics
       pm_specific: PMMetrics
       equity_curve_summary: dict[str, Any]
       monthly_returns: list[dict[str, Any]]
       best_trades: list[dict[str, Any]]   # Top 5 by PnL
       worst_trades: list[dict[str, Any]]  # Bottom 5 by PnL

   class BacktestEvaluator:
       """Computes all evaluation metrics and generates reports."""
       def __init__(self): ...
       
       def evaluate(self, result: BacktestResult,
                    dataset: GoldDataset) -> EvaluationReport: ...
       
       def compare(self, reports: list[EvaluationReport]) -> pd.DataFrame:
           """Side-by-side comparison of multiple strategies/parameter sets."""
   ```

4. **Implement report persistence**:
   ```python
   class ReportWriter:
       """Writes structured reports to disk."""
       def __init__(self, storage_root: Path): ...
       
       def write(self, report: EvaluationReport) -> Path:
           """Write to backtests/{backtest_id}/:
           - config.json
           - trades.parquet
           - positions.parquet
           - equity.parquet
           - metrics.json
           - report.json
           """
       
       def load(self, backtest_id: str) -> EvaluationReport: ...
       def list_reports(self) -> list[str]: ...
   ```

5. **Implement calibration curve computation**:
   ```python
   def calibration_curve(predictions: np.ndarray, outcomes: np.ndarray,
                         n_bins: int = 10) -> list[dict]:
       """Expected vs actual outcome probability per bin.
       Critical for prediction market strategies where probability calibration matters."""
   
   def expected_calibration_error(predictions: np.ndarray,
                                  outcomes: np.ndarray,
                                  n_bins: int = 10) -> float:
       """ECE = sum(|avg_predicted - avg_actual| * bin_weight)."""
   ```

6. **Add schema-versioned reporting contracts (embedded in R5)**:
   - Add explicit report schema version fields.
   - Add manifest/report schema regression tests to catch accidental contract drift.
   - Persist lineage references to dataset/feature/backtest run manifests.

**Files Created/Modified:**

| Action | Path |
|---|---|
| Create | `libs/core/alpha_core/evaluation/__init__.py` |
| Create | `libs/core/alpha_core/evaluation/financial.py` |
| Create | `libs/core/alpha_core/evaluation/pm_metrics.py` |
| Create | `libs/core/alpha_core/evaluation/calibration.py` |
| Create | `libs/core/alpha_core/evaluation/evaluator.py` |
| Create | `apps/research/reporting/__init__.py` |
| Create | `apps/research/reporting/writer.py` |
| Create | `apps/research/reporting/comparisons.py` |
| Create | `tests/regression/test_run_manifest_schema.py` |
| Create | `tests/regression/test_metrics_report_schema.py` |

**Tests Added:**

| Test File | Key Cases | Count |
|---|---|---|
| `tests/unit/test_financial_metrics.py` | Sharpe from known returns, drawdown from known equity, win rate, profit factor, zero-trade edge case | 12–15 |
| `tests/unit/test_pm_metrics.py` | Brier score on known binary outcomes, log-loss, calibration error, resolution accuracy, category breakdown | 12–15 |
| `tests/unit/test_calibration.py` | Perfect calibration → ECE = 0, degenerate predictions, empty bins, boundary cases | 8–10 |
| `tests/unit/test_evaluator.py` | Full evaluate produces all fields, compare returns aligned DataFrame | 6–8 |
| `tests/unit/test_report_writer.py` | Write → load round-trip, list reports, missing backtest error | 6–8 |
| `tests/integration/test_evaluation_pipeline.py` | Backtest result → evaluate → write → load → verify all metrics present | 3–5 |

**Targets:**

| Metric | Target |
|---|---|
| Sharpe calculation | Matches manual to 4 decimal places on known data |
| Brier score | = 0.0 for perfect forecaster, = 0.25 for uniform random on binary |
| Log-loss | = 0.0 for perfect, = ln(2) ≈ 0.693 for uniform random |
| Calibration error | = 0.0 for perfectly calibrated predictions |
| Report generation | < 1s for 1K-trade backtest |
| Round-trip persistence | 100% fidelity |
| New tests | 47–61 |

---

### Step R6: Research CLI & Integration Wiring (Est. 35–55 hrs)

**Goal:** Complete the research CLI with subcommands, wire all components together, and deliver example strategies.

**Embedded cross-stage contract work for this step (LA-004/LA-008/LA-010/LA-015):**

- Include `optimize` in the core CLI surface for repeatable search workflows.
- Standardize `--format json` output and non-zero exit behavior across all commands.
- Require every command to emit a run manifest and artifact index.
- Add CI smoke coverage for the command chain.

**Actions:**

1. **Wire `apps/research/main.py`** — full CLI:
   ```python
   @click.group()
   def cli(): ...
   
   @cli.command()
   @click.option("--name", required=True, help="Dataset name")
   @click.option("--start", required=True, type=click.DateTime())
   @click.option("--end", required=True, type=click.DateTime())
   @click.option("--venues", multiple=True)
   @click.option("--event-types", multiple=True, default=["trades", "ohlcv"])
   @click.option("--require-quality/--no-require-quality", default=True)
   def build_dataset(name, start, end, venues, event_types, require_quality):
       """Build a gold dataset from silver data."""
   
   @cli.command()
   @click.option("--dataset", required=True, help="Dataset ID or name")
   @click.option("--feature-set", required=True, help="Feature set name")
   @click.option("--features", multiple=True, help="Specific features (default: all registered)")
   def build_features(dataset, feature_set, features):
       """Compute features on a gold dataset."""
   
   @cli.command()
   @click.option("--strategy", required=True, help="Strategy module path")
   @click.option("--dataset", required=True)
   @click.option("--features", help="Feature set name")
   @click.option("--engine", type=click.Choice(["event", "vec"]), default="event")
   @click.option("--initial-cash", type=float, default=10000)
   @click.option("--fee-bps", type=float, default=0)
   @click.option("--slippage-bps", type=float, default=10)
   def backtest(strategy, dataset, features, engine, initial_cash, fee_bps, slippage_bps):
       """Run a backtest with a specified strategy."""
   
   @cli.command()
   @click.argument("backtest_ids", nargs=-1)
   def evaluate(backtest_ids):
       """Evaluate one or more backtest results."""
   
   @cli.command()
   @click.argument("backtest_ids", nargs=-1)
   @click.option("--format", type=click.Choice(["json", "table"]), default="table")
   def report(backtest_ids, format):
       """Generate and display evaluation reports."""

   @cli.command()
   @click.option("--config", required=True, help="Optimize config path")
   @click.option("--primary-metric", default="sharpe_ratio")
   @click.option("--max-trials", type=int, default=None)
   def optimize(config, primary_metric, max_trials):
       """Run parameter optimization and persist trial leaderboard artifacts."""

   @cli.command()
   def list_datasets():
       """List available gold datasets."""
   
   @cli.command()
   def list_backtests():
       """List available backtest results."""
   
   @cli.command()
   def list_features():
       """List registered features and feature sets."""
   ```

2. **Implement example strategies** for testing and demonstration:
   ```python
   # apps/research/strategies/probability_momentum.py
   class ProbabilityMomentumStrategy(Strategy):
       """Simple momentum: go long when implied probability momentum > threshold,
       short when < -threshold. PM-native signal."""
       def __init__(self, momentum_threshold: float = 0.02,
                    window: int = 20): ...

   # apps/research/strategies/cross_venue_arb.py
   class CrossVenueArbStrategy(Strategy):
       """Buy cheaper / sell more expensive when cross-venue spread exceeds threshold.
       PM-specific: same question traded on multiple venues."""
       def __init__(self, spread_threshold: float = 0.05): ...

   # apps/research/strategies/mean_reversion.py
   class MeanReversionStrategy(VecStrategy):
       """Cross-sectional mean reversion: short winners, long losers.
       Adapted for PM: reversion towards 0.5 in probability space."""
       def __init__(self, zscore_threshold: float = 2.0,
                    lookback: int = 50): ...
   ```

3. **Implement strategy loader** — dynamic import from module path:
   ```python
   class StrategyLoader:
       """Loads strategy classes from module paths."""
       def load(self, module_path: str) -> type[Strategy] | type[VecStrategy]:
           """Dynamically import and return strategy class.
           Example: 'apps.research.strategies.probability_momentum.ProbabilityMomentumStrategy'
           """
   ```

4. **Add research config extensions**:
   ```python
   # Extend Settings or add ResearchConfig
   class ResearchConfig(BaseModel):
       default_initial_cash: Decimal = Decimal("10000")
       default_fee_bps: Decimal = Decimal("0")
       default_slippage_bps: Decimal = Decimal("10")
       default_engine: Literal["event", "vec"] = "event"
       max_sweep_combinations: int = 1000
       backtest_storage_path: str = "backtests"
   ```

5. **Create integration smoke tests** — full research pipeline:
   ```python
   async def test_full_research_pipeline(tmp_path, sample_silver_data):
       """Silver → build dataset → build features → backtest → evaluate → report."""
   
   async def test_probability_momentum_strategy(tmp_path, sample_gold_dataset):
       """Run ProbMomentum on sample data, verify non-trivial trades generated."""
   
   async def test_vec_vs_event_congruence(tmp_path, sample_gold_dataset):
       """Same strategy on both engines produces similar metrics (within tolerance)."""
   ```

**Files Created/Modified:**

| Action | Path |
|---|---|
| Modify | `apps/research/main.py` — replace stub with full CLI |
| Create | `apps/research/commands/__init__.py` |
| Create | `apps/research/commands/common.py` |
| Create | `apps/research/commands/build_dataset.py` |
| Create | `apps/research/commands/build_features.py` |
| Create | `apps/research/commands/backtest.py` |
| Create | `apps/research/commands/evaluate.py` |
| Create | `apps/research/commands/report.py` |
| Create | `apps/research/commands/optimize.py` |
| Create | `apps/research/strategies/__init__.py` |
| Create | `apps/research/strategies/probability_momentum.py` |
| Create | `apps/research/strategies/cross_venue_arb.py` |
| Create | `apps/research/strategies/mean_reversion.py` |
| Create | `apps/research/strategies/loader.py` |
| Create | `libs/core/alpha_core/research/optimize_runner.py` |
| Modify | `libs/core/alpha_core/config/models.py` — add `ResearchConfig` |

**Tests Added:**

| Test File | Key Cases | Count |
|---|---|---|
| `tests/unit/test_research_cli.py` | CLI --help, build-dataset args, backtest args, list commands | 8–10 |
| `tests/unit/test_example_strategies.py` | Each strategy: generate orders on sample data, handles empty universe, respects thresholds | 10–12 |
| `tests/unit/test_strategy_loader.py` | Load valid module, invalid path error, wrong class type error | 4–6 |
| `tests/unit/test_optimize_runner.py` | Grid/random search, objective ranking, constraints, seed reproducibility | 6–8 |
| `tests/integration/test_research_pipeline_e2e.py` | Full pipeline: silver → dataset → features → backtest → evaluate → report | 4–6 |
| `tests/integration/test_engine_congruence.py` | Event vs vec engine produce similar results on shared strategy | 2–3 |
| `tests/integration/test_research_optimize.py` | End-to-end optimize run writes trial registry + leaderboard | 3–5 |

**Targets:**

| Metric | Target |
|---|---|
| CLI `--help` for all commands | Works |
| Full pipeline (sample data) | < 30s end-to-end |
| ProbMomentum strategy | Generates ≥ 1 trade on sample data |
| Strategy loader | Handles valid + invalid paths gracefully |
| Config backward compatible | All existing tests pass |
| New tests | 28–37 |
| **Total Research Plane tests** | **≥ 730** (460 existing + ~270 new) |

---

## 6. Baseline Targets & Acceptance Criteria

### Quantitative Targets

| Category | Metric | Research Plane Target |
|---|---|---|
| **Code quality** | ruff lint errors | 0 |
| | mypy strict errors | 0 |
| | Test coverage (`libs/core/` + `apps/`) | ≥ 85% |
| | All tests pass | 100% |
| | Total test count | ≥ 730 |
| **Dataset building** | Gold dataset build (10K silver events) | < 5s |
| | Universe snapshot (1K markets) | < 100ms |
| | As-of join (no look-ahead) | 0 future-leaked records |
| **Feature computation** | 8 features on 10K rows | < 2s |
| | Registry topological sort | < 10ms for 50 features |
| | PM features handle missing data | No crashes, NaN propagation |
| **Backtesting** | Event engine 10K events | < 5s |
| | Vectorised engine 10K × 50 instruments | < 3s |
| | Parameter sweep 20 combos | < 60s |
| **Execution simulation** | Fill price respects book | 100% — no fills at impossible prices |
| | Resolution payoff | Exact 0/1 settlement |
| | Portfolio PnL | Matches manual to 10 dp |
| **Evaluation** | Sharpe on known data | Matches to 4 dp |
| | Brier score | = 0.0 perfect, = 0.25 random |
| | Calibration error | = 0.0 for perfectly calibrated |
| | Report generation (1K trades) | < 1s |
| **Persistence** | Gold dataset round-trip | 100% fidelity |
| | Backtest report round-trip | 100% fidelity |
| | Run manifest completeness | 100% runs contain required fields (`run_id`, versions, config hash, git commit or fallback) |
| **Optimization** | Trial registry persistence | 100% trials persisted with params + objective + run links |
| | Reproducibility with fixed seed | Stable ranking within defined tolerance |
| **CLI contracts** | `--format json` support | Available for all research commands |
| | Exit behavior | Non-zero on validation/contract failure |
| **Congruence** | Event vs vec engine | Within 1% on same data/strategy |

### Acceptance Criteria (Definition of Done)

The Research Plane MVP is **complete** when all of the following are true:

- [ ] `ruff check . && mypy libs/core apps/ --strict` — 0 errors
- [ ] `pytest tests/ -v` — all tests green, ≥ 730 total, ≥ 85% coverage
- [ ] Dataset builder produces gold datasets with zero look-ahead leakage
- [ ] Universe manager respects market lifecycle at each point in time
- [ ] Feature registry computes all primitives + 7 PM-specific features with dependency resolution
- [ ] Event-driven backtester runs tick-by-tick with fill simulation, resolution handling, and portfolio tracking
- [ ] Vectorised backtester runs cross-sectional with rebalance-frequency grid
- [ ] Execution simulator handles market + limit orders, fees, slippage, PM resolution fees
- [ ] Portfolio tracker maintains correct PnL (realised, unrealised, resolution) to 10 decimal places
- [ ] Evaluation suite produces Sharpe, Brier, log-loss, calibration, and resolution decomposition
- [ ] Report writer persists and round-trips all metrics and equity curve data
- [ ] 3 example strategies exist and produce non-trivial results on sample data
- [ ] CLI works: `build-dataset`, `build-features`, `backtest`, `evaluate`, `report`, `optimize`, `list-*`
- [ ] All research CLI commands support `--format json` and deterministic exit codes
- [ ] Every stage emits a run manifest and artifact index under `data/runs/{run_id}/`
- [ ] Artifact persistence is routed through a stable store abstraction (filesystem backend for MVP)
- [ ] All existing foundation + data plane tests still pass (0 regressions)
- [ ] Config system extended for research settings (backward compatible)

---

## 7. Test Requirements

### Test Pyramid — Research Plane MVP

```
          ┌──────────┐
          │  E2E /   │   7–13 tests
          │  Pipeline │   Silver → gold → features → backtest/evaluate/optimize
          ├──────────┤
         │Integration│   15–24 tests
         │  Component│   Dataset build, feature pipeline,
         │  flows    │   backtest engine, evaluation, optimize, run manifests
         ├───────────┤
        │    Unit     │   ~255 tests
        │ Features,   │   Pure logic, no I/O
        │ portfolio,  │   Fast (< 15s total)
        │ metrics     │
        └─────────────┘
```

### Unit Test Summary by Module

| Module | Test File(s) | Key Test Cases | Min Count |
|---|---|---|---|
| Universe mgr | `test_universe.py` | Snapshot, lifecycle filter, time series | 10 |
| Dataset builder | `test_dataset_builder.py` | Build, look-ahead, quality gate, gap check | 12 |
| Gold dataset | `test_gold_dataset.py` | Load, query, universe_at, to_pandas | 8 |
| As-of joins | `test_as_of.py` | Filter, align, future-record rejection | 8 |
| Feature primitives | `test_feature_primitives.py` | Each primitive: correctness, edges | 20 |
| PM features | `test_pm_features.py` | Each PM feature: output, edges | 18 |
| Feature registry | `test_feature_registry.py` | Register, deps, compute_all | 10 |
| Feature set | `test_feature_set.py` | Build, persist, reload | 6 |
| Portfolio models | `test_portfolio_models.py` | Position, PnL, resolution | 10 |
| Portfolio tracker | `test_portfolio_tracker.py` | Fill, resolution, M2M, equity | 12 |
| Execution models | `test_execution_models.py` | OrderIntent, Fill, FeeSchedule | 6 |
| Execution simulator | `test_execution_simulator.py` | Market/limit fill, slippage, fees | 10 |
| Slippage | `test_slippage.py` | Fixed, book depth, empty book | 6 |
| Event engine | `test_event_engine.py` | Run, events order, resolution, portfolio | 12 |
| Vec engine | `test_vec_engine.py` | Run, rebalance, resolution, fees | 10 |
| Vec strategy | `test_vec_strategy.py` | Signals, sizing, empty universe | 6 |
| Parameter sweep | `test_parameter_sweep.py` | Grid, run all, best params | 8 |
| Position sizing | `test_position_sizing.py` | Equal, Kelly, fixed, edges | 8 |
| Financial metrics | `test_financial_metrics.py` | Sharpe, drawdown, win rate | 12 |
| PM metrics | `test_pm_metrics.py` | Brier, log-loss, calibration, resolution | 12 |
| Calibration | `test_calibration.py` | Perfect, degenerate, boundaries | 8 |
| Evaluator | `test_evaluator.py` | Evaluate, compare | 6 |
| Report writer | `test_report_writer.py` | Write, load, list | 6 |
| Research CLI | `test_research_cli.py` | Help, args for each command | 8 |
| Example strategies | `test_example_strategies.py` | Each strategy on sample data | 10 |
| Strategy loader | `test_strategy_loader.py` | Valid, invalid, wrong type | 4 |
| Run manifests | `test_research_manifest.py` | Schema, required fields, round-trip, hash determinism | 8 |
| Artifact store | `test_artifact_store.py` | Put/get/list/exists, overwrite semantics, path determinism | 8 |
| Optimize runner | `test_optimize_runner.py` | Grid/random sweep, constraints, leaderboard ordering | 8 |
| Schema regression | `tests/regression/test_run_manifest_schema.py`, `tests/regression/test_metrics_report_schema.py` | Contract stability across versions | 4 |

### Integration Test Summary

| Test File | Scope | Count |
|---|---|---|
| `test_dataset_build_roundtrip.py` | Silver → gold → load → verify | 4–6 |
| `test_feature_pipeline.py` | Gold → features → verify no NaN | 4–6 |
| `test_backtest_e2e.py` | Dataset → features → backtest → result | 4–6 |
| `test_evaluation_pipeline.py` | Result → evaluate → write → load | 3–5 |
| `test_research_pipeline_e2e.py` | Full pipeline end-to-end | 4–6 |
| `test_engine_congruence.py` | Event vs vec engines compared | 2–3 |
| `test_vec_backtest_e2e.py` | Features → vec strategy → run | 3–5 |
| `test_research_optimize.py` | Features/backtests → optimize → leaderboard artifacts | 3–5 |
| `test_live_contract_reuse.py` | Shared strategy contracts usable by research + live runtime stubs | 2–4 |

### Test Fixtures — New

| File | Content |
|---|---|
| `tests/data/fixtures/sample_gold_trades.parquet` | Pre-built gold-tier trades for strategy tests |
| `tests/data/fixtures/sample_gold_ohlcv.parquet` | Pre-built gold-tier OHLCV for feature tests |
| `tests/data/fixtures/sample_features.parquet` | Pre-computed feature matrix for backtest tests |
| `tests/data/fixtures/sample_equity_curve.json` | Known equity curve for metric validation |
| `tests/data/fixtures/sample_resolutions.json` | Market resolution events for PM metric tests |
| `tests/data/fixtures/known_brier_data.json` | Predictions + outcomes with known Brier score |

---

## 8. Codebase Evolution — File-by-File

### After R1: Dataset Builder & Universe Manager

```diff
+ libs/core/alpha_core/research/
+   __init__.py
+   universe.py                          # UniverseManager, UniverseSnapshot
+   dataset_builder.py                   # DatasetBuilder, DatasetConfig, DatasetManifest
+   dataset.py                           # GoldDataset handle
+   as_of.py                             # as_of_filter, align_to_grid
+   run_context.py                       # RunContext model (shared across stages)
+   manifest.py                          # Run manifest schema + persistence helpers
+   artifact_paths.py                    # Deterministic run/artifact path helpers
~ libs/core/alpha_core/storage/conventions.py  # + gold-tier schemas
+
  tests/unit/
+   test_universe.py
+   test_dataset_builder.py
+   test_gold_dataset.py
+   test_as_of.py
  tests/integration/
+   test_dataset_build_roundtrip.py
```

### After R2: Feature Engine

```diff
+ libs/core/alpha_core/features/
+   __init__.py
+   base.py                              # Feature ABC, FeatureResult
+   primitives.py                        # RollingMean, EWM, ZScore, Rank, Lag, Diff, Return, Volatility
+   pm_specific.py                       # ImpliedProbMomentum, CrossVenueSpread, VolumeWeightedProb,
+                                        #   TimeToResolutionDecay, CategoryMomentum, BookImbalance,
+                                        #   ProbAcceleration
+   registry.py                          # FeatureRegistry — declarative, dependency-resolved
+   feature_set.py                       # FeatureSetBuilder, FeatureSetConfig
+ libs/core/alpha_core/research/
+   artifact_store.py                    # Shared artifact persistence abstraction (filesystem backend)
+
  tests/unit/
+   test_feature_primitives.py
+   test_pm_features.py
+   test_feature_registry.py
+   test_feature_set.py
  tests/integration/
+   test_feature_pipeline.py
```

### After R3: Event-Driven Backtester & Execution Simulator

```diff
+ libs/core/alpha_core/portfolio/
+   __init__.py
+   models.py                            # PositionState, PortfolioState, Side
+   tracker.py                           # PortfolioTracker — fill, resolution, M2M, equity
+ libs/core/alpha_core/execution/
+   __init__.py
+   models.py                            # OrderIntent, SimulatedFill, FeeSchedule
+   simulator.py                         # ExecutionSimulator — fill against book/last price
+   slippage.py                          # SlippageModel ABC, FixedSlippage, BookDepthSlippage
+   fees.py                              # Fee calculation helpers
+ apps/research/backtester/
+   __init__.py
+   strategy.py                          # Strategy ABC, StrategyState
+   engine.py                            # EventBacktestEngine, EventBacktestConfig
+   result.py                            # BacktestResult
+
  tests/unit/
+   test_portfolio_models.py
+   test_portfolio_tracker.py
+   test_execution_models.py
+   test_execution_simulator.py
+   test_slippage.py
+   test_event_engine.py
  tests/integration/
+   test_backtest_e2e.py
```

### After R4: Vectorized Backtester & Parameter Sweep

```diff
+ apps/research/backtester/
+   vec_engine.py                        # VecBacktestEngine, VecBacktestConfig
+   vec_strategy.py                      # VecStrategy ABC
+   sweep.py                             # ParameterGrid, ParameterSweepRunner, SweepResult
+ libs/core/alpha_core/portfolio/
+   sizing.py                            # EqualWeightSizer, KellySizer, FixedSizeSizer
+
  tests/unit/
+   test_vec_engine.py
+   test_vec_strategy.py
+   test_parameter_sweep.py
+   test_position_sizing.py
  tests/integration/
+   test_vec_backtest_e2e.py
```

### After R5: Evaluation Metrics & Reporting

```diff
+ libs/core/alpha_core/evaluation/
+   __init__.py
+   financial.py                         # FinancialMetrics, compute_financial_metrics
+   pm_metrics.py                        # PMMetrics, compute_pm_metrics
+   calibration.py                       # calibration_curve, expected_calibration_error
+   evaluator.py                         # BacktestEvaluator, EvaluationReport
+ apps/research/reporting/
+   __init__.py
+   writer.py                            # ReportWriter — persist + load
+   comparisons.py                       # Side-by-side strategy comparison
+
  tests/unit/
+   test_financial_metrics.py
+   test_pm_metrics.py
+   test_calibration.py
+   test_evaluator.py
+   test_report_writer.py
  tests/integration/
+   test_evaluation_pipeline.py
  tests/data/fixtures/
+   sample_gold_trades.parquet
+   sample_gold_ohlcv.parquet
+   sample_features.parquet
+   sample_equity_curve.json
+   sample_resolutions.json
+   known_brier_data.json
```

### After R6: Research CLI & Integration (Final State)

```diff
~ apps/research/main.py                  # Full CLI: build-dataset, build-features, backtest,
~                                        #   evaluate, report, optimize, list-datasets, list-backtests,
~                                        #   list-features
+ apps/research/commands/
+   __init__.py
+   common.py
+   build_dataset.py
+   build_features.py
+   backtest.py
+   evaluate.py
+   report.py
+   optimize.py
+ apps/research/strategies/
+   __init__.py
+   probability_momentum.py              # ProbabilityMomentumStrategy (event-driven)
+   cross_venue_arb.py                   # CrossVenueArbStrategy (event-driven)
+   mean_reversion.py                    # MeanReversionStrategy (vectorized)
+   loader.py                            # StrategyLoader — dynamic import
~ libs/core/alpha_core/config/models.py  # + ResearchConfig
+
  tests/unit/
+   test_research_cli.py
+   test_example_strategies.py
+   test_strategy_loader.py
  tests/integration/
+   test_research_pipeline_e2e.py
+   test_engine_congruence.py
```

### Complete Post-Research-Plane File Tree (New/Modified Only)

```
alpha-research-lab-private/
├── apps/research/
│   ├── __init__.py
│   ├── main.py                          # Full CLI with subcommands
│   ├── commands/                        # Command modules incl. optimize
│   ├── backtester/
│   │   ├── __init__.py
│   │   ├── strategy.py                  # Strategy ABC, StrategyState
│   │   ├── engine.py                    # EventBacktestEngine
│   │   ├── vec_engine.py                # VecBacktestEngine
│   │   ├── vec_strategy.py              # VecStrategy ABC
│   │   ├── result.py                    # BacktestResult
│   │   └── sweep.py                     # ParameterGrid, SweepRunner
│   ├── reporting/
│   │   ├── __init__.py
│   │   ├── writer.py                    # ReportWriter
│   │   └── comparisons.py              # Strategy comparison
│   └── strategies/
│       ├── __init__.py
│       ├── probability_momentum.py      # Example: PM probability momentum
│       ├── cross_venue_arb.py           # Example: cross-venue arbitrage
│       ├── mean_reversion.py            # Example: cross-sectional mean reversion
│       └── loader.py                    # Dynamic strategy import
├── libs/core/alpha_core/
│   ├── research/                        # NEW MODULE
│   │   ├── __init__.py
│   │   ├── universe.py                  # UniverseManager, UniverseSnapshot
│   │   ├── dataset_builder.py           # DatasetBuilder, DatasetConfig, DatasetManifest
│   │   ├── dataset.py                   # GoldDataset
│   │   ├── as_of.py                     # Point-in-time join helpers
│   │   ├── run_context.py               # Cross-stage run metadata
│   │   ├── manifest.py                  # Run manifest schema/persistence
│   │   ├── artifact_paths.py            # Canonical run output paths
│   │   └── artifact_store.py            # Artifact persistence abstraction
│   ├── features/                        # NEW MODULE
│   │   ├── __init__.py
│   │   ├── base.py                      # Feature ABC, FeatureResult
│   │   ├── primitives.py                # 8 time-series primitives
│   │   ├── pm_specific.py               # 7 PM-specific features
│   │   ├── registry.py                  # FeatureRegistry
│   │   └── feature_set.py              # FeatureSetBuilder
│   ├── portfolio/                       # NEW MODULE
│   │   ├── __init__.py
│   │   ├── models.py                    # PositionState, PortfolioState, Side
│   │   ├── tracker.py                   # PortfolioTracker
│   │   └── sizing.py                    # Position sizing models
│   ├── execution/                       # NEW MODULE
│   │   ├── __init__.py
│   │   ├── models.py                    # OrderIntent, SimulatedFill, FeeSchedule
│   │   ├── simulator.py                # ExecutionSimulator
│   │   ├── slippage.py                 # Slippage models
│   │   └── fees.py                     # Fee helpers
│   ├── evaluation/                      # NEW MODULE
│   │   ├── __init__.py
│   │   ├── financial.py                # Sharpe, Sortino, drawdown, etc.
│   │   ├── pm_metrics.py              # Brier, log-loss, calibration, resolution
│   │   ├── calibration.py             # Calibration curve, ECE
│   │   └── evaluator.py              # BacktestEvaluator, EvaluationReport
│   ├── config/
│   │   └── models.py                    # + ResearchConfig
│   └── storage/
│       └── conventions.py               # + gold-tier schemas
├── data/
│   └── runs/
│       └── {run_id}/                    # Stage outputs + manifest + artifact index
├── tests/
│   ├── unit/                            # +26 new test files
│   ├── integration/                     # +7 new test files
│   ├── regression/                      # + schema contract guards
│   └── data/fixtures/                   # +6+ new fixture files
└── docs/implementation/
    └── research-plane-mvp.md            # This document
```

---

## 9. Dependencies & New Packages

### New Dependencies for Research Plane

```toml
# Added to pyproject.toml [project] dependencies
dependencies = [
    # ... existing foundation + data plane dependencies ...
    "numpy>=1.24",             # Vectorised feature computation + metrics
    "pandas>=2.0",             # DataFrame operations for vec backtester + reports
]
```

### Optional / Dev Dependencies

```toml
[project.optional-dependencies]
dev = [
    # ... existing ...
    "polars>=0.20",            # Optional: fast DataFrame alternative for large-scale sweeps
    "matplotlib>=3.7",         # Optional: equity curve plots for interactive research
]
```

### Design Decision: NumPy/Pandas vs. Pure PyArrow

The feature engine and vectorized backtester use **NumPy + Pandas** for computation because:

1. PyArrow compute kernels lack rolling-window aggregations needed for features
2. Pandas provides intuitive DataFrame semantics for cross-sectional operations
3. NumPy is the standard for numerical metrics (Sharpe, Brier, calibration)
4. Data interchange: `pa.Table.to_pandas()` / `pa.Table.from_pandas()` is zero-copy where possible

Storage remains **PyArrow/Parquet** throughout. Conversion happens at computation boundaries only.

---

## 10. Operational Runbook Stubs

### Building a Gold Dataset

```bash
# Build from silver data for a specific time window
python -m apps.research.main build-dataset \
    --name "my_research_set" \
    --start 2026-01-01 \
    --end 2026-03-01 \
    --venues kalshi polymarket \
    --event-types trades ohlcv \
    --require-quality

# List available datasets
python -m apps.research.main list-datasets
```

### Computing Features

```bash
# Compute all registered features on a gold dataset
python -m apps.research.main build-features \
    --dataset my_research_set \
    --feature-set "pm_features_v1"

# Compute specific features only
python -m apps.research.main build-features \
    --dataset my_research_set \
    --feature-set "momentum_only" \
    --features implied_prob_momentum prob_acceleration
```

### Running Backtests

```bash
# Event-driven backtest
python -m apps.research.main backtest \
    --strategy apps.research.strategies.probability_momentum.ProbabilityMomentumStrategy \
    --dataset my_research_set \
    --features pm_features_v1 \
    --engine event \
    --initial-cash 10000 \
    --fee-bps 10 \
    --slippage-bps 5

# Vectorized backtest
python -m apps.research.main backtest \
    --strategy apps.research.strategies.mean_reversion.MeanReversionStrategy \
    --dataset my_research_set \
    --features pm_features_v1 \
    --engine vec
```

### Evaluating & Comparing

```bash
# Evaluate a single backtest
python -m apps.research.main evaluate <backtest_id>

# Compare multiple backtests side-by-side
python -m apps.research.main report <backtest_id_1> <backtest_id_2> --format table
```

### Optimization Workflow

```bash
# Run parameter optimization from config
python -m apps.research.main optimize \
    --config config/research/optimize/momentum_grid.yaml \
    --primary-metric sharpe_ratio

# Machine-readable output for automation
python -m apps.research.main optimize \
    --config config/research/optimize/momentum_grid.yaml \
    --format json
```

Operational note:
- Every command should write `data/runs/{run_id}/manifest.json` and `artifacts.json`.

---

## 11. Future Microstructure Extension (Tick-Resolution)

This remains forward-looking until the corresponding microstructure capabilities are implemented and folded into the main R1-R6 sections.

Estimated additional effort: 80-140 hours.

### 11.1 Scope Delta vs Base R1-R6

| Area | Base MVP | Extension Requirement |
|---|---|---|
| Feature set | 7 PM-specific features | Add microprice, OFI family, cancel/trade intensities, spread-state, simplex residual, queue EV proxies |
| Execution simulator | Market/limit fill + slippage | Add latency, queue rank, partial fills, queue depletion and cancellation-ahead modeling |
| Evaluation | Financial + PM metrics | Add microstructure execution metrics (spread capture, adverse selection, slippage-to-edge, fill ratio) |
| CLI | Basic backtest/evaluate flags | Add microstructure config flags and run profile |

### 11.2 R1 Extension: Tick-Research Dataset Profile

Add an explicit dataset profile for microstructure research:

```python
class DatasetConfig(BaseModel):
    # Existing fields...
    profile: Literal["standard", "microstructure"] = "standard"
    event_types: list[str] = ["trades", "ohlcv"]  # existing default
```

Profile behavior:

- `profile="microstructure"` enforces `event_types` includes `books`.
- Use event-time alignment windows suitable for short horizon labels (for example 1s, 5s, 10s).
- Persist derived state keys required downstream:
  - `best_bid`, `best_ask`, `spread_ticks`, `mid`, `microprice`
  - optional `outcome_group_id` for simplex constraints

Suggested file deltas:

- `libs/core/alpha_core/research/dataset_builder.py`
- `libs/core/alpha_core/research/dataset.py`
- `tests/unit/test_dataset_builder.py` (microstructure profile cases)

### 11.3 R2 Extension: Microstructure Feature Library

Add a dedicated module:

- `libs/core/alpha_core/features/microstructure.py`

Minimum feature set:

- `L1Imbalance`
- `Microprice`
- `OFI` (L1 baseline)
- `MultiLevelOFI` (L1-L3 weighted)
- `DecayWeightedOFI`
- `CancelRate`
- `TradeIntensity`
- `SpreadState`
- `SimplexResidual`
- `QueueFillProbProxy`
- `PostFillAdverseMove` label helper

Modeling baseline for short-horizon drift:

`E[delta_p_(t->t+H) | state_t] = beta1 * I1 + beta2 * OFI + beta3 * cancel_rate + beta4 * trade_intensity + ...`

Suggested tests:

- `tests/unit/test_microstructure_features.py`
- `tests/integration/test_microstructure_feature_pipeline.py`

### 11.4 R3 Extension: Execution and Queue Dynamics

Extend execution contracts to support queue and latency effects.

```python
class SimulatedFill(BaseModel):
    # Existing fields...
    partial: bool = False
    remaining_size: Decimal = Decimal("0")
    queue_rank_estimate: int | None = None
    fill_probability: float | None = None
    latency_ms: float = 0.0
```

Add models:

- `LatencyModel` ABC with at least `FixedLatencyModel` and `EmpiricalLatencyModel`
- `QueueFillModel` with:
  - market-order arrival intensity
  - cancellation-ahead intensity
  - queue depletion process

Extend config:

```python
class EventBacktestConfig(BaseModel):
    # Existing fields...
    latency_model: str = "fixed"
    latency_params: dict[str, Any] = {"ms": 50}
    queue_model: str = "basic_poisson"
    queue_params: dict[str, Any] = {}
    inventory_gamma: Decimal = Decimal("0.0")
```

Suggested tests:

- `tests/unit/test_latency_models.py`
- `tests/unit/test_queue_fill_model.py`
- extend `tests/unit/test_execution_simulator.py` for partial fill and queue rank cases

### 11.5 R4 Extension: Strategy Templates for Mechanism Testing

Add strategy templates:

- `apps/research/strategies/queue_market_maker.py`
- `apps/research/strategies/ofi_taker.py`
- `apps/research/strategies/queue_arb.py`
- `apps/research/strategies/simplex_arb.py`
- `apps/research/strategies/hawkes_hybrid.py`

Sweep requirements:

- Include latency and queue parameters in parameter grids.
- Rank robust regions, not only best single point.
- Record microstructure diagnostics per parameter row.

### 11.6 R5 Extension: Microstructure Evaluation Metrics

Add `MicrostructureMetrics`:

```python
class MicrostructureMetrics(BaseModel):
    spread_capture_bps: float
    adverse_selection_bps: float
    fill_ratio: float
    partial_fill_ratio: float
    slippage_to_gross_edge_ratio: float
    avg_queue_rank_on_fill: float | None
    fee_edge_breakdown: dict[str, float]  # maker/taker/per_contract/resolution
    impact_decay_half_life_seconds: float | None
```

Wire into evaluation report:

```python
class EvaluationReport(BaseModel):
    # Existing fields...
    microstructure: MicrostructureMetrics | None = None
```

Suggested tests:

- `tests/unit/test_microstructure_metrics.py`
- extend `tests/unit/test_evaluator.py` for report merge behavior

### 11.7 R6 Extension: CLI Surface for Microstructure Runs

Extend backtest command flags:

- `--maker-fee-bps`
- `--taker-fee-bps`
- `--per-contract-fee`
- `--resolution-fee-bps`
- `--latency-model` / `--latency-ms`
- `--queue-model`
- `--inventory-gamma`
- `--microstructure-profile`

Add convenience command:

- `run-microstructure-pipeline`:
  - build dataset (microstructure profile)
  - build microstructure feature set
  - run strategy
  - evaluate with microstructure metrics

Suggested tests:

- extend `tests/unit/test_research_cli.py` for new options
- add `tests/integration/test_microstructure_pipeline_e2e.py`

### 11.8 Acceptance Criteria

This future section is complete when all are true:

- [ ] Microstructure dataset profile produces book-aware tick panels.
- [ ] Feature registry includes OFI/microprice/intensity/spread-state/simplex residual features.
- [ ] Execution simulator supports latency, queue rank, and partial fills.
- [ ] At least 3 mechanism strategies run end-to-end with realistic fees.
- [ ] Evaluation report includes microstructure metrics.
- [ ] CLI exposes microstructure run configuration without code edits.
- [ ] Extension tests are green with no regressions in base R1-R6 tests.

---

## 12. Future Research Ergonomics Extension (March 2026, Iteration 2)

This remains forward-looking until the corresponding research-session and experiment-governance capabilities are implemented and folded into the main R1-R6 sections.

Reference documents:
- `README.LEAN_ADOPTION.md`
- `docs/implementation/lean-adoption-issue-backlog.md`

### 12.1 R1 Extension B: ResearchSession Contract (Low-Churn for In-Flight R1)

Because R1 is already in progress, add a thin session wrapper instead of reworking dataset internals:

```python
class ResearchSession(BaseModel):
    session_id: str
    run_id: str
    dataset_id: str | None = None
    feature_set_version: str | None = None
    strategy_id: str | None = None
    notes: str | None = None
```

Usage rule:
- `DatasetBuilder.build(...)` updates `dataset_id`.
- downstream runners attach feature/backtest/eval IDs to the same session lineage.

This keeps R1 code stable while enabling cross-command continuity.

### 12.2 R2/R3 Extension: Factor-Pack Registry and Strategy Recipe Manifest

Add two contracts to improve module reuse:

- `FactorPackManifest`: `pack_id`, `version`, `dependencies`, `output_schema`
- `StrategyRecipeManifest`: references factor pack(s), strategy parameters, risk template, execution template

Outcome:
- CLI commands can consume `--factor-pack` and `--strategy-recipe` IDs rather than hardcoded notebook pipelines.

### 12.3 R4/R5 Extension: Experiment Catalog + Promotion Gates

For each optimize/backtest/evaluate run, register a catalog row:

- identity: `run_id`, `session_id`, `dataset_id`, `strategy_version`
- metrics: objective + key risk metrics
- status: `candidate`, `needs_review`, `approved_for_paper`, `rejected`
- reviewer metadata: `reviewed_by`, `reviewed_at_utc`, `reason`

Promotion gate example:
- block `approved_for_paper` unless liquidity threshold, max drawdown threshold, and min trade-count threshold are all satisfied.

### 12.4 R6 Extension: CLI Ergonomics for Research Velocity

Add optional CLI aliases over existing commands:

- `research session start`
- `research session status`
- `research catalog list --status candidate`
- `research promote --run-id ... --to approved_for_paper`

All aliases should still emit standard run manifests and reuse existing runners.

### 12.5 Acceptance Gates (Iteration 2)

This future section is complete when:

- [ ] `ResearchSession` schema is implemented and linked across R1-R5 artifacts.
- [ ] Factor-pack and strategy-recipe manifests are versioned and validated by tests.
- [ ] Optimize/evaluate runs register into a queryable experiment catalog.
- [ ] Promotion workflow enforces objective/risk gates before paper/live promotion.
- [ ] CLI aliases improve ergonomics without introducing a second artifact contract.

---

## Stage Transition: What Comes Next

After Research Plane MVP, the **Live Plane MVP** builds directly on top:

| Research Plane Provides | Live Plane Consumes |
|---|---|
| Validated strategies (backtest reports) | Deploy proven strategies to paper/live trading |
| Feature computation code (`alpha_core.features`) | Real-time feature service reuses same feature classes |
| Execution models (`alpha_core.execution`) | Live execution gateway extends simulator models |
| Portfolio tracker (`alpha_core.portfolio`) | Live position + PnL tracking reuses same tracker |
| Evaluation metrics | Real-time performance monitoring uses same metric suite |
| Strategy ABC (`Strategy`, `VecStrategy`) | Live strategies implement the same interface |

The Live Plane MVP will add: paper trading gateway, real-time feature service, signal generation service, risk gates (max position, max loss, kill-switch), execution routing via `pmxt.create_order`, and a live position dashboard.
