# Implementation Roadmap

## Purpose and authority

This is the repository view of the
[institutional blueprint's](../../Institutional_Multi_Asset_Quant_Monorepo_Blueprint.pdf)
12 waves and 96 logical implementation merge-request packages. It replaces the
obsolete P0-P8/`ENG-*`/`CRY-*` phase plan. The companion
[research program](research-program.md) sequences strategy evidence but remains
subordinate to these platform gates.

Each row below is a logical MR package. If it exceeds reviewable size, split it
into code, migration, backfill, and rollout MRs while preserving the ID as an epic.
Prefer one logical behavior change and keep non-generated changes near or below
400 lines where practical. Every MR inherits its R0-R4 approvers and mandatory
QG01-QG15 evidence from
[quality and operations](../architecture/operations.md).

A wave is complete only when exit evidence is demonstrated in the target
environment. Code merge, a favorable metric, or a dashboard score alone does not
complete a package.

## Solo-bootstrap execution overlay

The repository currently has one maintainer. Until the required team and
independent review functions exist, implementation may use a provisional
solo-bootstrap track. This overlay changes the execution status of work, not the
roadmap dependency graph, package exit criteria, quality gates, promotion rules,
or definition of institutional completion.

Two states must remain distinct:

- **Provisionally implemented:** the smallest coherent package behavior and all
  repository-local evidence within the maintainer's control are complete, while
  explicitly identified organizational or external acceptance evidence is
  deferred. Its package status remains `partial`.
- **Validated:** every required artifact, test, compatibility check, target-
  environment exercise, approval, and exit-evidence item exists. Only this state
  completes a dependency for institutional validation or a wave exit.

Solo-bootstrap work may move to the next provisional package only when:

1. The predecessor's required repository-local artifacts and deterministic tests
   exist and pass.
2. No missing technical prerequisite, architectural decision, schema, migration,
   safety control, or locally enforceable security control is being deferred.
3. Every remaining finding genuinely requires an unavailable independent role,
   organization, external control plane, or target acceptance environment.
4. The new package can be implemented and tested coherently without pretending
   the predecessor is validated or absorbing a separate missing technical package.

Each provisional package records its risk class, applicable gates, completed
evidence, deferred evidence, owner, closure condition, and explicit non-goals.
The maintainer may cover implementation roles but must not manufacture independent
risk, model-validation, SRE, security, compliance, legal, venue, or capital-owner
approval.

Solo bootstrap never permits production credentials, external executable order
flow, deployment or activation authority, capital exposure, or expansion of a
venue, account, instrument, or risk envelope. Paper, shadow, canary, live, release,
and promotion claims retain all original gates and target-environment evidence.

When the team forms, provisional packages are reviewed in original dependency
order. Deferred gates are executed, findings are remediated, and commit-bound
approvals are recorded before any package becomes `validated`. Provisional work
is not grandfathered, and a later provisional implementation cannot compensate
for a failed earlier hard gate.

## Milestones

| Milestone | Waves | Outcome | Do not proceed until |
| --- | --- | --- | --- |
| M0 - Governed source | A-B | Protected monorepo, hermetic build, evidence pipeline, signed artifacts | Ownership, risk classes, reproducibility, and supply-chain controls are live |
| M1 - Causal research | C-E | Canonical contracts, PIT data, experiment ledger, robust evaluation | Leakage suite, snapshot reproducibility, and independent research report pass |
| M2 - Executable simulation | F-G | Deterministic market/execution simulation, accounting/costs, portfolio, independent risk | Replay parity, accounting, cost calibration, risk, and stress pass |
| M3 - Safe production path | H-K | OMS/adapters, paper/shadow, immutable deployment, SLOs, security, model governance | Recovery, kill, shadow, rollback, DR, and audit evidence pass |
| M4 - Capital scale | L | Asset/strategy certification, controlled canary, scale-up | No critical finding; live reconciliation, capacity, and operational review approve each increase |

## Wave A - Governance foundation

| ID | Objective | Depends on |
| --- | --- | --- |
| A01 | Repository charter and monorepo boundary | - |
| A02 | Architecture principles, ADR framework, dependency/deprecation/exception rules | A01 |
| A03 | Domain ownership and CODEOWNERS with independent-review paths | A01-A02 |
| A04 | Deterministic R0-R4 change-risk classification and policy-as-code | A02-A03 |
| A05 | MR template and SHA-bound machine-readable evidence bundle | A04 |
| A06 | Data, model, strategy, service, limit, venue, release, and control inventories | A01-A05 |
| A07 | Threat model and jurisdiction-tailored regulatory control map | A02, A06 |
| A08 | Program dependency graph and owned baseline KPIs | A01-A07 |

**Wave evidence:** protected source, approved charter and ADR process, complete
ownership, enforced change classes, reconstructable evidence, inventories, threat
model, and non-vanity program metrics.

## Wave B - Build platform and software supply chain

| ID | Objective | Depends on |
| --- | --- | --- |
| B01 | Repository skeleton and automated dependency constraints | A02-A05 |
| B02 | Bazel hermetic toolchains for Python, C++ and/or Rust, Protobuf, SQL, and docs | B01 |
| B03 | Nix flake or equivalent hermetic developer environments | B02 |
| B04 | Language standards, static quality, sanitizers, numeric tolerances, codegen policy | B02-B03 |
| B05 | CI fast lane, affected-target analysis, secrets and schema checks | B01-B04 |
| B06 | Authenticated remote cache/execution, sharding, and flake control | B05 |
| B07 | Dependency, vulnerability, license, approved-registry, and no-runtime-install policy | B02-B06 |
| B08 | Provenance, SPDX SBOM, signing, attestations, and digest verification | B07, A07 |

**Wave evidence:** clean sandboxed local/CI builds have identical digests,
undeclared inputs fail, affected-target selection matches full builds, flaky tests
cannot pass silently, locks are complete, and unsigned or mutable artifacts are
rejected.

## Wave C - Canonical multi-asset contracts

| ID | Objective | Depends on |
| --- | --- | --- |
| C01 | Stable instrument identity and temporal symbology mappings | B01-B05 |
| C02 | Venue, session, calendar, market-status, and timezone contracts | C01 |
| C03 | Typed units, currencies, prices, quantities, and conventions | C01-C02 |
| C04 | Event, receipt, ingestion, knowledge, valid-time, sequence, and bitemporal model | C01-C03 |
| C05 | Versioned market, reference, and lifecycle event schemas | C01-C04 |
| C06 | Order, execution, and fill state machines with idempotency | C01-C05 |
| C07 | Position, cash, PnL, exposure, and limit schemas | C03, C05-C06 |
| C08 | Schema registry, compatibility policy, golden fixtures, migrations, deprecation | C01-C07 |

**Wave evidence:** lifecycle ambiguity, symbol reuse, unit errors, host-local time,
future knowledge, invalid transitions, accounting-sign errors, and unsupported
schema changes are caught by golden, property, compatibility, and replay tests.

## Wave D - Point-in-time data platform

| ID | Objective | Depends on |
| --- | --- | --- |
| D01 | Immutable entitled raw landing with checksums, retention, and encryption | B08, C04 |
| D02 | Connector SDK with checkpoints, backpressure, idempotency, dead letters, replay | D01, C05 |
| D03 | Deterministic canonical normalization and cross-source reconciliation | D01-D02, C08 |
| D04 | Temporal reference/master data service and vendor-priority rules | C01-C05, D03 |
| D05 | Data-quality framework, publication policy, dataset SLOs, runbooks | D02-D04 |
| D06 | PIT dataset builder, as-of joins, universe history, reproducible snapshots | C04, D03-D05 |
| D07 | Lineage, catalog, entitlements, usage/cost accounting, retention | D01-D06, A06 |
| D08 | Replay, corrections, backfills, downstream impact, and reconciliation | D06-D07 |

**Wave evidence:** immutable source integrity, recoverable connector faults,
source-to-canonical lineage, no private symbol maps, quality-triggered
quarantine/degrade/stop, adversarial leakage rejection, reproducible snapshot
digests, entitlement propagation, and idempotent impact-aware correction.

## Wave E - Research and model platform

| ID | Objective | Depends on |
| --- | --- | --- |
| E01 | Research SDK and explicit runtime context without global/workstation state | B, C, D06 |
| E02 | Immutable experiment and committed trial ledger | E01, A06 |
| E03 | Versioned dataset, feature, label, transformation, and universe APIs | D06-D08, E01-E02 |
| E04 | Time-series splits, purging, embargo, walk-forward, nested selection, final OOS lock | E03 |
| E05 | Baseline, model, calibration, ensemble, serialization, and inference adapters | E03-E04 |
| E06 | Evaluation, robustness, ablation, DSR/PBO/FDR, and multiple-testing controls | E02-E05 |
| E07 | Reproducible local/cluster/cloud-HPC runner with quotas, resume, cache, cost | E01-E06, B06 |
| E08 | Model registry, research report, promotion card, independent validation | E02-E07, B08 |

**Wave evidence:** notebook, batch, and CI semantics agree; trial deletion is
prevented; offline features reproduce; split/leakage attacks pass; declared
baselines remain; uncertainty is dependence-aware and trial-adjusted; distributed
runs are bounded/restartable; no promotion card has mutable or missing evidence.

## Wave F - Deterministic simulation

| ID | Objective | Depends on |
| --- | --- | --- |
| F01 | Deterministic event-driven simulator and extensible asset/venue models | C, D08, E01 |
| F02 | Injected clocks, named random streams, checkpoints, state, and causality guards | F01, C04 |
| F03 | Accounting, corporate action, expiry, roll, settlement, and FX engine | F01-F02, C07, D04 |
| F04 | Market-state/order-book simulator for sessions, auctions, limits, and bad books | F01-F03, D03-D05 |
| F05 | OMS, fill, queue, execution, outage, bust/correct, and drop-copy simulator | C06, F04 |
| F06 | Spread, fee, impact, borrow, funding, margin, and capacity models | F03-F05, D07 |
| F07 | Multi-venue latency, failure, regime, degradation, and counterfactual scenarios | F04-F06 |
| F08 | Research/simulation/paper/live parity, golden strategies, performance budgets | F01-F07 |

**Wave evidence:** event ordering and randomness are reproducible, checkpointed
runs equal uninterrupted runs, future access hard-fails, accounting reconciles,
fill/cost models are calibrated with conservative bands, scenario catalogs cover
normal/stressed/pathological states, and unexplained parity deltas block progress.

## Wave G - Portfolio and independent risk

| ID | Objective | Depends on |
| --- | --- | --- |
| G01 | Signal-to-target API separating forecast, portfolio, and execution policy | E05, F08, C07 |
| G02 | Authoritative intraday position, cash, pending-order, inventory, exposure service | C07, F03, G01 |
| G03 | Versioned risk-model, covariance, scenario, liquidity, and quality interfaces | G02, E06 |
| G04 | Optimizer/constraint library with diagnostics and explainable fallback | G01-G03, F06 |
| G05 | External fail-closed pre-trade risk gateway | C06-C07, G02-G04 |
| G06 | Hierarchical limits, stress, drawdown, liquidity, margin, and collateral | G03-G05 |
| G07 | Independent global/strategy/asset/venue/account/instrument kills and degraded modes | G05-G06, H04 preparation |
| G08 | Independent risk/PnL/control recomputation, breaks, sign-off, evidence retention | G02-G07, F06 |

**Wave evidence:** stage substitution is possible, authoritative state reconciles,
risk numerics and optimizer behavior are explainable, unavailable risk fails safe,
limits reconcile across accounts, kill paths work during process/data failure, and
material breaks block scale-up.

## Wave H - Trading runtime and connectivity

| ID | Objective | Depends on |
| --- | --- | --- |
| H01 | Shared typed deterministic strategy kernel for research through live | E01, G01, F08 |
| H02 | Live runtime, scheduling, dependency injection, readiness, health, resource limits | H01, B08, I preparation |
| H03 | Durable state, checkpoint/replay, idempotency, duplicate suppression, fencing | H02, C06 |
| H04 | Production OMS lifecycle, drop-copy comparison, aging, audited operator controls | C06, H03, G05 |
| H05 | FIX/native session adapter SDK, time sync, throttles, recovery, conformance | H04, C08 |
| H06 | One production-grade venue adapter with independent drop copy and reconciliation | H05, D02, G08 |
| H07 | Paper broker and shadow router with executable-message suppression | H01-H06, J preparation |
| H08 | Bounded canary/live activation certification and dual-control enablement | H07, G07, I, J, K |

**Wave evidence:** the same kernel runs in every mode; incompatible startup fails;
restart cannot duplicate orders; all OMS/session/venue anomalies reconcile;
secrets stay external; shadow cannot emit executable messages; activation cannot
exceed the signed envelope and rolls back safely.

## Wave I - Immutable deployment and recovery

| ID | Objective | Depends on |
| --- | --- | --- |
| I01 | Signed release manifest and immutable artifact registry | B08, E08, C08 |
| I02 | Dev/CI/replay/staging/paper/shadow/canary/prod separation and one-way promotion | I01, A04 |
| I03 | Typed configuration, validation, secret references, staged flags, expiry, digests | I01-I02, C08 |
| I04 | Short-lived service identities, secrets, privileged control plane, break glass | A07, B08, I02 |
| I05 | GitOps deployment lane for standard services | I01-I04, H02 |
| I06 | Immutable bare-metal low-latency lane with host/clock attestation | I01-I04, H02, H05 |
| I07 | Progressive rollout, schema/state migration, coordinated multidimensional rollback | I05-I06, C08 |
| I08 | Tiered backup, verified restore, DR, failover, and break-glass exercises | I01-I07, G07 |

**Wave evidence:** manifests reject mutable/incomplete state, no stage rebuilds,
config drift/unknown values fail, no static production secret exists, only signed
artifacts deploy, host/clock drift blocks low-latency activation, mixed-version and
failed migrations recover, and RTO/RPO restores are verified.

## Wave J - Observability, SLOs, and incident control

| ID | Objective | Depends on |
| --- | --- | --- |
| J01 | OpenTelemetry-based trace/metric/log/audit substrate and retention | B01, H02, I01 |
| J02 | Metric/log/trace naming, units, cardinality, clock-skew, sensitive-data policy | J01, C03-C04 |
| J03 | Tiered SLIs/SLOs, error budgets, burn alerts, and release freeze policy | J01-J02, A03-A04 |
| J04 | Data freshness, quality, lineage, entitlement, PIT, and clock monitors | D05-D08, J01-J03 |
| J05 | Feature/model/strategy/regime drift, calibration, and state monitoring | E08, H01, J01-J04 |
| J06 | Execution quality, TCA, capacity, and full PnL attribution | F06, H06, G08, J01-J05 |
| J07 | Alert routing, runbooks, immutable audit stream, and operator UX | J03-J06, A06 |
| J08 | Synthetic probes, game days, incident response, and postmortem-to-test loop | J04-J07, I08, G07 |

**Wave evidence:** every release/strategy/account/asset/venue/order/incident
correlates end to end; cardinality is bounded; SLOs reflect trading impact; stale
data changes control state; model monitoring avoids noisy-PnL auto-actions;
simulated/realized costs reconcile; alerts reach owners; game days close corrective
actions with tests.

## Wave K - Security, access, model risk, and audit

| ID | Objective | Depends on |
| --- | --- | --- |
| K01 | RBAC, JIT access, separation of duties, session recording, two-person control | A03-A07, I04 |
| K02 | Research/data/control/trading/risk/management network segmentation and egress | K01, I05-I06 |
| K03 | Enforced reviewed-source, hermetic-build, provenance, SBOM, signature, digest policy | B07-B08, I01 |
| K04 | Encryption, secrets/keys, rotation, revocation, ownership, backup-key controls | I04, K01-K03 |
| K05 | Vulnerability, license, dependency, exploitability, patch, and end-of-life operations | B07, K03 |
| K06 | Data entitlement, privacy, geographic/user restriction, retention/deletion controls | D01, D07, K01 |
| K07 | Model materiality, inventory, independent validation, findings, monitoring, retirement | E08, J05, A06 |
| K08 | Compliance evidence mapping, control tests, retention, and audit reconstruction | A07, K01-K07, J07 |

**Wave evidence:** production is read-only by default; network policy isolation is
tested; tampered artifacts fail; key rotation stays within budget; critical
exposures and license obligations have owned dispositions; entitlements propagate
through lineage; material models cannot self-validate; a release reconstructs from
hypothesis through orders and rollback.

## Wave L - Asset and strategy certification

| ID | Objective | Depends on |
| --- | --- | --- |
| L01 | Cash-equities certification | C-K |
| L02 | Futures certification | C-K |
| L03 | Listed-options and volatility certification | C-K |
| L04 | FX, rates, and credit certification | C-K |
| L05 | Optional, separately governed digital-assets certification | C-K |
| L06 | Cross-sectional, time-series, and statistical-arbitrage templates | E-K and selected L01/L02/L04 assets |
| L07 | Market-making, execution, and volatility-strategy templates | F-K and selected L01-L04 assets |
| L08 | Institutional-readiness review and controlled capital scale-up | L01-L07 |

Each asset certification covers identity/lifecycle, calendars/conventions,
market/reference and PIT data, accounting, cost, execution, risk,
margin/collateral, reconciliation, monitoring, runbooks, and failure scenarios.
Each strategy manifest declares target/horizon, universe, feature graph, model,
portfolio/execution policy, accounts, venues, capital/limits, state, data, SLOs,
alerts, rollback, recovery, and owner.

**Wave evidence:** asset-specific golden/stress/paper/shadow/canary cases pass;
unsupported behavior is explicit; at least one governed strategy reproduces from
ledger to shadow; hard risk remains external; readiness has no critical finding;
capital increases only after stable live reconciliation and signed review.

## Wave exit reviews

At every wave boundary, review evidence using a real representative sample, not
only unit fixtures. Include at least one normal scenario, data correction, venue
or service failure, state recovery, risk breach, rollback, and audit
reconstruction. Open critical findings block the next capital-exposure milestone.

Practical parallel ownership is:

- Platform/build: A, B, and I foundations.
- Data/reference: C, D, and asset lifecycle.
- Research/simulation: E, F, and strategy templates.
- Portfolio/risk/trading: G, H, and venue certification.
- SRE/security/governance: J, K, DR, and evidence.
- Asset pods: L, starting with one narrow target only after C-K foundations are
  stable.

Do not create a hand-off team that rewrites research for production. Researchers
and engineers remain jointly accountable through shadow and early live operation;
the shared kernel is the production path.

## Current repository mapping

Repository-local implementations and deterministic checks now exist for A01-A07.
Each remains `partial` on the solo-bootstrap track: all locally resolvable controls
through A07 pass, while their recorded organization, protected-forge,
target-control-plane, independent-review, and qualified applicability evidence
remains open. This does not validate wave A or authorize a wave exit.

The existing uv lock, Python package, Make checks, and engineering tests are
bootstrap evidence relevant to B02-B05. They do not yet meet the Bazel, Nix or
equivalent, ownership, risk-class, affected-target, merged-result, provenance,
SBOM, signing, or admission requirements and therefore are not marked validated.
Legacy `ENG-*`, `CRY-*`, `DATA-*`, `RES-*`, `PORT-*`, `EXEC-*`, `GOV-*`,
`SCALE-*`, and `ASSET-*` platform IDs are superseded by A01-L08. Research-stage
`R01-R16` identifiers remain local to the companion empirical program and are not
implementation MR IDs.
