# Statistical Arbitrage Research Platform Implementation Guidelines

## Purpose

This document defines the implementation sequence and review standards for a crypto-first, production-oriented statistical-arbitrage platform. The platform must support the complete research lifecycle: point-in-time data, feature and model research, portfolio construction, realistic execution, validation, governance, shadow trading, and operational monitoring.

The first workload is a transparent crypto factor-residual strategy. It is an acceptance test for the platform, not the platform architecture. Shared contracts must also support equities, futures, FX, options, volatility, and fixed-income relative value without rewriting the research, artifact, governance, or deployment layers.

## Intended audience

This guide is for the people who design, implement, review, validate, operate, and eventually approve the platform:

- Data engineers responsible for source fidelity, normalization, lineage, revisions, and data quality.
- Quantitative researchers implementing replications, signals, factor models, risk models, and portfolio policies.
- Execution researchers modeling fills, costs, impact, financing, capacity, and venue behavior.
- Platform engineers maintaining environments, artifacts, scheduling, observability, recovery, and access controls.
- Independent reviewers verifying that research results are reproducible and free from implementation leakage.
- Portfolio managers and risk owners deciding whether a candidate is suitable for shadow, paper, or capital allocation.

The guide assumes familiarity with Python, probability, statistics, optimization, financial markets, and time-series research. It does not assume that the reader already knows the internal platform conventions; those conventions must be explicit here and enforceable in code.

## Design targets

The platform is intended to make the following statements demonstrably true:

1. A result can be reproduced from immutable source data, a pinned code revision, a complete configuration, and a recorded environment.
2. A historical decision uses only information that was available at the simulated decision time.
3. The same feature, signal, risk, portfolio, accounting, and execution components can be used in research and shadow operation.
4. Gross alpha, systematic exposure, financing, execution, capacity, and operational assumptions are evaluated jointly.
5. Every attempted research variant remains visible, including failed, rejected, and superseded variants.
6. A promoted model has explicit intended use, limitations, ownership, monitoring, fallback, and retirement rules.
7. Adding an asset class primarily requires new instrument definitions, data adapters, valuation engines, lifecycle rules, and venue adapters rather than changes to the research-governance core.
8. Failures are explicit. Missing data, stale risk, infeasible optimization, unavailable borrow, incomplete fills, and model degradation must not silently fall back to optimistic assumptions.

## Guiding principles

### Correctness before scale

Begin with deterministic single-process implementations and small golden datasets. Distributed systems should be introduced only after profiling demonstrates a concrete throughput, latency, reliability, or isolation requirement.

### Point-in-time behavior is a platform property

Look-ahead prevention cannot depend on researcher discipline alone. Dataset joins, universe membership, feature transformations, model fitting, and evaluation splits must carry and enforce availability semantics.

### Research-production parity is tested

Shared source code is necessary but not sufficient. The platform must reconcile research predictions, target positions, risk estimates, orders, fills, costs, and P&L against shadow operation.

### Interfaces follow economic responsibilities

Contracts should describe instruments, cashflows, valuation, risk, portfolio intent, and execution behavior. They should not merely mirror the shape of one vendor API or one starter strategy.

### Simple baselines remain permanent challengers

Observable factors, rolling PCA, linear forecasts, shrinkage covariance, rank portfolios, and transparent execution assumptions remain in the benchmark suite after more complex methods are added.

### Evidence is an artifact

Data audits, feature diagnostics, model comparisons, risk validation, optimizer diagnostics, execution attribution, capacity curves, stress results, and model cards are versioned outputs, not prose reconstructed after a decision.

## Scope

### Initial scope

- Python modular monolith with explicit, tested interfaces.
- Crypto spot and perpetual-futures data, with Binance as the first historical adapter.
- Batch ingestion before streaming; vectorized simulation before event-driven replay.
- Immutable raw data, point-in-time datasets, reproducible research runs, and complete trial history.
- Paper and shadow trading as production-platform capabilities.
- Parquet for analytical data and SQLite for initial metadata, with storage interfaces that permit object storage and PostgreSQL later.

### Deferred scope

- Live capital deployment and broker/exchange certification.
- Microservice decomposition, Kafka, Kubernetes, and distributed compute until workload evidence requires them.
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

The three entrypoints must call the same domain, feature, valuation, risk, portfolio, accounting, and execution components. Research-only substitutes for production logic are prohibited unless explicitly labeled as approximations and reconciled later.

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
8. Record every attempted configuration and retain all artifacts.
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
9. Emit metrics, logs, traces, alerts, and review artifacts.

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
- Failed and rejected trials remain in an append-only trial ledger.
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

The trial ledger records the hypothesis family, researcher, parent experiment, reason for the trial, all reported metrics, outcome, and any later invalidation. Deleting or rewriting an unfavorable trial is prohibited.

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

```text
src/alpha_research/
  domain/          # identifiers, instruments, events, orders, cashflows
  data/            # connectors, normalization, storage, lineage, quality
  datasets/        # point-in-time assembly, universes, labels, splits
  features/        # feature contracts, registry, transforms
  models/          # factor, predictive, residual, and model registry
  valuation/       # market state, pricers, curves, surfaces, sensitivities
  risk/            # covariance, scenario risk, stress, limits
  portfolio/       # intents, constraints, static/dynamic optimizers
  backtest/        # clocks, vectorized simulation, event replay
  execution/       # orders, fills, costs, venue and paper adapters
  accounting/      # positions, cash, P&L, financing, reconciliation
  governance/      # trials, OOS locks, model cards, promotion
  reporting/       # research, risk, execution, and monitoring reports
apps/
  ingest.py
  research.py
  shadow.py
tests/
  unit/
  contract/
  integration/
  golden/
data/fixtures/     # tiny, reviewable test fixtures only
```

### Dependency direction

The intended dependency direction is:

```text
domain
  <- data, datasets, valuation, accounting
  <- features, models, risk
  <- portfolio, backtest, execution
  <- governance, reporting
  <- application entrypoints
```

Circular package dependencies are prohibited. Shared helpers belong in a narrowly named package only after at least two legitimate consumers exist; a generic `utils` dumping ground should be avoided.

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

- Implementation MRs have a maximum of 299 additions plus deletions, including their tests, fixtures, configuration, inline documentation, and generated files.
- Target 150-250 changed lines so review feedback does not breach the hard limit.
- One behavior or contract per MR; broad scaffolding and opportunistic refactors are rejected.
- Every MR names one human-readable invariant and includes a deterministic acceptance test.
- Network tests use recorded fixtures in CI; a separate bounded smoke test verifies the real provider.
- Binary fixtures and large generated lockfiles are not permitted in ordinary code MRs.
- Public interfaces require contract tests before receiving a second implementation.
- Each MR must leave all previously completed acceptance gates green.

The 299-line limit applies to implementation MRs. Documentation-only MRs are exempt when additional detail materially improves correctness, reviewability, operations, or governance. A documentation exemption must not be used to hide executable code, generated schemas, large fixtures, or mechanical source rewrites.

### Required MR description

Every implementation MR description includes:

1. The single behavior or contract introduced.
2. Why it is required by the platform roadmap or a research-program stage.
3. The invariant a human reviewer should verify.
4. Files and public interfaces changed.
5. Test commands and expected evidence.
6. Failure and rollback behavior.
7. Known omissions or follow-up work.
8. Changed-line count, excluding only an approved documentation exemption.

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

Each numbered item below is one merge request.

### Wave 0: engineering spine

1. Repository, pinned environment, package import, and test smoke check.
2. CI, static checks, and the 299-line diff gate.
3. Typed configuration, environment precedence, and secret references.
4. Canonical identifiers, UTC handling, decimal precision, currency, and units.
5. Content hashing, run manifests, and deterministic run identity.
6. Atomic artifact store with idempotent lookup and retention metadata.
7. Structured CLI results, errors, logs, and correlation IDs.

**Wave 0 exit criteria:** a clean checkout installs reproducibly; all tests and static checks run from one documented command; two identical fixture runs produce the same run and artifact identities; a one-byte configuration or input change produces a different identity; secrets and wall-clock timestamps do not affect deterministic hashes.

### Wave 1: asset-neutral domain foundation

1. Versioned `ContractSpec` hierarchy with cash, perpetual, future, and option fixtures.
2. Typed `MarketEvent` union and schema-version validation.
3. Four-time availability semantics and point-in-time query predicate.
4. Calendar, session, business-day, day-count, and settlement conventions.
5. Multi-currency cash, contract-quantity positions, and scheduled cashflows.
6. `MarketState`, `ValuationEngine`, and sensitivity protocols.
7. Instrument lifecycle for listing, roll, expiry, exercise, assignment, and settlement.
8. Covariance and full-revaluation scenario-risk protocols.
9. `StrategyOutput`, `PortfolioIntent`, dimensioned constraints, and order protocols.
10. Basket/multi-leg orders, margin, collateral, financing, borrow, and hedge protocols.

**Wave 1 exit criteria:** contract fixtures represent an equity, perpetual future, dated future, European option, American option, FX forward, and fixed cashflow; their quantities, currencies, multipliers, lifecycle dates, and settlement methods survive serialization; multi-currency ledger and lifecycle golden tests reconcile without asset-specific branches in shared accounting.

### Wave 2: first end-to-end crypto research slice

1. Canonical bars and funding events.
2. Immutable local bronze store.
3. Binance archive downloader with retry, checksum, and atomic promotion.
4. Kline and funding parsers with UTC and decimal validation.
5. Silver Parquet writer and deterministic reader.
6. Dataset specification and 24/7 resampling.
7. Pure feature-function contract and future-perturbation test.
8. Minimal vectorized simulation clock with delayed fills.
9. Position, cash, P&L, fees, and funding ledger.
10. Baseline metrics, attribution, run manifest, and report.

**Wave 2 exit criteria:** a small Binance fixture runs raw-to-report from one CLI command; signals cannot trade on their own input bar; positive funding makes longs pay and shorts receive; gross P&L, costs, funding, and net P&L reconcile exactly; repeated runs produce identical manifests and reports.

### Wave 3: point-in-time data platform

1. Bitemporal metadata catalog and raw-revision history.
2. Historical archive catalog and instrument lifecycle ingestion.
3. Mark, index, premium, trade, quote, and funding ingestion.
4. Declarative data-quality contract and crypto quality suite.
5. Point-in-time reader and as-of join implementation.
6. Time-varying universe snapshots with liquidity and history eligibility.
7. Data-lineage and universe-audit report.
8. Idempotent backfill, replay, interruption, and restart behavior.
9. Scheduled ingestion state, late-data handling, and degraded partitions.

**Wave 3 exit criteria:** an independent reviewer can reconstruct silver data and a historical universe from bronze manifests; future corrections, listings, liquidity, and metadata cannot alter earlier decisions at an earlier knowledge cutoff; interrupted backfills restart without duplicates or missing partitions; hard-quality failures block publication.

### Wave 4: research and model platform

1. Feature, label, signal, and dataset registries.
2. Rolling/expanding splits plus purging and embargo.
3. Train-only transforms, neutralization, and missing-data policies.
4. Factor-model protocol with observable-factor and rolling-PCA baselines.
5. Residual construction and convergence-signal pipeline.
6. Signal dossier with mechanism, horizon, decay, turnover, and failure mode.
7. Common linear, regularized, tree, forest, and neural-model adapter.
8. Rolling training, inference, artifact, and seed handling.
9. Common model bake-off using identical data, splits, costs, and constraints.
10. Regime, stability, calibration, monotonicity, and long/short diagnostics.

**Wave 4 exit criteria:** observable-factor, PCA-residual, linear, regularized, tree, forest, and neural baselines can run through the same dataset and rolling-evaluation contracts; perturbing future data leaves past features, transformations, models, and predictions unchanged; all attempted configurations appear in the trial ledger.

### Wave 5: risk and portfolio platform

1. Sample, shrinkage, factor, and sparse-residual covariance implementations.
2. Forecast-versus-realized risk, tail, concentration, and stability validation.
3. Gross, net, factor, position, liquidity, turnover, venue, and exposure constraints.
4. Static constrained optimizer with unit and sign tests.
5. Shadow prices, transfer diagnostics, and binding-frequency reporting.
6. Safe fallbacks for stale risk, missing inputs, and infeasibility.
7. Dynamic trading protocol and linear cost-aware baseline.
8. Multi-period convex optimizer and limiting-case tests.
9. Factor, covariance, liquidity, funding, crowding, and unwind stresses.

**Wave 5 exit criteria:** covariance forecasts are evaluated by realized portfolio outcomes; every constraint has unit, sign, feasibility, and comparative-static tests; binding constraints expose shadow costs; infeasible or stale inputs follow a safe deterministic fallback; the dynamic optimizer trades more slowly when costs rise or alpha decays more slowly.

### Wave 6: execution, financing, and capacity

1. Canonical order, fill, cancel, reject, and position state machine.
2. Deterministic event-replay engine and equal-timestamp ordering.
3. Spread, fee, rebate, delay, partial-fill, and opportunity-cost models.
4. Impact, participation, urgency, and cross-impact protocols.
5. Capacity curves across capital, participation, holding period, and stress.
6. Crypto margin, liquidation, funding, and financing implementation.
7. Transaction-cost analysis and decision-to-fill reconciliation.
8. Vectorized/event-driven parity suite under equivalent assumptions.
9. Paper execution adapter with idempotent client-order handling.

**Wave 6 exit criteria:** canonical order state cannot enter an impossible transition; execution retries cannot create duplicate economic orders; vectorized and event-driven results match when assumptions match; implementation shortfall reconciles from decision price to ledger P&L; capacity is reported as a curve with uncertainty and stress, not a single number.

### Wave 7: governance, shadow production, and operations

1. Append-only experiment and trial ledger.
2. Block bootstrap, multiple-testing, and research-wide trial accounting.
3. Frozen final-OOS dataset, configuration, and access log.
4. Model artifact registry, model card, ownership, and limitations.
5. Promotion state machine: research, candidate, shadow, paper, retired.
6. Shadow runner using shared feature, model, risk, and portfolio code.
7. Backtest-to-shadow forecast, target, order, fill, cost, and P&L reconciliation.
8. Kill switches for stale data, risk failure, infeasibility, rejects, and abnormal P&L.
9. Metrics, structured logs, traces, dashboards, and alert thresholds.
10. Container deployment, health checks, rollback, replay, and runbooks.

**Wave 7 exit criteria:** a frozen candidate can run in historical replay and shadow using shared production-path code; every prediction-to-fill difference is attributable; configured kill switches are exercised in tests; an operator can identify, stop, roll back, replay, and recover a failed deployment from the runbook.

### Wave 8: asset-class adapters

1. Equity delayed-SIP entitlement test and market-data adapter.
2. Equity sessions, identifiers, corporate actions, point-in-time universe, and borrow gate.
3. Futures contract, roll, multiplier, variation-margin, and delivery adapter.
4. FX spot/forward, settlement, swap-points, and multi-currency adapter.
5. Option chain, symbology, quote, trade, mark, and lifecycle adapter.
6. Curve and volatility-surface builders with no-arbitrage checks.
7. Option pricer and analytic-versus-finite-difference Greek tests.
8. Fixed-income cashflow, accrual, clean/dirty price, curve, and DV01 adapter.

**Wave 8 exit criteria:** each adapter passes shared connector, instrument, lifecycle, valuation, accounting, risk, portfolio, and execution contract tests; the option portability test passes; no shared research, ledger, registry, or promotion interface changes merely to accommodate an asset-class adapter.

## Research-program acceptance map

| Program stage | Required platform waves | Required evidence |
| --- | --- | --- |
| Weeks 1-2: baseline and data | 0-3 | Reproducible costed baseline plus point-in-time data and universe audit |
| Weeks 3-9: factors, signals, ML, regimes | 4 | Registered models under common rolling evaluation and diagnostics |
| Weeks 10-12: risk and portfolio | 5 | Realized-risk validation, constraints, optimizer diagnostics, dynamic trading |
| Weeks 13-14: execution and financing | 6 | TCA, capacity, funding/margin, partial fills, and stress evidence |
| Weeks 15-16: governance and shadow | 7 | Complete trials, locked OOS, promotion package, shadow reconciliation |
| Other asset classes | 1 and 8 | New adapters pass shared contracts without core rewrites |

### Week-by-week enablement

| Week | Research objective | Platform capability used | Required artifact |
| --- | --- | --- | --- |
| 1 | Strategy map and transparent baseline | Dataset specification, delayed simulation clock, shared ledger, baseline report | Horizon, universe, decision-price convention, gross-to-net identity, costed baseline |
| 2 | Point-in-time data and instrument master | Bitemporal catalog, instrument lifecycle, quality suite, universe snapshots, lineage | Data-lineage map, identifier tests, timestamp audit, lifecycle and gap report |
| 3 | Observable and PCA residual baselines | Factor-model protocol, PCA, residual pipeline, diagnostics | Factor stability, residual covariance, turnover, residual predictability |
| 4 | Conditional and pricing-relevant factors | Replaceable factor implementations, common splits and artifacts | Challenger comparison, omitted-factor exposure, loading stability |
| 5 | Signal library and hypotheses | Feature/signal registries and dossier schema | Versioned signal definitions, mechanisms, horizons, decay, missingness, turnover |
| 6 | Normalization and neutralization | Train-only transformation pipeline and dimensioned exposure reporting | Alpha removed, risk removed, orthogonalization and stability evidence |
| 7 | Predictive-model benchmark matrix | Common model adapter, rolling trainer, model bake-off | Identical-split IC, calibration, turnover, stability, and net-value comparison |
| 8 | Missing data and representation | Registered missing-data policies and leakage tests | Complete-case and imputation comparison with missingness diagnostics |
| 9 | Forecast evaluation and regimes | Conditional diagnostics and predeclared slices | Volatility, liquidity, trend, crowding, and break-condition tables |
| 10 | Risk model | Covariance implementations, realized-risk validation, scenario engine | Calibration, tails, concentration, eigenstructure, optimizer stability |
| 11 | Static portfolio construction | Constraint system, static optimizer, shadow-price diagnostics | Transfer coefficient, constraint costs, feasibility and fallback evidence |
| 12 | Dynamic cost-aware trading | Dynamic and multi-period optimizer contracts | Trading-speed comparative statics and net-value comparison |
| 13 | Execution, impact, and capacity | Event replay, cost/impact models, TCA, capacity generator | Implementation shortfall and net frontier across capital scales |
| 14 | Borrow, financing, and short-side stress | Financing, funding, margin, borrow, recall and lifecycle interfaces | Financing attribution, availability, squeeze, margin, and concentration stress |
| 15 | Multiple testing and governance | Complete trial ledger, bootstrap/correction tools, candidate freeze | Locked selection protocol, research degrees of freedom, independent review record |
| 16 | Integrated OOS and shadow package | Promotion state, shadow runner, reconciliation, telemetry, runbooks | Untouched OOS, attribution, capacity, stress, model card, shadow reconciliation |

The program may pause at any week if its required platform capability or evidence is incomplete. A later research week must not be used to justify bypassing an earlier data, accounting, or governance gate.

## Acceptance gates

1. **Foundation gate:** clean install, deterministic identities, contract fixtures, and CI line limit pass.
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

External services are replaced with deterministic containers or recorded responses in CI. Live provider smoke tests are bounded, non-destructive, separately labeled, and never required for ordinary unit-test execution.

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

Performance tests begin only after correctness gates pass. Benchmarks record dataset size, event count, instruments, hardware, runtime, peak memory, and code revision. A performance optimization must preserve golden results or document an explicitly accepted numerical tolerance.

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

Metrics use stable names and units. High-cardinality identifiers belong in logs or traces rather than unbounded metric labels.

### Failure and degradation policy

Each application defines behavior for missing data, stale data, unavailable metadata, schema mismatch, storage failure, model load failure, stale risk, optimizer infeasibility, venue reject, incomplete fill, and reconciliation breach. Permitted actions are fail, pause, degrade with an explicit flag, use a registered fallback, or flatten through an authorized process. Silent continuation is not permitted.

### Recovery and rollback

- Data publication is atomic and previous valid versions remain addressable.
- Candidate promotion is reversible without deleting evidence.
- Application deployments retain a known-good image and compatible configuration.
- State recovery procedures identify the authoritative event and ledger sources.
- Runbooks include detection, containment, rollback, replay, reconciliation, escalation, and post-incident evidence.
- Recovery drills use test or paper environments and record observed recovery time and unresolved gaps.

## Security and access controls

- Secrets are stored outside the repository and resolved through a documented provider.
- Least-privilege credentials separate historical data, live data, paper execution, and any future live execution.
- Research processes do not receive trading credentials.
- Production candidate artifacts and promotion actions have authenticated ownership and audit history.
- Sensitive account, position, order, and vendor-entitlement data is not included in public fixtures or logs.
- Dependency versions and container bases are pinned and scanned through the approved CI process.
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
8. Runs unchanged through research, final OOS, shadow, and paper entrypoints.

Any required modification to the shared ledger, dataset engine, backtest clock, registry, or promotion workflow fails the portability test and requires an abstraction review.

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
- Historical-research/shadow comparison using the same registered components.

## Research and promotion governance

### Research stages

| State | Meaning | Minimum requirement |
| --- | --- | --- |
| Exploration | Idea is being investigated | Registered hypothesis and complete trial recording |
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

Documentation is part of the implementation and may exceed the code-MR line limit when detail improves correctness or operations. Required maintained documents include:

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

## Companion references

- `Institutional-Grade Multi-Asset Alpha Research Implementation Framework.pdf` for the original shared-core, three-entrypoint, provenance, bias-control, and production-operability design.
- `Institutional_Statistical_Arbitrage_Reading_List_2026.pdf` for the research sequence, minimum evidence package, required deliverables, and promotion questions.
- [Apache Parquet](https://parquet.apache.org/) for portable columnar storage.
- [Apache Arrow](https://arrow.apache.org/overview/) for future cross-language in-memory interchange.
- [FIX Trading Community](https://www.fixtrading.org/standards/) for established instrument, order, execution, and multi-leg concepts.
- [OCC equity options specifications](https://www.theocc.com/clearance-and-settlement/clearing/equity-options-product-specifications) for equity-option exercise, assignment, and contract behavior.
- [CME contract specifications](https://www.cmegroup.com/education/courses/introduction-to-futures/learn-about-contract-specifications) for futures multipliers, delivery, expiration, and settlement concepts.

References inform the platform contracts but do not override effective venue rules, broker agreements, legal requirements, or internally approved policies.
