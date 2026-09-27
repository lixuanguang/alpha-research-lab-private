# Architecture

This page is the current architecture overview for the Alpha Research Python
workspace. The long-term destination is an institutional-grade monorepo for
multi-asset, multi-strategy research, productionization, and monitoring. The
repository implements three domain foundations: [instrument
identity](instrument-identity.md), [venue calendars](venue-calendar.md), and
[financial units](financial-units.md), plus exact serialization, provenance,
reference-catalog and bounded Binance event/decoder foundations. Historical
acquisition, occurrence/revision admission, bitemporal eligibility selection,
quality validation and atomic dataset publication/reopening are implemented.
Native Bitfinex/OKX acquisition, dataset queries as of a cutoff and bounded book
replay, bounded saved-snapshot discovery and pinned multi-input research selections
are also available. Retained experiment attempts, temporal split admission and
unfitted exploration studies, train-only models, bounded spot simulation/accounting
and independent spot risk limits are implemented. The codebase now also includes
a local shared-account portfolio increment: it commits selected strategy decisions
through independent budgets, retains tagged child orders, nets compatible spot
orders, and allocates normalized fills and fees back to their owners. The
[MR09 acceptance record](../roadmap/README.md#mr09-delivery-and-acceptance) owns
its validation status; physical venue execution remains unqualified and KIV.
Configured economic reports,
serial local ClearML pipelines and pinned lakeFS dataset versions are also available.
Named multi-feature, fitted-transform, estimator-state and restartable decision contracts
now have [installed research consumers](../../src/research/features/README.md#generalized-feature-lifecycle).
MR06 adds independent operating packages and trusted local installation. Economic
portfolio construction and deployed paper services remain planned. Live venue
order execution and live trading monitoring are
[KIV](../roadmap/README.md#live-trading-kiv-and-reconsideration). See the
[platform design](platform-design.md) for the future module boundaries,
lifecycles, runtime lanes, and scaling triggers.

The locked `msgspec` dependency supports the exact serialization boundary for
financial values, canonical market-data records, configuration, acquisition,
datasets, simulation orders/fills/checkpoints and retained research reports.
Wire records use frozen `msgspec.Struct` values with strict typed codecs;
the C01, C02 and C03 foundation models retain their Pydantic contracts.
Production venue order submission and live execution remain KIV.

The [platform roadmap](../roadmap/README.md) requires the complete initial
OKX/Bitfinex spot research and paper infrastructure before QR onboarding. Quant
development supplies reference rule/model studies, paper instances and metric/chart extensions to
qualify the shared APIs without waiting for accepted QR research. The same
versioned decision components serve research and runtime; actual research
acceptance and trading activation remain separate. Current bounded capabilities
above do not yet satisfy that planned gate.

The full monorepo is one source tree with multiple deployables and release
cadences. Shared economic semantics are canonical; strategy variants, asset
mechanics, storage, and computation lanes remain separate until a consumer or
measured workload justifies a shared boundary.

The current runtime ships functional packages directly under `src/`, with
`applications/` owning executable workflow composition. Each library has one
explicit public `__init__.py`; applications select adapters and inject reader,
verifier and book-construction capabilities. Shared libraries never import
applications or select source factories. The [functional source map and API
rules](platform-design.md#current-and-planned-repository-shape) describe current
owners and clearly label planned capabilities.

## Current boundary

The planned research-to-operation path is:

```text
configured fixture -> versioned data + explicit availability
    -> reference query/replay + synthetic economics
    -> reproducible baseline with declared cost assumptions and exact accounting
    -> reusable research + qualified live inputs + verified artifact
    -> paper/shadow with risk, reconciliation, monitoring, stop and recovery
    -> OOS and forward paper profitability net of applicable costs
    -> decision whether to reopen live work (KIV); separate qualification/activation
```

The [delivery dependencies](../roadmap/README.md#delivery-order-and-dependencies)
own detailed order. Artifact verification precedes any actual deployment, including a collector
pulled forward for a concrete data need. Operational controls accompany their
runtime and must pass before activation.

The fixture and dataset publication workflows exist today. Published snapshots
retain declared quality scope; current archive evidence supports exploratory
degraded use, not causal dataset acceptance. Keep research code dependent on the
implemented contracts. Quant development supplies launch workloads for required
data and broker adapters before onboarding. Do not introduce a service
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

Current dependency direction is organized by functional owner:

- `reference_data/instruments/` and `reference_data/calendars/` own identity and
  time contracts; `financial_units/` owns exact economic values and conventions.
- `market_data/contracts/` owns neutral event/source records. Adapters, storage,
  validation, datasets, query and replay implement their respective capabilities
  through explicit public APIs and injected reader/verifier operations.
- `research/experiments/` owns semantic identities, temporal split admission and
  atomic attempt history. [Its contract](../../src/research/experiments/README.md)
  defines the local writer and holdout boundaries.
- `research/studies/` owns comparisons, diagnostics, economic reports, tracking
  and pipeline metadata through its [study contract](../../src/research/studies/README.md).
- `research/exploration/` consumes admitted data for EDA and retained unfitted studies.
  `research/results/` owns the retained feature-result wire contract shared with
  model admission and diagnostics, preserving its existing serialized schema.
  `research/features/` owns versioned trailing-price diagnostics; `research/labels/`
  owns separate forward outcomes. `research/models/`, `strategies/`, `simulation/`,
  `accounting/` and `risk/` provide the bounded spot research path. The sole
  `alpha-backtest` command composes its configured and pipeline actions.
- `portfolio/` owns the shared-account portfolio context and exact deterministic
  allocation primitives. It preserves intent scope and resolves fill/fee residuals;
  it is not yet a general economic portfolio optimizer.
- `configuration/` resolves definitions and selections. `runtime/` and `telemetry/`
  supply identity, supervision and observations without importing applications.
  The [monitoring guide](../../src/telemetry/README.md) owns causal versioned
  telemetry, exact metrics, retained dashboards, local routing and independent
  watchdog emission. `execution.PaperMonitoring` projects committed paper facts
  and exact reports; research report adapters stay in `research.studies`.
  `runtime.SharedDecisionRuntime` reuses one `DecisionSession` per selected
  instance and restores its policy state from the account journal.
- [`execution/`](../../src/execution/README.md) owns the portable paper/shadow
  order journal, lifecycle, pending reservations and modeled matching. It consumes
  independent risk and accounting; candidate supervision stays in `runtime/`.
  Its shared `AccountJournal` adds atomic firm/account/instance admission, tagged
  child orders, compatible physical net orders, allocated event postings and
  complete local reconciliation. [Risk](../../src/risk/README.md) owns independent
  policy and [accounting](../../src/accounting/README.md) owns exact multi-currency
  postings and append-only corrections. MR11 owns integrated paper reconciliation;
  authenticated physical venue reconciliation is KIV.
- [`applications.paper`](../../src/applications/paper/README.md) composes the
  existing dedicated-account candidate flows, explicit normalized-fact
  `run_shared_paper`, and `run_live_shared_paper` for native public-input matching
  in dedicated/shared paper accounts. The latter retains exact reports and
  independently recoverable monitoring; it makes no venue submissions.
- `applications/` composes these libraries and exposes the installed commands.
  Libraries never import applications; applications never import sibling workflows.

Foundational contracts do not depend on notebooks, research-only approximations,
deployment composition roots, or workstation configuration. Provider details
stay inside adapters: Tardis framing owns capture and blank-line behavior, while
the Binance venue decoder owns combined-stream `stream`/`data` payload
interpretation. Strategy policy emits target/exposure or order/quote intents.
Shared-account coordination preserves their child ownership while combining only
compatible orders; independent risk admission remains in force. Economic portfolio
construction and venue submission remain separate capabilities. Cross-process
interfaces will use versioned schemas when such a boundary is introduced.

The [dataset library](../../src/market_data/datasets/publication.py) assembles
saved-input validation and publication with injected source capabilities. The
[data library guide](../../src/market_data/README.md) describes public consumers.

## Implemented domain contracts

These pages are normative for the implemented libraries and their retained
golden/property evidence.

| Contract | Implemented boundary | Key guarantee |
| --- | --- | --- |
| C01 | [Instrument identity and temporal symbology](instrument-identity.md) | Stable canonical IDs, validity-dated mappings, correction history, and explicit UTC resolution |
| C02 | [Venue calendars and market status](venue-calendar.md) | Versioned bounded snapshots, UTC half-open sessions, DST-safe state, and fail-closed overrides |
| C03 | [Financial units and conventions](financial-units.md) | Dimension-safe exact arithmetic, explicit rounding, and an isolated date-based convention adapter |
| Historical data | [Market-data contracts](../data/contracts.md) | Exact metadata/events, verified acquisition, occurrence/revision lineage, eligibility selection, quality reports and immutable snapshots with explicit use scope |
| Native books | [Collector contracts](../data/l3-collectors.md), [OKX data](../data/okx-market-data.md) | Source-specific capture, persistence, recovery and bounded offline replay |
| Shared spot account coordination | [Execution account contract](../../src/execution/README.md#shared-account-admission-and-reconciliation) | Atomic decision admission, tagged child orders, compatible physical net orders, allocated normalized fills/fees and local reconciliation |

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
| `uv run --frozen alpha-governance-artifacts release-check` | Refuse the full research release graph while its QuantLib source binding is unresolved |
| `uv run --frozen alpha-governance-artifacts build / verify / install / rollback / run` | Signed operating artifacts, complete closure admission, offline local installation and compatible state-preserving rollback; see the runbook |
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
- The [release workflow](../governance/workflow.md#build-a-release) builds and
  signs independent collector/execution releases after actual source, lock,
  inventory and vulnerability verification. An independently provisioned builder
  trust policy precedes installation. The administrative installer promotes the
  same authenticated bytes into a clean local environment and preserves compatible
  current state during rollback.

QuantLib 1.43 remains in the complete research graph under its bounded
[development/CI allowance](dependency-admission.md#wheel-only-development-allowance)
through **2026-10-04**. Its source-to-wheel binding is unverified; the whole graph
still cannot be released. MR06's actual operating closures omit that adapter and
unrelated research dependencies. This selected-closure admission retains the full
root policy and vulnerability checks and does not resolve QuantLib's own source
binding. Native adapter conformance and domain goldens remain in research checks.
The [runbook](../governance/operations.md#trusted-local-installation) owns local
trust, signing, installation, key rotation and rollback limits.

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
| Serialization boundary | Market data, configuration, simulation orders/fills/checkpoints and research results use the [engineering serialization requirements](../coding_standards/README.md#classes-records-errors-and-resources), including exact financial-value hooks. Venue execution remains planned. Pydantic remains available for cold administration and the C01/C02/C03 foundation APIs. |
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
