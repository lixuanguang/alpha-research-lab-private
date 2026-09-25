# Platform infrastructure roadmap

Owner: repository founder; quant development owns infrastructure delivery.
Status updated 2026-09-25. Delivery policy: complete the initial infrastructure
stack before quant researcher (QR) onboarding.

This page owns delivery status, remaining work and dependencies. The completed
MR09A saved-book baseline retains its historical identity. The remaining work
uses MR01–MR17, with MR07A/MR07B extending the completed MR07 increment without
renumbering later milestones. MR01 is complete for its declared read-only data/reference
scope; MR02 is complete for its declared research/decision SDK scope; MR03 is
complete for its bounded offline study/backtest/report scope; MR04 is complete
for its declared local feature-store, workspace and job-service scope. MR05 is
complete for candidate packaging and local intent-only runtime binding. MR06 is
complete for [independent operating packages and trusted local installation](#mr06-delivery-and-acceptance);
MR07 is complete for [local dedicated-account paper/shadow operation](#mr07-delivery-and-acceptance).
[MR07A](#mr07a-common-bbo-and-incremental-l3-aggregates) is complete for its declared per-book scope.
[MR07B](#mr07b-book-registry-and-consolidated-bbo) and MR08–MR17 remain planned.
The [MR05 record](#mr05-delivery-and-acceptance) states its evidence
and operating boundaries. The [MR04 record](#mr04-delivery-and-acceptance) states its service
evidence and later runtime/deployment boundaries. The [MR03 record](#mr03-delivery-and-acceptance) and
[MR02 record](#mr02-delivery-and-acceptance) state their evidence
and the later integration boundaries. The [MR01 record](#mr01-delivery-and-acceptance)
states its bounded support and evidence.
Component guides own implemented behavior. Historical delivery records remain
in Git history; P1 stays deferred and unaccepted.

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
workspace/job services; shared-account trading and a deployed OMS remain open. Library registries
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
| MR04 | **[Feature store](../architecture/platform-design.md#feature-store-contract), reproducible workspace and job services — complete for the [declared local scope](#mr04-delivery-and-acceptance).** Provision versioned data/artifact/experiment stores and offline/online feature-store paths, with causal historical retrieval, incremental materialization, entity/schema/version validation, freshness/TTL and missingness, idempotent retry, restart and rollback. Extend the isolated Feast integration and pinned lakeFS/ClearML paths while preserving independent compatible environments. Deliver scheduling/cancellation/retry, bounded concurrent workers, secrets references, backup/restore and service health. A clean workspace reopens studies and matched-cutoff features without manual repair or replacing an active worker; job failure cannot duplicate effects. | Start from existing local services and offline bridge; MR02 feature contracts and MR01 inputs; integrate MR03; qualify online consumption with MR05/MR07; MR06 before deployment |

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

### MR03 delivery and acceptance

Status: **complete for the declared bounded offline study/backtest/report scope**.
MR03 does not accept G2 or QR onboarding.

`applications.explore.evaluate_study` and `compare_studies` compose the existing
MR02 named-input feature, fitted-transform, estimator and policy interfaces with
exact accounting/risk, configurable execution/cost models and retained reports.
Typed values and strict serialized configurations select the same implementations;
external extension bytes join the installed distribution in run identity and
retained artifacts. The [study guide](../../src/research/studies/README.md#generalized-decision-studies)
owns the API, report readers, publication modes and reversal. The
[simulation guide](../../src/simulation/README.md#offline-decision-intent-studies)
owns execution assumptions and lifecycle support.

Walk-forward folds retain actual source/features/outcomes, resolved temporal
splits, fitting exclusions, fitted state, predictions, decisions and reconciled
ledgers. Source reads and label cutoffs protect a contiguous final holdout;
consumption survives failed access and changed-run retries are refused. Reports
carry exact versioned custom metrics/charts, predictive missingness, safe HTML/SVG
and typed manifest-verified readers. The existing Optuna journal retains failed,
rejected and pruned trials within the original budget. Local/deferred publication
separates computation from the existing recoverable ClearML outbox.

Dependency ownership remains explicit: MR07 owns the delivered **offline**
order-lifecycle prerequisite (entry/cancel/replace, expiry, partial IOC and declared
passive queue sensitivity); deployed OMS/reconciliation remains open. MR05's
capability admission and historical reference-resolution slices support offline
studies, while candidate/runtime binding remains open. MR12 owns the versioned
report metric/chart interface slice; runtime dashboards, telemetry and alerts
remain open. MR04's existing ClearML and Optuna integrations are reused without
claiming service provisioning, feature serving, jobs or recovery complete.
MR15 capacity budgets and MR17/G5 integrated handoff remain unaccepted.

Evidence is retained under ignored `logs/mr03/`; original retained MR02 capture
and publication bytes are reused without changing their provenance or universes.
`validation-context.json` binds the checkout, exact installed implementation,
wheel and consumer bytes. No new source availability observations are claimed.

| Boundary | Evidence and limit |
| --- | --- |
| Exact and causal contracts | `focused-final.log`: 25 focused tests passed. Independent expected losses/fees, partial fills, cancel/replace, quote rejection, queue sensitivities, historical reference changes, predictive missingness, report escaping and failed/pruned/rejected search cover software contracts. `source-cutoff-focused.log` additionally rejects a source that advances the requested cutoff; the offending bytes and failed attempt survive without a report. |
| Fresh installed components | `installed-studies-final.log` and `installed-studies-final/`: copied consumer runs with the clean wheel and `-I` outside the checkout. Fresh feature/transform/model/policy/metric/chart code reaches two walk-forward folds, typed/JSON config, exact losing/no-trade studies, passive queue sensitivity, retained fit exclusions, fresh-process readers, deferred search resume and failed holdout protection. Extension source bytes are retained, not replaced by defaults. |
| Retained actual sources | `captured-studies-final.log` and `captured-studies-final/`: the same installed workflow reopens MR02's original 100-message OKX/Bitfinex captures, trades and references. Each venue makes two costed fills; fees are exactly 0.01681253 USDT and 0.02 USD respectively. Native observations and receipt clocks remain retained. This is source consumption under explicit simulation assumptions, not observed exchange fills or complete historical coverage. |
| Actual publication recovery | `clearml/publication.log`: the existing verifier publishes one ordinary study and all three search attempts to the pinned local ClearML service, including a failed trial. It loses a local receipt after remote success, resumes in a fresh process and proves unique remote tasks, exact downloaded artifact bytes and unchanged attempt histories. Credentials and service state stay in ignored local evidence; the task's compose stack is stopped after verification. No production service is deployed. |
| Complete local gate | `make-check-final.log`: full `make check`, including all 1,305 non-performance tests, typing/native stubs, architecture/engineering/dependency/security checks and clean wheel installation. `component-links.log` also checks the changed guides outside the default docs scan. The final gate uses a short macOS pytest path and a dedicated environment. |
| Diagnostics and scope | `make-check-initial.log` retains the earlier full pass; it does not replace the final gate after the source-cutoff regression. `source-cutoff-stale-install.log` is explicitly a transcription of an initial stale installed-wheel failure, with the rebuilt-wheel pass retained separately. Initial focused/source logs are preserved without relabeling them as final acceptance. |

```sh
UV_PROJECT_ENVIRONMENT=/private/tmp/ar03-main-env TMPDIR=/private/tmp \
  PYTEST_ADDOPTS='--basetemp=/private/tmp/ar03-check' \
  make check > logs/mr03/make-check-final.log 2>&1

# Use the isolated wheel interpreter emitted by make check; copy consumers
# outside the checkout, then run from that directory with absolute evidence paths.
"$STUDY_PYTHON" -I decision_study.py "$REPO/logs/mr03/installed-studies-final"
"$STUDY_PYTHON" -I captured_study.py \
  --selection "$REPO/logs/mr02/source-publication/selection.json" \
  --snapshots "$REPO/logs/mr02/source-publication/snapshots" \
  --raw "$REPO/logs/mr02/public-acquisition/raw" \
  --captures "$REPO/logs/mr02" --output "$REPO/logs/mr03/captured-studies-final"
ALPHA_CLEARML_LOCAL_ENV="$REPO/logs/mr03/clearml/local.env" \
  "$STUDY_PYTHON" -I clearml_publication.py \
  "$REPO/logs/mr03/installed-studies-final/attempts"
```

The exact accepted wheel and dependency export are retained under `logs/mr03/`,
with SHA-256 fingerprints. Output directories must be new when reproducing these
consumers; retain earlier attempts instead of overwriting evidence. The local
service uses the existing [ClearML profile](../../configs/development/clearml/README.md).

Support remains cash-funded, single-account spot per fold, with up to 32 folds
and 1,024 decisions per schedule; search is a bounded 1–32-variant grid. Folds
have independent capital/state; initial/terminal marks are not an intraperiod
equity curve. Passive queue/latency assumptions are synthetic sensitivities.
Real captures use explicit receipt-as-matching clocks; Bitfinex L3 is aggregated
to visible depth without queue inference or invented trade prints. OKX resolves
then-known reference grids; Bitfinex uses explicitly authored 0.01 USD tick and
0.00001 BTC lot because the saved reference lacks those values. Bitfinex venue
grid/fill fidelity remains unqualified under MR11, not silently accepted by MR03.

Non-book inputs retain their own source family; neutral interfaces reject
unsupported products and dimensions. Supplied Python code remains trusted;
fingerprints are not authentication. Losing results are engineering acceptance,
not empirical strategy evidence. The existing QuantLib source-to-wheel admission
restriction still blocks release use under MR06. Feature services, shared-account
portfolio/execution, venue conformance, dashboards, capacity, MR17/G5 and production
readiness remain with their owners. No data purchase, live order or capital
activation is authorized by this delivery.

Reversal removes the additive study/intent/report APIs and their consumers together;
existing configured trade/book/model studies and saved schemas remain supported.
Keep new attempts and extension bytes with the matching wheel; older wheels do
not read the new schemas.

### MR04 delivery and acceptance

Status: **complete for the declared local feature-store, workspace and job-service
scope**, 2026-09-24.
Owner: quant development. This is infrastructure MR04; no QR research result,
production deployment or capital authority is implied. The initial working tree
was clean and this delivery remains uncommitted for review.

Delivered through the existing functional owners:

- `research.features` owns exact versioned multi-field history, definition/entity/
  fitted-signature validation, source and dataset revision identities, causal
  historical reads, explicit missing/partial/future/stale/expired outcomes, and
  atomic vector/checkpoint commits. Incremental state is isolated by definition,
  materializer instance and entity. Changed source or dataset pins require a new
  instance and replay; a stored correction never rewrites earlier knowledge.
- `applications.explore.materialize_features` resumes committed work, prepares a
  named immutable version, publishes and verifies the isolated Feast generation,
  then conditionally activates the pointer. A concurrent newer activation cannot
  be overwritten by a stale publisher. Explicit rollback retains both versions.
  The independent Feast 0.66 lock and core pandas 3 environment remain unchanged.
- `run_served_decision` consumes the same admitted feature definition through real
  Feast online retrieval and existing pure `DecisionSession` policies. It preserves
  feature origin clocks while recording the consuming decision time, and pauses
  without policy-state advance on missing/expired/service-loss results. This is
  the bounded MR05/MR07 online-consumer prerequisite; candidate packaging,
  supervised live-input paper/OMS and order submission are not completed by it.
- `runtime.JobQueue` and bounded workers retain delayed scheduling, cancellation,
  progress, capped retry, immutable outputs and crash recovery. Jobs pin installed
  implementation, configuration, input and compatible-environment identities;
  secrets remain references. `StudyJobHandler` uses MR03 study components, shared
  family holdout history and optional stable job keys. A completed study survives
  lost acknowledgement without recomputation or duplicate publication.
- Workspace backup/restore fences job workers and nested attempt writers, captures
  mutable SQLite stores consistently, preserves immutable Feast generation bytes,
  and restores verified files into a fresh destination. Existing lakeFS pinned
  inputs and ClearML experiment/artifact publication remain authoritative remote
  integrations; their service volumes must be backed up as well.

The [feature guide](../../src/research/features/README.md),
[runtime guide](../../src/runtime/README.md) and
[scheduled study guide](../../src/research/studies/README.md#scheduled-studies-and-reproducible-workspaces)
own supported APIs, producer quiescence, failure responses and recovery commands.
The installed [feature consumer](../../tests/integration/consumers/research/feature_workspace.py)
and extended [study consumer](../../tests/integration/consumers/research/decision_study.py)
are quant-development acceptance workloads. Their authored non-book signals and
spot quantities establish software behavior, not alpha or new venue qualification.
MR01's saved OKX/Bitfinex evidence remains valid: source adapters and their clocks
are unchanged. No new Binance/Tardis input or access is used.

Evidence is retained under ignored `logs/mr04/`. The separately locked real Feast
worker validates exact online values, missing/expired entities, late corrections,
retries, tamper rejection and relocation. The installed application workload also
checks stateful restart, two entities, rollback, online intents and service loss.
The extended study workload checks a lost acknowledgement after real completion,
one retained study across two job attempts, and clean queue/result restoration.
Local lakeFS/ClearML publication and stopped-volume restoration records qualify
the selected development services separately from fixtures:

| Boundary | Retained evidence | Result and limit |
| --- | --- | --- |
| Final local gate | `make-check-final.log` | 1,325 passed; one unselected real-Feast case skipped; three performance cases deselected; lint/format, strict typing/native stubs, ownership/docs, dependency/security checks and installed-wheel smoke passed |
| Real Feast SDK | `feast-serving-final.log` | Explicit separately locked worker test passed; exact rational online values, corrections, expiry, missingness, retry, relocation and tamper refusal |
| Installed feature workspace | `feature-workspace-final.log`, `feature-workspace-final/acceptance.json` | Two entities, exact offline/online parity, atomic incremental restart, retry, version rollback, intent-only serving and clean local restore |
| Installed study workspace | `study-workspace-final.log` | Fresh MR03 extensions remain executable; a lost completed-study acknowledgement produces two job attempts and one completed study; queue/history/results reopen after restore |
| Pinned lakeFS source/features | `lakefs-feature-version/feature-version.json`, `lakefs-features-reconciled.log`, `lakefs-after-restore.log` | Four exact named source/manifest/definition/history objects reopened from the same immutable commit, before and after actual service restore |
| ClearML experiment/artifact store | `clearml-publication-final.log`, `clearml-after-restore-fresh-cache.log` | Unique task/receipt recovery and exact remote artifacts, including fresh downloads after restore |
| Whole service recovery | `service-backups/manifest.json`, `service-backup-restore.log` | Five stopped lakeFS/ClearML volumes restored into separate projects under the same image pins and private credentials |

The final gate command is:

```sh
TMPDIR=/private/tmp PYTEST_ADDOPTS='--basetemp=/private/tmp/ar04-final-review' \
  make check > logs/mr04/make-check-final.log 2>&1
```

`wheel-sha256.txt` pins the retained final development wheel. The installed
acceptance interpreter was isolated from active workers; its owned runtime bytes
are compared with the retained wheel in `installed-runtime-parity.json`.
The initial virtual-environment symlink mistake, a relative credential-path
failure and a service-consumer tuple decoder error remain in their original logs.
The already-published ClearML attempts and lakeFS commit were reconciled after
those harness fixes; neither was relabelled as a fresh publication. The initial
installed runtime snapshot is retained separately, without rewriting old hashes.
Task-owned service containers are stopped after verification; backups and named
volumes remain as local-only evidence, not a portable shared-service deployment.

Scope and later ownership remain explicit. The supported topology is one trusted
local POSIX workspace, independently locked compatible Python environments and
loopback development services. It is not shared-host authentication, distributed
leases or arbitrary external exactly-once execution. Running study cancellation
is cooperative at a bounded computation boundary. Historical corrections require
an explicitly authored availability clock; source quality is not invented. MR06
still owns trusted deployable installation and the existing QuantLib source-to-wheel
release restriction. MR05/MR07 retain complete candidate/runtime/OMS acceptance;
MR15 owns launch capacity and latency budgets. G2–G5, QR onboarding, deployment,
live orders and capital activation are not accepted by this record.

Reversal preserves all retained stores and selects the prior feature generation
or prior compatible installed workspace. Restore to a new destination; do not
replace an active worker environment or edit a checkpoint to change its identity.

### MR05 delivery and acceptance

Status: **complete for candidate packaging and local intent-only runtime binding**,
2026-09-24. Owner: quant development. This is the current infrastructure MR05;
it does not accept a QR strategy, deploy a service or activate trading.

Delivered through existing functional owners:

- `research.experiments.CandidateBundle` retains immutable rule-only and learned
  manifests and verified content objects. The resolved dataset selection, completed
  MR03 experiment/attempt, exact report, feature schema, chosen fold's fitted bytes,
  component implementation/parameter identities, and candidate remain linked.
  Changed or unrelated components cannot borrow another report's acceptance.
- `configuration.CapabilityRegistry` resolves all six capability families through
  explicit environment selections. Product, venue, calendar, mode, named channel,
  depth, clock, field units, freshness, lifecycle and order operations fail closed.
  Requirements remain distinct from fixture/read-only/external qualification.
- `runtime.CandidateLoader` recreates the registered feature, policy, optional
  transform/model and metric/chart definitions. Replay and runtime use identical
  candidate bytes without implicit refitting, dynamic import or built-in fallback.
  `CandidateDeployment` links placement to the candidate and its resolved input,
  instance, universe and profile identities without adding executable authority.
- `applications.explore.run_candidate` and `runtime.CandidateFeatureFeed` provide the
  public source and offline/online feature paths. Exact fitted-state availability,
  signatures, warm-up, cadence and combined feature/policy checkpoints preserve
  causal state. Invalid transitions cannot partially commit. Stale, missing,
  changed-version or unavailable online features pause with unchanged state.

The [candidate guide](../../src/research/experiments/README.md#candidate-bundles)
and [runtime guide](../../src/runtime/README.md#candidate-loading-and-intent-evaluation)
own supported interfaces and failure behavior. The installed reference consumer
authors a fresh feature, transform, estimator, order/target policies, metric and
chart through those interfaces. Both candidates originate in completed costed
MR03 studies; their outputs and fitted provenance remain engineering evidence.

Acceptance commands and retained evidence live in ignored `logs/mr05/`:

| Boundary | Evidence and result |
| --- | --- |
| Candidate integrity and provenance | `bundle-focused.log`: completed-attempt/result linkage, exact selected artifacts, substitution/corruption, unsafe paths, qualification and idempotent publication |
| Typed admission | Focused registry tests cover all six families, incompatible signatures/modes, unknown selections and explicit OKX/Bitfinex clock distinctions |
| Atomic state and failure semantics | `runtime-focused.log`: policy/order failure rollback, cadence, warm-up, gap reset/pause, restart isolation, corrupt checkpoint and real SQLite freshness/missing/expiry boundaries |
| Installed fresh extensions | `candidate-focused-final.log`, `candidate-installed-source.log`: rule-order and learned-target studies/bundles; replay/runtime/source/offline parity; five pre-read rejection scenarios per candidate; exact fresh-process restart |
| Actual feature-store adapter | `candidate-feast.log`, `candidate-installed-feast.log`: same bundles through isolated Feast 0.66.0; source/offline/online parity and stale/service-loss/version-change pauses |
| Final local gate | `make-check.log` retains the complete `make check`, including isolated wheel installation. `final-installed-source.log` and `final-installed-feast.log` renew candidate proofs against that wheel; `final-source/` and `final-feast/` retain the actual bundles, attempts, deployments, traces and summaries |

Reproduce the focused installed workflow and complete gate from the repository:

```sh
ALPHA_FEAST_WORKER_PYTHON=/absolute/pinned-feast-worker/bin/python \
  uv run --frozen --no-editable pytest -q -m integration \
  --basetemp=/private/tmp/mr05-accept \
  tests/integration/test_candidate_workflow.py

PYTEST_ADDOPTS=--basetemp=/private/tmp/mr05-check \
  ALPHA_FEAST_WORKER_PYTHON=/absolute/pinned-feast-worker/bin/python \
  make check > logs/mr05/make-check.log 2>&1
```

The final outside-checkout consumer uses the clean wheel-smoke interpreter with
`-I`, copied `candidate_workflow.py` and `decision_study.py`, an absolute output
directory, and optional final argument `feast`. Its worker executes the installed
`applications.explore.command` bytes in the independently locked environment.
No production service or private venue API is used. Existing MR01 source and
MR04 service/restore evidence remains valid because their protocols and stores
are unchanged; new candidate consumption is qualified separately above.

Dependency ownership remains explicit. MR07 owns the delivered intent-evaluation,
atomic checkpoint and serving-pause prerequisite slice; supervision, live inputs,
durable order journal, OMS, risk reservation and reconciliation were still open
at MR05 acceptance. Their dedicated-account increment is recorded under MR07 below.
MR12 owns the carried metric/chart definitions, while runtime dashboards and
alert delivery remain open. MR13 owns the placement-identity slice; its independent
activation envelope, limits and recovery controls remain open. No entire later
milestone, G3–G5 or formal QR onboarding is accepted by this work.

The accepted economic scope remains bounded spot `DecisionStudy` candidates with
named market/reference/non-book inputs. Registry contracts preserve generalized
products and sources, but unimplemented economics reject explicitly. The OKX and
Bitfinex read-only profiles preserve their distinct clocks/representations;
neither is private execution conformance. Actual MR11 venue adapters and evidence
can be registered when available. At MR05 acceptance, runtime modes only emitted
intents; MR07 below adds modeled paper order/account effects while preserving
suppressed executable submission. Component
digests are integrity checks, not MR06 trusted installation. Exact environment
matching is currently required; independent deployable graphs, trusted compatibility,
and the existing QuantLib release restriction remain MR06. Feature generations
are pinned; selecting another version requires an explicit new binding. No
capacity, empirical alpha, live-input fidelity or deployment readiness is claimed.

Reversal removes the new candidate workflows, records and factory exports together;
retain matching wheels/bundles/checkpoints for reproduction. Existing study,
source, feature-store and job record schemas are unchanged. Older runtimes reject
the new candidate schemas and must not silently reinterpret their state.

### MR06 delivery and acceptance

Status: **complete for independent operating packages and trusted local
installation**, 2026-09-24.
Owner: quant development. This is current infrastructure MR06, not a historical
milestone or QR research deliverable. The initial working tree was clean. All
changes remain uncommitted for founder review.

The delivery follows the existing MR04 trusted local POSIX development profile:
Darwin arm64, standard-GIL CPython 3.14.7, local retained registry and clean
operating virtual environments. It adds shared-contract, collector and execution
distributions with independent collector/execution locks. Exact financial values
are separate from the optional QuantLib convention adapter. The complete research
environment and independently locked Feast/ClearML workers remain supported.

The existing administrative artifact command now composes actual build,
Ed25519 signing, trusted-origin/builder verification, offline installation and
compatible rollback. Signed releases bind source bytes/base commit/dirty state,
build commands, root and selected locks, admission policy, fresh complete audit,
wheel inventory, configuration and state. Installation rejects unsafe archives,
unknown/missing records, signature/source/dependency mismatches, expiry and
incompatible targets/schemas. Quiescence, immutable installation slots, an atomic
active pointer and preserved current state define local recovery.

The execution package consumes typed spot limit intents, scoped credential
references, the capability registry and existing exact reference/risk checks.
Research, paper and shadow modes suppress submission; production-mode requests
and credential/environment mismatches fail before any submission. This is an
executable reference application for the package boundary, not the later durable
OMS or venue-adapter acceptance. The collector retains existing public capture
and saved replay interfaces for the declared OKX/Bitfinex spot scope.

Dependency ownership remains bounded. MR16 owns the package/import-contract slice;
its broader ownership migration remains open. MR07 owns the intent-admission
reference application's execution slice; supervised events and durable OMS were
open at MR06 acceptance and are now addressed under MR07. MR13 owns
credential/mode separation and compatible-state refusal pulled
forward here; bounded activation, venue reconciliation and operational recovery
remain open. MR11 still owns both venues' private account/execution conformance.
MR04 owns workspace/data/feature/job restore; installation does not redefine those
schemas or rewind external order/fill state.

The [release workflow](../governance/workflow.md#build-a-release),
[dependency guide](../architecture/dependency-admission.md#first-deployment-dependency-decision)
and [operating runbook](../governance/operations.md#trusted-local-installation)
own interfaces, commands and limitations. Acceptance artifacts and logs are
retained under ignored `logs/mr06/`. Actual release builds used the pinned tools
and fresh pip-audit reports covering all 179 admitted external dependencies;
each reported no known vulnerabilities. The retained signed registry contains:

| Artifact | Signed release SHA-256 | Installed closure |
| --- | --- | --- |
| Execution, initial shadow configuration | `c6d92722f352928aeecdf9e48e6f9b657d9702c37f9cbdc06a01b6ba19a62527` | 8 distributions, including shared contracts |
| Execution, changed quantity limit | `1fae2b481550d3ef5912f0ad0920b4a645a2ea6b5d49a65105f54771ae92e67d` | Same pinned code/closure, separately signed configuration |
| Collector | `3563efb023e0bd0c86e31ebc199ef2d7ea469efd2db9d4b586ac3a6c10dc5266` | 14 distributions, including shared contracts |

The [maintained installation consumer](../../tests/integration/consumers/deployment/trusted_installation.py)
runs with the installed governance interpreter outside the checkout. It installs
the two real execution releases, checks actual isolated distribution metadata,
suppresses admitted intents, rejects production requests, and restores the prior
configuration while preserving current mutable state. The upgrade changes the
maximum quantity from 0.001 to 0.002; it is a configuration upgrade with unchanged
code, not a claim of a new application version or schema migration.

The installed collector's `replay` command reopens the retained MR02 native
100-message OKX BTC-USDT and Bitfinex tBTCUSD captures. Both finish synchronized
with no gaps in the saved prefix; terminal quality remains unavailable because
the finite recordings ended. `collector-okx-replay.json` and
`collector-bitfinex-replay.json` retain their book/trace identities. This reuses
the original public observations and renews installed decoder/package evidence;
it does not assert fresh acquisition, historical completeness or private venue
execution conformance. `collector-installed.json` records exact distribution and
runtime identities. Neither operating environment exposes unrelated research,
notebook, training or reporting modules, including QuantLib.

`trusted-installation-reviewed.json` records the completed configuration-change
consumer against the installed final governance artifact. It includes signed
configuration/request hashes, rejected → suppressed → rejected admission for the
larger intent, production-request refusal, and the unchanged mutable-state digest.
`actual-provenance-refusals.json` records real correctly signed invalid bundles:
source/wheel mismatch, selected-lock drift, omitted audit coverage and wrong
configuration mode. Each passes authentication and fails the installed semantic
verifier. Focused engineering tests additionally exercise entrypoint/RECORD and
dependency mismatch, unsafe files, stale/revoked trust, target/schema refusal,
fencing, staged failure, interrupted initial installation and local byte drift.

The full local gate passes, including strict typing/native stubs, ownership and
documentation checks, dependency/advisory admission, security/secret scans,
installed tests and the complete research-wheel smoke test. The independently
locked Feast 0.66.0/pandas 2.3.3 worker is also selected for the final gate; its
candidate/serving cases exercise compatibility with the pandas 3.0.5 core without
resolving either environment into the other. The final command and log are:

```sh
UV_PROJECT_ENVIRONMENT=/private/tmp/ar06-env TMPDIR=/private/tmp \
  ALPHA_FEAST_WORKER_PYTHON=/private/tmp/ar06-feast/bin/python \
  PYTEST_ADDOPTS='--basetemp=/private/tmp/ar06-check' \
  make check > logs/mr06/make-check-final.log 2>&1
```

`operating-source-parity.log` confirms every local file in the retained operating
wheels matches final source. Full-research import corrections are renewed by the
full wheel gate. The task's test signing identity is local acceptance evidence;
its retained public policy expires and is not production key provisioning.

The research graph's QuantLib source-to-wheel binding remains unverified and its
release block/2026-10-04 allowance deadline remain in force. Only genuinely
independent operating closures can be admitted. Linux, remote deployment,
production key provisioning, live orders, capital activation, empirical strategy
acceptance and QR onboarding are not qualified by this local delivery.

Reversal is patch review/revert plus selection of a previously verified compatible
release. Retain the current mutable state, all registry bytes and independent
worker environments. Never edit a signed manifest, dependency digest or checkpoint
to make an incompatible artifact appear acceptable.

### Runtime, operations and handoff

| MR | Planned delivered behavior and sufficient completion evidence | Dependencies |
| --- | --- | --- |
| MR05 | **[Candidate packaging and runtime binding](../architecture/platform-design.md#candidate-promotion-contract) — complete for the [declared local scope](#mr05-delivery-and-acceptance).** Package rule-only and learned reference candidates with input/feature-store/state/metric contracts and target or order/quote outputs; load the same components into replay and runtime. Resolve a typed capability registry for market data, reference data, calendars, valuation, account and execution interfaces; reject unsupported product/channel/order/freshness combinations before startup. Bind dataset → experiment → candidate → deployment identities without granting authority. | MR02–MR03; integrate MR04 serving interfaces and MR11 conformance when available |
| MR06 | **[Independent deployable packages and trusted installation](../governance/workflow.md#build-a-release) — complete for the [declared local scope](#mr06-delivery-and-acceptance).** Build, verify, install and roll back pinned artifacts/configuration/state on the declared target; reject provenance, dependency, signature and compatibility failures. Prove that collector/execution applications install without unrelated research, notebook, training or reporting dependencies; shared contracts and independently locked workers retain compatible versions and release cadences. Resolve current release restrictions and verify research/shadow credentials cannot submit production orders. | Existing build/admission and MR16 package contracts; MR04 local environment profile supplies the target; MR06 does not wait for full MR04 or MR16 completion |
| MR07 | **[Paper/shadow runtime and OMS](../architecture/platform-design.md#oms-and-venue-adapter-design) — complete for the [declared local scope](#mr07-delivery-and-acceptance).** Supervise candidates with lifecycle callbacks, timers, market/account/order events and checkpointed instance state. Bind live inputs/features and a durable order-intent journal; support target and order/quote decisions, partial fills, rejects, cancel/replace, unknown outcomes and restart. Keep request acknowledgement separate from accepted order state and confirmed cancellation. Stable client IDs, deduplication and one fenced execution owner prevent duplicate effects; reconcile an uncertain submission before retry. Same-component replay/live-input paper and shadow runs suppress executable submission. | MR05 and applicable MR04 serving; MR06 before deployment; base independent spot controls remain active throughout |
| MR07A | **[Common BBO and incremental L3 aggregates](#mr07a-common-bbo-and-incremental-l3-aggregates) — complete for the declared per-book scope.** Expose one typed per-book quote contract for native L2/L3, maintain exact L3 quantities/counts by side and price during lifecycle updates, and integrate existing research and paper consumers. Preserve native identity, clocks, quality and recovery; verify against independent full aggregation. | Completed MR01–MR07 contracts and consumers; preserve MR06 package boundaries |
| MR07B | **[Book registry and consolidated BBO](#mr07b-book-registry-and-consolidated-bbo) — planned.** Own independent books by venue/instrument and expose per-venue and consolidated BBO queries over explicitly equivalent instruments. Scan cached eligible venue quotes with causal cutoffs, freshness, provenance, ties and partial-coverage semantics. | MR07A; existing reference/capability admission and MR07 paper/replay interfaces |
| MR08 | **[Independent risk and account reconciliation](../architecture/platform-design.md#multi-strategy-netting-and-isolated-risk).** Enforce authorized instruments and instance/account/firm limits with atomic pending/uncertain exposure reservations, price/size/freshness checks and independent protection. Reconcile orders, fills, positions, currency cash, fees/rebates and transfers; duplicate events do not double-book. Unknown sends, stale state and breaks preserve exposure and trigger a defined safe response. Exercise shared-budget admission before portfolio netting, then integrate physical venue reconciliation through MR11. | MR07 and existing risk/accounting; base paper acceptance precedes MR11 external evidence |
| MR09 | **[Portfolio and shared-account infrastructure](../architecture/platform-design.md#multi-strategy-netting-and-isolated-risk).** Deliver allocation/target and order-intent coordination, account budgets, conflict/self-trade prevention, strategy-tagged child orders/fills/costs and shared-account recovery. Establish tagged-order attribution first, then qualify compatible netting and deterministic allocation of fills, residuals and costs as part of this same required outcome. Two distinct active strategies share an instrument/account and reconcile independently and in aggregate; either can stop without accidentally canceling the other's orders or bypassing account protection. | MR08; full allocation/netting remains required before onboarding, even without QR strategies |
| MR10 | **[Operational qualification](../architecture/platform-design.md#monitoring-recovery-and-operational-evidence).** Deliver runbooks and commands for startup, stop, restart, reconciliation, backup/restore and rollback. Reference paper workloads pass the applicable [failure scenarios](#decisive-acceptance-scenarios), retaining state, alerts and recovery outcomes. Keep paper results distinct from later MR11 private-stream/venue evidence; final operational acceptance incorporates MR11–MR14 results. | Applicable MR04 services and MR05–MR08 for dedicated-account drills; MR09 for shared-account drills; complete alongside MR11–MR14 rather than blocking their development |
| MR11 | **[OKX and Bitfinex execution/account adapters](../architecture/platform-design.md#oms-and-venue-adapter-design).** Implement both venues' declared spot operations, capability profiles, authentication, throttles, durable client IDs, private-stream recovery and reconciliation. Qualify one complete venue path first, then the second through the same strategy/OMS/risk contracts. Retain per-venue authorized test-environment conformance; fixtures supplement unavailable external proof. The first venue never closes this two-venue outcome. | MR07–MR08 contracts; MR06 before deployment; required venue access; integrate MR09 attribution |
| MR12 | **[Monitoring, metrics, charts and alerts](../architecture/platform-design.md#monitoring-recovery-and-operational-evidence).** Provide versioned event/metric APIs, queries, retained dashboards, configurable panels/thresholds, alert routing and default data/runtime/risk/account views. Register a custom research metric/chart and delayed-label diagnostic without modifying collectors or runtime; test telemetry loss independently of hard controls. | MR03 report contracts; MR08–MR11 runtime signals; basic telemetry ships earlier with each capability |
| MR13 | **[Activation and recovery machinery](../governance/workflow.md#activate-and-operate).** Implement disabled-by-default deployment manifests and separate authorization envelopes, scoped limits, fencing and recovery. Provide distinct block-new-exposure, cancel and reduce-position operations with defined stale-data, disconnected and illiquid behavior. Reject absent/expired authority and incompatible code/model/schema/state; prove safe restart and rollback without undoing or duplicating external fills. Completion does not require or grant live capital use. | MR06, MR10 paper drills and MR11–MR12; feed results back into final MR10 acceptance |
| MR14 | **[Multiple-instance integration](../architecture/platform-design.md#multi-strategy-netting-and-isolated-risk).** Run different reference components and instruments with isolated/shared-account configurations through paper/shadow; add an instance through configuration, then stop/restart it without losing attribution or weakening other accounts' controls. | MR09, MR12–MR13; actual live use remains separately authorized |
| MR15 | **[Research and runtime capacity qualification](../architecture/platform-design.md#scaling-triggers-and-technology-choices).** Define numeric launch budgets early, covering multi-day data, multiple instruments, concurrent studies/trials, replay, feature-store materialization/retrieval, live ingestion, book reconstruction, quote consolidation and dashboard queries. Record volumes, retention, throughput, p50/p95/p99 latency, memory/disk, concurrency, hardware/cache conditions and recovery targets before measurement. Remove demonstration-size limits where they prevent the workload; preserve causal/numerical parity. Retain research acceptance separately from final integrated runtime acceptance and deploy the topology needed to meet both. | Budgets start with MR01/MR04; MR01–MR04 for research acceptance; MR07/MR07A/MR07B/MR12/MR14 for final runtime acceptance; no QR bottleneck required |
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

Status: **complete for local dedicated-account paper/shadow operation**, accepted
2026-09-25. Owner: quant development. The acceptance envelope is
local paper/shadow, one cash-funded spot instrument and instance per dedicated
account. The initial native inputs remain OKX `books` L2 and Bitfinex `R0` L3.
Generalized candidate, named-source, feature and target/order/quote contracts are
preserved; unsupported product economics still fail admission.

Delivered behavior:

- `runtime.PaperCandidateRuntime` supervises the existing candidate feature/model/
  policy components with start/recovery, market, timer, order, account, stop and
  fault events. Candidate state, decision inputs/results and order admission are
  committed together. Durable event cursors replay the then-current account
  balance without delivering a later fill early. Stale input, serving loss,
  changed versions, unknown orders and account breaks suppress new decisions.
- `execution.PaperOrderJournal` owns stable child IDs, exact portable order records,
  SQLite transactions, one POSIX-fenced owner and persisted epochs. Request
  acknowledgment, accepted state, cancel acknowledgment and confirmed terminal
  outcomes remain distinct. Duplicate retries reopen saved results; conflicting
  bytes fail. Partial fills post exactly once. Unknown outcomes preserve
  reservations and require explicit reconciliation before retry. Replacement
  requires the old order to be terminal and retains its lineage.
- `PaperMatcher` consumes finite displayed bid/ask liquidity shared by orders,
  later-than-decision market events, resting post-only admission, IOC residual
  cancellation and exact fees. Paper fills are modeled observations; shadow never
  matches. Neither path has an executable submit interface.
- `applications.paper.run_paper` composes source or `CandidateFeatureFeed` with
  these same owners. `run_live_paper` injects native transport/book adapters into
  the reusable neutral collector and supervises a real UTC scheduler alongside it.
  The callback occurs after durable capture/reconstruction. Original receipt and
  actual local delivery clocks are both retained, allowing saved-live replay
  without inventing earlier availability. A fresh recording starts with a fresh
  synchronized book while candidate/order state survives process restart.
- The independent `alpha-execute paper` application accepts durable steps,
  normalized events, modeled markets, cancellation, confirmed replacement and
  inspection without importing research, simulation, training, notebooks or
  QuantLib. Candidate supervision remains in the complete research distribution.

Owning contracts and usage are in the [runtime guide](../../src/runtime/README.md#paper-candidate-supervision),
[execution guide](../../src/execution/README.md), [paper application](../../src/applications/paper/README.md),
[execute command](../../src/applications/execute/README.md) and
[test guide](../../tests/README.md#paper-and-live-input-acceptance).

Acceptance evidence is retained under ignored `logs/mr07/`:

| Boundary | Evidence and outcome |
| --- | --- |
| OMS lifecycle and independent limits | `independent-execution-pytest-final.log`: 21 focused execution/risk cases, including uncertain outcomes, partial fill/fee reservations, cancel/fill races, terminal contradiction, atomic quotes and replacement |
| Candidate clocks and hard controls | `runtime-focused.log`: 11 candidate/runtime cases, including paper/shadow parity, restored callbacks, stale quotes, clock regression, account break and a faulting callback unable to undo an independent block |
| Interrupted matching and independent stop | `runtime-final.log`: 13 runtime cases after review fixes, including completing a claimed quote before advancing the recovery clock, no duplicate fill/account callback, and preserving operator stop across both failed and successful reconciliation |
| Installed candidate and real serving | `installed-candidates-rerun.log`: both installed integration tests pass; `installed-candidates-source/` and `installed-candidates-feast/` retain actual candidate bundles, studies, paper traces and summaries. Rule-order and learned-target candidates preserve intent/feature parity and independently expected exact fill/fee/cash values; real Feast service loss and version change pause the OMS |
| Independent execution installation | `independent-execution-claim/README.md`: final admitted eight-wheel closure, clean offline install/pip check, all 58 owned source files matched, outside-checkout CLI partial fill, shadow refusal, confirmed replacement and restart parity; changed quote bytes rejected after interrupted matching while exact retry preserves liquidity/effects. Its focused execution/runtime run passes 28 cases |
| Independent collector installation | `collector-boundary/`: admitted 14-wheel closure with 16 edges, fresh offline installation/pip check, outside-checkout recovery consumer and `alpha-collect replay`; source parity and absence of research/simulation/execution verified |
| Earlier partial-fill installed proof | `independent-execution/`: retained original artifact demonstrates partial quantity 1 of 2, cash 899.90, holding 1, remaining reservation 100.90, duplicate/restart parity and shadow fill refusal |
| Actual OKX public input | `live-okx/summary.json` and `live-okx.log`: 8-second `books` L2 recording, 74 frames, one snapshot, 72 updates, no gaps, raw replay parity; seven decided cutoffs/orders from eight timer ticks |
| Actual Bitfinex public input | `live-bitfinex/summary.json` and `live-bitfinex.log`: 8-second `R0` L3 recording, 250 frames, one snapshot, 246 updates, no gaps, raw replay parity; seven decided cutoffs/orders from eight timer ticks |
| Same-component saved-live replay and restart | Both native output trees retain paper/shadow replay journals: all original paper `StepRecord` bytes, orders and ledger equal; shadow status/features/intents equal and no fills; a fresh recording preserves source binding, reopens the account and retries the saved timer without duplicate effects |
| Source identity of live acceptance | `live-installed-source-parity.json`: all 272 installed runtime/source/resource files match current source; installed source identity `8a8c059e42807b7f5f25392a095fa3c4fc6d3d9413979b0b1e6932b6e8b3dce9` |
| Complete local gate | `make-check.log`: complete `make check`, 1,502 tests passed, three performance tests deselected, real Feast enabled, strict mypy/stubtest, lint/format, engineering/dependency/link checks, security/audit/secret scan and isolated wheel APIs/resources/OKX book command. Short pytest base `/private/tmp/mr07-check` avoids macOS socket path limits |

`final-wheel/` retains the final research wheel, locked runtime requirements,
smoke inputs/results and a 272-file source-parity manifest. Its wheel SHA-256 is
`106aec1bec9ef1f754100de2bba2eb0bd53e19154078e4fdbb00c9ca1745d415`.
`final-candidates-source/` and `final-candidates-feast/` preserve the installed
consumer outputs from the final complete gate. Earlier snapshots remain separate.

The native runs used the installed core interpreter with `-I` and the three
maintained consumer scripts copied outside the checkout to
`/private/tmp/mr07-live-consumer/`. Exact script copies and bounded configs remain
in `live-consumer/` and `live-configs/`. The command for each venue was:

```sh
/private/tmp/ar07-core/bin/python -I /private/tmp/mr07-live-consumer/live_paper.py \
  --config /absolute/repository/logs/mr07/live-configs/okx.json \
  --output /absolute/repository/logs/mr07/live-okx
```

Use `bitfinex` in the config/output paths for its run. Capture duration was eight
seconds with zero retries. Each run retained actual source timestamps, receipt,
delivery and cadence clocks; no clock was shifted to force availability. The
passive engineering reference bid did not fill in either live-input run.
The summary's `canonical_parity=false` means optional persisted canonical batch
publication was not selected; raw native replay and the complete saved-delivery
paper replay both passed. Modeled fill semantics are established separately by
the exact controlled matching and installed OMS proofs.

The complete local command used an isolated task environment, preserving active
worker environments:

```sh
UV_PROJECT_ENVIRONMENT=/private/tmp/ar07-gate TMPDIR=/private/tmp \
  ALPHA_FEAST_WORKER_PYTHON=/private/tmp/ar07-feast/bin/python \
  PYTEST_ADDOPTS=--basetemp=/private/tmp/mr07-check \
  make check > logs/mr07/make-check.log 2>&1
```

The initial gate's single failure was an installed recovery consumer still
patching the old collector module after extraction; its log is retained as
`make-check-before-recovery-fixes.log`. The mock now targets the functional owner,
and the installed recovery consumer plus complete gate pass. Review also added
regressions for immutable quote claims, interrupted matching recovery, equal-time
book delivery and preserving independent stops during reconciliation. Changed
operating wheels were rebuilt and requalified; old proof hashes remain intact.

The final independent execution wheel SHA-256 is
`fd05a2d8d489f1f642f10b10f795bdcc7eb36f5086a6dccd8ab5813ad043fc59`;
its contracts wheel is
`1e661e802fb2c4f6f86d6e0ed589de6a74f69c7ac0d3b8fd9505e6ee244c6194`.
The earlier partial-fill proof retains its original wheel hash rather than being
relabeled as a later artifact. These are installed software proofs, not a signed
production deployment. The complete research graph's existing QuantLib
source-to-wheel release restriction is unchanged.

Prerequisite ownership is explicit. MR08 owns the delivered dedicated-account
cash/inventory/fee reservation and local reconciliation slice. Account/firm
budgets across instances, transfers, rebates, correction posting and physical
venue reconciliation remain open. MR11 owns authenticated execution, private
streams, venue rules/throttles and external uncertainty resolution for **both**
venues. MR10 owns broader failure/recovery drills; MR12 owns alert/dashboard
integration; MR13 owns deployment authority and safe activation; MR09/MR14 own
shared accounts and multiple active instances. None is closed by this slice.

A fill contradicting an already confirmed terminal cancellation saves a durable
`late_terminal_fill` block and raises without rewriting the ledger. Local matching
of a paper snapshot cannot clear this contradiction; the owning correction and
physical reconciliation increment must resolve it. Paper touch matching models
neither queue position nor market impact. Declared authored grids/fees are not
current venue-rule qualification. Native observations prove the data-to-runtime
boundary only, and completed engineering studies are not empirical strategy
evidence. Capacity, production operation and MR17/G5 remain open; formal QR work
has not started.

Reversal is patch review/revert plus selection of a compatible retained wheel and
its exact candidate/configuration/journal. Keep captured input and OMS bytes.
Never edit checkpoint identities or erase fills to force an older artifact to
accept newer state. Local acceptance does not authorize deployment or live trading.

### MR07A common BBO and incremental L3 aggregates

Status: **complete for the declared per-book scope**, 2026-09-25. Owner: quant development. This extends
`market_data` book contracts and their existing research/paper consumers.
MR03 already projects complete L3 observations to aggregate depth, and MR07
derives touch prices/quantities for paper matching. This milestone makes those
semantics reusable and maintains L3 aggregates as orders change.

- Define a typed per-book BBO result with venue/instrument identity, exact
  bid/ask prices and quantities, original source/receipt/availability clocks,
  sequence/epoch and quality. Missing sides and unavailable or invalid state
  remain explicit; only complete accepted message boundaries are observable.
- Update aggregate quantity and order count by side/price on L3 add, amend,
  partial fill and delete. Preserve native order IDs and L2 absolute-size
  semantics. Snapshot replacement, gaps and recovery reset or invalidate the
  derived quote consistently; no queue priority is inferred.
- Integrate shared quote/depth behavior into existing research projections and
  live paper delivery. Keep historical native/canonical evidence readable and
  retain exact arithmetic, causal availability and independent package ownership.

Acceptance: compare incremental levels and BBO with independently recomputed
expected state across multiple orders at one price, side/price amendments,
partial fills, deletion of the best/last level, missing sides and snapshot/gap
recovery. Exercise the affected installed research/paper consumer boundaries and
saved-input replay parity. Reuse unaffected venue-protocol evidence; record any
schema/state migration with the delivered implementation. Container choice remains
an implementation decision; MR15 qualifies throughput, latency and memory.

Delivered behavior and compatibility:

- `VisibleBook` owns incremental exact quantity/count changes alongside native
  order IDs. L3 set/remove operations move contributions between side/price
  levels and delete the last level. OKX absolute-size L2 semantics are unchanged.
- `BookQuote` / `BookQuoteSide` are frozen typed per-book values.
  `BookProjection.quote` uses the incremental native cache; `BookDepth` supplies
  the same projection for old canonical observations. Source, receipt and
  explicitly supplied delivery clocks remain distinct. Unavailable, empty,
  one-sided, locked and crossed states are explicit.
- `CapturedStudyMarket`, live imbalance and `PaperCaptureObserver` consume shared
  depth/quote behavior. Live quote availability is the original market delivery
  time; controls cannot refresh it or bypass existing causal/freshness admission.
- Existing L3 canonical records remain order-only, and native fingerprints,
  capture schemas, request identities and paper journal envelopes are unchanged.
  The cache rebuilds from retained frames, so no stored-state migration is needed.
  Collector packaging retains its existing independent ownership; the portable
  execution package has no new market-data or research dependency.

The [market-data guide](../../src/market_data/README.md#shared-book-quotes) owns
API semantics and limitations; the [observation guide](../../src/research/observations/README.md)
and [paper guide](../../src/applications/paper/README.md) own consumers.
Evidence is retained under ignored `logs/mr07a/`:

| Boundary | Evidence and observed outcome |
| --- | --- |
| Exact lifecycle and failures | `tests/unit/data/test_book_quotes.py` compares every native L3 boundary with independent full aggregation, including low Decimal precision, same-price orders, side/price changes, best/last deletion, invalid partial snapshots, gaps and replacement epochs. Coinbase fixtures add exact partial/full fills; quote round-trip and malformed clock/side cases preserve explicit unknowns |
| Installed saved native replay | `saved-replay/result.json`: retained MR07 OKX and Bitfinex captures expose 73 and 247 accepted quote boundaries, with original final book/trace identities unchanged. Published 32-record prefixes retain query/replay parity, every completed checkpoint, and fresh-process restart |
| Installed costed research | `captured-study-final.log`: both retained MR02 sources complete two decisions/two fills. Expected fees remain 0.01681253 USDT for OKX and 0.02 USD for Bitfinex. The `receipt-as-matching-v1` assumption and source limitations remain explicit |
| Installed actual public paper input | `live-okx/summary.json`: 56 frames, one snapshot, 54 updates and seven decided timers. `live-bitfinex/summary.json`: 145 frames, one snapshot, 140 updates and five decided timers. Both eight-second captures have no observed gaps and raw replay parity |
| Saved delivery and paper recovery | Both live output trees retain exact paper step/order/ledger replay, equal shadow intents with zero fills, original delivery clocks and fresh-recording restart without duplicate effects. These engineering passive orders produced no live-input fills |
| Source correspondence | `installed-source-parity.json`: all 274 installed runtime/source/resource files match the source used for saved and live acceptance; source identity `c573acb45410efc863ceefc6efcd8c2dc470dc0f294a3fd019757039a6cab5df` |
| Independent collector installation | `collector-boundary/README.md`: admitted 14-wheel/16-edge closure, isolated offline install and pip check, all 156 local wheel members equal source and installed files, no research/simulation/execution packages. Installed quote and CLI replay preserve both venues' original book/trace identities. Final collector SHA-256 `a4a2daeffafbd8bc8820d9441fde957f968df4f1e5f3a00d3fa76bd8c4b450f0`; unchanged contracts wheel `1e661e802fb2c4f6f86d6e0ed589de6a74f69c7ac0d3b8fd9505e6ee244c6194` |

Two complete source/test lanes passed 1,507 tests each, but the final installed
wheel's outer book-workflow watchdog timed out at 60 seconds. The original logs
remain `make-check-before-wheel-timeout.log` and
`make-check-before-watchdog-fix.log`; the first wheel and produced reports remain
under `wheel-timeout/`. The same installed workflow passed independently in 3.064
seconds (`wheel-diagnosis.json`). An instrumented full layout
(`wheel-layout-trace.log`) showed the parent waiting for its nested CLI before a
successful completion. The outer and nested watchdogs both allowed 60 seconds,
leaving no startup/verification/shutdown allowance. The outer watchdog now uses
the existing installed-backtest integration's 120-second bound; the nested CLI's
60-second limit and all assertions remain unchanged. The corrected isolated
boundary passed (`wheel-layout-final.log`). These observations do not establish
a runtime latency budget; MR15 still owns that qualification.

The final complete gate passed: `make-check.log` records **1,507 passed, three
performance tests deselected, zero skips**, with the real pinned Feast worker,
strict typing/stubtest, governance/security/audit checks and isolated installed-wheel
smoke. `final-wheel/` retains the identical research wheel
(`668549d8a2d7b7fda155bbce23a2c2510c95ef0392b2b81e2167e871a5bad27f`),
requirements, smoke inputs/results and exact source/installed-member correspondence.
`final-candidates-source/` and `final-candidates-feast/` retain the final installed
candidate consumer outputs. The full command was:

```sh
UV_PROJECT_ENVIRONMENT=/private/tmp/ar07a-gate TMPDIR=/private/tmp \
  ALPHA_FEAST_WORKER_PYTHON=/private/tmp/ar07a-feast/bin/python \
  PYTEST_ADDOPTS=--basetemp=/private/tmp/ar07a-check-gate \
  make check > logs/mr07a/make-check.log 2>&1
```

The final roadmap status/evidence edit is editorial; its links were checked again
without rebuilding unchanged package bytes. `consumer-commands.json` retains
exact saved/live invocations, and `consumers/` retains the copied scripts.
Task-specific temporary environments are removed after retaining their evidence.

The source protocol and endpoint implementations are unchanged. Earlier venue
qualification is reused; these new public-input runs renew the changed
quote-to-paper boundary, not private execution fidelity. Coinbase remains
fixture-qualified and its external access limitation is unchanged. No source
availability or empirical strategy claim is inferred from simulated matching.

Commands used the installed research interpreter with `-I` and copied existing
consumers under `/private/tmp/ar07a-consumers`, running outside the checkout:

```sh
/absolute/core/bin/python -I /private/tmp/ar07a-consumers/parity_consumer.py \
  /absolute/repository/logs/mr07a/saved-replay \
  /absolute/retained-okx-capture /absolute/retained-bitfinex-capture
/absolute/core/bin/python -I /private/tmp/ar07a-consumers/live_paper.py \
  --config /absolute/repository/logs/mr07a/live-configs/okx.json \
  --output /absolute/repository/logs/mr07a/live-okx
```

Use `bitfinex` in the live config/output names for that venue. The initial saved
study check in `captured-study/` preceded the stale-observation compatibility
adjustment and is retained separately; `captured-study-final/` renews that proof.
No whole prerequisite milestone was closed: this slice uses completed MR01–MR07
contracts. MR07B consolidation, MR15 measured capacity, MR08+ operating outcomes
and MR17/G5 remain open. Reversal selects the prior compatible code and existing
retained raw/canonical/journal bytes; do not rewrite historical hashes or clocks.
Production deployment and live trading remain separately authorized work.

### MR07B book registry and consolidated BBO

Status: **planned**, added 2026-09-25. Owner: quant development. Depends on MR07A;
the initial integration remains read-only market data and paper/replay consumption.

- Maintain independent book state under `(venue, instrument)` keys, preserving
  source/channel provenance and selecting one admitted source per book. Expose
  per-venue BBO lookup and consolidated BBO lookup through the same public owner.
- Require an explicit reference mapping for economically comparable instruments,
  quote currencies and quantity units. BTC-USD and BTC-USDT remain distinct;
  implicit FX conversion is unsupported. Name the crypto result consolidated BBO.
- Begin with a scan of cached venue quotes. At each query cutoff, use only then
  available observations and apply declared freshness/quality eligibility.
  Expiry and disconnect invalidate eligibility even without a new price update;
  saved replay must never expose a later cached quote at an earlier cutoff.
- Return the highest eligible bid and lowest eligible ask, summed size and
  contributing venues at each tied best price, original quote clocks and
  excluded/missing venue reasons. Mark partial coverage, absent sides and
  consolidated locked/crossed states explicitly. Reference paper/replay consumers
  demonstrate the query contract while fills remain tied to the selected venue.

Acceptance: independent multi-venue cases cover key isolation, tied prices,
empty sides, stale/disconnected venues, resynchronization, currency/unit mismatch,
cutoff ordering and replay/restart parity. Reuse retained OKX/Bitfinex recordings
for their native input paths; synthetic comparable-quote cases establish
consolidation correctness without relabeling USD/USDT captures as one market.
Record selected versus eligible coverage. Execution routing, shared-account
allocation and FX conversion remain outside this milestone; MR15 measures the
registry and quote workload before requiring a more complex index.

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
