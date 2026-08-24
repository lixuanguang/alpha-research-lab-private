# Monorepo Architecture

## Purpose

This document defines the target structure and dependency model for the alpha
research monorepo. It describes how research, simulation, shadow operation,
deployment, and monitoring fit together while allowing Python, Rust, and C/C++
targets to evolve independently.

Detailed domain contracts are in [contracts.md](contracts.md). Testing,
operations, security, and promotion controls are in
[operations.md](operations.md). Delivery order is defined by the
[implementation roadmap](../roadmap/README.md).

## Architectural basis and limits

This is a proposed architecture for this repository, not a reconstruction of a
trading firm's proprietary systems. Public material supports several patterns:

- Jane Street has described a large OCaml-and-Python monorepo, dedicated build
  tooling, Dune-based builds, and reproducible Python environments.
- Hudson River Trading has described majority-monorepo development, C++/Python
  research and trading systems, distributed cached builds and tests, and
  large-scale Prometheus monitoring.
- Citadel Securities publicly describes trading systems, research and simulation,
  core platforms, and SRE, but does not publicly establish a firm-wide monorepo or
  build tool.

The choices below are recommendations derived from those public signals and
general systems practice. They must not be presented as claims that a named firm
uses the same repository layout or tools.

## Architectural principles

1. **Correctness before scale.** Start with deterministic, single-process paths
   and small golden datasets. Add distribution or native optimization only after
   measurement establishes a requirement.
2. **Point-in-time behavior is enforced.** Availability semantics belong in data
   and evaluation contracts, not researcher convention.
3. **Research/live parity is tested.** Prefer one authoritative implementation.
   When languages differ, require versioned conformance tests and reconciliation.
4. **Domain first, language second.** Ownership follows instruments, data, risk,
   strategy, execution, and operations rather than global language silos.
5. **The monorepo is a dependency graph, not one release.** Targets have explicit
   dependencies, owners, artifacts, and deployment cadences.
6. **Evidence is an artifact.** Data audits, experiments, models, reports,
   deployments, and operational decisions carry immutable provenance.
7. **Failure is explicit.** Missing or stale data, invalid risk, infeasibility,
   partial execution, and degradation never select an optimistic fallback silently.

## Logical architecture

```text
                               shared contracts
                                      |
          +---------------------------+---------------------------+
          |                           |                           |
    data entrypoint            research entrypoint          shadow entrypoint
          |                           |                           |
   bronze -> silver          point-in-time datasets          live/replay events
          |                  features and models                    |
   quality + lineage         risk and portfolio               paper execution
          |                  backtests and reports             reconciliation
          +---------------------------+---------------------------+
                                      |
                      artifacts, governance, telemetry
```

These are logical composition roots, not necessarily network services. The
initial implementation can be a Python modular application with multiple command
entrypoints. A split into processes or services requires a measured isolation,
reliability, scaling, or latency need.

### Data entrypoint

The data path discovers or receives source records, records source identity and
retrieval metadata, writes immutable bronze objects, normalizes canonical events,
runs quality checks, publishes silver partitions atomically, and updates lineage.
Batch, scheduled, and streaming ingestion are orchestration modes around the same
connector and normalizer contracts.

### Research entrypoint

The research path resolves an immutable dataset, constructs a point-in-time
universe, computes registered features and labels, creates rolling splits, fits
training-only transformations, produces forecasts and positions, simulates
orders/fills/accounting, and records governed trials and evidence artifacts.

### Shadow entrypoint

The shadow path consumes live or replayed canonical events, loads an immutable
candidate and configuration, uses authoritative or conformant strategy/risk logic,
sends intents to a paper gateway, maintains the ledger, applies kill switches,
reconciles against research, and emits operational evidence.

## Runtime modes

| Mode | Data | Clock | Execution | Purpose |
| --- | --- | --- | --- | --- |
| Unit/golden | Tiny fixture | Deterministic | Fake | Exact correctness |
| Historical research | Immutable partitions | Simulated | Vector or event model | Research |
| Historical replay | Canonical events | Replay | Paper adapter | Production-path validation |
| Shadow | Live canonical events | Wall clock | Paper adapter | Operational evidence |
| Paper | Live canonical events | Wall clock | Controlled paper venue | Execution exercise |
| Live | Live canonical events | Wall clock | Authorized venue | Separately approved and out of scope |

Every run records its mode. Mode-dependent behavior belongs in adapters and
configuration, not hidden branches inside economic logic.

## Execution planes

- **Research plane:** interactive and batch work, historical data, experiment
  scheduling, and elastic CPU/GPU compute. Containers or a cluster scheduler may
  be appropriate after measured demand exists.
- **Trading plane:** replay, shadow, paper, and any future live processes.
  Latency-sensitive targets may require native binaries, controlled hosts,
  CPU/NUMA policy, and restricted background work.
- **Control plane:** artifact promotion, configuration, inventory, discovery,
  secrets, dashboards, alerts, audit history, and out-of-band stop controls.

The planes share schemas, provenance, ownership, and telemetry conventions. They
need not share a scheduler, packaging format, language, or release cadence.

## Component boundaries

- Connectors may depend on vendor SDKs; domain, research, risk, and portfolio
  targets may not.
- Canonical types may not import storage, network, dataframe, optimizer, or web
  frameworks.
- Features depend on canonical datasets and declared market state, not connectors
  or future partitions.
- Models consume registered features and labels; they do not query vendors.
- Portfolio targets consume forecasts, risk, costs, positions, and constraints;
  they do not place venue orders.
- Execution adapters translate order intent into venue requests and execution
  reports; they do not decide strategy targets.
- Accounting is authoritative for positions, cash, cashflows, and realized P&L.
- Reports consume registered artifacts rather than recomputing research logic.
- Production targets may not depend on notebooks, ad hoc experiments, or
  research-only approximations.
- Application entrypoints compose targets; reusable business logic does not live
  in `apps/`.

The intended dependency direction is:

```text
schemas
  -> foundational libraries
  -> domain libraries and strategy cores
  -> data, simulation, and venue adapters
  -> application entrypoints

platform and observability consume declared interfaces and artifact metadata;
they do not own strategy economics.
```

Circular target dependencies are prohibited. Target visibility and dependency
checks enforce the direction.

## Target repository layout

```text
build_defs/                  # tracked build rules, toolchains, CI helpers
third_party/                 # locks, patches, licenses
schemas/                     # market, order, risk, and telemetry contracts
libs/
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
  fixtures/                  # tiny reviewable fixtures only
research/
  sdk/
  features/
  models/
  experiments/
  notebooks/                 # interfaces, not sole production logic
strategies/
  <asset-class>/<strategy>/
    core/
    simulation/
    live_adapter/
    config/
    monitoring/
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
governance/
reporting/
apps/                        # thin composition roots
tests/                       # cross-target contract/integration/golden suites
docs/
```

This is a target topology, not a request to create empty directories. The first
Python slice may stay under `src/alpha_research/` until a real second deployable or
language target exists. Unit tests stay with their owning targets; top-level tests
exercise cross-target contracts.

When one component needs multiple languages, keep them together:

```text
libs/orderbook/
  api/                       # schema and compatibility tests
  python/
  rust/
  cpp/
  tests/                     # cross-language golden/differential tests
```

Bulk data, experiment outputs, compiler outputs, deployment artifacts, and secrets
do not belong in Git. Git contains their schemas, manifests, build definitions,
synthetic fixtures, and retention policies.

## Build and polyglot interoperability

- The repository exposes one root interface for build, test, lint, and formatting.
- Every target declares direct dependencies, visibility, owners, runtime platform,
  toolchain, and generated inputs.
- Python interpreters/packages, Rust toolchains/crates, C/C++ compilers/libraries,
  code generators, and system dependencies are pinned.
- A hermetic multi-language graph such as Bazel, Buck2, Pants, or an equivalent
  internal system is adopted only when native or multiple deployable targets make
  it necessary. The choice requires an architecture decision record.
- Remote caching and execution follow hermeticity and cache-correctness evidence;
  they are not Phase 0 prerequisites.
- Cross-process APIs use versioned schemas. Control-plane RPC and a latency-sensitive
  data plane may use different encodings while sharing semantic conformance tests.
- In-process Rust/C++ integration uses a narrow C ABI or reviewed interop layer.
  Ownership, allocator, lifetime, layout, errors, unwinding, and threading are
  explicit.
- Python/native APIs are coarse or batch-oriented and account for conversion,
  copying, buffer lifetime, and GIL costs.

## Artifact and release model

Each deployable target creates an immutable artifact whose provenance includes:

- Source revision and target.
- Toolchain and dependency digests.
- Schema and generated-code versions.
- Platform, CPU requirements, feature set, and build mode.
- Artifact digest and symbol/debug-artifact identity where applicable.

A target is built once and promoted by digest across applicable environments. A
historical simulator may be a separate adapter target, but it records the exact
shared-core revision or artifact and reconciles against the promoted target.
Configuration is separately versioned and validated. Secret values are excluded
from source, artifacts, deterministic identity, and logs.

## Ownership, configuration, and schema evolution

- Every target has an accountable owner and backup owner.
- Shared schemas, risk controls, build rules, and deployment definitions require
  their domain owners' review.
- Source visibility is separate from data entitlement and deployment authority.
- Configuration rejects unknown keys, records resolved non-secret values, makes
  units explicit, and references secrets by name.
- Schema additions require old/new reader tests. Renames, semantic changes, type
  changes, or unit changes require a new version and migration/rollback plan.
- Previously published data is never edited in place to match a new schema.
- A public schema or language-boundary change includes compatibility evidence for
  every affected consumer selected from the build graph.

## Required architecture decisions

Create an ADR before committing to any of the following:

- A root multi-language build system or remote execution service.
- A service/process split or new message transport.
- A native rewrite or new in-process language boundary.
- A distributed compute scheduler or storage migration.
- A new production artifact format or deployment substrate.
- A breaking schema, persistence, or event-ordering change.

Each ADR records the measured problem, alternatives, decision, migration,
rollback, owners, and evidence required to revisit the choice.

## Public references

- [Jane Street on its Dune migration](https://blog.janestreet.com/how-we-accidentally-built-a-better-build-system-for-ocaml-index/)
- [Jane Street on reproducible Python environments](https://blog.janestreet.com/building-reproducible-python-environments-with-xars/)
- [HRT on its Python monorepo environment](https://www.hudsonrivertrading.com/hrtbeat/inside-hrts-python-fork/)
- [HRT on research and trading engineering](https://www.hudsonrivertrading.com/hrtbeat/engineering-and-interviewing-at-hrt/)
- [HRT on scaling Prometheus](https://www.hudsonrivertrading.com/hrtbeat/scaling-prometheus/)
- [Citadel Securities engineering](https://www.citadelsecurities.com/careers/engineering/)
- [Bazel](https://bazel.build/) and
  [hermeticity](https://bazel.build/basics/hermeticity)

References inform the design but do not override effective venue rules, legal
requirements, measured system behavior, or internally approved policy.
