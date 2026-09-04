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
a tested frozen-uv rollback. B03 adds a locked Nix clean-machine development
shell with exact host tools, supported-platform checks, IDE integration, and a
tested rollback. B04 adds enforceable language admission, warnings-as-errors,
suppression metadata, generated-code and numerical rules, exact static-quality
tools, and deterministic property/state-machine and baseline evidence. The
repository also has B05 fast affected/reverse-dependency validation, an
authoritative full merged-result lane, secret and generated-diff hygiene, Buf
compatibility, configuration-drift checks, and CI duration events. The
repository also has B06's authenticated remote client boundary, isolated cache
namespace, deterministic two-way test sharding, strict flake handling, bounded
resources, guarded main-push integration, and remote-disabled local fallback. B07
adds exact dependency admission for sources, digests, locks, licenses,
vulnerability and exploitability decisions, maintenance, supported wheels and
native artifacts, registries, patch/EOL cadence, and runtime-install prohibition.
The B08 whole-artifact supply-chain boundary adds deterministic SPDX 2.3 SBOMs,
SLSA provenance, lock/toolchain/test identity, protected-context Cosign signing,
immutable digest publication, and fail-closed consumer verification. Its external
signing, registry, independent-review, and target-environment evidence remains
open. C01 adds the first canonical domain contract: immutable internal instrument
identity plus validity-dated, source-attributed symbology with ambiguity-safe
resolution and retained corrections. C02 adds immutable venue, session, holiday,
half-day, auction, halt, price-limit, settlement-calendar, and timezone contracts
behind an exact-version reference adapter with synthetic cross-timezone fixtures.
The repository does not yet contain the remaining canonical contracts, data
plane, simulator, independent risk gateway, OMS/EMS, deployment lanes,
observability substrate, or asset certification evidence.

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

The [B03 clean-machine contract](architecture/clean-machine-environment.md) pins
the developer shell through `flake.nix`, `flake.lock`, and the exact host-tool
record. From a supported host with multi-user Nix installed, enter it with:

```sh
/nix/var/nix/profiles/default/bin/nix \
  --extra-experimental-features 'nix-command flakes' \
  develop --no-write-lock-file
environments/dev/bootstrap.sh check
```

The bootstrap rejects ambient host tools, unsupported platforms, lock drift, and
version mismatch. `environments/dev/bootstrap.sh rollback` exercises the complete
retained uv backend.

The [B04 engineering-standards contract](architecture/engineering-standards.md)
pins the admitted Python quality stack and Hypothesis property/state-machine
target, while keeping C/C++ and Rust dormant until an owned target and provisional
dependency record are reviewed. Its checker rejects weakened policy, stale locks,
unowned or expired suppressions, generated/native source drift, and evidence drift.

The [B05 continuous-integration contract](architecture/ci-policy.md) makes the
fast lane derive owners and reverse dependencies from Bazel and keeps the full
merged-result lane authoritative. It uses pinned Buf for current schema modules,
scans affected or all tracked sources for secrets, rejects generated artifacts in
source diffs, validates interface drift, and emits revision-bound duration events.

The [B06 remote-execution contract](architecture/remote-execution.md) selects a
BuildBuddy-compatible REAPI v2 boundary through a proposed ADR, isolates trusted
cache writes, partitions the complete test graph deterministically, forbids
whole-test retry and silent remote fallback, caps resources, and preserves a
complete remote-disabled local path. Service provisioning remains an open finding.

The [B07 dependency-admission contract](architecture/dependency-admission.md)
reconciles every locked external Python package and the B02-B06 provisional
records, blocks mutable or unhashed lock surfaces and runtime installation, and
keeps pip-audit and Scorecard as signals under repository-owned admission and
exploitability decisions. Qualified, protected-forge, target-platform, registry,
and independent-review evidence remains open.

The [B08 artifact supply-chain contract](architecture/artifact-supply-chain.md)
binds complete artifacts to SPDX, SLSA provenance, tests, locks, toolchain, policy,
and a Sigstore bundle. It rejects native-library omission, unsigned or tampered
content, mutable references, revoked signers, and digest overwrite. Its local
content store is validation evidence, not I01's production registry.

The [C01 instrument-identity contract](architecture/instrument-identity.md)
defines opaque internal IDs, distinct economic/listing/series/contract concepts,
UTC valid-time symbology, exact global and provider-local identifier rules,
ambiguity-safe resolution, and append-only correction lineage. Its fixture is
synthetic and its package remains partial pending independent and target evidence.

The [C02 venue-calendar contract](architecture/venue-calendar.md) defines stable
venue identities, exact MIC and IANA timezone metadata, bounded UTC session
snapshots, versioned overrides, explicit market-state precedence, and bounded
settlement dates. Its pinned fixtures are non-authoritative; live venue/calendar
authority and target reconciliation remain unavailable.

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
| `make engineering-standards-check` | Validate B04 language admission, exact tools, warnings, suppressions, numerical/generated-code rules, baselines, dependency record, and evidence |
| `make dependency-admission-check` | Validate B07 sources, locks, digests, licenses, platforms, decisions, integrations, evidence, and runtime-install prohibition without network access |
| `make dependency-audit` | Run the exact admitted pip-audit signal over the validated locked graph and reject coverage gaps or unresolved vulnerabilities |
| `make architecture-check` | Lint ADRs, the decision log, and repository-local documentation links |
| `make ownership-check` | Validate A03 ownership, independent-review policy, CODEOWNERS, and path coverage |
| `make change-risk-check` | Validate A04 R0-R4 classification, gates, reviewers, rollout, retention, samples, and findings |
| `make evidence-check` | Validate A05 MR fields, SHA-bound evidence manifests, artifact digests, examples, and findings |
| `make topology-check` | Validate B01 source coverage, dependency direction, visibility, ownership, slice metadata, and evidence |
| `make inventory-check` | Validate and query the A06 versioned resource inventory, ownership, lineage, dependencies, retention, status, and evidence links |
| `make security-controls-check` | Validate and query the A07 threat model, control ownership and evidence, trust boundaries, abuse cases, and non-conclusive jurisdiction map |
| `make program-governance-check` | Validate and query the A08 96-package dependency graph, provisional readiness, owned KPI definitions, automatic observations, and non-vanity dashboard |
| `make ci-policy-check` | Validate B05 fast/full lanes, selection policy, schema roots, provisional scanner record, integrations, evidence, and findings |
| `make remote-execution-policy-check` | Validate B06 provider, trust, namespace, sharding, flake, budget, fallback, integration, evidence, and findings |
| `make artifact-supply-chain-check` | Validate B08 SBOM, provenance, signing, immutable publication, consumer policy, evidence, and findings |
| `make remote-build` | Run the authenticated B06 build after clean-main trust checks |
| `make remote-test` | Run one deterministic B06 test shard selected by `REMOTE_SHARD_INDEX` |
| `make remote-quarantine` | Repeat active quarantined targets diagnostically without removing them from normal shards |
| `make remote-local-fallback-check` | Run the complete bounded Bazel graph with remote cache, execution, and uploads disabled |
| `make ci-secrets-check` | Scan every tracked source with the provisionally reused private-key scanner and repository high-confidence token rules |
| `make ci-schema-check` | Lint current Protobuf modules and compare them with `CI_BASE_REF` using pinned Buf |
| `make ci-fast` | Build and test Bazel owners plus reverse dependencies between `CI_BASE_REF` and `CI_HEAD_REF` |
| `make ci-full` | Run the authoritative complete Bazel, hygiene, schema, secret, drift, event, and frozen-uv path |
| `make security` | Run Bandit against current platform and governance-tool Python source |
| `make bazel-build` | Build the representative pinned Python, governance, SQL, and documentation graph |
| `make bazel-test` | Run the focused B02 sandbox, pin, Protobuf, and SQL tests |
| `make bazel-check` | Build and test the B02 graph without invoking the compatibility suite |
| `make integration-test` | Exercise pre-commit ownership enforcement in an isolated Git repository |
| `make performance-test` | Run non-blocking repository-local wall-clock budget checks |
| `make rollback-check` | Run the complete frozen-uv pre-B02 validation, integration test, smoke, and package build |
| `make test` | Run the Bazel B02 test suite by default; use `BUILD_BACKEND=uv` for rollback |
| `make smoke` | Import the non-editable installed bootstrap package |
| `make build` | Build the representative Bazel graph by default; use `BUILD_BACKEND=uv` for rollback |
| `make check` | Run the authoritative B05 full lane |

Running `make` without a target is currently equivalent to `make check`.

This interface is a provisional B02-B08 implementation, not completion of wave B.
B08's repository-local controls do not supply its external signing, registry,
independent-review, or target-environment evidence.

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
| [Clean-machine developer environment](architecture/clean-machine-environment.md) | B03 locked Nix shell, exact host tools, supported platforms, bootstrap, IDE integration, equivalence, rollback, evidence, and findings |
| [Language and static quality standards](architecture/engineering-standards.md) | B04 admitted-language, formatter/linter/type/warning/sanitizer, suppression, generated-code, numerical, API, property/state-machine, baseline, dependency, and evidence contract |
| [Affected and full continuous integration](architecture/ci-policy.md) | B05 affected/reverse-dependency selection, merged-result authority, hygiene, secrets, schema compatibility, drift, events, evidence, and findings |
| [Remote cache, execution, sharding, and flake control](architecture/remote-execution.md) | B06 provider ADR, authenticated trust boundary, namespace isolation, deterministic shards, strict flake behavior, resource budgets, fallback, evidence, and findings |
| [Dependency admission and exploitability governance](architecture/dependency-admission.md) | B07 exact sources, digests, locks, licenses, signals, exploitability decisions, maintenance, platforms, native artifacts, registries, runtime-install prohibition, evidence, and findings |
| [Whole-artifact supply chain](architecture/artifact-supply-chain.md) | B08 SPDX SBOM, SLSA provenance, signed attestation boundary, immutable digest publication, consumer verification, rollback, evidence, and findings |
| [Canonical instrument identity](architecture/instrument-identity.md) | C01 stable internal identities, temporal symbology, ambiguity and correction semantics, goldens, evidence, and C02 boundary |
| [Venue, session, calendar, and market status](architecture/venue-calendar.md) | C02 venue/MIC/timezone values, versioned source and override adapter, sessions, closures, auctions, halts, limits, settlement dates, goldens, evidence, and C03 boundary |
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
