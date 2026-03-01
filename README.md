# Alpha Research Lab

> **Institutional-grade alpha research platform for prediction markets**  
> **Stack:** Python 3.11 · `pmxt` · Pydantic v2 · PyArrow/Parquet · DuckDB  
> **Baseline Reference:** *Institutional-Grade Multi-Asset Alpha Research Implementation Framework*

---

## Project Status

| Stage | Status | Tests | Docs |
|---|---|---|---|
| **Foundation** (F1–F6) | **Complete (closed)** | Covered by repo-wide quality gates | [Foundation Plan](docs/implementation/foundation-stage.md) |
| **Data Plane MVP** (D1–D6) | **Complete (D1–D6 closed)** | 451 passing, 8 skipped | [Data Plane Plan](docs/implementation/data-plane-mvp.md) |
| Research Plane MVP | Planned | — | — |
| Live Plane MVP | Planned | — | — |
| Observability Baseline | Planned | — | — |
| Robustness Hardening | Planned | — | — |

**Quality gates (as of March 1, 2026):**
- `ruff check .` — 0 errors
- `mypy libs/ apps/ --strict` — passing
- `pytest -q` — 451 passed, 8 skipped in ~3.7s
- Test coverage: 92.18% (`libs/core/alpha_core` + `apps/data_collector`)

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
