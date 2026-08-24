# Quality, Operations, and Governance

## Purpose

This document defines the evidence required to trust, operate, promote, recover,
and retire platform capabilities and research candidates. It complements the
[monorepo architecture](README.md) and [platform contracts](contracts.md).

## Test strategy

### Unit tests

Unit tests cover pure behavior and local failure semantics, including:

- Identifier, unit, currency, sign, precision, and timestamp validation.
- Parser boundaries, schema mismatches, missing/non-finite values, and empty input.
- Feature, label, model, risk, optimizer, execution, and accounting invariants.
- Retry, idempotency, state transition, and registered fallback behavior.

Unit tests are deterministic and do not use live networks, credentials, user
directories, wall-clock time, or uncontrolled randomness.

### Contract tests

Every replaceable boundary has a reusable suite. Examples include connectors,
storage, dataset readers, models, valuation, risk, optimizers, cost models,
execution gateways, artifact stores, and cross-language bindings.

A second implementation is not accepted before the common contract suite exists.
Cross-language implementations use identical fixtures and differential tests.

### Integration tests

Bounded workflows cover:

- Source fixture → bronze → normalization → silver → quality/lineage.
- Dataset → features → model → forecast artifact.
- Forecast → risk/portfolio → target → orders → fills → ledger → report.
- Candidate artifact → historical replay → paper gateway → reconciliation.
- Data correction → lineage impact → invalidation → rebuild.

External systems use deterministic fakes, local processes, containers, or recorded
responses as appropriate. Live smoke tests are bounded, non-destructive, separately
labeled, and never required for ordinary unit execution.

### Golden tests

Small human-auditable fixtures establish exact reference behavior for:

- Event normalization and time availability.
- Funding, fees, fills, cash, position, and P&L identities.
- Lifecycle and settlement once an asset class is implemented.
- Vectorized/event replay parity under aligned assumptions.
- Cross-language schema/ABI behavior.

Golden updates include the reason, generator or calculation, reviewer, and expected
semantic change. Snapshot churn is not evidence of correctness.

### Property, metamorphic, fuzz, and security tests

Use broad-input testing for parsers, serialization, state machines, numerical
invariants, and unsafe boundaries. Important properties include:

- Perturbing future data cannot alter earlier features, membership, fits, or
  decisions.
- Reordering independent events does not change economic state.
- Retrying an idempotent operation cannot duplicate economic state.
- Equivalent currency representations produce equivalent base-currency NAV.
- Accounting identities hold across generated fill/cashflow sequences.
- Analytic sensitivities approach finite-difference values as shock size shrinks.
- A one-period dynamic optimizer matches the equivalent static formulation.

### Performance tests

Correctness gates pass before performance work. Benchmarks record workload,
dataset/event size, instruments, toolchain, artifact digest, hardware, runtime,
latency distribution, and peak memory.

Latency regression gates run on controlled hardware with pinned CPU, NUMA, power,
and background-load policy. Shared CI timings are diagnostic only. An optimization
preserves golden results or declares and justifies a numerical difference.

## Idempotency, replay, and state authority

- Ingestion, publication, scheduling, order submission, reconciliation, and
  reporting use stable idempotency keys.
- Interrupted work resumes from recorded state or restarts safely.
- Replaying canonical events with fixed artifacts and configuration produces the
  same state.
- Corrections, cancels, rejects, and errors are explicit events, not dropped noise.
- Operators can locate every dataset, experiment, candidate, and report depending
  on a defective source partition.
- Each workflow identifies the authoritative event log, ledger, manifest, and
  ownership boundary used for recovery.

## Observability

At minimum, expose:

- Source/canonical freshness, gaps, corrections, rejects, and quality state.
- Dataset, feature, model, optimizer, and report duration/failure counts.
- Feature/prediction distributions, missingness, model age, and candidate version.
- Applicable gross/net/factor/liquidity/currency/Greek/DV01/margin exposures.
- Order lifecycle, rejects, fill ratios, latency, slippage, and implementation
  shortfall.
- P&L, fees, impact, funding, financing, drawdown, reconciliation residual, and
  kill-switch state.

Telemetry includes source revision, artifact digest, strategy/service,
configuration, environment, region, venue, and host where applicable. Stable names
and units are mandatory. High-cardinality identifiers belong in logs or traces,
not unbounded metric labels.

Latency-sensitive targets publish through bounded, non-blocking counters or
buffers. Collector backpressure must not delay market data, risk enforcement,
order handling, or a kill switch. Dropped telemetry is measured and alerted.

Dashboards, alerts, and runbooks are versioned with the owning service or strategy.
An alert names its owner, severity, response, escalation, and recovery condition.

## Failure and degradation policy

Each application defines behavior for missing/stale data, unavailable metadata,
schema mismatch, storage failure, model load failure, stale risk, infeasibility,
venue rejection, incomplete fills, and reconciliation breach.

Permitted actions are:

- Fail closed.
- Pause and retain state.
- Degrade with an explicit visible flag and bounded scope.
- Use a registered conservative fallback.
- Flatten through an authorized process.

Silent continuation is prohibited. A fallback records why it activated, affected
scope, input/artifact identities, owner, and return-to-normal condition.

## Recovery and rollback

- Data publication is atomic and prior valid versions remain addressable.
- Candidate promotion is reversible without deleting evidence.
- Deployments retain a known-good artifact and compatible configuration.
- Runbooks cover detection, containment, stop, rollback, replay, reconciliation,
  escalation, and post-incident evidence.
- Recovery drills use test or paper environments and record observed recovery time,
  data loss if any, manual steps, and unresolved gaps.
- Kill switches are tested from outside the strategy process so that an unhealthy
  process cannot disable its only stop mechanism.

## Security and access control

- Secrets remain outside Git and resolve through a documented provider.
- Historical data, live data, paper execution, artifact promotion, and any future
  live execution use distinct least-privilege credentials.
- Research processes do not receive trading credentials.
- Source visibility does not grant data entitlement or deployment authority.
- Candidate artifacts and promotion actions have authenticated ownership and audit
  history.
- Fixtures and logs exclude sensitive account, order, position, and entitlement
  data.
- Toolchains, dependencies, and container bases where used are pinned, licensed,
  and scanned through approved CI.
- Destructive operations have explicit targets, authorization, and recoverable
  backups or version history.
- Live trading, withdrawals, custody, and key management require a separate legal,
  security, and operational design.

## Research and promotion states

| State | Meaning | Minimum evidence |
| --- | --- | --- |
| Exploration | Idea under investigation | Hypothesis; governed recording begins before formal comparison |
| Replication | Baseline reproduced | Source, differences, dataset, reproducible artifact |
| Candidate research | Competes under common evaluation | Point-in-time data, splits, costs, risk, stress |
| Frozen candidate | Selection complete | Immutable inputs, artifacts, decision rules |
| Final OOS | Frozen candidate evaluated | Access log, untouched outcome, failure analysis |
| Shadow | Production path without capital | Monitoring, reconciliation, ownership, kill rules |
| Paper | Controlled order lifecycle | Execution controls, recovery, TCA, incident handling |
| Retired | No longer eligible | Reason, effective time, replacement, retained evidence |

State transitions are explicit and validated. A candidate cannot skip a blocking
gate because a later-stage metric is attractive.

## Promotion evidence

Promotion considers the whole system:

- Data integrity, point-in-time behavior, lineage, coverage, and biases.
- Economic mechanism, horizon, decay, capacity, and failure mode.
- Forecast calibration, stability, monotonicity, and long/short asymmetry.
- Incremental value after existing signals, netting, and constraints.
- Realized risk calibration, exposures, tails, and stress.
- Optimizer feasibility, comparative statics, shadow prices, and fallback behavior.
- Net results after applicable fees, spread, impact, delay, funding, financing,
  borrow, and taxes.
- Capacity across capital, participation, liquidity, and stressed conditions.
- Multiple-testing evidence and the complete governed research path.
- Final-OOS outcome against precommitted rules.
- Shadow reconciliation, data drift, order behavior, incidents, and recovery drills.

No candidate is promoted solely because historical Sharpe exceeds a threshold.
Thresholds are precommitted for the strategy, horizon, data quality, capacity
objective, and risk budget.

## Independent review

An independent reviewer must be able to reconstruct the result without private
researcher state and records:

1. Dataset and universe reproduction.
2. Code, build target, artifact, and configuration findings.
3. Leakage, sign, unit, timestamp, and accounting checks.
4. Comparison with transparent baselines and challengers.
5. Unresolved data, model, execution, operational, or governance risks.
6. Conditions required before promotion and the owner of each condition.

Material findings are retained with the candidate. Approval does not delete
dissenting evidence.

## Documentation requirements

Maintain:

- Architecture decisions and dependency boundaries.
- Schemas, units, timestamps, lifecycle, and compatibility rules.
- Source specifications and limitations.
- Dataset, feature, label, model, risk, cost, and portfolio registry references.
- Operator commands, configuration, deployment, monitoring, rollback, and replay.
- Research methodology, metrics, promotion rules, and model-card templates.
- Asset-class conventions and portability evidence.
- Incident reviews, invalidations, migrations, and deprecations.

Commands are executable or explicitly illustrative. Documentation changes that
alter economic or operational behavior receive the same owner review as code.

## Definition of done

A capability is complete only when all applicable statements hold:

- Responsibility, contract, owner, and consumers are documented.
- Types, units, currency, signs, precision, time, and lifecycle are explicit.
- Deterministic unit tests cover normal, boundary, and failure paths.
- Replaceable or cross-language boundaries have contract/conformance tests.
- At least one bounded integration or human-auditable golden test exists.
- Time-dependent behavior has future-perturbation or equivalent leakage tests.
- Idempotency, interruption, retry, correction, and replay are defined.
- Failure, fallback, degradation, and stop behavior are tested.
- Artifacts contain complete lineage and deterministic identities.
- Metrics, logs, alerts, and operator-visible failures exist where applicable.
- Security, compatibility, migration, and rollback implications are reviewed.
- Performance is measured on critical paths using appropriate hardware.
- User, reviewer, and operator documentation is current.
- The applicable roadmap exit criteria and acceptance gates pass.
- Known limitations and deferred work have owners or explicit decision points.

A successful backtest alone is never completion evidence. Live capital deployment
is outside this definition and requires separate legal, venue, credential, risk,
capital, and operational authorization.
