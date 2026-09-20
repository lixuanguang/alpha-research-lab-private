# Platform design: institutional destination

**Status: destination design with current functional ownership.** The source tree
below distinguishes implemented capabilities from planned infrastructure.

The long-term goal is an institutional-grade monorepo for multi-asset, multi-strategy research, productionization, and
monitoring. It should approach the engineering depth expected at a strong proprietary trading or hedge-fund platform
through measured delivery. The founder is the only current operator, so implementation starts with one useful data-to-
report workload. Staffing, independent review, operational separation, and broader organizational controls arrive as
contributors and operators join.

This design records the technical destination and functional source owners without
requiring empty skeletons or prematurely installed infrastructure. Every module, service, store, and native lane below is
**PLANNED** unless marked **CURRENT** or listed as an existing capability in the source tree.
Source-layout completion is not evidence for future capability or operational acceptance.

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
The [infrastructure roadmap](../roadmap/README.md) selects delivery work against
these boundaries. Bare functions serve workflow orchestration; reusable library
behavior belongs to cohesive classes under the
[engineering rule](../coding_standards/README.md#orchestrator-pipelines-and-libraries).
Remaining ownership/enforcement work is tracked in the roadmap.

## Current and planned repository shape

The current implementation uses functional packages directly under `src/`.
Applications and libraries follow the public API and dependency rules below.

Unannotated source capabilities in the following tree are **CURRENT**. Entries
marked FUTURE, CONDITIONAL, PLANNED or OPTIONAL remain absent until their first
working consumer requires them. The extra `market_data/books/` owner
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
    storage/                Verified raw bytes and durable capture journals
    validation/             Quality, lineage, revisions and freshness gates
    datasets/               Assembly, manifests, publication and reopening
    query/                  Point-in-time selection and projections
    replay/                 Historical stepping, cursors and saved replay
    books/                  Shared book state and reconstruction contracts
  research/
    exploration/            EDA and pinned multi-input saved-data selections
    observations/           FUTURE: completed decision observations
    features/               Versioned trailing-price diagnostics; future fitted transforms
    labels/                 Separate forward-return outcomes and availability
    models/                 CONDITIONAL: training, inference and evaluation
    experiments/            Attempts/splits; FUTURE: candidates and economic reports
  strategies/               FUTURE: contexts and decision rules
  simulation/               FUTURE: fills, costs and market mechanics
  accounting/               FUTURE: ledger, valuation, reconciliation
  risk/                     FUTURE: independent decisions and controls
  portfolio/                CONDITIONAL: allocation and netting
  execution/                FUTURE: orders, journals and adapters
  runtime/                  Identity and supervision; future deployment/recovery
  telemetry/                Health/alerts; future runtime and economic monitoring
  configuration/            Typed definitions and explicit selection
  serialization/            Exact domain codecs and strict wire records
  applications/
    acquire/                Existing historical/archive command and workflow
    collect/                Existing capture/probe/replay command and workflow
    publish_dataset/        Existing dataset publish/inspect command
    inspect_fixture/        Existing configured fixture command
    explore/                EDA, research assembly and retained feature/label studies
    train_model/            CONDITIONAL: fit and retain a model attempt
    evaluate_model/         CONDITIONAL: research/delayed-outcome evaluation
    backtest/               FUTURE: one configured economic runner
    paper/                  FUTURE: paper/shadow composition
    live/                   FUTURE: explicitly authorized operation
    deploy/                 FUTURE: concrete artifact verification/installation

configs/                    CURRENT: authored reference data; PLANNED: implementations, bindings and active instances
deploy/                     PLANNED: environment definitions and non-secret config
packages/                   OPTIONAL: separate distributions when a consumer needs them
tools/
  governance/               CURRENT: development checks and artifact boundaries
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

One `alpha-research-lab` distribution installs all nine functional roots using the
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

Cross-process messages use versioned schemas and explicit compatibility rules. In-process library interfaces use typed
methods on cohesive domain, service and adapter classes; orchestrator functions compose their workflows. Classes own
invariants, related behavior and useful dependency lifetimes. Introduce protocols for real interchangeable implementations
or useful test boundaries. A measured native boundary warrants an explicit ABI. Provider objects,
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

Existing normalization, quality checks, atomic publication, bounded queries and
replay support offline inspection without a live-feed dependency. Current source
scope and limitations live in the [data contracts](../data/contracts.md).
Market-event access and feature serving are distinct contracts even when they
share storage.

Historical ingestion and live capture converge on compatible envelopes while
retaining source/receipt/availability differences. Each enabled book consumer
requires tested quality transitions, backpressure and synchronization under its
source contract. Replay exact locally captured inputs and receipt order; a later
vendor archive cannot establish what the local system knew. A decoded depth update
alone does not establish a valid book after a gap. The contracts below govern
source extensions; [scaling decisions](#storage-and-performance-decisions) govern
infrastructure selection.

### Collection scope and source contracts

Source configuration records each enabled combination in the existing source/job configuration:
venue, product, canonical instrument, source/access mode, stream representation,
timestamp units and meaning, sequence/reset guarantees, depth coverage, supported
intervals, backfill limits and permitted use. Record unsupported and unknown
coverage explicitly. Revalidate the adapter's protocol assumptions when admitting
a changed source schema; retain the last working fixture and source version.

| Representation | Required distinction before claiming coverage |
| --- | --- |
| Individual trades | Retain trade identity, exact units, maker/aggressor meaning and correction policy. Aggregated trades cannot silently stand in for every individual trade; specify whether separate trade channels belong to the selected universe. |
| L2 market by price | Snapshot plus ordered changes reconstruct quantities at prices within declared coverage. This does not establish individual-order queue positions or L3 market-by-order history. |
| Tickers | Best bid/offer, last trade and rolling statistics are distinct products. Record the chosen fields/window, update semantics, age and source; one cannot certify another's completeness. |
| Klines | Enumerate the selected venue-supported intervals, timezone/boundaries and whether provisional updates or only closed bars are retained. Preserve close/finality and revision availability. Trade-derived bars have separate lineage and are not relabeled exchange klines. “Every kline” means the declared intervals and retained coverage, not an unspecified promise. |

For execution-sensitive inputs, prefer the direct feed for the actual venue and
product, with its native order adapter. An aggregator remains useful for research
and historical backfill. Any alternative execution input needs explicit freshness,
ordering and provenance acceptance; switching providers cannot silently preserve
the old source identity or measured latency. Endpoint, heartbeat, connection
lifetime and request limits are verified for the selected product during source negotiation,
not copied from another venue or an old example.

### L2 synchronization and recovery

Validate continuity against the source stream's documented contract, including
batched sequence ranges, resets and checksums where supplied. The local raw-record
position and a broker offset are not exchange sequence numbers. A stream without
consecutive IDs needs its documented integrity checks and an honest unknown-
coverage outcome; do not manufacture a universal per-message counter rule.

The reconstruction library consumes saved snapshots, updates and session controls;
the live pipeline owns network requests, rate limits, retries and persistence.
The same reconstruction library serves saved-input replay. Its supported book
carries instrument, session/recovery epoch, snapshot/raw identity, applied source
cursor, known depth coverage, effective availability and quality status.

1. On startup, a proven gap, checksum failure or unusable book, immediately block
   affected book-dependent consumers and enter `recovering`. Preserve raw input
   and the failure boundary. Keep independent healthy bindings usable.
2. Buffer updates within explicit memory/time bounds while requesting a fresh
   snapshot through the venue's supported recovery mechanism. For a REST-based
   adapter, coalesce recovery to one in-flight request per binding, respect the
   shared endpoint budget and retry/backoff policy, and discard responses from
   superseded session epochs. Overflow or exhausted recovery stays unavailable.
3. Reconcile snapshot and buffered updates under the venue-specific bridge rule;
   reject stale/incompatible snapshots and gaps in the retained suffix. Apply a
   complete source message atomically, including all bid/ask changes. Downstream
   decisions must not observe a half-applied message or snapshot.
4. Validate the reconstructed state and coverage, then resume at its actual
   availability time. A repaired book cannot restore observations or decisions
   inside the earlier missing interval. Persist enough snapshot/cursor/epoch
   identity for deterministic reconstruction after restart.

For Binance spot, the documented procedure buffers depth events before obtaining
a REST snapshot, removes updates covered by the snapshot, reconciles the first
remaining range and restarts if a subsequent `U` exceeds the local update ID plus
one. Updates set absolute quantities; zero quantity deletes a level. Snapshot
depth is limited, so untouched levels outside it remain unknown. Use the current
documented bridge rule and distinguish it from futures continuity fields.
[Official spot procedure](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md#how-to-manage-a-local-order-book-correctly)
(reviewed 2026-09-15; recheck during adapter implementation).

For a newly supported live book, combine a hand-reconstructed saved trace with
one permitted capture. Offline reconstruction can use verified saved inputs with
declared quality; synthetic traces prove the algorithm only. Exercise a gap during
snapshot fetch, stale-session response, duplicate/overlapping updates, deletion,
malformed level, interrupted message, rate-limited recovery and buffer overflow.
Resume must reproduce the same book and quality boundaries as uninterrupted replay.
Select analogous cases for another venue only where its protocol differs.

### Ingestion quality

Historical partition and continuous-capture checks share schema/unit and
source policies. Reject nonfinite or nonpositive trade prices and invalid trade
quantities under that representation's contract; zero L2 update quantity remains
a deletion. Preserve rejected raw records, reasons and binding-scoped counts.
An invalid required update invalidates dependent book state. Do not silently
drop an anomaly, forward-fill it or mark the stream healthy after reconnect.
Keep the existing frozen `msgspec.Struct` and explicit invariant requirements;
this design does not migrate market events to Pydantic.

## Dataset, feature, label, and experiment contracts

**Current saved research access:** `market_data.datasets.SnapshotCatalog` discovers
bounded manifest metadata; `research.exploration.ResearchSelection` pins named
trade/book inputs at one cutoff. `ResearchReader` assembles separate typed results
through existing snapshot admission and family-specific queries; the existing
`applications.explore.inspect_eda` composes it. Values retain source identities,
units, controls, membership and coverage limits. Book selection uses exact receipt
clocks and cannot invent availability for archives. No implicit join, filling or
currency conversion is performed. The
[public contract](../../src/market_data/README.md#discover-and-reopen-research-selections)
owns the supported fields, resource bounds, missingness and refusal behavior.


Planned dataset, feature, label, signal, model, cost, risk, portfolio, and candidate records carry identity, version,
inputs, units, availability, owner, and failure policy. They are small records around real consumers, not a global
registry that every exploratory file must enter.

Features are deterministic functions of PIT datasets. Metadata names every input, transform version, availability delay,
units, missing policy, range, and training fit interval. Labels name observation horizon, execution delay, price
convention, overlap, and missing policy. Scaling, neutralization, imputation, selection, and hyperparameters fit only on
data available in the applicable training interval.

**Current versioned diagnostic:** `research.features.TrailingReturn` computes exact
observed-price window returns; `research.labels.ForwardReturn` separately computes
delayed outcomes against frozen earlier endpoints. `FeatureStudy` reuses pinned
trade selection and the existing retained exploration application. Every decision
has its own knowledge cutoff; labels cannot enter earlier feature values. The
[public contract](../../src/research/features/README.md) defines the query business
clock, cadence, warm-up, missing/stale policy, exact rational units, input lineage
and bounded execution. This does not implement the economic baseline's completed
observations, runtime features, fitted models or a book/macro formula.

An experiment identity includes source and dataset manifests, code/artifact revision, resolved non-secret configuration,
environment/toolchain identity, component versions, split rules, and random seeds. Wall-clock creation time is metadata,
not identity. Failed or rejected trials that influence selection remain append-only, and the final holdout is frozen
before evaluation.

**Current attempt/split core:** `research.experiments` separates deterministic
input identities from execution IDs, admits only then-available training rows,
and retains explicit purge/embargo and no-fit policies. A local single-writer
store preserves incomplete, failed, rejected and abandoned attempts; atomic
completion contains the result bytes. Family holdouts are frozen and consumption
is retained before access. `applications.explore.inspect_experiment` composes
this core with the existing pinned selection reader for unfitted inspections.
The [public contract](../../src/research/experiments/README.md) owns clocks,
identity, retention, concurrency, recovery and supported evaluation boundaries.
Fitted preprocessing/model consumers and candidate/economic reports remain planned.

Research reports state the economic mechanism, falsifiable hypothesis, target, sign, horizon, universe, rebalance,
benchmark, expected turnover/liquidity, cost and capacity assumptions, metrics, rejection criteria, and limitations.
Once an exploratory result influences a candidate decision, it receives durable identity and provenance.

### Research-driven feature lifecycle

Introduce a feature for a concrete research consumer: a diagnostic, factor/signal
study, deterministic rule or model. A selected model is not required. This expands
the earlier model-only trigger while retaining its ban on a mandatory starter
catalog and unused abstractions. The QR owns the formula and research choices;
the platform owns execution, alignment, lineage and applicable state contracts.
Research dataset assembly supplies explicit inputs over the existing query
contracts. Fitted preprocessing is added with its first learned consumer;
incremental execution only with a candidate that needs it. Label generation and
alignment remain separate from prediction inputs. Shared attempt and temporal
split records now support retained exploration before a backtest or model exists.
These contracts serve model-free studies and future learned candidates alike.

Reusable transforms belong to `research/features/`; labels to `research/labels/`;
trainers/inference to `research/models/`; split/attempt/candidate records to
`research/experiments/`. The attempt/split owner now serves exploration; the
model and other future owners appear only with working consumers.
Notebooks may explore local variants; formal retained and promoted results call
the accepted versioned implementations. A candidate binds its inputs, definitions,
parameters, split/fit identity and fitted state where applicable. Rejected
candidates remain research evidence without becoming active runtime components.

Training and runtime applications compose those same library operations through
admitted input adapters. They do not import one another's workflows, copy formulas
or refit state implicitly. An incremental implementation must preserve historical
semantics under ordering, late data, warm-up and recovery; validate numerical
agreement under a declared contract rather than assuming identical algorithms.
A scheduled batch candidate need not acquire incremental machinery. Changed
semantics require new versions and affected validation.

### Candidate promotion contract

Status: **planned**. A candidate manifest belongs in `research/experiments/` with
its first strategy consumer. Learned fields are added with model artifacts and
remain inapplicable for a rule-only candidate. Runtime binding consumes this same
contract. Research can construct and validate a candidate without a paper runtime,
venue connection or trading credentials. These are small versioned artifacts,
not a registry service.

| Candidate content | Meaning at research/runtime handoff |
| --- | --- |
| Identity and reproduction | Candidate/component versions, code/environment identity, retrievable artifacts and accepted trial/report references; training input/split provenance remains retained |
| Runtime input requirements | Named data bindings, schema/units, supported instrument/product, cadence, knowledge/availability rules, coverage/freshness and missingness policy; runtime bindings may differ from historical snapshots but must satisfy the same contract |
| Features and fitted preprocessing | Definitions/parameters, input order/schema, accepted fitted-state bytes and fit cutoff; runtime does not refit implicitly |
| Optional model | Serialization/version, expected feature signature, output meaning and numerical contract, training/label cutoff and permitted activation time |
| Decision policy | Versioned prediction/signal-to-target implementation and parameters; rules need no model, and unsupported output contracts fail |
| State and qualification | Warm-up/checkpoint/reset compatibility, batch/incremental requirements, retained parity/evaluation evidence and limitations |

A model is not a trading strategy. The QR's decision policy turns then-available
predictions/signals into the supported target contract. Shared applications apply
independent risk, simulation or execution and accounting outside that policy.
Walk-forward evaluation chooses only artifacts that could have been fitted by the
historical decision, including label availability and declared training/deployment
timing. Never use a final full-history fit for earlier decisions.

Promotion loads the accepted components and verifies compatible inputs/state;
matched inputs reproduce features, predictions and targets under their declared
contracts. Artifact verification precedes deployment; runtime binding and
paper/live qualification preserve the accepted candidate. Candidate evidence grants neither release
admission nor trading authority. Retraining produces a new version and repeats
affected qualification. Rollback compatibility is explicit and cannot undo fills.

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

Replay and research consume one [event-stepping contract](../data/point-in-time-semantics.md#chronological-ordering-and-event-stepping),
owned by chronological replay. Pipelines compose operations and retain state; the iterator and
scheduled-step library enforce source admission, expiry, pending fill, decision
and valuation order. Use fixed source/stream precedence and stable logical source
order for meaningful ties. Hashes retain provenance without allowing future byte
changes to reorder earlier economics. The planned synthetic economic slice first exercises this contract through
observations, decisions and a reconciled synthetic ledger, then the configured backtest extends the
same path with saved-input/trial composition.

### Replay clocks and fill fidelity

Preserve exchange time, local receipt, ingestion and effective knowledge as
distinct facts under the [point-in-time contract](../data/point-in-time-semantics.md).
Retain original precision and source order. Introduce versioned integer timestamp
units only when a supported consumer needs precision beyond the current boundary;
never reinterpret existing microsecond values. Negative apparent latency is a
clock-quality observation. A correction requires an explicit versioned model
and calibration availability, retaining original clocks; a future extreme offset
must not rewrite an earlier decision's information set.

An order-book simulation distinguishes exchange-side matching state from the
strategy's then-known state. Feed delay, local processing, order entry and order
response delay have separate meanings. A fill can occur before its response is
visible locally; a cancel request is not a successful cancel. Retain send,
exchange/acknowledgement/fill and response identities/times where actually
observed, with absent clocks explicit. Constant delays are declared scenarios;
empirical latency models need source/environment identity, calibration windows,
coverage and sensitivity checks. Archive download time cannot measure historical
feed latency. Use recorded or paper/sandbox evidence first; the existing authority
rules continue to govern executable activity.

Extend replay, strategy, fill, cost and order contracts for a selected quoting consumer only after its book,
order lifecycle and product economics exist. Introduce pure order-lifecycle contracts
with an offline simulator when needed; runtime binding remains a prerequisite
for the paper runtime, not for those pure contracts. Saved-book research does not
require a deployed collector. Define queue assumptions, maker/taker
fees, supported order types, post-only rejection, partial fills and cancel/replace
priority. For L2, position in queue is modeled; L3 requires actual order identities
and lifecycle data. Trade depletion and its matching depth decrease must not
advance the modeled queue twice. Deterministic scenarios exercise the selected
model and an alternative plausible queue/latency assumption; they are not proof
of exchange fidelity.

Historical replay does not change other participants' recorded orders when our
simulated order trades. State the no-impact and size/liquidity envelope, and reject
or visibly bound unsupported liquidity-taking/capacity claims. A partial-fill
option alone does not remove this limitation. Keep P1's declared trade-price
model intact; book-based research needs a separate versioned experiment.

The roadmap owns [capture and paper comparison acceptance](../roadmap/README.md#operations-and-paper-qualification).

## Portfolio, accounting, and position state

Portfolio construction consumes forecasts, current positions, risk budgets, costs, liquidity, financing, and
constraints. It produces dimensioned desired exposures or quantities with a validity interval and fallback. It never
places orders. An infeasible or stale input takes a deterministic conservative path.

The planned accounting boundary owns positions, lots or contract quantities, cash by currency, accrued amounts,
margin/collateral, financing, fees, dividends, coupons, funding, variation margin, exercise, assignment, delivery, and
settlement events for supported asset classes. Money and quantities use the current exact financial-unit contract;
weight-only state cannot replace an economic position.
The planned P1 [arithmetic contract](financial-units.md#planned-research-and-accounting-arithmetic)
keeps cash/notional/marks on the exact C03 grid and uses dimensioned rational
basis/P&L attribution where proportional division is nonterminating. Exact
returns use reduced fractions; display/model approximation has a separate
declared representation. P1 NAV and gross-to-net reconciliation are exact.

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

For the first dedicated single-instance paper account, qualify durable state,
pending reservations, hard limits and base account reconciliation. Shared-account
netting/allocation and its reconciliation become mandatory before a second
instance shares the account, not before the first base reconciliation.

Initial strategies are trusted founder-authored code. Logical separation,
immutable limits, per-instance state and final risk enforcement outside strategy
logic protect supported interactions and failures. They do not isolate hostile
code. Before admitting adversarial or untrusted strategies, require a privilege
boundary with controlled communication and credentials/limits outside that
code's authority. A separate class or same-privilege process does not establish
this stronger guarantee; no sandbox platform is a P1 prerequisite.

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
Its artifact verification consumer and admitted deployment graph precede the first actual deployment,
including early capture and paper/shadow. Bounded activation later binds executable authority
to the verified artifact; it cannot be the first installer for an earlier milestone.

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
invalid counts and persistence failures for acquisition; advancing ingestion,
freshness, queues and recovery for capture; resource/failure visibility for queries;
execution, attribution and risk state for operating strategies. A live heartbeat with no advancing work must
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

### Feed health and observable loss

Measure receipt-to-durable delay, advancing source/persistence cursors, interarrival
gaps, queue age/bytes, invalid/duplicate counts, reconnects and recovery duration
per supported binding. Distinguish expected quiet feeds from stalled progress
using the stream contract. Heartbeats alone do not establish fresh data. Venue
quality is an observed property of the selected feed and period, not a permanent
ranking such as “Binance is always stable.”

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

### Storage and performance decisions

Durable capture decouples receipt from downstream work through replayable journals
and bounded queues. A durable local segment log is the first candidate. Evaluate
Kafka when independent consumers, retention/replay, cross-process recovery or
burst isolation justify a service. Partition by a declared ordering scope and
retain original event identity; acknowledgement and consumer checkpoint rules
must compose with durable sink writes. Broker guarantees do not by themselves
make an external database sink exactly once.
[Kafka delivery semantics](https://kafka.apache.org/design/).

Query workload evaluation compares the reference reader with a bounded columnar candidate; include
ClickHouse when the depth-history or concurrent analytics workload warrants it.
Decide sorting/partition keys, batching, retention and snapshot-plus-delta layout
from the named query. Keep all economically relevant revisions and control events
available to as-of selection; a latest-value table cannot replace replay history.
Columnar storage performance depends on layout and accessed data, so choosing the
engine alone is not acceptance.
[ClickHouse MergeTree design](https://github.com/ClickHouse/ClickHouse/blob/master/docs/en/engines/table-engines/mergetree-family/mergetree.md).

Use the proposed **7M+ source messages/day and sub-500ms historical depth query**
as a candidate workload to scope in a measured scaling study, not an achieved result or a reason
to mandate both services. Define total versus per-venue volume, messages versus
normalized rows, burst distribution, retention horizon, depth levels, query/result
size, concurrency, hardware, warm/cold cache and latency percentile before a run.
Measure sustained/burst ingestion, durable lag, memory/disk, queue growth, recovery,
rows/bytes scanned and p50/p95/p99 query latency. Retain exact-value/revision parity
and the operational cost. A bounded representative experiment decides whether to
adopt, defer or revise the target; no service deployment is required for P1.

### External simulator reuse

Use hftbacktest first as a source of small independent traces and, when a book
consumer exists, a candidate differential simulator. Its
[Python package metadata](https://github.com/nkaz001/hftbacktest/blob/5f3ec40b2afb764e0fea112f941ed85523ef4e88/py-hftbacktest/pyproject.toml)
adds a Rust build and NumPy/Numba dependencies; compatibility with this repository's
pinned Python 3.14 and dependency policy has not been established. Do not import
its stack, sample numeric types, timestamp repairs or connector code wholesale.
A reuse experiment names the revision and supported mechanics, checks exact
unit/clock conversion, compares matched traces and reports disagreements before
dependency admission. Optimize representation, prefetch or native loops only
after a representative workload measurement, preserving the reference semantics.


## Delivery sequence

The single [implementation roadmap](../roadmap/README.md) owns maturity, status,
delivery dependencies and acceptance criteria.
Validated historical data leads to EDA/replay and independent research/backtesting
while reliable live capture advances alongside them. Features/models are added
with their consumers; paper/shadow precedes controlled live operation. The people-triggered organizational workstream is last in
speculative priority. Technical scaling does not require hiring first, and onboarding does not wait for platform scale.

Each slice leaves the previous path usable or provides a tested rollback. It states what is implemented, what remains
planned, which identity is authoritative, and which failure response is safe. The architecture evolves by measured
boundary decisions rather than by filling the planned tree in advance.
