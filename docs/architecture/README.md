# Architecture

This page is the current architecture overview for the Alpha Research Python
workspace. The long-term destination is an institutional-grade monorepo for
multi-asset, multi-strategy research, productionization, and monitoring. The
repository currently implements three domain foundations: [instrument
identity](instrument-identity.md), [venue calendars](venue-calendar.md), and
[financial units](financial-units.md), plus exact serialization, provenance,
reference-catalog, and bounded Binance event/decoder foundations. Data
acquisition, point-in-time dataset construction, simulation, portfolio and risk
enforcement, order execution, deployment, and live monitoring are planned
capabilities; their absence is not hidden by the target model below. See the
[platform design](platform-design.md) for the future module boundaries,
lifecycles, runtime lanes, and scaling triggers.

The locked `msgspec` dependency supports the exact serialization boundary for
financial values and the bounded canonical Binance event records in this
candidate. Those records use frozen `msgspec.Struct` values with cached strict
typed codecs. Quote, order-intent, execution, configuration, report, acquisition,
and replay consumers remain planned; the established C01, C02 and C03 foundation
contracts remain preserved.

The [platform roadmap](../roadmap/README.md) selects the next work. The retired
blueprint and package catalog remain in Git history. MR 01–02 first deliver a
configured installed fixture consumer, followed by versioned data and reference
query/replay. E1 then starts the economic path toward the reproducible costed
baseline; the same strategy logic later serves paper operation.

The full monorepo is one source tree with multiple deployables and release
cadences. Shared economic semantics are canonical; strategy variants, asset
mechanics, storage, and computation lanes remain separate until a consumer or
measured workload justifies a shared boundary.

## Current boundary

The planned research-to-operation path is:

```text
configured fixture -> versioned data + explicit availability
    -> reference query/replay + E1 synthetic economics
    -> reproducible baseline with declared cost assumptions and exact accounting
    -> reusable research + live inputs + R1 verified artifact
    -> paper/shadow with risk, reconciliation, monitoring, stop and recovery
    -> explicit bounded live activation using those qualified controls
```

The [milestone dependency graph](../roadmap/capability-milestones.md#completion-and-dependency-model)
owns detailed order. R1 precedes any actual deployment, including a collector
pulled forward for a concrete data need. Operational controls accompany their
runtime and must pass before activation.

The domain, provenance, reference and decoding foundations exist today; the
configured workflow and versioned dataset above do not. Keep research code dependent on those
contracts, and add a data or
broker adapter only when an actual workload needs it. Do not introduce a service
mesh, event bus, schema platform, or distributed build system without a measured
requirement.

## Principles and dependency direction

The following rules govern new code and documentation:

1. Preserve point-in-time causality. Event, receipt, ingestion, knowledge, and
   valid time are distinct; a decision consumes only information known by its
   decision time.
2. Keep one decision implementation per strategy. Replay, paper, shadow, canary,
   and live modes reuse its logic with injected adapters; distinct strategies
   may have distinct kernels and state.
3. Keep units, identifiers, timestamps, source revisions, and artifact identity
   explicit. Mutable tags and workstation state are not release identity.
4. Keep risk and activation independent from strategy decisions. A strategy
   cannot grant itself credentials, capital, limits, or trading authority.
5. Make invalid, stale, unsupported, incompatible, and unauthorized state fail
   closed or pause visibly. Do not silently coerce it into a convenient value.
6. Prefer deterministic replay. Ordering, corrections, clocks, random streams,
   state, and failure behavior are inputs to a reproducible result.
7. Put providers behind narrow adapters. Vendor symbols, native objects,
   exceptions, mutable registries, and host-local time do not cross domain
   boundaries.
8. Choose technology from an actual workload and evidence. A replacement must
   preserve the relevant numerical, temporal, integrity, security, and recovery
   behavior before the existing boundary is retired.

Current and selected foundation-boundary imports are:

```text
financial_units -> instrument_identity
financial_units -> venue_calendar
serialization -> financial_units, instrument_identity, msgspec
core.events -> msgspec
reference_data -> financial_units, instrument_identity, serialization
data.events -> core.events, instrument_identity, msgspec
data.decoders -> core.events, msgspec
data.providers.tardis.decoder -> data.decoders, data.events
data.venues.binance.events -> data.events
data.venues.binance.codecs -> data.events, data.venues.binance.events, serialization, msgspec
data.venues.binance.payloads -> data.decoders, data.events, data.venues.binance.codecs, data.venues.binance.events, instrument_identity, reference_data
```

Foundational contracts do not depend on notebooks, research-only approximations,
deployment composition roots, or workstation configuration. Provider details
stay inside adapters: Tardis framing owns capture and blank-line behavior, while
the Binance venue decoder owns combined-stream `stream`/`data` payload
interpretation. Portfolio construction emits targets; execution turns an
intent into orders only after an independent risk boundary. Cross-process
interfaces will use versioned schemas when such a boundary is introduced.

The graph describes the current candidate after
[C0](../roadmap/p1-implementation-roadmap.md#existing-abstractions-to-retain-or-retire).
Callers construct the framing and payload decoders directly. The planned dataset
pipeline will own that composition; no pipeline is implemented yet.

## Implemented domain contracts

These pages are normative for the implemented libraries and their retained
golden/property evidence.

| Contract | Implemented boundary | Key guarantee |
| --- | --- | --- |
| C01 | [Instrument identity and temporal symbology](instrument-identity.md) | Stable canonical IDs, validity-dated mappings, correction history, and explicit UTC resolution |
| C02 | [Venue calendars and market status](venue-calendar.md) | Versioned bounded snapshots, UTC half-open sessions, DST-safe state, and fail-closed overrides |
| C03 | [Financial units and conventions](financial-units.md) | Dimension-safe exact arithmetic, explicit rounding, and an isolated date-based convention adapter |
| Data foundation | [Market-data contracts](../data/contracts.md) | Exact authored instrument metadata, source provenance, immutable Binance event records, and strict capture decoding; acquisition remains planned |

The contracts preserve strict external validation, immutable values, explicit
time semantics, and independent hand-calculated or declared goldens. Their
synthetic fixtures are engineering evidence; they do not certify a live venue,
market data source, strategy, deployment, or trading readiness.

## Build, setup, and CI contract

The supported development path uses standard GIL-enabled CPython 3.14.7 on
macOS arm64 and Linux x86_64, uv 0.12.7, the repository's frozen `uv.lock`, and
ordinary Git/Make prerequisites. Set up a checkout with:

```sh
uv python install
uv sync --frozen
```

The root [Makefile](../../Makefile) is the command reference. The focused
commands are:

| Command | Purpose |
| --- | --- |
| `make format-check` and `make lint` | Ruff formatting and lint checks |
| `make typecheck` | Strict mypy plus retained native stub checks |
| `make test` | Correctness tests with performance cases excluded |
| `make engineering-standards-check` | Required typing, import, and Google-style docstring rules |
| `make dependency-admission-check` and `make dependency-audit` | Frozen lock/source checks and vulnerability coverage |
| `uv run --frozen alpha-governance-artifacts release-check` | Fail-closed release-readiness diagnostic; no artifact lifecycle is implemented |
| `make architecture-check` | Repository-local links and heading fragments in `docs/**/*.md`; explicitly include component READMEs when changed |
| `make build` and `make wheel-smoke` | Build the runtime wheel and test it outside the checkout |
| `make source-check` | Compose source, policy, security, and correctness checks |
| `make check` | Run `source-check` and installed-wheel smoke validation |

For a targeted change, run only the affected tests in the frozen environment:

```sh
uv run --frozen --no-editable pytest -q <test-paths>
```

Hosted CI asserts the pinned interpreter, standard GIL build and architecture in
each job. It runs source validation once on Linux and then wheel smoke on Linux
and macOS arm64. The required check, `Authoritative merged-result full lane`, fails if
source validation or macOS smoke fails. Pull requests also verify the exact
checked-out merge commit and its base/head parents. The installed-wheel check
uses hash-checked dependencies and isolated public runtime imports outside the
checkout, and verifies that governance tooling is not a runtime dependency.
There is one uv-based setup and build path. Bazel, Nix, remote execution,
custom affected-target scheduling, and the former build probes are retired.

## Dependency and release boundaries

The retained development checks and release boundary are:

- [Dependency admission](dependency-admission.md) and
  [dependency-admission.toml](dependency-admission.toml) bind `pyproject.toml`,
  `uv.lock`, exact artifacts, sources, hashes, platforms, licenses, and
  vulnerability coverage.
- [Artifact supply chain](artifact-supply-chain.md) rejects release use until
  dependency admission is resolved and a concrete trusted release consumer is
  implemented. The unused general bundle, signing and publication framework
  is retired. Future consumers must bind the artifact digest to its source,
  lock, provenance and trusted origin before use.

QuantLib 1.43 is still used by C03's convention adapter under a bounded
development/CI admission through **2026-10-04**. Its source-to-wheel binding is
unverified, so artifact release, signing, publication, and consumer verification
remain blocked for the graph. The small
[wheel-only allowance](dependency-admission.md#wheel-only-development-allowance)
records this limit. Native adapter conformance tests and domain goldens remain;
CI no longer verifies publication signatures. The development
[workflow](../governance/workflow.md) and [runbook](../governance/operations.md)
own release and activation decisions.

## Release and operation boundary

When a deployable strategy exists, a release record should identify the source
commit, artifact digest, dependency lock, configuration, model/data references,
limits, environment, and rollback artifact. Building and deploying an artifact
does not activate trading. Activation must be a separate explicit decision with
bounded account, venue, exposure, notional, loss, schedule, and credential
scope. The process must reconcile state after startup or disconnect and provide
a tested stop/cancel path.

Monitoring should expose stale data, missing heartbeats, reject/error bursts,
position or cash mismatches, and limit breaches, with retained orders, fills,
state, and alert-delivery evidence. These are design requirements for the first
real operating target; this repository does not yet implement them.

## Current architecture decisions

The concise rationale for current constraints lives here. The
[dependency admission guide](dependency-admission.md) owns the native exception,
review triggers and reversal requirements:

| Decision | Current constraint |
| --- | --- |
| Serialization boundary | Financial values and bounded canonical Binance event records use the [engineering serialization requirements](../coding_standards/README.md#classes-records-errors-and-resources); later configuration, reports, quote/order-intent and execution records remain planned. Pydantic remains available for cold administration and the C01/C02/C03 foundation APIs. |
| Instrument identity models | C01 keeps strict immutable models while preserving its public constructors, temporal mappings, and graph invariants. |
| Venue calendar adapter | C02 owns UTC/session semantics and uses `exchange_calendars` only behind a versioned adapter. |
| [Wheel-only development allowance](dependency-admission.md#wheel-only-development-allowance) | An exact native package may receive an expiring development/CI allowance; its unverified source binding blocks release. |
| Financial units and conventions | C03 uses exact dimensioned values and an explicit QuantLib date-convention boundary. |

Record decisions about expensive-to-reverse choices with their scope, evidence,
consequences and safe reversal. Keep small decisions here and use a focused design
note when a complex capability needs more detail. Planned choices belong in the
[platform design](platform-design.md) until implementation establishes the actual
boundary. Documentation does not create a package catalog, staffing register,
approval gate or executable roadmap.
