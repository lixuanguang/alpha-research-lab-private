# Architecture

This page is the current architecture overview for the Alpha Research Python
workspace. The long-term destination is an institutional-grade monorepo for
multi-asset, multi-strategy research, productionization, and monitoring. The
repository currently implements three domain foundations: [instrument
identity](instrument-identity.md), [venue calendars](venue-calendar.md), and
[financial units](financial-units.md). Data ingestion, point-in-time dataset
construction, simulation, portfolio and risk enforcement, order execution,
deployment, and live monitoring are planned capabilities; their absence is not
hidden by the target model below. See the [platform design](platform-design.md)
for the future module boundaries, lifecycles, runtime lanes, and scaling
triggers.

The [platform roadmap](../roadmap/README.md) selects the next work. The retired
blueprint and package catalog remain in Git history. The first planned delivery
is one reproducible, costed strategy baseline that can later use the same
decision logic in replay and paper operation.

The full monorepo is one source tree with multiple deployables and release
cadences. Shared economic semantics are canonical; strategy variants, asset
mechanics, storage, and computation lanes remain separate until a consumer or
measured workload justifies a shared boundary.

## Current boundary

The first end-to-end delivery sequence is:

```text
future versioned data + explicit availability
    -> reproducible baseline with realistic costs and accounting
    -> shared strategy logic in replay and paper
    -> verified artifact and explicit activation
    -> reconciliation, monitoring, stop, and recovery
```

The three domain foundations exist today; the versioned data source at the left
does not. Keep research code dependent on those contracts, and add a data or
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

Current imports point from financial units to identity and calendar contracts:

```text
financial_units -> instrument_identity
financial_units -> venue_calendar
```

Foundational contracts do not depend on notebooks, research-only approximations,
deployment composition roots, or workstation configuration. Provider details
stay inside adapters. Portfolio construction emits targets; execution turns an
intent into orders only after an independent risk boundary. Cross-process
interfaces will use versioned schemas when such a boundary is introduced.

## Implemented domain contracts

These pages are normative for the implemented libraries and their retained
golden/property evidence.

| Contract | Implemented boundary | Key guarantee |
| --- | --- | --- |
| C01 | [Instrument identity and temporal symbology](instrument-identity.md) | Stable canonical IDs, validity-dated mappings, correction history, and explicit UTC resolution |
| C02 | [Venue calendars and market status](venue-calendar.md) | Versioned bounded snapshots, UTC half-open sessions, DST-safe state, and fail-closed overrides |
| C03 | [Financial units and conventions](financial-units.md) | Dimension-safe exact arithmetic, explicit rounding, and an isolated date-based convention adapter |

The contracts preserve strict external validation, immutable values, explicit
time semantics, and independent hand-calculated or declared goldens. Their
synthetic fixtures are engineering evidence; they do not certify a live venue,
market data source, strategy, deployment, or trading readiness.

## Build, setup, and CI contract

The supported development path uses Python 3.12.14, uv 0.12.7, the repository's
frozen `uv.lock`, and ordinary Git/Make prerequisites. Set up a checkout with:

```sh
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
| `make artifact-supply-chain-check` | Artifact identity, integrity, and release-boundary checks |
| `make architecture-check` | Repository-local Markdown links and heading fragments |
| `make build` and `make wheel-smoke` | Build the runtime wheel and test it outside the checkout |
| `make source-check` | Compose source, policy, security, and correctness checks |
| `make check` | Run `source-check` and installed-wheel smoke validation |

For a targeted change, run only the affected tests in the frozen environment:

```sh
uv run --frozen --no-editable pytest -q <test-paths>
```

Hosted CI runs source validation once on Linux and then wheel smoke on Linux and
macOS. The required check, `Authoritative merged-result full lane`, fails if
source validation or macOS smoke fails. Pull requests also verify the exact
checked-out merge commit and its base/head parents. The installed-wheel check
uses hash-checked dependencies and isolated public runtime imports outside the
checkout, and verifies that governance tooling is not a runtime dependency.
There is one uv-based setup and build path. Bazel, Nix, remote execution,
custom affected-target scheduling, and the former build probes are retired.

## Dependency and release boundaries

The machine-readable policies remain the authority for the checks that consume
them:

- [Dependency admission](dependency-admission.md) and
  [dependency-admission.toml](dependency-admission.toml) bind `pyproject.toml`,
  `uv.lock`, exact artifacts, sources, hashes, platforms, licenses, and
  vulnerability coverage.
- [Artifact supply chain](artifact-supply-chain.md) and
  [artifact-supply-chain.toml](artifact-supply-chain.toml) bind the project
  manifest and lock to an artifact digest, provenance, inventory, and trusted
  verification inputs.

QuantLib 1.43 is still used by C03's convention adapter under a bounded
development/CI admission through **2026-10-04**. Its source-to-wheel binding is
unverified, so artifact release, signing, publication, and consumer verification
remain blocked for the graph. The retained native signatures, source reviews,
compatibility records, and domain goldens stay reachable under the evidence
directories linked by those contracts.

Native attestation verification requires Cosign 3.1.3; the hosted source job
installs it. See the [retained evidence index](../governance/evidence/quantlib-1.43/README.md)
for current paths and historical observations. The development
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

The concise rationale for current constraints lives here. The detailed
wheel-only source-admission record remains as a reference because retained
evidence links to it:

| Decision | Current constraint |
| --- | --- |
| Pydantic boundary models | Strict Pydantic validation is explicit at retained configuration, tooling, serialization, and domain boundaries; it is not a blanket economic-kernel requirement. |
| Instrument identity models | C01 keeps strict immutable models while preserving its public constructors, temporal mappings, and graph invariants. |
| Venue calendar adapter | C02 owns UTC/session semantics and uses `exchange_calendars` only behind a versioned adapter. |
| [Wheel-only source admission](decisions/0012-wheel-only-source-admission.md) | Wheel-only native dependencies require explicit evidence and a release-blocking bootstrap profile. |
| Financial units and conventions | C03 uses exact dimensioned values and an explicit QuantLib date-convention boundary. |

Record decisions about expensive-to-reverse choices with their scope, evidence,
consequences and safe reversal. Keep small decisions here and use a focused design
note when a complex capability needs more detail. Planned choices belong in the
[platform design](platform-design.md) until implementation establishes the actual
boundary. Documentation does not create a package catalog, staffing register,
approval gate or executable roadmap.
