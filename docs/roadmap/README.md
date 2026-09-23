# Platform infrastructure roadmap

Owner: repository founder; quant development owns infrastructure delivery.
Status updated 2026-09-23. Delivery policy: complete the initial infrastructure
stack before quant researcher (QR) onboarding.

This page owns delivery status, remaining work and dependencies. The completed
MR09A saved-book baseline retains its historical identity. The remaining work
is numbered MR01–MR17 and is planned; this revision completes no capability.
Component guides own implemented behavior. Historical delivery records remain
in Git history; P1 stays deferred and unaccepted.

The [QR implementation guide](../../examples/README.md) explains how researchers
use the available capabilities. The [research program](research-program.md) owns
methodology and experimental choices. The [platform design](../architecture/platform-design.md)
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
| Features and labels | Typed extensible definitions, execution/alignment, lineage, fitted-transform lifecycle, batch/incremental state and recovery | Formulas, targets, windows, transformations and missingness choices within the supported contracts |
| Models and rules | Training/inference adapters, temporal evaluation/search, artifact reload, prediction-to-target binding and isolated state | Estimator/strategy implementations, parameters, comparison space and selection criteria |
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
- Multiple instruments and two independent strategy instances exercise selection,
  scheduling, risk and attribution, including a shared paper account.
- A custom metric and chart exercise retained research reports and runtime
  dashboards; missing/late observations and an alert exercise failure semantics.

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

## Delivery order and dependencies

All rows below are required for the initial infrastructure gate. The restarted
numbering follows delivery scope: MR01–MR04 close research/data usability gaps left by
the bounded foundations, and MR17 proves the integrated QR handoff. Quant development
owns every row. Dependencies are technical capabilities and reference workloads,
not progress in the [research program](research-program.md).

### Research and data foundation completion

| MR | Planned delivered behavior and sufficient completion evidence | Dependencies |
| --- | --- | --- |
| MR01 | **Usable spot data/reference plane.** Extend `market_data`, `reference_data` and data applications for the declared OKX/Bitfinex sources: configurable capture/backfill, current and historical reference facts with honest availability, catalog discovery, pinned selections, quality/coverage inspection and causal multi-input assembly. From a clean workspace, discover, read and replay saved inputs; recover interrupted ingestion and expose unsupported/gapped data without notebook-created manifests or invented clocks. | Existing data access/attempt contracts and MR09A; source policy and declared source access |
| MR02 | **Research component contracts.** Extend `research.features`, `labels`, `models`, `observations` and `strategies` beyond the fixed return/linear schemas: named trade/book features, labels, multi-feature inputs, fitted transforms, estimator/state adapters, predictions-to-targets and batch/incremental lifecycle. Run the rule-only, learned and stateful reference consumers through the same public contracts; future perturbation and restart preserve the declared semantics. | MR01 and existing feature/model/split owners |
| MR03 | **Complete study/backtest/report APIs.** Extend `research.studies`, `experiments`, `simulation` and applications with typed in-memory and serialized configuration, injected compatible implementations end to end, explicit local/deferred publication, typed result readers, temporal/walk-forward evaluation, parameter search, configurable execution/cost assumptions and custom metrics/charts. A reference author adds a feature/rule/model and a study/report without changing shared orchestration; attempts, exclusions and holdout history survive failures and publication retries. | MR02; reuse existing accounting/risk and reports |
| MR04 | **Reproducible workspace and job services.** Extend configuration/runtime/storage and development profiles with provisioned data/artifact/experiment stores, feature retrieval, job scheduling/cancellation/retry, bounded concurrent research workers, secrets references, backup/restore and service health. A clean environment runs and reopens retained studies without manual directory repair, monkeypatching tracking or reinstalling a running worker; job failure cannot duplicate an attempt's effects. | Start from existing local services; integrate MR01–MR03; MR06 before deployment |

### Runtime, operations and handoff

| MR | Planned delivered behavior and sufficient completion evidence | Dependencies |
| --- | --- | --- |
| MR05 | **[Candidate packaging and runtime binding](../architecture/platform-design.md#candidate-promotion-contract).** Package rule-only and learned reference candidates with input/state/metric contracts; load the same components into replay and runtime with compatibility rejection. A reference candidate proves the loader, without claiming accepted research or activation permission. | MR02–MR03 |
| MR06 | **[Trusted deployment artifact](../governance/workflow.md#build-a-release).** Build, verify, install and roll back pinned artifacts/configuration/state on the declared target; reject provenance, dependency, signature and compatibility failures. Develop against the reference runtime; resolve current release restrictions before deployment acceptance. | Existing build/admission; MR04 environment profile, which can be developed locally first |
| MR07 | **[Paper/shadow runtime and OMS](../architecture/platform-design.md#oms-and-venue-adapter-design).** Supervise candidates, inputs and durable order state; support the declared order lifecycle, partial fills, cancel/replace, unknown outcomes and restart. Replayed/live-data paper and shadow runs exercise the same decision code with executable submission suppressed. | MR05; MR06 before deployment; base independent spot controls remain active throughout |
| MR08 | **[Independent risk and reconciliation](../architecture/platform-design.md#multi-strategy-netting-and-isolated-risk).** Enforce instrument/instance/account limits and pending reservations; reconcile orders, fills, positions, cash and fees. Stale state, duplicates, unknown sends and reconciliation breaks produce the defined safe response. | MR07 and existing risk/accounting |
| MR09 | **[Portfolio and shared-account infrastructure](../architecture/platform-design.md#multi-strategy-netting-and-isolated-risk).** Implement allocation/target interfaces, compatible netting, budgets, attributable orders/fills/costs and shared-account recovery. Two engineering strategies share a paper account and reconcile independently and in aggregate; neither can bypass account protection. | MR08; required before onboarding, even without QR strategies |
| MR10 | **[Operational qualification](../architecture/platform-design.md#monitoring-recovery-and-operational-evidence).** Deliver runbooks and commands for service startup, stop, restart, reconciliation, backup/restore and rollback. Reference paper workloads pass process/data/service-loss drills with retained state and alert outcomes. | MR04, MR05–MR09 |
| MR11 | **[OKX/Bitfinex execution adapters](../architecture/platform-design.md#oms-and-venue-adapter-design).** Implement declared spot order/account operations, authentication boundaries, throttles, durable client IDs and reconciliation. Retain per-venue conformance evidence in an authorized test environment; protocol fixtures supplement rather than replace unavailable external proof. | MR07–MR08 contracts; MR06 before deployment; required venue access |
| MR12 | **[Monitoring, metrics, charts and alerts](../architecture/platform-design.md#monitoring-recovery-and-operational-evidence).** Provide versioned event/metric APIs, queries, retained dashboards, configurable panels/thresholds, alert routing and default data/runtime/risk/account views. Register a custom research metric/chart and delayed-label diagnostic without modifying collectors or runtime; test telemetry loss independently of hard controls. | MR03 report contracts; MR08–MR11 runtime signals; basic telemetry ships earlier with each capability |
| MR13 | **[Activation and recovery machinery](../governance/workflow.md#activate-and-operate).** Implement disabled-by-default authorization envelopes, scoped limits, fencing, stop/cancel and recovery commands. Reference/test-environment scenarios prove rejection of absent/expired authority and safe restart; completion does not require or grant live capital use. | MR06, MR10–MR12 |
| MR14 | **[Multiple-instance integration](../architecture/platform-design.md#multi-strategy-netting-and-isolated-risk).** Run different reference components and instruments with isolated/shared-account configurations through paper/shadow; add an instance through configuration, then stop/restart it without losing attribution or weakening other accounts' controls. | MR09, MR12–MR13; actual live use remains separately authorized |
| MR15 | **[Research and runtime capacity qualification](../architecture/platform-design.md#scaling-triggers-and-technology-choices).** Quant development defines and meets a launch workload covering multi-day data, multiple instruments, concurrent studies, trials, replay, live ingestion and dashboard queries. Record numeric volume/retention/concurrency/latency/recovery budgets and hardware before testing; remove the current demonstration-size limits where they prevent that workload. Prove causal/numerical parity and bounded resource/recovery behavior; deploy only the storage/compute topology needed to meet it. | MR01–MR04 for research measurements; MR07/MR12/MR14 for final runtime measurements; no QR bottleneck required |
| MR16 | **[Python ownership and enforcement](../coding_standards/README.md#python-scope-and-migration).** Complete the retained ownership/enforcement work with supported imports, packaging, checks and migration guidance; verify the APIs consumed by the reference workflows. | Existing engineering rules; can proceed alongside other work |
| MR17 | **[QR onboarding acceptance](#qr-onboarding-acceptance).** Exercise the installed integrated stack from a clean environment with fresh research extensions and the published onboarding guide. Close every in-scope platform gap before declaring it ready for QR. | All planned rows above, retaining valid earlier evidence |

The research path is MR01 → MR02 → MR03 → MR05. MR04's local development profile can
start alongside it and supplies MR06's installation target; MR06 does not wait
for MR04's deployed-service acceptance. MR04's deployed services then use the
verified installation path. MR06 precedes every deployment.

MR07 supplies the runtime/OMS for MR08; portfolio integration (MR09) and venue
adapters (MR11) follow those contracts. MR10 can qualify paper operations before
MR11 external qualification. MR12 joins the report, operational and venue paths
before MR13–MR14 qualify activation machinery and multiple instances. MR15 starts
with research measurements and completes against the integrated runtime before
MR17. MR16 can proceed alongside other work. The tables own exact prerequisites.

## QR onboarding acceptance

Quant development demonstrates the following with public APIs, installed artifacts,
maintained examples and the documented environment, without a QR supplying missing
infrastructure or selecting an alpha:

1. Provision a clean workspace, discover/admit the declared inputs, and reopen
   exact retained data/results with source quality and limitations visible.
2. Add fresh compatible feature/label, estimator and rule implementations plus
   a study specification. Execute rule-only and learned paths through temporal
   evaluation, costed backtesting and retained comparison reports. The extension
   must not be one of the runner's built-in special cases.
3. Define a custom metric and chart once through the supported contracts; inspect
   historical and paper/shadow outputs with declared applicability, units,
   missingness and alert behavior. No shared runner or dashboard-engine edit is needed.
4. Package/load candidates, run multiple paper/shadow instances, and exercise
   independent risk, account reconciliation, failure/restart and stop controls.
   Reference components do not acquire live authority by being installed.
5. Meet the MR15 workload budgets, recover data/artifacts/state from backup, and
   show per-venue/service integration evidence and the runnable operational guide.

Reuse milestone proofs for unchanged components; run an integrated fresh-entry
journey to establish that provisioning, interfaces and retention compose. Retain
the tested artifact/environment, workload, commands, outcomes and known support
limits in the existing acceptance record. Do not substitute an API skeleton,
mocked service, tiny fixture or closed milestone count for the boundary it cannot
prove. An unverified required boundary keeps onboarding acceptance open.

After this gate, QR owns empirical hypotheses, strategy/model content, backtest
design, metrics/charts and their interpretation. Research acceptance and any
strategy-specific operating qualification remain necessary before actual use;
they do not retroactively become prerequisites for building the shared stack.

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
