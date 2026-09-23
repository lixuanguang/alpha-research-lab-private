# Platform infrastructure roadmap

Owner: repository founder; quant development owns infrastructure delivery.
Status updated 2026-09-24. Delivery policy: complete the initial infrastructure
stack before quant researcher (QR) onboarding.

This page owns delivery status, remaining work and dependencies. The completed
MR09A saved-book baseline retains its historical identity. The remaining work
is numbered MR01–MR17. MR01 is complete for its declared read-only data/reference
scope; MR02 is complete for its declared research/decision SDK scope; MR03–MR17
remain planned. The [MR02 record](#mr02-delivery-and-acceptance) states its evidence
and the later integration boundaries. The [MR01 record](#mr01-delivery-and-acceptance)
states its bounded support and evidence.
Component guides own implemented behavior. Historical delivery records remain
in Git history; P1 stays deferred and unaccepted.

This revision strengthens generalization and acceptance without reducing the
destination. Intermediate gates expose usable increments; they do not retire
feature-store, portfolio/netting, second-venue, dashboard, capacity or handoff
requirements. All MR01–MR17 outcomes remain mandatory before formal QR onboarding.

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
immutable datasets, experiment history, exact spot accounting and an isolated
Feast offline bridge are reusable foundations; shared-account trading, online
feature serving and a deployed OMS are not thereby qualified. Library registries
also require end-to-end consumer acceptance before claiming general extensibility.

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
| G5 — Generalized handoff | Demonstrate fresh extensions through the installed integrated stack, all launch workloads, service/venue evidence and the operator/researcher guides. | MR17, after every MR01–MR16 outcome. This is full infrastructure acceptance, separate from empirical strategy acceptance and activation. |

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
| MR03 | **Complete study/backtest/report APIs.** Extend `research.studies`, `experiments`, `simulation` and applications with typed in-memory and serialized configuration, injected compatible implementations end to end, explicit local/deferred publication, typed result readers, temporal/walk-forward evaluation, parameter search, configurable execution/cost models and custom metrics/charts. Exercise target and order-intent strategies, including declared passive-fill/queue assumptions and sensitivity cases. A fresh feature/rule/model reaches the installed workflow without shared orchestration edits or replacement by a built-in default; attempts, exclusions and holdout history survive failures/publication retries. | MR02; reuse existing accounting/risk and reports; offline order-lifecycle contracts do not wait for a deployed OMS |
| MR04 | **[Feature store](../architecture/platform-design.md#feature-store-contract), reproducible workspace and job services.** Provision versioned data/artifact/experiment stores and offline/online feature-store paths, with causal historical retrieval, incremental materialization, entity/schema/version validation, freshness/TTL and missingness, idempotent retry, restart and rollback. Extend the isolated Feast integration and pinned lakeFS/ClearML paths while preserving independent compatible environments. Deliver scheduling/cancellation/retry, bounded concurrent workers, secrets references, backup/restore and service health. A clean workspace reopens studies and matched-cutoff features without manual repair or replacing an active worker; job failure cannot duplicate effects. | Start from existing local services and offline bridge; MR02 feature contracts and MR01 inputs; integrate MR03; qualify online consumption with MR05/MR07; MR06 before deployment |

### MR01 delivery and acceptance

Status: **complete for the declared read-only data/reference scope**, 2026-09-23.
Owner: quant development. This record concerns the current infrastructure MR01,
not historical deliveries or any QR research milestone.

Delivered through the existing owners and installed applications:

- OKX/Bitfinex public spot trade backfill and bounded recent-trade polling,
  exact native bytes/units/IDs, checked source-specific pagination, retained
  pending receipts and restart without refetching acknowledged input.
- Source-observed, content-versioned venue rules with valid/knowledge-time
  resolution, explicit corrections and unknown history. Complete rules feed
  the existing spot order-grid boundary; incomplete rules refuse admission.
- Four independent universes, saved in public jobs and optional scoped native
  captures. Data/source/reference/calendar requirements fail before work;
  current readers enforce the selected collection/research/strategy boundaries.
- Public-trade publication through the existing `RawStore` / `SnapshotStore`,
  catalog discovery, pinned CLI reads, cutoff revision selection, typed replay
  cursors and causal named trade/book/non-book-reference assembly. Historical
  Binance/Tardis identities, native book formats and selected integrations remain.
- A configuration-only OKX ETH onboarding case and an installed reference
  consumer which creates pinned selections from completed inputs without a
  notebook-created manifest. Negative fixtures reject unsupported products and
  non-continuous calendars; existing C02 tests retain non-24/7 calendar evidence.

Dependencies are capability slices, not completed later milestones. MR16 owns
the shared typed admission/interface slice used here; broader package isolation,
registry enforcement and engineering migration remain MR16/MR06 work. MR08 owns
the reference-driven order-grid/minimum-size admission slice; independent account
risk, reservations and reconciliation remain open. Named input assembly belongs
to MR01; generalized features/models, study APIs and runtime promotion still
belong to MR02/MR03/MR05. G1 as a whole and G2–G5 are not accepted by this delivery.

The [data guide](../../src/market_data/README.md#public-spot-data-plane) owns commands
and recovery. The [reference contract](../data/contracts.md#versioned-venue-specifications-and-scoped-universes)
owns temporal facts and the four universes. Quant development's
[installed consumer](../../tests/integration/consumers/datasets/public_data.py)
qualifies the integrated data boundary; it is not an alpha or execution workload.

Observed external evidence is retained locally under ignored `logs/mr01/`:

| Boundary | Observed evidence | Limit |
| --- | --- | --- |
| Both public reference endpoints | Exact OKX instrument and Bitfinex exchange-pair/configuration responses | Current observations only; no authenticated historical specification history |
| Both public historical-trade adapters | Maintained 2026-09-23 12:00:00–12:00:10 UTC job; five responses and 46,266 raw bytes; `public-backfill/acquisition.json` | Scoped endpoint responses, not an exhaustive venue tape or original availability |
| Both recent-trade polling adapters | Configured 45-second wall interval; eight responses and 71,116 raw bytes; `public-poll/acquisition.json` | Sampled REST observations; polling gaps/completeness remain unknown |
| OKX native L2 capture | 189 frames, one snapshot, 187 updates, 800 visible levels; no observed gaps; saved replay parity | 20-second `books` sample, 400 levels/side; no full-depth or fill-fidelity claim |
| Bitfinex native R0 capture | 1,104 frames, one snapshot, 1,099 updates, 50 visible orders; no observed gaps; saved replay parity | 20-second `len=25` sample; no event timestamp or matching-engine completeness claim |
| Integrated source reopening | `integrated-public-data-wheel/` publishes/reopens public trades, both books and venue specifications as four named inputs; 328 selected trades, 388 replayed observations and 60 repeated observations | Final wheel installed outside the checkout; book admission selects at most 1,000 raw positions and preserves unselected-prefix limits |

Raw capture IDs and response digests remain in their original manifests; no
historical hashes were rewritten. Failed editable invocation and the subsequent
non-editable command are retained separately. Live source bytes need no repeat
download when only reference validation, query projection or documentation changes;
final readers must re-decode and verify those retained bytes. These local-only
records are not distributed with Git; the commands and reference consumer reproduce
the workflow with new observations, not the same market sample.

Software evidence covers lost publication acknowledgement, pending-byte recovery,
backwards receipt/durable-clock rejection without invented timestamps,
malformed responses, changed resume configuration, source corruption, duplicate and
late versions, independent exact amounts, reference corrections/freshness, scoped
book exclusion, incompatible capabilities, configuration-only onboarding and an
isolated installed CLI/assembly/replay consumer. The complete local `make check`
gate covers source/style/typing/native contracts, ownership, dependencies/security,
unit/integration tests and an isolated wheel installation. The final command is:

```sh
TMPDIR=/private/tmp PYTEST_ADDOPTS='--basetemp=/private/tmp/ar-mr01-check' \
  make check > logs/mr01/make-check-final.log 2>&1
```

`make-check-final.log` retains the final results and installed-wheel location;
`wheel-sha256.txt` pins the copied wheel under `logs/mr01/wheels/`.
`integrated-public-data-wheel-command.log` records the final wheel's reopening of
the retained venue inputs. The earlier full gate remains in `make-check.log`;
its 1,272 passing tests preceded the final clock-regression test. Earlier focused
results and source attempts are retained, not replaced by the final run. The
existing QuantLib source-to-wheel restriction still blocks artifact release
outside its admitted development use; resolving it belongs to MR06.

Current source limitations are explicit acceptance boundaries, not empirical or
operating qualification. Current metadata cannot establish earlier tick/lot rules;
Bitfinex's selected public response does not supply fixed tick/quantity increments,
so order-rule admission remains closed there. There is no Bitfinex book backfill,
historical receipt reconstruction, continuous trade WebSocket service or proven
complete tape in this support declaration. Continuous services/scale, richer
candidate/runtime admission, venue execution qualification and deployment remain
with their owning future MRs. No strategy, QR onboarding, production deployment,
data purchase, live order or capital activation is accepted or authorized here.

Reversal is an uncommitted patch review/revert. Existing snapshot/request families
remain readable; newly authored public snapshots require the new reader family.
Retain their exact raw bytes and matching acquisition implementation for resume.
Do not migrate a checkpoint by editing its identity.

### MR02 delivery and acceptance

Status: **complete for the declared research/decision SDK scope**, 2026-09-24.
Owner: quant development. This is current infrastructure MR02, not a historical
milestone or empirical QR deliverable. The working tree was clean before this
additive implementation; changes remain uncommitted for founder review.

Delivered through existing functional owners:

- Named trade/book/reference/non-book numeric inputs, explicit clock/units/freshness,
  causal source projection and independent missingness/lineage. Public OKX/Bitfinex
  trades and venue assertions reuse MR01 readers; L2 and visible-order imbalance
  preserve source-specific receipt/event semantics and controls.
- Versioned ordered multi-feature schemas, pure batch/incremental transitions,
  exact values, entity/version/availability/TTL contracts and instance-bound
  checkpoints. Projection, stateful expanding means and a fresh nonlinear feature
  execute through the same feature session.
- Independent arbitrary outcomes and verified temporal sample alignment;
  train-only fitted transforms with explicit changed output signatures, generic
  estimator adapters and immutable reload
  state. Exact centering, nonlinear nearest-example inference and an external
  estimator exercise more than fixed return/linear schemas.
- Typed target-position, currency-exposure, limit-order and two-sided quote intents;
  feature/prediction signature admission and isolated stateful policies. Rule-only,
  learned and stateful reference consumers run through typed/serialized
  `DecisionRun`, `applications.explore.run_decisions` and `inspect_decisions`.
  Existing attempts retain completed/failed research traces and fitted bytes.
- Fresh feature/label/estimator/quote implementations in a copied installed
  consumer, with independent exact expectations and fresh-process continuation.
  Future perturbations preserve earlier outputs; changed signatures/units, corrupt
  state, foreign instances and unsupported product/calendar/capability combinations
  fail explicitly. Separate instruments retain independent state.

The [feature guide](../../src/research/features/README.md#generalized-feature-lifecycle),
[model guide](../../src/research/models/README.md#generalized-estimator-lifecycle),
[observation guide](../../src/research/observations/README.md) and
[strategy guide](../../src/strategies/README.md) own interfaces, runnable examples,
semantics and reversal. The
[fresh installed consumer](../../tests/integration/consumers/research/decision_extensions.py)
and [saved-source consumer](../../tests/integration/consumers/research/decision_sources.py)
are maintained acceptance workloads, not research recommendations.

Dependency ownership stays bounded. MR03 owns the application-composition and
local retained-result slice pulled forward for these consumers; its generalized
formal studies, execution/cost models, search, metrics/charts and reports remain
open. MR05 owns the research capability-declaration/admission slice, while its full
registry, candidate manifests and runtime loading remain open. MR16 owns the
public API/typing/OOP compliance slice; broader migration remains open. MR04
consumes the new feature version/entity/availability contract but still owns its
Feast extension, online/offline services, materialization and operational recovery.
Existing Feast/lakeFS/ClearML/search/analytical integrations are retained; none
is replaced or declared generalized merely by this delivery.

Evidence is retained in ignored `logs/mr02/`. The repository's previous `logs/`
directory disappeared during an interruption. Original MR01 samples and earlier
MR02 logs are consequently unavailable at their recorded paths. With explicit
founder authorization, MR02 evidence was recreated using fresh public samples;
these new observations do not reconstruct the historical MR01 acceptance record.
`validation-context.json` records that distinction and the installed artifact.

| Boundary | Evidence and limit |
| --- | --- |
| Exact and causal contracts | `focused-final.log`: 26 focused tests passed, including the installed fresh extension and public-data consumers. Independent means, nonlinear predictions, warm-up, TTL, late corrections, future perturbation, state integrity, changed transform width/units, horizon-specific label identity and restart are software evidence. |
| Retained external source bytes | `public-acquisition/`, `okx-capture/`, `bitfinex-capture/` and their logs retain fresh public responses and two bounded 100-message book captures. `source-publication/` pins publications and selections through the existing MR01 workflow: 241 selected trades, original local receipt clocks and replay continuation. `installed-sources/` and `installed-sources.log` retain completed wheel-based decisions for both venues, with all three selected numeric fields nonmissing. This establishes source consumption, not complete-tape or venue execution qualification. |
| Fresh installed extensions | `installed-extensions/` and `installed-extensions.log`: a copied feature/label/estimator/quote consumer uses the isolated wheel outside the checkout; exact forecasts 7/9, first bid/ask 106/108 and fresh-process restart agree. Actual fitted bytes, config, traces and attempts are retained. |
| Source-order regression | An earlier real-source run exposed distinct trades sharing event/knowledge timestamps. Its original failed-attempt bytes were lost with the logs; they are not reconstructed. The corrected projection uses retained native position for ties, with a dedicated independent regression in the focused suite and successful fresh-source consumers. |
| Full local validation | `make-check-final.log` retains the complete final gate, including static/native contracts, dependencies/security, all non-performance tests and clean wheel installation. `component-links.log` explicitly covers changed guides outside the default docs scan. Earlier observed full passes are not substituted for this retained final proof. |
| Environment and access diagnostics | An earlier collection failure followed overlapping uv commands changing the shared environment mode; its original log is unavailable. Final checks use one isolated task environment sequentially, with no disabled requirement. `public-acquisition.log` preserves a sandbox DNS failure followed by the successful authorized network retry. |

```sh
UV_PROJECT_ENVIRONMENT=/private/tmp/ar02-env TMPDIR=/private/tmp \
  PYTEST_ADDOPTS='--basetemp=/private/tmp/ar02-check' \
  make check > logs/mr02/make-check-final.log 2>&1
```

The exact built wheel and SHA-256 are retained under `logs/mr02/wheels/`;
`wheel-sha256.txt` pins artifact bytes. Temporary environments are disposable.
The repository's existing QuantLib source-to-wheel restriction still blocks release
use; this development/CI acceptance does not resolve MR06 deployment admission.

Support is the declared research SDK and retained OKX/Bitfinex spot projections.
Non-book and other-calendar/product fixtures establish interfaces or explicit
refusal, not qualification of another live asset class. Custom components are
trusted supplied code with versioned identities; retain their exact implementation
alongside source data, configuration, state and the matching wheel. Digests are
not artifact authentication. Research processing times and synthetic reference
observations are labeled assumptions, not latency or market-fidelity measurements.

MR02 does not deliver generalized economic reports, passive-fill fidelity,
provisioned feature serving, paper/shadow deployment, execution/account controls,
capacity qualification or trusted candidate promotion. These remain with their
owning MRs, as do G1's full installed foundation acceptance and G2–G5. No empirical
strategy, QR onboarding, production deployment, data purchase, live order or capital
activation is accepted or authorized here.

Reversal removes these additive APIs and consumers together. Existing return,
linear, scheduled, saved-book and integration schemas remain readable. Preserve
new vector/checkpoint/model bytes with their matching implementation; older wheels
do not read the new schemas. Do not hand-edit checkpoint bindings to migrate state.

### Runtime, operations and handoff

| MR | Planned delivered behavior and sufficient completion evidence | Dependencies |
| --- | --- | --- |
| MR05 | **[Candidate packaging and runtime binding](../architecture/platform-design.md#candidate-promotion-contract).** Package rule-only and learned reference candidates with input/feature-store/state/metric contracts and target or order/quote outputs; load the same components into replay and runtime. Resolve a typed capability registry for market data, reference data, calendars, valuation, account and execution interfaces; reject unsupported product/channel/order/freshness combinations before startup. Bind dataset → experiment → candidate → deployment identities without granting authority. | MR02–MR03; integrate MR04 serving interfaces and MR11 conformance when available |
| MR06 | **[Independent deployable packages and trusted installation](../governance/workflow.md#build-a-release).** Build, verify, install and roll back pinned artifacts/configuration/state on the declared target; reject provenance, dependency, signature and compatibility failures. Prove that collector/execution applications install without unrelated research, notebook, training or reporting dependencies; shared contracts and independently locked workers retain compatible versions and release cadences. Resolve current release restrictions and verify research/shadow credentials cannot submit production orders. | Existing build/admission and MR16 package contracts; MR04 local environment profile supplies the target; MR06 does not wait for full MR04 or MR16 completion |
| MR07 | **[Paper/shadow runtime and OMS](../architecture/platform-design.md#oms-and-venue-adapter-design).** Supervise candidates with lifecycle callbacks, timers, market/account/order events and checkpointed instance state. Bind live inputs/features and a durable order-intent journal; support target and order/quote decisions, partial fills, rejects, cancel/replace, unknown outcomes and restart. Keep request acknowledgement separate from accepted order state and confirmed cancellation. Stable client IDs, deduplication and one fenced execution owner prevent duplicate effects; reconcile an uncertain submission before retry. Same-component replay/live-input paper and shadow runs suppress executable submission. | MR05 and applicable MR04 serving; MR06 before deployment; base independent spot controls remain active throughout |
| MR08 | **[Independent risk and account reconciliation](../architecture/platform-design.md#multi-strategy-netting-and-isolated-risk).** Enforce authorized instruments and instance/account/firm limits with atomic pending/uncertain exposure reservations, price/size/freshness checks and independent protection. Reconcile orders, fills, positions, currency cash, fees/rebates and transfers; duplicate events do not double-book. Unknown sends, stale state and breaks preserve exposure and trigger a defined safe response. Exercise shared-budget admission before portfolio netting, then integrate physical venue reconciliation through MR11. | MR07 and existing risk/accounting; base paper acceptance precedes MR11 external evidence |
| MR09 | **[Portfolio and shared-account infrastructure](../architecture/platform-design.md#multi-strategy-netting-and-isolated-risk).** Deliver allocation/target and order-intent coordination, account budgets, conflict/self-trade prevention, strategy-tagged child orders/fills/costs and shared-account recovery. Establish tagged-order attribution first, then qualify compatible netting and deterministic allocation of fills, residuals and costs as part of this same required outcome. Two distinct active strategies share an instrument/account and reconcile independently and in aggregate; either can stop without accidentally canceling the other's orders or bypassing account protection. | MR08; full allocation/netting remains required before onboarding, even without QR strategies |
| MR10 | **[Operational qualification](../architecture/platform-design.md#monitoring-recovery-and-operational-evidence).** Deliver runbooks and commands for startup, stop, restart, reconciliation, backup/restore and rollback. Reference paper workloads pass the applicable [failure scenarios](#decisive-acceptance-scenarios), retaining state, alerts and recovery outcomes. Keep paper results distinct from later MR11 private-stream/venue evidence; final operational acceptance incorporates MR11–MR14 results. | Applicable MR04 services and MR05–MR08 for dedicated-account drills; MR09 for shared-account drills; complete alongside MR11–MR14 rather than blocking their development |
| MR11 | **[OKX and Bitfinex execution/account adapters](../architecture/platform-design.md#oms-and-venue-adapter-design).** Implement both venues' declared spot operations, capability profiles, authentication, throttles, durable client IDs, private-stream recovery and reconciliation. Qualify one complete venue path first, then the second through the same strategy/OMS/risk contracts. Retain per-venue authorized test-environment conformance; fixtures supplement unavailable external proof. The first venue never closes this two-venue outcome. | MR07–MR08 contracts; MR06 before deployment; required venue access; integrate MR09 attribution |
| MR12 | **[Monitoring, metrics, charts and alerts](../architecture/platform-design.md#monitoring-recovery-and-operational-evidence).** Provide versioned event/metric APIs, queries, retained dashboards, configurable panels/thresholds, alert routing and default data/runtime/risk/account views. Register a custom research metric/chart and delayed-label diagnostic without modifying collectors or runtime; test telemetry loss independently of hard controls. | MR03 report contracts; MR08–MR11 runtime signals; basic telemetry ships earlier with each capability |
| MR13 | **[Activation and recovery machinery](../governance/workflow.md#activate-and-operate).** Implement disabled-by-default deployment manifests and separate authorization envelopes, scoped limits, fencing and recovery. Provide distinct block-new-exposure, cancel and reduce-position operations with defined stale-data, disconnected and illiquid behavior. Reject absent/expired authority and incompatible code/model/schema/state; prove safe restart and rollback without undoing or duplicating external fills. Completion does not require or grant live capital use. | MR06, MR10 paper drills and MR11–MR12; feed results back into final MR10 acceptance |
| MR14 | **[Multiple-instance integration](../architecture/platform-design.md#multi-strategy-netting-and-isolated-risk).** Run different reference components and instruments with isolated/shared-account configurations through paper/shadow; add an instance through configuration, then stop/restart it without losing attribution or weakening other accounts' controls. | MR09, MR12–MR13; actual live use remains separately authorized |
| MR15 | **[Research and runtime capacity qualification](../architecture/platform-design.md#scaling-triggers-and-technology-choices).** Define numeric launch budgets early, covering multi-day data, multiple instruments, concurrent studies/trials, replay, feature-store materialization/retrieval, live ingestion and dashboard queries. Record volumes, retention, throughput, p50/p95/p99 latency, memory/disk, concurrency, hardware/cache conditions and recovery targets before measurement. Remove demonstration-size limits where they prevent the workload; preserve causal/numerical parity. Retain research acceptance separately from final integrated runtime acceptance and deploy the topology needed to meet both. | Budgets start with MR01/MR04; MR01–MR04 for research acceptance; MR07/MR12/MR14 for final runtime acceptance; no QR bottleneck required |
| MR16 | **[Python ownership and enforcement](../coding_standards/README.md#python-scope-and-migration).** Complete the retained ownership/enforcement work with supported imports, packaging, checks and migration guidance; verify the APIs consumed by the reference workflows. | Existing engineering rules; can proceed alongside other work |
| MR17 | **[QR onboarding acceptance](#qr-onboarding-acceptance).** Exercise the installed integrated stack from a clean environment with fresh research extensions and the published onboarding guide. Close every in-scope platform gap before declaring it ready for QR. | All planned rows above, retaining valid earlier evidence |

The research path is MR01 → MR02 → MR03 → MR05. MR04's local development profile can
start alongside it and supplies MR06's installation target; MR06 does not wait
for MR04's deployed-service acceptance. MR04's deployed services then use the
verified installation path. MR06 precedes every deployment.

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
| D06 — Book reconstruction and data quality | MR01/MR07 |
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

Only after every MR01–MR16 outcome and MR17/G5 integrated acceptance does QR begin
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
