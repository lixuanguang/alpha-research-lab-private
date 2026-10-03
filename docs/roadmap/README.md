# Platform infrastructure roadmap

Owner: repository founder; quant development owns infrastructure delivery.
Status updated 2026-09-27. Delivery policy: complete the initial research and
paper-trading infrastructure before quant researcher (QR) onboarding. Live trading
is **KIV (keep in view)** under the [reconsideration gate](#live-trading-kiv-and-reconsideration).

This index owns delivery status, remaining work and dependencies. Component
guides own implemented behavior; the milestone sections below retain only the
current accepted scope and qualification limits. One-off delivery narratives,
commands and evidence identities remain available in Git history.

The completed MR09A saved-book baseline retains its historical identity. The
remaining work uses MR01–MR17, with MR07A/MR07B extending the completed MR07
increment without renumbering later milestones. MR01–MR14 (including MR07A/MR07B)
are complete for the bounded scopes stated below. MR08/MR11 include installed
OKX/Bitfinex public-input paper matching, independent reconciliation and exact
cost/P&L reports. MR10 and MR14 accept the trusted local supervised paper/shadow
service envelope, with separately signed account owners and retained failure and
recovery evidence. MR12 retains bounded monitoring, and MR13 retains signed local
activation and latest-journal recovery. Native authenticated test-venue
qualification remains unavailable and KIV; its software evidence is separate.
MR15–MR17 remain open, including capacity, ownership enforcement and QR handoff.
P1 stays deferred and unaccepted.

This revision replaces live-capable delivery with paper-trading delivery.
Feature-store, portfolio/netting, second-venue market-data and paper simulation,
dashboard, capacity and handoff requirements retain their stated acceptance gates.
All MR01–MR17 outcomes,
including MR07A/MR07B, remain mandatory within the revised paper scope before
formal QR onboarding. Removing live qualification from that scope does not mark
later operating milestones complete or change historical evidence.

The [QR implementation guide](../../examples/README.md) explains how researchers
use the available capabilities. The [research program](research-program.md) owns
post-handoff QR milestones, deliverables, methodology and experimental choices.
The [platform design](../architecture/platform-design.md)
owns shared contracts.

## Current platform

The supported research path is configured acquisition or capture → retained raw
inputs → validation and versioned publication → explicit snapshot queries/replay
→ EDA, model studies or configured bounded spot economics → retained costed
reports. The installed [public-paper application](../../src/applications/paper/README.md#automatic-public-input-accounts)
now connects native books to reference decisions, portfolio/risk, paper matching,
attributed ledgers, independent reconciliation and retained cost/P&L evidence.

The [data command reference](../../src/market_data/README.md) owns current
invocations. The [saved L2 workflow](../research/l2-book-backtest.md)
owns the implemented OKX simulation scope and its limitations. No empirical
strategy, remote/general service or live trading acceptance is implied by the
current platform. The bounded signed local service scope is qualified below.

Current evidence is bounded: the accepted OKX simulation covers a 10,000-message
prefix with modeled delivery clocks, not known historical receipt or continuity.
Its instances have separate simulated accounts. Identity/calendar/unit contracts,
immutable datasets, experiment history and exact spot accounting remain reusable
foundations. MR04 now qualifies local offline/online feature serving and retained
workspace/job services. Local shared-account coordination and a durable paper OMS
operate within the accepted supervised service envelope. Authenticated venue
operation, general service deployment and measured runtime capacity remain open.
Library registries also require end-to-end consumer acceptance before claiming
general extensibility.

## Infrastructure completion before QR onboarding

Quant development must deliver and integrate every infrastructure layer in the
initial scope before the QR is expected to use it. A selected alpha, successful
model, completed QR backtest or QR-authored dashboard is not a prerequisite for
infrastructure work. Quant development supplies executable reference consumers
and acceptance workloads wherever those dependencies previously appeared.
The existing capabilities establish useful bounded foundations for this gate.

The initial market scope is **OKX/Bitfinex spot**, with explicit extension
interfaces for other assets. It includes historical and captured market data,
reference data, research and model lifecycles, backtesting, portfolio/account
state, paper/shadow execution, paper service deployment, monitoring, recovery
and the storage/computation needed to run them. Supported venue operations,
order types, dataset history, workload sizes and operating modes must be stated
in each capability's acceptance record. Both venues need explicit conformance
evidence for their declared market-data and simulated execution support; one
venue's pass does not qualify the other. Paper trading uses live public inputs
and simulated orders, fills, balances and positions without real-capital orders.
Shadow mode supplies decision comparisons but cannot replace paper fill/account
and cost evidence. Authenticated venue execution is outside this initial gate.

The destination remains a generalized multi-asset, multi-source, multi-strategy
monorepo. Required infrastructure includes a versioned feature store with offline
PIT retrieval and online materialization/retrieval, experiment/model/artifact
tracking, dataset versioning, concurrent job services, allocation and compatible
netting, paper execution for both venues, extensible reports/dashboards and recovery.
Preserve and extend the existing Feast, lakeFS, ClearML, search and analytical
integrations through their owned interfaces. Their present bounded support does
not complete the generalized capability; technology changes require equivalent
behavior and migration evidence rather than deleting the capability.

Generalization means localizing differences behind working typed contracts.
Support both target-position/exposure decisions and order/quote intents through
the same portfolio, risk, OMS and accounting boundaries. Support named market
and non-order-book inputs without forcing them into one feed representation.
Shared contracts must permit multiple deployment artifacts, compatible runtime
environments and independent release cadences. A particular directory layout or
one dependency resolution for incompatible workers is not required.

Other asset adapters and lifecycle mechanics, derivatives, borrowing, on-chain
execution and specialized native low-latency infrastructure are later scope.
Their neutral interfaces must preserve units, currencies, product capabilities
and lifecycle distinctions, and reject unsupported behavior. Extensibility does
not claim that those products already work. The gate requires working capabilities,
not a particular database, event bus, dashboard vendor or distributed topology.

Infrastructure completion, empirical strategy acceptance and trading activation
are separate outcomes. Quant development qualifies the machinery with engineering
workloads, including losing/no-trade cases. QR later supplies and evaluates the
research content. Executable credentials, purchases, deployment and live capital
retain their existing separate authority; this plan does not authorize them.
An unavailable required data or paper service integration remains an explicit
blocker to that capability's qualification, while independent work continues.
Unavailable private venue credentials or live qualification do not block paper
delivery or QR onboarding. Existing test-venue adapters and their software evidence
are retained; using an external demo/paper account is supplementary and does not
establish live execution fidelity.

## Live trading KIV and reconsideration

Live trading development, production order routing, authenticated venue execution
qualification, live account recovery and real-capital activation are parked as
KIV. They are outside MR17/G5 and are not prerequisites for QD's paper delivery or
QR onboarding. Preserve existing interfaces, adapter code and evidence without
claiming that deferred live requirements are complete.

Reconsider live trading only when the same frozen strategy has **both** untouched
out-of-sample (OOS) test evidence and forward paper-trading evidence demonstrating
profitability net of transaction costs, slippage and applicable digital-asset gas
fees. Gross returns, an in-sample backtest, shadow decisions or engineering
fixtures cannot satisfy this gate. QR owns the candidate-specific evaluation and
evidence through [QR-15–QR-18](research-program.md#stage-d--surviving-candidate-validation-and-handoff);
QD owns the paper runtime, cost-model interfaces, reconciliation and retained
reports needed to evaluate it.

Predeclare evaluation periods, sample sufficiency, selection and stop criteria,
cost assumptions and adverse cost/slippage scenarios before testing. Retain net
P&L, cost attribution, risk/capacity limits and uncertainty against those criteria;
do not choose thresholds after inspecting OOS or paper results. Charge gas for
required on-chain activity, including relevant transfers or failed transactions;
record a reason when gas is inapplicable to an off-chain spot strategy. Missing
cost evidence is unresolved, not a zero-cost assumption. On-chain execution
adapters remain later scope.

Passing this evidence gate permits a decision to reopen live work; it does not
qualify exchange fills or authorize deployment or capital. Any reopened live scope
needs its own venue, security, execution and recovery qualification and the
existing explicit activation decision. Until then, live trading stays KIV.

## Platform and researcher responsibilities

| Boundary | Quant development delivers before onboarding | QR supplies through the delivered interfaces |
| --- | --- | --- |
| Data | Source adapters, reference/universe contracts, collection/backfill, quality, revisions, discovery, PIT assembly, storage and replay | Research universe, datasets/fields, sample, horizon and stricter question-specific quality requirements |
| Features and labels | Typed extensible definitions, execution/alignment, lineage, fitted-transform lifecycle, batch/incremental state, versioned offline/online feature-store access and recovery | Formulas, targets, windows, transformations and missingness choices within the supported contracts |
| Models and rules | Training/inference adapters, temporal evaluation/search, artifact reload, prediction-to-target/order-intent binding and isolated state | Estimator/strategy implementations, parameters, comparison space and selection criteria |
| Backtesting | Reusable study runner, execution/cost model interfaces including transaction costs, slippage and applicable gas fees, portfolio/risk/accounting, checkpoints and net-of-cost analysis | Backtest specifications, hypotheses, scenarios, economic assumptions and interpretation |
| Metrics and charts | Versioned metric/result contracts, computation, query/export, report/dashboard rendering and alert evaluation | Research metrics, chart definitions, diagnostic views and strategy-specific thresholds |
| Paper promotion and operation | Candidate loading, trusted artifacts, provisioning, scheduling, paper OMS/execution, reconciliation, limits, stop, recovery and cost-attributed paper reports | Candidate content, OOS and forward paper evidence; investigation and proposed revisions |

QR-authored strategies, features, estimators, backtest specifications, metrics and
charts within the advertised support boundary must work through public library
APIs/configuration without edits to shared runners, storage, execution or telemetry.
Independent hard risk limits and operating authority are not QR extension points.
A genuinely new asset mechanic or source protocol remains quant development work;
an unimplemented promised extension point is an infrastructure defect, not a QR
onboarding task.

## Quant development reference workloads

Quant development owns the first consumers and keeps them executable alongside
the platform. They are engineering examples, not research recommendations:

- A rule-only spot study over retained books, a no-trade control and a deliberately
  losing/cost-sensitive case exercise decisions, fills, accounting and reports.
- A learned example with multiple named features and fitted preprocessing exercises
  train-only fitting, labels, temporal evaluation, artifact reload and predictions
  flowing into targets. A stateful feature/rule exercises warm-up and restart.
- Multiple instruments and two distinct active strategies exercise selection,
  scheduling, target and order/quote intents, competing risk requests and attribution
  on a shared paper account. Separate simulated accounts and a no-trade control
  do not establish shared-budget or conflicting-order behavior.
- One versioned feature definition exercises offline retrieval, incremental
  materialization and online serving with matched-cutoff parity, revisions,
  missing entities, staleness, restart and rollback. Reuse the existing Feast
  bridge and source semantics; vendor event-time joins cannot invent knowledge.
- A custom metric and chart exercise retained research reports and runtime
  dashboards; missing/late observations and an alert exercise failure semantics.
- A small non-order-book dataset and a non-24/7 calendar or different product
  economics fixture exercise the shared interfaces and explicit unsupported
  behavior. This establishes extension boundaries, not another live asset class.

Use small independent fixtures for exact/causal/failure proofs and permitted
saved or test-environment inputs for actual adapter/service boundaries. Extend
these same consumers for scale and recovery instead of building a parallel demo
platform. Fixtures cannot establish historical availability, source completeness,
venue execution fidelity or empirical alpha. Unknown facts remain explicit.
Reference implementations live under existing functional owners and examples;
their concrete use satisfies the requirement for a working consumer before an
abstraction is added. No QR hypothesis or profitable result is needed.

## Future-MR data policy

All future MRs must avoid Binance and Tardis data because of availability
constraints. Use OKX or Bitfinex where the required data and implemented
capabilities are available; start L2 work from the saved OKX order-book workflow.
New acquisition, research examples and acceptance evidence must not depend on
Binance/Tardis access or provider outreach. If neither preferred source supports
the required scope, record the gap and select an available alternative explicitly;
do not silently fall back to Binance/Tardis or claim unsupported source quality.

Existing Binance/Tardis adapters, fixtures and P1 evidence retain their original
identities for historical compatibility. They do not set the source choice for
new MRs. Further P1 investigation and provider outreach remain deferred.

## Closed delivery summary

The completed saved-book baseline retains its historical identifier separately
from the restarted roadmap below. Existing data, research and accounting
capabilities are described by their owning component guides.

| Historical milestone | Closed capability | Current meaning |
| --- | --- | --- |
| MR09A | [L2 order-book backtesting](../research/l2-book-backtest.md) | Saved OKX ETH-USDT EDA and IOC backtesting |

## Incremental acceptance gates

These gates are checkpoints within the complete delivery commitment. A gate
qualifies only its stated scope; it does not declare all contributing MRs complete
or replace MR17. Quant development owns the reference consumers at every gate.
Formal QR onboarding still requires the full stack; research-ready engineering
acceptance can be established earlier without waiting for execution adapters.

| Gate | Observable acceptance | Delivery boundary |
| --- | --- | --- |
| G1 — Foundation and contracts | Clean installed build; typed configuration; four distinct universes; versioned reference and adapter capability admission; incompatible inputs rejected before work. | Existing foundations plus MR01/MR02/MR16 contracts. Current domain tests are reusable evidence, not a pass for new contracts. |
| G2 — Research-ready increment | From a clean workspace, acquire/capture the declared inputs, publish pinned datasets, retrieve versioned offline features, add a fresh compatible strategy/feature/model, run temporal studies and costed backtests, and reopen results. Meet the declared research workload and restore data/artifacts. | MR01–MR03; MR04 research/feature-store services; MR15 research budgets. MR06 precedes any actual service deployment. Online serving and operating scope remain required at later gates. |
| G3 — Paper/shadow increment | Reuse decision components on live inputs with submission suppressed; exercise online features, durable order state, independent risk, base reconciliation, essential alerts and restart. | MR04 online path, MR05–MR08, applicable MR10/MR12 controls and MR06 installation. Initial dedicated-account evidence does not qualify shared accounts. |
| G4 — Integrated paper operating infrastructure | Qualify shared paper-account controls/netting, both venues' paper execution models, cost attribution, monitoring, scoped paper activation and operational failure drills in the selected paper environment. | MR09–MR14 and runtime MR15 budgets. Both venues' public inputs and paper behavior remain mandatory; private venue execution qualification is KIV. |
| G5 — Generalized paper handoff | Demonstrate fresh extensions through the installed integrated stack, all research/paper launch workloads, data/service evidence and the operator/researcher guides. | MR17, after every in-scope MR01–MR16 outcome, including MR07A/MR07B. This accepts research/paper infrastructure; profitability and live reconsideration are subsequent outcomes. |

## Delivery order and dependencies

All rows below are required within the research/paper scope for the initial
infrastructure gate. The restarted numbering follows delivery scope: MR01–MR04 close research/data usability gaps left by
the bounded foundations, and MR17 proves the integrated QR handoff. Quant development
owns every row. Dependencies are technical capabilities and reference workloads,
not progress in the [research program](research-program.md).

### Research and data foundation completion

| MR | Planned delivered behavior and sufficient completion evidence | Dependencies |
| --- | --- | --- |
| MR01 | **Generalized data/reference plane with OKX/Bitfinex qualification.** Extend `market_data`, `reference_data`, configuration and data applications with selected public trades and books, configurable capture/backfill, versioned venue specifications, catalog discovery, pinned selections, quality/coverage inspection and causal multi-input assembly. Separate collection, research, strategy and authorized-trading universes. Declare typed market-data/reference/calendar capabilities and preserve source-specific time, sequence and depth semantics. Resolve the specification valid and known for an observation/order; unknown history remains explicit. From a clean workspace, discover/read/replay inputs and recover interrupted ingestion without notebook-created manifests or invented clocks. | Existing data access/attempt contracts and MR09A; source policy and declared source access |
| MR02 | **Generalized research and decision contracts.** Extend `research.features`, `labels`, `models`, `observations` and `strategies` beyond fixed return/linear schemas: named trade/book/non-book inputs, multi-feature schemas, fitted transforms, estimator/state adapters, predictions-to-targets or order/quote intents, and batch/incremental lifecycle. Define feature entity/version/availability interfaces for MR04 and declare required capabilities for candidate admission. Run rule-only, learned and stateful reference consumers through the public contracts; future perturbation and restart preserve semantics. | MR01 and existing feature/model/split owners |
| MR03 | **Complete study/backtest/report APIs — complete for the [declared offline scope](#mr03-delivery-and-acceptance).** Extend `research.studies`, `experiments`, `simulation` and applications with typed in-memory and serialized configuration, injected compatible implementations end to end, explicit local/deferred publication, typed result readers, temporal/walk-forward evaluation, parameter search, configurable execution/cost models and custom metrics/charts. Exercise target and order-intent strategies, including declared passive-fill/queue assumptions and sensitivity cases. A fresh feature/rule/model reaches the installed workflow without shared orchestration edits or replacement by a built-in default; attempts, exclusions and holdout history survive failures/publication retries. | MR02; reuse existing accounting/risk and reports; offline order-lifecycle contracts do not wait for a deployed OMS |
| MR04 | **[Feature store](../architecture/research-and-simulation-design.md#feature-store-contract), reproducible workspace and job services — complete for the [declared local scope](#mr04-delivery-and-acceptance).** Provision versioned data/artifact/experiment stores and offline/online feature-store paths, with causal historical retrieval, incremental materialization, entity/schema/version validation, freshness/TTL and missingness, idempotent retry, restart and rollback. Extend the isolated Feast integration and pinned lakeFS/ClearML paths while preserving independent compatible environments. Deliver scheduling/cancellation/retry, bounded concurrent workers, secrets references, backup/restore and service health. A clean workspace reopens studies and matched-cutoff features without manual repair or replacing an active worker; job failure cannot duplicate effects. | Start from existing local services and offline bridge; MR02 feature contracts and MR01 inputs; integrate MR03; qualify online consumption with MR05/MR07; MR06 before deployment |

### MR01 delivery and acceptance

Complete for the declared read-only data/reference scope. The
[market-data guide](../../src/market_data/README.md#public-spot-data-plane) and
[data contracts](../data/contracts.md#versioned-venue-specifications-and-scoped-universes)
own the current interfaces. Qualification covers bounded OKX/Bitfinex public
spot trades and books; it does not establish a complete historical tape,
historical receipt reconstruction, Bitfinex book backfill or private execution
conformance. Current endpoint metadata cannot establish earlier venue rules.

### MR02 delivery and acceptance

Complete for the declared research/decision SDK scope. The feature, observation,
model and strategy component guides own the interfaces. Retained OKX/Bitfinex
spot projections qualify the initial source path; non-book and different-product
fixtures qualify extension/refusal behavior rather than another live asset class.
Supplied component code remains trusted, and no empirical strategy, runtime or
production qualification follows from this scope.

### MR03 delivery and acceptance

Complete for the bounded offline study/backtest/report scope documented by the
[study guide](../../src/research/studies/README.md#generalized-decision-studies)
and [simulation guide](../../src/simulation/README.md#offline-decision-intent-studies).
Current support is cash-funded spot, at most 32 folds, 1,024 decisions per
schedule and a 1–32-variant grid. Passive queue/latency behavior is a synthetic
sensitivity; saved public inputs and authored Bitfinex grids do not qualify
exchange fills, historical completeness or venue rules.

### MR04 delivery and acceptance

Complete for the declared local feature-store, workspace and job-service scope.
The [feature-store contract](../architecture/research-and-simulation-design.md#feature-store-contract)
and component guides own behavior and recovery. Qualification is one trusted
local POSIX workspace with independently locked environments and loopback
development services; it does not establish shared-host authentication,
distributed leases, arbitrary external exactly-once execution, deployment or
launch capacity. Historical corrections still require an authored availability
clock.

### MR05 delivery and acceptance

Complete for candidate packaging and local intent-only runtime binding. The
[candidate promotion contract](../architecture/research-and-simulation-design.md#candidate-promotion-contract)
and runtime/component guides own the interfaces. Registry contracts preserve
general product and source identities, but unimplemented economics fail closed;
the OKX/Bitfinex profiles are read-only and do not establish private execution,
empirical alpha, capacity or deployment readiness.

### MR06 delivery and acceptance

Complete for independent operating packages and trusted local installation under
the [release workflow](../governance/workflow.md#build-a-release) and
[operating runbook](../governance/operations.md#trusted-local-installation).
Qualification covers the declared trusted local Darwin arm64, CPython 3.14.7
profile and independent collector/execution closures. Linux and remote deployment,
production key provisioning, live orders and capital activation remain unqualified.

### Runtime, operations and handoff

| MR | Planned delivered behavior and sufficient completion evidence | Dependencies |
| --- | --- | --- |
| MR05 | **[Candidate packaging and runtime binding](../architecture/research-and-simulation-design.md#candidate-promotion-contract) — complete for the [declared local scope](#mr05-delivery-and-acceptance).** Package rule-only and learned reference candidates with input/feature-store/state/metric contracts and target or order/quote outputs; load the same components into replay and runtime. Resolve a typed capability registry for market data, reference data, calendars, valuation, account and execution interfaces; reject unsupported product/channel/order/freshness combinations before startup. Bind dataset → experiment → candidate → deployment identities without granting authority. | MR02–MR03; integrate MR04 serving interfaces and MR11 conformance when available |
| MR06 | **[Independent deployable packages and trusted installation](../governance/workflow.md#build-a-release) — complete for the [declared local scope](#mr06-delivery-and-acceptance).** Build, verify, install and roll back pinned artifacts/configuration/state on the declared target; reject provenance, dependency, signature and compatibility failures. Prove that collector/execution applications install without unrelated research, notebook, training or reporting dependencies; shared contracts and independently locked workers retain compatible versions and release cadences. Resolve current release restrictions and verify research/shadow credentials cannot submit production orders. | Existing build/admission and MR16 package contracts; MR04 local environment profile supplies the target; MR06 does not wait for full MR04 or MR16 completion |
| MR07 | **[Paper/shadow runtime and OMS](../architecture/portfolio-and-execution-design.md#oms-and-venue-adapter-design) — complete for the [declared local scope](#mr07-delivery-and-acceptance).** Supervise candidates with lifecycle callbacks, timers, market/account/order events and checkpointed instance state. Bind live inputs/features and a durable order-intent journal; support target and order/quote decisions, partial fills, rejects, cancel/replace, unknown outcomes and restart. Keep request acknowledgement separate from accepted order state and confirmed cancellation. Stable client IDs, deduplication and one fenced execution owner prevent duplicate effects; reconcile an uncertain submission before retry. Same-component replay/live-input paper and shadow runs suppress executable submission. | MR05 and applicable MR04 serving; MR06 before deployment; base independent spot controls remain active throughout |
| MR07A | **[Common BBO and incremental L3 aggregates](#mr07a-common-bbo-and-incremental-l3-aggregates) — complete for the declared per-book scope.** Expose one typed per-book quote contract for native L2/L3, maintain exact L3 quantities/counts by side and price during lifecycle updates, and integrate existing research and paper consumers. Preserve native identity, clocks, quality and recovery; verify against independent full aggregation. | Completed MR01–MR07 contracts and consumers; preserve MR06 package boundaries |
| MR07B | **[Book registry and consolidated BBO](#mr07b-book-registry-and-consolidated-bbo) — complete for the declared read-only scope.** Own independent books by venue/instrument and expose per-venue and consolidated BBO queries over explicitly equivalent instruments. Scan cached eligible venue quotes with causal cutoffs, freshness, provenance, ties and partial-coverage semantics. | MR07A; existing reference/capability admission and MR07 paper/replay interfaces |
| MR08 | **[Independent paper risk and account reconciliation](../architecture/portfolio-and-execution-design.md#multi-strategy-netting-and-isolated-risk) — complete for the [bounded paper scope](#mr08-delivery-and-acceptance).** Enforce authorized instruments and instance/account/firm limits with atomic pending/uncertain exposure reservations, price/size/freshness checks and independent protection. Reconcile simulated orders, fills, positions, currency cash, fees/rebates and transfers; duplicate events do not double-book. Uncertain orders, stale state and breaks preserve exposure and trigger a defined safe response. Exercise shared-budget admission before portfolio netting, then integrate both venues' paper ledgers through MR11. | MR07 and existing risk/accounting; authenticated physical venue reconciliation is KIV |
| MR09 | **[Portfolio and shared-account infrastructure](../architecture/portfolio-and-execution-design.md#multi-strategy-netting-and-isolated-risk).** Deliver allocation/target and order-intent coordination, account budgets, conflict/self-trade prevention, strategy-tagged child orders/fills/costs and shared-account recovery. Establish tagged-order attribution first, then qualify compatible netting and deterministic allocation of fills, residuals and costs as part of this same required outcome. Two distinct active strategies share an instrument/account and reconcile independently and in aggregate; either can stop without accidentally canceling the other's orders or bypassing account protection. | MR08; full allocation/netting remains required before onboarding, even without QR strategies |
| MR10 | **[Paper operational qualification](../architecture/runtime-and-operations-design.md#monitoring-recovery-and-operational-evidence) — complete for the [bounded trusted local scope](#mr10-delivery-and-acceptance).** Deliver runbooks and commands for startup, stop, restart, reconciliation, backup/restore and rollback. Reference paper workloads pass the applicable [failure scenarios](#decisive-acceptance-scenarios), retaining state, alerts and recovery outcomes. Final paper acceptance incorporates MR11–MR14 results; private-stream and real venue recovery qualification is KIV. | Applicable MR04 services and MR05–MR08 for dedicated-account drills; MR09 for shared-account drills; complete alongside MR11–MR14 rather than blocking their development |
| MR11 | **[OKX and Bitfinex paper execution/account integration](../architecture/portfolio-and-execution-design.md#oms-and-venue-adapter-design) — complete for the [bounded paper scope](#mr11-delivery-and-acceptance).** Deliver live-public-input spot paper execution through the same strategy/OMS/risk contracts, with per-venue capability/specification profiles, simulated order lifecycle, balances and reconciliation. Expose explicit fill, delay, transaction-cost and slippage assumptions, applicable gas-cost inputs or recorded inapplicability, and sensitivity scenarios. Retain separate per-venue integrated paper traces, cost attribution and net P&L; reconcile fills/fees to each strategy and the account. Qualify one complete paper path, then the second. Existing native test adapters are supplementary; authenticated private venue qualification is KIV. | MR07–MR08 contracts and MR03 cost interfaces; MR06 before paper deployment; public market-data access; MR09 attribution; no private trading credentials required |
| MR12 | **[Monitoring, metrics, charts and alerts](../architecture/runtime-and-operations-design.md#monitoring-recovery-and-operational-evidence) — complete for the [bounded installed public-paper scope](#mr12-delivery-and-acceptance).** Provide versioned event/metric APIs, queries, retained dashboards, configurable panels/thresholds, alert routing and default data/runtime/risk/account/economic views. Register custom research metrics/charts and delayed-label diagnostics without modifying collectors or runtime. Qualify both venues' dedicated/shared paper dashboards, causal replay and local alert receiver failure/recovery independently of hard controls. The dashboard view contract was [revised for MR15](paper-monitoring.md#bounded-dashboard-contract-revision-2026-10-01) to bounded views with retained provenance and its installed evidence [re-verified](paper-monitoring.md#installed-re-verification-result-2026-10-02). | MR03 report contracts; MR08–MR11 runtime signals; deployed services and capacity remain with MR14–MR15 |
| MR13 | **[Paper activation and recovery machinery](../governance/workflow.md#activate-and-operate) — complete for the [bounded signed local scope](#mr13-delivery-and-acceptance).** Disabled paper manifests and separate finite grants bind installed release, workload, account and state identities. Durable generations fence economic effects; stop, cancellation and attributable IOC reduction remain distinct. Reconcile before restart and retain current facts on compatible signed release rollback; historical snapshots cannot reactivate managed execution. Reject missing/expired/revoked or mismatched authority and production submission. Live activation and external-fill recovery are KIV. | MR06, MR10 paper drills and MR11–MR12; results incorporated into the bounded MR10/MR14 operating evidence |
| MR14 | **[Multiple-instance integration](../architecture/portfolio-and-execution-design.md#multi-strategy-netting-and-isolated-risk) — complete for the [bounded trusted local scope](#mr14-delivery-and-acceptance).** Run distinct reference policies and instruments over isolated/shared signed account services with supervised native sources in paper and shadow. Activate a provisioned inactive instance through a versioned controlled restart; selective stop/restart retains attribution and other accounts' controls. The finite 1–120 second, single-user envelope does not qualify unprovisioned definition migration, cross-journal limits/FX, remote services or MR15 throughput. | MR09, MR12–MR13; live trading remains KIV |
| MR15 | **[Research and runtime capacity qualification](../architecture/runtime-and-operations-design.md#scaling-triggers-and-technology-choices) — open; [research budgets and diagnostic evidence](research-capacity.md) retained; [bounded runtime processing, parity, four-owner recovery, receipt/BBO latency and warm queries](runtime-capacity.md#fresh-signed-latency-and-warm-query-follow-up) qualified, with integrated features partially qualified, finite original-clock acquisition armed, [populated-history depth/BBO and dashboard queries and the public Bitfinex route qualified for stage 1](runtime-capacity.md#counted-dashboard-cohort-result-second-attempt-2026-10-02), [public OKX health renewed](runtime-capacity.md#counted-public-okx-route-result-2026-10-02) and [filesystem-cold queries qualified](runtime-capacity.md#counted-filesystem-cold-query-result-2026-10-02) for stage 1, checkpoint/sustained-operation gaps and stage 2 gated.** Define numeric launch budgets early, covering multi-day data, multiple instruments, concurrent studies/trials, replay, feature-store materialization/retrieval, live ingestion, book reconstruction, quote consolidation and dashboard queries. Record volumes, retention, throughput, p50/p95/p99 latency, memory/disk, concurrency, hardware/cache conditions and recovery targets before measurement. Remove demonstration-size limits where they prevent the workload; preserve causal/numerical parity. Retain research acceptance separately from final integrated runtime acceptance and deploy the topology needed to meet both. | Budgets start with MR01/MR04; MR01–MR04 for research acceptance; MR07/MR07A/MR07B/MR12/MR14 for final runtime acceptance; no QR bottleneck required |
| MR16 | **[Python ownership and enforcement](../coding_standards/README.md#python-scope-and-migration).** Complete the retained ownership/enforcement work with supported imports, packaging, checks and migration guidance; verify the APIs consumed by the reference workflows. | Existing engineering rules; can proceed alongside other work |
| MR17 | **[QR onboarding acceptance](#qr-onboarding-acceptance).** Exercise the installed integrated stack from a clean environment with fresh research extensions and the published onboarding guide. Close every in-scope platform gap before declaring it ready for QR. | All planned rows above, retaining valid earlier evidence |

The research path is MR01 → MR02 → MR03 → MR05. MR04's local development profile can
start alongside it and supplies MR06's installation target; MR06 does not wait
for MR04's deployed-service acceptance. MR04's deployed services then use the
verified installation path. MR06 precedes every deployment.

The book-data extension follows MR07 → MR07A → MR07B. These additive milestones
retain MR01–MR07's accepted scopes and evidence. MR08 builds on its existing
contracts; consumers adopting the common or
consolidated quote APIs depend on the corresponding follow-on. MR15 owns measured
data-structure optimization and capacity acceptance; no separate MR07C is planned.

MR07 supplies the runtime/OMS for MR08; portfolio integration (MR09) and both
venues' paper execution (MR11) follow those contracts. MR10 can qualify initial
paper operations before MR11 integration; its final record includes the integrated
paper execution and activation drills. MR13 depends on MR10's paper increment,
not that final record, so their evidence integration introduces no circular implementation dependency.
MR12 joins the report, operational and paper execution paths; MR13 supplies local
paper activation machinery; MR14 accepts bounded trusted-local multiple-instance
service operation. Essential telemetry accompanies each earlier capability. MR15
sets budgets at the start, accepts research capacity
at G2 and completes against the integrated runtime before MR17. MR16 proceeds
alongside delivery; packaging changes relevant to MR06 cannot wait until handoff.
The tables own exact prerequisites; bounded paper acceptance does not erase
MR15–MR17 obligations. Deferred live requirements remain in the KIV gate.

### MR07 delivery and acceptance

Complete for local dedicated-account paper/shadow operation: one cash-funded
spot instrument and candidate instance per account, with OKX L2 or Bitfinex R0
public input. The [OMS design](../architecture/portfolio-and-execution-design.md#oms-and-venue-adapter-design)
and component guides own current behavior. Paper touch matching models neither
queue position nor market impact, shadow never matches and neither path can
submit executable orders. Authored grids/fees and public observations do not
qualify private venue execution or account behavior.

### MR07A common BBO and incremental L3 aggregates

Complete for the declared per-book scope. The
[market-data guide](../../src/market_data/README.md#shared-book-quotes) owns the
typed quote and incremental aggregate contract. Native identities, clocks and
recovery remain distinct; L3 aggregation does not infer queue priority, and this
scope establishes no new source continuity or capacity qualification.

### MR07B book registry and consolidated BBO

Complete for the declared read-only registry and consolidated BBO scope. The
[market-data guide](../../src/market_data/README.md#book-registry-and-consolidated-bbo)
owns configuration and query semantics. Consolidation requires explicit economic
equivalence and unit/currency compatibility; no implicit FX conversion occurs.
Execution routing, shared-account allocation, source continuity, venue fills and
capacity remain outside this scope.

### MR08 delivery and acceptance

Complete for local cash-funded off-chain spot paper accounts with explicit limits,
one valuation currency and independently reconciled OKX/Bitfinex modeled effects.
The installed public-input workflow now matches direct/net orders atomically and
compares orders, source fills, attributed children, cash, positions and fees against
independent expected facts. Duplicate/restarted inputs preserve fills, postings,
policy continuation and unresolved reservations. Existing shared-budget contention,
transfers/rebates/corrections and operational evidence remain valid; the
[delivery record](paper-integration.md) identifies renewed numerical and installed
proof. The execution, risk, portfolio and accounting guides own the contracts.

Public-paper profiles retain authored tick/lot, delay, fee, adverse-price and
finite-liquidity assumptions. They do not qualify authenticated physical account
reconciliation, venue execution fidelity, implicit FX or other products. Native
base/quote fees and wallet comparison retain their earlier software evidence;
authenticated OKX/Bitfinex observations remain KIV. MR10 and MR12–MR14 have
separate bounded operating records; MR15 owns measured capacity. None follows
solely from this MR08 acceptance.

### MR09 delivery and acceptance

Complete for local shared-account portfolio coordination and recovery. The
[portfolio design](../architecture/portfolio-and-execution-design.md#multi-strategy-netting-and-isolated-risk)
and component guides own allocation, netting, attribution and recovery. Initial
qualification remains cash-funded spot; unroutable physical-lot residuals remain
visible and reserved. Other product economics, FX/base-asset fee conversion,
broader paper operational drills and activation are assessed separately in
MR10/MR13/MR14; measured capacity remains MR15. Private venue conformance is KIV.

### MR10 delivery and acceptance

Complete for the bounded trusted local signed paper/shadow operating scope.
The [runbook](../governance/operations.md#local-paper-operations),
[execution guide](../../src/applications/execute/README.md#local-operational-commands)
and [runtime guide](../../src/runtime/README.md#account-workspace-recovery) own
interfaces and procedures. Startup, account/instance stop, independent
reconciliation, explicit restart, cancel requests, quiesced backup/restore and
state-preserving signed code rollback reuse existing functional owners.
No stop action claims cancellation or reduction. Typed contracts remain
multi-account/multi-strategy; initial economics are cash-funded spot with authored
OKX/USDT and Bitfinex/USD fixture inputs and exact account/child attribution.

Quant development's [installed operational consumer](../../tests/integration/consumers/runtime/account_operations.py)
uses both active target and order-intent policies, partial fills, fees, uncertain
orders and pending cancellation. It preserves exact account/checkpoint state
through restoration, tests actual child loss and bounded SQLite storage
exhaustion, and checks local alert success/failure independently of controls.
Dedicated runtime regressions cover malformed/disconnected capture, regressed
scheduler time, repeated faults, failed persistence and cancel/fill recovery.
Existing collector queue/stall/reconnect drills and MR04 workspace/job/feature
recovery remain applicable; unchanged service integrations are not requalified
by local fixtures. Commands and outcomes are retained under ignored `logs/mr10/`.

Ownership is incremental: signed account state validation extends MR06; bounded
local alert routing is an MR12 prerequisite; explicit recovery checks and
compatible rollback are MR13 prerequisites; shared reference consumers reuse
MR09 and are incorporated into bounded MR14 service evidence. The signed account
consumer used for this record checked actual isolated installation, current late
postings/stops across code upgrade/rollback, and refusal of caller config/journal
overrides; it was retired with single-document account journals, and the
[installation tests](../../tests/engineering/test_release_installation.py) retain
those installer checks.

Local validation on 2026-09-26 passed the focused operational tests and complete
`make check`, including installed research-wheel smoke. The real signed account
installation retained the same post-stop ledger payload across upgrade/rollback.
Its evidence is `logs/mr10/account-installation.json`, with signed bundles under
`logs/mr10/registry/`; the initial release is
`dcb8859d4f4270e0ce1390da2bb0604964715323c8292db3282cd9492df1cfcd`.
The final full-gate log is `logs/mr10/make-check-final.log`; the two isolated
operating workloads retain their requests, snapshots and summaries under
`logs/mr10/operating-okx/` and `logs/mr10/operating-bitfinex/`.
These artifacts are local retained evidence, not published deployment records.

The [public-paper monitoring record](paper-monitoring.md) renews affected MR10
evidence for both installed venue paths: independent exact dashboard reconciliation,
receiver-observed local alerts, receiver failure/restoration and unchanged account
controls. Actual public inputs establish the native source boundary; local
operating drills establish receiver and storage/queue boundaries. Bounded MR10
acceptance incorporates the [MR13 signed activation/recovery record](paper-activation.md)
and the [MR14 supervised service record](multi-instance-paper.md), with its exact
installed paper/shadow economics, multi-instance source/policy/account failure,
selective stop, storage loss and latest-journal restoration. The ignored
`logs/mr10/multi-instance-paper.json` retains the final joint qualification and
impact-based reuse of the earlier MR10 backup/restore and MR13 rollback proofs.
Those earlier artifacts remain historical evidence rather than new executions.

The accepted service envelope is a trusted single-user local invocation bounded
to 1–120 seconds. Its signed account owners and supervisor do not establish remote
service recovery, hostile-process isolation, sustained source capacity or general
unprovisioned deployment migration. Older snapshots are restored only into absent
stopped, quarantined workspaces. Managed paper resumes the latest retained journal
and cannot activate from historical copies. Authenticated private-stream loss,
exchange timeout/cancel/fill outcomes and real-account anti-rewind evidence remain
unqualified and KIV. No empirical strategy, live order or capital activation is
accepted by these engineering workloads.

### MR11 delivery and acceptance

Complete for the bounded installed public-input paper scope: native OKX books and
Bitfinex R0 feed the existing decision SDK, portfolio/risk, paper OMS/matching,
account ledger/allocation, independent reconciliation and retained cost/P&L reports.
Dedicated and shared accounts use explicit versioned execution scenarios. Entry
and cancellation delays, half-even fees, adverse prices, finite touch liquidity,
partial fills and GTC/IOC/post-only rules preserve causal timing and limits.
Unsupported mechanics fail explicitly. Gas is declared inapplicable with a reason
for off-chain spot; applicable gas accounting and on-chain execution are absent.

Separate installed venue fixtures establish losing/no-trade and adverse-cost
numbers, attribution and recovery. Actual bounded public-feed runs establish the
native-source path only. Assumptions remain authored, with no exchange fill,
queue, latency-calibration or profitability claim. The [delivery record](paper-integration.md)
retains commands, artifact/source identities, failures, results and precise limits;
the [paper guide](../../src/applications/paper/README.md#automatic-public-input-accounts)
owns the user journey. MR12 now projects retained versioned traces/reports into
qualified local dashboards. MR13 now qualifies signed local activation/recovery;
MR14 now separately qualifies bounded trusted-local services; MR15 capacity
remains open.

The native private-adapter implementation and its historical validation below are
supplementary software evidence and remain KIV for external qualification. The [execution guide](../../src/execution/README.md#test-venue-execution)
and [installed command guide](../../src/applications/execute/README.md#test-venue-commands)
own behavior and commands. OKX demo and verified Bitfinex paper subaccounts share
configured reference admission, portfolio/risk, durable physical order identities,
native fill/fee posting, private input recovery and complete bounded wallet/order
reconciliation. GTC, IOC and post-only limit orders are supported. Unsupported
products, borrowing, third-currency fees, missing history and unknown physical
orders block readiness; no implicit FX or source availability is invented.

The gateway commits send uncertainty before transport, fences one owner, retains
native receipts, and never resubmits an attempted economic order. Cancellation
acknowledgement retains exposure; a fresh complete open-order observation is
required before another explicit cancellation attempt. Native base fees change
inventory, quote fees change cash, and rebates and physical-to-child attribution
remain exact and idempotent. Physical account identity is pinned and cannot fund
two local account aliases in the same firm journal.

Quant development's [installed venue consumer](../../tests/integration/consumers/runtime/venue_execution.py)
uses both actual adapters with scripted native HTTP responses, target/order
intents, shared physical orders, partial fills, costs, cancellation and restart.
Gateway tests additionally cover lost acknowledgement, absent lookup, private
disconnect, duplicate recovery, separate authority and independent stops. These
are software proofs, not observations of an exchange. MR08 owns the native
accounting/reconciliation extension; MR09 attribution is reused. The explicit
test authorization and final dispatch/recovery fences are historical prerequisite
slices; the separate MR13 public-paper acceptance below does not qualify them externally.
Existing local MR10 evidence remains bounded;
the added execution-wheel WebSocket dependency is independently locked.

Local verification on 2026-09-26 is retained under ignored `logs/mr11/`.
`protocol-final.log` records 13 native-protocol tests, including rejection of
derivative symbols on the shared Bitfinex endpoint. `independent-okx.log` and
`independent-bitfinex.log` record consumers run with `python -I` outside the
checkout using rebuilt contracts/execution wheels in a separate nine-package
environment. Each produced one submit, one cancel, final cash 899.90, base
position 1 and fee 0.10, allocated equally to two children. These exact values
are scripted workload expectations, not exchange observations. Artifact hashes,
environment and configuration identities accompany the retained local results.
The complete local gate uses
`PYTEST_ADDOPTS=--basetemp=/private/tmp/mr11-check TMPDIR=/private/tmp make check`,
with output in `logs/mr11/make-check-final.log`; earlier failed attempts are
preserved separately. The short macOS pytest path avoids socket-path overflow.

External acceptance remains unavailable: the user confirmed that no venue test
access was available for that implementation. No authenticated request or test
order was sent. This unresolved external evidence is retained as a qualification
limit and deferred from MR17/G5 under the paper delivery policy.

MR10 and MR14 now incorporate this installed paper path through their bounded
service records. MR15 capacity, MR16 ownership enforcement and MR17/G5 handoff
remain open; this MR11 acceptance alone does not qualify those outcomes.
If live work is reopened, native conformance still needs separately authorized
OKX demo and Bitfinex paper-account access, account identities, venue specifications
and bounded test-order envelopes, followed by actual acknowledgement-loss,
fill/cancel, stream-loss and restart evidence. Scripted proofs do not supply it.

### MR12 delivery and acceptance

Complete for the bounded installed, finite local public-paper operating scope.
Dedicated and shared OKX/Bitfinex accounts now retain default source/runtime,
order/fill/reject/uncertain-exposure, independent risk, reconciliation,
account/strategy and exact cost/gross/net P&L views. Committed account facts and
MR11 reports remain authoritative. Cumulative economics use last values with
separate currency series, report valuation policy and explicit gas applicability.
The [integration record](paper-monitoring.md) retains the bounded plan, runnable
operator journey, independent results, artifact identities and impact-based reuse.
The
[telemetry guide](../../src/telemetry/README.md) owns versioned events/metrics,
causal revision queries, retention, configured dashboards and local alert routes.
The [execution command](../../src/applications/execute/README.md#retained-monitoring)
reopens actual account/venue observations, while the
[research bridge](../../src/research/studies/README.md#research-monitoring-bridge)
reuses MR03 report contracts. Exact units, missingness, applicability and separate
event/availability/receipt clocks remain explicit. Named version selections never
silently substitute another version; delayed labels and revisions cannot alter
an earlier cutoff. Dashboards retain query/config/result bytes, the count and
digest of their selected inputs and those inputs' payloads, and verify all of them
when reopened. The 2026-10-01
[contract revision](paper-monitoring.md#bounded-dashboard-contract-revision-2026-10-01)
bounded each view to its exact results and last 120 points per metric; its
[installed re-verification](paper-monitoring.md#installed-re-verification-result-2026-10-02)
renewed the public-feed, replay, operational and research evidence on 2026-10-02.

Data/runtime views distinguish process heartbeat from ingestion and durable
progress, local receipt-to-durable delay, queue bytes/age, gaps, duplicates and
failure. Account/risk views expose exact currency/instrument state, independent
blocking, reconciliation and physical-order uncertainty. A bounded background
writer keeps monitoring I/O off the watchdog control thread; saturation, failed
storage and unfinished shutdown are visible. Local alert attempts retain failure
and uncertainty; socket acceptance is not operator acknowledgement. No chart
threshold can grant authority or release a hard control.

Quant development's installed study consumer registers a fresh custom metric and
chart across retained studies and paper telemetry; saved model predictions and
outcomes exercise delayed-label diagnostics. The existing two-venue paper
operational consumer now exercises the installed dashboard command, exact account
values, reopening, idempotent retry, receiver loss and restoration. Actual
public-feed runs separately cover both venues and both account modes, with
independently reconciled economic dashboards and receiver-observed local alerts.
Socket acceptance, receiver observation and human acknowledgement are recorded
separately; no human acknowledgement is claimed. Focused
faults cover blocked telemetry writes, overflow, retention expiry, incompatible
units/schemas, changed retries and future/corrected labels. These are software
and local operating proofs, not empirical strategy or physical venue evidence.
Prior extension evidence lives under ignored `logs/mr12/`; renewed integration
evidence lives under `logs/paper-monitoring/`.

This acceptance covers a final retained view per finite invocation and its local
recovery. It does not establish continuous/deployed monitoring, remote routing,
human acknowledgement or host/source clock qualification. Actual monotonic
callback processing delay is distinct from modeled execution delay; source clock
drift and receipt-to-durable delay remain `not_measured`. Retrospective projection
uses actual monitoring receipt time; saved receipt envelopes reopen idempotently,
and late corrections cannot alter an earlier cutoff. New captures do not relabel
old lifecycle facts. Incomplete telemetry ingestion refuses partial dashboards
and remains recoverable without account actions. MR10 incorporates these operating
results into its bounded final service evidence. MR13 adds the account-isolation
correction and signed local activation/recovery below; MR14 separately qualifies
bounded local multiple-instance services. MR15 measured dashboard/load budgets,
MR16 ownership enforcement and MR17/G5 remain open. Native private-stream signals
remain unqualified and KIV.

### MR13 delivery and acceptance

Complete for one trusted local signed installation and its latest retained paper
journal. Disabled versioned deployments and separate bounded grants bind release,
policy/candidate/model/feature/input, configuration, account/instances, execution
scenario and state ABI. Current-time checks and durable owner generations guard
new exposure and restart, while safe operator controls preserve existing obligations.
Stop, requested cancellation and attributable position reduction remain separate;
IOC reductions use existing risk, OMS and finite public-book matching.

The [activation record](paper-activation.md) retains commands, artifact identities,
first failures, exact expected economics and limits. Both signed OKX and Bitfinex
native-message fixtures passed disabled installation, explicit authorization,
shared-account execution, pending-to-terminal cancellation, bounded zero-fill
reduction, release upgrade/rollback, fresh reconciliation and generation 1-to-2
reclaim with identical retried economics. Unit regressions cover partial reduction,
unavailable/stale data, unknown outcomes, independent ownership, grant expiry and
revocation, stale owners and quarantined historical restores. The MR12 two-account
regression confirms projection succeeds with both populated ledgers unchanged.

The final repository gate passed 1,748 tests plus installed wheel smoke; two
unrelated real-Feast worker integrations were skipped. The signed execution
target contains the independently admitted execution/contracts closure. Its
reference input/policy client cannot bypass installed authority or risk through
the research wheel. The signed fixture explicitly uses a 30-second freshness
profile to accommodate local command round trips; it is not MR15 latency proof.

Rollback selects between two signed releases of the same implementation and
preserves the current journal; this does not establish historical cross-version
schema migration. Restored snapshots are inspectable and quarantined before
publication, with no silent recovery after loss of the latest journal.
The bounded MR14 service record adds multi-instance recovery, preserving
this MR13 latest-journal and signed rollback evidence by documented
impact reuse. Coordination across installation roots, remote monitoring and
measured capacity remain outside this MR13 scope. MR10 incorporates its signed
activation proof in bounded final operating evidence. Live execution,
authenticated venue qualification and real capital remain KIV; these engineering
workloads imply no profitability.

### MR14 delivery and acceptance

Complete for a trusted single-user, finite local paper/shadow service envelope:
1–120 second invocations, qualified with two independently signed account owners,
two native source processes and four isolated policy instances. Distinct
reference policies and BTC/ETH sources run across shared and isolated accounts;
USD and USDT retain separate currencies, journals and budgets. Owner generations,
local socket/scheduler fences and retained checkpoints prevent duplicate account
producers and stale continuation. Adding an already provisioned inactive instance
requires a versioned active-selection change, controlled shutdown, reconciliation
and new owner claims; an unprovisioned definition is a new installation and is not
automatically migrated into the old journal. Implementation ceilings of four
accounts, eight sources and sixteen instances do not qualify MR15 capacity.

The [MR14 record](multi-instance-paper.md) owns signed artifact identities,
independent exact account/strategy cash, fees and marked net P&L, paper and shadow
runs, actual native OKX/Bitfinex routing, receiver observations, and selective
worker/source/account/storage fault and recovery results. The joint
`logs/mr10/multi-instance-paper.json` ties those results to the earlier MR10
backup/restore and MR13 signed rollback evidence by explicit impact analysis.
The original 30-second recovery-budget miss remains visible; separately
declared 40-second first-claim-request-to-progress confirmation passes.
Shadow retains zero modeled fill economics; its stopped, never-submitted intents
settle through a current-owner local rejection, complete independent empty-order
reconciliation and a fresh claim. No new economic request is automatically retried
after an uncertain result.

This scope does not qualify sustained feed rates or latency percentiles (MR15),
remote/hostile service isolation, cross-journal atomic firm limits, implicit
USD/USDT FX, arbitrary definition migration or private/live venue execution.
MR16 ownership enforcement and MR17 onboarding remain open; private routing and
real-capital operation remain KIV.

## Decisive acceptance scenarios

Implement these at their owning boundary and reuse them in the final installed
journey. Use independent expected results and targeted faults; do not repeat a
full test matrix for every gate. Record actual bytes, configuration, environment,
workload, outcomes and limits in the existing capability acceptance record.
Order/account fault cases below use the declared paper model. Real private-stream,
exchange-fill and live-account qualification remain KIV; public-source and paper
service observations must still establish their actual supported boundaries.

| Scenario | Required observable result | Owning MRs |
| --- | --- | --- |
| Universe and capability admission | Adding collection/research membership does not grant trading permission. Unsupported feeds, product economics, order types or feature signatures fail before executable work. | MR01/MR05/MR13 |
| Historical reference change | A tick/lot or specification change resolves by valid time and knowledge time; older runs retain their specification and unknown source history is not replaced by current metadata. | MR01/MR03 |
| Fresh research extension | Register a new feature/label, non-built-in estimator and strategy; selected implementations reach study, report, candidate and runtime without edits to generic runners or fallback to built-ins. | MR02/MR03/MR05/MR17 |
| Feature-store parity and recovery | Matched definitions/entities/cutoffs reproduce admitted offline and online values within the declared numerical contract. Late corrections, TTL expiry, missing entities, materialization retry and version rollback remain explicit and cannot leak future values. | MR02/MR04/MR07 |
| Book and consolidated quote parity | Incremental L3 aggregates match independent expected levels/BBO; venue/instrument isolation, query cutoffs and freshness preserve eligible quote provenance, ties and explicit partial coverage. See the scoped acceptance cases above. | MR07A/MR07B |
| Shared-budget race | With no prior exposure, A and B each request 8,000 account-currency units against a shared 10,000 limit. Atomic admission rejects or policy-clips requests so admitted, pending and uncertain commitments never exceed 10,000; retry/restart cannot release unknown exposure. | MR08/MR09 |
| Conflicting strategies and netting | Two active strategies on one instrument retain intent/child-order/fill ownership; self-trade conflicts follow explicit policy. Netting, partial fills, fees and residuals reconcile to both strategy allocations and physical account state; stopping one preserves the other's ownership. | MR09/MR14 |
| Paper order uncertainty | Modeled lost acknowledgement, duplicate events, rejects, partial fills, cancel/fill races, event loss and restart with open simulated orders cannot duplicate submissions or postings. Cancel acknowledgement alone does not release exposure; paper reconciliation resolves uncertainty. | MR07/MR08/MR11 |
| Paper cost and economics | Transaction costs, slippage and applicable gas reconcile from simulated fills/activity to strategy/account net P&L with explicit units and assumptions. Missing costs or unjustified gas inapplicability prevent economic acceptance. Reference losing/no-trade and adverse-cost cases exercise the machinery without claiming empirical profitability. | MR03/MR08/MR11/MR12 |
| Faults and operator actions | Public market-data disconnect, simulated order-event loss/timeouts, malformed messages, clock regression, queue overload, disk exhaustion and process/service loss cause the declared visible response. Block, cancel and reduce remain distinct; telemetry loss cannot disable hard controls. Test recovery and alert delivery. | MR01/MR04/MR07/MR10–MR14 |
| Trusted installation and restoration | Install the appropriate research or paper operating artifact in a clean environment; research/paper/shadow lacks production submission authority. Reject incompatible state, restore data/features/artifacts/account state, and reconcile before resuming. | MR04/MR06/MR10/MR13 |
| Architectural extension | Add a supported-family instrument by reference/configuration and another compatible adapter through its public boundary. Carry a non-book input and a non-24/7 calendar or different-economics fixture through relevant research/simulation consumers without disguising source semantics or changing unrelated code. Unsupported lifecycle behavior is rejected. | MR01–MR03/MR11/MR17 |

## Deliverable coverage

The quant-development work packages remain acceptance obligations inside this
single roadmap. This mapping connects the original D01–D18 identifiers to the
revised research/paper scope; live obligations remain KIV. It is not a second
backlog or a completion score.

| Deliverable | Owning MRs |
| --- | --- |
| D01 — Monorepo foundation and dependency boundaries | MR06/MR16 |
| D02 — Domain model and versioned reference data | MR01/MR02 |
| D03 — Typed configuration and four universes | MR01/MR05/MR09/MR13 |
| D04 — Adapter interfaces and capability registry | MR01/MR05/MR11 |
| D05 — Collectors and raw journal | MR01/MR04/MR15 |
| D06 — Book reconstruction and data quality, extended with common and consolidated BBO | MR01/MR07/MR07A/MR07B |
| D07 — Storage, catalog and dataset builder | MR01/MR04/MR15 |
| D08 — Research SDK and feature computation, extended with offline/online feature store | MR02–MR04/MR07 |
| D09 — Replay and execution-aware backtesting | MR03/MR05/MR07 |
| D10 — Experiments, artifacts and paper handoff | MR03–MR06 |
| D11 — Strategy SDK and multi-strategy runtime | MR02/MR05/MR07/MR14 |
| D12 — Portfolio coordination and centralized risk | MR08/MR09/MR13 |
| D13 — Paper OMS and execution models for both venues | MR07/MR11/MR13 |
| D14 — Ledger, portfolio state and reconciliation | MR08/MR09/MR11 |
| D15 — Paper deployment, security and release pipeline | MR04/MR06/MR13/MR14 |
| D16 — Monitoring, operator controls and runbooks, extended with metric/chart APIs | MR10/MR12–MR14 |
| D17 — Correctness, failure and capacity qualification | Each owning MR; integrated MR10/MR15/MR17 |
| D18 — Operating documentation and extension demonstrations | Each owning guide; MR16/MR17 |

## QR onboarding acceptance

Quant development demonstrates the following with public APIs, installed artifacts,
maintained examples and the documented environment, without a QR supplying missing
infrastructure or selecting an alpha:

1. Provision a clean workspace, discover/admit the declared inputs, and reopen
   exact retained data/results with source quality, specification versions and
   limitations visible. Collection/research selections cannot authorize trading.
2. Add fresh compatible feature/label, estimator and rule implementations plus
   a study specification. Execute rule-only and learned paths through temporal
   evaluation, costed backtesting and retained comparison reports. The extension
   must not be one of the runner's built-in special cases. Exercise both target
   and order/quote decisions and the architectural extension scenario above.
3. Define a custom metric and chart once through the supported contracts; inspect
   historical and paper/shadow outputs with declared applicability, units,
   missingness and alert behavior. No shared runner or dashboard-engine edit is needed.
4. Retrieve versioned offline features, materialize and serve them online, and
   demonstrate parity, missing/stale/revised inputs, recovery and version rollback
   through the provisioned feature store and candidate/runtime interfaces.
5. Package/load candidates, run two distinct active strategies on shared and
   isolated paper accounts, and exercise independent risk, compatible netting,
   allocation reconciliation, order uncertainty, selective stop and recovery.
   Retain separate OKX and Bitfinex public-input paper execution/account evidence,
   with transaction-cost/slippage attribution, applicable gas fees or recorded
   inapplicability, net P&L and adverse-cost scenarios.
   Reference components do not acquire live authority by being installed.
6. Meet both MR15 research and runtime budgets, restore data/features/artifacts/state
   from backup, and show independent operating-package installation, trusted
   paper deployment/rollback, service integration and the runnable operational guide.

Reuse milestone proofs for unchanged components; run an integrated fresh-entry
journey to establish that provisioning, interfaces and retention compose. Retain
the tested artifact/environment, workload, commands, outcomes and known support
limits in the existing acceptance record. Do not substitute an API skeleton,
mocked service, tiny fixture or closed milestone count for the boundary it cannot
prove. An unverified required boundary keeps onboarding acceptance open.

## Research phase after full handoff

Only after every in-scope research/paper MR01–MR16 outcome, including MR07A/MR07B,
and MR17/G5 integrated acceptance does QR begin
the [research milestones](research-program.md#post-infrastructure-research-milestones):

1. **QR-M1 — Research-ready:** question-specific data acceptance, ranked hypotheses,
   preliminary economics and an executable evaluation protocol.
2. **QR-M2 — End-to-end prototype:** reproducible feature/label and rule/model code,
   a complete policy, costed replay and ledger reconciliation.
3. **QR-M3 — Evidence-backed decision:** robustness, final evaluation and
   risk/capacity evidence supporting a forward paper-validation proposal or rejection.

The research program owns QR-01–QR-18 across readiness, signal experiments,
strategy prototypes and conditional candidate validation/handoff. All are planned
and not started. Even QR-M1 waits for the full infrastructure; G2's research-ready
engineering increment is not QR-M1. A losing or rejected study can be a completed
research outcome. Surviving candidates need frozen reproduction/parity and forward
paper evidence. Both OOS and paper trading must show net-of-cost profitability
under the [KIV reconsideration gate](#live-trading-kiv-and-reconsideration) before
live work can be reconsidered; actual activation remains separate.

These QR deliverables consume the accepted platform and add no infrastructure
milestones. QR owns empirical content and candidate-specific assumptions; QD
retains platform defects, extensions and operations. Research acceptance and
strategy-specific operating qualification do not retroactively become prerequisites
for building the shared stack.

## Execution and maintenance

For each planned MR, refine its observable outcome, supported capability envelope,
reference workload, dependencies and smallest sufficient proof before implementation.
Quant development makes routine implementation and representative workload choices;
it must not defer an in-scope capability until a QR requests it. Split large rows
into reviewable implementation slices without retiring their completion outcomes.
Keep this page as the backlog and update the owning component guide when complete.
Follow the [engineering guide](../coding_standards/README.md) and
[development workflow](../governance/workflow.md). Implementation, research
acceptance, artifact admission, deployment and trading activation remain separate.

New asset mechanics beyond the launch scope and specialized scaling remain later
extensions. People-dependent organizational controls follow actual staffing;
they are distinct from the mandatory technical onboarding gate. Existing spot
and saved-book evidence does not qualify additional scope.
