# Alpha Research Lab

> **Institutional-grade alpha research platform for prediction markets**  
> **Stack:** Python 3.11 · `pmxt` · Pydantic v2 · PyArrow/Parquet · DuckDB  
> **Baseline Reference:** *Institutional-Grade Multi-Asset Alpha Research Implementation Framework*

---

## Project Status

| Stage | Status | Tests | Docs |
|---|---|---|---|
| **Foundation** (F1–F6 + 11.x addendum) | **Complete (closed)** | Covered by repo-wide quality gates | [Foundation Plan](docs/implementation/foundation-stage.md) |
| **Data Plane MVP** (D1–D6) | **Complete (D1–D6 closed)** | 534 passed, 8 skipped | [Data Plane Plan](docs/implementation/data-plane-mvp.md) |
| **Research Plane MVP** (R1–R6) | **Next** | — | [Research Plane Plan](docs/implementation/research-plane-mvp.md) |
| Live Plane MVP | Planned | — | — |
| Observability Baseline | Planned | — | — |
| Robustness Hardening | Planned | — | — |

**Quality gates (as of March 2, 2026):**
- `ruff check .` — 0 errors
- `mypy libs/ apps/ --strict` — 0 errors
- `pytest tests/` — 534 passed, 8 skipped in ~3.9s

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

| Document | Scope |
|---|---|
| [Foundation Stage](docs/implementation/foundation-stage.md) | Repo scaffold, canonical models, instrument master, config, storage, CI |
| [Data Plane MVP](docs/implementation/data-plane-mvp.md) | Live connectors, streaming/batch ingestion, data quality, backfill tools |
| [Research Plane MVP](docs/implementation/research-plane-mvp.md) | Dataset builder, feature engineering, backtester, PM-specific evaluation |

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
