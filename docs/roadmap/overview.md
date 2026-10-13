# Platform roadmap

Owner: repository founder; quant development (QD) owns infrastructure delivery.

The platform delivers research and paper-trading infrastructure for OKX and Bitfinex
spot before a quant researcher (QR) is onboarded. Live trading is
[kept in view](#live-trading-kept-in-view): it is outside the current scope and reopens
only through its evidence gate.

**Status.** Every capability below is accepted for its stated scope, except two:
- [runtime capacity](runtime-capacity.md), which waits for the counted day run;
- [QR onboarding acceptance](qr-onboarding.md), the final gate (G5).

The [remaining work](#remaining-work-before-qr-onboarding) lists what is left. Once G5 is
accepted, QR work follows the [research program](../research/program.md).

## Scope

**Markets.** OKX and Bitfinex spot, with explicit extension interfaces for other assets.
The scope covers:
- historical and captured market data, and reference data;
- research and model lifecycles, and backtesting;
- portfolio and account state;
- paper and shadow execution, and paper service deployment;
- monitoring and recovery;
- the storage and computation to run them.

Each capability's record states its supported venue operations, order types, dataset
history, workload sizes and operating modes. Both venues need their own conformance
evidence: one venue's pass does not qualify the other.

**Paper trading** uses live public inputs, with simulated orders, fills, balances and
positions. No order uses real capital. Shadow mode compares decisions but does not
replace paper fill, account and cost evidence. Authenticated venue execution is outside
this scope.

**Generality.** The platform is a multi-asset, multi-source, multi-strategy monorepo,
and differences are localized behind typed contracts:
- Target-position and order/quote decisions share one portfolio, risk, OMS and
  accounting boundary.
- Market and non-order-book inputs stay distinct; nothing is forced into one feed
  representation.
- Shared contracts allow several deployment artifacts, compatible runtime environments
  and independent release cadences.
- The required infrastructure includes a versioned feature store (offline
  point-in-time retrieval, online materialization and serving), experiment, model and
  artifact tracking, dataset versioning, concurrent job services, allocation and
  netting, paper execution for both venues, reports, dashboards and recovery.
- Feast, lakeFS and ClearML are integrated through owned interfaces. Replacing a
  technology needs equivalent behaviour and migration evidence.

**Later scope.** Other asset adapters and lifecycle mechanics, derivatives, borrowing,
on-chain execution and specialized low-latency infrastructure. Their neutral interfaces
keep units, currencies, product capabilities and lifecycle distinctions, and refuse
unsupported behaviour. An extension point does not claim that those products work.

**Separate outcomes.** Infrastructure acceptance, empirical strategy acceptance and
trading activation are separate:
- QD qualifies the machinery with engineering workloads, including losing and no-trade
  cases.
- The QR later supplies and evaluates research content.
- Credentials, purchases, deployment and live capital keep their own authority. This
  roadmap grants none of them.

An unavailable data or paper service integration blocks that capability's
qualification, while independent work continues. Missing private venue credentials do
not block paper delivery or QR onboarding.

## Responsibilities

| Boundary | QD delivers before onboarding | QR supplies through the delivered interfaces |
| --- | --- | --- |
| Data | Source adapters, reference and universe contracts, collection and backfill, quality, revisions, discovery, point-in-time assembly, storage and replay | Research universe, datasets and fields, sample, horizon and stricter question-specific quality requirements |
| Features and labels | Typed extensible definitions, execution and alignment, lineage, fitted-transform lifecycle, batch and incremental state, versioned offline/online feature-store access and recovery | Formulas, targets, windows, transformations and missingness choices |
| Models and rules | Training and inference adapters, temporal evaluation and search, artifact reload, prediction-to-target or order-intent binding, isolated state | Estimators, strategies, parameters, comparison space and selection criteria |
| Backtesting | Study runner, execution and cost models (transaction costs, slippage, applicable gas), portfolio, risk, accounting, checkpoints and net-of-cost analysis | Backtest specifications, hypotheses, scenarios, economic assumptions and interpretation |
| Metrics and charts | Versioned metric and result contracts, computation, query and export, report and dashboard rendering, alert evaluation | Research metrics, chart definitions, diagnostic views and strategy thresholds |
| Paper promotion and operation | Candidate loading, trusted artifacts, provisioning, scheduling, paper OMS and execution, reconciliation, limits, stop, recovery and cost-attributed paper reports | Candidate content, out-of-sample and forward paper evidence, investigation and proposed revisions |

A QR's strategies, features, estimators, backtest specifications, metrics and charts
work through public APIs and configuration, with no edits to shared runners, storage,
execution or telemetry. Hard risk limits and operating authority are not extension
points. A new asset mechanic or source protocol is QD work. A promised extension point
that does not work is an infrastructure defect, not a QR task.

## Reference workloads

QD owns the first consumers and keeps them executable. They are engineering examples,
not research recommendations:
- a rule-only spot study over retained books, a no-trade control, and a losing,
  cost-sensitive case;
- a learned example with several named features and fitted preprocessing: train-only
  fitting, labels, temporal evaluation, artifact reload, and predictions flowing into
  targets; a stateful feature or rule exercises warm-up and restart;
- several instruments and two active strategies on a shared paper account, with target
  and order/quote intents, competing risk requests and attribution;
- one versioned feature definition through offline retrieval, incremental
  materialization and online serving, with matched-cutoff parity, revisions, missing
  entities, staleness, restart and rollback;
- a custom metric and chart in research reports and runtime dashboards, with missing or
  late observations and an alert;
- a small non-order-book dataset, and a non-24/7 calendar or different-economics
  fixture, to show extension boundaries and explicit refusal.

Small independent fixtures prove exact, causal and failure behaviour. Saved or live
public inputs prove adapter and service boundaries. Fixtures do not establish
historical availability, source completeness, venue execution fidelity or alpha.

## Data source policy

New work avoids Binance and Tardis data because of availability constraints:
- Use OKX or Bitfinex where the data and capabilities exist. L2 work starts from the
  saved OKX order-book workflow.
- If neither supports the scope, record the gap and choose an alternative explicitly.
  Never fall back to Binance or Tardis silently.
- Existing Binance and Tardis adapters and fixtures keep their identities. Further
  provider outreach is deferred.

## Acceptance gates

| Gate | Observable acceptance | Status |
| --- | --- | --- |
| G1 — Foundation and contracts | Clean installed build; typed configuration; four distinct universes; versioned reference data and adapter capability admission; incompatible inputs refused before work | Accepted |
| G2 — Research-ready | From a clean workspace: capture inputs, publish pinned datasets, retrieve versioned offline features, add a fresh strategy, feature and model, run temporal studies and costed backtests, reopen results; meet the research capacity profile; restore data and artifacts | Accepted; [research capacity](research-capacity.md) by extrapolation, with the measured run still required |
| G3 — Paper and shadow | Decision components on live inputs with submission suppressed: online features, durable order state, independent risk, reconciliation, alerts and restart | Accepted |
| G4 — Integrated paper operations | Shared-account controls and netting, both venues' paper execution, cost attribution, monitoring, paper activation and failure drills, within the runtime capacity profile | Open until the [day run](runtime-capacity.md#day-run) passes |
| G5 — QR handoff | Fresh extensions through the installed integrated stack, every research and paper launch workload, data and service evidence, and the operator and researcher guides | Open: [QR onboarding acceptance](qr-onboarding.md) |

## Capabilities

Each capability is accepted for the scope stated. Its package guide owns the
interface. No capability establishes private venue execution, live orders or
profitability.

| Capability | Accepted scope | Not established |
| --- | --- | --- |
| Data and reference plane | Bounded OKX and Bitfinex public spot trades and books; configurable capture and backfill; versioned venue specifications; catalog discovery; pinned selections; quality and coverage; causal multi-input assembly; separate collection, research, strategy and trading universes ([market data](../packages/market-data.md), [data contracts](../data/contracts.md)) | A complete historical tape, historical receipt reconstruction, Bitfinex book backfill; current metadata cannot establish earlier venue rules |
| Research and decision contracts | Named trade, book and non-book inputs, multi-feature schemas, fitted transforms, estimator and state adapters, predictions to targets or order/quote intents, batch and incremental lifecycle ([features](../packages/research-features.md), [models](../packages/research-models.md), [strategies](../packages/strategies.md)) | Supplied component code is trusted |
| Studies, backtests and reports | Typed configuration, injected implementations end to end, temporal and walk-forward evaluation, parameter search, configurable execution and cost models, custom metrics and charts; cash-funded spot, at most 32 folds, 1,024 decisions a schedule and a 1–32-variant grid ([studies](../packages/research-studies.md), [simulation](../packages/simulation.md)) | Passive queue and latency are synthetic sensitivities; authored grids do not qualify exchange fills |
| Feature store, workspace and jobs | Versioned offline and online feature paths with causal retrieval, incremental materialization, validation, TTL, idempotent retry, restart and rollback; lakeFS and ClearML; scheduling, cancellation, bounded workers, backup and restore, on one trusted local POSIX workspace ([feature store contract](../architecture/research-and-simulation-design.md#feature-store-contract)) | Shared-host authentication, distributed leases, external exactly-once execution |
| Candidate packaging | Rule-only and learned candidates with input, feature, state and metric contracts; the same components in replay and runtime; a typed capability registry that refuses unsupported combinations before startup ([candidate promotion contract](../architecture/research-and-simulation-design.md#candidate-promotion-contract)) | Unimplemented product economics fail closed |
| Packages and trusted installation | Independent collector and execution closures; build, verify, install and roll back signed artifacts on Darwin arm64 with CPython 3.14.7 ([release workflow](../governance/workflow.md#build-a-release)) | Linux and remote deployment, production key provisioning |
| Paper and shadow runtime and OMS | Supervised candidates with checkpointed state; durable order-intent journal; partial fills, rejects, cancel/replace, unknown outcomes and restart; one fenced execution owner ([OMS design](../architecture/portfolio-and-execution-design.md#oms-and-venue-adapter-design)) | Paper touch matching models no queue position or impact. Research-aligned decision lifecycle (D2) is implemented for shared accounts and the dedicated journal; fill-model, queue and IOC-lifetime differences remain ([details](../packages/execution.md#unfinished-replacement-alignment)) |
| Book quotes | One typed per-book quote contract for native L2 and L3; exact incremental L3 aggregates; a book registry with per-venue and consolidated BBO over explicitly equivalent instruments ([shared book quotes](../packages/market-data.md#shared-book-quotes)) | No implicit FX; no queue priority inferred |
| Paper risk and reconciliation | Authorized instruments; instance, account and firm limits with atomic pending and uncertain reservations; independent reconciliation of orders, fills, positions, cash and fees for both venues ([execution](../packages/execution.md)) | Authenticated physical account reconciliation |
| Portfolio and shared accounts | Allocation and order-intent coordination, budgets, conflict and self-trade prevention, strategy-tagged children, netting, deterministic allocation of fills, residuals and costs ([portfolio design](../architecture/portfolio-and-execution-design.md#multi-strategy-netting-and-isolated-risk)) | Other product economics and FX fee conversion |
| OKX and Bitfinex paper execution | Native OKX books and Bitfinex R0 into the decision SDK, risk, paper matching, ledgers, reconciliation and cost/P&L reports; versioned execution scenarios with entry and cancellation delays, fees, adverse prices and finite touch liquidity; gas declared inapplicable with a reason ([paper application](../packages/paper-application.md)) | Exchange fill, queue or latency calibration; native private adapters are kept as software evidence only |
| Monitoring | Versioned events and metrics, causal revision queries, retention, bounded dashboards that verify their inputs on reopen, local alert routing; default data, runtime, risk, account and economic views ([telemetry](../packages/telemetry.md)) | Continuous or remote monitoring, human acknowledgement |
| Activation and recovery | Disabled signed deployments with separate finite grants; durable owner generations; stop, cancellation and attributable reduction kept distinct; reconciliation before restart; signed rollback that keeps current facts ([operations](../governance/operations.md)) | Historical cross-version schema migration |
| Multi-instance services | Up to four signed account owners, native source processes and isolated policy instances over shared and isolated accounts, in paper and shadow; controlled activation of a provisioned inactive instance; selective stop and restart ([runtime](../packages/runtime.md)) | Remote or hostile isolation, cross-journal firm limits, implicit USD/USDT FX |
| Python ownership | Ownership rules enforced with no waiver; supported imports published and verified installed ([engineering standards](../development/engineering-standards.md)) | — |
| Research capacity | Accepted by extrapolation from measured 2-hour and 6-minute runs ([research capacity](research-capacity.md)) | A measured 72-hour run, which is [required](../research/program.md#measured-research-capacity) |
| Runtime capacity | Baseline and sustained runs qualified ([runtime capacity](runtime-capacity.md)) | The counted day run, its replay and retention |

## Remaining work before QR onboarding

The consolidated sequence (owner, 2026-10-12). On 2026-10-12 the owner moved the
counted day run and its retention to the end of the work. `day-counted-2` failed and
stays failed ([failed attempts](runtime-capacity.md#failed-attempts)); the shutdown fix
and the supervisor delivery gate passed uncounted checks on `d91d7cd`
([integration checks](runtime-capacity.md#uncounted-integration-checks)), which the
final candidate will very likely supersede.

1. **Finish the work.** The remaining decisions and their implementation, including
   the efficiency and storage work, then the bounded
   [efficiency measurements](runtime-capacity.md#efficiency-measurements) before
   any final acceptance run.
2. **Development preflight.** One fault-injection J1–J7
   [development run](qr-onboarding.md#development-runs) after those changes land. The
   last one, rehearsal-135 on `c4a5f78`, predates the telemetry, shutdown, supervisor
   and paper decision-lifecycle changes, so it does not cover them.
3. **Freeze one candidate** before either counted run, and verify it: the commit, the
   built artifacts and installed identity, and the configuration and evidence identities
   ([day-run host checklist](runtime-capacity.md#day-run-host-checklist)). Both counted
   runs qualify this same candidate.
4. **Day rehearsal** (2 hours) on the frozen candidate, because the journal and runtime
   changed since the last one. Equivalent earlier evidence is reused only if it covers
   this candidate and workload, and the record explains the reuse.
5. **Counted runs.** The counted J1–J7 [journey](qr-onboarding.md#counted-attempt)
   (separate owner approval; the owner chooses its host), then the counted
   [day run](runtime-capacity.md#day-run) and its 4× replay on the declared day-run host
   (estimated 32–34 hours together; an owner-booked slot of about 36 hours). No fault
   injection overlaps the measured day.
6. **Retention clock.** The 72 hours start when the measured day ends. The replay runs
   while retention elapses; no further 72-hour wait follows it.
7. **Measured research capacity.** The
   [72-hour run](../research/program.md#measured-research-capacity) may start once the
   day and its replay release the host, and may overlap the rest of the retention
   interval. Its acquisition and processing requirements are unchanged, and so is its
   relationship to J8 and G5.
8. **Retention verification** when eligible, then J8 and G5 once their required
   evidence passes.

**Acceptance policy (owner, 2026-10-12).** This replaces the earlier order, which froze
code only after the counted day run passed and added a full uncounted journey on the
frozen commit.
- The freeze precedes both counted runs, and the counted journey and day evidence
  belong to that one frozen candidate.
- A full uncounted journey on the frozen candidate is no longer required; the
  development preflight (step 2) covers the code before the freeze.
- Consolidation removes redundant runs and overlaps eligible waits. It does not shorten
  a measurement, relax a threshold or waive a gate.
- Failed attempts keep their original outcomes. Diagnostics never turn a failed attempt
  into a pass.

**Candidate changes and reruns.** Evidence is valid for the candidate, workload,
configuration and grading semantics it was taken under. A change after the freeze is
classified by its effect on that validity and recorded before any rerun:
- *Guide or record only*: it changes no executable artifact, workload, configuration or
  grading semantics. It does not by itself require a rerun. A counted attempt is still
  never patched while it runs.
- *Code*: any change to an executable artifact makes a new candidate. Same-candidate
  acceptance then needs a renewed counted journey and the new candidate's own day
  evidence from steps 4–6: the rehearsal (or equivalent evidence for that candidate),
  the counted day with its 4× replay, and retention.
- *Workload, configuration or grading semantics without a code change*: every run whose
  evidence the change affects is repeated under it, and the record names those runs and
  why the others stay valid. A change that alters a recorded candidate identity makes a
  new candidate, as for code.
- A replacement counted day starts its own 72-hour retention clock when its measured day
  ends, with its replay inside that window. No other rehearsal or retention wait is
  added, and an earlier attempt's retention never stands in for it.
- Earlier attempts stay recorded with their actual outcomes; a rerun replaces none of
  them.

## Decisive acceptance scenarios

Each scenario is proven at its owning boundary and reused in the onboarding journey,
with independent expected results and targeted faults.

| Scenario | Required observable result |
| --- | --- |
| Universe and capability admission | Adding collection or research membership does not grant trading permission. Unsupported feeds, product economics, order types or feature signatures fail before executable work |
| Historical reference change | A tick, lot or specification change resolves by valid time and knowledge time; older runs keep their specification, and unknown history is not replaced by current metadata |
| Fresh research extension | A new feature, label, non-built-in estimator and strategy reach study, report, candidate and runtime without edits to generic runners or fallback to built-ins |
| Feature-store parity and recovery | Matched definitions, entities and cutoffs reproduce offline and online values. Late corrections, TTL expiry, missing entities, materialization retry and version rollback stay explicit and cannot leak future values |
| Book and consolidated quote parity | Incremental L3 aggregates match independent expected levels and BBO; isolation, cutoffs and freshness keep provenance, ties and partial coverage |
| Shared-budget race | A and B each request 8,000 units against a shared 10,000 limit. Admitted, pending and uncertain commitments never exceed 10,000; retry or restart cannot release unknown exposure |
| Conflicting strategies and netting | Two strategies on one instrument keep intent, child-order and fill ownership; self-trade conflicts follow policy; netting, partial fills, fees and residuals reconcile to both allocations and the account; stopping one preserves the other |
| Paper order uncertainty | Lost acknowledgement, duplicates, rejects, partial fills, cancel/fill races, event loss and restart with open orders cannot duplicate submissions or postings. A cancel acknowledgement alone does not release exposure |
| Paper cost and economics | Transaction costs, slippage and applicable gas reconcile from simulated fills to strategy and account net P&L. Missing costs or unjustified gas inapplicability prevent economic acceptance |
| Faults and operator actions | Disconnects, order-event loss and timeouts, malformed messages, clock regression, queue overload, disk exhaustion and process loss cause their declared visible response. Block, cancel and reduce stay distinct; telemetry loss cannot disable hard controls |
| Trusted installation and restoration | Install a research or paper artifact in a clean environment without production submission authority; refuse incompatible state; restore data, features, artifacts and account state, and reconcile before resuming |
| Architectural extension | Add an instrument by configuration and an adapter through its public boundary; carry a non-book input and a non-24/7 calendar or different-economics fixture through research and simulation; refuse unsupported lifecycle behaviour |

## QR onboarding acceptance

QD demonstrates the following with public APIs, installed artifacts, maintained
examples and the documented environment, without a QR supplying missing infrastructure
or selecting an alpha:
1. Provision a clean workspace, discover and admit the inputs, and reopen exact retained
   data and results, with source quality, specification versions and limits visible.
   Collection and research selections cannot authorize trading.
2. Add fresh feature, label, estimator and rule implementations and a study
   specification. Run rule-only and learned paths through temporal evaluation, costed
   backtests and comparison reports, with both target and order/quote decisions and the
   architectural extension scenario.
3. Define a custom metric and chart once, and inspect historical and paper/shadow
   outputs with applicability, units, missingness and alerts.
4. Retrieve versioned offline features, materialize and serve them online, and show
   parity, missing, stale and revised inputs, recovery and version rollback.
5. Package and load candidates; run two strategies on shared and isolated paper
   accounts with independent risk, netting, allocation reconciliation, order
   uncertainty, selective stop and recovery; keep separate OKX and Bitfinex paper
   evidence with cost and slippage attribution, gas applicability, net P&L and
   adverse-cost scenarios.
6. Meet the research and runtime capacity profiles; restore data, features, artifacts
   and state from backup; show independent package installation, trusted paper
   deployment and rollback, service integration and the operator guide.

The [onboarding record](qr-onboarding.md) declares the integrated journey that proves
these. An API skeleton, mocked service or small fixture never substitutes for a
boundary it cannot prove. An unverified boundary keeps acceptance open.

## Research after the handoff

The QR begins the [research milestones](../research/program.md#post-infrastructure-research-milestones)
only after G5:
1. **Research-ready:** question-specific data acceptance, ranked hypotheses,
   preliminary economics and an executable evaluation protocol.
2. **End-to-end prototype:** reproducible feature, label, rule and model code, a
   complete policy, costed replay and ledger reconciliation.
3. **Evidence-backed decision:** robustness, final evaluation and risk and capacity
   evidence supporting a forward paper-validation proposal or a rejection.

A losing or rejected study is a completed research outcome. These deliverables consume
the platform and add no infrastructure milestones.

## Live trading kept in view

Live trading development, production order routing, authenticated venue execution,
live account recovery and real-capital activation are outside the current scope.
Existing interfaces, adapters and evidence are kept, without claiming that live
requirements are met.

**Reconsideration gate.** Live work is reconsidered only when the same frozen strategy
has both untouched out-of-sample evidence and forward paper evidence showing
profitability net of transaction costs, slippage and applicable gas fees:
- Gross returns, an in-sample backtest, shadow decisions or engineering fixtures do not
  qualify.
- Evaluation periods, sample sufficiency, selection and stop criteria, cost assumptions
  and adverse scenarios are declared before testing. Thresholds are never chosen after
  seeing results.
- Gas is charged for required on-chain activity, or its inapplicability is recorded with
  a reason. Missing cost evidence is unresolved, never zero.

Passing the gate permits a decision to reopen live work. It does not qualify exchange
fills or authorize deployment or capital. Reopened live scope needs its own venue,
security, execution and recovery qualification and an explicit activation decision.

## Working rules

- Before implementing a capability, state its observable outcome, supported envelope,
  reference workload, dependencies and the smallest sufficient proof.
- QD makes routine implementation and workload choices, and never defers an in-scope
  capability until a QR asks for it.
- When a capability is complete, update its package guide and the capabilities table.
- Follow the [engineering standards](../development/engineering-standards.md) and the
  [development workflow](../governance/workflow.md). Implementation, research
  acceptance, artifact admission, deployment and trading activation stay separate.
