# Alpha Research Platform

## Purpose

This repository is the design and implementation workspace for a crypto-first,
production-oriented statistical-arbitrage platform. The target lifecycle covers
point-in-time data, feature/model research, portfolio construction, realistic
execution, validation, governance, shadow trading, and operational monitoring.

The first workload is a transparent crypto factor-residual strategy. It is a
vertical acceptance test for the platform, not the permanent architecture. The
platform is Python-first and may add Rust or C++ only when measurement, safety, or
interoperability requirements justify native code.

## Current status

The repository is in the design and engineering-foundation stage. Architecture,
contracts, roadmap, and coding standards are tracked. The initial Python package,
locked development environment, and root command interface are implemented;
domain runtime capabilities remain Phase 0 and later implementation work.

Live capital deployment is not authorized by this repository. The highest planned
initial outcome is a reproducible, independently reviewed, paper-ready candidate
with shadow reconciliation and tested recovery controls.

## Development environment

The repository pins uv 0.12.5 and CPython 3.12.14. From a clean checkout with uv
available, create the complete locked development environment with:

```sh
uv sync --frozen
```

The tracked `.python-version`, `pyproject.toml`, and `uv.lock` are authoritative.
uv installs the pinned interpreter when it is unavailable and rejects an
incompatible uv version. `make sync` provides the same locked setup through the
root command interface.

Use these root commands for development and validation:

| Command | Behavior |
| --- | --- |
| `make format` | Format Python source and tests in place |
| `make format-check` | Verify formatting without changing files |
| `make lint` | Run Ruff lint checks |
| `make typecheck` | Run strict mypy checks |
| `make security` | Run Bandit against production Python source |
| `make test` | Run the deterministic test suite |
| `make smoke` | Import the installed package in the locked environment |
| `make build` | Build the source distribution and wheel |
| `make check` | Verify the lock, run all checks and smoke, then build the package |

Running `make` without a target is equivalent to `make check`. The root commands
delegate environment and tool resolution to the pinned uv configuration; the
language-native commands remain available for narrow local iteration.

## Documentation map

| Document | Purpose |
| --- | --- |
| [Monorepo architecture](architecture/README.md) | Runtime planes, component boundaries, repository layout, polyglot builds, artifacts, ownership |
| [Platform contracts](architecture/contracts.md) | Instruments, time, data lineage, research/model, accounting, risk, execution, source and asset-extension contracts |
| [Quality and operations](architecture/operations.md) | Testing, observability, failure, recovery, security, promotion, independent review, definition of done |
| [Implementation roadmap](roadmap/README.md) | Dependency-ordered platform phases, work packages, exit criteria, conditional scaling/cross-asset work |
| [Research program](roadmap/research-program.md) | Sixteen evidence stages from baseline through frozen OOS and shadow package |
| [Coding standards](coding_standards/README.md) | Shared engineering rules and Python, C/C++, and Rust guides |

The architecture and operational documents are normative for target behavior. The
roadmaps define delivery order and may be revised when measured evidence changes a
dependency or invalidates an assumption. Architecture changes require an ADR and
updates to affected contracts, tests, and roadmap packages.

## Design goals

The platform should make these statements demonstrably true:

1. A result is reproducible from immutable source data, source/artifact revision,
   complete non-secret configuration, pinned environment, component versions, and
   seeds.
2. A historical decision uses only information available at its simulated
   decision time.
3. Research, replay, and shadow use authoritative economic logic or independently
   implemented targets that pass versioned conformance tests.
4. Alpha, exposure, financing, execution, capacity, and operational assumptions
   are evaluated jointly.
5. Governed experiments informing selection or promotion remain visible,
   including failed, rejected, and superseded variants.
6. A candidate has an owner, intended use, limitations, monitoring, fallback,
   kill, recovery, and retirement rules.
7. Every deployed target is traceable to an immutable artifact and independently
   versioned configuration.
8. Missing/stale data, invalid risk, infeasibility, unavailable financing,
   incomplete fills, and degradation cannot choose an optimistic fallback silently.
9. Python, Rust, and C++ targets can coexist without duplicating economic rules or
   forcing one repository-wide release.
10. A new asset class extends domain and adapter contracts without rewriting the
    research-governance core.

## Guiding principles

- **Correctness before scale:** begin with deterministic single-process paths and
  small golden datasets.
- **Vertical slice before abstraction:** complete the minimal crypto raw-to-report
  path before designing broad multi-asset hierarchies.
- **Point-in-time behavior is a platform property:** data and evaluation contracts
  enforce availability.
- **Research/live parity is tested:** shared source is useful but not sufficient;
  reconciliation and conformance provide evidence.
- **Domain first, language second:** repository ownership follows economic and
  platform responsibility.
- **Transparent baselines persist:** complex challengers never erase simple
  reference models.
- **Evidence is an artifact:** audits, trials, reports, deployments, and decisions
  are versioned outputs.
- **Operational authority is separate:** source access does not grant data,
  deployment, credential, or capital permissions.

## Initial scope

- Python-first modular implementation in a domain-oriented monorepo.
- Crypto spot and perpetual-futures data, beginning with Binance historical data.
- Batch ingestion before scheduling/streaming.
- Vectorized simulation before event-driven replay.
- Immutable bronze data, canonical Parquet, point-in-time datasets, and local
  metadata/artifact stores.
- Transparent factors/residuals, common model evaluation, risk/portfolio,
  execution/financing, governed trials, shadow, and paper controls.
- One documented root interface for build, test, lint, formatting, and smoke runs.

## Deferred and conditional scope

- Live capital, broker/exchange certification, custody, and key management.
- Microservices, Kafka, Kubernetes, remote execution, and distributed compute
  until workload evidence requires them.
- Rust/C++ or specialized hardware until profiling and an ADR justify them.
- Low-latency market making, full queue-position simulation, and on-chain execution.
- Equities, futures, FX, options, and fixed income until the crypto operational gate
  passes and a concrete research/data need exists.

## Delivery overview

```text
P0 engineering foundation
  -> P1 minimal crypto vertical slice
    -> P2 point-in-time data
      -> P3 governed research/models
        -> P4 risk/portfolio
          -> P5 replay/execution/capacity
            -> P6 shadow/promotion/recovery
              +-> P7 scale/polyglot (evidence-gated)
              +-> P8 cross-asset (evidence-gated)
```

The current next milestone is
[Phase 0: engineering foundation](roadmap/README.md#phase-0-engineering-foundation).
Research stages begin only when their corresponding platform gates pass.

## Working agreement

- Use the nearest coding standard and target owner review.
- Keep changes coherent and verifiable; there is no arbitrary changed-line limit.
- Record commands, fixtures, artifacts, failure behavior, and rollback evidence.
- Preserve unrelated work and generated-file ownership.
- Update architecture, contracts, roadmap, and operator documentation in the same
  change when behavior or a public boundary changes.
- A successful backtest alone is never completion or promotion evidence.
