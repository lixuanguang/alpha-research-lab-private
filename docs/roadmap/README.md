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

| ID | Objective / delivery | Library/tool to use or incorporate | Incorporation boundary / restriction | Depends on |
| --- | --- | --- | --- | --- |
| A01 | Repository charter and monorepo boundary | — | Repository-owned governance; no external authority | - |
| A02 | Architecture principles, ADR framework, dependency/deprecation/exception rules | — | ADRs remain repository authority | A01 |
| A03 | Domain ownership and CODEOWNERS with independent-review paths | `CODEOWNERS` | Forge enforcement and independent approval remain external evidence | A01-A02 |
| A04 | Deterministic R0-R4 change-risk classification and policy-as-code | — | Repository owns classification and gate mapping | A02-A03 |
| A05 | MR template and SHA-bound machine-readable evidence bundle | — | Evidence must bind to the reviewed revision | A04 |
| A06 | Data, model, strategy, service, limit, venue, release, and control inventories | — | Repository owns inventory schema and identifiers | A01-A05 |
| A07 | Threat model and jurisdiction-tailored regulatory control map | — | Qualified legal/compliance applicability remains external evidence | A02, A06 |
| A08 | Program dependency graph and owned baseline KPIs | — | Metrics are non-vanity signals and never replace hard gates | A01-A07 |

**Wave evidence:** protected source, approved charter and ADR process, complete
ownership, enforced change classes, reconstructable evidence, inventories, threat
model, and non-vanity program metrics.

## Wave B - Build platform and software supply chain

| ID | Objective / delivery | Library/tool to use or incorporate | Incorporation boundary / restriction | Depends on |
| --- | --- | --- | --- | --- |
| B01 | Governed topology: `B01a` registry and graph checks; `B01b` owned tooling targets and compatibility entry points; `B01c` root, pre-commit, hosted-CI, A06, and A08 enforcement | Repository-owned Python tooling | Complete current source coverage; no empty placeholders or new build/domain dependencies | A02-A05 |
| B02 | Pinned hermetic graph for Python, justified native languages, schemas, SQL, and docs; sandbox and undeclared-input tests; tested Make rollback | Bazel, `rules_python` 2.2, uv, Buf | uv lock is transitional resolution input; Make delegates; native languages require justification | B01 |
| B03 | Clean-machine declarative bootstrap with exact host-tool and supported-platform evidence | Nix or equivalent | No workstation state; prove Bazel equivalence and rollback | B02 |
| B04 | Language, sanitizer, numerical, generated-code, and property/state-machine standards | Hypothesis 6.167; admitted language sanitizers | Current-tool upgrades belong to the pre-B01 gate; add new tools through provisional B07-compatible records; no domain behavior | B02-B03 |
| B05 | Fast affected/reverse-dependency CI plus full merged-result lane, hygiene, secrets, schema compatibility, drift checks, and evidence events | Bazel affected targets, Buf, pre-commit, admitted secret scanner | Full merged result remains authoritative; root/Bazel/local/hosted interfaces must agree | B01-B04 |
| B06 | Authenticated remote cache/execution, deterministic sharding, flake controls, and resource budgets | Bazel remote cache/execution service selected by ADR | Isolate namespaces and trust; pass poisoning tests; retain verified local fallback | B05 |
| B07 | Dependency admission covering source, digest, lock, license, vulnerabilities, exploitability, maintenance, platforms, wheels/native code, registry, patch/EOL, and runtime-install prohibition | pip-audit 2.10.1; OpenSSF Scorecard | Signals only; migrate provisional B02-B06 records; repository owns admission and exploitability decision | B02-B06 |
| B08 | Whole-artifact SBOM, provenance, signatures, attestations, immutable publication, and consumer verification | Syft; Cosign | Include native/shared libraries, toolchain and lock identity; verify digest and policy at consumption | B07, A07 |

**Wave evidence:** clean sandboxed local/CI builds have identical digests,
undeclared inputs fail, affected-target selection matches full builds, flaky tests
cannot pass silently, locks are complete, and unsigned or mutable artifacts are
rejected.

## Wave C - Canonical multi-asset contracts

| ID | Objective / delivery | Library/tool to use or incorporate | Incorporation boundary / restriction | Depends on |
| --- | --- | --- | --- | --- |
| C01 | Stable instrument identity and temporal symbology mappings with retained auditable fixtures | Hypothesis 6.167 | Provider symbols terminate at adapters; canonical IDs and invariants are owned | B01-B05 |
| C02 | Venue, session, calendar, market-status, and timezone contracts | `exchange_calendars` 4.13.2 | Versioned source/override adapter and pinned fixtures; never live authority | C01 |
| C03 | Typed units, currencies, prices, quantities, and conventions | QuantLib 1.40 | Explicit day-count/convention adapters and evaluation context; no ambient global state | C01-C02 |
| C04 | Event, receipt, ingestion, knowledge, valid-time, sequence, and bitemporal model | — | Repository-owned thin-waist contract | C01-C03 |
| C05 | Versioned market, reference, and lifecycle event schemas plus analytical representations | Protobuf, Buf, PyArrow 25.0.1 | Translate generated and Arrow types into owned domain types | C01-C04 |
| C06 | Idempotent order, execution, and fill state machines with explicit invalid transitions | Hypothesis 6.167 | Property/state-machine tests; no framework-owned order model | C01-C05 |
| C07 | Position, cash, PnL, exposure, and limit schemas | — | Repository-owned accounting and risk contracts | C03, C05-C06 |
| C08 | Schema registry, compatibility, fixtures, generated-client digests, migration windows, deprecation, inventory, and rollback | Buf | Repository owns schema policy, golden/differential fixtures, and migration approval | C01-C07 |

**Wave evidence:** lifecycle ambiguity, symbol reuse, unit errors, host-local time,
future knowledge, invalid transitions, accounting-sign errors, and unsupported
schema changes are caught by golden, property, compatibility, and replay tests.

## Wave D - Point-in-time data platform

| ID | Objective / delivery | Library/tool to use or incorporate | Incorporation boundary / restriction | Depends on |
| --- | --- | --- | --- | --- |
| D01 | Immutable entitled raw landing with checksums, retention, and encryption | Object store/catalog selected by ADR | Repository owns dataset identity, entitlements, retention, and integrity policy | B08, C04 |
| D02 | Connector SDK with checkpoints, backpressure, idempotency, dead letters, and replay | Official Databento/Alpaca SDKs; evaluate Temporal Python 1.32 | Provider types stay adapter-local; Temporal is control-plane recovery only, never event transport/hot path | D01, C05 |
| D03 | Deterministic canonical normalization and cross-source reconciliation | PyArrow 25.0.1, Polars 1.44.1, DuckDB 1.5.5, Pandera 0.33 | Measure execution; Pandera validates boundaries but owns no canonical schema, PIT, or publication | D01-D02, C08 |
| D04 | Temporal reference/master data, priority rules, full knowledge/valid-time history, overrides, and source evidence | `exchange_calendars` 4.13.2; official provider SDKs | All mappings and calendars sit behind versioned owned adapters | C01-C05, D03 |
| D05 | Data-quality checks, publication policy, quarantine/degrade/stop behavior, SLOs, and runbooks | Pandera 0.33; evaluate Great Expectations 1.21 | GX only for a measured analyst/SQL documentation gap; one authoritative owner per check | D02-D04 |
| D06 | PIT datasets, as-of joins, universe history, corrections, snapshots, and reproducible manifests | PyArrow/Parquet, Polars, DuckDB, PyIceberg 0.11.1; defer Ibis | Repository owns PIT/order/precision semantics; Ibis only after multiple remote engines justify it | C04, D03-D05 |
| D07 | Lineage, catalog, entitlements, usage/cost accounting, and retention | OpenLineage 1.52; evaluate Dagster 1.13.20 | Canonical run/dataset IDs and authorization remain owned | D01-D06, A06 |
| D08 | Replay, corrections, impact-aware backfills, and reconciliation | Dagster 1.13.20; evaluate Temporal Python 1.32 | Neither tool owns the event log, correction model, or idempotency keys | D06-D07 |

**Wave evidence:** immutable source integrity, recoverable connector faults,
source-to-canonical lineage, no private symbol maps, quality-triggered
quarantine/degrade/stop, adversarial leakage rejection, reproducible snapshot
digests, entitlement propagation, and idempotent impact-aware correction.

## Wave E - Research and model platform

| ID | Objective / delivery | Library/tool to use or incorporate | Incorporation boundary / restriction | Depends on |
| --- | --- | --- | --- | --- |
| E01 | Research SDK and explicit runtime context over immutable PIT snapshot manifests | PyArrow 25.0.1, Polars 1.44.1 | Arrow-native boundaries only; no global/workstation state or direct provider/framework dependency | B01-B08, C01-C08, D06 |
| E02 | Immutable experiment record and committed append-only trial ledger | MLflow 3.15.2; Optuna 4.9 | MLflow indexes/displays and Optuna proposes bounded trials; neither mutates identity, erases trials, or promotes | E01, A06 |
| E03 | Versioned dataset, feature, label, transformation, and universe APIs | PyArrow/Parquet; Pandera 0.33 | Repository owns fingerprints, transformations, PIT semantics, and lineage | D06-D08, E01-E02 |
| E04 | Time-series splits, purging, embargo, walk-forward, nested selection, final-OOS lock, and leakage attacks | Hypothesis 6.167; scikit-learn 1.9; skfolio 1.0.1 reference-only | Repository owns split/leakage semantics; skfolio requires conformance before bounded use | E03 |
| E05 | Baseline, model, calibration, ensemble, serialization, and inference adapters | scikit-learn 1.9; statsmodels 0.15 | Use admitted formats; library registry stages are not approval | E03-E04 |
| E06 | Robustness, ablation, DSR/PBO/FDR, and multiple-testing controls | statsmodels 0.15; arch 8.0; skfolio reference-only | Repository owns formulas, dependence assumptions, trial counts, and conclusions | E02-E05 |
| E07 | Reproducible local/cluster/cloud-HPC runner with quotas, resume, cache, and cost | Dagster 1.13.20; Optuna 4.9 | Committed suggestions/seeds and trial ledger remain authoritative | E01-E06, B06 |
| E08 | Model registry, immutable report, promotion card, and independent validation | MLflow 3.15.2; Evidently 0.7.21 | Adapter/UI and advisory reports only; no promotion, capital, limit, or kill authority | E02-E07, B08 |

**Wave evidence:** notebook, batch, and CI semantics agree; trial deletion is
prevented; offline features reproduce; split/leakage attacks pass; declared
baselines remain; uncertainty is dependence-aware and trial-adjusted; distributed
runs are bounded/restartable; no promotion card has mutable or missing evidence.

## Wave F - Deterministic simulation

| ID | Objective / delivery | Library/tool to use or incorporate | Incorporation boundary / restriction | Depends on |
| --- | --- | --- | --- | --- |
| F01 | Owned deterministic event-driven simulator and extensible asset/venue contracts | Time-boxed NautilusTrader 1.231 differential spike | Start after C contracts and initial goldens; define adoption/rejection and exit criteria | C01-C08, D08, E01 |
| F02 | Injected clocks, named random streams, checkpoints, state, and causality guards | Hypothesis 6.167 | State-machine/metamorphic tests with retained minimal counterexamples | F01, C04 |
| F03 | Accounting, corporate action, expiry, roll, settlement, and FX engine | QuantLib 1.40 | Explicit context and golden reconciliation; never canonical accounting state | F01-F02, C07, D04 |
| F04 | Market-state/order-book simulator for sessions, auctions, limits, and bad books | — | Repository owns ordering and venue semantics | F01-F03, D03-D05 |
| F05 | OMS, fill, queue, execution, outage, bust/correct, and drop-copy simulator | — | Repository owns order/execution state and recovery | C06, F04 |
| F06 | Spread, fee, impact, borrow, funding, margin, and capacity models | — | Calibrated owned models with conservative uncertainty bands | F03-F05, D07 |
| F07 | Multi-venue latency, failure, regime, degradation, and counterfactual scenarios | — | Repository owns scenario catalog and deterministic replay | F04-F06 |
| F08 | Research/simulation/paper/live parity, golden strategies, and performance budgets | NautilusTrader differential; VectorBT 1.1 restricted | Identical owned traces before reuse; VectorBT is exploration/reference-only and cannot certify parity | F01-F07 |

**Wave evidence:** event ordering and randomness are reproducible, checkpointed
runs equal uninterrupted runs, future access hard-fails, accounting reconciles,
fill/cost models are calibrated with conservative bands, scenario catalogs cover
normal/stressed/pathological states, and unexplained parity deltas block progress.

## Wave G - Portfolio and independent risk

| ID | Objective / delivery | Library/tool to use or incorporate | Incorporation boundary / restriction | Depends on |
| --- | --- | --- | --- | --- |
| G01 | Signal-to-target API separating forecast, portfolio, and execution policy | — | Repository-owned stage interfaces | E05, F08, C07 |
| G02 | Authoritative intraday position, cash, pending-order, inventory, and exposure service | — | Runtime service is authoritative and independently reconcilable | C07, F03, G01 |
| G03 | Versioned risk-model, covariance, scenario, liquidity, and quality interfaces | skfolio 1.0.1 reference-only | Research/conformance only until estimates match independent owned results | G02, E06 |
| G04 | Optimizer/constraint library with complete solver diagnostics and fallback | CVXPY 1.9.2; cvxportfolio 1.5.1 reference-only | Owned protocol records solver/version/tolerances/status/residuals and reconciles limits | G01-G03, F06 |
| G05 | External fail-closed pre-trade risk gateway | — | Risk remains independent of strategy/optimizer/runtime | C06-C07, G02-G04 |
| G06 | Hierarchical limits, stress, drawdown, liquidity, margin, and collateral | — | Repository-owned risk policy and reconciliation | G03-G05 |
| G07 | Independent global/strategy/asset/venue/account/instrument kills and degraded modes | — | External fail-safe control and independent authority | G05-G06, H04 |
| G08 | Independent risk/PnL/control recomputation, breaks, sign-off, and evidence retention | — | Independent implementation and approval | G02-G07, F06 |

**Wave evidence:** stage substitution is possible, authoritative state reconciles,
risk numerics and optimizer behavior are explainable, unavailable risk fails safe,
limits reconcile across accounts, kill paths work during process/data failure, and
material breaks block scale-up.

## Wave H - Trading runtime and connectivity

| ID | Objective / delivery | Library/tool to use or incorporate | Incorporation boundary / restriction | Depends on |
| --- | --- | --- | --- | --- |
| H01 | Shared typed deterministic strategy kernel for research through live | — | No simulator, dataframe, provider, orchestrator, or registry type crosses the interface | E01, G01, F08 |
| H02 | Live runtime, scheduling, dependency injection, readiness, health, and resource limits | — | Repository-owned composition and runtime contracts | H01, B08, I01-I04 |
| H03 | Durable state, checkpoint/replay, idempotency, duplicate suppression, and fencing | Evaluate Temporal Python 1.32 | Recovery workflows only; never dispatcher, simulator clock, hot path, or authoritative state/log | H02, C06 |
| H04 | Production OMS lifecycle, drop-copy comparison, aging, and audited operator controls | — | Repository owns OMS state and controls | C06, H03, G05 |
| H05 | FIX/native session SDK, time sync, throttles, recovery, and conformance | Native FIX/venue libraries selected by ADR; CCXT restricted | CCXT is discovery/prototype-fixture only and defines no production semantics | H04, C08 |
| H06 | One production-grade venue adapter with independent drop copy and reconciliation | Official provider/native SDK | SDK stays behind adapter; CCXT cannot satisfy certification | H05, D02, G08 |
| H07 | Paper broker and shadow router with executable-message suppression | Admitted NautilusTrader component, if any | Same owned kernel/risk/OMS contracts and differential suite | H01-H06, J01-J03 |
| H08 | Bounded canary/live activation certification and dual-control enablement | — | No library grants activation or capital authority | H07, G07, I01-K08 |

**Wave evidence:** the same kernel runs in every mode; incompatible startup fails;
restart cannot duplicate orders; all OMS/session/venue anomalies reconcile;
secrets stay external; shadow cannot emit executable messages; activation cannot
exceed the signed envelope and rolls back safely.

## Wave I - Immutable deployment and recovery

| ID | Objective / delivery | Library/tool to use or incorporate | Incorporation boundary / restriction | Depends on |
| --- | --- | --- | --- | --- |
| I01 | Signed release manifest and immutable artifact registry | Cosign-verified B08 artifacts | Registry cannot replace consumer-side digest/policy verification | B08, E08, C08 |
| I02 | Environment separation and one-way promotion | — | No rebuild between dev, CI, replay, staging, paper, shadow, canary, and production | I01, A04 |
| I03 | Typed configuration, secret references, staged flags, expiry, and resolved non-secret digests | pydantic-settings 2.15 | ADR-0008 boundary; configuration models cannot enter economic/trading domain types | I01-I02, C08 |
| I04 | Short-lived service identities, secrets, privileged control plane, and break glass | Identity/secret services selected by ADR | External secret authority; no long-lived production credentials | A07, B08, I02 |
| I05 | GitOps deployment lane for standard services | GitOps controller selected by ADR | Signed immutable inputs and one-way promotion remain authoritative | I01-I04, H02 |
| I06 | Immutable bare-metal low-latency lane with host/clock attestation | Host tooling selected by ADR | No mutable in-place production build or unverified clock state | I01-I04, H02, H05 |
| I07 | Progressive rollout, schema/state migration, and multidimensional rollback | Evaluate Temporal Python 1.32 | Control-plane steps only after history/compatibility/rollback conformance | I05-I06, C08 |
| I08 | Tiered backup, verified restore, DR, failover, and break-glass exercises | Evaluate Temporal Python 1.32 | Workflow is evidence-producing coordination, never backup/state authority | I01-I07, G07 |

**Wave evidence:** manifests reject mutable/incomplete state, no stage rebuilds,
config drift/unknown values fail, no static production secret exists, only signed
artifacts deploy, host/clock drift blocks low-latency activation, mixed-version and
failed migrations recover, and RTO/RPO restores are verified.

## Wave J - Observability, SLOs, and incident control

| ID | Objective / delivery | Library/tool to use or incorporate | Incorporation boundary / restriction | Depends on |
| --- | --- | --- | --- | --- |
| J01 | Trace/metric substrate with controlled exporters plus owned log/audit integration and retention | OpenTelemetry Python 1.44 API/SDK | Libraries use APIs; composition roots own SDK/exporters; hot paths stay bounded/non-blocking | B01, H02, I01 |
| J02 | Stable metric/log/trace names, units, cardinality, clock skew, sensitive data, propagation, sampling, and release correlation | OpenTelemetry semantic conventions | Conventions are inputs; repository owns telemetry contract | J01, C03-C04 |
| J03 | Tiered SLIs/SLOs, error budgets, burn alerts, and release freeze policy | — | Repository-owned operational policy | J01-J02, A03-A04 |
| J04 | Data freshness, quality, lineage, entitlement, PIT, and clock monitors | — | Monitors evidence owned D/J contracts | D05-D08, J01-J03 |
| J05 | Feature/model/strategy/regime drift, calibration, and state monitoring | Evidently 0.7.21 | Advisory reports only; no promotion, capital, limit, retraining, or independent kill authority | E08, H01, J01-J04 |
| J06 | Execution quality, TCA, capacity, and full PnL attribution | — | Independent owned calculations and reconciliation | F06, H06, G08, J01-J05 |
| J07 | Alert routing, runbooks, immutable audit stream, and operator UX | — | No dashboard state substitutes for evidence or authority | J03-J06, A06 |
| J08 | Synthetic probes, game days, incident response, and postmortem-to-test loop | — | Repository owns scenarios, evidence, and closure | J04-J07, I08, G07 |

**Wave evidence:** every release/strategy/account/asset/venue/order/incident
correlates end to end; cardinality is bounded; SLOs reflect trading impact; stale
data changes control state; model monitoring avoids noisy-PnL auto-actions;
simulated/realized costs reconcile; alerts reach owners; game days close corrective
actions with tests.

## Wave K - Security, access, model risk, and audit

| ID | Objective / delivery | Library/tool to use or incorporate | Incorporation boundary / restriction | Depends on |
| --- | --- | --- | --- | --- |
| K01 | RBAC, JIT access, separation of duties, session recording, and two-person control | Access platform selected by ADR | Independent identity and approval evidence required | A03-A07, I04 |
| K02 | Research/data/control/trading/risk/management segmentation and egress | Network-policy tooling selected by ADR | Default-deny owned policy and target-environment evidence | K01, I05-I06 |
| K03 | Reviewed-source, hermetic-build, provenance, whole-artifact SBOM, signatures, attestations, and consumer verification | Syft; Cosign | Enforce B07-B08 policy and include native/shared libraries | B07-B08, I01 |
| K04 | Encryption, secrets/keys, rotation, revocation, ownership, and backup-key controls | KMS/secret platform selected by ADR | Independent authority and tested recovery/revocation | I04, K01-K03 |
| K05 | Vulnerability, license, exploitability, patch, and end-of-life operations | pip-audit 2.10.1; OpenSSF Scorecard | Signals only; no substitute for native inventory, license disposition, exploitability, provenance, or admission | B07, K03 |
| K06 | Data entitlement, privacy, geographic/user restriction, retention/deletion controls | — | Repository policy plus qualified applicability and target enforcement | D01, D07, K01 |
| K07 | Model materiality, inventory, independent validation, findings, monitoring, and retirement | — | Independent model-risk authority | E08, J05, A06 |
| K08 | Compliance evidence mapping, control tests, retention, and audit reconstruction | — | Qualified applicability and immutable reconstructable evidence | A07, K01-K07, J07 |

**Wave evidence:** production is read-only by default; network policy isolation is
tested; tampered artifacts fail; key rotation stays within budget; critical
exposures and license obligations have owned dispositions; entitlements propagate
through lineage; material models cannot self-validate; a release reconstructs from
hypothesis through orders and rollback.

## Wave L - Asset and strategy certification

| ID | Objective / delivery | Library/tool to use or incorporate | Incorporation boundary / restriction | Depends on |
| --- | --- | --- | --- | --- |
| L01 | Cash-equities certification | `exchange_calendars` adapter, if admitted | Independent asset-specific golden, stress, paper, shadow, and canary evidence | C01-K08 |
| L02 | Futures certification | `exchange_calendars` adapter, if admitted | Independent lifecycle, roll, margin, and reconciliation evidence | C01-K08 |
| L03 | Listed-options and volatility certification | QuantLib adapter, if admitted | Explicit context and independent golden valuation/reconciliation | C01-K08 |
| L04 | FX, rates, and credit certification | QuantLib and calendar adapters, if admitted | Independent conventions, lifecycle, valuation, and reconciliation | C01-K08 |
| L05 | Optional separately governed digital-assets certification | Official provider/venue SDKs; CCXT and VectorBT restricted | Entitled adapter/conformance evidence; CCXT and VectorBT remain non-production | C01-K08 |
| L06 | Cross-sectional, time-series, and statistical-arbitrage templates | Admitted E-G components only | Strategy manifest and independent promotion evidence remain authoritative | E01-K08; any of L01, L02, L04 |
| L07 | Market-making, execution, and volatility-strategy templates | Admitted F-H components only | External risk, kill, OMS, and activation authority remain independent | F01-K08; any of L01-L04 |
| L08 | Institutional-readiness review and controlled capital scale-up | — | No critical finding; signed independent review before every increase | L01-L07 |

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

Repository-local implementations and deterministic checks now exist for A01-A08.
Each remains `partial` on the solo-bootstrap track: all locally resolvable controls
through A08 pass, while their recorded organization, protected-forge,
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
