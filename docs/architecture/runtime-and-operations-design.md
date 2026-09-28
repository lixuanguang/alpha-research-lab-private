# Runtime and operations design

**Status: destination design.** Capabilities remain planned unless explicitly
identified as current. Quant development owns the implementation boundaries;
the roadmap owns delivery and acceptance.

The initial operating scope is paper trading. Live deployment, authenticated
venue qualification and real-capital operation are
[KIV](../roadmap/README.md#live-trading-kiv-and-reconsideration); their destination
contracts below are retained for reconsideration, outside QR onboarding.

[Platform design and dependency direction](platform-design.md).

## Runtime lanes and deployment

The platform has three possible lanes with one shared semantic waist:

1. **Batch/research — CURRENT, bounded local scope.** Saved datasets, features, model studies, simulation and reports run with reproducible inputs. Distributed execution and measured parallel scaling remain planned.
2. **Ordinary event-driven — CURRENT bounded trusted-local paper/shadow service qualification.** MR07 connects native ingestion, candidate callbacks, dedicated-account risk/OMS and exact paper accounting with durable restart. A separate local shared-account workflow reuses per-instance decision sessions and coordinates attributable child and physical orders over normalized events. MR14 composes signed account services with source and policy processes and qualifies their finite 1–120 second local failure and restoration envelope. General deployment and MR15 throughput remain open; private venue reconciliation is KIV.
3. **Latency-sensitive — OPTIONAL PLANNED.** A native component or dedicated host is added only after a measured latency, jitter, or vendor ABI need. It consumes compatible schemas and remains behind independent risk and kill controls.

Lanes may use different artifacts, process models, stores, and release cadences. A deployment is placement of an
immutable compatible artifact; it does not grant trading authority. Activation is a separate envelope naming accounts,
venues, instruments, capital, limits, duration, credentials, and stop conditions.

## Artifact, schema, and state migration

MR06 implements the [local signed installation boundary](../governance/operations.md#trusted-local-installation)
for independent collector and execution artifacts, now extended with MR07's
portable paper OMS. It verifies
actual wheel/source/lock/audit bytes, out-of-band builder trust, configuration and
exact state compatibility before an offline installation. Rollback preserves
current mutable state. The initial local target and acceptance record do not
qualify remote production deployment, OMS state migration or venue recovery.
The paper destination below remains required at its owning milestones; live
qualification is deferred under the roadmap's KIV gate.

Managed local paper adds disabled deployment manifests and separate bounded
operator grants to that installer. Journal v3 owns generation fencing and checks
inside serialized economic transactions. The public-input API can use the signed
account-command adapter; the execution target does not import the research wheel.
Only the latest journal resumes after reconciliation. Historical restores remain
quarantined, and compatible rollback selects code while preserving current state.
The [activation record](../roadmap/paper-activation.md) owns the bounded evidence;
remote service recovery remains outside this increment.

MR14 adds a bounded local composition over those owners. One signed execution
service serializes each account's existing journal commands; one supervisor owns
the selected native-source processes and isolated policy processes. Only the
supervisor schedules and commits a decision cohort, in source-name then
instance-name order. Policy processes receive typed decision inputs and previous
state, with no account client. A missing policy response stops that cohort's new
decision commit and fences affected scheduling. A lost account-command response
has an uncertain economic outcome and is never retried automatically. A durable
owner generation fences replacements; a local account/socket scheduling fence
rejects duplicate producers. This is a trusted
single-user topology, not hostile-process isolation or distributed consensus.

Full diagnostic reports run in one bounded child that can inspect accounts but
cannot submit economic or lifecycle commands. The supervisor still reads account
phases at the configured protection cadence. The diagnostic channel retains one
current report batch and only the latest pending batch; skipped diagnostic
requests and actual report times are visible. Native deliveries and decision
cohorts never use that replaceable channel. The child shares the supervisor's
shutdown deadline, and its PID, completion counts and forced fencing are retained
for resource and cleanup review. Existing report fields and telemetry remain
available; a delayed diagnostic does not become a fresh account observation.

The supervised native-source definition also binds an explicit selected-book
paper cadence, `market_interval_us`. It defaults to 3,000,000 microseconds and
must be positive and no greater than source freshness or capture idle time; the
complete deployment and input identities include it. Every native record is
retained and validated in order. The first eligible market, then eligible markets
at least one interval after the last selected market, can match outstanding paper
orders and evaluate active policies. Intermediate eligible books advance the freshest
monitoring mark without modeled fills or policy checkpoints; invalid source
input still faults promptly. The retained `SharedBookDelivery.market_effects=false`
marks skipped economics for exact replay, while legacy envelopes omitting that
optional field preserve the earlier per-book behavior. This is a declared paper
market model rather than native-feed downsampling or MR15 throughput evidence.

The immutable deployment can bind multiple explicit source/scenario identities
per account. A versioned active selection can enable an already provisioned
instance after a controlled restart. Its predecessor hash, source definitions,
policies, exact account configuration and journal remain compatible or launch
fails. New definitions outside the signed envelope need separately qualified
installation compatibility. The [service guide](../../src/applications/paper/README.md#supervised-local-deployments)
owns commands; the [MR14 record](../roadmap/multi-instance-paper.md) owns qualification.

An artifact identity binds source commit, build command, dependency lock, platform, configuration, model/data
references, schema versions, limits, and complete artifact digest. Build once and promote the same bytes. The retained
[release workflow](../governance/workflow.md#build-a-release) owns this identity and verification contract.
Its artifact verification consumer and admitted deployment graph precede the first actual deployment,
including early capture and paper/shadow. Bounded activation later binds executable authority
to the verified artifact; it cannot be the first installer for an earlier milestone.

Keep dataset, experiment, candidate and deployment manifests distinct and linked.
The deployment manifest binds executable/model/feature artifacts, instances,
accounts, capabilities and operating configuration. A separate activation
envelope binds authorized instruments, limits and duration. Research/shadow
environments have no production submission authority; installed artifacts alone
cannot grant it. Each operating package is installed and verified independently
of unrelated research dependencies while retaining compatible shared schemas.

Schema changes use explicit versions and compatibility windows. The normal migration is expand, dual-read/write where
necessary, backfill or reconcile, cut over, then contract. A reader rejects unknown incompatible versions with a visible
reason. State migration includes a replay fixture, compatibility check, rollback point, and proof that old orders/fills
cannot be applied twice.

Model, dataset, and configuration changes are separate identities even when they share one release artifact. A rollback
selects a compatible prior set of code, model, data, schema, limits, and state; reverting only a Python wheel is unsafe
when state or schema changed.

## Monitoring, recovery, and operational evidence

**Current bounded local qualification:** MR10 connects durable account
stop/fault/restart and cancel requests, retained local alert outcomes, quiesced
account backup/restore, signed account installation/rollback and the MR14
supervised paper/shadow service drills. Dedicated live-paper failures persist a
decision block before releasing their fence. The
[runbook](../governance/operations.md#local-paper-operations) and
[runtime guide](../../src/runtime/README.md#account-workspace-recovery) own the
implemented interfaces. MR12 extends the original local alert prerequisite with
[versioned telemetry and retained dashboards](../../src/telemetry/README.md),
causal query/metric APIs and report adapters. Periodic collector observations use
a bounded background writer; disk stalls cannot hold the watchdog control thread.
Account/venue commands project committed state into a separate optional journal.
The bounded managed-paper activation/recovery increment is described in the
[runbook](../governance/operations.md#managed-public-paper-activation-and-recovery).
The [MR14 record](../roadmap/multi-instance-paper.md) and joint ignored
`logs/mr10/multi-instance-paper.json` complete bounded trusted-local MR10/MR14
operating acceptance, reusing historical MR10 backup/restore and MR13 signed
rollback proofs by explicit impact analysis. This scope does not qualify general
remote service deployment, sustained MR15 capacity or cross-journal atomic limits.
External private venue qualification remains unproven and KIV.

Current monitoring events correlate release, strategy, model, dataset/source/study,
account, instrument, venue, order, fill, state epoch and incident through fixed
bounded fields. Exact units, clock quality and sensitivity classification are
retained alongside separate event, availability and receipt clocks. Input
revisions, missing/stale results and telemetry loss are observable; telemetry
failure cannot disable an emergency stop. Source-clock qualification, remote
service/alert delivery and measured operating capacity remain open.

Minimum signals include stale or missing data, heartbeat loss, sequence gaps, reject/error bursts, clock drift, risk-
limit breaches, position/cash mismatch, open-order mismatch, fill duplication, reconciliation failure, resource
exhaustion, and alert-delivery failure.

Deliver the applicable signals with the first working capability: batch progress,
invalid counts and persistence failures for acquisition; advancing ingestion,
freshness, queues and recovery for capture; resource/failure visibility for queries;
execution, attribution and risk state for operating strategies. A live heartbeat with no advancing work must
be distinguishable from a healthy service. Test process/collector loss and alert
delivery; hard risk controls do not depend on telemetry availability. Instrumentation
or model-tracking products supply adapters, not the domain checks or responses.
Every deployed strategy needs operational/economic monitoring; learned-model checks
add feature freshness, prediction behavior, inference failures and delayed-label
evaluation through the same versioned research definitions.

Before QR onboarding, quant development delivers the metric computation and
query APIs, report/dashboard engine, default operational views, alert routing
and retention. QR later defines strategy-specific metrics, charts and diagnostic
thresholds through versioned interfaces. A reference metric and chart must work
over both retained studies and paper/shadow telemetry, with explicit applicability,
units, time aggregation, missingness and late-label behavior. Adding them must not
require edits to shared collectors, runtime or dashboard rendering. Hard risk
controls remain independently configured and cannot be replaced by chart thresholds.

On a material signal, safe response stops new risk, cancels where safe, fences the affected process or account,
preserves raw and normalized evidence, reconciles the venue, and records release/configuration identity. Restart follows
state, schema, credential, limit, and fencing checks. Backup/restore, stop/cancel, replay, rollback, and alert delivery
are tested before a canary receives more exposure.

Expose block-new-exposure, cancel-outstanding and reduce-position as distinct
operations with explicit connectivity, freshness and liquidity requirements.
Stopping a strategy does not imply immediate flattening or release of uncertain
orders. The roadmap's failure scenarios cover disk/queue exhaustion, malformed
inputs, clock anomalies and modeled order-event loss/timeouts alongside
process/service loss. Final paper acceptance requires both public-input paper
paths and their actual service/failure evidence. Private-stream loss, exchange
timeouts and external venue conformance remain live KIV requirements.

### Feed health and observable loss

Measure receipt-to-durable delay, advancing source/persistence cursors, interarrival
gaps, queue age/bytes, invalid/duplicate counts, reconnects and recovery duration
per supported binding. Distinguish expected quiet feeds from stalled progress
using the stream contract. Heartbeats alone do not establish fresh data. Venue
quality is an observed property of the selected feed and period, not a permanent
ranking such as “Binance is always stable.”

## Security, entitlements, and organization

Secrets stay outside source, fixtures, logs, and artifacts. Data rights, retention, venue permissions, account scope,
and broker terms are checked for the actual source and deployment. A development wheel does not create market,
credential, or capital authority. External legal and source obligations remain applicable throughout the solo phase.

The founder may implement and activate a bounded system while working alone when technical safety and release checks
pass. Onboarding progressively adds independent domain review, security review, deployment authority, risk ownership,
and operational coverage. Controls attach to real people, accounts, and responsibilities when those exist; they do not
block an ordinary local calculation by pretending unavailable roles are present.

## Scaling triggers and technology choices

Keep the current Python/uv path while it is reproducible and within the workload budget.
The implemented [research integrations](../../src/research/studies/README.md#ownership-and-verification)
address concrete tracking, orchestration and data/feature-reuse consumers;
their initial bounded integrations do not require a throughput bottleneck. Preserve
existing source, temporal and numerical contracts through their adapters. Measure before
expanding to distributed execution, large/shared databases, a distributed event bus,
another build system or HPC scheduling.

Capacity qualification itself is required before QR onboarding. Quant development
authors the launch workload and numeric acceptance budgets, covering more than
the existing 1,024-row/close demonstrations: multi-day samples, multiple instruments,
concurrent trials, ingestion, replay, reports and monitoring queries. Resource
limits and supported workload must be explicit. Implement and measure the needed
storage/compute path before handing it to QR; only expansion beyond the accepted
launch envelope waits for a later workload. Architecture measurements determine
the technology, not whether the capability is delivered.

Set research and operating budgets at the start of their delivery paths. Include
offline retrieval and online feature materialization/serving alongside queries,
ingestion and execution. Record throughput, p50/p95/p99 latency, memory/disk,
concurrency, hardware/cache conditions and recovery targets. Research capacity
can be accepted at G2; final runtime and service capacity qualification remains
MR15 work. MR14's bounded service failure drills do not establish that capacity.

The provisional numeric [research launch profile and measured diagnostics](../roadmap/research-capacity.md)
and [integrated runtime profile](../roadmap/runtime-capacity.md) now declare those
budgets. Research diagnostics cover the enlarged study schedules, incremental
scheduled replay and isolated Feast worker; representative 72-hour acceptance
remains open. Runtime qualification must separately resolve MR14's 120-second
service lifetime, finite capture limits and signed-grant validity before a
sustained claim. Neither record closes MR16 ownership or MR17 onboarding.

Useful triggers include a dataset build that misses research cadence, concurrent readers that contend on local storage,
replay throughput that blocks iteration, recovery time beyond the operating target, or measured native latency/jitter
that Python cannot meet. Each trigger records the measurement, failure mode, target, cost, and rollback path.

HPC or distributed execution is a batch optimization, not a new semantic lane. Workers receive immutable partition
identities and deterministic seeds; output manifests are reconciled before publication. Remote caching or execution is
not introduced merely to reproduce an institutional pattern.

A Rust or C++ component preserves the Python reference's goldens and accounting/risk decisions. Its ABI names
allocation, ownership, error, threading, layout, numeric representation, version, and shutdown behavior. The native
artifact is admitted and tested for every supported platform before a consumer depends on it.

### Storage and performance decisions

Durable capture decouples receipt from downstream work through replayable journals
and bounded queues. A durable local segment log is the first candidate. Evaluate
Kafka when independent consumers, retention/replay, cross-process recovery or
burst isolation justify a service. Partition by a declared ordering scope and
retain original event identity; acknowledgement and consumer checkpoint rules
must compose with durable sink writes. Broker guarantees do not by themselves
make an external database sink exactly once.
[Kafka delivery semantics](https://kafka.apache.org/design/).

Query workload evaluation compares the reference reader with a bounded columnar candidate; include
ClickHouse when the depth-history or concurrent analytics workload warrants it.
Decide sorting/partition keys, batching, retention and snapshot-plus-delta layout
from the named query. Keep all economically relevant revisions and control events
available to as-of selection; a latest-value table cannot replace replay history.
Columnar storage performance depends on layout and accessed data, so choosing the
engine alone is not acceptance.
[ClickHouse MergeTree design](https://github.com/ClickHouse/ClickHouse/blob/master/docs/en/engines/table-engines/mergetree-family/mergetree.md).

Use the proposed **7M+ source messages/day and sub-500ms historical depth query**
as a candidate workload to scope in a measured scaling study, not an achieved result or a reason
to mandate both services. Define total versus per-venue volume, messages versus
normalized rows, burst distribution, retention horizon, depth levels, query/result
size, concurrency, hardware, warm/cold cache and latency percentile before a run.
Measure sustained/burst ingestion, durable lag, memory/disk, queue growth, recovery,
rows/bytes scanned and p50/p95/p99 query latency. Retain exact-value/revision parity
and the operational cost. A bounded representative experiment decides whether to
adopt, defer or revise the target; no service deployment is required for P1.

### External simulator reuse

Use hftbacktest first as a source of small independent traces and, when a book
consumer exists, a candidate differential simulator. Its
[Python package metadata](https://github.com/nkaz001/hftbacktest/blob/5f3ec40b2afb764e0fea112f941ed85523ef4e88/py-hftbacktest/pyproject.toml)
adds a Rust build and NumPy/Numba dependencies; compatibility with this repository's
pinned Python 3.14 and dependency policy has not been established. Do not import
its stack, sample numeric types, timestamp repairs or connector code wholesale.
A reuse experiment names the revision and supported mechanics, checks exact
unit/clock conversion, compares matched traces and reports disagreements before
dependency admission. Optimize representation, prefetch or native loops only
after a representative workload measurement, preserving the reference semantics.
