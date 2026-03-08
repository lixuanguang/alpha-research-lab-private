# Alpha Research Lab

> **Institutional-grade alpha research platform for prediction markets**  
> **Stack:** Python 3.11 · `pmxt` · Pydantic v2 · PyArrow/Parquet · DuckDB  
> **Baseline Reference:** *Institutional-Grade Multi-Asset Alpha Research Implementation Framework*

---

## Project Status

| Stage | Status | Tests | Docs |
|---|---|---|---|
| **Foundation** | **Complete (F1-F6 closed; all validated baseline work folded into implementation steps)** | Covered by repo-wide quality gates | [Foundation Plan](docs/implementation/foundation-stage.md) |
| **Data Plane MVP** | **Complete (D1-D6 closed; section 11 integrated)** | Covered by repo-wide quality gates | [Data Plane Plan](docs/implementation/data-plane-mvp.md) |
| **Research Plane MVP** (R1–R6) | **In Progress (dataset/feature/backtest/evaluate/report/artifact-store/optimize workflows are landed; richer PM-native execution, vectorized parity, and evaluation hardening remain open)** | Covered by repo-wide quality gates | [Research Plane Plan](docs/implementation/research-plane-mvp.md) |
| Live Plane MVP | Planned | — | — |
| Observability Baseline | Planned | — | — |
| Robustness Hardening | Planned | — | — |

### Possible Extensions

| Extension | Status | Tests | Docs |
|---|---|---|---|
| Research Ergonomics Extension | **Partially delivered (sessions, catalog, promotion gates, factor packs, and strategy recipes are landed; remaining work is mostly doc folding and workflow hardening)** | Covered by repo-wide quality gates | [Research Plane Plan](docs/implementation/research-plane-mvp.md) |
| Data Plane -> Research Handoff Contract | **Complete (lineage bridge fields, `dataset_ready` gating, handoff manifests, ingestion artifact compatibility, and handoff-driven dataset builds are landed)** | Focused unit/integration coverage for sections 12.1-12.4 | [Data Plane Plan](docs/implementation/data-plane-mvp.md) |
| PM-Native Backtester Enhancement Plan (`B0`-`B4`) | Planned | — | [README Backtester Plan](README.md#backtester-enhancement-plan-zipline-informed-pm-native) |
| Research Microstructure Extension (Tick-Resolution) | Planned | — | [Research Plane Extension](docs/implementation/research-plane-mvp.md#11-future-microstructure-extension-tick-resolution) |
| Macro/OpenBB Ingestion (`M0`-`M3`) | Optional / Planned | — | [README Macro Plan](README.md#macro-data-ingestion-plan-openbb-hybrid) |

**Quality gates (as of March 8, 2026):**
- `ruff check .` — 0 errors
- `mypy libs/core apps tests --strict` — 0 errors
- `pytest tests/ -q` — 2083 passed, 10 skipped

**Maintenance updates (March 1, 2026):**
- Data-collector connector internals were decomposed into focused modules:
  - `apps/data_collector/connectors/_types.py`
  - `apps/data_collector/connectors/_lifecycle.py`
  - `apps/data_collector/connectors/_polling.py`
  - `apps/data_collector/connectors/_streaming.py`
  - Call sites now import connector internals directly; compatibility facade removed
- Config loading internals were decomposed for SRP:
  - `libs/core/alpha_core/config/_merge.py`
  - `libs/core/alpha_core/config/_overrides.py`
  - `libs/core/alpha_core/config/loader.py` remains the public entrypoint

---

## Quick Start

```bash
conda activate py311
cd alpha-research-lab-private
pip install -e ".[dev]"
pre-commit install
python scripts/validate_env.py
pytest tests/ -v --cov=alpha_core --cov=apps/data_collector
```

---

## Research CLI Command Chain

The research plane exposes a first-class CLI pipeline. All commands are run from the repo root with `conda activate py311`.

| Step | Command | Key output |
|---|---|---|
| 1 | `python -m apps.research.main build-dataset --storage-root data/ --execute` | `data/gold/datasets/<dataset_id>/trades.parquet` |
| 2 | `python -m apps.research.main build-features --dataset-id <id> --storage-root data/ --execute` | `data/gold/runs/<run_id>/features.parquet` |
| 3 | `python -m apps.research.main backtest --dataset-id <id> --strategy-id <id> --parent-run-id <feature_run_id> --storage-root data/ --execute` | `trades.parquet`, `equity.parquet`, `run_manifest.json` |
| 4 | `python -m apps.research.main evaluate --backtest-run-id <id> --storage-root data/ --execute` | `metrics.json`, `metrics.parquet` |
| 5 | `python -m apps.research.main report --evaluate-run-id <id> --storage-root data/ --execute` | `report.json` |
| 6 | `python -m apps.research.main optimize --config config/research/optimize.example.yaml --storage-root data/ --execute` | `trial_registry.jsonl`, `trial_registry.parquet`, `leaderboard.json`, `best_manifest.json` |

Run the full smoke path against fixture data (matches CI):

```bash
pytest -m smoke tests/integration/test_research_pipeline_e2e.py -v
```

Each stage writes a `run_manifest.json` under `data/gold/runs/<run_id>/` linking the run to its parent for full lineage traceability.

---

## Architecture

Three entrypoints on a shared core, specialised for prediction markets via [`pmxt`](https://github.com/pmxt-dev/pmxt):

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

### Supported Venues (via pmxt)

Kalshi · KalshiDemo · Polymarket · Limitless · Baozi · Myriad · Probable

---

## Repository Layout

```
├── libs/core/alpha_core/        # Shared core library
│   ├── adapters/                # Venue connectivity (pmxt adapter)
│   ├── config/                  # Hierarchical YAML + env config
│   ├── events/                  # Canonical market data models
│   ├── instruments/             # Market master & symbology
│   ├── storage/                 # Parquet writer/reader + DuckDB
│   └── utils/                   # Time, IDs
├── apps/
│   ├── data_collector/          # Entrypoint A — data ingestion
│   ├── live_system/             # Entrypoint B — live trading
│   └── research/                # Entrypoint C — backtesting
├── config/                      # YAML configuration files
├── tests/                       # Unit + integration tests
├── docs/                        # ADRs + implementation plans
├── infra/                       # Docker, future K8s
└── scripts/                     # Bootstrap & validation
```

---

## Implementation Stage Plans

Completed follow-on contracts are folded into the relevant stage plans below. Separate reference docs now cover only still-open or cross-stage work that has not yet been promoted into the main implementation structure.

| Document | Scope |
|---|---|
| [Foundation Stage](docs/implementation/foundation-stage.md) | Repo scaffold, canonical models, instrument master, config, storage, CI |
| [Data Plane MVP](docs/implementation/data-plane-mvp.md) | Live connectors, streaming/batch ingestion, data quality, backfill tools |
| [Research Plane MVP](docs/implementation/research-plane-mvp.md) | Dataset builder, feature engineering, backtester, PM-specific evaluation |
| [Lean Adoption Guide](README.LEAN_ADOPTION.md) | Reference for delivered Lean-derived contracts and remaining cross-stage hardening work |
| [Lean Adoption Issue Backlog](docs/implementation/lean-adoption-issue-backlog.md) | Historical issue templates and dependency order for `LA-001` through `LA-022` (all delivered) |

### Status Snapshot

Closed:
- Foundation Stage (`F1`-`F6`)
- Data Plane MVP (`D1`-`D6`)
- Data Plane -> Research handoff contract (`§12.1`-`§12.4`)
- Lean adoption backlog (`LA-001` through `LA-022`)
- Research CLI baseline: `build-dataset`, `build-features`, `backtest`, `evaluate`, `report`, `optimize`
- Research governance baseline: `session`, `catalog`, `promote`
- Filesystem `ArtifactStore`, optimize trial registry, runtime profiles, and acceleration parity boundary

Still open:
- Research Plane MVP hardening: richer execution simulation, vectorized fast path, deeper PM-native evaluation metrics, and example strategies
- Cross-stage contract cleanup: harmonized materialized CLI payloads, optional `run-pipeline` decision, broader `ArtifactStore` reuse in live/runtime
- PM-native backtester enhancement plan (`B0`-`B4`)
- Live Plane MVP
- Observability Baseline
- Robustness Hardening
- Macro/OpenBB ingestion plan (`M0`-`M3`) if strategy-driven

### Active Delivery Order (Recommended)

1. Finish the open **Research Plane MVP** gaps: richer execution simulation, vectorized fast path, deeper PM-native evaluation metrics, and example strategies.
2. Clean up remaining **cross-stage contracts**: harmonize materialized research CLI payloads, decide on the optional `run-pipeline` alias, and extend `ArtifactStore` reuse into live/runtime paths.
3. Apply the **PM-native backtester enhancement plan** (`B0`-`B4` below): scheduling/calendars, pluggable cost models, deterministic bundle snapshots, metrics-set registry, and factor-graph ergonomics.
4. Build **Live Plane MVP** on top of the validated research contracts: paper/live-safe routing, real-time feature/signal services, and production risk gates.
5. Add the **Observability Baseline**: telemetry, dashboards, alerts, and operator runbooks for the now-meaningful live/runtime surface.
6. Finish **Robustness Hardening**: purged/embargoed CV, multiple-testing controls, survivorship/bias enforcement, and research validation workflows.
7. Treat **macro/OpenBB ingestion** (`M0`-`M3` below) as an optional, thesis-driven extension unless it is directly required by the current alpha roadmap.

## Macro Data Ingestion Plan (OpenBB Hybrid)

Decision:
- Use OpenBB first for macro/public data sources (`FRED`, `BLS`, `IMF`, `Federal Reserve` data including FOMC-related series/calendars where available).
- Keep Alpha Research Lab contracts as the system boundary.
- Route all provider calls through internal adapters so OpenBB is replaceable.

Why this plan:
- Faster time-to-data for research.
- Lower connector maintenance burden for public datasets.
- Preserves production safety by keeping lineage, quality gates, and canonical schemas internal.

### Scope

In scope:
- Daily/intraday macro enrichment for research datasets.
- Historical pulls via OpenBB provider extensions.
- Canonical storage in bronze/silver with lineage + manifests.

Out of scope:
- Replacing `pmxt` venue connectors.
- Routing live trading decisions directly from unvalidated macro provider payloads.

### Implementation Phases

Phase M0 (Contracts + config, 1-2 days):
- Add provider-agnostic macro connector contract.
- Add config for enabled macro providers and datasets.
- Define canonical macro event schema + partition convention.

Suggested file targets:
- `libs/core/alpha_core/adapters/macro_base.py`
- `libs/core/alpha_core/events/models.py` (macro event model additions)
- `libs/core/alpha_core/storage/conventions.py` (macro dataset schema/partitions)
- `config/default.yaml` + `config/environments/*.yaml` (provider toggles, cadence)

Phase M1 (OpenBB adapter + ingestion, 2-4 days):
- Implement OpenBB-backed macro adapter wrappers for:
  - `fred`
  - `bls`
  - `imf`
  - `federal_reserve`
- Add collector command(s) for macro sync windows.
- Persist raw payloads to bronze, normalized macro records to silver.

Suggested file targets:
- `libs/core/alpha_core/adapters/openbb_macro.py`
- `apps/data_collector/connectors/macro_poller.py`
- `apps/data_collector/main.py` (add `macro-sync` command)
- `libs/core/alpha_core/storage/bronze_writer.py` (macro payload support)
- `libs/core/alpha_core/storage/parquet_writer.py` / `parquet_reader.py`

Phase M2 (Quality + lineage + research handoff, 2-3 days):
- Add macro quality suite (nulls, timestamp monotonicity, release-lag sanity, revision tracking fields).
- Emit lineage links and dataset-ready handoff manifests for macro windows.
- Join macro artifacts into research dataset builder via run manifests.

Suggested file targets:
- `libs/core/alpha_core/quality/suites/macro_quality.py`
- `libs/core/alpha_core/storage/lineage.py`
- `libs/core/alpha_core/research/dataset_builder.py`
- `docs/implementation/data-plane-mvp.md` / `research-plane-mvp.md` (handoff notes)

Phase M3 (Selective first-party fallback, only if needed):
- Implement direct, first-party connectors only for critical series that need stricter SLA/control.
- Keep adapter signatures identical so downstream code is unchanged.

### Acceptance Criteria

- `macro-sync` can fetch configured FRED/BLS/IMF/Fed datasets into bronze/silver deterministically.
- Macro records pass quality suites and emit lineage metadata.
- Research dataset build can include macro features without bypassing run manifests.
- Provider adapter can be swapped without changing research/backtest CLI contracts.

### Risks and Controls

- Provider/API changes:
  - Control: adapter boundary + contract tests.
- Public dataset revisions:
  - Control: include `release_ts`, `effective_ts`, and revision metadata where available.
- Licensing and operational constraints:
  - Control: review provider terms before production promotion; keep fallback path available.

## Backtester Enhancement Plan (Zipline-Informed, PM-Native)

Decision:
- Do not replace the core backtester with Zipline.
- Port specific proven patterns from Zipline where they improve ergonomics and reproducibility.
- Keep prediction-market microstructure, resolution logic, and PM metrics in native modules.

### Why Not Full Zipline Adoption

- Zipline is strongest for equity/futures bar workflows.
- Current roadmap requires PM-specific execution behavior, resolution lifecycle handling, and microstructure diagnostics.
- Existing stage plans already target event-driven + vectorized PM engines with shared contracts.

### What to Port from Zipline

- Scheduling rules (`schedule_function`-style time/date rules).
- Trading-calendar abstraction and custom calendar registration.
- Commission/slippage model interfaces and model registry.
- Bundle-style deterministic data ingestion snapshots and version tags.
- Metrics-set registry (selectable report packs, including lightweight dev mode).
- Factor graph ergonomics for feature composition (`pipeline`-like execution graph).

### What to Keep Native

- Binary/multi-outcome market lifecycle and settlement rules.
- Queue/latency/partial-fill simulation for PM microstructure.
- PM evaluation metrics: Brier, log-loss, calibration, resolution decomposition.
- Research run manifests and artifact lineage conventions in `data/runs/{run_id}/...`.

### Implementation Phases

Phase B0 (Interface extraction, 1-2 days):
- Define scheduler, calendar, slippage, commission, metrics-registry interfaces.
- Keep interfaces independent from any Zipline runtime internals.

Suggested file targets:
- `libs/core/alpha_core/research/scheduling.py`
- `libs/core/alpha_core/research/calendars.py`
- `libs/core/alpha_core/execution/cost_models.py`
- `libs/core/alpha_core/evaluation/metrics_registry.py`

Phase B1 (Scheduling + calendars, 2-4 days):
- Add rule-based scheduling primitives for research/backtest tasks.
- Add calendar adapters for deterministic session boundaries and event alignment.

Suggested file targets:
- `apps/research/backtester/engine.py`
- `apps/research/main.py`
- `libs/core/alpha_core/research/calendars.py`
- `tests/unit/test_scheduling_rules.py`

Phase B2 (Cost model registry, 2-3 days):
- Implement pluggable commission and slippage models.
- Add config-driven model selection and deterministic defaults.

Suggested file targets:
- `libs/core/alpha_core/execution/simulator.py`
- `libs/core/alpha_core/execution/cost_models.py`
- `config/research/backtest.example.yaml`
- `tests/unit/test_cost_models.py`

Phase B3 (Bundle snapshots + metrics sets, 3-5 days):
- Add bundle-like data snapshot metadata for reproducible runs.
- Add named metrics sets (`default`, `pm_core`, `microstructure`, `minimal`).

Suggested file targets:
- `libs/core/alpha_core/research/manifest.py`
- `libs/core/alpha_core/research/dataset_builder.py`
- `libs/core/alpha_core/evaluation/metrics_registry.py`
- `tests/regression/test_metrics_report_schema.py`

Phase B4 (Factor-graph ergonomics, 3-5 days):
- Add graph-based feature/factor composition APIs while retaining existing feature registry.
- Allow strategy recipes to reference factor graphs by version.

Suggested file targets:
- `libs/core/alpha_core/features/registry.py`
- `libs/core/alpha_core/features/factor_pack.py`
- `libs/core/alpha_core/research/strategy_recipe.py`
- `tests/unit/test_factor_pack_registry.py`

### Acceptance Criteria

- Backtester keeps PM-specific correctness while gaining reusable scheduling/cost/calendar primitives.
- New abstractions are selectable by config and covered by unit/integration tests.
- Re-running same dataset/config/seed produces stable results within defined tolerance.
- CLI contracts and run manifests remain backward compatible.

## Research Guides

| Guide | Scope |
|---|---|
| [Research Signals Guide](docs/guides/research-signals-guide.md) | Signal lifecycle, PM signal taxonomy, stage-by-stage microstructure workflow |
| [Notebook to Modules/CLI Migration Guide](docs/guides/notebook-to-modules-cli-migration-guide.md) | How to promote stable notebook logic into tested modules and CLI pipelines |
| [Gold Dataset Collection And Streaming Guide](docs/guides/gold-dataset-collection-streaming-guide.md) | Current-architecture runbook for bronze/silver collection and practical gold materialization patterns |

---

## Conventions

| Aspect | Standard |
|---|---|
| Formatting | `ruff format` (100 char lines) |
| Linting | `ruff check` — E/F/I/W/UP/RUF |
| Types | `mypy --strict` on `libs/` and `apps/` |
| Models | Pydantic v2, `Decimal` for prices, UTC `datetime` always |
| Tests | `pytest`, no network calls in CI, fixtures in `tests/data/` |
| Branching | `main` ← `feature/...`, conventional commits |
| Versioning | `setuptools_scm` from Git tags |
