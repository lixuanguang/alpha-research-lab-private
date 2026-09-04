# Quality, Operations, and Governance

## Purpose and authority

This document defines the evidence required to review, build, operate, promote,
recover, and retire platform capabilities and strategies. It implements the
[blueprint's](../../Institutional_Multi_Asset_Quant_Monorepo_Blueprint.pdf)
service tiers, change classes, QG01-QG15 catalog, promotion controls, and
definition of done. A score or favorable PnL cannot compensate for a failed
mandatory control.

For solo implementation, the
[current operating policy](../governance/domain-ownership.md#current-operating-policy)
supersedes organizational approval prerequisites in this catalog. Technical
requirements still apply to the capability being implemented. Human review and
target-operation acceptance remain separate from engineering completion.

## Service criticality

| Tier | Examples | Minimum posture |
| --- | --- | --- |
| T0 | Pre-trade risk, OMS, kill switches, venue sessions, authoritative positions | Independent control path, fail-closed defaults, deterministic recovery, active on-call, game days, strict changes |
| T1 | Live strategy runtime, market data, feature serving, model service, deployment control | Tight SLOs, shadow/canary, state recovery, release identity, data/model monitoring |
| T2 | Batch research, simulation clusters, catalog, experiment services | Reproducible jobs, quotas, restore, lineage, quality monitoring; availability may be lower than T0/T1 |
| T3 | Documentation, examples, offline utilities | Version control, ownership, and impact-appropriate tests |

Every service, dataset, strategy, model, control, and change records its owner,
criticality, dependencies, and evidence-retention class.

## Merge-request governance

### Risk classes

| Class | Typical change | Required review and rollout |
| --- | --- | --- |
| R0 | Documentation or non-functional metadata | One Code Owner; automated checks; fast lane |
| R1 | Research-only code with no shared-data or production dependency | Research owner plus peer; reproducible batch test; no production promotion |
| R2 | Shared library, schema, dataset, feature, or model candidate | Code Owner plus independent domain/data/model reviewer; merged-result, compatibility, replay, and impact evidence |
| R3 | Paper/shadow runtime, deployment tooling, non-capital production service | Code Owner plus platform/SRE and security as applicable; staging, failure injection, shadow or synthetic validation |
| R4 | Capital-at-risk strategy, OMS, risk, venue, limits, production access, or kill switch | Domain owner, independent risk/model validation, platform/SRE, security/compliance as applicable, dual-control activation; full certification and bounded canary |

Risk classification considers capital at risk, blast radius, data/model
materiality, security privilege, and reversibility. It must be deterministic and
policy-enforced; authors cannot lower a class to avoid gates.

### Definition of Ready

Implementation starts only when the MR has:

- A linked roadmap item or issue, owner, risk class, and impacted systems.
- Explicit scope and non-goals.
- An ADR accepted by the founder for cross-cutting solo implementation, or the
  applicable institutional decision for an institutional operation.
- Data, model, schema, security, entitlement, regulatory, and model-risk impact
  analysis as applicable.
- Test and benchmark plans with acceptance thresholds.
- Migration, rollout, rollback, monitoring, and runbook plans.
- Available technical dependencies. Unstaffed review roles do not prevent
  implementation; active scoped hires create a separate handover requirement.

### Required MR shape

Prefer one logical behavior change with tests and evidence. Keep non-generated
changes near or below 400 lines where practical. Larger work needs a split plan,
a generated-code explanation, or an explicitly approved indivisible-migration
rationale. Do not combine broad refactoring, schema migration, model change, and
production activation unless their coordinated sequence is itself the reviewed
change.

### Quality gate catalog

| Gate | Control objective | Representative blocking evidence |
| --- | --- | --- |
| QG01 | Source hygiene | Format, lint, types, warnings-as-errors, forbidden APIs; suppressions have owner and expiry |
| QG02 | Hermeticity/reproducibility | Pinned/sandboxed build, deterministic generation, digest comparison, provenance |
| QG03 | Functional correctness | Unit, contract, state-machine, serialization, boundary, and error-path tests on affected and merged result |
| QG04 | Property/numerical correctness | Invariants, metamorphic/perturbation tests, NaN/Inf policy, conditioning, numeric tolerance report |
| QG05 | Schema/data/PIT integrity | Compatibility, freshness, completeness, uniqueness, causal as-of, universe, revision, lineage, dataset fingerprint |
| QG06 | Research/model validity | Registered metrics/baselines, nested time splits, trial ledger, multiple-testing controls, ablations, stability, independent report |
| QG07 | Costs/capacity | Calibrated spread, fees, impact, latency, borrow/funding, liquidity, participation, and stress sensitivity |
| QG08 | Portfolio/risk controls | Exposure, limit, stress, margin, concentration, liquidity, fallback tests, and independent risk approval |
| QG09 | Integration/scenario | Replay, OMS/venue, disconnect, duplicate, gap, bust/correct, reconciliation, paper/shadow trace matrix |
| QG10 | Performance | Signed tail-latency, throughput, jitter, memory, CPU/allocation, startup/recovery, and query budgets |
| QG11 | Resilience | Crash/restart, backpressure, failover, degraded mode, backup/restore, chaos, clock/data failure, RTO/RPO evidence |
| QG12 | Security/supply chain | SAST, secrets, dependencies, vulnerabilities, licenses, SBOM, signature, provenance, IAM, network; no unaccepted critical finding |
| QG13 | Documentation/governance | ADRs, APIs, examples, model card, runbook, control mapping, ownership, valid links and checked examples |
| QG14 | Observability/SLO | Metrics, logs, traces, audit, dashboards, alerts, cardinality, SLO, owner, and synthetic alert evidence |
| QG15 | Deployment/promotion | Staging/merged result, paper, shadow, canary, rollout/rollback, activation envelope, signed release manifest, post-deploy validation |

### Institutional gates and approvers

| Class | Mandatory gates | Minimum approvers |
| --- | --- | --- |
| R0 | QG01, QG13 | One Code Owner |
| R1 | QG01-QG06, QG13; QG10 when computationally material | Research owner plus peer |
| R2 | QG01-QG06, QG09-QG14; QG07-QG08 when economically/risk relevant | Code Owner plus independent data/model/domain reviewer |
| R3 | QG01-QG05, QG09-QG15; QG06-QG08 when model/trading relevant | Code Owner, platform/SRE, security as applicable |
| R4 | QG01-QG15 | Domain owner, independent risk/model validation, platform/SRE, security/compliance as applicable; dual control for activation |

Applicability is evidence, not discretion to ignore a required gate. When a gate
is conditionally applicable, the MR records the rationale.

### Waivers

A waiver records a unique ID, failed gate, rationale, affected release and scope,
compensating controls, owner, approvers, expiry, and remediation MR. It appears in
the release manifest and monitoring. Indefinite waivers are prohibited. Causal
integrity, immutable artifact identity, independent hard risk, and kill capability
cannot be waived for live capital.

## Test and evidence strategy

### Unit, contract, and integration tests

- Unit tests cover identifiers, units, timestamp validation, parsers, numerical
  behavior, features, models, risk, optimizers, order/accounting invariants,
  idempotency, and safe fallbacks without live networks or uncontrolled clocks.
- Every replaceable boundary has a reusable contract suite. Cross-language
  implementations use the same fixtures and differential tests.
- Integration workflows include raw landing through canonical publication and
  lineage; PIT dataset through model artifact; forecast through portfolio, risk,
  orders, fills, ledger, and report; release through replay/paper/shadow; and data
  correction through impact, invalidation, and idempotent rebuild.

### Golden, property, numerical, and adversarial tests

Small human-auditable fixtures cover event normalization, lifecycle, accounting,
order states, replay parity, and cross-language schemas/ABI. Property,
metamorphic, fuzz, and leakage tests cover at least:

- Future-data perturbations cannot change earlier features, membership, fits, or
  decisions.
- Retries and duplicate event IDs cannot duplicate economic state.
- Accounting conservation, unit/sign conventions, and currency translation hold.
- Terminal orders cannot transition again; delayed/out-of-order messages are
  deterministic.
- Equivalent representations and limiting cases produce equivalent results within
  declared tolerances.
- Unsafe symbol, revision, lifecycle, stale-data, queue/fill, and cost assumptions
  fail dedicated attack fixtures.

### Performance and resilience

Benchmarks record workload, data/event size, instruments, toolchain, artifact
digest, hardware, runtime, tail distribution, CPU, allocations, memory, jitter,
and recovery. Latency gates run on controlled hosts; shared-CI timings are
diagnostic. Optimization never waives correctness, sanitizer, conformance,
security, recovery, or risk evidence.

Resilience tests inject crash/restart, duplicate and missing messages,
backpressure, split brain, venue/data loss, clock degradation, partial migration,
backup/restore, and failover. Every tier has owned RTO and RPO targets, and restore
is verified rather than inferred from backup completion.

## State authority, failure, and reconciliation

- Ingestion, publication, scheduling, order submission, reconciliation, and
  reporting use stable idempotency keys.
- Canonical events with fixed release/configuration replay to the same state.
- Corrections, cancels, rejects, busts, and errors are explicit events.
- Each workflow identifies the authoritative log, ledger, position source,
  manifest, checkpoint, fencing mechanism, and recovery owner.
- T0 recovery reconciles venue, broker, drop-copy, clearing, position, cash, and
  order records before reactivation.

For missing/stale data, unavailable metadata or limits, schema mismatch, storage
failure, model load failure, infeasibility, venue rejection, incomplete fills, or
reconciliation breach, an application may fail closed, pause with state, enter a
bounded visible degraded/hedge-only mode, use a registered conservative fallback,
or flatten through an authorized process. Silent continuation is prohibited.

## Deployment, activation, and promotion

### Release manifest

A signed immutable release manifest contains repository/MR identity, build
platform and provenance, dependency lock, SBOM, signature and artifact digest;
model, feature graph, data snapshot, schemas, random-state policy and validation;
configuration and limit digests; environment, account, venue, asset, universe,
capital and schedule; service compatibility; evidence, dashboards, alerts,
runbooks, rollback, kill procedure, waivers, and approvals.

Build once and promote by digest. Production never deploys a mutable tag or a
workstation artifact. Every running process reports release identity in decisions,
risk decisions, orders, fills, audit events, and telemetry.

### Promotion state machine

```text
research -> deterministic replay -> certification -> paper -> shadow
                                                        |
                                                        v
                                                   bounded canary
                                                        |
                                                        v
                                                    production

any technical/control breach -> disabled or rolled back -> re-certification
```

Capital exposure increases only with progressively stronger evidence. Paper
exercises the full order lifecycle without capital. Shadow consumes live data but
suppresses executable messages. Canary limits capital, instruments, venues,
schedule, order size, participation, or strategy allocation to a signed envelope.

Deployment and activation are distinct. Rollout begins with replay and synthetic
probes, then paper, shadow, bounded canary, and approved production. Guardrails
connect to automatic disable or operator escalation.

Rollback includes binary, model, feature graph, configuration, limits, schema
compatibility, and state. An old binary that cannot read current state is not a
rollback. Migrations use expand-migrate-contract, dual-read/write where needed,
and explicit compatibility windows.

## Observability, SLOs, and incidents

### Monitoring planes

| Plane | Signals | Control actions |
| --- | --- | --- |
| Platform | Availability, errors, tail latency, throughput, saturation, queue, memory, clock, recovery | Restart, failover, add capacity, rollback, shift traffic |
| Data | Freshness, gaps, duplicates, schema, revisions, PIT, entitlements, cross-source breaks | Quarantine, source failover, stale mode, stop affected strategies, backfill |
| Feature/model | Missingness, drift, calibration, residuals, score distribution, inference latency, state divergence | Review, conservative fallback, reduce scope, disable, controlled retraining |
| Trading/execution | Decision/order rate, rejects, cancels, fills, slippage, queue, adverse selection, venue health | Throttle, reroute, cancel, hedge-only, venue/strategy kill |
| Risk | Positions, exposure, limit use, stress, margin, liquidity, drawdown, reconciliation | Block new risk, reduce, hedge, kill, escalate |
| Economic | Gross/net PnL, alpha capture, spread, fees, impact, timing, funding, borrow, hedge/FX residual, capacity decay | Recalibrate, update costs, reduce allocation, retire |

Telemetry correlates release, strategy, model, config, data snapshot, account,
asset, venue, order, environment, host, and incident. Stable names and units are
mandatory; unbounded identifiers stay out of metric labels. Hot-path telemetry is
bounded and non-blocking, and dropped telemetry is itself monitored.

SLOs are tier-, strategy-horizon-, and economic-impact-specific. They cover
availability, latency, freshness, correctness, recovery, and durability and use
multi-window error-budget burn rather than unrealistic 100-percent targets.

TCA/PnL decomposes at least signal, spread, fees, impact, timing, funding, borrow,
hedge, FX, and reconciliation residual by release, strategy, model, asset, venue,
account, and order cohort. Simulated-versus-realized gaps feed cost models,
capacity limits, and research conclusions.

Every actionable alert has severity, owner, control/SLO, threshold rationale,
deduplication key, runbook, safe action, escalation, and closure evidence. Alerts
without an owner or action remain dashboards, not pages.

Incidents follow detect, contain, preserve evidence, reconcile, communicate,
recover, verify, and learn. Postmortems record exact release/data/state/control
behavior, economic impact, contributing factors, and why tests or alerts failed;
corrective actions add automated tests or controls, not only prose.

## Security, access, and model risk

- Pinned dependencies, hermetic hosted builds, signed provenance,
  SPDX-compatible SBOMs, digest deployment, policy verification, protected source,
  and independent review are the minimum supply-chain posture.
- Human production access is read-only by default. Write/activation access is
  just-in-time, time-bounded, strongly authenticated, authorized, logged, and
  dual-controlled for material actions.
- Workload identities are specific and short-lived. Research credentials cannot
  place orders; strategies cannot modify their limits; secrets never enter source,
  images, manifests, deterministic identity, or logs.
- Networks separate research, data, control, trading, risk, and management paths;
  exceptions for low latency are documented and compensated.
- Model materiality reflects exposure, purpose, complexity, interconnectedness,
  and change sensitivity. Validation is proportionate but independent and covers
  conceptual soundness, data, implementation, outcomes, limitations, sensitivity,
  benchmarks, OOS/OOT, monitoring, change control, and retirement.
- Legal and regulatory mappings are jurisdiction-specific and reviewed by the
  relevant functions; documentation examples are not legal advice.

## Independent review and definition of done

An independent reviewer must be able to reconstruct the path from hypothesis and
trial ledger through data, code, build, model, simulation, risk, approvals,
deployment, decisions, orders, incidents, rollback, and retirement without private
workstation state.

Implementation is done when its declared repository-local behavior, applicable
technical tests, compatibility and documentation pass, no technical finding
remains, and the founder accepts the work. The program registry records this as
`implementation_status = complete`. Governance is `not_required` until a relevant
hire joins, then `pending` for scoped handover. Neither state grants release or
activation authority. A failing local check or technical prerequisite blocks
completion regardless of team size.

Institutional acceptance and operation additionally require these applicable conditions:

- Code and tests merge through the required affected-target and merged-result
  pipelines with mandatory approvals.
- Contracts, types, units, timestamps, lifecycle, owners, consumers, and
  compatibility are documented.
- Functional, property/numerical, PIT, research, cost, risk, scenario, performance,
  resilience, security, documentation, observability, and deployment evidence
  required by its class passes.
- Immutable artifact and release identity are available; evidence is retained.
- Migration, rollout, rollback, stop/kill, degradation, and recovery are tested.
- Monitoring is active, post-deploy checks pass, and temporary flags, migrations,
  waivers, and limitations have owners and removal or expiry dates.
- Runbooks, model cards, control maps, and operator documentation are current.

A merged MR is not automatically a release. A deployed artifact is not
automatically activated. A backtest or weighted score is never a substitute for a
hard gate, and repository implementation does not itself authorize capital.
