# Institutional platform roadmap

## Destination and current state

Build an institutional-grade monorepo for multi-asset, multi-strategy quantitative
research, simulation, portfolio construction, production trading and monitoring.
The founder implements it incrementally. Validated historical ingestion and EDA
are the first usable data deliveries; one reproducible strategy then exercises
the shared research/accounting foundations. These narrow deliveries retain
extension boundaries for the broader platform.

Today the runtime contains instrument identity, venue calendars, financial units,
exact serialization, event provenance, an authored reference catalog and bounded
Tardis/Binance event decoding. The frozen uv build, strict source checks, CI and
runtime wheel installation exist. Data acquisition, versioned datasets, strategy
runners, accounting, simulation, execution, deployment and monitoring are planned.
The current native dependency restriction is recorded in the
[architecture guide](../architecture/README.md#dependency-and-release-boundaries).

This roadmap owns priority, deliverables and capability status. The
[platform design](../architecture/platform-design.md) owns intended module
boundaries, interfaces, runtime lanes and scaling choices. The
[research program](research-program.md) owns experiment methodology and candidate
research workstreams. Preserve implementation detail in those documents and add
focused design notes where a complex feature needs them. Page and file counts
are maintenance observations, not a ceiling on technical design.

A monorepo provides shared source history, atomic changes and reusable contracts.
It can contain multiple packages, native libraries, applications and independently
released artifacts. It does not require every application to install the whole
repository, run in one process or deploy on the same schedule. Keep the current
single-package uv path until a concrete consumer justifies another package or
build target; retain a straightforward supported development entry point as it grows.

## Priority and completion model

The following P0–P7 areas describe maturity and long-term scope. Delivery follows
the [capability milestones](capability-milestones.md), whose M0–M7 identifiers
are distinct from these priority-area names. Dependencies are the interfaces actually
consumed by that slice, not completion of every row in a global package catalog.
A second strategy may expose a shared requirement before the first live release;
an asset-specific lifecycle belongs with the first strategy that needs it.

| Priority | Outcome | Current status | Depends on | Completion evidence |
| --- | --- | --- | --- | --- |
| P0 | Typed domain foundations and reproducible development | Three domain libraries and uv/CI implemented; bounded cleanup complete | Existing checkout | Existing contract tests, strict checks and isolated installed imports |
| P1 | One causal raw-data-to-net-report baseline | Data foundations partially implemented; end-to-end delivery planned | P0 and a permitted source | Saved inputs reproduce a hand-reconciled costed result without future information |
| P2 | Reusable research and multiple candidate strategies | Planned | M2 historical access; experiment/accounting interfaces as consumed | Two independently configured strategies share infrastructure without sharing mutable state; comparison is reproducible |
| P3 | Faithful simulation, asset accounting and replay | Planned | P1 accounting and the strategy's required market data; P2 interfaces where used | Deterministic order/fill/state traces, checkpoint parity, realistic costs and reconciled lifecycle events |
| P4 | One supervised paper-to-live production path with monitoring | Planned | Required P3 behavior, a venue adapter and release-admissible dependencies | Paper/shadow, restart, limits, alerts, stop and rollback exercised before bounded founder activation |
| P5 | Multi-asset, multi-strategy portfolio operation | Planned | Reusable research plus accounting/risk/operation for each selected instrument and venue | Combined exposures and costs reconcile; strategy failures and lifecycle differences are isolated |
| P6 | Scale research, builds, deployment and observability | Planned; pull forward only for an observed bottleneck | Measured workload and operating requirements | Faster or more reliable execution with parity, bounded cost, recovery and operable failure handling |
| P7 | Team ownership and organizational controls | Deferred; lowest feature priority, triggered by onboarding | Actual contributors, operators or external obligations | Responsibilities, access, reviews and handover exercised by the people who hold them |

Basic correctness and safety are part of P1–P6 implementation: data availability,
accounting, tests, secrets hygiene, loss/exposure limits, duplicate protection,
reconciliation, monitoring and recovery. They are needed when the corresponding
behavior becomes real. P7 covers staffing-dependent process: separation of duties,
independent approvals, formal model-risk review, access-review programs and audit
workflows. It does not create imaginary approvers for a one-person company.

## Usable delivery milestones

The [milestone implementation plan](capability-milestones.md#completion-and-dependency-model)
assigns the single MR 01–62 sequence to runnable outcomes, with MR 00 and C0
retained as completed prerequisites.
M0 resolves and exercises a fixture; M1 delivers validated historical ingestion;
M2 delivers selective EDA and replay. Live capture proceeds through M3 with
validation, monitoring and recovery included. M4 adds features and optional model
research; M5 delivers strategy simulation and research controls. M6 qualifies
paper/shadow operation and M7 qualifies specifically authorized live operation
and compatible expansion.

This order is a dependency graph. M2 EDA and M5 deterministic backtests do not
wait for M3 streaming or an ML platform; historical M4 work can start after M2.
Collection may start early for irrecoverable feeds with its basic controls intact.
Monitoring is part of each operational milestone, not a final platform add-on.
Completion requires the declared workflow and failure/extension evidence, not a
particular MR count. The original frozen P1 experiment remains unchanged.

## P1: first causal baseline

The [P1 implementation roadmap](p1-implementation-roadmap.md) maps the current
`main` foundations to pipeline ownership, reusable library operations and
bounded delivery slices with activity-based local notebook checkpoints and
acceptance evidence. It records the inspected base revision, identifies existing
abstractions to retain or retire, and separates current code from planned consumers.

The merged [MR 00 specification](../research/p1-baseline.md) selects Tardis raw
Binance BTCUSDT spot trades and the fixed one-minute positive-return baseline.
Source access, retention rights and historical eligibility/revision evidence
remain unresolved; selection does not authorize controlled data access. The
earlier digital-asset factor/residual idea remains a future research candidate.

The P1 [ownership map](p1-implementation-roadmap.md#p1-code-ownership-and-call-flow)
assigns acquisition, dataset building and research execution to explicit
orchestrator pipelines. Other implementation modules expose cohesive library
operations and records. Cleanup C0 has removed redundant decoder composition and
legacy import facades in the current checkpoint.

General names, explicit inputs and
[configuration-driven activation](../coding_standards/README.md#generalized-code-and-configuration-driven-activation)
are P1 requirements. Scoped config selects data jobs/universes and strategy
instances with their input dependencies; collection may exceed a strategy's
universe and does not grant trading authority. The frozen BTCUSDT case is one selection.
Compatible asset onboarding should change config/reference data; a new strategy
adds its implementation and config. Shared code changes only for missing
capabilities, with focused tests at the affected boundary.

Implement the following small slices together with their concrete types and tests:

| Slice | Implementation detail | Decisive evidence |
| --- | --- | --- |
| Configuration and onboarding | Typed definitions and explicit active instances with implementation, asset, parameter and data bindings; pipelines resolve and compose supported selections | Another supported synthetic asset and a compatible test strategy use the same orchestration; inactive selections do not execute and unsupported bindings fail |
| Time and event identity | Aware event/receipt/ingestion/availability times, valid interval, source revision, source sequence and deterministic tie-breaking; distinguish what happened from what was knowable | Late publication, future corrections, repeated timestamps and timezone boundaries cannot alter an earlier decision |
| Raw ingestion | One adapter, immutable raw-object digest, request/range manifest, restart checkpoint, bounded retry and explicit gap/duplicate handling | Interrupt and resume a download without inventing, losing or duplicating observations; mutated input fails identity checks |
| Canonical dataset | Normalize vendor identifiers and units at the adapter; preserve source lineage, historical membership, exclusions and correction policy; publish a versioned snapshot atomically | Rebuild the same snapshot and perform as-of selection by availability time; schema or quality failures stay out of published data |
| Strategy input and output | Explicit context containing strategy/version, data/config identity, clock and random seed; signal or target output with horizon and units | The same context reproduces decisions; changing a strategy configuration cannot silently replace an earlier run |
| Baseline accounting | No-trade plus one transparent baseline; declared fill delay/price, quantities, fees, positions, cash, financing where applicable and gross-to-net attribution | Hand-calculated buy/sell, no-trade, cost-sign and valuation examples reconcile to the report |
| Run and report | A callable runner over the existing libraries, a small append-only trial record and durable output references | An independent process reproduces the net report from the saved command and identities |

These are proposed implementation slices, not existing module names or commands.
Prefer files, typed records and local functions/classes until concurrency or
operating needs justify a service. Build only the required market representation:
a daily baseline need not first implement an order-book exchange simulator.

## P2: shared research and strategy development

Use M2 historical data access to develop features/models in M4 and research
controls in M5. Fitting and comparison work does not require the entire original
baseline or live platform to finish first:

- Separate dataset/universe selection, feature and label generation, transforms,
  model fitting, signal generation, portfolio targets and execution assumptions.
  Keep strategy-specific formulas in their own modules; common infrastructure
  must not become a configurable container for every strategy's private logic.
- Define immutable strategy, model, feature, config and trial identities. Give
  each running strategy instance a distinct identity and state even when it uses
  the same implementation. Start the strategy catalog as small versioned records.
- Make train/validation/holdout splits explicit, with purging and embargo where
  information horizons overlap. Fitted transform state, model artifacts and
  preprocessing versions travel together from training to inference.
- Implement comparable baseline/challenger reports: net return and risk, turnover,
  costs, drawdown, capacity assumptions, exposures and stability across time.
  Preserve all comparison attempts and account for selection over related trials.
- Add batch parameter sweeps with deterministic seeds, resumable trial IDs,
  resource limits and cache keys derived from complete input identity. A cache
  hit must never substitute a result computed under another dataset or cost model.
- Keep notebooks as consumers of the same package APIs used by the batch runner.
  Extract selected calculations from notebooks before making them production
  dependencies; exploratory notebooks may evolve faster than deployed code.

Extend the P1 onboarding proof to two strategies with different configurations
and horizons using the same data/accounting/reporting code. Exercise concurrent
runs, changed schema versions and failed runs. Decide whether a shared abstraction is useful
from those consumers. Detailed research families and experiments live in the
[research program](research-program.md); a strategy uses only relevant families.

## P3: simulation, accounting and replay

Build fidelity appropriate to the intended production strategy and asset:

- Own deterministic event order, injected clock and named random streams.
  Persist enough event/input identity and checkpoint state to reproduce a run.
  A resumed run must agree with uninterrupted execution under declared tolerances.
- Model order intent, submission, acknowledgement, partial/full fill, cancel,
  replace, rejection, expiry and unknown outcomes. Preserve stable identifiers
  across retries; define duplicate, delayed, out-of-order and bust/correct rules.
- Make execution assumptions pluggable: bar-based delayed fills, trade/quote replay,
  then book/queue and latency models only where the hypothesis depends on them.
  Explicitly identify what each model cannot establish about live execution.
- Use common accounting rules for orders, fills, positions, cash, fees, FX,
  realized/unrealized P&L and instrument lifecycle. Add corporate actions, expiry,
  exercise/assignment, rolls, funding, borrow or margin with the selected asset.
- Model spread, impact, fee tiers, liquidity, financing and capacity with versioned
  calibration inputs and sensitivity bounds. Report unknown venue behavior as a
  limitation, not an assumed favorable fill.
- Replay market/data interruptions, session changes, stale references, bad books,
  funding/fee changes and process failure. Retain minimal deterministic scenarios
  alongside independent accounting goldens and framework differential checks.

The selected strategy's signal and decision logic must be shared across research,
replay and operation. Vectorized research implementations may coexist with event
runtimes when their outputs agree for the declared inputs, timing and numerical
contract. No rewrite may silently change timing, state transitions or accounting.
Evaluate external simulator reuse against these traces before adopting its types
or replacing an owned boundary.

## P4: productionization and monitoring for one strategy

Research success leads first to a paper adapter and shadow execution that cannot
send executable orders. Add the real venue path only after the relevant behavior
has been exercised. Implementation includes:

1. An application entry point composing strategy, portfolio, risk, OMS and adapters
   through explicit configuration. Startup rejects incompatible schema/state,
   missing inputs and unreconciled positions. Dependency source or release
   restrictions must be resolved before the artifact lifecycle can proceed.
2. A broker/venue session boundary for sequencing, throttles, reconnect and replay.
   Treat a send timeout as an unknown outcome; query/reconcile before retrying.
   Prevent concurrent processes from owning the same executable session by using
   an explicit single-writer policy and fencing where needed.
3. Durable OMS state and a journal supporting duplicate suppression and restart.
   Compare order/fill records with venue state and drop copy where available;
   maintain observable breaks and a safe response until reconciliation succeeds.
4. Risk checks outside strategy logic, covering pending orders as well as fills:
   quantity/notional, strategy and account exposures, loss, price bounds,
   liquidity/rate limits and stale input. A strategy cannot raise its own limits.
5. One immutable artifact/config identity, one deployment target and an explicit
   founder activation record. Exercise installed imports, state compatibility,
   bounded paper/canary duration, exposure, stop conditions and post-run checks.
6. Operational metrics and actionable alerts: feed freshness, heartbeat, queue lag,
   rejects, disconnects, reconciliation breaks, exposure/loss and execution/P&L
   drift. Every alert identifies the instance and the defined response; test
   delivery and the safe behavior when the founder is unavailable.
7. Stop/cancel, restart, backup/restore and rollback commands tested against the
   actual state model. Retain the prior usable artifact and compatible state;
   do not claim rollback can undo filled orders or an irreversible migration.

Deployment, activation, monitoring and recovery commands remain planned. Add their
actual invocation, target, thresholds and expected failure behavior to the
[operations runbook](../governance/operations.md) when implemented. These runtime
behaviors are required for operation even while the founder is the only member.

## P5: multiple strategies, assets, accounts and venues

Expand one supported dimension at a time, keeping an explicit support matrix.
A common identifier or schema is not evidence that an instrument is correctly
modeled or executable at a venue.

| Expansion | Required implementation | Evidence before operational use |
| --- | --- | --- |
| Second strategy in one account | Per-instance state, budgets and positions; allocation/netting policy; pending-order reservations; attributable fills and shared costs | Combined book reconciles to broker cash/positions and to strategy allocations; stopping one strategy preserves the other's correct state |
| Multiple accounts or venues | Account/venue identity on each instruction; isolated credentials/sessions; scoped limits and venue-specific recovery | Failure of one adapter cannot duplicate or misroute orders elsewhere; combined exposure is consistently measured |
| Equities | Corporate actions, symbol/universe history, dividends, splits, delistings, borrow/recall and settlement | Historical membership and cash/quantity transformations reconcile across lifecycle dates |
| Futures | Contract chain/roll rule, multiplier, expiry, variation margin and session calendars | Continuous-series research maps back to actual tradable contracts; cash and roll attribution reconcile |
| Listed options | Contract/underlying identity, volatility/valuation context, exercise/assignment, expiry, Greeks and nonlinear stress | Independent pricing/lifecycle goldens and hedging/exposure scenarios agree within declared numerical budgets |
| FX, rates and credit | Quote/settlement conventions, calendars, curves, carry/cashflows and instrument-specific lifecycle events | Currency, fixing, day-count and valuation-date changes have explicit accounting and exposure effects |
| Digital assets where selected | Venue-specific funding, collateral, liquidation, continuous sessions and custody/transfer or chain behavior where applicable | Outages, collateral impairment, funding changes and discontinuous liquidity are modeled and reconciled |

Introduce portfolio allocation across strategies with explicit capital/risk budgets,
constraint precedence and feasible fallbacks. Measure correlation, concentration,
liquidity, turnover, shared financing and nonlinear stress at strategy and combined
book levels. Preserve raw strategy intent alongside net executable orders so
internal netting cannot hide attribution, limit usage or a failed strategy.
A new asset uses its own lifecycle and simulator extensions; common infrastructure
shares interfaces and proven semantics without forcing unlike products into one
universal model.

## P6: research and operating scale

Treat scale engineering as an explicit capability workstream. Pull a slice forward
when its trigger is measured; it does not require hiring first.

| Observed trigger | Implementation direction | Validation |
| --- | --- | --- |
| M2's selective embedded queries no longer meet memory/storage, concurrency or latency needs | Extend the existing query contract with object storage, a service or an appropriate table/catalog backend | Same as-of results and identifiers; interrupted publication/backfill is recoverable; cost and read amplification are measured |
| Trial throughput or GPUs are the bottleneck | Queue-backed CPU/GPU workers, immutable run inputs, resource quotas, cancellation, checkpoint/resume and explicit retry ownership | Worker loss/reschedule cannot overwrite or duplicate a trial; resumed outputs and numerical tolerances remain comparable |
| Native code or cross-language generation becomes material | Admit a pinned compiler and narrow ABI; generate schemas reproducibly; add conformance, sanitizer/fuzz and installed-artifact checks | Shared golden traces and errors survive the boundary; compiler/platform identity explains performance or numerical changes |
| Build duration or dependency coupling slows multiple applications | Target dependency graph, selective CI with coverage evidence, trusted caches and hermetic execution where justified | Relevant reverse dependencies are checked; generated inputs and clean installs agree; missing/stale cache data cannot produce a false pass |
| Several deployments need reliable rollout | Independent artifact/config releases, declarative host/environment setup, staged deployment and state/schema migration | Unrelated strategies stay on their selected revision; rollback and restart compatibility are exercised |
| Existing milestone telemetry no longer provides sufficient visibility across operating instances | Scale metrics/logs collection and operator views, retain bounded cardinality and identity correlation, add tracing where useful | Alerts survive collector/node failure; telemetry cannot block trading; aggregate queries retain per-instance attribution |
| Measured latency or burst behavior exceeds the strategy budget | Profile first, then compiled kernels or a dedicated native event loop; define hardware/clock/network assumptions | Tail latency and jitter under representative load, bounded queues, overload response and numerical parity |

The current uv path, lock and strict checks remain authoritative until a
replacement or extension has proved a required capability. Native toolchains,
remote build/execution, Kubernetes, specialized storage and distributed services
are implementation options with explicit triggers, not permanently prohibited
technologies or immediate startup prerequisites.

## P7: organizational controls as people join

This is the last priority for speculative implementation. Start a small applicable
slice when an actual contributor or operator joins, rather than delaying essential
access setup until all P6 work is complete.

- For another contributor: grant individual repository access, define concrete
  module ownership and review expectations, document setup, and test a handover.
  Use the forge's existing mechanisms before building any internal registry.
- For another operator: separate research/deploy/trading credentials, define
  incident coverage, scope production actions and access revocation, and test
  operational handoff. Add approval rules only where two real authorized people
  can fulfill them.
- With dedicated research/risk/operations responsibilities: add genuinely
  independent model validation, limit/activation decisions, separation of duties,
  periodic access reviews and formal incident or change review for that scope.
- With external capital, contractual or regulatory obligations: map the applicable
  requirements and evidence to the actual business. Obligations follow their
  applicability, not an assumed employee-count exemption.

The founder currently owns implementation and a separate activation decision.
Do not recreate staff tables, universal R0–R4 classification, mandatory synthetic
per-package evidence packs or a program-status service in order to claim maturity.
Introduce a control with its concrete trigger, owner, enforcement point and test.

## How to execute and maintain the plan

The bounded governance cleanup is complete, and
[MR 00](../research/p1-baseline.md) has frozen the first source and hypothesis.
The [C0 cleanup](p1-implementation-roadmap.md#c0-remove-redundant-composition-before-adding-consumers)
is implemented in the current checkpoint. Continue with MRs 01–02, then
the dependency-ordered [milestone packages](capability-milestones.md). Historical
ingestion closes only with normalization, validation and publication; the earlier
raw-download command remains a useful intermediate checkpoint. For each slice, record the input/output contract,
affected modules and consumers, persisted identities, critical failure behavior,
selected tests and a working command or artifact. Update its status here when
that evidence exists. Keep future work explicitly planned.

During local development run only relevant tests and static checks; hosted CI
retains the complete required lane. Existing commands are listed in the
[documentation home](../README.md). There is no executable backtest, paper or live
command yet. Neither this roadmap nor a page-count reduction establishes delivery.

## Public engineering references

The following public accounts inform the design direction; the phase sequence
and proposed modules above are this repository's design judgment. They are not a
reconstruction of any firm's private platform or a requirement to copy its stack.
Reviewed on 2026-09-07.

- HRT describes most development occurring in a monorepo and the startup costs
  that arose as Python dependencies grew. This supports retaining shared-code
  architecture and measuring dependency costs as the platform expands.
  [Inside HRT's Python Fork](https://www.hudsonrivertrading.com/hrtbeat/inside-hrts-python-fork/).
- Jane Street describes monorepo libraries and reproducible deployed Python
  environments with independently managed lifecycles. This informs the separation
  between shared source and application release identity.
  [Building reproducible Python environments with XARs](https://blog.janestreet.com/building-reproducible-python-environments-with-xars/).
- Two Sigma describes versioning transformations/data infrastructure, automated
  data-quality checks and lineage as engineering concerns. This supports making
  data reliability a functional platform capability from the first dataset.
  [Treating Data as Code at Two Sigma](https://www.twosigma.com/articles/treating-data-as-code-at-two-sigma/).
- HRT describes scaling monitoring for research and trading workloads, including
  availability and query tradeoffs. This informs a staged observability path.
  [Scaling Prometheus](https://www.hudsonrivertrading.com/hrtbeat/scaling-prometheus/).
