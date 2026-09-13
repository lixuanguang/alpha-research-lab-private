# Platform design: institutional destination

**Status: planned design.** The repository does not implement the platform described here.

The long-term goal is an institutional-grade monorepo for multi-asset, multi-strategy research, productionization, and
monitoring. It should approach the engineering depth expected at a strong proprietary trading or hedge-fund platform
through measured delivery. The founder is the only current operator, so implementation starts with one useful data-to-
report workload. Staffing, independent review, operational separation, and broader organizational controls arrive as
contributors and operators join.

This design restores the technical destination without restoring a package catalog, a source-file ownership registry, a
mass of empty skeletons, or prematurely installed infrastructure. Every module, service, store, and native lane below is
**PLANNED** unless marked **CURRENT**. A planned name is a boundary proposal, not evidence that the capability exists.

## Architectural stance

The monorepo is one source tree with many possible deployables. It is not one artifact, one process, one database, one
runtime lane, one release train, or a globally coupled release. A strategy library, data normalizer, risk service, and
execution gateway may have separate artifacts and release lifecycles while sharing versioned contracts and provenance.

Canonical economic semantics are shared. Strategy variants, numerical methods, asset adapters, storage engines, and
computation lanes are not forced into one universal implementation. A choice becomes shared when two consumers need the
same invariant or a measured boundary makes the distinction valuable.

Python is the initial implementation language. Rust or C++ may be introduced at a specific measured native boundary for
memory safety, vendor interoperability, or latency. A native choice requires a typed ABI, ownership and error contract,
conformance fixtures, packaging evidence, and a demonstrated budget; language prestige or an anticipated workload is not
sufficient.

The current [architecture overview](README.md) owns active command and dependency boundaries. This page owns future
platform shape, module seams, data and runtime contracts, and the triggers for adding infrastructure.
The [P1 ownership map](../roadmap/p1-implementation-roadmap.md#p1-code-ownership-and-call-flow) specializes this design
into the next working acquisition, dataset and research pipelines. Only orchestrator pipelines compose workflows;
other implementation modules expose library operations under the [engineering rule](../coding_standards/README.md#orchestrator-pipelines-and-libraries).

## Current and planned repository shape

The existing tree contains the domain, event/decoder and reference foundations plus development tooling. The following
tree shows the intended layout without creating directories before their consumers exist:

```text
src/alpha_research/
  financial_units/          CURRENT: exact values and date conventions
  instrument_identity/      CURRENT: canonical IDs and temporal mappings
  venue_calendar/           CURRENT: bounded venue/session state
  core/                     CURRENT: event provenance; further shared contracts as needed
  configuration.py          PLANNED: typed configuration reading, validation and resolution
  data/                     CURRENT: events and decoding; PLANNED: transport, raw storage, PIT datasets
  research/                 PLANNED: observations, features, labels, trial/report operations
  pipelines/                PLANNED: acquisition, dataset, EDA/replay, live, research and runtime orchestration
  strategies/               PLANNED: strategy kernels and versioned configs
  simulation/               PLANNED: replay, fills, costs, market mechanics
  portfolio/                PLANNED: targets, constraints, allocation, netting
  risk/                     PLANNED: independent limits and risk decisions
  accounting/               PLANNED: positions, cash, ledger, reconciliation
  execution/                PLANNED: order state and OMS contracts
  venues/                   PLANNED: broker and venue protocol adapters
  runtime/                  PLANNED: process lifecycle and durable-state library contracts
  telemetry/                PLANNED: bounded metrics, traces, and audit events

configs/                    CURRENT: authored reference data; PLANNED: implementations, bindings and active instances
apps/                       PLANNED: independently deployed pipeline entry points when needed
deploy/                     PLANNED: environment definitions and non-secret config
packages/                   OPTIONAL PLANNED: separately packaged shared libraries
tools/
  governance/               CURRENT: development checks and artifact boundaries
  native/                   PLANNED: only when an admitted ABI exists
tests/
  unit/                     CURRENT: domain behavior and focused contracts
  golden/                   CURRENT: three domain fixtures
  integration/              PLANNED: installed boundaries and replay parity
  scenarios/                PLANNED: accounting, recovery, and risk drills
```

These names describe responsibilities rather than a required package count. A future implementation may combine small
modules when their state and lifecycle are the same. It should split a boundary when it has different ownership, failure
handling, release cadence, or data authority.

## Dependency and interface graph

The intended information flow is:

```text
canonical types and schemas
        |
        +--> instrument and venue reference state
        +--> raw/source adapters --> normalized events --> PIT datasets
                                                        |
                                                        +--> features/labels
                                                        +--> research reports
                                                        +--> replay/simulation
                                                              |
                                                              v
                                                        strategy kernel
                                                              |
                                                              v
                                                        portfolio intent
                                                              |
                                    positions + pending orders + limits
                                                              |
                                                              v
                                                     independent risk
                                                              |
                                                              v
                                                        OMS/order state
                                                              |
                                                              v
                                                     broker/venue adapters
```

Portfolio intent enters the independent risk boundary together with authoritative positions, pending orders and limits.
Execution events flow back into accounting and risk snapshots. This runtime feedback does not require cyclic library
imports: the existing domain foundations and narrow contract modules sit below strategy/data/portfolio/risk/accounting/
execution implementations; application composition roots depend on those implementations and connect them.
A strategy may read an approved position and risk snapshot, but the risk decision cannot call the strategy to decide
whether its own limit is valid. Accounting does not import a broker SDK. Test the import direction as actual modules
appear, alongside order-to-fill-to-ledger conformance traces at the connected boundaries.

Cross-process messages use versioned schemas and explicit compatibility rules. In-process code uses typed functions and
cohesive classes; introduce protocols for real interchangeable implementations or useful test boundaries. A measured
native boundary warrants an explicit ABI. Provider objects,
exceptions, timestamps with unknown timezone semantics, and mutable registries stop at adapters.

## Configuration and active workflows

This is a planned boundary under the
[configuration-driven implementation standard](../coding_standards/README.md#generalized-code-and-configuration-driven-activation).
The current authored instrument catalog supplies reference facts and assumptions;
it does not select active assets or strategies. Introduce a small typed file
reader with the first acquisition consumer, then extend its records with actual
strategy consumers. JSON fits the existing serialization boundary; multiple file
formats, a registry service and a configuration programming language are unnecessary.

Keep these responsibilities distinct, whether the records live in one file or
in explicitly referenced versioned files:

| Configuration record | What it declares | What consumes it |
| --- | --- | --- |
| Implementation definitions | Stable IDs/versions for reviewed installed strategy, pipeline and adapter entry points, with their supported input/output contracts and capabilities. Configuration cannot grant capabilities absent from the implementation. | A configuration resolver validates references/records; the orchestrator loads, checks and constructs the selected implementation. Foundation/config libraries do not import pipelines or providers. |
| Instrument/reference and universe definitions | Canonical IDs, temporal membership/source/venue mappings, applicable increments/multipliers/currencies and market rules, with evidence semantics. | Data, strategy and accounting validation. Catalog membership is not collection, research selection or trading authority. |
| Data jobs and pipeline bindings | Job ID, source, dataset/stream type, pipeline, independently selected universe, historical/live mode, interval, policies and explicit raw/snapshot references. | Acquisition, dataset or live orchestration. The collection universe may exceed a strategy's universe. |
| Strategy definitions | Strategy ID/version, implementation, parameters, declared input/output capabilities and named data/feature/model requirements. | Strategy-instance resolution and contract validation; formulas remain in strategy code. |
| Strategy instances | Instance ID, strategy reference, selected assets and dependency bindings, supported mode and isolated state namespace. Active instances are selected per workflow. | Research/runtime orchestrators and per-instance trials/results; multiple instances can share compatible immutable inputs. |
| Deployment and authorization, when implemented | Deployment/environment, instance/artifact versions, account/venue/execution connections, independently approved instrument/limit/duration envelope and monitoring/risk bindings. | Runtime orchestration within existing release/operating boundaries. Research config cannot grant executable access. |

For example, a `return_momentum` implementation can have a BTCUSDT instance and
an ETHUSDT instance with different configured quantities. Both refer to their
canonical instrument IDs and compatible trade-data bindings. Enabling the second
instance changes configuration, while the observation, decision, fill and ledger
operations keep their role-based names and explicit inputs. This demonstrates
reuse within supported spot mechanics; it does not authorize another empirical
experiment or establish support for a derivative or a multi-currency portfolio.

The orchestrator reads a selected configuration, resolves the active data jobs or
strategy instances and their bindings, validates references, units and capability
compatibility, then composes the requested workflow. Relationships are many-to-many:
one strategy may use several instruments/sources, and several strategies may share
a dataset or collection job. A strategy-driven acquisition derives requirements
from its selected instances; an independent data job owns its broader collection
scope. Deactivating a strategy does not implicitly stop that collection. Avoid a
platform-global mutable active asset/pipeline. Use a small declarative
mapping to reviewed installed entry points with a typed contract, so adding a
compatible strategy does not require editing a shared strategy-name dispatch
chain. Resolve only explicit installed implementations; do not evaluate formulas
or arbitrary commands from configuration. Keep construction and sequencing in
the pipeline, with parsing and validation as reusable library operations.

Acquisition, dataset building and saved-snapshot research remain separate
workflows. A research input binding identifies the required saved dataset; it
does not implicitly trigger a download. Inactive definitions cause no workflow
execution. Reuse immutable inputs only when their complete identities and
requirements match; keep mutable state and outputs separate for each strategy
instance. P1 is planned to execute independent instances sequentially without introducing
concurrency or cross-strategy portfolio allocation.

Retain an immutable resolved run manifest with actual universe membership and
reference versions, parameters/policies, implementation/code/schema versions,
source/input identities and run/instance/state namespace as applicable. Add
deployment identity with its consumer; keep attempt clocks outside semantic identity.
A mutable config name or model alias alone cannot identify what ran. Reject missing selections and unsupported
combinations before workflow effects. New assets using existing mechanics need
configuration/reference additions; new algorithms need strategy code and config.
A missing representation, source protocol, lifecycle or monitoring behavior
requires an implementation at that owning boundary before activation can succeed.

## Canonical economic and temporal model

The current [instrument identity](instrument-identity.md), [venue calendar](venue-calendar.md), and [financial units](financial-units.md)
contracts remain the foundation. A future core layer extends them; it does not replace them
with vendor symbols, floating-point money, or a generic model framework.

### Identity and lifecycle

`InstrumentId` remains stable across alias changes and provider renames for the same identified instrument. A distinct
relisting has its own ID linked to the economic root, as the current identity contract requires. Planned `ContractSpec` records
add effective-dated quantity units, price units, multipliers, tick and lot rules, currencies, settlement, and lifecycle
state. A derivative references an internal underlying ID. A continuous futures series is a derived research product and
never a listed contract.

Future lifecycle records represent listing, activation, trading halt, expiry, exercise, assignment, delivery, delisting,
redenomination, and corporate-action effects as explicit versioned events. They retain the source assertion and
effective interval. A correction appends a revision and identifies datasets, models, positions, and releases that may be
affected.

### Market events and time

Planned `MarketEvent` schemas cover trades, quotes, books, bars, funding, fixings, settlements, corporate actions,
curves, volatility points, and venue state. Every event carries at least:

| Field | Contract |
| --- | --- |
| `ts_event` | When the economic event occurred, at source precision |
| `ts_received` | When the platform first received the payload |
| `ts_ingested` | When the payload entered governed storage |
| `ts_knowledge` | Earliest time a validated version could be used |
| `valid_from`, `valid_to` | Business interval for reference state |
| `source_revision` | Source sequence, file, or revision identity |
| `schema_version` | Version of the canonical event shape |
| `correction_id` | Link to an append-only correction when applicable |
| `source_digest` | Identity of the raw payload or source partition |

For a decision at `decision_time`, every feature input, reference record and risk value consumed by that decision must
satisfy `ts_knowledge <= decision_time`. Forward labels become available later: training may use a label only after its
outcome is knowable at the fitting cutoff; retrospective evaluation keeps those outcomes separate from decision inputs.
Event time is not knowledge time, and valid time is not receipt time. A source that
cannot support the required availability semantics is usable only for an explicitly limited engineering or exploratory
result.

Point-in-time selection resolves the record valid at the requested business time from revisions known at the requested
knowledge cutoff. It returns the selected revision, source digest, transformation version, and quality state, so a later
correction can invalidate affected products without rewriting the original result.

## Data source, storage, and lineage design

Every source adapter is responsible for authentication, rate limits, pagination, source-specific identifiers, source
timestamps, and raw payload capture. It does not expose its SDK models to research or execution code.

The planned data flow is:

```text
source adapter
    -> immutable raw landing + receipt metadata + source digest
    -> normalization and validation
    -> canonical events/reference state
    -> correction-aware PIT partitions
    -> dataset manifest and quality report
    -> feature/label products and research consumers
```

Raw inputs are append-only and retain entitlement, license, encryption, and retention metadata. Canonical records retain
source pointers and deterministic transform versions. Curated partitions are immutable products identified by a manifest
of partition digests, specification, code, dependencies, and source revisions. Publications are atomic: readers see
either the old manifest or the new manifest, never a partially written partition.

The first implementation may use ordinary files and a local database where that is enough for one workload. A lakehouse,
object store, event log, or online feature store is **PLANNED**, not a prerequisite. Add one when measured volume,
concurrent readers, retention, recovery, or cross-process latency requires it.

Dataset specifications declare universe eligibility, event fields, source priority, schedule, timezone, calendar,
interval, lookback, warm-up, availability cutoff, correction policy, adjustment/roll policy, missing/stale rules,
expected partitions, and quality thresholds. A new specification or policy produces a new dataset identity.

Quality states are explicit: informational records remain visible; degraded data may be used only with a visible
limitation and stated scope; hard failures prevent publication; and an incident identifies affected products,
experiments, candidates, and releases for replay.

The [delivery plan](../roadmap/capability-milestones.md) places basic normalization,
coverage/identity/time checks and atomic publication in M1, before a dataset is
advertised as valid. M2 supplies selective, versioned, bounded-memory EDA and replay
without a live feed or hosted service dependency. Market-event access and feature
serving are distinct contracts even if they share storage.

Historical ingestion and live capture converge on compatible canonical envelopes
while retaining source/receipt/availability differences. M3 adds tested `valid`,
`degraded`, `stale`, `recovering` and `unavailable` transitions with consumer actions,
backpressure and synchronization. Replay the exact locally captured inputs and
receipt order to establish parity; a later vendor archive cannot stand in for
what the local system knew. A decoded depth update alone does not establish a
valid book after a gap; enable that consumer only with its reconstruction contract.

## Dataset, feature, label, and experiment contracts

Planned dataset, feature, label, signal, model, cost, risk, portfolio, and candidate records carry identity, version,
inputs, units, availability, owner, and failure policy. They are small records around real consumers, not a global
registry that every exploratory file must enter.

Features are deterministic functions of PIT datasets. Metadata names every input, transform version, availability delay,
units, missing policy, range, and training fit interval. Labels name observation horizon, execution delay, price
convention, overlap, and missing policy. Scaling, neutralization, imputation, selection, and hyperparameters fit only on
data available in the applicable training interval.

An experiment identity includes source and dataset manifests, code/artifact revision, resolved non-secret configuration,
environment/toolchain identity, component versions, split rules, and random seeds. Wall-clock creation time is metadata,
not identity. Failed or rejected trials that influence selection remain append-only, and the final holdout is frozen
before evaluation.

Research reports state the economic mechanism, falsifiable hypothesis, target, sign, horizon, universe, rebalance,
benchmark, expected turnover/liquidity, cost and capacity assumptions, metrics, rejection criteria, and limitations.
Once an exploratory result influences a candidate decision, it receives durable identity and provenance.

## Shared strategy and simulation parity

The strategy kernel is typed deterministic logic with injected clocks, data, positions, risk decisions, and execution
interfaces. It contains economic decision logic, not a broker client, database transaction, or self-approval path.

The same kernel runs in these modes:

| Mode | Purpose and boundary |
| --- | --- |
| Unit/golden | Exact fixtures and hand-calculated behavior |
| Replay | Historical canonical events with deterministic state transitions |
| Simulation | Replay plus declared fill, latency, cost, and market-mechanics models |
| Paper | Live or delayed data with simulated order/fill lifecycle and no executable venue submission |
| Shadow | Live decisions and risk traces with venue submission suppressed |
| Canary | Bounded live venue activity under an explicit activation envelope |
| Live | Only after release, risk, reconciliation, stop, and monitoring evidence |

Simulation declares what it omits: queue priority, venue throttles, partial fills, market impact, borrow recalls,
funding timing, auctions, disconnects, or other behavior. A result cannot silently imply omitted mechanics. Replay and
paper compare decisions, target quantities, risk decisions, order intent, and state traces; differences are classified
by data, timing, randomness, market mechanics, or implementation before advancement.

## Portfolio, accounting, and position state

Portfolio construction consumes forecasts, current positions, risk budgets, costs, liquidity, financing, and
constraints. It produces dimensioned desired exposures or quantities with a validity interval and fallback. It never
places orders. An infeasible or stale input takes a deterministic conservative path.

The planned accounting boundary owns positions, lots or contract quantities, cash by currency, accrued amounts,
margin/collateral, financing, fees, dividends, coupons, funding, variation margin, exercise, assignment, delivery, and
settlement events for supported asset classes. Money and quantities use the current exact financial-unit contract;
weight-only state cannot replace an economic position.

Each accepted fill changes economic state exactly once. Rejected or canceled quantity never becomes a position. Realized
and unrealized P&L use one authoritative definition. Base-currency translation names its FX source and timestamp. NAV
reconciliation checks beginning NAV plus external cashflows, trading/marking P&L, financing, and lifecycle cashflows
against ending NAV within a declared tolerance.

State is event-identified and restartable. A durable snapshot records the last applied event sequence, release identity,
account/venue identity, and schema version. Recovery replays subsequent events idempotently; order, fill, cancel,
correction, and ledger-event identities are unique across retries.

An active process carries a fencing epoch or lease. A restarted process cannot write orders or ledger state after its
epoch is revoked. Startup validates release/schema compatibility, loads the latest valid snapshot, reconciles open
orders and positions with the venue, and enables only explicitly allowed actions. A mismatch pauses new risk and orders.

## Multi-strategy netting and isolated risk

Every strategy intent retains strategy ID, model/config revision, decision time, account, portfolio, instrument, side,
quantity or exposure, horizon, and reason metadata. Allocation and execution may net compatible intents to reduce cost,
but the ledger keeps pre-net intents and post-net order lineage.

Netting is permitted only when account, currency, venue, instrument contract, settlement, risk bucket, and authority
scope are compatible. It never erases strategy attribution, prevents a strategy-level stop, or transfers a loss budget
without policy. Residual and shared costs use a stable documented method and remain reversible for reconciliation.

The planned risk boundary computes portfolio, strategy, and account views with gross/net exposure, leverage,
concentration, liquidity, margin, stress loss, sensitivities, and loss limits as applicable. Strategy budgets nest under
account and firm limits. A strategy can be disabled while others continue only if resulting net exposure and shared
limits remain safe; otherwise the account or venue is fenced as a whole.

Risk consumes authoritative positions, pending orders, market state, limits, entitlements, and activation state. Missing
or stale inputs, unavailable limits, timeout, unknown instrument, or failed authorization rejects new risk with a
visible reason. Kill and cancel controls remain reachable when a strategy process is unhealthy.

## OMS and venue adapter design

The planned OMS owns canonical intent, order, acknowledgment, partial fill, cancel, reject, correction, and
reconciliation state. It assigns stable IDs and maps strategy intent through net order to venue order and fill. It does
not decide economic targets or override risk.

Venue adapters translate canonical orders into one broker or venue protocol. They own credentials, throttles, sequence
numbers, venue-specific timeouts, retry rules, idempotency keys, and source errors. They expose normalized events back
to the OMS and retain raw protocol messages for investigation.

A retry cannot create a duplicate economic order. Where a venue lacks a native idempotency key, the adapter uses durable
client identity and reconciles before retrying. Partial multi-leg fills remain explicit; temporary leg exposure is
visible to risk. Decision, arrival, fill, fee, and benchmark prices are retained for transaction-cost analysis.

## Asset-class specializations

The canonical model is shared, but each asset class owns lifecycle and market mechanics. Unsupported features fail
explicitly rather than falling back to equity-like behavior.

**Equities — PLANNED.** Add identifiers, listings and delistings, corporate actions, auctions, short-sale and borrow
state, dividends, settlement, and jurisdiction-specific restrictions. Raw prices and actions remain beside derived
adjusted series.

**Futures and commodities — PLANNED.** Add expiries, delivery and last-trade lifecycle, multipliers, tick values,
variation margin, rolls, spreads, settlement, and delivery risk. Continuous series remain derived.

**FX — PLANNED.** Add base/quote direction, holiday-center combinations, spot dates, forwards, swap points, broken
dates, funding curves, and venue conventions. FX conversion cannot rely on an implicit global currency.

**Options and volatility — PLANNED.** Add point-in-time chains, underlying and forward links, exercise and settlement,
corporate-action adjustment, surfaces, Greeks, multi-leg orders, assignment, and margin. Covariance and full-revaluation
stress remain distinct calculations.

**Fixed income and rates — PLANNED.** Add schedules, accrued and clean/dirty price, discount/projection curves, fixings,
resets, issuer hierarchy, embedded options, financing, DV01, key-rate, and scenario risk.

**Digital assets — OPTIONAL PLANNED.** For centralized venues, add continuous sessions, spot/perpetual contract rules,
funding, index/mark prices, collateral haircuts, liquidation and venue credit risk. For on-chain strategies, add chain
and token identity, finality, reorgs, gas, nonce and custody state, AMM/oracle semantics, MEV, and bridge/transfer risk.
Apply stablecoin FX and venue/chain outage scenarios where relevant. Only the selected operating scope is required.

**Low-latency market making — OPTIONAL PLANNED.** Keep L2/L3 reconstruction, queue priority, cancel/replace latency,
inventory, adverse selection, and venue throttles in a specialized subsystem. Do not distort a medium-frequency
simulator for an unmeasured hot path.

## Runtime lanes and deployment

The platform has three possible lanes with one shared semantic waist:

1. **Batch/research — PLANNED.** Dataset construction, features, simulation, training, and reports run with reproducible inputs and bounded parallelism.
2. **Ordinary event-driven — PLANNED.** Ingestion, strategy, portfolio, risk, OMS, accounting, and reconciliation run as supervised processes with durable state and explicit restarts.
3. **Latency-sensitive — OPTIONAL PLANNED.** A native component or dedicated host is added only after a measured latency, jitter, or vendor ABI need. It consumes compatible schemas and remains behind independent risk and kill controls.

Lanes may use different artifacts, process models, stores, and release cadences. A deployment is placement of an
immutable compatible artifact; it does not grant trading authority. Activation is a separate envelope naming accounts,
venues, instruments, capital, limits, duration, credentials, and stop conditions.

## Artifact, schema, and state migration

An artifact identity binds source commit, build command, dependency lock, platform, configuration, model/data
references, schema versions, limits, and complete artifact digest. Build once and promote the same bytes. The retained
[artifact boundary](artifact-supply-chain.md) is the reference for this identity and verification contract.

Schema changes use explicit versions and compatibility windows. The normal migration is expand, dual-read/write where
necessary, backfill or reconcile, cut over, then contract. A reader rejects unknown incompatible versions with a visible
reason. State migration includes a replay fixture, compatibility check, rollback point, and proof that old orders/fills
cannot be applied twice.

Model, dataset, and configuration changes are separate identities even when they share one release artifact. A rollback
selects a compatible prior set of code, model, data, schema, limits, and state; reverting only a Python wheel is unsafe
when state or schema changed.

## Monitoring, recovery, and operational evidence

Planned telemetry correlates release, strategy, model, dataset, account, instrument, venue, order, fill, state epoch,
and incident without unbounded labels on a hot path. Events carry units, clock quality, and sensitivity classification.
Latency-sensitive emission is bounded and loss is observable; telemetry failure cannot disable an emergency stop.

Minimum signals include stale or missing data, heartbeat loss, sequence gaps, reject/error bursts, clock drift, risk-
limit breaches, position/cash mismatch, open-order mismatch, fill duplication, reconciliation failure, resource
exhaustion, and alert-delivery failure.

Deliver the applicable signals with the first working capability: batch progress,
invalid counts and persistence failures in M1; advancing ingestion, freshness,
queues and recovery in M3; query resource/failure visibility in M2; execution,
attribution and risk state in M6/M7. A live heartbeat with no advancing work must
be distinguishable from a healthy service. Test process/collector loss and alert
delivery; hard risk controls do not depend on telemetry availability. Instrumentation
or model-tracking products supply adapters, not the domain checks or responses.
Every deployed strategy needs operational/economic monitoring; learned-model checks
add feature freshness, prediction behavior, inference failures and delayed-label
evaluation through the same versioned research definitions.

On a material signal, safe response stops new risk, cancels where safe, fences the affected process or account,
preserves raw and normalized evidence, reconciles the venue, and records release/configuration identity. Restart follows
state, schema, credential, limit, and fencing checks. Backup/restore, stop/cancel, replay, rollback, and alert delivery
are tested before a canary receives more exposure.

## Security, entitlements, and organization

Secrets stay outside source, fixtures, logs, and artifacts. Data rights, retention, venue permissions, account scope,
and broker terms are checked for the actual source and deployment. A development wheel does not create market,
credential, or capital authority. External legal and source obligations remain applicable throughout the solo phase.

The founder may implement and activate a bounded system while working alone when technical safety and release checks
pass. Onboarding progressively adds independent domain review, security review, deployment authority, risk ownership,
and operational coverage. Controls attach to real people, accounts, and responsibilities when those exist; they do not
block an ordinary local calculation by pretending unavailable roles are present.

## Scaling triggers and technology choices

Keep the current Python/uv path while it is reproducible and within the workload budget. Measure before adding a second
build system, remote execution, large database, feature store, distributed event bus, or HPC scheduler.

Useful triggers include a dataset build that misses research cadence, concurrent readers that contend on local storage,
replay throughput that blocks iteration, recovery time beyond the operating target, or measured native latency/jitter
that Python cannot meet. Each trigger records the measurement, failure mode, target, cost, and rollback path.

HPC or distributed execution is a batch optimization, not a new semantic lane. Workers receive immutable partition
identities and deterministic seeds; output manifests are reconciled before publication. Remote caching or execution is
not introduced merely to reproduce an institutional pattern.

A Rust or C++ component preserves the Python reference's goldens and accounting/risk decisions. Its ABI names
allocation, ownership, error, threading, layout, numeric representation, version, and shutdown behavior. The native
artifact is admitted and tested for every supported platform before a consumer depends on it.

## Delivery sequence

The [platform roadmap](../roadmap/README.md#priority-and-completion-model) owns maturity and status;
the [capability milestones](../roadmap/capability-milestones.md) own MR delivery and demonstrated exits.
Validated historical data leads to EDA/replay and independent research/backtesting
while reliable live capture advances alongside them. Features/models are added
with their consumers; paper/shadow precedes controlled live operation. The people-triggered organizational workstream is last in
speculative priority. Technical scaling does not require hiring first, and onboarding does not wait for platform scale.

Each slice leaves the previous path usable or provides a tested rollback. It states what is implemented, what remains
planned, which identity is authoritative, and which failure response is safe. The architecture evolves by measured
boundary decisions rather than by filling the planned tree in advance.
