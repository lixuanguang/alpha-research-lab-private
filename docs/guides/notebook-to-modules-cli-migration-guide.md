# Notebook-to-Modules/CLI Migration Guide

> **Purpose:** Promote stable alpha research logic from `.ipynb` experiments into tested Python modules and reproducible CLI flows  
> **Audience:** Researchers and engineers working on Entrypoint C (`apps/research`)  
> **Scope:** R1-R6 workflows in `docs/implementation/research-plane-mvp.md`

---

## Table of Contents

1. [Why Migrate](#1-why-migrate)
2. [When Notebook Logic Is Stable Enough](#2-when-notebook-logic-is-stable-enough)
3. [Target Module/CLI Landing Zones](#3-target-modulecli-landing-zones)
4. [Migration Workflow (Cell to Function to Module to CLI)](#4-migration-workflow-cell-to-function-to-module-to-cli)
5. [Worked Example: `r1_to_r5_microstructure_pipeline.ipynb`](#5-worked-example-r1_to_r5_microstructure_pipelineipynb)
6. [Parity Validation Before Merge](#6-parity-validation-before-merge)
7. [Test Strategy for Migrated Logic](#7-test-strategy-for-migrated-logic)
8. [CLI Wiring Pattern](#8-cli-wiring-pattern)
9. [Operational Hand-off](#9-operational-hand-off)
10. [Common Migration Pitfalls](#10-common-migration-pitfalls)
11. [PR Checklist Template](#11-pr-checklist-template)

---

## 1. Why Migrate

Notebooks are excellent for exploration, diagnostics, and iteration speed. They are weak for long-term reproducibility and operations.

Move logic into modules/CLI when you need:

- Deterministic reruns in CI or cron jobs
- Reuse across multiple notebooks/strategies
- Clear interfaces, versioning, and test coverage
- Lower risk of hidden state and copy-paste drift

Keep notebooks after migration, but as thin consumers of module APIs.

---

## 2. When Notebook Logic Is Stable Enough

Use these gates before migration:

### 2.1 Functional Stability

- The same notebook run produces consistent outputs for fixed seed/config.
- Core outputs have stable schema (columns/types/order where relevant).
- Inputs and assumptions are explicitly parameterized (not hardcoded cell constants).

### 2.2 Statistical Stability

- Signal behavior is not dependent on one narrow parameter point.
- Performance does not collapse under small parameter perturbations.
- Sample size is adequate for the metric you rely on.

### 2.3 Interface Stability

- You can describe the logic as one sentence function contract.
- Inputs are portable (`pd.DataFrame`, `Path`, config object).
- Outputs are machine-consumable (table/dataclass/report object).

### 2.4 Operational Stability

- Runtime and memory are acceptable for repeated runs.
- Failure modes are known and handled (empty inputs, missing columns, NaN/inf).
- Export paths and IDs are standardized.

If any gate fails, keep iterating in notebook mode.

---

## 3. Target Module/CLI Landing Zones

Align extracted logic with the Research Plane architecture.

| Notebook Logic Type | Target Module Path | Typical Output |
|---|---|---|
| Dataset assembly, as-of joins, universe snapshotting | `libs/core/alpha_core/research/` | Gold dataset manifest/handle |
| Feature transforms (microstructure + PM-specific) | `libs/core/alpha_core/features/` | Feature table (`pyarrow`/`pandas`) |
| Position, fills, slippage, fees | `libs/core/alpha_core/portfolio/` + `libs/core/alpha_core/execution/` | Fill stream + portfolio state |
| Event/vectorized simulation | `apps/research/backtester/` | `BacktestResult` |
| PM and financial evaluation | `libs/core/alpha_core/evaluation/` | Metrics report |
| Report persistence/comparison | `apps/research/reporting/` | JSON/Parquet artifacts |
| User-facing orchestration | `apps/research/main.py` | CLI subcommands |

Rule: domain logic in `libs/core`; orchestration in `apps/research`.

---

## 4. Migration Workflow (Cell to Function to Module to CLI)

### Step 1: Freeze the Notebook Baseline

- Save a timestamped notebook snapshot.
- Export baseline artifacts (`csv/json`) to `data/research_journal/notebook_exports/`.
- Record seed, date range, and parameter set.

### Step 2: Extract Pure Functions First

Start with computation-only cells:

- JSON/orderbook parsing helpers
- Feature formulas
- Metric calculations
- Signal rules

Avoid moving plotting/UI cells initially.

### Step 3: Define Explicit Contracts

For each function define:

- Inputs (schema + required columns)
- Outputs (schema + units)
- Error behavior (raise vs return empty)
- Time semantics (timezone, as-of rules)

### Step 4: Package into Modules

- Move function families into the correct module path.
- Keep the first pass minimal; avoid broad refactors.
- Add docstrings that encode assumptions and units.

### Step 5: Add Tests Before CLI Wiring

- Unit tests for edge cases and invariants
- Integration test for one representative end-to-end flow
- Golden snapshot test for expected outputs where useful

### Step 6: Replace Notebook Cell Logic with Imports

Notebook should call module functions, not duplicate logic:

```python
from alpha_core.features.pm_specific import compute_microprice_deviation
from apps.research.backtester.engine import EventBacktestEngine
```

### Step 7: Expose Through CLI

Create or extend a CLI command that:

- Accepts the same core params as notebook baseline
- Writes standardized outputs
- Prints run ID + output locations

### Step 8: Run Parity Check and Cut Over

- Compare module/CLI outputs against frozen notebook baseline
- Keep notebook as diagnostics layer
- Remove duplicated business logic from notebook cells

---

## 5. Worked Example: `r1_to_r5_microstructure_pipeline.ipynb`

Source notebook:

- `apps/research/notebooks/r1_to_r5_microstructure_pipeline.ipynb`

Suggested extraction map:

| Notebook Section | Promote To | Notes |
|---|---|---|
| R1 book/trade loading + as-of merge | `alpha_core.research.dataset_builder` + helper in `alpha_core.research.as_of` | Keep joins point-in-time safe |
| Book JSON parsing and spread/imbalance derivation | `alpha_core.features.pm_specific` (or helper module under `features`) | Add strict schema validation |
| R2 feature engineering (`mom_5`, `ofi_proxy_5`, etc.) | `alpha_core.features.pm_specific` + `FeatureRegistry` entries | Version feature params |
| R3 `run_event_style_backtest` | `apps/research/backtester/engine.py` strategy/engine path | Replace proxy with canonical engine models |
| R4 grid sweep loop | `apps/research/backtester/sweep.py` | Persist sweep metadata |
| R5 scorecard and metric summary | `alpha_core.evaluation/*` + `apps/research/reporting/writer.py` | Separate metric compute from presentation |
| Export block | `apps/research/reporting/writer.py` | Keep output schema stable |

Minimal migration order for this notebook:

1. Extract parsing + feature cells (R1/R2)
2. Extract backtest function and make deterministic
3. Extract scorecard/evaluation
4. Wire one CLI command for full run

---

## 6. Parity Validation Before Merge

Use a small fixed dataset window and compare notebook vs module/CLI outputs.

Required parity checks:

- Row counts match (or expected deterministic delta explained)
- Feature column null rates within tolerance
- Key metrics within tolerance (`abs(diff) < epsilon`)
- Trade count and cost totals reconcile
- Export schema and file naming match expected contract

Example tolerance table:

| Metric | Tolerance |
|---|---|
| Feature mean/std | `1e-9` to `1e-6` depending on dtype |
| PnL / cost totals | `1e-6` (float) or exact (`Decimal`) |
| Sharpe/Brier | `1e-6` |
| Trade count | exact |

---

## 7. Test Strategy for Migrated Logic

### Unit Tests

- Parsing helpers (`bids_json`, `asks_json`) with malformed payloads
- Feature computations with empty frames, NaN, inf, and short warmup windows
- Cost and slippage calculations
- Scorecard threshold logic

### Integration Tests

- Silver/gold fixture -> features -> backtest -> evaluate -> report
- CLI smoke tests for argument parsing and output artifact creation

### Regression Tests

- Golden report snapshot for one fixed fixture window
- Guard against accidental schema changes

---

## 8. CLI Wiring Pattern

As of **March 1, 2026**, `apps/research/main.py` is a stub. During R6, expose migrated logic with stable commands.

CLI design rules:

- One command = one coherent stage action
- Support config-file + explicit flags
- Emit machine-readable output (`--format json`) for automation
- Return non-zero exit code on failed validation gates

Suggested command surface:

- `build-dataset`
- `build-features`
- `backtest`
- `evaluate`
- `report`
- `run-microstructure-pipeline` (optional convenience wrapper)

---

## 9. Operational Hand-off

After migration:

- Notebook remains for diagnostics and visual analysis
- Production/repeat runs use CLI only
- Weekly research journal links to module version and CLI run ID

Recommended traceability fields per run:

- `dataset_id`
- `feature_set_version`
- `strategy_version`
- `config_hash`
- `git_commit`
- `run_timestamp_utc`

### 9.1 Run Artifact Layout Convention

Every CLI run produces a deterministic output tree under a shared root.  Use
`alpha_core.research.artifact_paths` helpers — never construct these paths manually.

```text
{storage_root}/runs/{run_id}/
    manifest.json       # RunManifest (run context + full artifact index)
    config.json         # frozen config snapshot for this run
    artifacts.json      # logical key → absolute path index
    stage_outputs/      # default home for files produced by this run
        <artifact_key>  # e.g. "features.parquet", "report/summary.json"
```

**How to use the helpers:**

```python
from alpha_core.research import (
    artifact_key_path,       # deterministic path for a named output file
    stage_outputs_path,      # root of the stage_outputs/ directory
    write_artifacts_index,   # atomically write artifacts.json
    read_artifacts_index,    # read artifacts.json (empty dict if missing)
    run_manifest_path,       # path to manifest.json
    run_config_path,         # path to config.json
)

# Get the canonical path for a named artifact (no I/O performed)
out_path = artifact_key_path(storage_root, run_id, "features.parquet")

# Or for a nested key:
out_path = artifact_key_path(storage_root, run_id, "report/summary.json")

# After writing outputs, register them:
write_artifacts_index(storage_root, run_id, {
    "features":       str(out_path),
    "report_summary": str(artifact_key_path(storage_root, run_id, "report/summary.json")),
})

# Retrieve later (returns {} if not found — backward-compatible):
index = read_artifacts_index(storage_root, run_id)
```

**Rules:**

- `artifact_key_path` is the **only** sanctioned way to derive a default path for a
  named output. It guarantees path determinism for identical `(run_id, artifact_key)`.
- Stage-specific outputs (`gold/datasets/…`, `gold/features/…`) **may** live outside
  `stage_outputs/` but **must** be registered in `artifacts.json` so `RunManifest` can
  locate them.
- `artifact_key` must be a relative path; no `..` traversal; forward-slash creates
  sub-directories under `stage_outputs/`.

**Linking ingestion runs to downstream research runs:**

```python
from alpha_core.storage.lineage import LineageStore

store = LineageStore(storage_root)
# After a dataset_build run that consumed ingestion run X:
store.link_downstream_run(ingestion_run_id, dataset_build_run_id)
# The downstream RunManifest.parent_run_id should also be set to ingestion_run_id
# for bidirectional traceability.
```

---

## 10. Common Migration Pitfalls

- Copying notebook code verbatim without contracts/tests
- Leaving hidden global state (cell-order dependencies)
- Mixing plotting/presentation logic into domain modules
- Ignoring empty-data behavior
- Promoting unstable parameter-tuned logic too early
- Failing to preserve point-in-time constraints during refactor

---

## 11. PR Checklist Template

Use this checklist in migration PRs:

- [ ] Notebook baseline snapshot saved and linked
- [ ] Extracted functions have typed signatures and docstrings
- [ ] Unit tests added for edge cases
- [ ] Integration path tested end-to-end
- [ ] Notebook now imports module functions (no duplicated business logic)
- [ ] CLI command added/extended
- [ ] Parity validation documented with tolerances
- [ ] Artifacts/report schema documented
- [ ] Research journal entry updated with migration decision
