# Active delivery contracts: MR10–MR21

Owner: repository founder. Status: planned; updated 2026-09-23.

This page is the canonical detailed contract record for active work linked from
the [platform infrastructure roadmap](README.md). The contracts below preserve
the original future-MR acceptance wording and limits; completed MRs and their
historical evidence remain in [history-mr1-to-mr9a.md](history-mr1-to-mr9a.md).

All future MRs follow the [current data policy](README.md#current-platform):
use OKX or Bitfinex where feasible; do not depend on Binance or Tardis availability.

## Candidate packaging and runtime binding

**MR 10.** Freeze the [candidate contract](../architecture/platform-design.md#candidate-promotion-contract):
input requirements, features/preprocessing, optional model, signal-to-target policy,
state/warm-up rules and accepted experiment evidence. Retain artifact bytes as well
as hashes. A rule has no invented model artifact. Reuse the accepted components in
research and runtime applications; no translation into separate production formulas.

For an order-book candidate, reuse the closed [MR 9A](history-mr1-to-mr9a.md#l2-order-book-backtesting)
capability. Bind its supported order types, book requirements,
timing/fill model and accepted backtest evidence in the candidate contract. A
strategy requiring resting orders must also have that execution model implemented
and tested; the first immediate-execution slice cannot qualify it. Candidates
using the existing trade-price model keep their current acceptance path.

Acceptance: reconstruct a candidate from retained bytes without a notebook or
credentials; reject incompatible schemas, units, timing, state or outputs; bind a
compatible runtime input and reproduce matched decisions. Deployment configuration
selects candidate instances and resources separately from research selection and
trading authority. Retraining creates a new candidate and renews affected evidence.

Pin the ClearML model/task IDs, immutable model manifest and bytes/digests, relevant
lakeFS commits, feature definitions and accepted evaluation/report IDs. ClearML model
publication can protect model contents, but tags/metadata are not an immutable
candidate identity. Reconstruct from retained bytes when the UI is unavailable;
verify content rather than resolving a mutable "latest" name. Catalog publication,
research selection, deployment and trading activation remain separate actions.

### Trusted deployment artifact

**MR 11, before any deployment.** Supply a concrete build/install/verify consumer
that binds exact artifact bytes, source, dependency lock, provenance, platform and
trusted origin. Enforce inventory, safe archive paths and configuration/state
compatibility. Verification fails before loading incompatible or untrusted content.

The [dependency/release boundary](../architecture/README.md#dependency-and-release-boundaries)
currently blocks release. Clearing that restriction alone does not implement this
consumer. Exercise the actual isolated installed artifact and failure boundary.
A collector pulled forward for a data need must meet the same applicable deployment
requirement; it need not wait for a strategy or executable venue adapter.

Apply the same concrete deployment boundary to operated ClearML server/agent,
lakeFS and applicable Feast services. Pin their images/configuration, admit the
actual edition and dependencies, and verify access boundaries, artifact retrieval,
backup/restore and upgrades for the selected topology. ClearML is one selected
product, not one process; include its backing services and retained artifact storage.
Workers execute trusted research entrypoints in the declared environment. A service
deployment or queued research task does not confer trading authority.

### Paper order lifecycle and recovery

**MR 12.** Compose a paper/shadow runtime with stable order identity, acknowledgement,
fill, reject, cancel/replace and unknown-outcome states. Retain orders, fills and
state in a durable journal with idempotency and writer fencing. Paper and replay
reuse strategy decisions; their execution adapters expose different assumptions.

Acceptance: delayed/duplicate messages cannot duplicate orders or fills; unknown
sends reconcile before retry; crash/restart preserves commitments and economic state.
Qualification may introduce an offline order lifecycle earlier when a selected
simulator needs it, without implying deployment acceptance or live authority.

### Independent risk and account reconciliation

**MR 13.** Enforce independent account/instance limits including pending exposure.
Reconcile authoritative cash, positions, open orders and unknown/pending commitments
before continuing after startup, disconnect or a break. An instance cannot raise
its own limits or erase reservations by restarting.

Acceptance: rejected or duplicate activity cannot bypass limits; stale/missing state
and reconciliation breaks trigger the specified protective response. Record the
resolution and owner. Base reconciliation is mandatory for one instance; shared
allocation is an additional requirement, not a reason to postpone the base control.

### Shared account allocation

**MR 14, conditional.** Before a second instance shares an account, define allocation,
arbitration, netting and attribution while preserving each strategy's intent.
Reconcile allocated commitments/positions/cash with authoritative account state.

Acceptance: conflicting targets, partial fills, restarts and allocation changes
cannot double spend capital or conceal exposure. Shared inputs stay immutable;
strategy state and limits remain attributable. New accounts/asset mechanics need
their own applicable qualification rather than blanket platform acceptance.

### Operations and paper qualification

**MR 15.** Deliver an owned runbook and independent health/alert path with the
paper/shadow candidate. Observe data freshness, decision progress, errors, journal
persistence, reconciliation, limits and alert delivery. A live process may be stalled;
failed alert delivery must not silently disable protection.

Acceptance: compare matched replay/paper input, feature, prediction and target traces;
qualify start, stop, cancel, disconnect, restart and compatible rollback. Retain the
first divergence and every material failed attempt. Simulated fills qualify only
their declared model. Stop, cancel and flatten remain distinct operations. Actual
paper/shadow deployment also requires MR 11.

Schedule retained evaluation/report tasks through the qualified ClearML worker path.
Reuse MR 7 reference/current diagnostic reports for feature quality, distributions
and model performance where labels exist, keeping reference windows and thresholds versioned. Record stale,
missing-label and failed-report outcomes. These jobs may lag or fail independently;
they do not replace the health/alert path or sit in the order/decision hot path.

### Executable venue adapter

**MR 16.** Implement one selected venue/product/account boundary with supported
order types, precision, limits, authentication and authoritative reconciliation.
Keep vendor state behind the order contract. Market-data capture is not an order
adapter. Preserve partial fills, cancel races and unknown outcomes.

Acceptance: the appropriate permitted environment demonstrates the actual adapter
boundary and its failure/recovery behavior. Offline mocks alone cannot establish
venue compatibility. Retain the operating environment and observed limitations;
this package does not grant live activation.

### Live monitoring and controls

**MR 17.** Bind the qualified operations path to actual execution/account state.
Retain artifact, candidate and instance identities with stale inputs, failed inference,
orders/fills, rejects, cash/position breaks, P&L attribution and limit events.

Acceptance: fault scenarios demonstrate independent detection, alert delivery and
the configured stop/cancel response, including alive-but-stalled processing.
Delayed-label/model monitoring is applicable only to candidates that use it.
Keep controls effective through disconnects and operator/restart transitions.

Link realized performance and applicable reference/current diagnostic findings
to the exact deployed candidate/model version and observation window in ClearML. Distinguish delayed
outcomes from missing data. A drift finding can request research investigation;
automatic retraining, candidate replacement or live activation is not implied.

### Bounded activation and recovery

**MR 18.** Add an explicit activation decision binding artifact/configuration,
account, venue, instruments, capital, exposure/loss limits, duration and credential
scope. Deployment alone must leave executable authority disabled. Invalid or
incompatible startup state is refused.

Acceptance: authorized bounded operation demonstrates stop/cancel, reconciliation,
recovery and rollback with retained external fills. Rollback cannot undo venue
activity. The [workflow](../governance/workflow.md#activate-and-operate) and
[operations runbook](../governance/operations.md) own authority and response rules.
This roadmap authorizes implementation work only when requested, not live orders.

### Additional compatible live instance

**MR 19.** Add one real compatible strategy/instrument instance through configuration
and accepted components. Qualify isolation, resource/risk attribution and required
shared-account controls. New product mechanics require new simulation, accounting,
risk and execution capabilities before admission; do not conceal them as configuration.

Acceptance: starting/stopping/updating one instance cannot mutate another's strategy
state or bypass account controls. Extend only the affected source, economic and
operational evidence for the added scope.

## Maintenance and growth

The [post-MR9A maintenance review](post-mr9a-maintenance-review.md) records the
completed acceptance-scaffolding cleanup and remaining output/documentation
consolidation candidates. Retained evidence has not been deleted.

### Measured storage and computation growth

**MR 20, conditional.** Revisit the reference reader or computation lane only when a
representative workload misses an accepted latency, throughput, memory or storage
budget. Compare verified end-to-end behavior, including loading, integrity, causal
selection, controls and retained lineage. Output batch size is not a total-RSS bound.

Use [query workload evidence](../../examples/notebook-operations.md#query-workload-evidence)
for its original measured scope; it does not benchmark current code. A Parquet scan
alone is not a replacement for the reader. Columnar/distributed/native/GPU paths
must preserve relevant exact arithmetic, timing, identity and recovery contracts.
The selected integrations above address concrete traceability and research consumers;
they do not need to wait for a scale bottleneck. This MR owns their measured growth:
DuckDB/Polars replacements for expensive reader/transformation paths, larger lakeFS
storage, shared Feast stores and additional ClearML workers. Benchmark the full
validated path and conversion costs against the retained reference. Preserve original
data/model identities and numerical/temporal behavior when moving storage or engines.
Qualify writer coordination and restart before multiple workers write shared attempt
state; MR 2's local single-writer store is not a distributed trial database. Process
isolation for trusted research is not a malicious-code sandbox.

### Python ownership and enforcement

**MR 21.** Complete the existing [Python ownership requirements](../coding_standards/README.md#python-scope-and-migration)
in developer tooling, tests and maintained snippets. Reusable behavior belongs to
cohesive classes; bare functions serve actual orchestration. Preserve pytest
discovery, callback signatures, isolation and native stub contracts.

Add focused enforcement for non-orchestrator bare functions without weakening
existing typing, import or documentation checks. Update permissive cases and run
the configured static scope. Class cohesion still requires review; moving unrelated
helpers into one static-method collection is not acceptance.

### Further scope needs a consumer

The platform can grow toward multi-asset research, portfolios and independently
operated strategies. New financing, derivatives, corporate-action, session, currency,
margin, queue/impact or lifecycle behavior needs an explicit consumer and its own
bounded contract and independent numerical/causal proof. Existing spot or visible-book
evidence cannot qualify those mechanics. Reuse mature libraries behind narrow
adapters where they satisfy the required semantics.

Team ownership, independent approvals and organizational controls are introduced
as actual contributors/operators join. They do not replace the technical integrity,
reproduction and safety controls required by the first real consumer.

## Execution and maintenance

For each MR, select one observable consumer outcome, its dependencies and the
smallest sufficient proof. Split an oversized implementation before starting it;
keep this backlog as the canonical list and use stable capability names elsewhere.
Do not create a permanent roadmap file or notebook for each completed MR.

Follow the [engineering guide](../coding_standards/README.md) and
[development workflow](../governance/workflow.md). Preserve functional ownership,
public APIs and application composition boundaries. Keep definitions separate from
selections, shared inputs immutable and mutable state per instance. Unsupported
capabilities and invalid configuration fail explicitly.

Acceptance records identify source/artifact, environment, configuration, inputs,
attempt, command, result and limitations. Reuse unaffected evidence and renew the
proof changed by code/data/configuration/dependency/artifact changes. Retain failed
attempts; a new success does not rewrite measured reliability. Run expensive checks
only for a concrete boundary that cheaper evidence cannot establish.

Update the current architecture/component documentation and QR guide when behavior
becomes usable. Keep empirical research acceptance, software correctness, artifact
admission, operating qualification and actual activation distinct. Completed MR
history remains in version control; active READMEs describe current behavior and
active plans. Preserved content-addressed fixtures and measured evidence retain
their original identities and do not serve as roadmap navigation.
