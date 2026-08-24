# Implementation Roadmap

## Purpose

This is the delivery plan for the crypto-first alpha research platform. It turns
the [architecture](../architecture/README.md),
[contracts](../architecture/contracts.md), and
[operational controls](../architecture/operations.md) into dependency-ordered,
verifiable work.

The companion [research program](research-program.md) describes empirical work.
Platform completion and research evidence are separate: merging infrastructure is
not evidence that a strategy works, and a promising notebook is not evidence that
the platform is safe to operate.

## Roadmap corrections and rationale

The earlier plan implemented a broad equity/futures/options/FX domain hierarchy
before the first crypto end-to-end slice. That ordering was inconsistent with
correctness-first and YAGNI. This roadmap changes the sequence:

```text
P0 foundation
   -> P1 minimal crypto vertical slice
      -> P2 point-in-time data hardening
         -> P3 governed research and models
            -> P4 risk and portfolio
               -> P5 replay, execution, financing, capacity
                  -> P6 shadow, promotion, operations
                     +-> P7 scale/polyglot optimization (conditional)
                     +-> P8 cross-asset expansion (conditional)
```

Only the critical path P0-P6 is required for the first shadow-ready candidate.
P7 and P8 require explicit entry evidence. A small native performance target may
be pulled forward after P1 profiling, but it does not justify a repository-wide
build-system migration by itself.

## How to execute the roadmap

### Phases are gates, not calendar promises

Phase numbers express dependency order. Work may overlap when dependencies and
owners are clear, but a later phase cannot be declared complete while an earlier
blocking gate is open. The research program's numbered stages are likewise a
sequence, not a guarantee of one stage per week.

### Work-package status

Track every package with one of:

| Status | Meaning |
| --- | --- |
| Planned | Defined here but not yet dependency-ready |
| Ready | Dependencies and acceptance procedure are available |
| In progress | Owner and implementation/review work are active |
| Validated | Evidence exists and the phase reviewer accepted it |
| Blocked | Named dependency or decision prevents progress |
| Superseded | Replaced, with the replacement and reason retained |

Work-package IDs are capability identifiers, not mandatory one-PR limits. A
package may need several coherent pull requests; use suffixes in the tracker if
needed. IDs become stable when implementation starts and are never silently reused.

### Pull-request requirements

Each implementation PR states:

1. Work-package ID and single primary behavior.
2. Dependencies and affected targets/owners.
3. Human-readable invariant.
4. Interfaces, schemas, generated files, and migrations changed.
5. Exact validation commands and expected evidence.
6. Failure, rollback, and compatibility behavior.
7. Known omissions and follow-up packages.

There is no universal line-count limit. Generated or mechanical changes are
separated from semantic changes, and every PR leaves completed gates green.

## Phase 0: engineering foundation

**Goal:** make a clean checkout deterministic, testable, and attributable before
building research behavior.

| ID | Deliverable | Depends on | Acceptance evidence |
| --- | --- | --- | --- |
| `ENG-01` | Pin Python/tool dependencies and define the initial package | — | Clean environment installs without undeclared host packages |
| `ENG-02` | Root commands for format, lint, type-check, test, and smoke run | `ENG-01` | One documented interface runs all configured checks |
| `ENG-03` | CI, pre-commit alignment, affected-target selection, scheduled full validation | `ENG-02` | Leaf and foundational-change selection fixtures pass |
| `ENG-04` | Typed configuration, precedence, environment profiles, secret references | `ENG-01` | Unknown keys fail; resolved non-secret config is complete |
| `ENG-05` | Core IDs, UTC/time semantics, currency, decimal precision, and units | `ENG-01` | Invalid values fail; round-trip/golden tests pass |
| `ENG-06` | Content hashing, run manifests, and deterministic identity | `ENG-04`, `ENG-05` | Same inputs match; one-byte semantic change changes identity |
| `ENG-07` | Atomic local artifact store and retention metadata | `ENG-06` | Interrupted writes remain invisible; retries do not duplicate |
| `ENG-08` | Structured CLI outcomes, errors, logs, and correlation IDs | `ENG-04`, `ENG-06` | One fixture run traces from command to logs/artifacts |
| `ENG-09` | ADR template and owner/decision registry | — | A sample build/storage decision can be proposed and reviewed |
| `ENG-10` | Dependency lock, provenance, license, and vulnerability baseline | `ENG-01`, `ENG-02` | Resolved dependencies and exceptions are reviewable and reproducible |

**Exit gate:** a clean checkout installs reproducibly; root checks pass; two
identical fixture runs have identical identities; changed inputs change identity;
secret values and wall-clock time do not affect deterministic hashes; resolved
dependencies and their provenance are recorded.

**Explicit non-goals:** Bazel, Rust/C++, remote execution, distributed compute,
Kubernetes, streaming ingestion, and live credentials.

## Phase 1: minimal crypto vertical slice

**Goal:** prove raw-to-report economic correctness with the smallest spot/perpetual
contract set before building generic multi-asset abstractions.

| ID | Deliverable | Depends on | Acceptance evidence |
| --- | --- | --- | --- |
| `CRY-01` | Minimal cash/spot and perpetual instrument specifications | `ENG-05` | Instrument, multiplier, currency, tick/lot fixtures round-trip |
| `CRY-02` | Canonical bar and funding events with four-time semantics | `CRY-01` | Known source rows preserve values, signs, and timestamps |
| `CRY-03` | Immutable local bronze store | `ENG-07` | Existing raw objects cannot be overwritten |
| `CRY-04` | Binance archive download with retry, checksum, and atomic publication | `CRY-03` | Corrupt/partial downloads never publish |
| `CRY-05` | Kline/funding normalizers and deterministic silver Parquet | `CRY-02`, `CRY-04` | Read/write preserves schema, order, timezone, decimals, hash |
| `CRY-06` | Minimal dataset specification and 24/7 resampling | `CRY-05` | Aggregation is exact; gaps remain explicit |
| `CRY-07` | Pure feature contract and future-perturbation test | `CRY-06` | Future changes cannot alter prior features |
| `CRY-08` | Vectorized clock with explicit decision/fill delay | `CRY-06` | An order cannot fill on its input signal bar |
| `CRY-09` | Quantity/cash/P&L/fee/funding ledger | `CRY-01`, `CRY-08` | Hand-calculated long/short examples reconcile |
| `CRY-10` | Transparent factor-residual baseline, manifest, attribution, report | `CRY-07`, `CRY-09` | Raw-to-report command is deterministic; gross-to-net reconciles |

**Exit gate:** one tiny Binance fixture runs from immutable raw input to a
reviewable report; no look-ahead or same-bar fill is possible; funding, fees, cash,
positions, and P&L reconcile exactly; repeated runs are identical.

**Replan trigger:** if the slice cannot fit a modular Python process, document the
measured constraint before adding services or native code.

## Phase 2: point-in-time data hardening

**Goal:** make source revision, historical universe, correction, and restart
behavior independently reproducible.

| ID | Deliverable | Depends on | Acceptance evidence |
| --- | --- | --- | --- |
| `DATA-01` | Bitemporal metadata and raw-revision catalog | `CRY-03`, `ENG-06` | Event-time and knowledge-time queries return expected versions |
| `DATA-02` | Historical instrument/alias/lifecycle catalog for supported crypto | `CRY-01`, `DATA-01` | Inactive/delisted contracts remain historically discoverable |
| `DATA-03` | Trades, quotes, mark, index, premium, and funding ingestion as needed | `CRY-05` | IDs and timestamps align across golden events |
| `DATA-04` | Declarative quality rules and severity policy | `DATA-01`, `DATA-03` | Duplicate/gap/stale/OHLC/funding failures classify correctly |
| `DATA-05` | Point-in-time reader and as-of joins | `DATA-01`, `DATA-02` | Future records/revisions cannot enter earlier decisions |
| `DATA-06` | Time-varying universe and eligibility snapshots | `DATA-02`, `DATA-05` | Future listing/liquidity cannot alter earlier membership |
| `DATA-07` | Lineage and universe audit report | `DATA-04`-`DATA-06` | Derived rows resolve to silver and bronze identities |
| `DATA-08` | Idempotent backfill, interruption, resume, and replay | `DATA-04`, `ENG-07` | Interrupted and uninterrupted publication is identical |
| `DATA-09` | Scheduled state, late data, degradation, republish policy | `DATA-08` | Late/degraded partitions follow declared blocking rules |
| `DATA-10` | Schema compatibility matrix, migration, and old/new reader fixtures | `DATA-01`, `DATA-05` | Supported old/new readers pass; unsupported versions fail clearly |

**Exit gate:** an independent reviewer reconstructs silver data and a historical
universe from manifests; future corrections/listings do not alter earlier
knowledge; interrupted backfills recover without duplicates or omissions; hard
quality failures block publication; schema evolution has tested migration and
rollback behavior.

## Phase 3: governed research and model platform

**Goal:** compare transparent and complex models under one leakage-resistant,
fully recorded evaluation contract.

| ID | Deliverable | Depends on | Acceptance evidence |
| --- | --- | --- | --- |
| `RES-01` | Dataset, feature, label, signal, and model registries | `DATA-07` | Required availability, units, horizon, mechanism, owner enforced |
| `RES-02` | Append-only governed experiment/trial ledger | `ENG-06`, `RES-01` | Formal failed/rejected trials cannot be hidden or rewritten |
| `RES-03` | Rolling/expanding splits with retraining cadence | `RES-01` | All interval boundaries match configuration |
| `RES-04` | Purging, embargo, and overlapping-label controls | `RES-03` | Training labels cannot overlap validation/test labels |
| `RES-05` | Train-only scaling, neutralization, imputation, and selection | `RES-03`, `RES-04` | Future outliers/missing values cannot alter fitted transforms |
| `RES-06` | Observable-factor and rolling-PCA baselines | `RES-05`, `CRY-10` | Return reconstruction, factor stability, deterministic PCA sign pass |
| `RES-07` | Residual/convergence pipeline and signal dossier | `RES-06` | Common plus residual reconstructs returns; decay/turnover documented |
| `RES-08` | Common model adapter and rolling trainer | `RES-03`-`RES-05` | Linear, regularized, tree/forest, and optional MLP share splits |
| `RES-09` | Seed/artifact handling, bake-off, regime/stability diagnostics | `RES-02`, `RES-08` | Comparisons use identical data/costs; tables are predeclared |
| `RES-10` | Research evidence package and independent reproduction command | `RES-06`-`RES-09` | Reviewer rebuilds a selected run without private state |

**Exit gate:** all evaluated models use identical point-in-time datasets and
rolling protocols; future perturbation leaves historical outputs unchanged;
governed trials are complete; transparent baselines remain in every comparison;
an independent reviewer reproduces the evidence package. Rankings remain
provisional until P5 supplies execution, financing, and capacity evidence; the
governed candidate family is not pruned retroactively to the eventual winner.

**Scope rule:** advanced ML is a challenger, not a prerequisite. If linear and
PCA baselines do not survive costs and stability checks, do not proceed to a model
zoo merely to search for a favorable result.

## Phase 4: risk and portfolio construction

**Goal:** turn forecasts into dimensioned, constrained, explainable positions with
safe failure behavior.

| ID | Deliverable | Depends on | Acceptance evidence |
| --- | --- | --- | --- |
| `PORT-01` | Sample and shrinkage covariance baselines | `RES-03` | Closed-form fixtures and PSD policy pass |
| `PORT-02` | Factor plus residual covariance | `RES-06`, `PORT-01` | Factor/residual reconstruction and stability pass |
| `PORT-03` | Forecast-vs-realized risk, tails, concentration, stability | `PORT-01`, `PORT-02` | Risk is judged by realized portfolio outcomes |
| `PORT-04` | Typed strategy output, portfolio intent, and dimensioned constraints | `CRY-09`, `RES-09`, `PORT-03` | Units, signs, boundaries, and independent constraints pass |
| `PORT-05` | Static constrained optimizer | `PORT-04` | Feasibility and comparative statics pass |
| `PORT-06` | Shadow prices, transfer diagnostics, binding frequency | `PORT-05` | Every binding constraint has attributed marginal cost |
| `PORT-07` | Conservative fallbacks for stale/missing/infeasible inputs | `PORT-05` | Registered fallback is deterministic and fail-safe |
| `PORT-08` | Dynamic trading interface, simple declared cost baseline, and one-period limit | `CRY-10`, `PORT-05`, `PORT-07` | Higher costs/slower decay reduce trading speed as expected |
| `PORT-09` | Factor, liquidity, funding, crowding, and unwind stress | `PORT-03`, `PORT-08` | Complete portfolio revalues and loss attribution reconciles |

**Exit gate:** realized risk validates forecasts; constraints have explicit units
and diagnostics; infeasible/stale inputs cannot produce optimistic positions; the
optimizer passes limiting cases and comparative statics under the declared simple
cost baseline; stress losses reconcile. Net dynamic-policy claims wait for P5.

## Phase 5: replay, execution, financing, and capacity

**Goal:** replace optimistic execution assumptions with deterministic event paths,
cost attribution, and capacity evidence.

| ID | Deliverable | Depends on | Acceptance evidence |
| --- | --- | --- | --- |
| `EXEC-01` | Order/ack/fill/cancel/reject/correction state machine | `CRY-09` | Impossible transitions and duplicate economics fail |
| `EXEC-02` | Deterministic event replay and equal-time ordering | `DATA-03`, `EXEC-01` | Identical events produce identical state/artifacts |
| `EXEC-03` | Spread, fee, rebate, delay, partial-fill, opportunity-cost models | `EXEC-02` | Hand-calculated implementation shortfall reconciles |
| `EXEC-04` | Impact, participation, urgency, uncertainty, cross-impact interface | `EXEC-03` | Cost responds sensibly to size/urgency; units explicit |
| `EXEC-05` | Capacity curves across capital, participation, horizon, stress | `PORT-09`, `EXEC-04` | Every scale reports net return/risk with uncertainty |
| `EXEC-06` | Crypto margin, liquidation, funding, and financing state | `CRY-09`, `EXEC-01` | Margin/funding/deleveraging golden paths reconcile |
| `EXEC-07` | Decision-to-fill TCA and ledger reconciliation | `EXEC-03`, `EXEC-06` | Decision price through fill and P&L reconcile |
| `EXEC-08` | Vectorized/event-driven parity under aligned assumptions | `CRY-08`, `EXEC-02`, `EXEC-03` | Engines agree within declared tolerance |
| `EXEC-09` | Paper gateway with idempotent client-order handling | `EXEC-01`, `EXEC-02` | Retries cannot duplicate; partial/reject states explicit |

**Exit gate:** event replay is deterministic; order state cannot become impossible;
vector and event engines agree when assumptions match; TCA reconciles; financing
and margin are explicit; capacity is a curve with uncertainty, not one number.

## Phase 6: shadow operation, promotion, and recovery

**Goal:** operate a frozen candidate without capital using immutable artifacts,
observable controls, and tested recovery.

| ID | Deliverable | Depends on | Acceptance evidence |
| --- | --- | --- | --- |
| `GOV-01` | Block bootstrap and multiple-testing policy over governed trials | `RES-02`, `RES-09` | Complete candidate family and dependence blocks retained |
| `GOV-02` | Frozen final-OOS dataset/config/rules and access log | `RES-10`, `GOV-01` | Inputs cannot drift; every access is recorded |
| `GOV-03` | Candidate artifact registry and model card | `ENG-07`, `PORT-09`, `EXEC-05` | Owner, use, limits, dependencies, thresholds required |
| `GOV-04` | Validated promotion/retirement state machine | `GOV-02`, `GOV-03` | Invalid transitions and missing approvals fail |
| `GOV-05` | Live/shadow market-data adapter, reconnect, gap/freshness state | `DATA-03`, `DATA-09`, `EXEC-02` | Recorded/live canonical parity and reconnect/gap fixtures pass |
| `GOV-06` | Build-once artifact packaging/promotion and shadow health checks | `GOV-03`, `GOV-04` | Same digest promotes; provenance/configuration link is complete |
| `GOV-07` | Shadow runner using authoritative/conformant targets | `EXEC-09`, `GOV-05`, `GOV-06` | Artifact/component identity excludes research substitutes |
| `GOV-08` | Research/replay/shadow forecast-to-P&L reconciliation | `GOV-07`, `EXEC-07` | Differences attribute fully or block promotion |
| `GOV-09` | Kill switches for data, risk, infeasibility, rejects, and P&L | `PORT-07`, `GOV-05`, `GOV-07` | Every trigger is exercised, including out-of-process stop |
| `GOV-10` | Metrics, logs, dashboards, alerts, and runbook ownership | `ENG-08`, `GOV-05`, `GOV-07` | One candidate is traceable from source data through P&L |
| `GOV-11` | Rollback, replay, recovery, and incident drills in paper | `GOV-08`-`GOV-10` | Operator recovers; RTO, data loss, manual steps, gaps recorded |

**Exit gate:** a frozen candidate runs in replay and shadow using authoritative or
approved conformant artifacts; recorded and live event adapters agree; stale/gap
state is visible; differences reconcile; kill switches work; operators can
identify, stop, roll back, replay, reconcile, and recover the system; final OOS
remains untouched until precommitted criteria and approvals exist.

## Phase 7: scale and polyglot optimization — conditional

**Entry evidence:** P1 has an end-to-end benchmark; the measured bottleneck cannot
be solved acceptably through algorithm/data-layout improvements in the current
runtime; the expected benefit and operational cost have owners.

| ID | Deliverable | Depends on | Acceptance evidence |
| --- | --- | --- | --- |
| `SCALE-01` | Reproducible workload and bottleneck profile | Relevant completed phase | Profile and target SLO reproduce on controlled hardware |
| `SCALE-02` | ADR: algorithm/layout, multiprocessing, Rust, C++, service, or hardware option | `SCALE-01` | Alternatives, benefit, complexity, migration, rollback reviewed |
| `SCALE-03` | Hermetic multi-language target/toolchain graph if selected | `SCALE-02` | Local/CI outputs match; host dependencies excluded |
| `SCALE-04` | Native or alternate implementation behind existing contract | `SCALE-02`, optionally `SCALE-03` | Shared golden/differential/ABI tests pass |
| `SCALE-05` | Controlled-hardware performance regression gate | `SCALE-04` | SLO and numerical-equivalence thresholds enforced |
| `SCALE-06` | Remote cache/execution if build latency warrants it | `SCALE-03` | Cache correctness, isolation, auth, fallback measured |
| `SCALE-07` | Distributed research compute if workload warrants it | `SCALE-01` | Determinism, retries, quotas, lineage, local fallback pass |
| `SCALE-08` | Monitoring sharding/HA if ingestion/query limits warrant it | `GOV-10` | Failure loses bounded visibility; HA drill passes |

**Exit gate:** the new path demonstrates material measured benefit, preserves
contract/golden results or approved tolerances, has immutable provenance, and can
fall back or roll back without invalidating research evidence.

## Phase 8: cross-asset expansion — conditional

**Entry evidence:** P6 passes for the crypto candidate, a concrete asset-class
research need exists, adequate point-in-time data is available, and domain owners
accept the legal/operational scope.

| ID | Deliverable | Depends on | Acceptance evidence |
| --- | --- | --- | --- |
| `ASSET-01` | Equity sessions, IDs, corporate actions, universe, borrow | P6 plus equity source/data gate | Rename/split/delisting/borrow fixtures and source audit pass |
| `ASSET-02` | Futures contracts, rolls, margin, settlement, delivery | P6 plus futures source/data gate | Listed history remains intact; roll/variation margin reconcile |
| `ASSET-03` | FX spot/forward, settlement, funding, multi-currency | P6 plus FX source/data gate | Carry, settlement, cash, translation reconcile |
| `ASSET-04` | Option chain, symbology, lifecycle, margin | P6 plus options source/data gate | Identity, chain, exercise/assignment/expiry tests pass |
| `ASSET-05` | Curves/surfaces, pricer, Greeks, arbitrage checks | `ASSET-04` | Price identities and finite-difference tolerances pass |
| `ASSET-06` | Fixed-income schedules, curves, prices, DV01 | P6 plus rates source/data gate | Cashflow, clean/dirty price, and DV01 references reconcile |
| `ASSET-07` | End-to-end options portability test | `ASSET-04`, `ASSET-05` | Research-to-shadow multi-leg lifecycle/stress evidence passes |

Each source/data gate extends the P2 point-in-time, quality, lineage, and restart
contracts for that asset. It is not permission to reuse crypto assumptions. Each
adapter receives its own work-package breakdown before implementation.

**Exit gate:** the selected adapter passes connector, instrument, lifecycle,
valuation, accounting, risk, portfolio, execution, governance, and operational
contracts without an asset-specialized breaking change to the shared research or
promotion core.

## Cross-phase acceptance gates

| Gate | Required evidence | Blocks |
| --- | --- | --- |
| Foundation | Clean install, root checks, deterministic identity/artifacts | All implementation |
| Economic slice | Raw-to-report golden reconciliation | General platform expansion |
| Data | PIT queries/universe, revision retention, lineage, restart | Governed model comparison |
| Research | Leakage tests, complete governed trials, reproducible bake-off | Candidate selection |
| Accounting | Cash/position/fee/funding/settlement identities | Portfolio and execution claims |
| Portfolio | Risk calibration, constraint tests, fallbacks, stress | Capacity and shadow |
| Execution | Replay parity, state machine, TCA, financing, capacity | Shadow promotion |
| Governance | Multiple testing, frozen OOS, model card, review | Final OOS |
| Operations | Reconciliation, kill, observability, rollback/recovery | Paper-ready status |
| Scale | Profile, ADR, conformance, controlled benchmark | Native/distributed default path |
| Cross-asset | Source audit plus full shared-contract suite | Asset-class production claim |

## Roadmap health checks

Revisit the plan when:

- A work package cannot state deterministic acceptance evidence.
- Two phases implement the same economic rule independently.
- An abstraction has no current consumer.
- A later phase requires hidden manual state from an earlier one.
- Tooling cost exceeds the measured problem it is intended to solve.
- Data quality cannot support the research claim.
- Research results depend materially on an untracked trial, post-hoc rule, or
  unavailable source.
- Operational recovery depends on the unhealthy process being recovered.

The applicable [definition of done](../architecture/operations.md#definition-of-done)
and [coding standards](../coding_standards/README.md) apply to every work package.
