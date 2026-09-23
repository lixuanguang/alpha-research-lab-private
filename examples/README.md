# Quant researcher implementation guide

Owner: repository founder. Updated 2026-09-23. This page is the short reader
entrypoint for the working research journeys under `examples/`. The
[platform roadmap](../docs/roadmap/README.md) owns capability delivery and
acceptance; the [research program](../docs/roadmap/research-program.md) owns
methodology. Execution, kernel repair, retention and source budgets belong in
the [notebook operations guide](notebook-operations.md).

The current working path is saved OKX L2 inspection/backtesting or a bounded
Bitfinex book capture and replay. Saved trade/book selections, EDA, retained
experiment attempts and temporal splits, observed-price feature/label studies,
exact model construction/evaluation, bounded synthetic spot economics and local
reports are implemented. Candidate packaging, paper/live operation and
production monitoring remain future work. The [legacy P1 reproduction
guide](../docs/research/legacy-p1-reproduction.md) preserves the deferred
Binance/Tardis source-evidence handoff; it is not part of the current journey.

These examples describe today's bounded capabilities. The
[pre-onboarding roadmap](../docs/roadmap/README.md#infrastructure-completion-before-qr-onboarding)
requires quant development to finish the initial OKX/Bitfinex spot stack using
its own reference workloads before handing it to QR. QR will supply research
formulas, strategies, backtest specifications, metrics and chart definitions
through the completed public APIs. QR is not responsible for filling gaps in
shared execution, data access, tracking, dashboards or recovery. The
[onboarding acceptance](../docs/roadmap/README.md#qr-onboarding-acceptance) remains
planned; the current notebooks are not evidence that it has passed.

## Start with your research question

Choose one maintained reader journey, then use the operations guide for setup
and retention details.

| Question | Entry point | What it establishes |
| --- | --- | --- |
| Inspect a saved order book and bounded spot economics | [OKX order-book notebook](orderbook-research.ipynb) and the [saved L2 workflow](../docs/research/l2-book-backtest.md) | Native replay, depth/imbalance EDA, IOC fills and exact cash/NAV accounting for the selected saved prefix |
| Walk through research from data to a retained study | [Offline QR notebook](research-foundations.ipynb) | Synthetic saved inputs, quality and missingness, observed-price features/labels, model reload and fixed-rule economics |
| Inspect a bounded current book capture | [Live QR notebook](research-foundations-live.ipynb) | Bitfinex R0 capture or explicit local replay; source access is skipped unless opted in |
| Diagnose installed consumers and recovery | [Offline diagnostics](infrastructure-diagnostics.ipynb) or [live diagnostics](infrastructure-diagnostics-live.ipynb) | Fresh-process identity, data publication, feature/model state, economic checkpoints and bounded collector health |
| Reopen deferred P1 source evidence | [Legacy P1 reproduction](../docs/research/legacy-p1-reproduction.md) | Historical Binance/Tardis records and unresolved eligibility, coverage and revision evidence |

The owning contracts are the [market-data command map](../src/market_data/README.md),
[experiment core](../src/research/experiments/README.md), [study/report
reference](../src/research/studies/README.md), [feature and label contracts](../src/research/features/README.md),
[model contract](../src/research/models/README.md) and [bounded simulation
contract](../src/simulation/README.md). This guide describes how they fit a
researcher's decision; it does not copy their schemas.

## Current journeys

### Saved OKX L2 research

The OKX notebook reads an explicitly retained archive and the versioned
`okx-eth-usdt-book-v1.json` configuration. It selects the saved prefix, computes
spread/depth/imbalance diagnostics, compares the configured rule with a no-trade
control, walks depth for IOC fills and reconciles cash, position, fees and NAV.
The complete command, recovery boundary, current bundle reader and historical
result are owned by the [saved L2 workflow](../docs/research/l2-book-backtest.md).

This is an engineering scenario over the selected saved messages. Original
receipt time, sequence continuity, full-day coverage, historical eligibility,
queue position, market impact and measured latency remain unknown. A matching
replay demonstrates byte/state reproducibility for the saved inputs; it does not
establish executable liquidity or profitability.

### Bounded Bitfinex capture and replay

The maintained QR live notebook defaults to a local-only skipped state. Set
`ALPHA_QR_CAPTURE=1` to opt into one bounded public capture, or set
`ALPHA_BITFINEX_CAPTURE_DIRECTORY` to reopen a completed recording without a
source call. The route resolves the checked-in Bitfinex configuration before
connecting, retains the raw journal and a bounded canonical prefix, and writes a
pinned selection that the offline reader can reopen. The [collector guide](../docs/data/l3-collectors.md)
owns source/session recovery and quality semantics.

The current route permits at most 20 seconds and 10,000 messages for the
configured R0 capture. It records receipt order and native prices/sizes; R0 has
no exchange timestamp, hidden orders, queue priority or executable fills. A
network, timeout, publication or quality failure remains a failed retained
attempt and never falls back to synthetic data.

### Offline QR study

With no selectors, the offline notebook uses small synthetic Binance-format
trades and a saved synthetic OKX book. Set
`ALPHA_RESEARCH_DATASET_DIRECTORY` only to an authored directory containing
`raw/`, `snapshots/` and `selection.json` when reopening a retained study. The
selection is verified by identity and bytes; missing or corrupt inputs fail, and
there is no latest-file or source fallback. The saved book input remains a
separate named input and is not silently converted into a trade feature or
backtest dataset.

The later price-study fixture has explicit availability, trailing/forward
definitions, train-only model state and fixed-rule economics. It is software
evidence for the declared synthetic inputs, not empirical alpha or a repair for
unknown archive availability. Keep the source, selection, attempt and report
identities together when a result affects a research decision.

## Research activities and journey

Use only the activities that apply to the question. A rule study can stop after
diagnostics, and a batch model need not have streaming feature machinery.

| Activity | Researcher supplies | Retain | Current owner |
| --- | --- | --- | --- |
| [Frame the question](#frame-a-research-question) | Mechanism, universe, horizon, comparator and stop conditions | Research note and evaluation boundaries | Research program; record manually |
| [Select and inspect data](#select-and-inspect-research-data) | Instruments, fields, clocks, cutoffs and quality needs | Pinned selection, source identities and limitations | `market_data` and `applications.explore` |
| [Onboard a missing input](#onboard-a-missing-source-or-dataset) | Source/data requirements, units, history and first consumer | Qualified dataset or an explicit implementation gap | Source adapters and publication owners |
| [Explore features and labels](#research-features-and-labels) | Formula, window, target, availability and missingness policy | Versioned definitions and diagnostics | `research.features` / `research.labels` |
| [Compare models or rules](#compare-models-or-deterministic-rules) | Temporal split, transforms, trainer/rule, metrics and selection rule | Attempts, fitted state, predictions and applicable errors | `research.experiments`, `research.models`, `research.studies` |
| [Build and backtest](#build-and-backtest-a-strategy) | Signal policy, execution assumptions and limits | Reconciled economic trace and report | `simulation` and `research.studies` |
| [Freeze and qualify](#freeze-and-qualify-a-candidate) | Candidate bundle and operating requirements | Qualification and authorized deployment identities | Planned |

### Frame a research question

State the mechanism, required observations, decision horizon and a simple
comparator. Write down what would make the result uninformative: missing
historical availability, inadequate coverage, unstable behavior or an execution
assumption the data cannot support. Choose the applicable methodology in the
[research program](../docs/roadmap/research-program.md#rules-for-every-workstream).

Before formal comparison, pin the sample and evaluation boundaries. Retain
failed, rejected and abandoned attempts that change the next choice. An ignored
notebook snapshot is a convenience; a decision record needs the research
program's trial fields and retrievable input/output references.

### Select and inspect research data

Start with the [data-source index](../docs/data_source/README.md) and the
[market-data command map](../src/market_data/README.md). Choose an explicit
offline or live journey above. Author a `ResearchSelection` with named trade or
book inputs, explicit snapshots, fields, windows and one knowledge cutoff. Save
the selection JSON and its identity beside the addressed raw/snapshot stores.

Inspect units, coverage, gaps, revisions, membership and source clocks before
calculating a result. Trade windows use business time; saved-book windows use
receipt time where supplied. Unknown availability remains unavailable at a
cutoff. Missing files fail the read, and the reference reader's byte ceilings
bound declared input materialization rather than total process RSS. The
[selection reference](../src/market_data/README.md#discover-and-reopen-research-selections)
owns the public records and retention boundary.

Finish with a statement of what the selected evidence can support. A successful
download or nonempty result does not prove historical coverage, membership or
causal eligibility.

### Onboard a missing source or dataset

Describe the missing source, product/data family, fields, units, cadence,
availability and revision behavior, access/retention need, expected volume and
first consumer. Reuse an existing adapter/publication path when the request is a
supported selection. A new provider or data type needs its own schema, identity,
clock/revision mapping and focused acceptance; a notebook download alone does
not create a maintained capability.

Return to data inspection with retrievable raw bytes, a dataset identity, quality
scope and source limitations. Keep macro/fundamental revisions in their owning
schemas rather than presenting them as trades.

### Research features and labels

The maintained [`FeatureStudy`](../src/research/features/README.md) path supports
versioned observed-price diagnostics with independent cutoff windows, missingness,
input identities and information/availability intervals. Define a feature by its
bindings, formula, units, cadence, warm-up and stale/missing policy. Define a
label separately by outcome, horizon, price convention and availability. A
forward label cannot enter the inputs to the decision it evaluates.

Inspect a hand-readable sample before fitting. Missing observations remain
missing, and fitted normalization or selection belongs inside the training
partition. A visible-book imbalance prototype may be useful exploration, but it
does not become a trade label without suitable future prices and timing evidence.

### Compare models or deterministic rules

Supply the temporal split, information intervals, transforms, trainer or rule,
comparison space, seeds, metrics and selection rule. The current split API admits
only rows available by the fit cutoff and protects validation/holdout information
with purge and embargo rules. Retain exact fit rows, feature/label versions,
fitted bytes, predictions and evaluation identity. A final holdout is consumed
evidence, not another exploratory input.

The [experiment core](../src/research/experiments/README.md) owns attempt history
and split semantics; the [study/report reference](../src/research/studies/README.md)
owns comparisons, diagnostics, publication and configured reports. Predictive
accuracy and economic value remain separate conclusions.

### Compare reference and current windows

The [window diagnostic reference](../src/research/studies/README.md#offline-window-diagnostics)
owns the frozen reference/current windows, KS thresholds, label cutoff, exact
source identities and report publication. This is an offline investigation. It
does not retrain, promote or trade, and missing labels leave feature diagnostics
available while predictive metrics retain explicit inapplicability reasons.

### Build and backtest a strategy

The [simulation contract](../src/simulation/README.md) and [saved L2 workflow](../docs/research/l2-book-backtest.md)
cover bounded synthetic/offline spot research. Select the instrument, cadence,
capital, limits, fees, positive delay and completed-price or book rule explicitly.
Inspect prediction/signal, target, rejection, fill, costs and NAV in one trace.
Trade prints or a reconstructed book alone do not establish a counterfactual fill
or queue position. Walk-forward decisions must use the model and preprocessing
state available at each historical decision; a final full-history fit cannot be
applied retroactively.

### Freeze and qualify a candidate

This is planned. A candidate bundle will identify inputs, feature/preprocessing,
optional model, signal policy, state/warm-up behavior and accepted experiment
references. Promotion, release installation and trading activation remain
separate decisions governed by the [platform design](../docs/architecture/platform-design.md#candidate-promotion-contract)
and [operating workflow](../docs/governance/workflow.md#activate-and-operate).

### Monitor, investigate and revise

Strategy monitoring is planned; bounded collector health and saved replay exist.
Retain candidate, input and artifact identities beside freshness, missingness,
decision failures, delayed-label coverage and economic attribution. A break in
data, features, model or execution returns to the relevant activity with a new
attempt and renewed qualification where assumptions changed.

## When research requires platform work

Within an implemented capability, a compatible formula, estimator, rule or
instance belongs in its owning package/configuration with focused tests. A new
source/schema, output contract, execution mechanic or runtime-state requirement
needs a bounded platform request. Describe the blocked activity, smallest
input/output example, missing capability, current limitation and observable
acceptance; keep the hypothesis and comparison attempts in the research record.
Under the revised roadmap, quant development closes all promised launch-scope
gaps before onboarding. This request path applies to later scope expansion or
defects discovered after handoff; it is not the trigger for building the initial
infrastructure. A compatible QR extension must not require a shared-runner edit.

## Construct and evaluate a retained model

The [model contract](../src/research/models/README.md) owns
`applications.explore.evaluate_model` over pinned feature results. It supports
configured no-fit coefficients and train-only exact least squares, reloads
immutable state for inference and retains predictive errors separately from
strategy economics. Use its installed consumer for construction/reload; local
publication failure evidence is not successful ClearML publication.

## What data am I actually researching?

The default offline QR lesson is synthetic software evidence: saved
Binance-format trades and one saved OKX L2 sequence, followed by a separate
synthetic price study with authored availability. The earlier archive can have
zero decision-eligible rows because historical availability is unknown; a saved
book state can support an exact visible-size calculation while coverage remains
unproven. These fixtures demonstrate interfaces and reconciliation, not a
user-selected empirical result.

The current supported source samples have distinct limits:

| Sample | Exposes | Still unknown |
| --- | --- | --- |
| Saved OKX historical L2 | Bounded archive prefix and native reconstruction | Per-record historical receipt clock, sequence continuity and full-day coverage |
| Bitfinex R0 recording | Visible orders, native prices/sizes and receipt order | Exchange timestamp, hidden orders, queue priority and executable fills |
| OKX public live book | Aggregate levels, source timestamps and local receipt evidence | Feed completeness and capture beyond the bounded interval |

A book is visible interest; a trade is a transaction. USD and USDT remain
different currencies, and sequential captures are not simultaneous. Do not infer
arbitrage or execution from an unqualified price difference.

## What the data pipeline provides

| Capability | Researcher receives |
| --- | --- |
| Acquisition and storage | Exact bytes, request identity, integrity checks and explicit access/timeout failures |
| Eligibility and revisions | Separate event/knowledge clocks, retained exclusions and unknown outcomes |
| Publication and reopening | Declared quality scope, deterministic identity and atomic snapshots reopened by explicit ID |
| Queries and replay | Cutoff/history modes, scoped controls and shared chronological stepping |

The [market-data command map](../src/market_data/README.md) owns exact
parameters, limits and failure contracts. An acquisition checkpoint does not
make every archive or live recording resumable, and output batch size does not
bound total process memory.

## Follow the connected dataset walkthrough

The offline QR notebook connects the implemented stages while keeping each input
and conclusion scoped:

| Stage | Reader action | Result |
| --- | --- | --- |
| 1. Question | State observable, universe, horizon and comparator | Research boundary |
| 2. Data | Discover metadata, pin named inputs and inspect clocks/quality | Selection and source limitations |
| 3. Features/labels | Apply explicit definitions and availability rules | Versioned diagnostics |
| 4. Models/rules | Reopen state, compare train-only or deterministic alternatives | Complete attempts and predictions |
| 5. Economics | Run a declared bounded rule or saved L2 scenario | Reconciled trace, checkpoints and report |
| 6. Handoff | Preserve identities, assumptions and limitations | Reviewable research record |

The [engineer notebook](infrastructure-diagnostics.ipynb) owns failure
interpretation and fresh-process reopening for installed consumers. It is not a
replacement for hosted validation or a research journal. The detailed execution
and query workload evidence remain in [notebook operations](notebook-operations.md#query-workload-evidence).

## How to interpret the evidence

An unchanged file matches its saved fingerprint; it does not prove provider
completeness. An empty input does not prove a quiet market. Source timestamps,
local receipt times, archive acquisition times and knowledge cutoffs answer
different questions and must stay separate. A live gap makes the reconstructed
book unavailable until synchronization; matching offline replay proves only that
the saved messages reproduce the same states.

Reopening the same saved bytes helps reproduce an analysis. A later provider
revision or changed implementation/settings needs a new identity. Keep raw
inputs, selections, attempts and reports together; a digest cannot recover a
missing file.

## A useful way to work through a notebook

Use the sequence **question → sample and assumptions → action → observed output →
interpretation and limits → next question**. Restart the kernel and run all cells
for a maintained executable example. Inspect clocks, identities, units, counts,
rejections and unknown statuses before interpreting a chart. Preserve the
attempt before changing a hypothesis. Do not inspect a final holdout through an
exploratory notebook.

## Small vocabulary for reading existing outputs

| Term | Meaning |
| --- | --- |
| Raw object | Original saved source bytes, such as an archive or capture journal |
| Partition | One requested source piece, often an instrument/day interval |
| Manifest | Saved request, input and completion record |
| Digest | Byte fingerprint; it is not a completeness score |
| Provenance | Path from an observation to source file, row and acquisition record |
| Replay | Process saved observations in order; it does not itself simulate a fill |

Update this page when a working reader journey, output meaning or limitation
changes. Keep commands and repair detail in `notebook-operations.md`, schemas in
their owning package guides, and historical evidence in its dated research page.

## Keeping this guide useful as the project grows

Refresh the reader entrypoints, status, output meaning, remaining limitations
and next useful action whenever a maintained workflow changes. Keep future work
as a named handoff in the roadmap and put shared calculations or execution repair
in their owning package/operations guide. Preserve fixed reference examples and
historical source identities when adding a new journey.
