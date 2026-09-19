# Platform infrastructure roadmap

Owner: repository founder. Updated 2026-09-19. **MR 1 is implemented; MRs 2–21 are planned.**
Numbering identifies the selected delivery slices; completed capabilities become
the current platform without renumbering the remaining backlog. MR numbers identify delivery
work, not packages, APIs, notebook sections or experiment versions.

This is the quant developer's infrastructure plan. The
[QR implementation guide](../../examples/README.md) explains how researchers use
available capabilities and prepare research for promotion. The
[research program](research-program.md) owns methodology and experimental choices;
the [platform design](../architecture/platform-design.md) owns shared contracts.

## Current platform

The working path is configured acquisition or capture → retained raw inputs →
validation and versioned publication → explicit snapshot queries/replay → EDA.

| Available capability | Researcher benefit | Current limit |
| --- | --- | --- |
| Instrument identity, calendars and exact financial units | Shared identifiers, clocks and numerical conventions | These foundations do not constitute a strategy ledger or execution engine |
| Bounded historical acquisition and native capture | Retained source bytes, request identities and explicit failure/recovery behavior | Supported sources and products only; source-specific limits remain visible |
| Occurrences, revisions, eligibility and dataset publication | Trace observations and reopen a verified snapshot | Empirical historical eligibility, coverage and revision availability remain unresolved for the frozen sample |
| Trade cutoff/history queries and chronological replay | Inspect what is knowable and retain corrections and scoped controls | Bounded reference implementation; replay alone does not simulate economic fills |
| Book reconstruction, publication and replay | Inspect visible books, recovery and matching saved state | Exploratory degraded scope; no queue position or executable-fill claim |
| Pinned research selections, configured EDA and maintained notebooks | Discover saved snapshots and reopen named trade/book inputs with identities, units and missingness | Bounded exploratory assembly; formal feature/model workflows and economic backtesting remain planned |

The [data command reference](../../src/market_data/README.md) owns current usage.
The [frozen P1 experiment](../research/p1-baseline.md) retains its own identity,
source sample and economic assumptions. It is not renumbered with this roadmap.
No empirical strategy, paper deployment or live trading acceptance is claimed.

## Platform and researcher responsibilities

| Boundary | Quant researcher owns | Platform infrastructure owns |
| --- | --- | --- |
| Data | Required universe, fields, horizon, quality and source/use requirements | Adapters, provenance, revisions, publication, discovery and causal assembly |
| Features and labels | Hypothesis, formula, target, windows and missingness policy | Reusable execution, alignment, lineage and applicable state handling |
| Models and rules | Estimator/rule, comparison space, metrics and selection choices | Temporal splits, fit/inference lifecycle, complete attempts and reproducible artifacts |
| Backtesting | Signal-to-target policy and declared economic assumptions | Shared runner, independent risk, simulated fills, exact accounting and reporting |
| Promotion | Frozen candidate and accepted research evidence | Compatibility checks, artifact loading, runtime binding and qualification |
| Operation | Investigate attributed behavior and propose a new candidate | Execution, reconciliation, monitoring, recovery and separate activation controls |

A supported new feature, estimator or rule should plug into existing interfaces
without modifying shared runners. A new source/schema or execution mechanic needs
its missing platform capability first. Add interfaces with concrete consumers;
do not build an empty feature catalog, registry service or generic plugin framework.

## Delivery order and dependencies

The first useful outcomes are researcher data access, auditable comparisons and a
small economic backtest. Those tracks share contracts but do not force every
candidate through model training. Source onboarding is driven by an actual missing
input. The synthetic economic path can begin with existing saved fixtures while
source evidence and researcher access improve independently.

| MR | Delivery outcome | Prerequisites |
| --- | --- | --- |
| 1 | [Research dataset access and source onboarding](#research-dataset-access-and-source-onboarding) — implemented | Current query/publication APIs |
| 2 | [Experiment attempts and temporal splits](#experiment-attempts-and-temporal-splits) | Existing saved inputs; integrates with MR 1 |
| 3 | [Versioned features and labels](#versioned-features-and-labels) | MR 1; MR 2 for formal comparisons |
| 4 | [Fitted preprocessing and model evaluation](#fitted-preprocessing-and-model-evaluation) | MRs 2–3; only for a selected learned consumer |
| 5 | [First economic backtest](#first-economic-backtest) | Existing replay and financial contracts; no model dependency |
| 6 | [Configured runs and durable reports](#configured-runs-and-durable-reports) | MRs 1–2 and 5 |
| 7 | [Research comparison and extension](#research-comparison-and-extension) | MRs 1–3, 5–6; MR 4 where applicable |
| 8 | [Frozen baseline acceptance](#frozen-baseline-acceptance) | MRs 5–6 plus required actual source evidence |
| 9 | [Runtime feature parity](#runtime-feature-parity) | MR 3 and applicable MR 4; qualified runtime input, only if required |
| 10 | [Candidate packaging and runtime binding](#candidate-packaging-and-runtime-binding) | MRs 6–7 and accepted candidate evidence; MRs 4/9 where applicable |
| 11 | [Trusted deployment artifact](#trusted-deployment-artifact) | Dependency admission and a concrete deployable consumer |
| 12 | [Paper order lifecycle and recovery](#paper-order-lifecycle-and-recovery) | MR 10; MR 11 before deployment |
| 13 | [Independent risk and account reconciliation](#independent-risk-and-account-reconciliation) | MRs 5 and 12 |
| 14 | [Shared account allocation](#shared-account-allocation) | MR 13; only before multiple instances share an account |
| 15 | [Operations and paper qualification](#operations-and-paper-qualification) | MRs 10–13; MR 14 if sharing an account |
| 16 | [Executable venue adapter](#executable-venue-adapter) | Order/risk/reconciliation contracts from MRs 12–13 |
| 17 | [Live monitoring and controls](#live-monitoring-and-controls) | MRs 15–16 |
| 18 | [Bounded activation and recovery](#bounded-activation-and-recovery) | MRs 11, 15–17; explicit operating authorization |
| 19 | [Additional compatible live instance](#additional-compatible-live-instance) | MR 18; MR 14 if sharing an account |
| 20 | [Measured storage and computation growth](#measured-storage-and-computation-growth) | A measured workload exceeding an accepted budget |
| 21 | [Python ownership and enforcement](#python-ownership-and-enforcement) | Existing engineering rules and tooling/tests |

Numbers provide a fresh backlog order, not a requirement to wait for every lower
number. MR 11 must move forward before any actual deployment, including a collector.
MR 21 can proceed independently. MR 8 accepts the specific frozen experiment;
MR 7 separately accepts the reusable research workflow. Neither substitutes for
the other's evidence. Conditional work stays dormant until its consumer exists.

## Research infrastructure

### Research dataset access and source onboarding

**MR 1 — implemented (bounded software acceptance).** Give the QR one bounded way to discover saved datasets, select explicit
snapshots/universes/fields/time ranges and assemble compatible research inputs.
Use existing publication, trade and book interfaces; do not merge incompatible
schemas by pretending every source is a trade. Retain query/input identities,
units, quality, historical membership and missingness alongside the values.

Exercise one demanded source or dataset extension from acquisition through
publication and the same research interface. Additional supported instruments or
intervals should require configuration; new providers/data families require the
adapter, schema and temporal semantics they actually lack. Preserve access and
retention limits. A future macro/fundamental input must expose release/revision
availability, not merely a business date.

Acceptance: a QR can reopen a pinned multi-input selection; a late correction or
unavailable input cannot appear at an earlier decision; missing coverage remains
visible; a supported extension works without changing the research runner.
Own this in `market_data/` and `research/`, composed by `applications/`.

Delivered through `SnapshotCatalog`, `ResearchSelection` / `ResearchReader`, native
book cutoff projections and the existing `inspect_eda` entry. The configured
`spot-comparison` job exercises BTC/ETH acquisition through publication and a
pinned selection alongside a synthetic OKX book, reopened in a fresh process.
The [installed workflow](../../tests/integration/consumers/datasets/ingestion_workflow.py)
and [access regressions](../../tests/unit/data/test_research_access.py) cover the
acceptance boundaries; the [QR guide](../../examples/README.md#select-and-inspect-research-data)
and [command reference](../../src/market_data/README.md#discover-and-reopen-research-selections)
own current use. Validation commands/results and the failed development attempts
are recorded in the implementation PR, rather than a separate MR archive.

This is synthetic software evidence. Source coverage, book historical membership
and archive revision availability remain unproven where documented. Unknown
availability yields no earlier values; no new provider, macro schema, empirical
P1 acceptance, deployment or execution capability is claimed.

### Experiment attempts and temporal splits

**MR 2.** Introduce shared attempt and split records before formal feature/model
comparison. Separate reproducible semantic run identity from execution attempt
identity. Hash inputs, components, configuration and seeds; exclude output paths,
wall-clock attempt times and generated results from the semantic input identity.
Retain influencing failed, rejected and abandoned attempts and consumed holdouts.

Temporal splits carry information intervals and label availability, with purging
and embargo when applicable. Train-only fitting and untouched evaluation boundaries
must be enforceable by the consumer. A rule with no fit records inapplicability
rather than inventing training rows. Define atomic completion and the initial
single-writer/concurrency boundary; incomplete attempts remain inspectable.

Acceptance: reload the same inputs/splits deterministically; future/holdout rows and
late labels cannot enter fitting; changed inputs produce a new identity; interrupted
attempts cannot appear completed. `research/experiments/` owns the reusable core.

### Versioned features and labels

**MR 3.** Add a versioned feature interface for a concrete diagnostic, signal,
factor study, rule or model. Inputs, formula, units, windows, cadence, warm-up and
missing/stale policy are explicit. Label generation is a separate capability with
outcome horizon, information interval and time of availability. Forward outcomes
cannot enter the earlier feature vector. No model is required for feature research.

Acceptance: hand-inspectable window/label examples, future-input perturbation,
missingness and repeated-execution parity; retain dataset/definition identities.
Notebook prototypes become shared operations when formal retained consumers need
them. Own formulas in `research/features/` and `research/labels/`; applications
compose them. Incremental execution is deferred unless a runtime consumer needs it.

### Fitted preprocessing and model evaluation

**MR 4, conditional.** Support one selected trainer and its necessary preprocessing.
Fit only on permitted rows and then-available labels; serialize transform/model
state with input signature, fit window/cutoff, parameters, seed and environment.
Inference loads accepted state without implicitly fitting. Evaluation records
predictions, delayed outcomes, metrics and split identity separately from training.

Acceptance: fixed-input inference after reload agrees under a declared numerical
contract; held-out/future perturbations do not change the fit; incompatible feature
order, units or state fails explicitly. Walk-forward decisions select only artifacts
that could have been fitted and made available by that decision. A final full-history
fit cannot be used for earlier decisions. Own behavior in `research/models/` and
feature preprocessing; training/evaluation applications remain composition roots.

## Economic research

### First economic backtest

**MR 5.** Deliver a small integrated path: saved verified synthetic inputs → completed
observations → no-trade and fixed momentum rules → independent limits → positive-delay
fills → exact cash, positions, costs and NAV. Reuse the existing chronological
iterator. This proves economics without waiting for fitted features or live data.

Keep observation construction in `research/observations/`, decisions in `strategies/`,
fills/costs in `simulation/`, accounting in `accounting/` and limits in `risk/`.
`applications/backtest/` composes them. The strategy returns targets and cannot
bypass independent risk. Introduce only the frozen baseline's product mechanics.

Acceptance follows the [frozen economics](../research/p1-baseline.md) and
[clock/fill contract](../architecture/platform-design.md#replay-clocks-and-fill-fidelity):

- Decisions use completed windows; positive delay prevents same-observation fills.
  Equal-time source/control events precede expiry, fill, decision and mark phases.
  A later gap cannot retroactively cancel an already applied fill.
- Preserve all applicable scoped controls through instrument/field projection.
  Unrelated bindings remain isolated. Expiry is strict; pending reservations and
  at most the supported pending intents are explicit.
- Reconcile the independent hand ledger, no-trade case and gross-to-net attribution.
  Money follows explicit quantum/rounding; basis and returns use exact rational
  representation where division is not finite. Ambient Decimal context must not
  change results. Keep the hand oracle's half-up and baseline's half-even distinct.
- Reject unaffordable intents without changing cash/holdings. Expected risk rejection
  can belong to a completed run; invalid accounting or missing required valuation
  cannot. Terminal marking is not an invented liquidation.
- Whole, single-row and tied-group batches produce the same trace. Resume preserves
  consumer state, schedules, applied-fill identities and ledger alongside the source
  cursor. A cursor alone is not an economic checkpoint.

### Configured runs and durable reports

**MR 6.** Expose the economic path through validated configuration and one installed
command, reusing the attempt core and explicit data selection. Retain immutable
input/configuration/component identities, event/decision/fill trace and a readable
costed report. Write results atomically before recording successful completion.
A failed attempt remains a failed attempt even if some output files exist.

Acceptance: run from an isolated installed artifact outside the checkout; repeat
and resume reproduce declared results; malformed configuration, missing bytes,
interrupted report publication and incompatible checkpoints fail visibly. Compare
net return, turnover, drawdown and exposure only where the selected experiment's
observations support them. Reports must expose invalid/missing periods and limitations.

### Research comparison and extension

**MR 7.** Let QRs register compatible features, estimators and rules through narrow
public interfaces and configuration. Exercise a second genuinely distinct research
consumer and compare declared attempts with the same split/report semantics.
Shared runners must not acquire model-specific branches or copied notebook logic.

Acceptance: EDA, offline replay and formal backtest retain the same selection
identity; one compatible extension works without runner edits; two instances can
share immutable inputs while their mutable state, random streams, pending intents
and outputs remain isolated. Retain selection/rejection reasons and holdout use.
The maintained QR guide and activity notebook demonstrate this path with applicable
features/models; a rule-only example must remain possible.

### Frozen baseline acceptance

**MR 8.** Run `p1-btcusdt-return-v1` unchanged against the permitted actual source
and an isolated installed candidate. Resolve or explicitly leave unresolved the
[experiment's source and acceptance requirements](../research/p1-baseline.md#acceptance-and-research-discipline).
Saved ZIP integrity does not prove historical membership, coverage or revision
availability. Assumed event-time availability remains exploratory.

Acceptance requires the complete saved-source path, causal eligibility and revision
evidence, declared quality, exact no-trade/economic reconciliation, durable reports
and fresh-process reproduction. Synthetic software evidence is reusable for its
scope but cannot supply missing empirical source evidence. A negative costed result
can satisfy the engineering criterion; tuning the frozen experiment to pass cannot.
If a required source fact is unavailable, record the gap and leave acceptance open.

## Candidate promotion and operation

### Runtime feature parity

**MR 9, conditional.** Add incremental features only for a candidate that needs them;
a scheduled batch candidate can retain a qualified batch path. Use qualified inputs
with explicit clocks, cadence, missingness, late-data, warm-up and recovery behavior.

Acceptance: historical, replay and runtime feature/prediction traces agree under
the declared contract, including ordering, gaps, corrections and restart. Never
infer live readiness from the existence of a historical adapter. Keep one versioned
formula and explicit state compatibility; investigate the first divergence.

### Candidate packaging and runtime binding

**MR 10.** Freeze the [candidate contract](../architecture/platform-design.md#candidate-promotion-contract):
input requirements, features/preprocessing, optional model, signal-to-target policy,
state/warm-up rules and accepted experiment evidence. Retain artifact bytes as well
as hashes. A rule has no invented model artifact. Reuse the accepted components in
research and runtime applications; no translation into separate production formulas.

Acceptance: reconstruct a candidate from retained bytes without a notebook or
credentials; reject incompatible schemas, units, timing, state or outputs; bind a
compatible runtime input and reproduce matched decisions. Deployment configuration
selects candidate instances and resources separately from research selection and
trading authority. Retraining creates a new candidate and renews affected evidence.

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

### Measured storage and computation growth

**MR 20, conditional.** Revisit the reference reader or computation lane only when a
representative workload misses an accepted latency, throughput, memory or storage
budget. Compare verified end-to-end behavior, including loading, integrity, causal
selection, controls and retained lineage. Output batch size is not a total-RSS bound.

Use [query workload evidence](../../examples/notebook-operations.md#query-workload-evidence)
for its original measured scope; it does not benchmark current code. A Parquet scan
alone is not a replacement for the reader. Columnar/distributed/native/GPU paths
must preserve relevant exact arithmetic, timing, identity and recovery contracts.
Introduce durable stores, services or process isolation for measured consumers;
trusted research-code isolation is not a malicious-code sandbox.

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
