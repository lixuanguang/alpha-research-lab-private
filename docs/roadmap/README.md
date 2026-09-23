# Platform infrastructure roadmap

Owner: repository founder. Status updated 2026-09-23.

This page owns delivery status, remaining work and dependencies. MRs 1–9A are
complete within their documented limits; MR10–MR21 remain planned. Current
component guides own implemented behavior. Detailed milestone narratives remain
in Git history rather than the working documentation; P1 stays deferred and
unaccepted.

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

All entries below are **complete**. Links lead to their current owning guides
and retained acceptance records.

| MR | Closed capability | Current meaning |
| --- | --- | --- |
| 1 | [Research dataset access and source onboarding](../../src/market_data/README.md) | Bounded discovery, publication, selection and source contracts |
| 2 | [Experiment attempts and temporal splits](../../src/research/experiments/README.md) | Retained attempts and declared temporal boundaries |
| 3 | [Versioned features and labels](../../src/research/features/README.md) | Causal observed-price features and separate forward labels |
| 4 | [Model records and evaluation](../../src/research/studies/README.md#model-evaluations-and-clearml-publication) | Applicable fitted preprocessing, evaluation and model records |
| 5 | [First economic backtest](../../src/simulation/README.md) | Bounded exact spot economics and vectorbt comparison |
| 6 | [Configured runs and durable reports](../../src/research/studies/README.md#configured-economics-reports-and-serial-pipelines) | Repeatable reports, local serial pipelines and pinned inputs |
| 7 | [Research comparison and extension](../../src/research/studies/README.md#bounded-comparison-and-factor-diagnostics) | Bounded comparisons, diagnostics and applicable Feast retrieval |
| 8 | [Saved-data baseline acceptance](../research/saved-baseline-acceptance.md) | Accepted saved OKX simulation scope; P1 remains deferred |
| 9 | [Runtime feature parity](../../src/research/features/README.md) | Closed within saved-input batch parity scope |
| 9A | [L2 order-book backtesting](../research/l2-book-backtest.md) | Saved OKX ETH-USDT EDA and IOC backtesting |

## Delivery order and dependencies

MR10 can package an order-book candidate using closed MR9A capability. Conditional
work stays dormant until its consumer exists. MR11 must move forward before any
deployment, including a collector. MR21 can proceed independently. New work keeps
the applicable source, timing, accounting, recovery and operational limits explicit.

| MR | Planned delivery outcome | Prerequisites |
| --- | --- | --- |
| 10 | [Candidate packaging and runtime binding](../architecture/platform-design.md#candidate-promotion-contract) | MRs 6–7 and accepted candidate evidence; MR9A for order-book strategies |
| 11 | [Trusted deployment artifact](../governance/workflow.md#build-a-release) | Dependency admission and a concrete deployable consumer |
| 12 | [Paper order lifecycle and recovery](../architecture/platform-design.md#oms-and-venue-adapter-design) | MR10; MR11 before deployment |
| 13 | [Independent risk and account reconciliation](../architecture/platform-design.md#multi-strategy-netting-and-isolated-risk) | MRs 5 and 12 |
| 14 | [Shared account allocation](../architecture/platform-design.md#multi-strategy-netting-and-isolated-risk) | MR13; only before multiple instances share an account |
| 15 | [Operations and paper qualification](../architecture/platform-design.md#monitoring-recovery-and-operational-evidence) | MRs 10–13; MR14 when sharing an account |
| 16 | [Executable venue adapter](../architecture/platform-design.md#oms-and-venue-adapter-design) | Order, risk and reconciliation contracts from MRs 12–13 |
| 17 | [Live monitoring and controls](../governance/operations.md) | MRs 15–16 |
| 18 | [Bounded activation and recovery](../governance/workflow.md#activate-and-operate) | MRs 11 and 15–17; explicit operating authorization |
| 19 | [Additional compatible live instance](../architecture/platform-design.md#multi-strategy-netting-and-isolated-risk) | MR18; MR14 when sharing an account |
| 20 | [Measured storage and computation growth](../architecture/platform-design.md#scaling-triggers-and-technology-choices) | A representative workload exceeding an accepted budget |
| 21 | [Python ownership and enforcement](../coding_standards/README.md#python-scope-and-migration) | Existing engineering rules and tooling/tests |

## Execution and maintenance

For each planned MR, select one observable consumer outcome, its dependencies and
the smallest sufficient proof. Define detailed acceptance when that work starts;
keep this table as the backlog and update the owning component guide when complete.
Follow the [engineering guide](../coding_standards/README.md) and
[development workflow](../governance/workflow.md). Implementation, research
acceptance, artifact admission, deployment and trading activation remain separate.

The [completed maintenance record](post-mr9a-maintenance-review.md) retains the
post-MR9A cleanup results. New asset mechanics, scale work or organizational
controls need a concrete consumer; existing spot and saved-book evidence does not
qualify additional scope.
