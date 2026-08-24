# Statistical Arbitrage Research Platform Implementation Guidelines

## Purpose

This document defines the implementation sequence and review standards for a crypto-first, production-oriented statistical-arbitrage platform. The platform must support the complete research lifecycle: point-in-time data, feature and model research, portfolio construction, realistic execution, validation, governance, shadow trading, and operational monitoring.

The first workload is a transparent crypto factor-residual strategy. It is an acceptance test for the platform, not the platform architecture. Shared contracts must also support equities, futures, FX, options, volatility, and fixed-income relative value without rewriting the research, artifact, governance, or deployment layers.

## Architectural basis and limits

This is a proposed architecture for this repository, not a description of any trading firm's proprietary systems. Public material establishes some useful patterns but does not disclose complete internal directory layouts or deployment controls:

- Jane Street has described a large OCaml-and-Python monorepo, a dedicated build-systems function, Dune-based builds, and reproducible Python deployment environments.
- Hudson River Trading has described majority-monorepo development, C++/Python research and trading systems, distributed cached builds and tests, and large-scale Prometheus monitoring.
- Citadel Securities publicly describes trading systems, research and simulation infrastructure, core platforms, and SRE, but does not publicly establish that all of those systems use one monorepo.

Accordingly, the choices below are engineering recommendations derived from public evidence and general systems practice. They must not be presented as claims that a named firm uses the same tools or repository structure.

## Intended audience

This guide is for the people who design, implement, review, validate, operate, and eventually approve the platform:

- Data engineers responsible for source fidelity, normalization, lineage, revisions, and data quality.
- Quantitative researchers implementing replications, signals, factor models, risk models, and portfolio policies.
- Execution researchers modeling fills, costs, impact, financing, capacity, and venue behavior.
- Platform engineers maintaining environments, artifacts, scheduling, observability, recovery, and access controls.
- Independent reviewers verifying that research results are reproducible and free from implementation leakage.
- Portfolio managers and risk owners deciding whether a candidate is suitable for shadow, paper, or capital allocation.

The guide assumes familiarity with Python, probability, statistics, optimization, financial markets, and time-series research. Contributors to native components also need the applicable Rust or C++ knowledge. It does not assume that the reader already knows the internal platform conventions; those conventions must be explicit here and enforceable in code and build metadata.

## Design targets

The platform is intended to make the following statements demonstrably true:

1. A result can be reproduced from immutable source data, a pinned code revision, a complete configuration, and a recorded environment.
2. A historical decision uses only information that was available at the simulated decision time.
3. Research and shadow operation use the same authoritative feature, signal, risk, portfolio, accounting, and execution logic, or independently implemented components that pass the same versioned conformance suite.
4. Gross alpha, systematic exposure, financing, execution, capacity, and operational assumptions are evaluated jointly.
5. Every governed experiment that informs candidate selection, promotion, or final out-of-sample evaluation remains visible, including failed, rejected, and superseded variants.
6. A promoted model has explicit intended use, limitations, ownership, monitoring, fallback, and retirement rules.
7. Adding an asset class primarily requires new instrument definitions, data adapters, valuation engines, lifecycle rules, and venue adapters rather than changes to the research-governance core.
8. Failures are explicit. Missing data, stale risk, infeasible optimization, unavailable borrow, incomplete fills, and model degradation must not silently fall back to optimistic assumptions.
9. Every deployed program is traceable to an immutable artifact built from a source revision, build target, pinned toolchain, declared dependencies, and resolved non-secret configuration.
10. Python, Rust, and C++ components can coexist without duplicating economic rules or forcing the entire repository onto one release cycle.

## Guiding principles

### Correctness before scale

Begin with deterministic single-process implementations and small golden datasets. Distributed systems should be introduced only after profiling demonstrates a concrete throughput, latency, reliability, or isolation requirement.

### Point-in-time behavior is a platform property

Look-ahead prevention cannot depend on researcher discipline alone. Dataset joins, universe membership, feature transformations, model fitting, and evaluation splits must carry and enforce availability semantics.

### Research-production parity is tested

Shared source code is useful but not sufficient. The platform must reconcile research predictions, target positions, risk estimates, orders, fills, costs, and P&L against shadow operation. Where research and shadow use different language implementations, a versioned conformance suite and golden event streams must establish equivalent behavior within declared numerical tolerances.

### Interfaces follow economic responsibilities

Contracts should describe instruments, cashflows, valuation, risk, portfolio intent, and execution behavior. They should not merely mirror the shape of one vendor API or one starter strategy.

### Simple baselines remain permanent challengers

Observable factors, rolling PCA, linear forecasts, shrinkage covariance, rank portfolios, and transparent execution assumptions remain in the benchmark suite after more complex methods are added.

### Evidence is an artifact

Data audits, feature diagnostics, model comparisons, risk validation, optimizer diagnostics, execution attribution, capacity curves, stress results, and model cards are versioned outputs, not prose reconstructed after a decision.

## Scope

### Initial scope

- Domain-oriented monorepo with a Python-first modular implementation and explicit, tested interfaces.
- Rust or C++ targets only where profiling, safety, interoperability, or latency requirements justify native code.
- One documented build and test entrypoint, pinned toolchains and dependencies, and immutable artifact identities.
- Crypto spot and perpetual-futures data, with Binance as the first historical adapter.
- Batch ingestion before streaming; vectorized simulation before event-driven replay.
- Immutable raw data, point-in-time datasets, reproducible research runs, and complete governed trial history for formal comparison and candidate selection.
- Paper and shadow trading as production-platform capabilities.
- Parquet for analytical data and SQLite for initial metadata, with storage interfaces that permit object storage and PostgreSQL later.

### Deferred scope

- Live capital deployment and broker/exchange certification.
- Microservice decomposition, Kafka, Kubernetes, and distributed compute until workload evidence requires them.
- A low-latency native trading path until strategy requirements and measurements justify it.
- Low-latency market making, full queue-position simulation, and on-chain execution engines.
- Paid institutional datasets unless a research stage cannot be validated credibly without them.

## Architecture

```text
                             Shared core
                                 |
       +-------------------------+-------------------------+
       |                         |                         |
  Data entrypoint          Research entrypoint       Shadow entrypoint
       |                         |                         |
 bronze -> silver          point-in-time datasets     live/replayed data
       |                   features/models                  |
 metadata catalog          risk/portfolio              paper execution
       |                   backtests/reports                 |
 quality + lineage         candidate registry          reconciliation
       +-------------------------+-------------------------+
                                 |
                    artifacts, governance, telemetry
```

The three entrypoints are logical composition roots, not necessarily separate network services. They use the same authoritative domain, feature, valuation, risk, portfolio, accounting, and execution logic wherever practical. A separate implementation is allowed only when the boundary and reason are explicit, both implementations satisfy the same contract and golden tests, and their outputs are reconciled. Research-only approximations must be labeled and cannot be promoted as production-equivalent evidence.

### Data entrypoint responsibilities

The data entrypoint acquires, validates, normalizes, versions, and publishes data. It must:

1. Discover source partitions or subscribe to source streams.
2. Record source identity, request parameters, checksums, and retrieval timestamps.
3. Persist source payloads unchanged in bronze storage.
4. Normalize source records into versioned canonical events.
5. Run hard and soft data-quality checks before publication.
6. Publish silver partitions atomically and update lineage metadata.
7. Support deterministic backfill and replay using the same normalizers.
8. Expose freshness, gap, correction, and degradation state to research and shadow consumers.

The initial implementation is a CLI-driven batch process. Scheduling and streaming are later orchestration modes around the same connector and normalizer contracts.

### Research entrypoint responsibilities

The research entrypoint assembles point-in-time data and produces reviewable evidence. It must:

1. Resolve a dataset specification to immutable source and derived partitions.
2. Construct the decision-time universe and apply eligibility rules.
3. Compute features and labels using registered implementations.
4. Generate rolling train, validation, and test intervals.
5. Fit all transformations and models inside the applicable training interval.
6. Produce forecasts, residuals, risk estimates, portfolio intents, target positions, and simulated orders.
7. Run vectorized or event-driven simulation using the shared ledger and cost models.
8. Record every configuration admitted to a formal comparison, candidate-selection process, or final out-of-sample evaluation and retain the required artifacts.
9. Generate standardized data, signal, model, risk, execution, capacity, stress, and governance reports.

### Shadow entrypoint responsibilities

The shadow entrypoint exercises the production path without deploying capital. It must:

1. Consume live or replayed canonical events.
2. Build features at the same information cutoffs used in research.
3. Load a registered candidate artifact and configuration.
4. Compute forecasts, risk, and target positions using shared components.
5. Send orders to a deterministic paper-execution gateway.
6. Maintain positions, cash, margin, and P&L from execution reports.
7. Apply operational limits and kill switches.
8. Reconcile observed behavior against the candidate backtest.
9. Emit metrics, logs, traces where appropriate, alerts, and review artifacts without blocking latency-sensitive processing.

### Component-boundary rules

- Connectors may depend on vendor SDKs; domain, research, risk, and portfolio packages may not.
- Canonical domain types may not import storage, network, dataframe, optimizer, or web-framework packages.
- Features may depend on canonical datasets and declared market state, but not on connectors or future partitions.
- Models may consume registered features and labels, but may not query raw vendors directly.
- Portfolio code may consume forecasts, risk, costs, positions, and constraints, but may not place venue orders.
- Execution adapters translate canonical order intents into venue requests and execution reports; they do not decide strategy targets.
- Accounting is authoritative for positions, cash, cashflows, and realized P&L.
- Reports consume registered artifacts and do not recompute research logic independently.
- Application entrypoints compose packages; reusable business logic does not live in `apps/`.

### Runtime modes

Every pipeline run declares one of the following modes:

| Mode | Data source | Clock | Execution | Intended use |
| --- | --- | --- | --- | --- |
| Unit/golden | Tiny fixture | Deterministic test clock | Deterministic fake | Exact correctness |
| Historical research | Immutable historical partitions | Simulated | Vectorized or event-driven | Model and portfolio research |
| Historical replay | Historical canonical events | Event replay | Paper adapter | Production-path validation |
| Shadow | Live canonical events | Wall clock | Paper adapter | Operational and reconciliation evidence |
| Live | Live canonical events | Wall clock | Authorized venue adapter | Outside this guideline until separately approved |

### Execution planes

The monorepo is one source and dependency graph, not one runtime. Deployment requirements differ by plane:

- **Research plane:** interactive and batch workloads, historical data, experiment scheduling, and elastic CPU/GPU compute. Containers or a cluster scheduler may be appropriate here after measured demand exists.
- **Trading plane:** replay, shadow, paper, and any future live processes. Latency-sensitive services may require static native binaries, controlled hosts, CPU/NUMA policy, and restricted background work rather than a general container orchestrator.
- **Control plane:** artifact promotion, configuration, inventory, service discovery, secrets, dashboards, alerts, and audit history. It must remain able to stop or roll back a trading process even when that process is unhealthy.

All planes share schemas, artifact provenance, ownership metadata, and observability conventions. They do not have to share a scheduler, packaging format, release cadence, or programming language.

## Required shared contracts

### Instruments and market events

- `InstrumentId` is internal and stable; vendor symbols are aliases with effective dates.
- `ContractSpec` is versioned and supports cash, perpetual, future, option, forward, and generic cashflow instruments.
- Derivative specifications include underlying, multiplier, strike, option type, exercise style, expiration, last-trade time, settlement currency, and settlement method.
- `MarketEvent` is a typed union for trades, quotes, books, bars, fixings, settlements, funding, corporate actions, curve points, and volatility points.
- Every record distinguishes event time, first-recorded time, information-available time, and effective time.

#### Instrument invariants

- An instrument version is immutable after publication; corrections create a new recorded version.
- Tick size, lot size, multiplier, currency, and lifecycle state are effective-dated.
- An option references an underlying instrument ID, not a vendor ticker string.
- A continuous futures series is a derived research instrument and never replaces the underlying listed contracts.
- Adjusted equity series are derived datasets; raw prices and corporate-action events remain independently available.
- Instrument identity does not change when a vendor symbol changes.
- Position quantity is expressed in the instrument's native unit and converted to economic exposure through its contract specification.

#### Time semantics

| Field | Meaning | Example |
| --- | --- | --- |
| `ts_event` | Time the market or source says the event occurred | Trade exchange timestamp |
| `ts_recorded` | Time the platform first stored this version | Downloader or consumer receipt time |
| `ts_available` | Earliest time the information was usable by a strategy | Filing acceptance time plus processing delay |
| `ts_effective` | Time the event changes economic state | Split effective date or contract-parameter activation |

Point-in-time queries use `ts_available <= decision_time` and the latest record version known at the requested knowledge cutoff. `ts_event` alone is never treated as proof of availability.

### Data and lineage

- Bronze data is content-addressed and never overwritten.
- Silver data uses canonical, versioned Parquet schemas.
- Gold datasets are deterministic products of explicit dataset specifications.
- Corrections create new revisions while preserving prior recorded state.
- Every research result identifies raw partitions, dataset specification, code revision, configuration, dependencies, and random seeds.
- Data-quality failures have severity, evidence, affected partitions, and promotion consequences.

#### Storage tiers

| Tier | Contents | Mutability | Primary purpose |
| --- | --- | --- | --- |
| Bronze | Original files, packets, responses, and checksums | Append-only | Audit, correction history, reprocessing |
| Silver | Canonical events and reference data | Versioned publication | Shared research and shadow input |
| Gold | Universes, bars, features, labels, curves, surfaces, and model-ready panels | Rebuildable and content-addressed | Reproducible research artifacts |

#### Dataset specification

A dataset specification must declare at least:

- Instrument or universe source and its point-in-time eligibility rule.
- Event types, fields, source priority, and canonical schema versions.
- Event interval, decision schedule, timezone, session, and calendar.
- Start, end, lookback, warm-up, and permitted data latency.
- Adjustment, roll, missing-data, stale-data, and outlier policies.
- Information-availability cutoff and knowledge cutoff.
- Derived transformations and their registered versions.
- Expected partitions and hard/soft quality thresholds.

Resolving a specification produces a dataset manifest containing exact partition identities and content hashes. Researchers may not substitute files after resolution without creating a new dataset identity.

#### Data-quality severity

- **Informational:** recorded for audit; no effect on publication.
- **Degraded:** silver may publish, but the partition is marked and cannot support production promotion without an explicit waiver.
- **Hard failure:** silver does not publish; downstream runs fail closed.
- **Incident:** a previously published partition is found defective; affected datasets and research runs are located through lineage and marked for review.

### Research and models

- Features are pure, time-consistent functions registered by name and version.
- Labels declare horizon, observation interval, and overlap semantics.
- Scaling, neutralization, imputation, feature selection, and hyperparameters are fitted inside the training window.
- Model adapters share dataset, split, prediction, artifact, and diagnostic contracts.
- Failed and rejected governed trials remain in an append-only trial ledger. Disposable local debugging runs need not be registered unless their results influence a research decision.
- Final out-of-sample data is locked before candidate selection.

#### Registry responsibilities

| Registry | Required metadata |
| --- | --- |
| Feature | Formula, inputs, version, availability rule, units, expected range, owner |
| Label | Horizon, price convention, execution delay, overlap interval, missing policy |
| Signal | Economic mechanism, transformation, direction, decay, turnover, known risks |
| Model | Implementation, hyperparameters, training policy, features, artifact format |
| Risk model | Factors, horizon, estimator, universe, covariance/specific-risk conventions |
| Cost model | Venue, fee tier, spread, impact, participation, calibration sample |
| Portfolio policy | Objective, constraints, solver, fallback, rebalance policy |
| Candidate | Complete component versions, dataset ID, selection evidence, owner |

#### Experiment identity

An experiment run ID is derived from the resolved dataset manifest, code revision, environment identity, complete configuration, registered component versions, and random seeds. Wall-clock time is metadata and must not be part of deterministic identity.

For governed experiments, the trial ledger records the hypothesis family, researcher, parent experiment, reason for the trial, all reported metrics, outcome, and any later invalidation. Deleting or rewriting an unfavorable governed trial is prohibited; corrections append a new record and preserve the earlier one.

### Valuation, accounting, and risk

- Positions are recorded in quantities or contracts, not only portfolio weights.
- Cash is tracked by currency; FX conversion is explicit.
- Premiums, coupons, dividends, funding, variation margin, exercise, assignment, and settlement are cashflow events.
- A `ValuationEngine` maps instrument, market state, and valuation time to value, sensitivities, and cashflows.
- `MarketState` can contain spot prices, curves, volatility surfaces, FX rates, and fixings with point-in-time availability.
- Risk supports covariance forecasts and full-revaluation scenarios.
- Risk measures carry units: dollars, delta, gamma, vega, DV01, margin, liquidity, currency, or a registered custom unit.

#### Accounting identities

At every ledger timestamp, the platform must be able to reconcile:

```text
ending NAV
  = starting NAV
  + realized trading P&L
  + unrealized mark change
  + contractual cashflows
  + financing and funding
  - fees, spread, impact, and taxes
  + FX translation
```

The exact attribution taxonomy may be asset-specific, but its components must sum to the authoritative ledger change. Reports may not maintain an independent P&L calculation.

#### Valuation and market-state rules

- Every valuation identifies the price, curve, surface, fixing, FX, and convention versions it consumed.
- Observed market marks and model-derived theoretical values are distinct fields.
- Missing market-state inputs cause a declared fallback or failure; stale values are never silently accepted.
- Analytic sensitivities are checked against finite differences on bounded fixtures.
- Curves and surfaces preserve their calibration inputs and expose residuals and no-arbitrage diagnostics.
- Full-revaluation scenarios use the same valuation engine as ordinary marking.

### Strategy, portfolio, and execution

```text
market state
  -> strategy forecast or relative-value state
  -> portfolio intent
  -> risk-constrained target positions
  -> executable orders
```

- `StrategyOutput` may contain expected returns, spread forecasts, volatility mispricing, exposure targets, or a control policy.
- `PortfolioIntent` supports quantities, baskets, hedge relationships, and exposure targets.
- Constraints are dimensioned and reject incompatible units.
- Orders support single instruments and multi-leg groups with ratios and partial-leg risk.
- Venue adapters declare supported order types, sessions, auctions, combinations, RFQ, and settlement behavior.
- Margin, collateral, financing, borrow, and hedge policies are replaceable interfaces.

#### Portfolio-intent examples

- Cross-sectional equity alpha: expected returns plus beta, sector, liquidity, gross, net, position, turnover, and borrow constraints.
- Crypto residual convergence: residual scores plus venue, funding, liquidity, factor, and concentration constraints.
- Futures curve trade: target calendar-spread quantities plus DV01, expiry, roll, and margin constraints.
- FX carry: currency and forward exposures plus settlement, funding, and country limits.
- Volatility relative value: multi-leg option quantities plus delta, gamma, vega, theta, liquidity, and margin targets.
- Fixed-income curve trade: instrument quantities plus DV01, key-rate, curve, issuer, liquidity, and financing constraints.

#### Execution guarantees

- Order intents, venue orders, acknowledgements, fills, cancels, rejects, and corrections have stable unique IDs.
- Retries are idempotent and cannot create duplicate economic orders.
- Partial fills remain explicit; canceled or rejected quantity never becomes a position.
- Multi-leg fills preserve parent intent and expose temporary leg risk.
- Decision price, arrival price, fill price, fees, opportunity cost, and benchmark conventions are retained for transaction-cost analysis.
- Research execution models declare which venue behaviors they omit.

## Repository layout

Organize by economic or platform responsibility first and by language second. A global `python/`, `rust/`, or `cpp/` tree would separate implementations that share an owner and contract. The target layout is:

```text
build_defs/                  # tracked build rules, pinned toolchains, CI helpers
third_party/                 # dependency locks, patches, license metadata
schemas/                     # language-neutral market, order, risk, telemetry contracts
libs/                        # narrow shared domain and infrastructure libraries
  instruments/
  time/
  orderbook/
  valuation/
  risk/
  accounting/
  telemetry/
data/
  connectors/
  normalization/
  datasets/
  quality/
  lineage/
  fixtures/                  # tiny, reviewable fixtures; never bulk market data
research/
  sdk/
  features/
  models/
  experiments/
  notebooks/                 # interfaces and reports, not sole production logic
strategies/
  <asset-class>/<strategy>/
    core/                    # authoritative strategy logic
    simulation/              # historical adapter and scenario tests
    live_adapter/            # shadow/paper/live integration boundary
    config/
    monitoring/              # strategy dashboards, alerts, and runbooks
simulation/
  replay/
  exchange_models/
  costs/
trading/
  market_data/
  execution/
  pretrade_risk/
  reconciliation/
platform/
  compute/
  artifacts/
  deployment/
  configuration/
  service_discovery/
observability/
  exporters/
  dashboards/
  alerts/
  runbooks/
governance/                  # trial policy, model cards, promotion, audit contracts
reporting/                   # research, risk, execution, and operational reports
apps/                        # thin composition roots only
tests/                       # cross-package suites; unit tests stay with owning targets
  contract/
  integration/
  golden/
docs/                        # architecture decisions, contracts, and operator guidance
```

The initial Python implementation may keep closely related packages under one `src/alpha_research/` distribution until there is a real second deployable or language target. The conceptual ownership and dependency boundaries above still apply; empty directories and speculative services should not be scaffolded merely to resemble the target layout.

When one component needs multiple languages, keep them below the owning domain package:

```text
libs/orderbook/
  api/                       # schema and compatibility tests
  python/
  rust/
  cpp/
  tests/                     # cross-language golden and differential tests
```

Bulk data, experiment outputs, compiler outputs, deployment artifacts, and secrets do not belong in Git. The repository contains their schemas, manifests, build definitions, and retention policies.

### Dependency direction

The intended dependency direction is:

```text
schemas
  -> foundational libraries
  -> domain libraries and strategy cores
  -> simulation, data, and venue adapters
  -> application entrypoints

platform and observability consume declared interfaces and artifact metadata;
they do not own strategy economics.
```

Research code may depend on production-capable domain libraries; production targets may not depend on notebooks, ad hoc experiments, or research-only approximations. Circular package dependencies are prohibited. Build-target visibility and automated dependency checks enforce these rules. Shared helpers belong in a narrowly named package only after at least two legitimate consumers exist; a generic `utils` dumping ground should be avoided.

### Polyglot build and interoperability

- The repository exposes one root-level interface for build, test, lint, and formatting even when language-specific tools perform the underlying work.
- Every build target declares direct dependencies, owners, runtime platform, and visibility. Directory proximity does not grant dependency access.
- Python interpreters and packages, Rust toolchains and crates, C/C++ compilers and libraries, code generators, and system dependencies are pinned. Developer-machine installations are not implicit build inputs.
- Once native targets are introduced, adopt a hermetic multi-language build graph such as Bazel, Buck2, Pants, or an equivalently capable internal system through an architecture decision. Bazel is a suitable default candidate, not an assertion about a named firm's internal tooling.
- Remote caching and remote execution are scale optimizations added after build hermeticity and cache correctness are established.
- Language package managers remain useful for resolving ecosystems, but their lockfiles and outputs are inputs to the repository build graph rather than independent release authorities.
- Cross-process boundaries use versioned schemas and compatibility tests. Control-plane RPC and latency-sensitive data-plane transport may use different encodings.
- In-process Rust/C++ boundaries use a narrow stable C ABI or a reviewed interoperability layer. Do not expose STL containers, Rust-owned collections, exceptions, or allocator ownership across an undocumented ABI.
- Python bindings should expose coarse, batch-oriented native operations. Repeated fine-grained FFI calls can erase the expected performance benefit.

### Artifact and release model

The monorepo does not have one version or one firm-wide release. Each deployable target produces an independently versioned immutable artifact identified by at least:

- Source revision and build target.
- Toolchain and declared dependency digests.
- Schema and generated-code versions.
- Target platform and build mode.
- Artifact digest and provenance record.

CI builds each deployable target once. A target promoted from shadow to paper and, if separately approved, live operation keeps the same digest; it is not rebuilt from an environment branch. Historical simulation may be a different adapter target, but it must identify the exact shared-core revision or artifact and pass reconciliation against the promoted target. Environment configuration is independently versioned, validated, and linked to the deployment record. Secret values remain outside both source and artifact manifests.

### Ownership and access

- Every build target has an accountable owner and backup owner. Shared schemas, risk controls, deployment rules, and toolchains require reviews from their domain owners.
- Source-code visibility is separate from runtime authority. Permission to read or modify research code does not grant access to market-data entitlements, deployment systems, trading credentials, or capital.
- Secrets and sensitive datasets remain outside Git. Repository paths contain only references, schemas, synthetic fixtures, and access-policy metadata.
- Narrow package visibility, ownership rules, and deployment authorization limit blast radius without giving up atomic cross-component changes.
- A change to a public schema or language boundary includes compatibility, migration, and rollback evidence for every affected consumer selected from the dependency graph.

### Configuration conventions

- Configuration files are declarative and validated before data access or execution begins.
- Unknown keys are errors rather than ignored warnings.
- Defaults are explicit, versioned, and included in the resolved run configuration.
- Secrets are referenced by name and resolved at runtime; secret values never enter manifests, logs, reports, fixtures, or version control.
- Units appear in field names or typed values where ambiguity is possible, such as `fee_bps`, `latency_ms`, or `notional_usd`.
- Strategy research does not read arbitrary environment variables directly.
- Production-sensitive settings such as venues, account IDs, capital, limits, and kill-switch thresholds require environment-specific configuration and review.

### Schema evolution

- Canonical schemas carry explicit versions.
- Additive optional fields require compatibility tests across old and new readers.
- Renames, semantic changes, type changes, and unit changes require a new schema version and migration/reprocessing plan.
- Normalizers state which source versions they support.
- Previously published silver data is not edited in place to match a new schema.
- Artifact readers fail with a clear compatibility error when a required migration is unavailable.

## Merge-request policy

- Implementation MRs contain the smallest coherent change that can be implemented, tested, reviewed, and rolled back safely. There is no universal line-count limit: generated schemas, migrations, and cross-language contract changes have different review costs from ordinary source edits.
- One behavior or contract per MR where practical; broad scaffolding and opportunistic refactors are rejected.
- Every MR names one human-readable invariant and includes a deterministic acceptance test.
- Network tests use recorded fixtures in CI; a separate bounded smoke test verifies the real provider.
- Large generated, vendored, formatting-only, or mechanical changes are isolated from semantic changes and reviewed with the owning generator or transformation command.
- Binary fixtures are allowed only when a text fixture cannot exercise the relevant format and the fixture is small, non-sensitive, documented, and reproducibly generated or independently verified.
- Public interfaces require contract tests before receiving a second implementation.
- Each MR must leave all previously completed acceptance gates green.

CI selects affected targets and their reverse dependencies from the declared build graph. Repository-wide tests remain available for changes to foundational schemas, toolchains, build rules, or other high-blast-radius components and for scheduled validation.

### Required MR description

Every implementation MR description includes:

1. Its stable platform or research-replication MR ID.
2. The single behavior or contract introduced.
3. The tracked requirement or roadmap item: MR ID, week, section, or deliverable, plus the primary paper or venue specification when applicable.
4. Why the change is required and which later steps depend on it.
5. The invariant a human reviewer should verify.
6. Files and public interfaces changed.
7. Test commands, expected evidence artifact, and acceptance gate affected.
8. Failure and rollback behavior.
9. Known omissions or follow-up work.
10. Any generated or mechanical content and the command or tool that produced it.

An MR may cite more than one requirement, but it must have one primary requirement and one primary verification claim. Research-replication MRs also name the exact paper or specification being replicated, the deviations from the source design, and the artifact paths containing the result. A citation without executable evidence or a deterministic review procedure does not establish traceability.

### Review order

Reviewers should inspect changes in this order:

1. Contract and economic semantics.
2. Time, availability, units, signs, and currency conventions.
3. Failure behavior and idempotency.
4. Deterministic tests and fixtures.
5. Implementation clarity and dependency direction.
6. Metrics, lineage, and operational evidence.
7. Performance only after correctness is established.

## Implementation roadmap

Every implementation MR has a stable global ID. IDs are never reused, even if an MR is abandoned or superseded. The research-program linkage column uses `W01`-`W16` for the sixteen-week program and retains section numbers from the source planning material as provenance. The capability, human-verification statement, acceptance gate, and tracked references in this README are normative; an unavailable local source document is not required to implement or review an MR.

Platform MRs build reusable capabilities. They do not by themselves constitute completion of a research week; the research-replication MRs defined later produce the required empirical evidence.

### Wave 0: engineering spine

| MR ID | Capability | Research-program linkage | Human verification |
| --- | --- | --- | --- |
| `MR-ENG-001` | Root build interface, pinned Python environment, package import, and test smoke check | All weeks; §06.3 reproducible environments | Clean checkout installs and the smoke test passes without undeclared host dependencies |
| `MR-ENG-002` | Affected-target CI, static checks, build-graph validation, and scheduled full validation | All weeks; §06.3 CI/CD; §07.7 independent review | A leaf change tests its target and reverse dependencies; a foundational schema change selects all affected consumers |
| `MR-ENG-003` | Typed configuration, precedence, and secret references | W16; §06.3 workflow controls; §07.7 governance | Unknown keys fail and resolved non-secret configuration is complete |
| `MR-ENG-004` | Canonical identifiers, UTC, decimal precision, currency, and units | W02; §07.1 point-in-time data; §07.4 sign conventions | Invalid timestamps, units, currency, and precision fail explicitly |
| `MR-ENG-005` | Content hashing, run manifests, and deterministic run identity | W02, W15-W16; §07.1 lineage; §07.7 governance | Same inputs produce the same ID; one-byte change produces a new ID |
| `MR-ENG-006` | Atomic artifact store with idempotent lookup and retention metadata | W01-W16; §06.3 experiment tracking; §08 deliverables | Interrupted writes are invisible and retries do not duplicate artifacts |
| `MR-ENG-007` | Structured CLI results, errors, logs, and correlation IDs | W16; §07.6 operational controls; §07.7 evaluation | One run is traceable across CLI output, logs, and artifacts |

**Wave 0 exit criteria:** a clean checkout installs reproducibly; all tests and static checks run from one documented command; two identical fixture runs produce the same run and artifact identities; a one-byte configuration or input change produces a different identity; secrets and wall-clock timestamps do not affect deterministic hashes.

### Wave 1: asset-neutral domain foundation

| MR ID | Capability | Research-program linkage | Human verification |
| --- | --- | --- | --- |
| `MR-DOM-001` | Versioned `ContractSpec` hierarchy | W02, W14; §04.14; §07.1, §07.6 | Cash, perpetual, future, option, FX-forward, and cashflow fixtures round-trip |
| `MR-DOM-002` | Typed `MarketEvent` union and schema validation | W02, W13-W14; §06.3; §07.1 | Payload/type mismatches and incompatible schema versions fail |
| `MR-DOM-003` | Event, recorded, available, and effective time semantics | W02-W09; §07.1-§07.2 | A late correction cannot enter an earlier decision-time query |
| `MR-DOM-004` | Calendar, session, day-count, and settlement conventions | W01-W02, W13-W14; §06.4; §07.1, §07.6 | Known sessions, holidays, accrual dates, and settlements match fixtures |
| `MR-DOM-005` | Multi-currency cash, contract positions, and scheduled cashflows | W01, W13-W14; §07.5-§07.6 | Futures, options, funding, and FX cashflows reconcile to NAV |
| `MR-DOM-006` | `MarketState`, valuation, and sensitivity protocols | W10-W14; §04.7-§04.10, §04.14 | Cash and option reference pricers pass value and finite-difference tests |
| `MR-DOM-007` | Listing, roll, expiry, exercise, assignment, and settlement lifecycle | W02, W14; §04.11, §04.14; §07.1, §07.6 | Golden lifecycle paths produce exact positions and cashflows |
| `MR-DOM-008` | Covariance and full-revaluation scenario-risk protocols | W10, W14, W16; §04.7; §07.4, §07.7 | Linear scenario risk agrees with covariance risk in the limiting case |
| `MR-DOM-009` | Strategy output, portfolio intent, constraints, and order protocols | W01, W11-W13; §04.8-§04.10; §07.4-§07.5 | Return, spread, Greek, and quantity intents pass shared contracts |
| `MR-DOM-010` | Multi-leg orders, margin, collateral, financing, borrow, and hedges | W13-W14; §04.9, §04.11, §04.14; §07.5-§07.6 | A partially filled option spread exposes correct leg risk and margin |

**Wave 1 exit criteria:** contract fixtures represent an equity, perpetual future, dated future, European option, American option, FX forward, and fixed cashflow; their quantities, currencies, multipliers, lifecycle dates, and settlement methods survive serialization; multi-currency ledger and lifecycle golden tests reconcile without asset-specific branches in shared accounting.

### Wave 2: first end-to-end crypto research slice

| MR ID | Capability | Research-program linkage | Human verification |
| --- | --- | --- | --- |
| `MR-CRY-001` | Canonical crypto bars and funding events | W01-W03, W14; §04.14; §07.1 | Fixture values preserve event time, prices, volumes, and funding sign |
| `MR-CRY-002` | Immutable local bronze store | W02; §07.1; §08 data audit | Existing raw objects cannot be overwritten |
| `MR-CRY-003` | Binance archive download, retry, checksum, and atomic promotion | W02; §06.4; §07.1 | A bit-flipped file fails and no partial object becomes visible |
| `MR-CRY-004` | Kline and funding parsers | W01-W03, W14; §07.1, §07.6 | Known CSV rows produce exact UTC and decimal canonical events |
| `MR-CRY-005` | Silver Parquet writer and deterministic reader | W02; §06.3; §07.1 | Write/read preserves schema, ordering, timezone, and hash |
| `MR-CRY-006` | Dataset specification and 24/7 resampling | W01-W03; §07.1-§07.2 | Known minute data aggregates exactly and gaps remain explicit |
| `MR-CRY-007` | Pure feature contract and future-perturbation test | W03-W09; §07.2-§07.3 | Changing future data cannot alter prior feature values |
| `MR-CRY-008` | Minimal vectorized clock with delayed fills | W01, W13; §07.1, §07.5 | No order fills on the bar used to calculate its signal |
| `MR-CRY-009` | Position, cash, P&L, fee, and funding ledger | W01, W13-W14; §07.5-§07.6 | Hand-calculated long/short funding and trading P&L reconcile |
| `MR-CRY-010` | Baseline metrics, attribution, manifest, and report | W01, W16; §07.7; §08 baseline and OOS artifacts | Gross minus costs and funding equals reported net P&L |

**Wave 2 exit criteria:** a small Binance fixture runs raw-to-report from one CLI command; signals cannot trade on their own input bar; positive funding makes longs pay and shorts receive; gross P&L, costs, funding, and net P&L reconcile exactly; repeated runs produce identical manifests and reports.

### Wave 3: point-in-time data platform

| MR ID | Capability | Research-program linkage | Human verification |
| --- | --- | --- | --- |
| `MR-DATA-001` | Bitemporal metadata catalog and raw-revision history | W02; §07.1; §08 data audit | Actual-time and knowledge-time queries return the expected versions |
| `MR-DATA-002` | Historical archive catalog and lifecycle ingestion | W02; §04.12; §07.1 | Delisted or inactive contracts remain historically discoverable |
| `MR-DATA-003` | Mark, index, premium, trade, quote, and funding ingestion | W02-W03, W13-W14; §06.2; §07.1, §07.5 | Cross-event timestamps and instrument IDs align on a golden fixture |
| `MR-DATA-004` | Declarative quality contract and crypto quality suite | W02; §06.3; §07.1; §08 data audit | Duplicate, gap, stale, OHLC, and funding failures have correct severity |
| `MR-DATA-005` | Point-in-time reader and as-of joins | W02-W09; §07.1-§07.2 | Future revisions and releases cannot enter earlier datasets |
| `MR-DATA-006` | Time-varying universe snapshots | W01-W03; §04.12; §07.1 | Future listing and liquidity changes cannot alter earlier membership |
| `MR-DATA-007` | Data-lineage and universe-audit report | W02; §07.1; §08 data and universe audit | Every derived row resolves to canonical and raw partition identities |
| `MR-DATA-008` | Idempotent backfill, replay, interruption, and restart | W02, W16; §06.3; §07.7 | Interrupted and uninterrupted runs publish identical partitions |
| `MR-DATA-009` | Scheduled ingestion, late data, and degraded partitions | W02, W16; §06.3; §07.6-§07.7 | Late data follows declared republish and promotion-blocking rules |

**Wave 3 exit criteria:** an independent reviewer can reconstruct silver data and a historical universe from bronze manifests; future corrections, listings, liquidity, and metadata cannot alter earlier decisions at an earlier knowledge cutoff; interrupted backfills restart without duplicates or missing partitions; hard-quality failures block publication.

### Wave 4: research and model platform

| MR ID | Capability | Research-program linkage | Human verification |
| --- | --- | --- | --- |
| `MR-RES-001` | Feature, label, signal, and dataset registries | W05; §04.4-§04.5; §07.2-§07.3 | Required mechanism, horizon, availability, decay, and owner metadata is enforced |
| `MR-RES-002` | Rolling and expanding splits | W07-W09, W15; §04.6, §04.12; §07.2 | All boundaries match the declared retraining and test cadence |
| `MR-RES-003` | Purging and embargo | W07-W09, W15; §04.12; §07.2 | No training label overlaps validation or test labels |
| `MR-RES-004` | Train-only transforms, neutralization, and missing-data policies | W06, W08; §04.4-§04.5; §07.2-§07.3 | Future outliers and missing values cannot alter past fitted transforms |
| `MR-RES-005` | Factor-model protocol and observable-factor baseline | W03-W04; §04.3; §07.3 | Factor returns, exposures, and residuals reconstruct asset returns |
| `MR-RES-006` | Rolling-PCA factor baseline | W03; §04.2-§04.3; §07.3 | Deterministic sign convention and future-perturbation tests pass |
| `MR-RES-007` | Residual construction and convergence-signal pipeline | W03-W04; §04.2-§04.3 | Common plus residual return reconstructs original return within tolerance |
| `MR-RES-008` | Signal dossier and failure-mode schema | W05-W06; §04.4; §07.3; §08 signal dossier | Formula, mechanism, horizon, decay, turnover, and risks are mandatory |
| `MR-RES-009` | Common predictive-model adapter and rolling trainer | W07-W08; §04.5; §07.2 | Linear, elastic-net, tree, forest, and MLP use identical data and splits |
| `MR-RES-010` | Model bake-off, regime, stability, and long/short diagnostics | W07-W09; §04.5-§04.6; §07.3; §08 model bake-off | Same costs and constraints are used; conditional tables are predeclared |

**Wave 4 exit criteria:** observable-factor, PCA-residual, linear, regularized, tree, forest, and neural baselines can run through the same dataset and rolling-evaluation contracts; perturbing future data leaves past features, transformations, models, and predictions unchanged; all attempted configurations appear in the trial ledger.

### Wave 5: risk and portfolio platform

| MR ID | Capability | Research-program linkage | Human verification |
| --- | --- | --- | --- |
| `MR-PORT-001` | Sample and shrinkage covariance | W10; §04.7; §07.4 | Closed-form fixtures and positive-semidefinite checks pass |
| `MR-PORT-002` | Factor and sparse-residual covariance | W10; §04.3, §04.7; §07.4 | Factor-plus-residual reconstruction and sparsity tests pass |
| `MR-PORT-003` | Realized-risk, tail, concentration, and stability validation | W10; §04.7; §07.4; §08 risk validation | Forecast risk is assessed through realized portfolio outcomes |
| `MR-PORT-004` | Dimensioned portfolio constraints | W11-W12; §04.8; §07.4 | Gross, net, factor, position, liquidity, turnover, and venue limits test independently |
| `MR-PORT-005` | Static constrained optimizer | W11; §04.8; §07.4 | Units, signs, feasibility, and comparative statics pass |
| `MR-PORT-006` | Shadow prices, transfer diagnostics, and binding frequency | W11; §04.8; §07.4; §08 optimizer validation | Each binding constraint has an attributed marginal cost |
| `MR-PORT-007` | Safe fallbacks for stale, missing, or infeasible inputs | W11-W12, W16; §07.4, §07.6 | Registered fallback is deterministic and fail-safe |
| `MR-PORT-008` | Dynamic trading and multi-period optimization | W12; §04.8; §07.4-§07.5 | One-period limiting case and trading-speed comparative statics pass |
| `MR-PORT-009` | Factor, covariance, liquidity, funding, crowding, and unwind stress | W10-W16; §04.2, §04.7-§04.9; §07.4, §07.7 | Named stresses revalue the complete portfolio and reconcile losses |

**Wave 5 exit criteria:** covariance forecasts are evaluated by realized portfolio outcomes; every constraint has unit, sign, feasibility, and comparative-static tests; binding constraints expose shadow costs; infeasible or stale inputs follow a safe deterministic fallback; the dynamic optimizer trades more slowly when costs rise or alpha decays more slowly.

### Wave 6: execution, financing, and capacity

| MR ID | Capability | Research-program linkage | Human verification |
| --- | --- | --- | --- |
| `MR-EXEC-001` | Order, fill, cancel, reject, and position state machine | W13-W14, W16; §04.9-§04.11; §07.5-§07.6 | Impossible transitions and duplicate economic orders are rejected |
| `MR-EXEC-002` | Deterministic event replay and timestamp ordering | W13, W16; §04.9-§04.10; §07.5, §07.7 | Replaying identical events produces identical state and artifacts |
| `MR-EXEC-003` | Spread, fee, rebate, delay, partial-fill, and opportunity cost | W13; §04.9; §07.5 | Hand-calculated implementation-shortfall example reconciles |
| `MR-EXEC-004` | Impact, participation, urgency, and cross-impact | W13; §04.9-§04.10; §07.5 | Cost increases sensibly with size and urgency; units are explicit |
| `MR-EXEC-005` | Capacity curves across capital, participation, horizon, and stress | W13, W16; §04.9; §07.5; §08 capacity report | Every configured capital scale appears with net return and risk |
| `MR-EXEC-006` | Crypto margin, liquidation, funding, and financing | W14; §04.11, §04.14; §07.6 | Margin, funding, and forced-deleveraging fixtures reconcile |
| `MR-EXEC-007` | Transaction-cost analysis and decision-to-fill reconciliation | W13, W16; §04.9; §07.5; §08 cost model | Decision price through fill and ledger P&L reconcile exactly |
| `MR-EXEC-008` | Vectorized/event-driven parity | W13, W16; §07.5, §07.7 | Both engines agree when execution assumptions are equivalent |
| `MR-EXEC-009` | Paper execution adapter and idempotent client orders | W16; §07.5-§07.7 | Retries cannot duplicate orders; rejects and partial fills remain explicit |

**Wave 6 exit criteria:** canonical order state cannot enter an impossible transition; execution retries cannot create duplicate economic orders; vectorized and event-driven results match when assumptions match; implementation shortfall reconciles from decision price to ledger P&L; capacity is reported as a curve with uncertainty and stress, not a single number.

### Wave 7: governance, shadow production, and operations

| MR ID | Capability | Research-program linkage | Human verification |
| --- | --- | --- | --- |
| `MR-GOV-001` | Append-only governed experiment and trial ledger | W05-W16; §04.12; §07.2, §07.7 | Failed and rejected variants used in formal comparison or selection cannot be deleted or hidden |
| `MR-GOV-002` | Block bootstrap and multiple-testing corrections | W15; §04.12; §07.2, §07.7 | Dependence blocks and the complete candidate family are retained |
| `MR-GOV-003` | Frozen final-OOS dataset, configuration, and access log | W15-W16; §04.12; §07.2, §07.7; §08 OOS package | Candidate inputs cannot drift and every OOS access is recorded |
| `MR-GOV-004` | Model artifact registry and model card | W15-W16; §07.7; §08 production model card | Owner, intended use, limitations, dependencies, and thresholds are required |
| `MR-GOV-005` | Promotion state machine | W15-W16; §07.7; §08 decision rules | Invalid state transitions and missing approvals fail |
| `MR-GOV-006` | Shadow runner using authoritative or conformant production-path components | W16; §07.7; §08 OOS/model-card artifacts | Component identity or conformance-suite evidence detects unapproved research substitutes |
| `MR-GOV-007` | Backtest-to-shadow reconciliation | W16; §07.5, §07.7; §08 final OOS package | Forecast, target, order, fill, cost, and P&L differences attribute fully |
| `MR-GOV-008` | Operational kill switches | W16; §07.6-§07.7 | Stale data, risk failure, infeasibility, rejects, and P&L breaches trigger |
| `MR-GOV-009` | Metrics, logs, traces, dashboards, and alerts | W09, W16; §06.3; §07.7 | One candidate run is observable from market data through P&L |
| `MR-GOV-010` | Immutable deployment artifacts, health checks, rollback, replay, and runbooks | W16; §06.3-§06.4; §07.7 | Operator promotes one artifact digest and completes stop, rollback, replay, and recovery drills |

**Wave 7 exit criteria:** a frozen candidate can run in historical replay and shadow using the same authoritative artifacts or approved conformant components; every prediction-to-fill difference is attributable; configured kill switches are exercised in tests; an operator can identify, stop, roll back, replay, and recover a failed deployment from the runbook.

### Wave 8: asset-class adapters

| MR ID | Capability | Research-program linkage | Human verification |
| --- | --- | --- | --- |
| `MR-ASSET-001` | Equity delayed-SIP entitlement and data adapter | §04.1-§04.13; §06.1-§06.2; §07.1 | Actual entitlement is probed and adapter passes connector contracts |
| `MR-ASSET-002` | Equity sessions, IDs, corporate actions, PIT universe, and borrow gate | W02, W14; §04.11-§04.12; §07.1, §07.6 | Rename, split, delisting, and unavailable-borrow fixtures pass |
| `MR-ASSET-003` | Futures contract, roll, multiplier, margin, and delivery adapter | §04.14; §07.1, §07.5-§07.6 | Listed contracts remain intact and derived rolls reconcile |
| `MR-ASSET-004` | FX spot/forward, settlement, swap-points, and currency adapter | §04.14; §07.4-§07.6 | Spot and forward carry, settlement, cash, and translation reconcile |
| `MR-ASSET-005` | Option chain, symbology, quotes, marks, and lifecycle adapter | §04.10, §04.14; §07.1, §07.5-§07.6 | Chain identity and exercise/assignment/expiry golden tests pass |
| `MR-ASSET-006` | Curve and volatility-surface builders with arbitrage checks | §04.3, §04.7, §04.14; §07.4 | Input knots reproduce and parity/calendar/butterfly checks execute |
| `MR-ASSET-007` | Option pricer and analytic/finite-difference Greeks | §04.7-§04.10, §04.14; §07.4-§07.5 | Price identities and Greek tolerances pass across bounded fixtures |
| `MR-ASSET-008` | Fixed-income cashflows, accrual, prices, curves, and DV01 | §04.14; §07.1, §07.4-§07.6 | Cashflows, clean/dirty price, and DV01 reconcile to references |

**Wave 8 exit criteria:** each adapter passes shared connector, instrument, lifecycle, valuation, accounting, risk, portfolio, and execution contract tests; the option portability test passes; no shared research, ledger, registry, or promotion interface changes merely to accommodate an asset-class adapter.

## Research-replication MR roadmap

Platform capability and research evidence are separate concerns. The following MRs run on top of the platform and form the tracked sixteen-week replication program. Each research MR records its parent hypothesis, dataset ID, registered component versions, and all governed trial outcomes.

### Week 1: strategy map and transparent baseline

| Research MR ID | Research change | Required reading | Required evidence |
| --- | --- | --- | --- |
| `MR-REP-W01-01` | Freeze horizon, universe, decision price, delay, benchmark, and gross-to-net identity | Lehmann; Lo and MacKinlay; Hogan et al. | Signed strategy specification and accounting identity fixture |
| `MR-REP-W01-02` | Replicate a short-horizon reversal baseline | Lehmann (1990) | Published-style and corrected point-in-time/costed results |
| `MR-REP-W01-03` | Decompose contrarian profit and evaluate statistical-arbitrage conditions | Lo and MacKinlay (1990); Hogan et al. (2004) | Own-return, cross-autocovariance, lead-lag, and long-horizon profit diagnostics |

### Week 2: point-in-time data and instrument master

| Research MR ID | Research change | Required reading | Required evidence |
| --- | --- | --- | --- |
| `MR-REP-W02-01` | Audit source lineage, timestamps, revisions, and availability rules | Shumway; Chen and Zimmermann documentation | Field-level source and availability map with unresolved issues |
| `MR-REP-W02-02` | Audit identifier and instrument lifecycle history | Shumway (1997); Open Source Asset Pricing documentation | Rename, listing, delisting/expiry, status, and terminal-value tests |
| `MR-REP-W02-03` | Reconcile universe membership, missing intervals, adjustments, and terminal events | Shumway; Chen and Zimmermann | Sample counts, continuity breaks, exclusions, and point-in-time universe artifact |

### Week 3: observable factors and PCA residuals

| Research MR ID | Research change | Required reading | Required evidence |
| --- | --- | --- | --- |
| `MR-REP-W03-01` | Implement and validate transparent observable factors | Fama and French (1993) | Factor definitions, exposures, reconstruction, and stability report |
| `MR-REP-W03-02` | Select and estimate rolling latent-factor dimension | Bai and Ng (2002) | Per-window factor-count criteria and sensitivity analysis |
| `MR-REP-W03-03` | Replicate PCA and observable-factor residual convergence | Avellaneda and Lee (2010) | Residual covariance, predictability, turnover, factor contamination, and costed comparison |

### Week 4: conditional and pricing-relevant factors

| Research MR ID | Research change | Required reading | Required evidence |
| --- | --- | --- | --- |
| `MR-REP-W04-01` | Implement an IPCA conditional-factor challenger | Kelly, Pruitt, and Su (2019) | Conditional loadings, factor stability, residual alpha, and baseline comparison |
| `MR-REP-W04-02` | Implement pricing-relevant or risk-premium PCA challenger | Lettau and Pelger (2020) | Variance versus pricing-relevance comparison and residual diagnostics |
| `MR-REP-W04-03` | Evaluate candidate factors under omitted-factor risk | Giglio and Xiu (2021) | Omitted-factor-robust alpha/exposure comparison across regimes |

### Week 5: signal library and economic hypotheses

| Research MR ID | Research change | Required reading | Required evidence |
| --- | --- | --- | --- |
| `MR-REP-W05-01` | Register signal hypotheses and publication/availability dates | Green, Hand, and Zhang; Hou, Xue, and Zhang; Chen and Zimmermann | Complete dossiers with formula, mechanism, horizon, decay, missingness, turnover, and risks |
| `MR-REP-W05-02` | Reproduce a selected transparent signal set | Hou, Xue, and Zhang (2020); Chen and Zimmermann (2022) | Published, corrected, and crypto-adapted definitions with explained differences |
| `MR-REP-W05-03` | Measure signal decay, turnover, correlation, and incremental coverage | Chen and Zimmermann; Jensen, Kelly, and Pedersen; Feng, Giglio, and Xiu | Decay curves, correlation clusters, missingness, replication dispersion, and redundancy report |

### Week 6: normalization and neutralization

| Research MR ID | Research change | Required reading | Required evidence |
| --- | --- | --- | --- |
| `MR-REP-W06-01` | Compare winsorization, robust scaling, and rank transforms | Fama and MacBeth; Green, Hand, and Zhang | Train-only parameter history and sensitivity of signal shape |
| `MR-REP-W06-02` | Implement factor, industry/sector, country, liquidity, and volatility neutralization | Fama and MacBeth (1973); Kozak, Nagel, and Santosh | Pre/post exposure, residual alpha, and stability evidence |
| `MR-REP-W06-03` | Evaluate signal orthogonalization and incremental information | Feng, Giglio, and Xiu (2020) | Alpha lost, risk removed, incremental IC, and ordering-sensitivity report |

### Week 7: predictive-model benchmark matrix

| Research MR ID | Research change | Required reading | Required evidence |
| --- | --- | --- | --- |
| `MR-REP-W07-01` | Run linear and elastic-net baselines | Gu, Kelly, and Xiu (2020) | Common-split forecast, calibration, turnover, and net-portfolio metrics |
| `MR-REP-W07-02` | Run boosted-tree and random-forest challengers | Gu, Kelly, and Xiu; Freyberger et al. | Identical-data model comparison, feature stability, and capacity effects |
| `MR-REP-W07-03` | Run MLP challenger and complete common bake-off | Gu, Kelly, and Xiu (2020); Chen, Pelger, and Zhu | Seed dispersion, ablation, model stability, and locked validation ranking |

### Week 8: missing data and representation learning

| Research MR ID | Research change | Required reading | Required evidence |
| --- | --- | --- | --- |
| `MR-REP-W08-01` | Benchmark complete-case, cross-sectional, and temporal imputation | Bryzgalova, Lerner, Lettau, and Pelger (2025) | Missingness map and downstream common-objective comparison |
| `MR-REP-W08-02` | Add model-based imputation and missingness indicators | Missing Financial Data; Missing Data in Asset Pricing Panels | Leakage tests, imputation stability, and missingness-feature value |
| `MR-REP-W08-03` | Implement nonlinear latent-representation and end-to-end frontier challengers | Gu, Kelly, and Xiu (2021); Guijarro-Ordonez, Pelger, and Zanotti (2025) | Autoencoder and deep-stat-arb challengers versus PCA/IPCA on costs, borrow, turnover, stability, ablation, and interpretation |

### Week 9: conditional forecast evaluation and regimes

| Research MR ID | Research change | Required reading | Required evidence |
| --- | --- | --- | --- |
| `MR-REP-W09-01` | Build predeclared conditional performance tables | Giacomini and White; Hamilton | Performance by volatility, liquidity, trend, crowding, and event state |
| `MR-REP-W09-02` | Estimate structural-break and parameter-instability diagnostics | Bai and Perron; Andrews | Break dates, uncertainty, rolling stability, and no-hindsight interpretation |
| `MR-REP-W09-03` | Freeze live degradation and regime-response rules | Giacomini and White; Bai and Perron | Precommitted alert, de-risk, retraining, and kill thresholds |

### Week 10: covariance and risk-model validation

| Research MR ID | Research change | Required reading | Required evidence |
| --- | --- | --- | --- |
| `MR-REP-W10-01` | Compare sample and shrinkage covariance forecasts | Ledoit and Wolf (2004) | Realized risk, tail, turnover, concentration, and calibration comparison |
| `MR-REP-W10-02` | Compare factor and sparse-residual covariance forecasts | Fan, Liao, and Mincheva (2013) | Eigenstructure, residual dependence, stability, and runtime report |
| `MR-REP-W10-03` | Validate risk models through downstream portfolios | Ledoit and Wolf; POET; Jagannathan and Ma | Optimizer stability, constraint interaction, and stressed realized risk |

### Week 11: static portfolio construction

| Research MR ID | Research change | Required reading | Required evidence |
| --- | --- | --- | --- |
| `MR-REP-W11-01` | Implement rank-weighted and simple diversification baselines | DeMiguel, Garlappi, and Uppal | Baseline return, risk, turnover, concentration, and robustness |
| `MR-REP-W11-02` | Implement constrained mean-variance portfolio | Markowitz; Grinold; Clarke, de Silva, and Thorley | Objective, units, signs, feasibility, and comparative statics |
| `MR-REP-W11-03` | Attribute forecast-to-portfolio transfer and constraint costs | Clarke, de Silva, and Thorley | Transfer coefficient, shadow costs, binding frequency, and fallback evidence |

### Week 12: dynamic cost-aware trading

| Research MR ID | Research change | Required reading | Required evidence |
| --- | --- | --- | --- |
| `MR-REP-W12-01` | Replicate dynamic trading with predictable returns and costs | Garleanu and Pedersen (2013) | Trading-rate response to persistence, risk, and cost |
| `MR-REP-W12-02` | Implement multi-period constrained optimization | Boyd et al. (2017) | Horizon, terminal-value, constraint, and limiting-case tests |
| `MR-REP-W12-03` | Compare implementable efficient frontiers | Jensen, Kelly, Malamud, and Pedersen (2026) | Net frontier by risk, turnover, costs, and model class |

### Week 13: execution, impact, and capacity

| Research MR ID | Research change | Required reading | Required evidence |
| --- | --- | --- | --- |
| `MR-REP-W13-01` | Reconcile decision-to-fill implementation shortfall | Perold; Frazzini, Israel, and Moskowitz | Delay, spread, impact, opportunity cost, fee, and residual attribution |
| `MR-REP-W13-02` | Calibrate and stress execution-impact models | Almgren and Chriss (2000); Gatheral | Participation, urgency, volatility, size, and model-pathology checks |
| `MR-REP-W13-03` | Produce capacity and drawdown curves across capital | Frazzini, Israel, and Moskowitz; Detzel et al. | Net return, drawdown, participation, and uncertainty by capital scale |

### Week 14: financing, borrow, and short-side stress

| Research MR ID | Research change | Required reading | Required evidence |
| --- | --- | --- | --- |
| `MR-REP-W14-01` | Reconcile crypto funding, margin, and financing regimes | D'Avolio as financing analogue; venue specifications | Funding state, margin utilization, liquidation, and concentration report |
| `MR-REP-W14-02` | Implement historical equity-borrow study when data is available | D'Avolio (2002); Cohen, Diether, and Malloy | Availability, fee, locate, utilization, recall, and missing-not-at-random analysis |
| `MR-REP-W14-03` | Run short squeeze, fee jump, recall, margin, and funding stresses | Engelberg, Reed, and Ringgenberg (2018) | Severe but plausible short-book and financing stress report |

### Week 15: multiple testing and governance

| Research MR ID | Research change | Required reading | Required evidence |
| --- | --- | --- | --- |
| `MR-REP-W15-01` | Reconcile the complete trial family and freeze selection protocol | Lo and MacKinlay; Arnott, Harvey, and Markowitz | Trial-family manifest, degrees of freedom, selection rule, and freeze record |
| `MR-REP-W15-02` | Apply reality-check and superior-predictive-ability tests | White (2000); Hansen (2005) | Model-family-adjusted evidence with dependence-preserving resampling |
| `MR-REP-W15-03` | Apply hurdle rates and document governance decision | Harvey, Liu, and Zhu (2016); Bailey and Lopez de Prado | Corrected evidence, model card draft, reviewer findings, and kill criteria |

### Week 16: integrated OOS and shadow package

| Research MR ID | Research change | Required reading | Required evidence |
| --- | --- | --- | --- |
| `MR-REP-W16-01` | Evaluate the frozen candidate on untouched OOS | Arnott, Harvey, and Markowitz; Jensen et al. (2026) | Access log, locked results, attribution, stress, and failure analysis |
| `MR-REP-W16-02` | Run capital-convergence, crowding, and correlated-deleveraging scenarios | Shleifer and Vishny (1997); Khandani and Lo (2011); Lou and Polk (2022) | Capital withdrawal, factor overlap, liquidity withdrawal, correlated impact, and drawdown stress |
| `MR-REP-W16-03` | Deliver shadow reconciliation and PM-ready package | Jensen et al. (2026); §08 deliverable | Capacity frontier, model card, monitoring, reconciliation, and promotion decision |

## Research-program acceptance map

| Program stage | Required platform waves | Research MR range | Required evidence |
| --- | --- | --- | --- |
| Weeks 1-2: baseline and data | 0-3 | `MR-REP-W01-*` to `MR-REP-W02-*` | Reproducible costed baseline plus point-in-time data and universe audit |
| Weeks 3-9: factors, signals, ML, regimes | 4 | `MR-REP-W03-*` to `MR-REP-W09-*` | Registered models under common rolling evaluation and diagnostics |
| Weeks 10-12: risk and portfolio | 5 | `MR-REP-W10-*` to `MR-REP-W12-*` | Realized-risk validation, constraints, optimizer diagnostics, dynamic trading |
| Weeks 13-14: execution and financing | 6 | `MR-REP-W13-*` to `MR-REP-W14-*` | TCA, capacity, funding/margin, partial fills, and stress evidence |
| Weeks 15-16: governance and shadow | 7 | `MR-REP-W15-*` to `MR-REP-W16-*` | Complete trials, locked OOS, promotion package, shadow reconciliation |
| Other asset classes | 1 and 8 | Asset-specific extension MRs | New adapters pass shared contracts without core rewrites |

### Week-by-week enablement

| Week | Research objective | Required platform MR IDs | Research MR IDs | Required artifact |
| --- | --- | --- | --- | --- |
| 1 | Strategy map and transparent baseline | `MR-ENG-001`, `MR-ENG-005`-`007`; `MR-DOM-004`-`005`, `MR-DOM-009`; `MR-CRY-001`, `MR-CRY-006`, `MR-CRY-008`-`010` | `MR-REP-W01-01`-`03` | Horizon, universe, decision-price convention, gross-to-net identity, costed baseline |
| 2 | Point-in-time data and instrument master | `MR-ENG-004`-`006`; `MR-DOM-001`-`004`, `MR-DOM-007`; `MR-CRY-002`-`006`; `MR-DATA-001`-`009` | `MR-REP-W02-01`-`03` | Data-lineage map, identifier tests, timestamp audit, lifecycle and gap report |
| 3 | Observable and PCA residual baselines | `MR-CRY-006`-`007`; `MR-DATA-003`, `MR-DATA-005`-`006`; `MR-RES-002`-`007` | `MR-REP-W03-01`-`03` | Factor stability, residual covariance, turnover, residual predictability |
| 4 | Conditional and pricing-relevant factors | `MR-DATA-005`-`006`; `MR-RES-002`-`007`, `MR-GOV-001` | `MR-REP-W04-01`-`03` | Challenger comparison, omitted-factor exposure, loading stability |
| 5 | Signal library and hypotheses | `MR-DATA-005`-`006`; `MR-RES-001`-`004`, `MR-RES-008`; `MR-GOV-001` | `MR-REP-W05-01`-`03` | Versioned signal definitions, mechanisms, horizons, decay, missingness, turnover |
| 6 | Normalization and neutralization | `MR-RES-001`, `MR-RES-004`, `MR-RES-008`; `MR-GOV-001` | `MR-REP-W06-01`-`03` | Alpha removed, risk removed, orthogonalization and stability evidence |
| 7 | Predictive-model benchmark matrix | `MR-RES-002`-`004`, `MR-RES-009`-`010`; `MR-GOV-001` | `MR-REP-W07-01`-`03` | Identical-split IC, calibration, turnover, stability, and net-value comparison |
| 8 | Missing data and representation | `MR-RES-002`-`004`, `MR-RES-009`-`010`; `MR-GOV-001` | `MR-REP-W08-01`-`03` | Complete-case and imputation comparison with missingness diagnostics |
| 9 | Forecast evaluation and regimes | `MR-RES-002`-`003`, `MR-RES-010`; `MR-GOV-001`, `MR-GOV-009` | `MR-REP-W09-01`-`03` | Volatility, liquidity, trend, crowding, and break-condition tables |
| 10 | Risk model | `MR-DOM-008`; `MR-PORT-001`-`003`, `MR-PORT-009` | `MR-REP-W10-01`-`03` | Calibration, tails, concentration, eigenstructure, optimizer stability |
| 11 | Static portfolio construction | `MR-DOM-009`; `MR-PORT-003`-`007` | `MR-REP-W11-01`-`03` | Transfer coefficient, constraint costs, feasibility and fallback evidence |
| 12 | Dynamic cost-aware trading | `MR-DOM-009`; `MR-PORT-004`-`008` | `MR-REP-W12-01`-`03` | Trading-speed comparative statics and net-value comparison |
| 13 | Execution, impact, and capacity | `MR-DOM-009`-`010`; `MR-EXEC-001`-`005`, `MR-EXEC-007`-`008` | `MR-REP-W13-01`-`03` | Implementation shortfall and net frontier across capital scales |
| 14 | Borrow, financing, and short-side stress | `MR-DOM-005`, `MR-DOM-007`, `MR-DOM-010`; `MR-EXEC-001`, `MR-EXEC-006`; `MR-ASSET-002` | `MR-REP-W14-01`-`03` | Financing attribution, availability, squeeze, margin, and concentration stress |
| 15 | Multiple testing and governance | `MR-ENG-005`-`006`; `MR-RES-002`-`003`; `MR-GOV-001`-`005` | `MR-REP-W15-01`-`03` | Locked selection protocol, research degrees of freedom, independent review record |
| 16 | Integrated OOS and shadow package | `MR-ENG-003`, `MR-ENG-005`-`007`; `MR-PORT-007`, `MR-PORT-009`; `MR-EXEC-001`-`009`; `MR-GOV-003`-`010` | `MR-REP-W16-01`-`03` | Untouched OOS, attribution, capacity, stress, model card, shadow reconciliation |

The program may pause at any week if its required platform capability or evidence is incomplete. A later research week must not be used to justify bypassing an earlier data, accounting, or governance gate.

## Research-program traceability

The research program is a set of evidence requirements, not merely a software backlog. The platform MR IDs identify reusable enabling code. The `MR-REP-*` IDs identify the empirical work that closes a research requirement. A paper-based replication is complete only when the cited research MR's evidence is reproducible; merging its supporting platform code is necessary but insufficient.

### Core 32 reading-to-MR crosswalk

| # | Core reading and desk purpose | Primary platform support | Research evidence MR IDs |
| --- | --- | --- | --- |
| 1 | Lehmann (1990), short-horizon reversal baseline | `MR-CRY-006`-`010` | `MR-REP-W01-02` |
| 2 | Lo and MacKinlay (1990), return-dependence decomposition | `MR-RES-002`-`004`, `MR-CRY-010` | `MR-REP-W01-03` |
| 3 | Shleifer and Vishny (1997), capital and convergence risk | `MR-PORT-009`, `MR-EXEC-005`, `MR-GOV-008` | `MR-REP-W16-02` |
| 4 | Hogan, Jarrow, Teo, and Warachka (2004), formal statistical-arbitrage definition | `MR-ENG-005`-`006`, `MR-CRY-010`, `MR-GOV-001` | `MR-REP-W01-01`, `MR-REP-W01-03` |
| 5 | Avellaneda and Lee (2010), factor-residual stat-arb baseline | `MR-RES-005`-`007` | `MR-REP-W03-03` |
| 6 | Khandani and Lo (2011), correlated-deleveraging case study | `MR-PORT-009`, `MR-EXEC-004`-`005` | `MR-REP-W16-02` |
| 7 | Lou and Polk (2022), arbitrage-crowding state variable | `MR-RES-010`, `MR-PORT-009`, `MR-EXEC-005` | `MR-REP-W09-01`, `MR-REP-W16-02` |
| 8 | Guijarro-Ordonez, Pelger, and Zanotti (2025), end-to-end frontier challenger | `MR-RES-009`-`010`, `MR-PORT-008`, `MR-GOV-001` | `MR-REP-W08-03`, `MR-REP-W16-01` |
| 9 | Fama and French (1993), transparent observable-factor baseline | `MR-RES-005` | `MR-REP-W03-01` |
| 10 | Bai and Ng (2002), latent-factor dimension selection | `MR-RES-006` | `MR-REP-W03-02` |
| 11 | Kelly, Pruitt, and Su (2019), conditional factor model | `MR-RES-005`, `MR-RES-007` | `MR-REP-W04-01` |
| 12 | Lettau and Pelger (2020), pricing-relevant latent factors | `MR-RES-005`-`007` | `MR-REP-W04-02` |
| 13 | Giglio and Xiu (2021), omitted-factor-robust evaluation | `MR-RES-005`, `MR-RES-010` | `MR-REP-W04-03` |
| 14 | Gu, Kelly, and Xiu (2021), nonlinear latent representation | `MR-RES-009`-`010` | `MR-REP-W08-03` |
| 15 | Fama and MacBeth (1973), cross-sectional diagnostics | `MR-RES-004`, `MR-RES-008`, `MR-RES-010` | `MR-REP-W06-01`, `MR-REP-W06-02` |
| 16 | Hou, Xue, and Zhang (2020), large anomaly replication | `MR-RES-001`, `MR-RES-008` | `MR-REP-W05-02` |
| 17 | Chen and Zimmermann (2022), open signal-data/code benchmark | `MR-DATA-005`-`007`, `MR-RES-001`, `MR-RES-008` | `MR-REP-W05-01`, `MR-REP-W05-02` |
| 18 | Jensen, Kelly, and Pedersen (2023), global replication discipline | `MR-ENG-005`-`006`, `MR-GOV-001` | `MR-REP-W05-03`, `MR-REP-W15-01` |
| 19 | Gu, Kelly, and Xiu (2020), machine-learning benchmark matrix | `MR-RES-002`-`004`, `MR-RES-009`-`010` | `MR-REP-W07-01`-`03` |
| 20 | Chen, Pelger, and Zhu (2024), no-arbitrage deep-factor model | `MR-RES-005`, `MR-RES-009`-`010` | `MR-REP-W07-03`, `MR-REP-W08-03` |
| 21 | Bryzgalova, Lerner, Lettau, and Pelger (2025), systematic missing-data treatment | `MR-RES-004`, `MR-RES-009`-`010` | `MR-REP-W08-01`, `MR-REP-W08-02` |
| 22 | Ledoit and Wolf (2004), covariance-shrinkage baseline | `MR-PORT-001`, `MR-PORT-003` | `MR-REP-W10-01` |
| 23 | Fan, Liao, and Mincheva (2013), factor plus sparse-residual risk | `MR-PORT-002`-`003` | `MR-REP-W10-02`, `MR-REP-W10-03` |
| 24 | Garleanu and Pedersen (2013), dynamic cost-aware trading | `MR-PORT-008` | `MR-REP-W12-01` |
| 25 | Boyd et al. (2017), multi-period constrained optimizer | `MR-PORT-004`-`008` | `MR-REP-W12-02` |
| 26 | Jensen, Kelly, Malamud, and Pedersen (2026), net-of-cost ML portfolio frontier | `MR-PORT-008`, `MR-EXEC-005`, `MR-GOV-003` | `MR-REP-W12-03`, `MR-REP-W16-01` |
| 27 | Almgren and Chriss (2000), execution risk-impact benchmark | `MR-EXEC-003`-`004` | `MR-REP-W13-02` |
| 28 | Frazzini, Israel, and Moskowitz (2018), institutional trading-cost evidence | `MR-EXEC-003`-`005`, `MR-EXEC-007` | `MR-REP-W13-01`, `MR-REP-W13-03` |
| 29 | D'Avolio (2002), stock-loan market foundation | `MR-DOM-010`, `MR-EXEC-006`, `MR-ASSET-002` | `MR-REP-W14-02` |
| 30 | Engelberg, Reed, and Ringgenberg (2018), recall and squeeze tail risk | `MR-PORT-009`, `MR-EXEC-006` | `MR-REP-W14-03` |
| 31 | White (2000), data-snooping correction | `MR-GOV-001`-`002` | `MR-REP-W15-02` |
| 32 | Harvey, Liu, and Zhu (2016), factor-zoo hurdle rates | `MR-GOV-001`-`002`, `MR-GOV-005` | `MR-REP-W15-03` |

This crosswalk assigns every Core 32 reading to evidence work, but it does not imply equal implementation size. Foundational papers usually define a deterministic baseline or diagnostic. Frontier papers remain challengers and cannot displace transparent baselines without passing the same data, cost, borrow, risk, capacity, and governance tests.

### Annotated research-problem crosswalk

| Research-program section | Platform MR families | Primary research MR IDs | Completion evidence |
| --- | --- | --- | --- |
| §04.1 Foundations: predictability and limits to arbitrage | `MR-CRY-*`, `MR-RES-002`-`004`, `MR-GOV-001` | `MR-REP-W01-*`, `MR-REP-W16-02` | Transparent baseline, formal profit decomposition, and convergence-capital stress |
| §04.2 Core statistical arbitrage, residual trading, and crowding | `MR-RES-005`-`007`, `MR-RES-010`, `MR-PORT-009` | `MR-REP-W03-03`, `MR-REP-W09-01`, `MR-REP-W16-02` | Residual reconstruction, convergence diagnostics, crowding state, and unwind stress |
| §04.3 Factor models and latent representations | `MR-RES-005`-`007`, `MR-RES-009`-`010`, `MR-PORT-002` | `MR-REP-W03-*`, `MR-REP-W04-*`, `MR-REP-W08-03` | Observable, PCA, IPCA, pricing-relevant, and nonlinear challenger comparison |
| §04.4 Cross-sectional signals and anomaly replication | `MR-RES-001`, `MR-RES-004`, `MR-RES-008` | `MR-REP-W05-*`, `MR-REP-W06-*` | Versioned hypotheses, corrected replications, decay, neutralization, and incremental value |
| §04.5 Machine learning and high-dimensional prediction | `MR-RES-002`-`004`, `MR-RES-009`-`010` | `MR-REP-W07-*`, `MR-REP-W08-*` | Common-split model bake-off, leakage checks, ablations, seeds, and net utility |
| §04.6 Forecast evaluation and regime instability | `MR-RES-002`-`003`, `MR-RES-010`, `MR-GOV-009` | `MR-REP-W09-*` | Conditional forecast tables, structural breaks, and precommitted degradation rules |
| §04.7 Risk models and covariance estimation | `MR-DOM-008`, `MR-PORT-001`-`003`, `MR-PORT-009` | `MR-REP-W10-*` | Forecast-versus-realized risk, tail, stability, concentration, and stress |
| §04.8 Portfolio construction and dynamic trading | `MR-DOM-009`, `MR-PORT-004`-`008` | `MR-REP-W11-*`, `MR-REP-W12-*` | Baseline and optimized portfolios, shadow costs, fallbacks, and dynamic response |
| §04.9 Transaction costs, impact, execution, and capacity | `MR-EXEC-001`-`009` | `MR-REP-W13-*` | Implementation-shortfall reconciliation, calibrated impact, and capacity curves |
| §04.10 Market microstructure and intraday alpha | `MR-DATA-003`, `MR-EXEC-001`-`004`, `MR-EXEC-007` | `MR-REP-W13-01`, `MR-REP-W13-02` | Timestamp/order-state correctness and decision-to-fill evidence; queue models require later extension MRs |
| §04.11 Short selling, borrow, and financing | `MR-DOM-010`, `MR-EXEC-006`, `MR-ASSET-002` | `MR-REP-W14-*` | Historical availability/fees or crypto funding analogue plus severe short-side stress |
| §04.12 Backtest integrity, multiple testing, and research governance | `MR-DATA-005`-`006`, `MR-RES-002`-`003`, `MR-GOV-001`-`010` | `MR-REP-W15-*`, `MR-REP-W16-01`, `MR-REP-W16-03` | Complete trial ledger, locked OOS, independent review, model card, and shadow reconciliation |
| §04.13 Alternative data, text, and economic networks | `MR-DATA-001`, `MR-DATA-004`-`007`, `MR-RES-001`, `MR-RES-004` | Strategy-specific extension MRs | Timestamped availability, entity/link history, ablations, incremental value, and licensed reproducibility |
| §04.14 Cross-asset extensions | `MR-DOM-*`, `MR-ASSET-*` | Asset-specific extension MRs | Shared-contract, lifecycle, accounting, valuation, risk, execution, and promotion tests |

Section §04.13 and specialized intraday queue modeling are intentionally not mandatory for the first crypto stat-arb candidate. When introduced, their research IDs use the next allocated extension sequence and must point back to the relevant §04 row, §07 controls, and §08 artifact; they may not be folded invisibly into an existing MR.

### Minimum institutional specification crosswalk

| Requirement | Primary platform MR IDs | Evidence-producing research MR IDs | Blocking gate |
| --- | --- | --- | --- |
| §07.1 Point-in-time data and universe | `MR-ENG-004`-`006`, `MR-DOM-001`-`004`, `MR-DOM-007`, `MR-DATA-001`-`009` | `MR-REP-W02-*` | Data gate |
| §07.2 Labels, splits, and model selection | `MR-RES-001`-`004`, `MR-RES-009`, `MR-GOV-001`-`003` | `MR-REP-W07-*`, `MR-REP-W08-*`, `MR-REP-W15-01` | Research and governance gates |
| §07.3 Alpha diagnostics | `MR-RES-005`-`010` | `MR-REP-W03-*` to `MR-REP-W09-*` | Research gate |
| §07.4 Risk model and portfolio construction | `MR-DOM-008`-`009`, `MR-PORT-001`-`009` | `MR-REP-W10-*` to `MR-REP-W12-*` | Portfolio gate |
| §07.5 Costs, execution, and capacity | `MR-CRY-008`-`009`, `MR-EXEC-001`-`009` | `MR-REP-W13-*`, `MR-REP-W16-03` | Execution gate |
| §07.6 Borrow, funding, and operational constraints | `MR-DOM-005`, `MR-DOM-007`, `MR-DOM-010`, `MR-EXEC-006`, `MR-EXEC-009`, `MR-GOV-008`, `MR-ASSET-002` | `MR-REP-W14-*`, `MR-REP-W16-03` | Execution and production gates |
| §07.7 Evaluation and governance | `MR-ENG-005`-`007`, `MR-PORT-009`, `MR-GOV-001`-`010` | `MR-REP-W15-*`, `MR-REP-W16-*` | Governance and production gates |

No research candidate may graduate merely because all its week-specific MRs merged. Each §07 row is a blocking control, and the MR evidence must be reviewed against the named gate before promotion.

### Required-deliverable crosswalk

| §08 artifact | Platform MR IDs that produce or govern it | Research MR IDs that populate it | Human promotion check |
| --- | --- | --- | --- |
| Data and universe audit | `MR-DATA-001`-`009` | `MR-REP-W02-*` | No unresolved lookahead or unexplained discontinuity; versions pinned |
| Baseline replication | `MR-CRY-006`-`010` | `MR-REP-W01-*` | Published-style and corrected costed results reproduce independently |
| Signal dossier | `MR-RES-001`, `MR-RES-008` | `MR-REP-W05-*`, `MR-REP-W06-*` | Formula, timing, mechanism, decay, asymmetry, risks, and incremental value present |
| Model bake-off | `MR-RES-002`-`004`, `MR-RES-009`-`010` | `MR-REP-W07-*`, `MR-REP-W08-*` | Locked net portfolio utility and stability, not in-sample fit, select the model |
| Risk model validation | `MR-DOM-008`, `MR-PORT-001`-`003` | `MR-REP-W10-*` | Realized risk is calibrated and optimizer behavior is stable with limitations documented |
| Optimizer validation | `MR-PORT-004`-`008` | `MR-REP-W11-*`, `MR-REP-W12-*` | Units/signs, feasibility, shadow prices, comparative statics, and fallback pass |
| Execution and cost model | `MR-EXEC-001`-`004`, `MR-EXEC-007`-`008` | `MR-REP-W13-01`, `MR-REP-W13-02` | Backtest assumptions reconcile to observed shadow fills with uncertainty |
| Borrow and short report | `MR-DOM-010`, `MR-EXEC-006`, `MR-ASSET-002` | `MR-REP-W14-*` | Short book survives severe plausible fee, funding, recall, squeeze, and margin states |
| Capacity and crowding report | `MR-PORT-009`, `MR-EXEC-004`-`005` | `MR-REP-W13-03`, `MR-REP-W16-02` | Proposed capital is below average and stressed capacity limits |
| Final OOS package | `MR-GOV-003`, `MR-GOV-006`-`007` | `MR-REP-W16-01`, `MR-REP-W16-03` | Locked statistical, economic, operational, stress, and drawdown criteria pass |
| Production model card | `MR-GOV-004`-`005`, `MR-GOV-008`-`010` | `MR-REP-W15-03`, `MR-REP-W16-03` | Research, PM, risk, execution, technology, and governance approvals are complete |

### §08.1 decision-rule ownership

| Decision question | Principal MR evidence | Fail or de-risk trigger |
| --- | --- | --- |
| Is the alpha real? | `MR-REP-W01-*`, `MR-REP-W05-*`, `MR-REP-W09-*`, `MR-REP-W15-*`, `MR-REP-W16-01` | Sign or ordering depends on one period, tail, survivor universe, or post-hoc cleaning |
| Is it incremental? | `MR-REP-W05-03`, `MR-REP-W06-03`, `MR-REP-W11-03` | Standalone value disappears after existing signals, netting, and constraints |
| Is it implementable? | `MR-REP-W12-*`, `MR-REP-W13-*`, `MR-REP-W14-*` | Turnover, impact, delay, financing, or unavailable shorts consume the gross result |
| Is risk understood? | `MR-REP-W09-*`, `MR-REP-W10-*`, `MR-REP-W14-03`, `MR-REP-W16-02` | Neutrality relies only on historical beta or average volatility |
| Is complexity justified? | `MR-REP-W07-*`, `MR-REP-W08-*`, `MR-REP-W12-03` | Gain is caused by leakage, missingness artifacts, unstable features, seeds, or uncosted turnover |
| Can it be operated? | `MR-REP-W02-*`, `MR-REP-W15-03`, `MR-REP-W16-03` | Pipeline needs manual fixes, unavailable historical inputs, or unobservable live states |

## Acceptance gates

1. **Foundation gate:** clean install, deterministic identities, contract fixtures, build-graph validation, and affected-target CI pass.
2. **Data gate:** raw-to-silver reproduction, revision retention, point-in-time queries, and historical universe tests pass.
3. **Research gate:** future perturbations do not change past features, transforms, models, or membership.
4. **Accounting gate:** cash, positions, fees, funding, settlement, and P&L reconcile exactly on golden fixtures.
5. **Portfolio gate:** every constraint has unit tests, comparative statics, diagnostics, and a safe fallback.
6. **Execution gate:** vectorized and event-driven engines agree under equivalent assumptions; TCA reconciles.
7. **Governance gate:** all trials remain visible and final OOS inputs are frozen before evaluation.
8. **Production gate:** shadow results reconcile, kill switches work, and rollback/replay drills pass.
9. **Cross-asset gate:** adapters add asset-specific definitions and engines without changing shared research or governance contracts.

## Test strategy

### Unit tests

Unit tests cover pure economic and mathematical behavior with small explicit inputs. Priority cases include:

- Timestamp boundaries, availability predicates, timezone conversion, and session transitions.
- Quantity, multiplier, currency, unit, sign, and rounding conventions.
- Corporate actions, futures rolls, funding, expiry, exercise, assignment, and settlement.
- Feature, label, transformation, and split behavior.
- Accounting identities and P&L attribution.
- Constraint evaluation, optimizer feasibility, and fallback selection.
- Order-state transitions and idempotency.
- Pricing identities, curve/surface interpolation, sensitivities, and scenario revaluation.

### Contract tests

Every replaceable interface has a reusable conformance suite. An implementation is not considered compatible because it type-checks; it must pass behavioral tests covering ordering, idempotency, failure semantics, metadata, lineage, and declared capabilities.

Required contract suites include:

- Market-data connector and normalizer.
- Bronze/silver storage and point-in-time reader.
- Instrument and lifecycle provider.
- Feature, label, transformation, model, and factor model.
- Valuation, curve, volatility surface, sensitivity, and scenario risk.
- Cost, financing, borrow, margin, optimizer, and hedge policy.
- Venue and paper-execution adapter.
- Artifact store, registry, and promotion workflow.

### Integration tests

Integration tests exercise bounded workflows across packages:

- Source fixture -> bronze -> silver -> dataset manifest.
- Dataset -> features -> model -> forecast artifact.
- Forecast -> risk -> portfolio intent -> target positions.
- Target positions -> simulated orders -> fills -> ledger -> report.
- Candidate artifact -> historical replay -> paper gateway -> reconciliation.
- Data correction -> lineage impact -> invalidation and rebuild.

External services are replaced with deterministic fakes, local processes, containers, or recorded responses in CI as appropriate. Live provider smoke tests are bounded, non-destructive, separately labeled, and never required for ordinary unit-test execution.

### Golden tests

Golden datasets are intentionally tiny and human-auditable. Expected outputs should be independently calculated or reviewed before being frozen. Golden tests are appropriate for:

- Point-in-time universe membership.
- As-of joins and data revisions.
- End-to-end P&L and cashflow reconciliation.
- Futures roll and settlement.
- Option exercise, assignment, expiration, and delta hedging.
- Risk constraints and optimizer fallbacks.
- Backtest-to-shadow reconciliation.

Golden outputs are updated only when the economic contract intentionally changes. A bulk snapshot update without an explanation is not acceptable review evidence.

### Property and metamorphic tests

Where exact expected values are insufficient, test invariants such as:

- Perturbing future data cannot change past datasets, features, models, or decisions.
- Increasing fees or spread cannot improve net P&L with unchanged trades.
- Scaling all portfolio quantities scales linear P&L and risk consistently before nonlinear costs or limits.
- Reordering equal-content input partitions cannot change deterministic outputs.
- Retrying an idempotent operation cannot change economic state.
- Equivalent currency representations yield equivalent base-currency NAV.
- Analytic sensitivities converge to finite-difference sensitivities as shock size decreases.
- A one-period multi-period optimizer reduces to the static formulation under equivalent assumptions.

### Performance tests

Performance tests begin only after correctness gates pass. Benchmarks record dataset size, event count, instruments, toolchain, artifact digest, hardware, runtime, peak memory, and code revision. Regression gates for latency-sensitive targets run on controlled hardware with pinned power, CPU, NUMA, and background-load policy; results from arbitrary shared CI hosts are diagnostic only. A performance optimization must preserve golden results or document an explicitly accepted numerical tolerance.

## Operational requirements

### Idempotency and replay

- Ingestion, normalization, publication, scheduling, order submission, reconciliation, and reporting have stable idempotency keys.
- An interrupted job can resume from recorded state or restart safely.
- Replaying canonical events produces the same state for a fixed code and configuration identity.
- Corrections and cancel/error events are processed explicitly rather than dropped.
- Operators can identify which datasets, experiments, candidates, and reports depend on a defective partition.

### Observability

At minimum, expose:

- Source and canonical data freshness by venue, event type, and instrument.
- Missing partitions, sequence gaps, correction counts, rejected records, and degraded quality state.
- Dataset-build, feature, model, optimizer, and report durations and failure counts.
- Feature and prediction distributions, missingness, model age, and candidate version.
- Gross, net, factor, liquidity, currency, Greek, DV01, margin, and concentration exposures as applicable.
- Orders, acknowledgements, fills, cancels, rejects, fill ratios, latency, slippage, and implementation shortfall.
- P&L, funding, financing, fees, impact, drawdown, reconciliation residual, and kill-switch state.

Metrics use stable names and units. High-cardinality identifiers belong in logs or traces rather than unbounded metric labels. Telemetry identifies the source revision, artifact digest, strategy or service, configuration version, environment, region, venue, and host where applicable.

Latency-sensitive components publish telemetry through bounded, non-blocking paths such as counters or ring buffers drained by a separate thread or process. Observability backpressure must not block market-data handling, risk enforcement, order submission, or a kill switch. Dropped telemetry is itself measured and alerted.

### Failure and degradation policy

Each application defines behavior for missing data, stale data, unavailable metadata, schema mismatch, storage failure, model load failure, stale risk, optimizer infeasibility, venue reject, incomplete fill, and reconciliation breach. Permitted actions are fail, pause, degrade with an explicit flag, use a registered fallback, or flatten through an authorized process. Silent continuation is not permitted.

### Recovery and rollback

- Data publication is atomic and previous valid versions remain addressable.
- Candidate promotion is reversible without deleting evidence.
- Application deployments retain a known-good artifact and compatible configuration; the artifact may be a native binary, archive, package, or container image.
- State recovery procedures identify the authoritative event and ledger sources.
- Runbooks include detection, containment, rollback, replay, reconciliation, escalation, and post-incident evidence.
- Recovery drills use test or paper environments and record observed recovery time and unresolved gaps.

## Security and access controls

- Secrets are stored outside the repository and resolved through a documented provider.
- Least-privilege credentials separate historical data, live data, paper execution, and any future live execution.
- Research processes do not receive trading credentials.
- Production candidate artifacts and promotion actions have authenticated ownership and audit history.
- Sensitive account, position, order, and vendor-entitlement data is not included in public fixtures or logs.
- Toolchains, dependency versions, and any container bases are pinned and scanned through the approved CI process.
- Destructive data operations require explicit targets, authorization, and recoverable backups or version history.
- Live execution, withdrawals, custody, and key-management controls require a separate security design and approval.

## Data-source policy

Before adopting a source, document:

1. Provider and legal/entitlement terms.
2. Markets, venues, instruments, fields, conditions, and historical depth.
3. Timestamp origin, precision, timezone, latency, and correction behavior.
4. Identifier, lifecycle, corporate-action, roll, and delisting coverage.
5. Trade/quote filtering, aggregation, adjustment, and bar-construction rules.
6. Availability limits, rate limits, retention, outages, and backfill procedure.
7. Known survivorship, revision, coverage, or venue-selection biases.
8. Checksum, reconciliation, and independent comparison procedure.
9. Whether the source is sufficient for engineering tests, exploratory research, shadow operation, or production evidence.

A free source may be sufficient for connector development or medium-frequency research without being sufficient for institutional promotion. Source quality classifications must remain visible in dataset and candidate manifests.

### Initial provider choices

| Purpose | Initial source | Intended classification | Important limitation |
| --- | --- | --- | --- |
| Crypto spot and USD-M futures history | [Binance public data](https://github.com/binance/binance-public-data) | Engineering and medium-frequency research | Single-venue history; historical reference metadata must be reconstructed and snapshotted |
| Crypto current contract metadata and funding | Binance public market-data APIs | Engineering, research, and forward snapshots | Current exchange information is not a historical instrument master |
| U.S. equity bars/trades/quotes | [Alpaca Market Data](https://docs.alpaca.markets/us/docs/about-market-data-api) after entitlement probe | Adapter development and conditional research | Free-feed entitlement and consolidated coverage must be verified; price data does not solve universe or borrow history |
| Crypto options market state | [Deribit public API](https://docs.deribit.com/) plus platform capture | Adapter and options portability research | Long historical depth and correction behavior must be assessed before institutional claims |
| Exchange and contract rules | Official venue specifications | Authoritative reference | Rules are versioned and must be snapshotted with effective dates |

The platform must not encode provider-specific field names or identifiers outside connectors, normalizers, and source-reference metadata.

## Asset-class extension requirements

### Equities

Equity support requires exchange sessions and auctions, historical identifiers, share classes, currencies, corporate actions, delistings, point-in-time universes, adjusted and unadjusted series, short-sale constraints, borrow availability, fees, recalls, and jurisdiction-specific rules. A static liquid-ETF experiment verifies portability but does not validate security-level institutional equity research.

### Futures and commodities

Futures support requires contract multipliers, tick values, listed expiries, last-trade and delivery dates, settlement method, variation margin, roll conventions, continuous-series derivation, spread instruments, delivery risk, and contract-specific calendars. Research must retain listed-contract history even when using a derived continuous series.

### FX

FX support requires base/quote currency semantics, spot dates, holiday-center combinations, settlement instructions, forwards and swap points, broken dates, funding curves, cross-currency conversion, and counterparty/venue conventions. P&L and risk must distinguish trading return from carry and currency translation.

### Options and volatility

Options support requires complete contract identity, option chain construction, underlying and forward linkage, discounting, exercise style, settlement, corporate-action adjustment, implied-volatility inversion, surfaces, Greeks, multi-leg intent, delta hedging, margin, assignment, and expiration. Risk validation relies on full revaluation and cannot be reduced to covariance alone.

### Fixed income and rates

Fixed-income support requires cashflow schedules, day-count, business-day adjustment, accrued interest, clean/dirty price, settlement lag, calendars, discount and projection curves, fixings, coupon/reset state, issuer and seniority, calls or other embedded options, financing, and DV01/key-rate/scenario risk. Curve construction and instrument valuation must be separate registered components.

### Market making and low latency

The shared data, artifacts, governance, accounting, and monitoring layers are reusable, but market making requires a dedicated subsystem for L2/L3 order-book reconstruction, queue priority, exchange sequence recovery, latency distributions, cancel/replace behavior, adverse selection, inventory control, and venue-specific throttles. Do not force these concerns into the medium-frequency simulator.

### DeFi and on-chain markets

The shared research and governance layers may be reused, but execution requires block height and finality, chain reorganizations, gas, nonce handling, wallet and custody state, AMM pool mathematics, oracle state, smart-contract events, MEV, bridging, and transaction-failure semantics. This is a specialized execution and accounting adapter family, not a minor venue connector.

## Options and volatility portability test

The cross-asset gate must include an end-to-end option strategy that:

1. Reconstructs a point-in-time option chain and volatility surface.
2. Validates put-call parity, calendar consistency, and butterfly convexity.
3. Forms a multi-leg, delta-hedged, vega-targeted portfolio intent.
4. Simulates option fills, partial-leg exposure, and subsequent hedge trades.
5. Accounts for premiums, fees, financing, margin, exercise, and settlement.
6. Attributes P&L to delta, gamma, vega, theta, execution, financing, and residual.
7. Revalues under spot, volatility, skew, term-structure, liquidity, and margin shocks.
8. Runs through research, final OOS, shadow, and paper entrypoints using the same contracts and authoritative or conformant economic logic, with only environment adapters changing.

An asset-specialized or breaking modification to the shared ledger, dataset engine, backtest clock, registry, or promotion workflow fails the portability test and requires an abstraction review. An additive change that expresses a genuinely asset-neutral capability may proceed after contract and regression review.

### Required options-portability evidence

- Instrument audit covering underlying linkage, strikes, expiries, exercise style, multiplier, settlement, and lifecycle state.
- Point-in-time option-chain and market-state manifest.
- Surface calibration inputs, residuals, interpolation method, and no-arbitrage diagnostics.
- Analytic and finite-difference Greek comparison within declared tolerances.
- Multi-leg target, constraint, order, partial-fill, and hedge history.
- Premium, mark, realized/unrealized P&L, fee, financing, margin, exercise, and settlement reconciliation.
- P&L explain for delta, gamma, vega, theta, curve/rate, execution, financing, and residual.
- Scenario cube covering underlying gaps, volatility level, skew, term structure, correlation, liquidity, and margin.
- Vectorized/event replay comparison under aligned assumptions.
- Historical-research/shadow comparison using the same registered artifacts or approved conformant components.

## Research and promotion governance

### Research stages

| State | Meaning | Minimum requirement |
| --- | --- | --- |
| Exploration | Idea is being investigated | Registered hypothesis; governed runs begin when results enter formal comparison or selection |
| Replication | Published or internal baseline is reproduced | Source specification, known differences, reproducible artifact |
| Candidate research | Model competes under common evaluation | Point-in-time data, common splits, costs, risk, portfolio and stress |
| Frozen candidate | Selection is complete | Immutable dataset, configuration, code, artifacts and decision rules |
| Final OOS | Frozen candidate is evaluated once | Access log, untouched result, failure analysis |
| Shadow | Candidate runs on production-path data and code | Monitoring, reconciliation, operational ownership, kill criteria |
| Paper | Orders exercise a paper execution environment | Execution controls, state recovery, TCA, incident handling |
| Retired | Candidate is no longer eligible | Reason, effective time, replacement, retained evidence |

### Promotion evidence

Promotion decisions consider the complete system rather than one headline metric:

- Data integrity, point-in-time behavior, lineage, coverage, and known biases.
- Economic mechanism, expected horizon, decay, capacity, and failure mode.
- Forecast quality, calibration, monotonicity, stability, and long/short asymmetry.
- Incremental contribution after existing signals and portfolio netting.
- Realized risk calibration, systematic and residual exposure, tails, and stress.
- Constraint behavior, optimizer stability, fallback behavior, and shadow prices.
- Net performance after fees, spread, impact, delay, funding, financing, borrow, and taxes as applicable.
- Capacity across capital, participation, liquidity, and stressed conditions.
- Multiple-testing evidence and the complete research path.
- Final-OOS outcome against precommitted rules.
- Shadow reconciliation, data drift, order behavior, operational incidents, and recovery exercises.

No result is promoted solely because its historical Sharpe ratio exceeds a threshold. Thresholds are precommitted for the particular strategy, horizon, data quality, capacity objective, and risk budget.

### Independent review

Independent review must be able to reconstruct the result without private researcher state. The reviewer records:

1. Dataset and universe reproduction outcome.
2. Code and configuration review findings.
3. Leakage, sign, unit, timestamp, and accounting checks.
4. Comparison with simple baselines and challengers.
5. Unresolved data, model, execution, operational, or governance risks.
6. Conditions required before promotion and the owner of each condition.

Material findings are artifacts linked to the candidate. Approval does not delete or obscure dissenting evidence.

## Documentation requirements

Documentation is part of the implementation and is reviewed for correctness and operational impact. Required maintained documents include:

- Architecture and dependency decisions.
- Canonical schemas, units, timestamps, and lifecycle semantics.
- Connector source specifications and known data limitations.
- Dataset, feature, label, model, risk, cost, and portfolio registry references.
- Operator commands, configuration, deployment, monitoring, rollback, and replay procedures.
- Research methodology, metric definitions, promotion rules, and model-card template.
- Asset-class conventions and portability-test results.
- Incident reviews, data invalidations, migrations, and deprecation notices.

Examples and commands must be executable or clearly marked as illustrative. Documentation changes that alter economic or operational behavior require the same domain review as code changes.

## Definition of done

A capability is complete only when all applicable items below are satisfied:

- The economic responsibility and public contract are documented.
- Types, units, currency, signs, timestamp semantics, and lifecycle behavior are explicit.
- Deterministic unit tests cover normal, boundary, and failure cases.
- A reusable contract test exists when the interface is replaceable.
- At least one bounded integration or human-auditable golden test exists.
- Future-perturbation or equivalent leakage tests exist for time-dependent research behavior.
- Idempotency, retry, interruption, correction, and replay behavior are defined where applicable.
- Failure is explicit and the fallback, degradation, or stop behavior is tested.
- Artifacts contain complete lineage and deterministic identities.
- Metrics, logs, and operator-visible failure evidence are present.
- Security and access implications have been reviewed.
- Performance is measured when the capability is on a critical path.
- User, reviewer, and operator documentation is current.
- The relevant wave exit criteria and acceptance gates remain green.
- Known limitations and deferred work are recorded with owners or decision points.

A successful backtest alone is never completion evidence.

Live capital deployment is outside this guideline. It requires a separate review of legal access, exchange and broker agreements, credentials, operational ownership, capital limits, and explicit authorization.

## References

The local PDFs used during early drafting are not tracked by this repository and are therefore not normative dependencies. Requirements needed to implement or review the platform must be stated in tracked documentation.

### Public architecture evidence

- [Jane Street: How we accidentally built a better build system for OCaml](https://blog.janestreet.com/how-we-accidentally-built-a-better-build-system-for-ocaml-index/) for its publicly stated monorepo scale, Dune migration, build caching, and dedicated build-systems work.
- [Jane Street: Building reproducible Python environments with XARs](https://blog.janestreet.com/building-reproducible-python-environments-with-xars/) for immutable Python environments, native-language integration, and stable versus continuously updated environment tags.
- [HRT: Inside HRT's Python Fork](https://www.hudsonrivertrading.com/hrtbeat/inside-hrts-python-fork/) for its publicly stated majority-monorepo development and the costs of globally importable Python modules at scale.
- [HRT: Engineering and Interviewing at HRT](https://www.hudsonrivertrading.com/hrtbeat/engineering-and-interviewing-at-hrt/) for its public distinction between research and live-trading engineering, platform and embedded teams, and C++/Python responsibilities.
- [HRT: Scaling Prometheus to Billions of Samples a Second](https://www.hudsonrivertrading.com/hrtbeat/scaling-prometheus/) for horizontally scaled, highly available monitoring across research and live environments.
- [Citadel Securities Engineering](https://www.citadelsecurities.com/careers/engineering/) for its public descriptions of trading systems, research and simulation, core platforms, and SRE. This source does not establish a Citadel Securities monorepo or a specific build tool.

### Technical references

- [Bazel](https://bazel.build/) and [Bazel hermeticity](https://bazel.build/basics/hermeticity) for a reference multi-language build graph, pinned inputs, reproducibility, caching, and remote execution.
- [Apache Parquet](https://parquet.apache.org/) for portable columnar storage.
- [Apache Arrow](https://arrow.apache.org/overview/) for future cross-language in-memory interchange.
- [FIX Trading Community](https://www.fixtrading.org/standards/) for established instrument, order, execution, and multi-leg concepts.
- [OCC equity options specifications](https://www.theocc.com/clearance-and-settlement/clearing/equity-options-product-specifications) for equity-option exercise, assignment, and contract behavior.
- [CME contract specifications](https://www.cmegroup.com/education/courses/introduction-to-futures/learn-about-contract-specifications) for futures multipliers, delivery, expiration, and settlement concepts.

References inform the platform contracts but do not override effective venue rules, broker agreements, legal requirements, measurements from this system, or internally approved policies.
