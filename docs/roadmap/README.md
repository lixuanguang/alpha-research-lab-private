# Platform infrastructure roadmap

Owner: repository founder. Status updated 2026-09-23.

This page is the active roadmap. It describes the current platform, the closed
delivery capabilities, and the remaining MR10–MR21 work. The detailed delivery
record for MRs 1–9A remains in the [preserved historical roadmap](history-mr1-to-mr9a.md),
including its original evidence identities, commands, limitations and section
anchors. It is an evidence record, not an active backlog.

The [QR implementation guide](../../examples/README.md) explains how researchers
use the available capabilities. The [research program](research-program.md) owns
methodology and experimental choices. The [platform design](../architecture/platform-design.md)
owns shared contracts.

## Current platform

The supported research path is configured acquisition or capture → retained raw
inputs → validation and versioned publication → explicit snapshot queries/replay
→ EDA, model studies or configured bounded spot economics → retained costed
reports.

| Available capability | Researcher benefit | Current limit |
| --- | --- | --- |
| Instrument identity, calendars and exact financial units | Shared identifiers, clocks and numerical conventions | These foundations do not constitute a strategy ledger or execution engine |
| Bounded acquisition and native capture | Retained source bytes, request identities and explicit failure/recovery behavior | Supported sources and products only; source-specific limits remain visible |
| Dataset publication, revisions, eligibility and point-in-time queries | Reopen a verified snapshot and inspect what was knowable | Empirical historical eligibility, coverage and revision availability remain unresolved for the frozen P1 sample |
| Book reconstruction, publication and replay | Inspect visible books and matching saved state | Exploratory degraded scope; no queue-position or executable-fill claim |
| Retained experiment attempts and temporal splits | Reproduce semantic inputs and enforce declared fit/holdout boundaries | Local single-writer store; large-study orchestration remains planned |
| Versioned features and separate forward labels | Inspect exact returns, causal windows, missingness and delayed outcomes | Bounded unfitted trade-price diagnostic; no runtime or empirical alpha claim |
| Saved OKX L2 IOC backtesting | Run saved-book EDA, isolated rules, depth fills and exact cash/position/P&L accounting | Constant research delays; unknown source receipt/continuity; no-impact visible-size model |
| Exact trade-price spot economics and configured reports | Reconcile target execution, costs, cash and holdings with retained output | Synthetic/offline spot scope; no liquidity, empirical or execution qualification |
| Research comparisons and offline feature parity | Reproduce bounded diagnostics through installed research APIs | Local synthetic scope; diagnostics confer no promotion authority |
| Pinned selections and maintained notebooks | Discover saved inputs with identities, units and missingness | Exploratory assembly; shared large-study orchestration remains planned |

The [data command reference](../../src/market_data/README.md) owns current
invocations. The [saved-baseline acceptance](../research/saved-baseline-acceptance.md)
owns the accepted OKX simulation scope. The [frozen P1 experiment](../research/p1-baseline.md)
retains its own source sample and economic assumptions; it remains deferred and
unaccepted. No empirical strategy, paper deployment or live trading acceptance
is implied by the current platform.

## Platform and researcher responsibilities

| Boundary | Quant researcher owns | Platform infrastructure owns |
| --- | --- | --- |
| Data | Required universe, fields, horizon, quality and source/use requirements | Adapters, provenance, revisions, publication, discovery and causal assembly |
| Features and labels | Hypothesis, formula, target, windows and missingness policy | Reusable execution, alignment, lineage and applicable state handling |
| Models and rules | Estimator/rule, comparison space, metrics and selection choices | Temporal splits, fit/inference lifecycle, complete attempts and reproducible artifacts |
| Backtesting | Signal-to-target policy and declared economic assumptions | Shared runner, independent risk, simulated fills, exact accounting and reporting |
| Promotion | Frozen candidate and accepted research evidence | Compatibility checks, artifact loading, runtime binding and qualification |
| Operation | Investigate attributed behavior and propose a new candidate | Execution, reconciliation, monitoring, recovery and separate activation controls |

A supported feature, estimator or rule plugs into an existing interface without
modifying shared runners. A new source/schema or execution mechanic needs its
missing platform capability first. Add interfaces with concrete consumers; do not
build an empty feature catalog, registry service or generic plugin framework.

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

The following capabilities are closed and available in the current platform. The
historical record preserves the full acceptance narrative and all original
evidence references.

| MR | Closed capability | Current meaning |
| --- | --- | --- |
| 1 | [Research dataset access and source onboarding](history-mr1-to-mr9a.md#research-dataset-access-and-source-onboarding) | Bounded discovery, publication, selection and source contracts |
| 2 | [Experiment attempts and temporal splits](history-mr1-to-mr9a.md#experiment-attempts-and-temporal-splits) | Retained attempts and declared temporal boundaries |
| 3 | [Versioned features and labels](history-mr1-to-mr9a.md#versioned-features-and-labels) | Causal observed-price features and separate forward labels |
| 4 | [Model records and evaluation](history-mr1-to-mr9a.md#fitted-preprocessing-and-model-evaluation) | Applicable fitted preprocessing, evaluation and model records |
| 5 | [First economic backtest](history-mr1-to-mr9a.md#first-economic-backtest) | Bounded exact spot economics and vectorbt comparison |
| 6 | [Configured runs and durable reports](history-mr1-to-mr9a.md#configured-runs-and-durable-reports) | Repeatable reports, local serial pipelines and pinned inputs |
| 7 | [Research comparison and extension](history-mr1-to-mr9a.md#research-comparison-and-extension) | Bounded comparisons, diagnostics and applicable Feast retrieval |
| 8 | [Saved-data baseline acceptance](history-mr1-to-mr9a.md#saved-data-baseline-acceptance) | Accepted saved OKX simulation scope; P1 remains deferred |
| 9 | [Runtime feature parity](history-mr1-to-mr9a.md#runtime-feature-parity) | Closed within saved-input batch parity scope |
| 9A | [L2 order-book backtesting](history-mr1-to-mr9a.md#l2-order-book-backtesting) | Saved OKX ETH-USDT EDA and IOC backtesting |

### Runtime feature parity

The closed MR9 capability remains bounded saved-input batch parity. Its original
contract, evidence and current qualification limits are preserved in the
[historical MR9 record](history-mr1-to-mr9a.md#runtime-feature-parity).

### L2 order-book backtesting

See the [closed MR9A record](history-mr1-to-mr9a.md#l2-order-book-backtesting).

The exact MR10–MR21 acceptance contracts are maintained in the [active future
contract record](future-mr10-to-mr21.md). The sections below provide the active
navigation summary; the contract record remains authoritative for acceptance
detail and limitations.

The [post-MR9A maintenance review](post-mr9a-maintenance-review.md) records the
separate cleanup state and remains the owning combined summary for that review.

## Delivery order and dependencies

MR10 can package an order-book candidate using closed MR9A capability. Conditional
work stays dormant until its consumer exists. MR11 must move forward before any
deployment, including a collector. MR21 can proceed independently. New work keeps
the applicable source, timing, accounting, recovery and operational limits explicit.

| MR | Active delivery outcome | Prerequisites |
| --- | --- | --- |
| 10 | [Candidate packaging and runtime binding](future-mr10-to-mr21.md#candidate-packaging-and-runtime-binding) | MRs 6–7 and accepted candidate evidence; MR9A for order-book strategies |
| 11 | [Trusted deployment artifact](future-mr10-to-mr21.md#trusted-deployment-artifact) | Dependency admission and a concrete deployable consumer |
| 12 | [Paper order lifecycle and recovery](future-mr10-to-mr21.md#paper-order-lifecycle-and-recovery) | MR10; MR11 before deployment |
| 13 | [Independent risk and account reconciliation](future-mr10-to-mr21.md#independent-risk-and-account-reconciliation) | MRs 5 and 12 |
| 14 | [Shared account allocation](future-mr10-to-mr21.md#shared-account-allocation) | MR13; only before multiple instances share an account |
| 15 | [Operations and paper qualification](future-mr10-to-mr21.md#operations-and-paper-qualification) | MRs 10–13; MR14 when sharing an account |
| 16 | [Executable venue adapter](future-mr10-to-mr21.md#executable-venue-adapter) | Order, risk and reconciliation contracts from MRs 12–13 |
| 17 | [Live monitoring and controls](future-mr10-to-mr21.md#live-monitoring-and-controls) | MRs 15–16 |
| 18 | [Bounded activation and recovery](future-mr10-to-mr21.md#bounded-activation-and-recovery) | MRs 11 and 15–17; explicit operating authorization |
| 19 | [Additional compatible live instance](future-mr10-to-mr21.md#additional-compatible-live-instance) | MR18; MR14 when sharing an account |
| 20 | [Measured storage and computation growth](future-mr10-to-mr21.md#measured-storage-and-computation-growth) | A representative workload exceeding an accepted budget |
| 21 | [Python ownership and enforcement](future-mr10-to-mr21.md#python-ownership-and-enforcement) | Existing engineering rules and tooling/tests |

The exact MR10–MR21 acceptance contracts are canonical in the [active future
contract record](future-mr10-to-mr21.md). Keep that record beside this navigation
page so the active roadmap stays readable while preserving the original
acceptance wording and limits.

## Historical navigation stubs

These compact headings preserve the old `README.md#...` destinations for external
references. Each points to the retained closed record or the active contract
record; no historical acceptance is duplicated here.

### Selected research integrations

See the [closed integration record](history-mr1-to-mr9a.md#selected-research-integrations).

### Research infrastructure

See the [closed research-infrastructure record](history-mr1-to-mr9a.md#research-infrastructure).

### Research dataset access and source onboarding

See [MR1's closed record](history-mr1-to-mr9a.md#research-dataset-access-and-source-onboarding).

### Experiment attempts and temporal splits

See [MR2's closed record](history-mr1-to-mr9a.md#experiment-attempts-and-temporal-splits).

### Versioned features and labels

See [MR3's closed record](history-mr1-to-mr9a.md#versioned-features-and-labels).

### Fitted preprocessing and model evaluation

See [MR4's closed record](history-mr1-to-mr9a.md#fitted-preprocessing-and-model-evaluation).

### Economic research

See the [closed economic-research record](history-mr1-to-mr9a.md#economic-research).

### First economic backtest

See [MR5's closed record](history-mr1-to-mr9a.md#first-economic-backtest).

### Configured runs and durable reports

See [MR6's closed record](history-mr1-to-mr9a.md#configured-runs-and-durable-reports).

### Research comparison and extension

See [MR7's closed record](history-mr1-to-mr9a.md#research-comparison-and-extension).

#### Diagnostic tool requirement amendment

See the [closed diagnostic-tool record](history-mr1-to-mr9a.md#diagnostic-tool-requirement-amendment).

#### Completion attempt and acceptance reconciliation

See the [closed completion record](history-mr1-to-mr9a.md#completion-attempt-and-acceptance-reconciliation).

#### Offline diagnostic completion and final reconciliation

See the [closed offline diagnostic record](history-mr1-to-mr9a.md#offline-diagnostic-completion-and-final-reconciliation).

### Frozen baseline acceptance

See [MR8's closed record](history-mr1-to-mr9a.md#frozen-baseline-acceptance).

### Saved-data baseline acceptance

See the [closed saved-data scope](history-mr1-to-mr9a.md#saved-data-baseline-acceptance).

### Frozen baseline continuation

See the [closed continuation record](history-mr1-to-mr9a.md#frozen-baseline-continuation).

### Strict provider evidence continuation

See the [closed provider-evidence record](history-mr1-to-mr9a.md#strict-provider-evidence-continuation).

### Candidate promotion and operation

See the [active promotion contract](future-mr10-to-mr21.md#candidate-packaging-and-runtime-binding).

### Candidate packaging and runtime binding

See [MR10's active contract](future-mr10-to-mr21.md#candidate-packaging-and-runtime-binding).

### Trusted deployment artifact

See [MR11's active contract](future-mr10-to-mr21.md#trusted-deployment-artifact).

### Paper order lifecycle and recovery

See [MR12's active contract](future-mr10-to-mr21.md#paper-order-lifecycle-and-recovery).

### Independent risk and account reconciliation

See [MR13's active contract](future-mr10-to-mr21.md#independent-risk-and-account-reconciliation).

### Shared account allocation

See [MR14's active contract](future-mr10-to-mr21.md#shared-account-allocation).

### Operations and paper qualification

See [MR15's active contract](future-mr10-to-mr21.md#operations-and-paper-qualification).

### Executable venue adapter

See [MR16's active contract](future-mr10-to-mr21.md#executable-venue-adapter).

### Live monitoring and controls

See [MR17's active contract](future-mr10-to-mr21.md#live-monitoring-and-controls).

### Bounded activation and recovery

See [MR18's active contract](future-mr10-to-mr21.md#bounded-activation-and-recovery).

### Additional compatible live instance

See [MR19's active contract](future-mr10-to-mr21.md#additional-compatible-live-instance).

### Measured storage and computation growth

See [MR20's active contract](future-mr10-to-mr21.md#measured-storage-and-computation-growth).

### Python ownership and enforcement

See [MR21's active contract](future-mr10-to-mr21.md#python-ownership-and-enforcement).

### Further scope needs a consumer

See the [active scope contract](future-mr10-to-mr21.md#further-scope-needs-a-consumer).

### Maintenance and growth

See the [active maintenance contracts](future-mr10-to-mr21.md#measured-storage-and-computation-growth).

### Prerequisite state: 59 passed.

This historical validation label is retained in the [closed MR9 record](history-mr1-to-mr9a.md).

### Final changed-domain state: 20 passed.

This historical validation label is retained in the [closed MR9 record](history-mr1-to-mr9a.md).

## Execution and maintenance

For each MR, select one observable consumer outcome, its dependencies and the
smallest sufficient proof. Follow the [engineering guide](../coding_standards/README.md)
and [development workflow](../governance/workflow.md). Keep definitions separate
from selections, shared inputs immutable and mutable state per instance.
Unsupported capabilities and invalid configuration fail explicitly.

Acceptance records identify source/artifact, environment, configuration, inputs,
attempt, command, result and limitations. Reuse unaffected evidence and renew the
proof changed by code, data, configuration, dependency or artifact changes.
Retain failed attempts; a new success does not rewrite measured reliability.

The former detailed roadmap remains available at
[history-mr1-to-mr9a.md](history-mr1-to-mr9a.md). Its original MR headings retain
the historical anchors used by evidence records. New active work should update
this page and the owning component/research records without adding a permanent
roadmap file or notebook for each completed MR.
