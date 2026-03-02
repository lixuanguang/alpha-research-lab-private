# Lean Adoption GitHub Issue Backlog

> Last updated: March 2, 2026  
> Source: `README.LEAN_ADOPTION.md`  
> Purpose: Copy-paste-ready issue plan with milestones, dependencies, file targets, and acceptance criteria.

---

## 1. Milestones

Use these milestone names in GitHub:

1. `Lean Adoption P0 - Contracts & Metadata` (target: April 1, 2026)
2. `Lean Adoption P1 - Research CLI Core` (target: April 22, 2026)
3. `Lean Adoption P2 - Optimize & Artifact Store` (target: May 1, 2026)
4. `Lean Adoption P3 - Live Reuse & Pre-Trade Guards` (target: May 22, 2026)
5. `Lean Adoption P4 - Observability & Hardening` (target: May 31, 2026)

Suggested labels:
- `lean-adoption`
- `area/research`
- `area/live`
- `area/core`
- `area/cli`
- `area/testing`
- `type/architecture`
- `type/feature`
- `type/docs`

---

## 2. Master Checklist

- [ ] LA-001: Add strategy framework contracts and models (P0)
- [ ] LA-002: Add run context + run manifest models/writer (P0)
- [ ] LA-003: Add run manifest bridge + artifact path conventions (P0)
- [ ] LA-004: Convert research CLI from stub to command group (P1)
- [ ] LA-005: Implement `build-dataset` command + runner (P1)
- [ ] LA-006: Implement `build-features` command + runner (P1)
- [ ] LA-007: Implement `backtest`, `evaluate`, `report` commands + runners (P1)
- [ ] LA-008: Add research end-to-end integration tests and docs wiring (P1)
- [ ] LA-009: Add `ArtifactStore` abstraction and filesystem backend (P2)
- [ ] LA-010: Implement `optimize` command + trial registry persistence (P2)
- [ ] LA-011: Implement live runtime using shared strategy framework contracts (P3)
- [ ] LA-012: Implement pre-trade validator and execution report pipeline (P3)
- [ ] LA-013: Add live dry-run integration tests (mock venue adapters) (P3)
- [ ] LA-014: Add run observability summaries + manifest/report schema regression tests (P4)
- [ ] LA-015: Add CI smoke job for research CLI pipeline (P4)

---

## 3. Issue Templates

Use one section below as one GitHub issue body.

## LA-001

**Title:** `Introduce strategy framework contracts and core models`  
**Milestone:** `Lean Adoption P0 - Contracts & Metadata`  
**Labels:** `lean-adoption`, `area/core`, `type/architecture`

### Summary

Add Lean-inspired modular strategy contracts so research, backtest, and live can share the same strategy shape.

### Dependencies

None.

### Files to create

- `libs/core/alpha_core/strategy_framework/__init__.py`
- `libs/core/alpha_core/strategy_framework/interfaces.py`
- `libs/core/alpha_core/strategy_framework/models.py`
- `libs/core/alpha_core/strategy_framework/engine.py`

### Files to update

- `libs/core/alpha_core/__init__.py`
- `tests/unit/test_scaffold.py` (or equivalent package export tests)

### Checklist

- [ ] Define protocol interfaces: `UniverseModel`, `AlphaModel`, `PortfolioConstructionModel`, `RiskModel`, `ExecutionModel`
- [ ] Define core datamodels: market state, signal, target, order intent
- [ ] Add minimal framework engine orchestration skeleton with typed boundaries
- [ ] Export new module in package init
- [ ] Add unit tests for contract and model invariants

### Acceptance criteria

- Interfaces compile under `mypy --strict`.
- New models validate with Pydantic and reject malformed payloads.
- Unit tests cover happy path and invalid input path.

---

## LA-002

**Title:** `Add research run context and standardized run manifest models`  
**Milestone:** `Lean Adoption P0 - Contracts & Metadata`  
**Labels:** `lean-adoption`, `area/core`, `area/research`, `type/architecture`

### Summary

Create strongly typed run metadata contracts shared by dataset, feature, backtest, evaluate, optimize, and live flows.

### Dependencies

- LA-001

### Files to create

- `libs/core/alpha_core/research/run_context.py`
- `libs/core/alpha_core/research/manifest.py`

### Files to update

- `libs/core/alpha_core/research/__init__.py` (create if missing)
- `tests/unit/test_lineage.py` (if helpers are reused)
- `tests/unit/test_research_manifest.py` (new)

### Checklist

- [ ] Add `RunContext` model with required fields
- [ ] Add run manifest schema and JSON writer/reader helpers
- [ ] Include deterministic config hashing helper
- [ ] Include git commit capture hook (safe fallback when unavailable)
- [ ] Add unit tests for serialization round-trip

### Acceptance criteria

- Manifest contains required fields from `README.LEAN_ADOPTION.md`.
- Round-trip JSON parse preserves exact values.
- Missing required fields fail with clear error messages.

---

## LA-003

**Title:** `Bridge ingestion lineage and research run manifests with artifact path conventions`  
**Milestone:** `Lean Adoption P0 - Contracts & Metadata`  
**Labels:** `lean-adoption`, `area/core`, `type/feature`

### Summary

Define and enforce canonical artifact layout for non-ingestion runs and add optional linkage from ingestion lineage to downstream research runs.

### Dependencies

- LA-002

### Files to create

- `libs/core/alpha_core/research/artifact_paths.py`

### Files to update

- `libs/core/alpha_core/storage/lineage.py`
- `docs/guides/notebook-to-modules-cli-migration-guide.md`

### Checklist

- [ ] Define canonical path helpers under `data/gold/runs/{run_id}/...`
- [ ] Add optional metadata bridge fields for `parent_run_id` / lineage references
- [ ] Keep ingestion behavior backward compatible
- [ ] Document artifact path convention in migration guide
- [ ] Add unit tests for path helpers and backward compatibility

### Acceptance criteria

- Existing ingestion tests continue to pass unchanged.
- New helpers produce deterministic paths for the same inputs.
- Docs explain path convention and migration usage.

---

## LA-004

**Title:** `Convert apps.research CLI from stub to command group with shared options`  
**Milestone:** `Lean Adoption P1 - Research CLI Core`  
**Labels:** `lean-adoption`, `area/research`, `area/cli`, `type/feature`

### Summary

Replace stubbed research entrypoint with click group and base plumbing used by all research commands.

### Dependencies

- LA-002

### Files to create

- `apps/research/commands/__init__.py`
- `apps/research/commands/common.py`

### Files to update

- `apps/research/main.py`
- `pyproject.toml` (if CLI entrypoint metadata is needed)
- `tests/unit/test_cli_commands.py`

### Checklist

- [ ] Convert `apps/research/main.py` to `@click.group()`
- [ ] Add common options (`--config`, `--format`, `--output-dir`)
- [ ] Standardize machine-readable JSON output mode
- [ ] Standardize non-zero exit behavior on failures
- [ ] Add CLI smoke tests

### Acceptance criteria

- `python -m apps.research.main --help` shows command group.
- Invalid config exits non-zero with meaningful error.
- JSON format output can be parsed by tests.

---

## LA-005

**Title:** `Implement build-dataset command and dataset runner`  
**Milestone:** `Lean Adoption P1 - Research CLI Core`  
**Labels:** `lean-adoption`, `area/research`, `area/cli`, `type/feature`

### Summary

Add first-class dataset materialization command replacing ad-hoc scripts in docs.

### Dependencies

- LA-004
- LA-003

### Files to create

- `libs/core/alpha_core/research/dataset_builder.py`
- `apps/research/commands/build_dataset.py`
- `config/research/dataset.example.yaml`

### Files to update

- `apps/research/main.py`
- `docs/guides/gold-dataset-collection-streaming-guide.md`
- `tests/integration/test_research_build_dataset.py`

### Checklist

- [ ] Implement dataset runner with point-in-time window arguments
- [ ] Persist manifest and artifact paths under canonical run directory
- [ ] Add CLI command wiring and output summary
- [ ] Replace doc script example with official command flow
- [ ] Add integration test using fixture silver data

### Acceptance criteria

- Command builds deterministic gold dataset from fixtures.
- Manifest includes dataset counts and window metadata.
- Guide references command instead of only custom script.

---

## LA-006

**Title:** `Implement build-features command and feature runner contract`  
**Milestone:** `Lean Adoption P1 - Research CLI Core`  
**Labels:** `lean-adoption`, `area/research`, `area/cli`, `type/feature`

### Summary

Add first-class feature build command with versioned feature-set metadata.

### Dependencies

- LA-004
- LA-002

### Files to create

- `libs/core/alpha_core/research/feature_runner.py`
- `apps/research/commands/build_features.py`
- `config/research/features.example.yaml`

### Files to update

- `apps/research/main.py`
- `tests/integration/test_research_build_features.py`

### Checklist

- [ ] Implement feature runner interface over input dataset artifacts
- [ ] Persist feature matrix and feature manifest
- [ ] Include `feature_set_version` in run manifest
- [ ] Add CLI wiring and JSON output
- [ ] Add integration tests for empty and normal cases

### Acceptance criteria

- Command fails fast when dataset artifacts are missing.
- Feature output schema is deterministic for same config.
- Tests validate run manifest links to feature artifacts.

---

## LA-007

**Title:** `Implement backtest, evaluate, and report research commands`  
**Milestone:** `Lean Adoption P1 - Research CLI Core`  
**Labels:** `lean-adoption`, `area/research`, `area/cli`, `type/feature`

### Summary

Implement remaining core research pipeline commands with consistent contracts and artifacts.

### Dependencies

- LA-001
- LA-004
- LA-006

### Files to create

- `libs/core/alpha_core/research/backtest_runner.py`
- `libs/core/alpha_core/research/evaluate_runner.py`
- `apps/research/commands/backtest.py`
- `apps/research/commands/evaluate.py`
- `apps/research/commands/report.py`

### Files to update

- `apps/research/main.py`
- `tests/integration/test_research_backtest_evaluate_report.py`

### Checklist

- [ ] Implement backtest runner using framework contracts
- [ ] Implement evaluation runner for financial and PM metrics
- [ ] Implement report writer producing JSON/Parquet outputs
- [ ] Wire commands and shared output semantics
- [ ] Add integration tests for command chain

### Acceptance criteria

- Backtest command emits trades/equity artifacts and run manifest.
- Evaluate command emits metrics artifact with expected keys.
- Report command renders deterministic summary payload.

---

## LA-008

**Title:** `Add research E2E command-chain tests and migration guide mapping`  
**Milestone:** `Lean Adoption P1 - Research CLI Core`  
**Labels:** `lean-adoption`, `area/testing`, `area/research`, `type/docs`

### Summary

Enforce reproducible end-to-end research workflow and document notebook-to-CLI mapping.

### Dependencies

- LA-005
- LA-006
- LA-007

### Files to update

- `tests/integration/test_research_pipeline_e2e.py` (new)
- `docs/guides/notebook-to-modules-cli-migration-guide.md`
- `docs/implementation/research-plane-mvp.md`

### Checklist

- [ ] Add full chain test (`build-dataset` -> `build-features` -> `backtest` -> `evaluate`)
- [ ] Add artifact existence and schema assertions
- [ ] Update migration guide with exact command mapping
- [ ] Add progress checkbox tracker into research implementation doc

### Acceptance criteria

- Single test covers the full command chain on fixtures.
- Docs explicitly map notebook sections to CLI commands.
- Research implementation doc has checkboxes tied to real modules.

---

## LA-009

**Title:** `Introduce ArtifactStore abstraction with filesystem backend`  
**Milestone:** `Lean Adoption P2 - Optimize & Artifact Store`  
**Labels:** `lean-adoption`, `area/core`, `area/research`, `type/architecture`

### Summary

Create object-store-style abstraction for shared artifacts across research/backtest/live.

### Dependencies

- LA-002

### Files to create

- `libs/core/alpha_core/research/artifact_store.py`
- `tests/unit/test_artifact_store.py`

### Files to update

- `libs/core/alpha_core/research/dataset_builder.py`
- `libs/core/alpha_core/research/feature_runner.py`
- `libs/core/alpha_core/research/backtest_runner.py`
- `libs/core/alpha_core/research/evaluate_runner.py`

### Checklist

- [ ] Define store interface (`put`, `get`, `exists`, `list`)
- [ ] Add filesystem implementation with deterministic paths
- [ ] Migrate runners to use store interface
- [ ] Add idempotency and overwrite semantics tests

### Acceptance criteria

- Runners no longer hardcode raw filesystem writes.
- Store API behavior is covered by unit tests.
- Existing artifacts remain backward compatible in location or have migration note.

---

## LA-010

**Title:** `Implement optimize command with trial registry and leaderboard artifacts`  
**Milestone:** `Lean Adoption P2 - Optimize & Artifact Store`  
**Labels:** `lean-adoption`, `area/research`, `area/cli`, `type/feature`

### Summary

Add first-class optimization workflow to replace notebook-only parameter sweeps.

### Dependencies

- LA-007
- LA-009

### Files to create

- `apps/research/commands/optimize.py`
- `libs/core/alpha_core/research/optimize_runner.py`
- `config/research/optimize.example.yaml`
- `tests/integration/test_research_optimize.py`

### Files to update

- `apps/research/main.py`

### Checklist

- [ ] Add grid/random search modes
- [ ] Add objective metric and constraints config support
- [ ] Persist trial registry (jsonl/parquet) and leaderboard artifact
- [ ] Persist best-run manifest reference
- [ ] Add deterministic-seed test path

### Acceptance criteria

- Command produces trial table and top-N leaderboard artifacts.
- Same seed/config yields stable ordering within test tolerance.
- CLI help clearly documents objective and constraints.

---

## LA-011

**Title:** `Implement live runtime that reuses strategy framework contracts`  
**Milestone:** `Lean Adoption P3 - Live Reuse & Pre-Trade Guards`  
**Labels:** `lean-adoption`, `area/live`, `area/core`, `type/feature`

### Summary

Replace live stub with runtime that executes the same strategy component contracts used in backtesting.

### Dependencies

- LA-001
- LA-007

### Files to create

- `apps/live_system/runtime.py`
- `apps/live_system/order_router.py`

### Files to update

- `apps/live_system/main.py`
- `tests/unit/test_live_runtime.py` (new)

### Checklist

- [ ] Add live command group and runtime startup/shutdown path
- [ ] Wire strategy framework components into live event loop
- [ ] Add order routing boundary (adapter-facing)
- [ ] Add basic runtime metrics/logging hooks
- [ ] Add unit tests with mocked adapters

### Acceptance criteria

- `python -m apps.live_system.main --help` exposes runnable live command surface.
- Live runtime can process mocked events and emit order intents.
- Strategy module can be shared between backtest and live tests.

---

## LA-012

**Title:** `Add pre-trade validation and execution report model pipeline`  
**Milestone:** `Lean Adoption P3 - Live Reuse & Pre-Trade Guards`  
**Labels:** `lean-adoption`, `area/live`, `area/core`, `type/feature`

### Summary

Add explicit guardrails and status reporting before order submission.

### Dependencies

- LA-011

### Files to create

- `libs/core/alpha_core/execution/pretrade.py`
- `libs/core/alpha_core/execution/order_models.py`
- `libs/core/alpha_core/execution/simulator.py`
- `tests/unit/test_pretrade_validator.py`

### Files to update

- `apps/live_system/order_router.py`
- `apps/research/backtester` modules when present (shared execution models)

### Checklist

- [ ] Define order lifecycle models (`OrderIntent`, `ValidatedOrder`, `ExecutionReport`)
- [ ] Add PM-specific validator checks (market state, limits, fee/slippage sanity)
- [ ] Add structured reject reason codes
- [ ] Integrate validator before routing/submission
- [ ] Add tests for accept/reject paths

### Acceptance criteria

- Invalid intents are rejected with deterministic reason codes.
- Execution report schema is stable and serialized in tests.
- Validator is invoked in live runtime path before any submission call.

---

## LA-013

**Title:** `Add live dry-run integration tests with mocked venue adapters`  
**Milestone:** `Lean Adoption P3 - Live Reuse & Pre-Trade Guards`  
**Labels:** `lean-adoption`, `area/live`, `area/testing`, `type/feature`

### Summary

Add integration coverage for live strategy flow without external network calls.

### Dependencies

- LA-011
- LA-012

### Files to create

- `tests/integration/test_live_system_dry_run.py`

### Files to update

- `tests/conftest.py` (if reusable live adapter fixtures are needed)

### Checklist

- [ ] Build mock adapter fixture for event feed + order ack
- [ ] Test signal -> intent -> validation -> execution report path
- [ ] Assert no network dependency in CI
- [ ] Assert deterministic output artifacts/log summaries

### Acceptance criteria

- Integration test passes in CI/offline mode.
- Test asserts both accepted and rejected order scenarios.
- No flaky timing dependency in the test harness.

---

## LA-014

**Title:** `Add run observability summaries and schema regression tests`  
**Milestone:** `Lean Adoption P4 - Observability & Hardening`  
**Labels:** `lean-adoption`, `area/testing`, `area/core`, `type/feature`

### Summary

Strengthen long-term stability through run summary outputs and schema regression tests.

### Dependencies

- LA-007
- LA-010
- LA-013

### Files to create

- `tests/regression/test_run_manifest_schema.py`
- `tests/regression/test_metrics_report_schema.py`

### Files to update

- `apps/research/main.py`
- `apps/live_system/main.py`
- `README.LEAN_ADOPTION.md`

### Checklist

- [ ] Emit standardized run summary blocks for research/live commands
- [ ] Add regression snapshots for manifest schema
- [ ] Add regression snapshots for metrics/report schema
- [ ] Document schema versioning policy in adoption README

### Acceptance criteria

- Schema changes fail tests unless explicitly updated.
- Run summaries include core traceability fields.
- Docs define schema change process.

---

## LA-015

**Title:** `Add CI smoke pipeline for research CLI lifecycle`  
**Milestone:** `Lean Adoption P4 - Observability & Hardening`  
**Labels:** `lean-adoption`, `area/testing`, `area/cli`, `type/feature`

### Summary

Add CI job that validates minimal research lifecycle command chain on fixture data.

### Dependencies

- LA-008
- LA-014

### Files to update

- `.github/workflows/ci.yml`
- `tests/integration/test_research_pipeline_e2e.py`
- `README.md`

### Checklist

- [ ] Add CI stage executing minimal command chain
- [ ] Add artifact upload for failed run diagnostics
- [ ] Keep runtime bounded for CI (< 5 minutes target)
- [ ] Document command chain in root README

### Acceptance criteria

- CI executes research smoke path on each PR.
- Failures expose enough artifacts/logs for diagnosis.
- Pipeline adds acceptable runtime overhead.

---

## 4. Suggested Creation Order

Create issues in this order to preserve dependency flow:

1. LA-001
2. LA-002
3. LA-003
4. LA-004
5. LA-005
6. LA-006
7. LA-007
8. LA-008
9. LA-009
10. LA-010
11. LA-011
12. LA-012
13. LA-013
14. LA-014
15. LA-015

