# Lean Adoption GitHub Issue Backlog

> Last updated: March 7, 2026  
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
6. `Lean Adoption P5 - Research Ergonomics & Governance` (target: June 14, 2026)
7. `Lean Adoption P6 - Data Bridge & Runtime Profiles` (target: June 28, 2026)
8. `Lean Adoption P7 - Performance Boundary & Documentation Discipline` (target: July 10, 2026)

Suggested labels:
- `lean-adoption`
- `area/research`
- `area/live`
- `area/core`
- `area/cli`
- `area/data-plane`
- `area/ops`
- `area/testing`
- `type/architecture`
- `type/feature`
- `type/performance`
- `type/docs`

---

## 2. Master Checklist

- [x] LA-001: Add strategy framework contracts and models (P0)
- [x] LA-002: Add run context + run manifest models/writer (P0)
- [x] LA-003: Add run manifest bridge + artifact path conventions (P0)
- [x] LA-004: Convert research CLI from stub to command group (P1)
- [x] LA-005: Implement `build-dataset` command + runner (P1)
- [x] LA-006: Implement `build-features` command + runner (P1)
- [x] LA-007: Implement `backtest`, `evaluate`, `report` commands + runners (P1)
- [x] LA-008: Add research end-to-end integration tests and docs wiring (P1)
- [x] LA-009: Add `ArtifactStore` abstraction and filesystem backend (P2)
- [x] LA-010: Implement `optimize` command + trial registry persistence (P2)
- [x] LA-011: Implement live runtime using shared strategy framework contracts (P3)
- [x] LA-012: Implement pre-trade validator and execution report pipeline (P3)
- [x] LA-013: Add live dry-run integration tests (mock venue adapters) (P3)
- [x] LA-014: Add run observability summaries + manifest/report schema regression tests (P4)
- [x] LA-015: Add CI smoke job for research CLI pipeline (P4)
- [x] LA-016: Add `ResearchSession` + `ExperimentCatalog` contracts and persistence (P5)
- [x] LA-017: Add factor-pack registry and strategy recipe manifests (P5)
- [x] LA-018: Add promotion-gate workflow and research ergonomics CLI aliases (P5)
- [x] LA-019: Add provider-neutral data-bridge contract and capability declarations (P6)
- [x] LA-020: Add incremental cursor persistence and replay-package manifests (P6)
- [x] LA-021: Standardize runtime environment profiles across collector/research/live (P6)
- [x] LA-022: Add optional acceleration boundary and parity-test harness + docs modularity rule (P7)

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

- [x] Define protocol interfaces: `UniverseModel`, `AlphaModel`, `PortfolioConstructionModel`, `RiskModel`, `ExecutionModel`
- [x] Define core datamodels: market state, signal, target, order intent
- [x] Add minimal framework engine orchestration skeleton with typed boundaries
- [x] Export new module in package init
- [x] Add unit tests for contract and model invariants

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

- [x] Add `RunContext` model with required fields
- [x] Add run manifest schema and JSON writer/reader helpers
- [x] Include deterministic config hashing helper
- [x] Include git commit capture hook (safe fallback when unavailable)
- [x] Add unit tests for serialization round-trip

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

- [x] Define canonical path helpers under `data/gold/runs/{run_id}/...`
- [x] Add optional metadata bridge fields for `parent_run_id` / lineage references
- [x] Keep ingestion behavior backward compatible
- [x] Document artifact path convention in migration guide
- [x] Add unit tests for path helpers and backward compatibility

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

- [x] Convert `apps/research/main.py` to `@click.group()`
- [x] Add common options (`--config`, `--format`, `--output-dir`)
- [x] Standardize machine-readable JSON output mode
- [x] Standardize non-zero exit behavior on failures
- [x] Add CLI smoke tests

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

- [x] Implement dataset runner with point-in-time window arguments
- [x] Persist manifest and artifact paths under canonical run directory
- [x] Add CLI command wiring and output summary
- [x] Replace doc script example with official command flow
- [x] Add integration test using fixture silver data

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

- [x] Implement feature runner interface over input dataset artifacts
- [x] Persist feature matrix and feature manifest
- [x] Include `feature_set_version` in run manifest
- [x] Add CLI wiring and JSON output
- [x] Add integration tests for empty and normal cases

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

- [x] Implement backtest runner using framework contracts
- [x] Implement evaluation runner for financial and PM metrics
- [x] Implement report writer producing JSON/Parquet outputs
- [x] Wire commands and shared output semantics
- [x] Add integration tests for command chain

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

- [x] Add full chain test (`build-dataset` -> `build-features` -> `backtest` -> `evaluate`)
- [x] Add artifact existence and schema assertions
- [x] Update migration guide with exact command mapping
- [x] Add progress checkbox tracker into research implementation doc

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

- [x] Define store interface (`put`, `get`, `exists`, `list`)
- [x] Add filesystem implementation with deterministic paths
- [x] Migrate runners to use store interface
- [x] Add idempotency and overwrite semantics tests

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

- [x] Add grid/random search modes
- [x] Add objective metric and constraints config support
- [x] Persist trial registry (jsonl/parquet) and leaderboard artifact
- [x] Persist best-run manifest reference
- [x] Add deterministic-seed test path

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

- [x] Add live command group and runtime startup/shutdown path
- [x] Wire strategy framework components into live event loop
- [x] Add order routing boundary (adapter-facing)
- [x] Add basic runtime metrics/logging hooks
- [x] Add unit tests with mocked adapters

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

- [x] Define order lifecycle models (`OrderIntent`, `ValidatedOrder`, `ExecutionReport`)
- [x] Add PM-specific validator checks (market state, limits, fee/slippage sanity)
- [x] Add structured reject reason codes
- [x] Integrate validator before routing/submission
- [x] Add tests for accept/reject paths

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

- [x] Build mock adapter fixture for event feed + order ack
- [x] Test signal -> intent -> validation -> execution report path
- [x] Assert no network dependency in CI
- [x] Assert deterministic output artifacts/log summaries

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

Strengthen long-term stability through versioned observability payloads and schema regression tests.

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

- [x] Add a standardized `RunSummary` schema and emit it from live commands while keeping research plan outputs machine-readable
- [x] Add regression snapshots for manifest schema
- [x] Add regression snapshots for metrics/report schema
- [x] Document schema versioning policy in adoption README

### Acceptance criteria

- Schema changes fail tests unless explicitly updated.
- `RunSummary` schema includes core traceability fields, and research/live CLIs expose machine-readable run metadata.
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

- [x] Add CI stage executing minimal command chain
- [x] Add artifact upload for failed run diagnostics
- [x] Keep runtime bounded for CI (< 5 minutes target)
- [x] Document command chain in root README

### Acceptance criteria

- CI executes research smoke path on each PR.
- Failures expose enough artifacts/logs for diagnosis.
- Pipeline adds acceptable runtime overhead.

---

## LA-016

**Title:** `Introduce ResearchSession and ExperimentCatalog contracts`  
**Milestone:** `Lean Adoption P5 - Research Ergonomics & Governance`  
**Labels:** `lean-adoption`, `area/research`, `area/core`, `type/architecture`

### Summary

Add session-level and experiment-level contracts so dataset/features/backtest/evaluate/optimize runs can be grouped and promoted with explicit metadata.

### Dependencies

- LA-002
- LA-010

### Files to create

- `libs/core/alpha_core/research/session.py`
- `libs/core/alpha_core/research/experiment_catalog.py`
- `tests/unit/test_research_session.py`
- `tests/unit/test_experiment_catalog.py`

### Files to update

- `libs/core/alpha_core/research/__init__.py`
- `apps/research/main.py`
- `docs/implementation/research-plane-mvp.md`

### Checklist

- [x] Add `ResearchSession` schema with `session_id`, `run_id`, `dataset_id`, `feature_set_version`, `strategy_id`, `notes`
- [x] Add `ExperimentCatalog` schema/index with status fields (`candidate`, `needs_review`, `approved_for_paper`, `rejected`)
- [x] Add read/write/list helpers for catalog persistence
- [x] Link run manifests to `session_id`
- [x] Add unit tests for schema validation and catalog lifecycle operations

### Acceptance criteria

- Research runs can be queried by `session_id` and `status`.
- Catalog updates are deterministic and serialized losslessly.
- Existing run-manifest flows remain backward compatible.

---

## LA-017

**Title:** `Add factor-pack registry and strategy recipe manifests`  
**Milestone:** `Lean Adoption P5 - Research Ergonomics & Governance`  
**Labels:** `lean-adoption`, `area/research`, `area/core`, `type/feature`

### Summary

Introduce reusable factor-pack and strategy-recipe contracts so feature/backtest pipelines depend on versioned manifests rather than notebook-defined logic.

### Dependencies

- LA-006
- LA-016

### Files to create

- `libs/core/alpha_core/features/factor_pack.py`
- `libs/core/alpha_core/research/strategy_recipe.py`
- `config/research/factor_packs/example.yaml`
- `config/research/recipes/example.yaml`
- `tests/unit/test_factor_pack_registry.py`
- `tests/unit/test_strategy_recipe_manifest.py`

### Files to update

- `apps/research/commands/build_features.py`
- `apps/research/commands/backtest.py`
- `apps/research/main.py`

### Checklist

- [x] Add `FactorPackManifest` contract with `pack_id`, `version`, `dependencies`, `output_schema`
- [x] Add `StrategyRecipeManifest` contract with factor-pack refs, risk/execution templates, and parameter blocks
- [x] Add validation and dependency-resolution checks
- [x] Add CLI flags for `--factor-pack` and `--strategy-recipe`
- [x] Add unit tests for manifest validation and conflict paths

### Acceptance criteria

- Same factor-pack + recipe inputs produce deterministic feature/backtest metadata.
- Missing dependencies fail with explicit validation errors.
- Runs persist pack/recipe versions in manifests.

---

## LA-018

**Title:** `Implement promotion-gate workflow and research ergonomics CLI aliases`  
**Milestone:** `Lean Adoption P5 - Research Ergonomics & Governance`  
**Labels:** `lean-adoption`, `area/research`, `area/cli`, `area/testing`, `type/feature`

### Summary

Add lightweight CLI ergonomics and approval gates so experiment promotion from research to paper/live uses explicit, testable criteria.

### Dependencies

- LA-016
- LA-017
- LA-010

### Files to create

- `apps/research/commands/session.py`
- `apps/research/commands/catalog.py`
- `apps/research/commands/promote.py`
- `tests/integration/test_research_promotion_flow.py`

### Files to update

- `apps/research/main.py`
- `docs/guides/notebook-to-modules-cli-migration-guide.md`
- `docs/implementation/research-plane-mvp.md`

### Checklist

- [x] Add alias command group: `research session start/status`, `research catalog list`, `research promote`
- [x] Implement promotion gates using objective/risk thresholds and minimum trade count
- [x] Record reviewer metadata (`reviewed_by`, `reviewed_at_utc`, `reason`) in catalog
- [x] Ensure aliases still emit standard run manifests and artifact links
- [x] Add integration tests for pass/fail promotion scenarios

### Acceptance criteria

- Promotion to `approved_for_paper` is blocked when gate conditions fail.
- CLI aliases provide machine-readable output (`--format json`) and deterministic exit codes.
- Promotion metadata is traceable to source runs and sessions.

---

## LA-019

**Title:** `Add provider-neutral data-bridge contract and capability declarations`  
**Milestone:** `Lean Adoption P6 - Data Bridge & Runtime Profiles`  
**Labels:** `lean-adoption`, `area/data-plane`, `area/core`, `type/architecture`

### Summary

Define a data-bridge contract so downstream dataset/replay paths use a consistent provider interface independent of connector internals.

### Dependencies

- LA-003

### Files to create

- `apps/data_collector/connectors/data_bridge.py`
- `apps/data_collector/connectors/capabilities.py`
- `tests/unit/test_data_bridge_contract.py`

### Files to update

- `apps/data_collector/connectors/factory.py`
- `apps/data_collector/pipeline.py`
- `docs/implementation/data-plane-mvp.md`

### Checklist

- [x] Define contract methods: `pull_snapshot(window)`, `pull_incremental(cursor)`, `stream_subscribe(topics)`, `capabilities()`
- [x] Add typed capability model (books, deltas, ohlcv resolutions, metadata cadence)
- [x] Implement bridge adapter(s) over current connector stack
- [x] Add deterministic error mapping for unsupported capabilities
- [x] Add unit tests for contract conformance and capability reporting

### Acceptance criteria

- [x] Dataset/replay consumers can call one bridge interface across supported venues.
- [x] Capability declarations are explicit and test-verified.
- [x] Existing connector behavior remains backward compatible.

---

## LA-020

**Title:** `Persist incremental cursors and replay-package manifests for deterministic resume`  
**Milestone:** `Lean Adoption P6 - Data Bridge & Runtime Profiles`  
**Labels:** `lean-adoption`, `area/data-plane`, `area/research`, `area/core`, `type/feature`

### Summary

Add cursor and replay-package contracts so ingestion can resume safely and research can replay deterministic event slices.

### Dependencies

- LA-019
- LA-005

### Files to create

- `libs/core/alpha_core/storage/replay_package.py`
- `tests/unit/test_replay_package.py`
- `tests/integration/test_resume_replay_flow.py`

### Files to update

- `libs/core/alpha_core/storage/lineage.py`
- `apps/data_collector/backfill.py`
- `apps/data_collector/main.py`

### Checklist

- [x] Add lineage cursor fields (`cursor_type`, `cursor_value`, `cursor_watermark_utc`, `resume_safe`)
- [x] Add replay-package manifest schema with source runs, partition refs, ordering policy, and integrity hash
- [x] Emit replay-package artifacts for eligible ingestion windows
- [x] Add resume logic that consumes stored cursor metadata
- [x] Add integration test for failure -> resume -> replay consistency

### Acceptance criteria

- Ingestion can resume from stored cursor state without duplicate window drift.
- Replay packages are consumable by research runners with deterministic ordering.
- Lineage and replay manifests round-trip without schema loss.

---

## LA-021

**Title:** `Standardize runtime environment profiles across collector, research, and live`  
**Milestone:** `Lean Adoption P6 - Data Bridge & Runtime Profiles`  
**Labels:** `lean-adoption`, `area/ops`, `area/core`, `area/cli`, `type/docs`

### Summary

Define and enforce shared runtime profiles (`dev`, `research`, `ci`, `paper`, `live`) to make behavior predictable across commands and deployment contexts.

### Dependencies

- LA-004
- LA-011
- LA-019

### Files to create

- `config/environments/research.yaml`
- `config/environments/paper.yaml`
- `config/environments/live.yaml`
- `tests/unit/test_runtime_profiles.py`

### Files to update

- `config/default.yaml`
- `libs/core/alpha_core/config/models.py`
- `libs/core/alpha_core/config/loader.py`
- `apps/data_collector/main.py`
- `apps/research/main.py`
- `apps/live_system/main.py`

### Checklist

- [x] Add profile schema with required keys: storage roots, log level, safety flags, retention policy
- [x] Add profile selection flag for entrypoints (`--profile`)
- [x] Enforce safety behavior (for example no live order submission in `research` profile)
- [x] Document profile semantics and defaults
- [x] Add tests for profile parsing and guard behavior

### Acceptance criteria

- All three entrypoints accept and validate the same profile model.
- Misconfigured profiles fail fast with actionable errors.
- Profile-specific safety gates are covered by tests.

---

## LA-022

**Title:** `Introduce optional acceleration boundary with parity-test harness and docs modularity rule`  
**Milestone:** `Lean Adoption P7 - Performance Boundary & Documentation Discipline`  
**Labels:** `lean-adoption`, `area/core`, `area/testing`, `type/performance`, `type/docs`

### Summary

Create a formal boundary for optional accelerated compute backends and enforce parity and documentation discipline before enabling performance-specific paths.

### Dependencies

- LA-006
- LA-007
- LA-021

### Files to create

- `libs/core/alpha_core/perf/interfaces.py`
- `tests/regression/test_acceleration_parity.py`
- `docs/adr/00x-performance-boundary.md`

### Files to update

- `docs/implementation/foundation-stage.md`
- `docs/implementation/research-plane-mvp.md`
- `README.LEAN_ADOPTION.md`

### Checklist

- [x] Define pure-Python baseline interface and optional accelerated interface contract
- [x] Add parity test harness and numerical tolerance policy
- [x] Add fallback policy when accelerated backend is unavailable
- [x] Add documentation modularity rule references (architecture vs runbook vs guide vs ADR)
- [x] Add regression tests for baseline/accelerated parity on representative workloads

### Acceptance criteria

- Baseline path remains default and unchanged in behavior.
- Accelerated path cannot be enabled unless parity tests pass.
- Documentation updates follow modularity rule and include ADR traceability.

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
16. LA-016
17. LA-017
18. LA-018
19. LA-019
20. LA-020
21. LA-021
22. LA-022
