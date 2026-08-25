# Alpha Research Platform

## Purpose and authority

This repository is the implementation workspace for an institutional multi-asset,
multi-strategy quantitative platform spanning research, deterministic simulation,
portfolio construction and risk, trading, controlled deployment, monitoring, and
governance.

The root
[Institutional Multi-Asset Quant Monorepo Blueprint](../Institutional_Multi_Asset_Quant_Monorepo_Blueprint.pdf)
is the authoritative implementation guideline. Its `MUST`, `SHOULD`, and `MAY`
requirements govern this documentation. The documents under `docs/` refine that
guideline for this repository; they do not weaken its invariants or quality gates.

The first proposed workload is a transparent digital-asset factor-residual
strategy. It is a deliberately narrow platform certification path, not the
permanent architecture or permission to skip the separately governed digital-asset
certification package. The first production target remains one asset class, one
strategy family, one or two venues or brokers, bounded capital, and a
non-ultra-low-latency lane unless latency is the strategy's measured edge.

## Current status

The repository is at the bootstrap stage. It currently contains architecture,
contracts, governance, roadmaps, coding standards, a minimal Python package, a
locked uv environment, and a transitional Make interface. It does not yet contain
the blueprint's Bazel build graph, canonical contracts, data plane, simulator,
independent risk gateway, OMS/EMS, deployment lanes, observability substrate, or
asset certification evidence.

Existing Python bootstrap work is useful input to waves A and B, but it does not
by itself satisfy milestone M0. A wave is complete only when its exit evidence is
demonstrated in the target environment.

This repository never grants trading authority merely by merging code. Capital
exposure requires the complete applicable R4 evidence, independent approvals, a
signed activation envelope, bounded canary, tested rollback and kill paths, and
the applicable legal, compliance, venue, security, operational-risk, and capital
authorizations.

## Development environment

The current bootstrap pins uv 0.12.5 and CPython 3.12.14. From a clean checkout
with uv available, create the current locked Python environment with:

```sh
uv sync --frozen
```

The tracked `.python-version`, `pyproject.toml`, and `uv.lock` are authoritative
for this bootstrap package. `make sync` provides the same setup through the
transitional root interface.

Current root commands are:

| Command | Behavior |
| --- | --- |
| `make format` | Format current Python source and tests in place |
| `make format-check` | Verify current Python formatting |
| `make lint` | Run Ruff lint checks |
| `make typecheck` | Run strict mypy checks |
| `make security` | Run Bandit against current production Python source |
| `make test` | Run the current deterministic test suite |
| `make smoke` | Import the installed bootstrap package |
| `make build` | Build the current Python source distribution and wheel |
| `make check` | Verify the lock, run all current checks, smoke-test, and build |

Running `make` without a target is currently equivalent to `make check`.

This interface is not the target monorepo build architecture. Wave B introduces a
pinned, hermetic Bazel graph for Python, C++ and/or Rust, Protobuf, SQL generation,
and documentation, plus a Nix flake or equivalent reproducible developer
environment. Once those packages are implemented, the repository root interface
must delegate to that graph and preserve affected-target and merged-result checks.

## Documentation map

| Document | Purpose |
| --- | --- |
| [Monorepo architecture](architecture/README.md) | Control/data planes, runtime lanes, thin waist, dependency direction, target topology, build and release model |
| [Platform contracts](architecture/contracts.md) | Identity, time, data states, research/model, accounting, risk, execution, and asset-extension contracts |
| [Quality and operations](architecture/operations.md) | Criticality, MR risk classes, QG01-QG15, observability, recovery, security, promotion, waivers, and definition of done |
| [Implementation roadmap](roadmap/README.md) | The 12 waves and 96 dependency-ordered implementation MR packages |
| [Research program](roadmap/research-program.md) | Strategy-research evidence stages subordinate to platform and promotion gates |
| [Coding standards](coding_standards/README.md) | Shared engineering rules and Python, C/C++, and Rust guides |

Architecture changes require an ADR and corresponding contract, compatibility,
test, migration, rollback, operations, and roadmap updates.

## Non-negotiable invariants

The platform must make all seven blueprint invariants demonstrably true:

1. **Point-in-time causality:** every decision input, universe, price, feature,
   label, corporate action, and reference lookup is queryable as known at the
   decision timestamp.
2. **One strategy kernel:** research, replay, paper, shadow, canary, and live use
   the same decision logic; adapters inject mode-specific behavior.
3. **Immutable release identity:** code, build, model, data references, schemas,
   configuration, limits, evidence, and approvals form a signed manifest.
4. **Risk outside the strategy:** independent gates, limits, throttles, and kill
   switches remain able to constrain a faulty strategy process.
5. **Deterministic replay:** market, reference, order, fill, state, and control
   events have specified ordering, clocks, and random streams.
6. **Evidence before promotion:** every mandatory gate passes before promotion;
   backtest performance cannot compensate for a failed control.
7. **Monitor the economic chain:** platform, data, model, execution, risk, TCA,
   capacity, and PnL health are correlated to the exact release.

Monorepo means one source of truth for code, contracts, lineage, ownership, and
change governance. It does not mean one deployable, one runtime, one security
zone, one performance profile, or one failure domain.

## Target scope

The target platform includes:

- Canonical multi-asset identifiers, units, timestamps, lifecycle, market,
  reference, order, fill, position, risk, audit, and telemetry contracts.
- Immutable raw landing, canonical normalization, point-in-time datasets,
  corrections, lineage, quality, entitlements, and online serving.
- A research SDK, committed trial ledger, leakage-resistant evaluation, model
  registry, model cards, and independent validation.
- A deterministic event simulator, accounting, calibrated execution and cost
  models, capacity, portfolio construction, and stress testing.
- An external pre-trade risk gateway, resilient OMS/EMS, certified venue adapters,
  drop copy, reconciliation, throttles, degraded modes, and kill switches.
- Immutable release manifests and distinct standard-service and low-latency
  deployment lanes, with deployment separated from activation.
- Correlated OpenTelemetry-class observability, SLOs, TCA/PnL attribution,
  runbooks, incident response, disaster recovery, and audit reconstruction.
- Reusable asset and strategy certification packages. Digital assets are optional
  and separately governed, as are cash equities, futures, listed options, FX,
  rates, and credit.

Named technologies in the blueprint are reference choices. A substitution is
valid only when it preserves the same contracts, evidence, isolation, security,
reproducibility, and operational controls.

## Explicit non-goals

- One universal runtime or latency profile for every strategy and asset class.
- One database for research, order routing, audit, and monitoring.
- Promotion based only on Sharpe ratio, PnL, or a weighted readiness score.
- Manual production deployment, notebook execution, workstation artifacts, or
  runtime package installation.
- Monitoring detached from limits, rollback, incident ownership, and economic
  attribution.
- A claim that engineering process or controls guarantee investment performance.

## Delivery overview

```text
A governance -----> B build platform
       |                    |
       +-------> C canonical contracts
                        -> D data platform
                        -> E research platform
                        -> F simulation
                        -> G portfolio and independent risk
                        -> H trading runtime
                        -> I deployment
                        -> J observability
                        -> K security and governance
                        -> L asset and strategy certification
```

The 96 packages are grouped into twelve waves, A through L. Governance, build,
contracts, security, and observability begin early; they are not cleanup phases.
The critical path is canonical contracts, point-in-time data, deterministic
simulation, portfolio/risk, trading runtime, controlled deployment, and finally
asset/strategy certification. See the [implementation roadmap](roadmap/README.md).

## Working agreement

- Assign every change an R0-R4 risk class and run all mandatory QG01-QG15 gates
  applicable to that class.
- Prefer one logical behavior change per MR. Keep non-generated changes near or
  below 400 lines where practical; larger work needs a split plan, a generated-code
  explanation, or an approved indivisible-migration rationale.
- Require a linked roadmap item, owner, scope/non-goals, impact analysis, evidence
  plan, rollout, rollback, monitoring, runbook, and available reviewers before
  implementation.
- Preserve dependency direction, target ownership, immutable evidence, and
  research/live kernel parity.
- Update architecture, contracts, roadmap, tests, and operator documentation in
  the same change when behavior or a public boundary changes.
- A merged MR is not automatically a release, a deployed artifact is not
  automatically activated, and a successful backtest is never promotion evidence.
