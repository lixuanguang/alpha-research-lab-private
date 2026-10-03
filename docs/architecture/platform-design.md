# Platform design: institutional destination

**Status: destination design with current functional ownership.** The source tree
below distinguishes implemented capabilities from planned infrastructure.

This index retains functional ownership, dependency direction and configuration
boundaries. Detailed contracts have cohesive homes:

| Reader task | Design chapter |
| --- | --- |
| Resolve identity, clocks, source contracts and storage lineage | [Economic and market-data design](economic-and-market-data-design.md) |
| Define datasets, features, candidates and simulation behavior | [Research and simulation design](research-and-simulation-design.md) |
| Coordinate portfolios, account state, risk and venue orders | [Portfolio and execution design](portfolio-and-execution-design.md) |
| Plan deployment, migration, monitoring, security and scaling | [Runtime and operations design](runtime-and-operations-design.md) |

The long-term goal is an institutional-grade monorepo for multi-asset, multi-strategy research, productionization, and
monitoring. It should approach the engineering depth expected at a strong proprietary trading or hedge-fund platform
through measured delivery. Quant development delivers the complete initial
OKX/Bitfinex spot research and paper infrastructure before QR onboarding, using
its own reference research and operating workloads. The [roadmap's onboarding gate](../roadmap/README.md#infrastructure-completion-before-qr-onboarding)
defines the required scope and separates software completion from empirical
strategy acceptance and live activation. Staffing, independent review, operational
separation and broader organizational controls arrive as contributors and operators join.

The roadmap's intermediate research, shadow and operating gates improve delivery
sequencing within that paper scope. Versioned offline/online
feature-store capabilities, both venues' paper execution, portfolio allocation/netting,
extensible dashboards and capacity qualification remain required. The initial
spot integrations exercise generalized contracts for other sources, products and
strategies; they do not define the limits of the monorepo's architecture.
Live execution and qualification remain
[KIV pending profitable OOS and paper evidence](../roadmap/README.md#live-trading-kiv-and-reconsideration);
retained live design contracts below are outside the initial delivery gate.

This design records the technical destination and functional source owners without
requiring empty skeletons or prematurely installed infrastructure. Every module, service, store, and native lane below is
**PLANNED** unless marked **CURRENT** or listed as an existing capability in the source tree.
Source-layout completion is not evidence for future capability or operational acceptance.

## Architectural stance

The monorepo is one source tree with many possible deployables. It is not one artifact, one process, one database, one
runtime lane, one release train, or a globally coupled release. A strategy library, data normalizer, risk service, and
execution gateway may have separate artifacts and release lifecycles while sharing versioned contracts and provenance.

Qualify that separation with installed consumers: collector and execution
artifacts must not require unrelated notebook, training, research-reporting or
experiment SDKs. Keep the full research environment and separately locked workers
available. Dependency isolation removes accidental coupling, not platform features;
each deployed graph still satisfies admission and compatibility requirements.

Canonical economic semantics are shared. Strategy variants, numerical methods, asset adapters, storage engines, and
computation lanes are not forced into one universal implementation. A choice becomes shared when two consumers need the
same invariant or a measured boundary makes the distinction valuable.

Required platform consumers are authored by quant development before QR joins:
rule-only and learned studies, stateful features, multi-instance paper workloads
and custom report/monitoring components. A working-consumer requirement does not
mean waiting for a QR hypothesis, selected model or profitable strategy. Reference
workloads exercise real shared implementations; empty interfaces and fixed demos
that cannot accept another compatible implementation do not complete a capability.

Python is the initial implementation language. Rust or C++ may be introduced at a specific measured native boundary for
memory safety, vendor interoperability, or latency. A native choice requires a typed ABI, ownership and error contract,
conformance fixtures, packaging evidence, and a demonstrated budget; language prestige or an anticipated workload is not
sufficient.

The current [architecture overview](README.md) owns active command and dependency boundaries.
This index owns future platform shape and module seams; the linked design chapters
own the detailed data/runtime contracts and infrastructure triggers.
The [infrastructure roadmap](../roadmap/README.md) selects delivery work against
these boundaries. Bare functions serve workflow orchestration; reusable library
behavior belongs to cohesive classes under the
[engineering rule](../coding_standards/README.md#orchestrator-pipelines-and-libraries).
Remaining ownership/enforcement work is tracked in the roadmap.

## Current and planned repository shape

The current implementation uses functional packages directly under `src/`.
Applications and libraries follow the public API and dependency rules below.

Unannotated source capabilities in the following tree are **CURRENT**. Entries
marked FUTURE or PLANNED remain unimplemented; the roadmap makes in-scope behavior
mandatory before QR onboarding through reference consumers owned by quant development.
CONDITIONAL or OPTIONAL layout/technology choices do not defer required behavior.
The extra `market_data/books/` owner
holds the existing shared book state/reconstruction used by capture and replay.

```text
src/
  reference_data/
    instruments/            Canonical identity and temporal symbology
    calendars/              Sessions, calendars and market status
    catalogs/               Authored instrument/reference snapshots
    eligibility/            Bitemporal universe membership and evidence
  financial_units/          Exact values, dimensions and conventions
  market_data/
    contracts/              Records, provenance and source/reader interfaces
    acquisition/            Historical acquisition policy and checkpoints
    collection/             Receipt, session recovery and canonical capture
    adapters/
      sources/              Explicit reader/verifier and native-book selection
      wire/                 Strict vendor JSON primitives
      transport/            Shared native feed transport
      providers/            Binance archives, Tardis framing and transport
      venues/               Binance, Bitfinex, Coinbase and OKX feed semantics
    storage/                Verified raw bytes, capture journals and pinned lakeFS dataset versions
    validation/             Quality, lineage, revisions and freshness gates
    datasets/               Assembly, manifests, publication and reopening
    query/                  Point-in-time selection and projections
    replay/                 Historical stepping, cursors and saved replay
    books/                  Shared reconstruction, independent book registry and causal consolidated BBO
  research/
    exploration/            EDA and pinned multi-input saved-data selections
    results/                Shared retained feature-study wire contract
    observations/           Frozen completed decision observations and scoped controls
    features/               Versioned definitions/fitting, causal history, incremental state and isolated Feast serving
    labels/                 Separate forward-return outcomes and availability
    models/                 Exact linear construction, retained state and inference
    experiments/            Attempt storage, semantic identities and temporal splits; FUTURE: candidates
    studies/                Retained evaluations, diagnostics, reports and local ClearML pipelines
  strategies/               Fixed completed-price momentum and no-trade target rules
  simulation/               Delayed spot fills/costs/checkpoints and bounded vectorbt adapter
  accounting/               Exact spot attribution and identified account postings/corrections
  risk/                     Independent spot grids, authority and instance/account/firm budgets
  portfolio/                Shared-account context and exact fill/fee allocation; economic optimizer planned
  execution/                Paper OMS, shared-account admission/netting and matching; future venue adapters
  runtime/                  Candidate/shared-decision supervision, identity, bounded jobs and workspace recovery
  telemetry/                Health/alerts; future runtime and economic monitoring
  configuration/            Typed definitions and explicit selection
  serialization/            Exact domain codecs and strict wire records
  applications/
    acquire/                Existing historical/archive command and workflow
    collect/                Existing capture/probe/replay command and workflow
    publish_dataset/        Existing dataset publish/inspect command
    inspect_fixture/        Existing configured fixture command
    explore/                EDA, feature/label/model studies and ClearML publication
    train_model/            OPTIONAL source split; fit/state behavior required through explore or this owner
    evaluate_model/         OPTIONAL source split; evaluation required through explore or this owner
    backtest/               Economic Python workflow and tracked vectorbt comparison
    execute/                CURRENT: installed intent/risk admission with submission suppressed
    paper/                  CURRENT: dedicated and shared-account paper/shadow composition
    live/                   FUTURE: explicitly authorized operation
    deploy/                 OPTIONAL future composition; local installer is governance CLI

configs/                    CURRENT: reference/source selections, studies, backtests and local services; FUTURE: deployment/activation bindings
deploy/                     PLANNED: environment definitions and non-secret config
packages/                   CURRENT: shared contracts and independent collector/execution distributions
tools/
  governance/               CURRENT: checks, signed operating releases and trusted local installation
  native/                   PLANNED: only when an admitted ABI exists
tests/
  unit/                     CURRENT: domain behavior and focused contracts
  engineering/              CURRENT: source, packaging and governance contracts
  golden/                   CURRENT: three domain fixtures
  fixtures/                 CURRENT: static inputs organized by domain and scenario
  support/subprocesses/     CURRENT: process-level fakes and interruption drivers
  integration/              CURRENT: workflow tests and standalone installed consumers
  scenarios/                PLANNED: accounting, recovery, and risk drills
```

Application source has one home, `src/applications/`; do not also create a root
`apps/` tree or a `pipelines/` implementation of the same workflow. Root `deploy/`
contains deployment definitions, while `applications/deploy/` owns executable
installation composition. Market-data adapters and execution adapters stay with
their respective capabilities; there is no mixed top-level `venues/` package.

One `alpha-research-lab` distribution installs all thirteen functional roots using the
existing uv build path and frozen dependency set. Distribution names, deployable artifacts and Python
package names are separate decisions. Neither preserving the old import prefix
nor creating one distribution per folder is required. Supporting module filenames
can evolve within the named owners; changes to an owning boundary must update
the roadmap and its consumers together.

The [tests guide](../../tests/README.md) defines the current fixture, subprocess
and installed-consumer layout and its execution boundaries.

### Functional APIs and application entrypoints

These rules apply to the current implementation and subsequent work. The
engineering check validates owned imports, explicit APIs and command metadata.

- Each owned library package exposes one curated public API module,
  `__init__.py`, containing actual exported types/operations and explicit
  `__all__`. It has zero runnable command entrypoints. Cross-owner consumers use
  that API; implementation modules within an owner may import directly.
- Grouping parents do not eagerly re-export all child packages. Keep contracts
  independent of implementation imports so using an instrument ID does not
  initialize catalogs, applications or adapters. A private helper shared only
  within one functional owner stays internal to that owner.
- Each application directory has at most one runnable entry function, `main`,
  exported through its public API and used by its installed command. Related
  actions are subcommands. A callable-only consumer need not acquire a CLI.
  Programmatic orchestrators may be exported from the same API; the rule limits
  public entry modules and runnable entry functions, not the number of useful
  library methods or genuine orchestration steps.
- Applications compose libraries and explicitly selected adapters; libraries
  never import applications, and applications never import sibling application
  workflows. Shared behavior belongs to its functional library owner.
- Neutral records and source/reader protocols do not import concrete adapters,
  storage implementations or application composition. Storage, quality and
  replay receive the capabilities needed for their contracts; moving files must
  not remove validation or source-specific semantics to satisfy import checks.
- Configuration resolves typed definitions without importing applications or
  selecting factories. Runtime supervision receives a workload explicitly and
  never imports the application it supervises. Strategy logic cannot construct
  executable venue clients or change independent risk/activation policy.

The engineering checker enforces imports, public APIs and entrypoints for the
current source tree. New capabilities follow these rules when they gain a working
consumer; no empty-folder or framework mandate is implied.

**Supported imports.** The supported Python API is exactly the `__all__` of each
functional owner's `__init__.py`: the top-level packages and the owner
subpackages of the grouping namespaces `market_data`, `market_data.adapters.*`,
`reference_data`, `research` and `applications`. Deep modules, private names,
grouping namespaces and command implementation modules are not supported even
when they are importable. The maintained reference workflows (integration
consumers, integration and engineering tests, subprocess support and
`examples/`) import only supported names, and the ownership check enforces this;
unit tests may also import public names from the deep modules they test. An
owner may export a name lazily through a checked `__getattr__` when an
independently installed distribution does not ship the module behind it, as
`applications.execute` does for its paper-service composition. The installed
wheel smoke resolves every exported name, lazy ones included.

The MR03 offline study API carries explicitly supplied compatible features,
transforms, estimators, rules, execution/cost assumptions and metric/chart definitions
through `applications.explore.evaluate_study` and `compare_studies`. Typed and
serialized configuration identify the same run; retained implementation bytes,
resolved folds and typed result/report readers preserve reproduction inputs.
Local/deferred publication preserves attempts independently of tracking availability.
The [study guide](../../src/research/studies/README.md#generalized-decision-studies)
owns the bounded spot implementation and installed consumers. No runner may replace
a selected implementation with its built-in default. Candidate/runtime binding
is implemented by MR05's local candidate loader; MR04 services and MR12 runtime
telemetry extend these contracts.

The [book registry](../../src/market_data/README.md#book-registry-and-consolidated-bbo)
owns independent venue/listing reconstruction and bounded causal quote history.
Explicit reference equivalence permits consolidated BBO scans with exact tied
sizes and selected/eligible coverage. USD/USDT, native units, source clocks and
quality remain distinct; paper matching selects one native venue quote. MR15
owns measured capacity and MR08+ retain their operating scopes.

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
                                                   target/order/quote intent
                                                              |
                                                              v
                                                     portfolio coordination
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

Cross-process messages use versioned schemas and explicit compatibility rules. In-process library interfaces use typed
methods on cohesive domain, service and adapter classes; orchestrator functions compose their workflows. Classes own
invariants, related behavior and useful dependency lifetimes. Introduce protocols for real interchangeable implementations
or useful test boundaries. A measured native boundary warrants an explicit ABI. Provider objects,
exceptions, timestamps with unknown timezone semantics, and mutable registries stop at adapters.

## Configuration and active workflows

The runtime boundary follows the
[configuration-driven implementation standard](../coding_standards/README.md#generalized-code-and-configuration-driven-activation).
**CURRENT data-plane slice:** `PublicDataJob` and `UniverseSelection` pin four
independent scopes, public trade/reference requests, and named cutoff selections.
Scoped native book requests also retain collection/research admission. Typed
`DataCapability` records admit installed data/reference/calendar profiles. The
[data contracts](../data/contracts.md#versioned-venue-specifications-and-scoped-universes)
own these implemented interfaces. MR05 supplies typed candidate capability
admission; MR07 connects dedicated paper accounts and execution state. Production
deployment and executable authorization remain separate; a scope record grants
no executable authority.
The current authored instrument catalog supplies reference facts and assumptions;
it does not select active assets or strategies. Introduce a small typed file
reader with the first acquisition consumer, then extend its records with reference
strategies supplied by quant development before onboarding. JSON fits the existing
serialization boundary; multiple file formats, a registry service and a
configuration programming language are unnecessary.

Keep these responsibilities distinct, whether the records live in one file or
in explicitly referenced versioned files:

| Configuration record | What it declares | What consumes it |
| --- | --- | --- |
| Implementation definitions | Stable IDs/versions for reviewed installed strategy, pipeline and adapter entry points, with their supported input/output contracts and capabilities. Configuration cannot grant capabilities absent from the implementation. | A configuration resolver validates references/records; the orchestrator loads, checks and constructs the selected implementation. Foundation/config libraries do not import pipelines or providers. |
| Instrument/reference and universe definitions | Canonical IDs, temporal membership/source/venue mappings, applicable increments/multipliers/currencies and market rules, with evidence semantics. | Data, strategy and accounting validation. Catalog membership is not collection, research selection or trading authority. |
| Data jobs and pipeline bindings | Job ID, source, dataset/stream type, pipeline, independently selected universe, historical/live mode, interval, policies and explicit raw/snapshot references. | Acquisition, dataset or live orchestration. The collection universe may exceed a strategy's universe. |
| Strategy definitions | Strategy ID/version, implementation, parameters, target-position/exposure or order/quote output contract, and named data/feature/model requirements. | Strategy-instance resolution and capability validation; formulas remain in strategy code. |
| Strategy instances | Instance ID, strategy reference, selected assets and dependency bindings, supported mode and isolated state namespace. Active instances are selected per workflow. | Research/runtime orchestrators and per-instance trials/results; multiple instances can share compatible immutable inputs. |
| Deployment and authorization, when implemented | Deployment/environment, instance/artifact versions, account/venue/execution connections, independently approved instrument/limit/duration envelope and monitoring/risk bindings. | Runtime orchestration within existing release/operating boundaries. Research config cannot grant executable access. |

Resolve four distinct universes: collection, research, strategy evaluation and
authorized trading. Expanding one does not expand the others or transfer authority.
Retain each resolved membership and its reference versions in the owning run or
deployment manifest; startup and risk both enforce the authorized subset.

The planned typed capability registry covers market data, reference data,
calendars, valuation, account state and execution separately. An adapter declares
its supported products, representations/channels, depth, clocks, freshness,
operations/order types and recovery behavior as applicable. Candidates declare
requirements; composition rejects incompatible bindings before work starts.
Configuration selects reviewed installed implementations rather than granting
unimplemented support. New compatible adapters and strategies extend registration
and fixtures without editing generic decision, risk, OMS or accounting logic.

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

See [canonical economic and temporal model](economic-and-market-data-design.md#canonical-economic-and-temporal-model).

### Identity and lifecycle

See [identity and lifecycle](economic-and-market-data-design.md#identity-and-lifecycle).

### Market events and time

See [market events and time](economic-and-market-data-design.md#market-events-and-time).

## Data source, storage, and lineage design

See [data source, storage, and lineage design](economic-and-market-data-design.md#data-source-storage-and-lineage-design).

### Collection scope and source contracts

See [collection scope and source contracts](economic-and-market-data-design.md#collection-scope-and-source-contracts).

### L2 synchronization and recovery

See [l2 synchronization and recovery](economic-and-market-data-design.md#l2-synchronization-and-recovery).

### Ingestion quality

See [ingestion quality](economic-and-market-data-design.md#ingestion-quality).

## Dataset, feature, label, and experiment contracts

See [dataset, feature, label, and experiment contracts](research-and-simulation-design.md#dataset-feature-label-and-experiment-contracts).

### Feature-store contract

See [feature-store contract](research-and-simulation-design.md#feature-store-contract).

### Research-driven feature lifecycle

See [research-driven feature lifecycle](research-and-simulation-design.md#research-driven-feature-lifecycle).

### Candidate promotion contract

See [candidate promotion contract](research-and-simulation-design.md#candidate-promotion-contract).

## Shared strategy and simulation parity

See [shared strategy and simulation parity](research-and-simulation-design.md#shared-strategy-and-simulation-parity).

### Replay clocks and fill fidelity

See [replay clocks and fill fidelity](research-and-simulation-design.md#replay-clocks-and-fill-fidelity).

## Portfolio, accounting, and position state

See [portfolio, accounting, and position state](portfolio-and-execution-design.md#portfolio-accounting-and-position-state).

## Multi-strategy netting and isolated risk

See [multi-strategy netting and isolated risk](portfolio-and-execution-design.md#multi-strategy-netting-and-isolated-risk).

## OMS and venue adapter design

See [oms and venue adapter design](portfolio-and-execution-design.md#oms-and-venue-adapter-design).

## Asset-class specializations

See [asset-class specializations](portfolio-and-execution-design.md#asset-class-specializations).

## Runtime lanes and deployment

See [runtime lanes and deployment](runtime-and-operations-design.md#runtime-lanes-and-deployment).

## Artifact, schema, and state migration

See [artifact, schema, and state migration](runtime-and-operations-design.md#artifact-schema-and-state-migration).

## Monitoring, recovery, and operational evidence

See [monitoring, recovery, and operational evidence](runtime-and-operations-design.md#monitoring-recovery-and-operational-evidence).

### Feed health and observable loss

See [feed health and observable loss](runtime-and-operations-design.md#feed-health-and-observable-loss).

## Security, entitlements, and organization

See [security, entitlements, and organization](runtime-and-operations-design.md#security-entitlements-and-organization).

## Scaling triggers and technology choices

See [scaling triggers and technology choices](runtime-and-operations-design.md#scaling-triggers-and-technology-choices).

### Storage and performance decisions

See [storage and performance decisions](runtime-and-operations-design.md#storage-and-performance-decisions).

### External simulator reuse

See [external simulator reuse](runtime-and-operations-design.md#external-simulator-reuse).

## Delivery sequence

The single [implementation roadmap](../roadmap/README.md) owns maturity, status,
delivery dependencies and acceptance criteria.
Quant development completes data/research APIs, offline/online feature stores,
candidate/runtime interfaces, portfolio/risk/OMS, both venues' paper execution,
paper deployment, observability, recovery and launch capacity using reference
consumers before QR onboarding. Public-source and paper operating evidence qualify
infrastructure independently of empirical research; private venue qualification
and live activation are KIV. The roadmap owns
the clean-environment handoff gate. People-dependent organizational work remains
separate from technical completion and follows actual staffing.

G1–G5 record foundation, research, paper/shadow, integrated paper operating and
generalized handoff acceptance. They preserve all in-scope paper MR outcomes and
the pre-onboarding gate. MR10 establishes paper drills first and incorporates integrated paper execution/activation
evidence; MR13 uses that paper increment rather than waiting on MR10's final
integrated record. Generalization is demonstrated by fresh installed extensions,
including a non-book input and calendar/product fixture, with source limits intact.

Each slice leaves the previous path usable or provides a tested rollback. It states what is implemented, what remains
planned, which identity is authoritative, and which failure response is safe. The architecture evolves by measured
boundary decisions against acceptance workloads owned by quant development. Required
capabilities cannot be deferred merely because a QR has not supplied a consumer;
optional directory/service choices do not require filling the planned tree.
