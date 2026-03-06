# Lean Lessons Adoption Guide for Alpha Research Lab

> Last updated: March 6, 2026
> Scope: Practical implementation reference for Lean-derived patterns that are not yet fully folded into the stage implementation plans.
> Issue backlog: `docs/implementation/lean-adoption-issue-backlog.md`

---

## 1. Objective

Use Lean's best architectural ideas to improve:

1. **Ease of alpha research development** (faster idea -> test -> iterate loop)
2. **Productionization** (same strategy logic from research to backtest to live)

This guide focuses on patterns that fit your current codebase and roadmap, not a full Lean clone.

Several Foundation and Data Plane contracts from this guide are already documented directly in the stage plans as first-class sections. This file should now be treated as a forward-looking reference for the remaining cross-stage patterns and backlog sequencing.

## 1.1 Current Role of This Guide

- Treat `docs/implementation/foundation-stage.md`, `docs/implementation/data-plane-mvp.md`, and `docs/implementation/research-plane-mvp.md` as the primary implementation sources of truth.
- Use this guide for patterns that are still open, still cross-stage, or still too early to promote into one stage plan without creating duplication.
- When a contract is implemented and validated, it should be folded into the relevant stage plan and removed as a standalone dependency here.

---

## 2. Current Baseline in This Repo

As of today:

- Data plane is operational and tested (`apps/data_collector`, `alpha_core/storage`, `alpha_core/quality`).
- Canonical PM event modeling is strict and reproducible (`alpha_core/events/models.py`).
- Ingestion lineage exists (`alpha_core/storage/lineage.py`).
- Research and live entrypoints now expose scaffolded Click command groups (`apps/research/main.py`, `apps/live_system/main.py`), but the full production research/live workflows are still in progress.
- Gold dataset materialization is now available through first-class research modules and CLI scaffolding, with broader feature/backtest/runtime coverage still planned.

Implication: the largest leverage is in **research/live orchestration and shared strategy contracts**.

---

## 3. What to Bring Over from Lean (Prioritized)

### 3.1 Strategy Framework Contracts (Highest ROI)

**Lean lesson:** Separate strategy concerns into pluggable modules instead of one monolithic algorithm script.

**Bring over:**
- `UniverseModel`
- `AlphaModel`
- `PortfolioConstructionModel`
- `RiskModel`
- `ExecutionModel`

**Why this helps you:**
- Researchers can swap one model (for example risk) without rewriting backtest/live orchestration.
- Same strategy graph can run in notebook/backtest/live contexts.

---

### 3.2 Unified Run Context and Artifact Contract

**Lean lesson:** Every run carries strong metadata and standardized outputs.

**Bring over:**
- `RunContext` object passed through dataset/feature/backtest/eval/live stages
- Standard run manifest fields:
  - `run_id`
  - `run_type` (`research`, `backtest`, `optimize`, `live`)
  - `dataset_id`
  - `feature_set_version`
  - `strategy_version`
  - `config_hash`
  - `git_commit`
  - `started_at_utc`, `completed_at_utc`

**Why this helps you:**
- Full reproducibility and traceability.
- Faster postmortem/debug loops.

---

### 3.3 First-Class Research CLI Surface

**Lean lesson:** CLI is the main interface for repeatable workflows.

**Bring over:**
- Implement `apps/research/main.py` group commands:
  - `build-dataset`
  - `build-features`
  - `backtest`
  - `evaluate`
  - `report`
  - optional `run-pipeline`

**Why this helps you:**
- Replaces notebook-only flows with deterministic commands.
- Enables CI/nightly automation.

---

### 3.4 Optimize Runner as a First-Class Capability

**Lean lesson:** Parameter search should be a built-in workflow, not ad-hoc notebook loops.

**Bring over:**
- `optimize` command with:
  - search space declaration
  - objective metric
  - constraints (min trades, max drawdown, etc.)
  - persisted trial registry and leaderboard

**Why this helps you:**
- Faster exploration with better experiment hygiene.

---

### 3.5 Lightweight Object Store for Shared Artifacts

**Lean lesson:** Research/backtest/live should share persisted objects through one abstraction.

**Bring over:**
- `ArtifactStore` interface over local filesystem first
- Store:
  - feature caches
  - calibration objects
  - strategy params
  - optimization outputs
  - evaluation reports

**Why this helps you:**
- Eliminates fragile handoffs between notebook files and runtime scripts.

---

### 3.6 Pre-Trade Validation and Execution Guardrails

**Lean lesson:** Orders pass explicit brokerage/risk checks before execution.

**Bring over:**
- `PreTradeValidator` for PM constraints:
  - market lifecycle active check
  - max notional / exposure guard
  - fee/slippage estimate sanity
  - venue capability checks
- `OrderIntent -> ValidatedOrder -> ExecutionReport` flow

**Why this helps you:**
- Reduces live trading failure modes and unsafe order paths.

---

## 4. Repository Implementation Blueprint

### 4.1 New Modules to Add

```text
libs/core/alpha_core/
  strategy_framework/
    __init__.py
    models.py
    interfaces.py
    engine.py
  research/
    run_context.py
    manifest.py
    artifact_store.py
    dataset_builder.py
    feature_runner.py
    backtest_runner.py
    evaluate_runner.py
  execution/
    pretrade.py
    order_models.py
    simulator.py

apps/research/
  main.py
  commands/
    build_dataset.py
    build_features.py
    backtest.py
    evaluate.py
    report.py
    optimize.py

apps/live_system/
  main.py
  runtime.py
  order_router.py
```

### 4.2 Existing Modules to Extend

- `libs/core/alpha_core/storage/lineage.py`
  - keep ingestion lineage as-is, add bridge helpers for research/backtest manifests
- `docs/guides/notebook-to-modules-cli-migration-guide.md`
  - add mandatory mapping to new research CLI commands
- `docs/implementation/research-plane-mvp.md`
  - convert to implementation tracker with completion checkboxes per module

---

## 5. Detailed Build Plan

## Phase P0: Contracts and Metadata (1-2 weeks)

### Tasks

1. Add strategy framework interfaces and core datamodels.
2. Add `RunContext` + run manifest writer.
3. Define artifact directory convention under `data/gold/runs/{run_id}/`.

### Deliverables

- Strongly typed interfaces.
- Every research command emits a manifest JSON.

### Definition of Done

- Unit tests validate model invariants and serialization.
- `pytest` green on added tests.

---

## Phase P1: Research CLI Core (2-3 weeks)

### Tasks

1. Expand the existing `apps/research/main.py` click group into the full research operator surface.
2. Implement:
   - `build-dataset`
   - `build-features`
   - `backtest`
   - `evaluate`
3. Emit machine-readable outputs (`--format json`) and non-zero on failures.

### Deliverables

- Reproducible CLI pipeline for one baseline strategy.

### Definition of Done

- Integration test: silver fixture -> dataset -> features -> backtest -> evaluation.
- Artifacts and manifests written deterministically.

---

## Phase P2: Optimize + Artifact Store (1-2 weeks)

### Tasks

1. Add local `ArtifactStore` abstraction.
2. Add `optimize` command with grid/random search.
3. Persist trial table with:
   - params
   - objective
   - secondary metrics
   - run metadata links

### Deliverables

- Trial leaderboard + best-run manifest.

### Definition of Done

- Re-running same optimize config yields reproducible ranking within expected tolerance.

---

## Phase P3: Live Reuse of Same Contracts (2-3 weeks)

### Tasks

1. Implement live strategy runtime using same framework interfaces as backtest.
2. Add `PreTradeValidator`.
3. Add explicit execution reports with accepted/rejected reason codes.

### Deliverables

- `apps/live_system` moves beyond the current scaffold runtime into a production-grade shared-contract path.
- One paper/live-safe end-to-end path.

### Definition of Done

- Integration test with mocked venue adapter:
  - signal -> order intent -> validation -> simulated fill -> position/PnL update.

---

## Phase P4: Observability and Hardening (ongoing)

### Tasks

1. Add standardized run summaries and health counters.
2. Add regression tests for run manifests and report schema.
3. Add CI job for research CLI smoke pipeline.

### Deliverables

- Stable contracts for automation and reporting.

---

## 6. Interface Contracts (Reference)

## 6.1 Strategy Framework Interfaces

```python
from __future__ import annotations

from typing import Protocol


class UniverseModel(Protocol):
    def select(self, state: "MarketState") -> list[str]: ...


class AlphaModel(Protocol):
    def generate(self, state: "MarketState") -> list["Signal"]: ...


class PortfolioConstructionModel(Protocol):
    def targets(self, signals: list["Signal"], state: "MarketState") -> list["Target"]: ...


class RiskModel(Protocol):
    def apply(self, targets: list["Target"], state: "MarketState") -> list["Target"]: ...


class ExecutionModel(Protocol):
    def create_orders(self, targets: list["Target"], state: "MarketState") -> list["OrderIntent"]: ...
```

## 6.2 Run Manifest Schema (Minimum)

```json
{
  "run_id": "20260302T130000Z_backtest_001",
  "run_type": "backtest",
  "dataset_id": "pm_gold_20260302",
  "feature_set_version": "pm_features_v1",
  "strategy_version": "mom_spread_v2",
  "config_hash": "sha256:...",
  "git_commit": "abc1234",
  "started_at_utc": "2026-03-02T13:00:00Z",
  "completed_at_utc": "2026-03-02T13:05:22Z",
  "artifacts": {
    "features": "data/gold/runs/.../features.parquet",
    "trades": "data/gold/runs/.../trades.parquet",
    "metrics": "data/gold/runs/.../metrics.json"
  }
}
```

---

## 7. Recommended CLI UX

```bash
python -m apps.research.main build-dataset --config config/research/dataset.yaml
python -m apps.research.main build-features --dataset-id pm_gold_20260302 --feature-set pm_v1
python -m apps.research.main backtest --dataset-id pm_gold_20260302 --strategy mom_spread_v2
python -m apps.research.main evaluate --run-id 20260302T130000Z_backtest_001
python -m apps.research.main optimize --config config/research/optimize/mom_spread_v2.yaml
```

CLI output rule:
- Human-readable summary by default
- `--format json` for automation
- Non-zero exit on validation failure or contract breach

---

## 8. Testing Strategy to Enforce Quality

### Unit Tests

- Strategy model interfaces and datamodel invariants.
- Run manifest serialization/deserialization.
- Artifact store read/write idempotency.
- Pre-trade validator rule coverage.

### Integration Tests

- End-to-end research pipeline command chain.
- Optimize command with fixture dataset.
- Live runtime dry-run with mocked adapters.

### Regression Tests

- Golden metric snapshot for baseline strategy.
- Manifest schema snapshot test.

---

## 9. Risks and Mitigations

1. **Risk:** Overengineering before research CLI is usable  
   **Mitigation:** Ship P1 early with one baseline strategy and one dataset.

2. **Risk:** Contract drift between backtest and live  
   **Mitigation:** Shared framework interfaces and shared order/state models only.

3. **Risk:** Notebook logic diverges from production modules  
   **Mitigation:** Notebook must import module functions; forbid duplicated business logic in PR checklist.

4. **Risk:** Non-reproducible optimize results  
   **Mitigation:** Persist seed, config hash, dataset manifest, and git commit for every trial.

---

## 10. 30/60/90-Day Rollout Targets

### Day 30

- Research CLI commands exist and run on fixture data.
- Run manifests emitted for dataset/features/backtest/eval.

### Day 60

- Optimize command shipped with artifact registry.
- One strategy fully reproducible from CLI only.

### Day 90

- Live runtime using same strategy framework contracts.
- Pre-trade validation and execution report chain in place.

---

## 11. Adoption Rule of Thumb

Copy **Lean's architecture patterns**, not Lean's full complexity.

For this repo, the winning formula is:

1. Keep PM-native data model and canonical event guarantees.
2. Add framework contracts to decouple strategy concerns.
3. Make research/backtest/live workflows first-class CLIs with strict manifests.
4. Enforce reproducibility and artifact traceability by default.

---

## 12. Complementary Lessons from QUANTAXIS (Lean-Compatible, Iteration 2)

Lean remains the primary architecture reference. QUANTAXIS contributes practical patterns for research ergonomics and operations that can be added without importing its full stack.

### 12.1 Protocol-First Boundaries (Keep Core Swappable)

Add protocol boundaries in core for:

- market/account state access
- strategy context and clock
- data bundle loading
- order routing and execution acknowledgement

Outcome:
- strategy code and research runners stop depending on one concrete connector/runtime implementation.

### 12.2 Research Session + Experiment Catalog

Introduce two lightweight contracts:

- `ResearchSession`: one object for dataset/feature/backtest/evaluate state for a user run
- `ExperimentCatalog`: index of experiment metadata (`run_id`, tags, objective, promotion status)

Outcome:
- easier iteration loops and promotion of successful research runs to production candidates.

### 12.3 Factor/Signal Pack Registry

Add a registry pattern for grouped feature/signal definitions:

- each pack declares version, dependencies, schema, and compute entrypoint
- backtests/optimize consume pack IDs instead of ad-hoc notebook code

Outcome:
- clearer ownership and versioning of reusable alpha components.

### 12.4 Optional Acceleration Boundary (Not Mandatory in MVP)

Define an optional performance boundary now:

- pure-Python default path
- optional accelerated implementation behind same interface (Numba/Rust/C++)
- strict parity tests between baseline and accelerated implementations

Outcome:
- performance improvements later without API churn.

### 12.5 Ops Profile Standardization

Standardize environment profiles for reproducible runs:

- `dev`, `research`, `ci`, `paper`, `live`
- each profile declares storage roots, log level, retention, and safety flags

Outcome:
- fewer environment-specific surprises when moving from notebook to CI/live.

### 12.6 What Not to Bring Over

Do not import heavy infra patterns unless a concrete bottleneck exists:

- avoid adopting large service meshes or distributed schedulers preemptively
- avoid parallel account/exchange model layers if protocol boundaries already cover the need

Keep the adoption filter:
- add only patterns that improve iteration speed, reproducibility, or production safety.
