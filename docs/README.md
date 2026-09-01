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
contracts, governance, a versioned repository-local resource inventory, a threat
and regulatory control map, a program dependency and KPI dashboard, governed
repository-tool targets with compatibility entry points, canonical root,
pre-commit, and hosted-CI topology enforcement, roadmaps, coding standards, a
minimal platform package, a locked uv environment, and a transitional Make
interface. B02 adds a pinned sandboxed Bazel graph for current Python,
governance, documentation, SQL-generation, and test-only Protobuf targets, with
a tested frozen-uv rollback. It does not yet contain clean-machine provisioning,
canonical contracts, data plane, simulator,
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

## Current operating mode: solo bootstrap

The repository currently operates on an explicit **solo-bootstrap track** while
one maintainer is developing the platform and independent functional reviewers
are not yet available. This track separates provisional engineering progress from
institutional acceptance; it does not mark missing approvals as passed or weaken
the blueprint's eventual gates.

During solo bootstrap:

- Repository-local artifacts, tests, documentation, compatibility, deterministic
  behavior, and safety controls that can be completed by one maintainer remain
  mandatory.
- Work may advance provisionally in roadmap order after its technical dependencies
  are implemented and verified. Missing evidence may be deferred only when it
  genuinely requires an unavailable independent reviewer, organization, external
  control plane, or target acceptance environment.
- A deferred gate is recorded as an open finding with its required reviewer,
  environment, evidence, and closure condition. The maintainer does not approve
  the same change repeatedly under fictional independent roles.
- A provisionally implemented package remains `partial`; it does not complete a
  dependency for institutional validation, complete a wave, or satisfy a promotion
  milestone.
- No solo-bootstrap result authorizes external market access, production
  deployment or activation, credentials, capital, venue/account/risk expansion,
  or a claim of institutional readiness.

The track ends when accountable owners and required independent reviewers are
available. They must review provisional work in dependency order, run the missing
gates in the required environments, resolve findings, and record commit-bound
approvals. No provisional result is grandfathered into `validated` status.

## Development environment

The current bootstrap pins uv 0.12.7, Bazel 9.1.0 through `.bazelversion`,
Bazelisk 1.29.0 in CI, and CPython 3.12.14 in both uv and Bazel. From a checkout
with uv and Bazelisk available, create the locked Python environment with:

```sh
uv sync --frozen
```

The tracked `.python-version`, root and `tools/governance` project files, and
`uv.lock` are authoritative for the bootstrap platform and governance-tool
targets. `make sync` provides the same setup through the transitional root
interface.

Bazel module, toolchain, runtime-manifest, and Buf inputs are pinned by
`MODULE.bazel` and `MODULE.bazel.lock`. The [B02 graph contract](architecture/hermetic-build-graph.md)
documents supported targets, sandbox guarantees, provisional dependency records,
the native-language decision, CI parity limits, and rollback.

B01's canonical repository checks are the installed `alpha-governance-*`
commands documented in the
[governed repository topology](architecture/repository-topology.md). B01c makes
Make, pre-commit, hosted CI, A06, and A08 consume those installed commands and
enforce the source topology without ambient `PYTHONPATH`. Existing
`alpha_research.*` APIs and module commands remain compatibility facades for
existing callers and reviewed rollback until a later compatibility change.

Current root commands are:

| Command | Behavior |
| --- | --- |
| `make format` | Format current platform, governance-tool, and test Python source in place |
| `make format-check` | Verify current platform, governance-tool, and test Python formatting |
| `make lint` | Run Ruff lint checks across current Python source |
| `make typecheck` | Run strict mypy checks across current Python source |
| `make architecture-check` | Lint ADRs, the decision log, and repository-local documentation links |
| `make ownership-check` | Validate A03 ownership, independent-review policy, CODEOWNERS, and path coverage |
| `make change-risk-check` | Validate A04 R0-R4 classification, gates, reviewers, rollout, retention, samples, and findings |
| `make evidence-check` | Validate A05 MR fields, SHA-bound evidence manifests, artifact digests, examples, and findings |
| `make topology-check` | Validate B01 source coverage, dependency direction, visibility, ownership, slice metadata, and evidence |
| `make inventory-check` | Validate and query the A06 versioned resource inventory, ownership, lineage, dependencies, retention, status, and evidence links |
| `make security-controls-check` | Validate and query the A07 threat model, control ownership and evidence, trust boundaries, abuse cases, and non-conclusive jurisdiction map |
| `make program-governance-check` | Validate and query the A08 96-package dependency graph, provisional readiness, owned KPI definitions, automatic observations, and non-vanity dashboard |
| `make security` | Run Bandit against current platform and governance-tool Python source |
| `make bazel-build` | Build the representative pinned Python, governance, SQL, and documentation graph |
| `make bazel-test` | Run the focused B02 sandbox, pin, Protobuf, and SQL tests |
| `make bazel-check` | Build and test the B02 graph without invoking the compatibility suite |
| `make rollback-check` | Run the complete frozen-uv pre-B02 validation, smoke, and package build |
| `make test` | Run the Bazel B02 test suite by default; use `BUILD_BACKEND=uv` for rollback |
| `make smoke` | Import the non-editable installed bootstrap package |
| `make build` | Build the representative Bazel graph by default; use `BUILD_BACKEND=uv` for rollback |
| `make check` | Run the Bazel graph and the full retained frozen-uv compatibility path |

Running `make` without a target is currently equivalent to `make check`.

This interface is a provisional B02 implementation, not completion of wave B.
B03 still owns a Nix flake or equivalent clean-machine environment, B04 owns
native-language standards when a native target is justified, B05 owns affected
and merged-result policy, and B06-B08 own remote execution, final admission, and
supply-chain evidence.

## Documentation map

| Document | Purpose |
| --- | --- |
| [Repository charter and boundaries](governance/repository-charter.md) | A01 source/governance scope, naming, external-system boundary, repository dispositions, and pending acceptance evidence |
| [Domain ownership](governance/domain-ownership.md) | A03 accountable domains, CODEOWNERS, independent-review and escalation policy, enforcement, and findings |
| [Change-risk classification](governance/change-risk-classification.md) | A04 deterministic R0-R4 policy, gates, reviewers, rollout, retention, enforcement, and findings |
| [MR template and evidence bundle](governance/merge-evidence.md) | A05 required MR fields, SHA-bound evidence manifest, validator, examples, enforcement, and findings |
| [Governed resource inventory](governance/resource-inventory.md) | A06 stable inventory identities, current resource population, query contract, validation, and findings |
| [Threat model and regulatory control map](governance/threat-model.md) | A07 assets, trust boundaries, abuse cases, privileged actions, control ownership and tests, evidence, jurisdiction profiles, and findings |
| [Program dependency and KPI governance](governance/program-governance.md) | A08 exact roadmap DAG, solo/institutional readiness, automatic observation contract, owned baseline KPIs, dashboard, and findings |
| [Monorepo architecture](architecture/README.md) | Control/data planes, runtime lanes, thin waist, dependency direction, target topology, build and release model |
| [Governed repository topology and tooling](architecture/repository-topology.md) | B01 governed targets, compatibility entry points, root/hook/hosted enforcement, A06/A08 integration, evidence, findings, and B02 boundary |
| [Pinned hermetic build graph](architecture/hermetic-build-graph.md) | B02 Bazel pins, sandbox and code-generation graph, provisional dependencies, Make/CI delegation, rollback, evidence, and findings |
| [Architecture principles](architecture/principles.md) | A02 invariants, design principles, dependency rules, and cross-cutting change rule |
| [Architecture governance](architecture/governance.md) | A02 ADR lifecycle, deprecation policy, exception process, and evidence requirements |
| [Architecture decision log](architecture/decisions/README.md) | A02 template, proposed foundational decisions, package evidence, and deferred findings |
| [Platform contracts](architecture/contracts.md) | Identity, time, data states, research/model, accounting, risk, execution, and asset-extension contracts |
| [Quality and operations](architecture/operations.md) | Criticality, MR risk classes, QG01-QG15, observability, recovery, security, promotion, waivers, and definition of done |
| [Implementation roadmap](roadmap/README.md) | The 12 waves and 96 dependency-ordered packages with delivery slices, tool ownership/restrictions, and adoption order |
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

- Apply the [solo-bootstrap execution overlay](roadmap/README.md#solo-bootstrap-execution-overlay)
  until the repository records that the team-based review model is active.
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
