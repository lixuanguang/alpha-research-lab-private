# Platform infrastructure roadmap

Owner: repository founder; quant development owns infrastructure delivery.
Status updated 2026-09-26. Delivery policy: complete the initial infrastructure
stack before quant researcher (QR) onboarding.

This index owns delivery status, remaining work and dependencies. Component
guides own implemented behavior; the milestone sections below retain only the
current accepted scope and qualification limits. One-off delivery narratives,
commands and evidence identities remain available in Git history.

The completed MR09A saved-book baseline retains its historical identity. The
remaining work uses MR01–MR17, with MR07A/MR07B extending the completed MR07
increment without renumbering later milestones. MR01–MR07B and MR09 are complete
for the bounded scopes stated below. MR08 has a delivered local account/risk
increment, while physical account qualification through MR11 remains open.
MR10 has a delivered local operational increment; its final integrated
qualification and MR11–MR17 remain open, including their explicitly owned
prerequisite slices.
P1 stays deferred and unaccepted.

This revision strengthens generalization and acceptance without reducing the
destination. Intermediate gates expose usable increments; they do not retire
feature-store, portfolio/netting, second-venue, dashboard, capacity or handoff
requirements. All MR01–MR17 outcomes, including MR07A/MR07B, remain mandatory
before formal QR onboarding.

The [QR implementation guide](../../examples/README.md) explains how researchers
use the available capabilities. The [research program](research-program.md) owns
post-handoff QR milestones, deliverables, methodology and experimental choices.
The [platform design](../architecture/platform-design.md)
owns shared contracts.

## Current platform

The supported research path is configured acquisition or capture → retained raw
inputs → validation and versioned publication → explicit snapshot queries/replay
→ EDA, model studies or configured bounded spot economics → retained costed
reports.

The [data command reference](../../src/market_data/README.md) owns current
invocations. The [saved L2 workflow](../research/l2-book-backtest.md)
owns the implemented OKX simulation scope and its limitations. No empirical
strategy, paper deployment or live trading acceptance is implied by the current
platform.

Current evidence is bounded: the accepted OKX simulation covers a 10,000-message
prefix with modeled delivery clocks, not known historical receipt or continuity.
Its instances have separate simulated accounts. Identity/calendar/unit contracts,
immutable datasets, experiment history and exact spot accounting remain reusable
foundations. MR04 now qualifies local offline/online feature serving and retained
workspace/job services. Local shared-account coordination and a durable paper OMS
are available; authenticated venue operation and service deployment remain open.
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
state, paper/shadow and live-capable execution, deployment, monitoring, recovery
and the storage/computation needed to run them. Supported venue operations,
order types, dataset history, workload sizes and operating modes must be stated
in each capability's acceptance record. Both venues need explicit conformance
evidence for their declared support; one venue's pass does not qualify the other.

The destination remains a generalized multi-asset, multi-source, multi-strategy
monorepo. Required infrastructure includes a versioned feature store with offline
PIT retrieval and online materialization/retrieval, experiment/model/artifact
tracking, dataset versioning, concurrent job services, allocation and compatible
netting, both venue execution adapters, extensible reports/dashboards and recovery.
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
An unavailable required external integration remains an explicit blocker to that
capability's qualification, while independent infrastructure work continues.

## Platform and researcher responsibilities

| Boundary | Quant development delivers before onboarding | QR supplies through the delivered interfaces |
| --- | --- | --- |
| Data | Source adapters, reference/universe contracts, collection/backfill, quality, revisions, discovery, PIT assembly, storage and replay | Research universe, datasets/fields, sample, horizon and stricter question-specific quality requirements |
| Features and labels | Typed extensible definitions, execution/alignment, lineage, fitted-transform lifecycle, batch/incremental state, versioned offline/online feature-store access and recovery | Formulas, targets, windows, transformations and missingness choices within the supported contracts |
| Models and rules | Training/inference adapters, temporal evaluation/search, artifact reload, prediction-to-target/order-intent binding and isolated state | Estimator/strategy implementations, parameters, comparison space and selection criteria |
| Backtesting | Reusable study runner, execution/cost model interfaces, portfolio/risk/accounting, checkpoints and analysis | Backtest specifications, hypotheses, scenarios, economic assumptions and interpretation |
| Metrics and charts | Versioned metric/result contracts, computation, query/export, report/dashboard rendering and alert evaluation | Research metrics, chart definitions, diagnostic views and strategy-specific thresholds |
| Promotion and operation | Candidate loading, trusted artifacts, provisioning, scheduling, OMS/venue adapters, reconciliation, limits, stop and recovery | Candidate content and accepted research evidence; investigation and proposed revisions |

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
| G4 — Integrated operating infrastructure | Qualify shared-account controls/netting, both venue adapters, complete monitoring, scoped activation machinery and operational failure drills, using authorized test environments. | MR09–MR14 and runtime MR15 budgets. A first-venue increment is useful evidence; the second venue remains mandatory. No gate authorizes live capital. |
| G5 — Generalized handoff | Demonstrate fresh extensions through the installed integrated stack, all launch workloads, service/venue evidence and the operator/researcher guides. | MR17, after every MR01–MR16 outcome, including MR07A/MR07B. This is full infrastructure acceptance, separate from empirical strategy acceptance and activation. |

## Delivery order and dependencies

All rows below are required for the initial infrastructure gate. The restarted
numbering follows delivery scope: MR01–MR04 close research/data usability gaps left by
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
production key provisioning, live orders and capital activation remain unqualified;
the research graph's QuantLib release restriction remains in force.

### Runtime, operations and handoff

| MR | Planned delivered behavior and sufficient completion evidence | Dependencies |
| --- | --- | --- |
| MR05 | **[Candidate packaging and runtime binding](../architecture/research-and-simulation-design.md#candidate-promotion-contract) — complete for the [declared local scope](#mr05-delivery-and-acceptance).** Package rule-only and learned reference candidates with input/feature-store/state/metric contracts and target or order/quote outputs; load the same components into replay and runtime. Resolve a typed capability registry for market data, reference data, calendars, valuation, account and execution interfaces; reject unsupported product/channel/order/freshness combinations before startup. Bind dataset → experiment → candidate → deployment identities without granting authority. | MR02–MR03; integrate MR04 serving interfaces and MR11 conformance when available |
| MR06 | **[Independent deployable packages and trusted installation](../governance/workflow.md#build-a-release) — complete for the [declared local scope](#mr06-delivery-and-acceptance).** Build, verify, install and roll back pinned artifacts/configuration/state on the declared target; reject provenance, dependency, signature and compatibility failures. Prove that collector/execution applications install without unrelated research, notebook, training or reporting dependencies; shared contracts and independently locked workers retain compatible versions and release cadences. Resolve current release restrictions and verify research/shadow credentials cannot submit production orders. | Existing build/admission and MR16 package contracts; MR04 local environment profile supplies the target; MR06 does not wait for full MR04 or MR16 completion |
| MR07 | **[Paper/shadow runtime and OMS](../architecture/portfolio-and-execution-design.md#oms-and-venue-adapter-design) — complete for the [declared local scope](#mr07-delivery-and-acceptance).** Supervise candidates with lifecycle callbacks, timers, market/account/order events and checkpointed instance state. Bind live inputs/features and a durable order-intent journal; support target and order/quote decisions, partial fills, rejects, cancel/replace, unknown outcomes and restart. Keep request acknowledgement separate from accepted order state and confirmed cancellation. Stable client IDs, deduplication and one fenced execution owner prevent duplicate effects; reconcile an uncertain submission before retry. Same-component replay/live-input paper and shadow runs suppress executable submission. | MR05 and applicable MR04 serving; MR06 before deployment; base independent spot controls remain active throughout |
| MR07A | **[Common BBO and incremental L3 aggregates](#mr07a-common-bbo-and-incremental-l3-aggregates) — complete for the declared per-book scope.** Expose one typed per-book quote contract for native L2/L3, maintain exact L3 quantities/counts by side and price during lifecycle updates, and integrate existing research and paper consumers. Preserve native identity, clocks, quality and recovery; verify against independent full aggregation. | Completed MR01–MR07 contracts and consumers; preserve MR06 package boundaries |
| MR07B | **[Book registry and consolidated BBO](#mr07b-book-registry-and-consolidated-bbo) — complete for the declared read-only scope.** Own independent books by venue/instrument and expose per-venue and consolidated BBO queries over explicitly equivalent instruments. Scan cached eligible venue quotes with causal cutoffs, freshness, provenance, ties and partial-coverage semantics. | MR07A; existing reference/capability admission and MR07 paper/replay interfaces |
| MR08 | **[Independent risk and account reconciliation](../architecture/portfolio-and-execution-design.md#multi-strategy-netting-and-isolated-risk).** Enforce authorized instruments and instance/account/firm limits with atomic pending/uncertain exposure reservations, price/size/freshness checks and independent protection. Reconcile orders, fills, positions, currency cash, fees/rebates and transfers; duplicate events do not double-book. Unknown sends, stale state and breaks preserve exposure and trigger a defined safe response. Exercise shared-budget admission before portfolio netting, then integrate physical venue reconciliation through MR11. | MR07 and existing risk/accounting; base paper acceptance precedes MR11 external evidence |
| MR09 | **[Portfolio and shared-account infrastructure](../architecture/portfolio-and-execution-design.md#multi-strategy-netting-and-isolated-risk).** Deliver allocation/target and order-intent coordination, account budgets, conflict/self-trade prevention, strategy-tagged child orders/fills/costs and shared-account recovery. Establish tagged-order attribution first, then qualify compatible netting and deterministic allocation of fills, residuals and costs as part of this same required outcome. Two distinct active strategies share an instrument/account and reconcile independently and in aggregate; either can stop without accidentally canceling the other's orders or bypassing account protection. | MR08; full allocation/netting remains required before onboarding, even without QR strategies |
| MR10 | **[Operational qualification](../architecture/runtime-and-operations-design.md#monitoring-recovery-and-operational-evidence).** Deliver runbooks and commands for startup, stop, restart, reconciliation, backup/restore and rollback. Reference paper workloads pass the applicable [failure scenarios](#decisive-acceptance-scenarios), retaining state, alerts and recovery outcomes. Keep paper results distinct from later MR11 private-stream/venue evidence; final operational acceptance incorporates MR11–MR14 results. | Applicable MR04 services and MR05–MR08 for dedicated-account drills; MR09 for shared-account drills; complete alongside MR11–MR14 rather than blocking their development |
| MR11 | **[OKX and Bitfinex execution/account adapters](../architecture/portfolio-and-execution-design.md#oms-and-venue-adapter-design).** Implement both venues' declared spot operations, capability profiles, authentication, throttles, durable client IDs, private-stream recovery and reconciliation. Qualify one complete venue path first, then the second through the same strategy/OMS/risk contracts. Retain per-venue authorized test-environment conformance; fixtures supplement unavailable external proof. The first venue never closes this two-venue outcome. | MR07–MR08 contracts; MR06 before deployment; required venue access; integrate MR09 attribution |
| MR12 | **[Monitoring, metrics, charts and alerts](../architecture/runtime-and-operations-design.md#monitoring-recovery-and-operational-evidence).** Provide versioned event/metric APIs, queries, retained dashboards, configurable panels/thresholds, alert routing and default data/runtime/risk/account views. Register a custom research metric/chart and delayed-label diagnostic without modifying collectors or runtime; test telemetry loss independently of hard controls. | MR03 report contracts; MR08–MR11 runtime signals; basic telemetry ships earlier with each capability |
| MR13 | **[Activation and recovery machinery](../governance/workflow.md#activate-and-operate).** Implement disabled-by-default deployment manifests and separate authorization envelopes, scoped limits, fencing and recovery. Provide distinct block-new-exposure, cancel and reduce-position operations with defined stale-data, disconnected and illiquid behavior. Reject absent/expired authority and incompatible code/model/schema/state; prove safe restart and rollback without undoing or duplicating external fills. Completion does not require or grant live capital use. | MR06, MR10 paper drills and MR11–MR12; feed results back into final MR10 acceptance |
| MR14 | **[Multiple-instance integration](../architecture/portfolio-and-execution-design.md#multi-strategy-netting-and-isolated-risk).** Run different reference components and instruments with isolated/shared-account configurations through paper/shadow; add an instance through configuration, then stop/restart it without losing attribution or weakening other accounts' controls. | MR09, MR12–MR13; actual live use remains separately authorized |
| MR15 | **[Research and runtime capacity qualification](../architecture/runtime-and-operations-design.md#scaling-triggers-and-technology-choices).** Define numeric launch budgets early, covering multi-day data, multiple instruments, concurrent studies/trials, replay, feature-store materialization/retrieval, live ingestion, book reconstruction, quote consolidation and dashboard queries. Record volumes, retention, throughput, p50/p95/p99 latency, memory/disk, concurrency, hardware/cache conditions and recovery targets before measurement. Remove demonstration-size limits where they prevent the workload; preserve causal/numerical parity. Retain research acceptance separately from final integrated runtime acceptance and deploy the topology needed to meet both. | Budgets start with MR01/MR04; MR01–MR04 for research acceptance; MR07/MR07A/MR07B/MR12/MR14 for final runtime acceptance; no QR bottleneck required |
| MR16 | **[Python ownership and enforcement](../coding_standards/README.md#python-scope-and-migration).** Complete the retained ownership/enforcement work with supported imports, packaging, checks and migration guidance; verify the APIs consumed by the reference workflows. | Existing engineering rules; can proceed alongside other work |
| MR17 | **[QR onboarding acceptance](#qr-onboarding-acceptance).** Exercise the installed integrated stack from a clean environment with fresh research extensions and the published onboarding guide. Close every in-scope platform gap before declaring it ready for QR. | All planned rows above, retaining valid earlier evidence |

The research path is MR01 → MR02 → MR03 → MR05. MR04's local development profile can
start alongside it and supplies MR06's installation target; MR06 does not wait
for MR04's deployed-service acceptance. MR04's deployed services then use the
verified installation path. MR06 precedes every deployment.

The book-data extension follows MR07 → MR07A → MR07B. These additive milestones
retain MR01–MR07's accepted scopes and evidence. MR08 can proceed on its existing
contracts while this extension is built; consumers adopting the common or
consolidated quote APIs depend on the corresponding follow-on. MR15 owns measured
data-structure optimization and capacity acceptance; no separate MR07C is planned.

MR07 supplies the runtime/OMS for MR08; portfolio integration (MR09) and venue
adapters (MR11) follow those contracts. MR10 can qualify paper operations before
MR11 external qualification; its final record includes the later venue and
activation drills. MR13 depends on MR10's paper increment, not that final record,
so their evidence integration introduces no circular implementation dependency.
MR12 joins the report, operational and venue paths before MR13–MR14 complete
activation machinery and multiple instances; essential telemetry accompanies
each earlier capability. MR15 sets budgets at the start, accepts research capacity
at G2 and completes against the integrated runtime before MR17. MR16 proceeds
alongside delivery; packaging changes relevant to MR06 cannot wait until handoff.
The tables own exact prerequisites; incremental acceptance never erases open scope.

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

Partial: the local account/risk increment is implemented, while physical venue
reconciliation remains unqualified. The execution, accounting and risk guides
own current behavior. Initial qualification is local cash-funded spot with
authored grids, a common explicit valuation currency, quote-currency fee reserves
and normalized paper facts. FX aggregation, base-asset fee conversion, other
product mechanics and authenticated OKX/Bitfinex account observations remain
MR11 work.

### MR09 delivery and acceptance

Complete for local shared-account portfolio coordination and recovery. The
[portfolio design](../architecture/portfolio-and-execution-design.md#multi-strategy-netting-and-isolated-risk)
and component guides own allocation, netting, attribution and recovery. Initial
qualification remains cash-funded spot; unroutable physical-lot residuals remain
visible and reserved. Other product economics, FX/base-asset fee conversion,
private venue conformance, broader operational drills, activation and capacity
remain open in their owning milestones.

### MR10 delivery and acceptance

Partial: local paper operational commands and recovery drills are implemented.
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
MR09 without closing deployed MR14. The
[signed account consumer](../../tests/integration/consumers/deployment/account_installation.py)
checks actual isolated installation, current late postings/stops across code
upgrade/rollback, and refusal of caller config/journal overrides.

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

Final MR10 acceptance remains open. Next, implement and qualify both MR11 private
execution/account adapters with explicitly authorized test endpoints/accounts
and credentials references, then incorporate MR12 monitoring/routing, MR13
authorization/reduce-position/deployed recovery and MR14 multi-instance results.
Authenticated private-stream loss, exchange timeout/cancel/fill outcomes, remote
service/alert failure and deployed restoration cannot be proven by this local
increment. Older snapshots are restored only into absent stopped workspaces;
venue-generation/anti-rewind proof remains part of integrated recovery. No
empirical strategy, service deployment, live order or capital activation is accepted.

## Decisive acceptance scenarios

Implement these at their owning boundary and reuse them in the final installed
journey. Use independent expected results and targeted faults; do not repeat a
full test matrix for every gate. Record actual bytes, configuration, environment,
workload, outcomes and limits in the existing capability acceptance record.

| Scenario | Required observable result | Owning MRs |
| --- | --- | --- |
| Universe and capability admission | Adding collection/research membership does not grant trading permission. Unsupported feeds, product economics, order types or feature signatures fail before executable work. | MR01/MR05/MR13 |
| Historical reference change | A tick/lot or specification change resolves by valid time and knowledge time; older runs retain their specification and unknown source history is not replaced by current metadata. | MR01/MR03 |
| Fresh research extension | Register a new feature/label, non-built-in estimator and strategy; selected implementations reach study, report, candidate and runtime without edits to generic runners or fallback to built-ins. | MR02/MR03/MR05/MR17 |
| Feature-store parity and recovery | Matched definitions/entities/cutoffs reproduce admitted offline and online values within the declared numerical contract. Late corrections, TTL expiry, missing entities, materialization retry and version rollback remain explicit and cannot leak future values. | MR02/MR04/MR07 |
| Book and consolidated quote parity | Incremental L3 aggregates match independent expected levels/BBO; venue/instrument isolation, query cutoffs and freshness preserve eligible quote provenance, ties and explicit partial coverage. See the scoped acceptance cases above. | MR07A/MR07B |
| Shared-budget race | With no prior exposure, A and B each request 8,000 account-currency units against a shared 10,000 limit. Atomic admission rejects or policy-clips requests so admitted, pending and uncertain commitments never exceed 10,000; retry/restart cannot release unknown exposure. | MR08/MR09 |
| Conflicting strategies and netting | Two active strategies on one instrument retain intent/child-order/fill ownership; self-trade conflicts follow explicit policy. Netting, partial fills, fees and residuals reconcile to both strategy allocations and physical account state; stopping one preserves the other's ownership. | MR09/MR14 |
| External order uncertainty | Lost acknowledgement, duplicate events, rejects, partial fills, cancel/fill races, private-stream loss and restart with open orders cannot duplicate submissions or postings. Cancel acknowledgement alone does not release exposure; venue reconciliation resolves uncertainty. | MR07/MR08/MR11 |
| Faults and operator actions | Market-data/private-stream disconnect, malformed messages, clock regression, queue overload, disk exhaustion, process/service loss and exchange timeout cause the declared visible response. Block, cancel and reduce remain distinct; telemetry loss cannot disable hard controls. Test recovery and alert delivery. | MR01/MR04/MR07/MR10–MR13 |
| Trusted installation and restoration | Install the appropriate research or operating artifact in a clean environment; research/shadow lacks production submission authority. Reject incompatible state, restore data/features/artifacts/account state, and reconcile before resuming. | MR04/MR06/MR10/MR13 |
| Architectural extension | Add a supported-family instrument by reference/configuration and another compatible adapter through its public boundary. Carry a non-book input and a non-24/7 calendar or different-economics fixture through relevant research/simulation consumers without disguising source semantics or changing unrelated code. Unsupported lifecycle behavior is rejected. | MR01–MR03/MR11/MR17 |

## Deliverable coverage

The quant-development work packages remain acceptance obligations inside this
single roadmap. This mapping connects the original D01–D18 deliverables to the
broader retained platform; it is not a second backlog or a completion score.

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
| D10 — Experiments, artifacts and production handoff | MR03–MR06 |
| D11 — Strategy SDK and multi-strategy runtime | MR02/MR05/MR07/MR14 |
| D12 — Portfolio coordination and centralized risk | MR08/MR09/MR13 |
| D13 — OMS and execution gateways for both venues | MR07/MR11/MR13 |
| D14 — Ledger, portfolio state and reconciliation | MR08/MR09/MR11 |
| D15 — Deployment, security and release pipeline | MR04/MR06/MR13 |
| D16 — Monitoring, operator controls and runbooks, extended with metric/chart APIs | MR10/MR12/MR13 |
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
   Retain separate OKX and Bitfinex execution/account conformance evidence.
   Reference components do not acquire live authority by being installed.
6. Meet both MR15 research and runtime budgets, restore data/features/artifacts/state
   from backup, and show independent operating-package installation, trusted
   deployment/rollback, service integration and the runnable operational guide.

Reuse milestone proofs for unchanged components; run an integrated fresh-entry
journey to establish that provisioning, interfaces and retention compose. Retain
the tested artifact/environment, workload, commands, outcomes and known support
limits in the existing acceptance record. Do not substitute an API skeleton,
mocked service, tiny fixture or closed milestone count for the boundary it cannot
prove. An unverified required boundary keeps onboarding acceptance open.

## Research phase after full handoff

Only after every MR01–MR16 outcome, including MR07A/MR07B, and MR17/G5 integrated acceptance does QR begin
the [research milestones](research-program.md#post-infrastructure-research-milestones):

1. **QR-M1 — Research-ready:** question-specific data acceptance, ranked hypotheses,
   preliminary economics and an executable evaluation protocol.
2. **QR-M2 — End-to-end prototype:** reproducible feature/label and rule/model code,
   a complete policy, costed replay and ledger reconciliation.
3. **QR-M3 — Evidence-backed decision:** robustness, final evaluation and
   risk/capacity evidence supporting a forward-validation proposal or rejection.

The research program owns QR-01–QR-18 across readiness, signal experiments,
strategy prototypes and conditional candidate validation/handoff. All are planned
and not started. Even QR-M1 waits for the full infrastructure; G2's research-ready
engineering increment is not QR-M1. A losing or rejected study can be a completed
research outcome. Surviving candidates need frozen reproduction/parity and forward
evidence before a deployment recommendation; actual activation remains separate.

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
