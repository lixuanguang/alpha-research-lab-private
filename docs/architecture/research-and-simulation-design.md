# Research and simulation design

**Status: destination design.** Capabilities remain planned unless explicitly
identified as current. Quant development owns the implementation boundaries;
the roadmap owns delivery and acceptance.

[Platform design and dependency direction](platform-design.md).

## Dataset, feature, label, and experiment contracts

**Current saved research access:** `market_data.datasets.SnapshotCatalog` discovers
bounded manifest metadata; `research.exploration.ResearchSelection` pins named
trade/book inputs at one cutoff. `ResearchReader` assembles separate typed results
through existing snapshot admission and family-specific queries; the existing
`applications.explore.inspect_eda` composes it. Values retain source identities,
units, controls, membership and coverage limits. Book selection uses exact receipt
clocks and cannot invent availability for archives. No implicit join, filling or
currency conversion is performed. The
[public contract](../packages/market-data.md#discover-and-reopen-research-selections)
owns the supported fields, resource bounds, missingness and refusal behavior.


Planned dataset, feature, label, signal, model, cost, risk, portfolio, and candidate records carry identity, version,
inputs, units, availability, owner, and failure policy. They are small records around real consumers, not a global
registry that every exploratory file must enter.

Features are deterministic functions of PIT datasets. Metadata names every input, transform version, availability delay,
units, missing policy, range, and training fit interval. Labels name observation horizon, execution delay, price
convention, overlap, and missing policy. Scaling, neutralization, imputation, selection, and hyperparameters fit only on
data available in the applicable training interval.

**Current versioned diagnostic:** `research.features.TrailingReturn` computes exact
observed-price window returns; `research.labels.ForwardReturn` separately computes
delayed outcomes against frozen earlier endpoints. `FeatureStudy` reuses pinned
trade selection and the existing retained exploration application. Every decision
has its own knowledge cutoff; labels cannot enter earlier feature values. The
[public contract](../packages/research-features.md) defines the query business
clock, cadence, warm-up, missing/stale policy, exact rational units, input lineage
and bounded execution. This does not implement the economic baseline's completed
observations or a book/macro formula. The separate completed-price feature now
reuses `research.observations` and one `CompletedReturn` formula across simulation
and a bounded scheduled batch path. `applications.backtest.qualify_scheduled_features`
and its `qualify-features` subcommand retain exact replay/batch/restart traces.
This qualifies saved-input software only; live source/cadence qualification
remains open. Online retrieval and local candidate binding implement
their declared boundaries. Their in-scope
lifecycle and serving interfaces are required before full QR onboarding (G5), exercised
by reference consumers owned by quant development. The feature store must provide
the offline and online behavior below; its service topology follows the workload.

An experiment identity includes source and dataset manifests, code/artifact revision, resolved non-secret configuration,
environment/toolchain identity, component versions, split rules, and random seeds. Wall-clock creation time is metadata,
not identity. Failed or rejected trials that influence selection remain append-only, and the final holdout is frozen
before evaluation.

**Current attempt/split core:** `research.experiments` separates deterministic
input identities from execution IDs, admits only then-available training rows,
and retains explicit purge/embargo and no-fit policies. A local single-writer
store preserves incomplete, failed, rejected and abandoned attempts; atomic
completion contains the result bytes. Family holdouts are frozen and consumption
is retained before access. `applications.explore.inspect_experiment` composes
this core with the existing pinned selection reader for unfitted inspections.
`research.studies` owns the existing report, diagnostic, comparison and tracking
implementations behind a separate curated API. Core record access does not import
those integrations; both owners retain the existing serialized record contracts.
Study and exploration APIs import ClearML, Optuna, DuckDB and Polars only when
their corresponding operations run. `research.results.FeatureStudyResult` owns
the shared retained feature-result schema used by production and admission.
The [public contract](../packages/research-experiments.md) owns clocks,
identity, retention, concurrency, recovery and supported evaluation boundaries.
The [bounded model consumer](../packages/research-models.md) now adds configured
and train-only centered least-squares state, reload-only inference and exact
predictive evaluation. ClearML publication is a separate recoverable outbox;
terminal attempts and holdout history remain authoritative locally. ClearML source admission verifies
the locked wheel against its pinned upstream archive. Configured economic reports and local serial installed pipelines are now implemented;
local candidate packaging/binding is now implemented. Explicit unfitted engineering samples use the
same backtest workflow and retained stores without designating a validation or holdout
window. Family declarations prevent crossing design modes to bypass holdout controls.
Native archive capture corroboration lives in existing market-data owners; scoped
causal admission preserves unresolved coverage and revision-history limits.

**Current comparison owners:** compatible feature and estimator factories extend
their existing typed definitions, while `strategies.RuleRegistry` creates fresh
rule instances for each economic run. `research.studies` owns bounded Optuna
journals, complete unsuccessful-trial history and Alphalens report contracts;
`research.exploration` owns verified bounded DuckDB/Polars projections.
`research.features` owns the offline Feast bridge and causal result admission.
The existing exploration/backtest applications compose these libraries; no library
imports an application or exposes a runnable command. Feast's incompatible pandas
constraint is isolated in a separately locked local SDK worker, while core pandas
remains 3.0.5. The
[accepted diagnostic tool amendment](dependency-admission.md#diagnostic-tool-requirement-amendment)
makes offline reference/current reports mandatory and Evidently optional. The
consumer now belongs to `research.studies.WindowDiagnostics` and
`WindowDiagnosticRun`, composed by `applications.explore.compare_windows` and
published through the existing ClearML outbox. It uses admitted SciPy for explicit
reference/current tests and exact rational predictive errors with delayed-label
admission. Its [contract](../packages/research-studies.md#offline-window-diagnostics)
retains reproducible reports and failure/retry semantics. Evidently's reviewed
closure still fails admission; it is not installed. The roadmap owns verification
and acceptance status. No comparison grants candidate, deployment or trading authority.

Research reports state the economic mechanism, falsifiable hypothesis, target, sign, horizon, universe, rebalance,
benchmark, expected turnover/liquidity, cost and capacity assumptions, metrics, rejection criteria, and limitations.
Once an exploratory result influences a candidate decision, it receives durable identity and provenance.

### Feature-store contract

Status: **implemented local versioned feature store and isolated Feast serving,
including supervised paper/shadow consumption; deployment remains separate**.
The research contracts own feature definitions and result semantics; the feature store
owns provisioned stores, materialization and retrieval. Candidate packaging loads complete
candidates through that store, and the paper runtime binds it through `runtime.CandidateFeatureFeed` to the
checkpointed paper OMS. The store serves
versioned features across studies and strategy instances rather than a special
case for the initial return diagnostic. Preserve Feast's independently locked
worker and the core numerical/temporal contracts while extending its integration.

Each retrieval binds entity/instrument keys, feature definition and schema,
fitted-transform version where applicable, source/dataset revisions, event and
availability clocks, missingness and freshness/TTL policy. Offline PIT retrieval
preserves knowledge-time corrections. Online materialization is restartable and
idempotent, publishes a named version atomically, and cannot expose a future or
incompatible value. Latest-value retrieval is not historical replay; retained
versions and inputs must permit reconstruction of decisions.

Matched definitions, entities and cutoffs reproduce admitted offline and online
values within declared numerical tolerances, retaining exact financial contracts.
Exercise late corrections, missing entities, expired values, partial publication,
retry and version rollback. Serving returns version and quality metadata; consumers
refuse incompatible or stale state according to their declared policy. Loss of
the serving service triggers the runtime's explicit pause or qualified fallback,
never silent recomputation using different definitions. Backup/restore and capacity
evidence cover source products, registry/state and serving recovery.

### Research-driven feature lifecycle

**Research SDK:** named source projections, ordered multi-feature
schemas, train-only fitted transforms, arbitrary estimator state, separate labels,
and target/exposure/order/quote policies now run through
`applications.explore.run_decisions` / `inspect_decisions`. Pure feature/policy
transitions retain isolated restart state; the installed consumer supplies fresh
implementations without shared runner edits. The owning
[feature guide](../packages/research-features.md#generalized-feature-lifecycle),
[model guide](../packages/research-models.md#generalized-estimator-lifecycle),
[observation guide](../packages/research-observations.md) and
[strategy guide](../packages/strategies.md) define the exact supported scope.
Studies compose these definitions into costed temporal studies, search and
extensible retained reports. The [feature guide](../packages/research-features.md) owns local
feature-store services and online consumption. Candidate packaging
and runtime binding are implemented locally, with supervised
paper/shadow integration. Offline study fills do not
qualify venue execution.


QR owns new formulas and research choices within an
[accepted bounded offline scope](../roadmap/overview.md#bounded-offline-research);
quant development supplies the execution, alignment, lineage and state machinery
plus concrete reference consumers. Full G5 completion includes named trade/book/non-book features,
separate labels, multiple model inputs, fitted preprocessing, train/inference
adapters and stateful batch/incremental execution. Demonstrate these through the
roadmap's rule-only, learned and stateful examples. Support compatible definitions
beyond the current trailing-return and linear-model schemas without adding every
possible formula or estimator to a starter catalog.

Research dataset assembly supplies explicit inputs over the query contracts.
Label generation and alignment remain separate from prediction inputs. Shared
attempt and temporal split records support retained exploration, fitting,
walk-forward evaluation and backtests. QR does not need to select a model or
candidate before this infrastructure can be implemented and qualified.

Reusable transforms belong to `research/features/`; labels to `research/labels/`;
trainers/inference to `research/models/`; split/attempt/candidate records to
`research/experiments/`; retained feature-result contracts to `research/results/`;
study/report integrations to `research/studies/`.
The attempt/split owner now serves exploration; the
model owner now serves the same application; quant development supplies consumers
for planned behavior before onboarding, with source owners added as needed.
Notebooks may explore local variants; formal retained and promoted results call
the accepted versioned implementations. A candidate binds its inputs, definitions,
parameters, split/fit identity and fitted state where applicable. Rejected
candidates remain research evidence without becoming active runtime components.

Training and runtime applications compose those same library operations through
admitted input adapters. They do not import one another's workflows, copy formulas
or refit state implicitly. An incremental implementation must preserve historical
semantics under ordering, late data, warm-up and recovery; validate numerical
agreement under a declared contract rather than assuming identical algorithms.
A scheduled batch candidate need not acquire incremental machinery. Changed
semantics require new versions and affected validation.

### Candidate promotion contract

Status: **implemented for local candidate packaging and intent-only runtime binding**.
The [candidate guide](../packages/research-experiments.md#candidate-bundles) and
[runtime guide](../packages/runtime.md#candidate-loading-and-intent-evaluation)
own the installed interfaces. Quant development implements
the candidate manifest in `research/experiments/` using both rule-only and learned
reference candidates. Learned fields remain inapplicable for a rule-only
candidate. A reference engineering artifact is explicitly distinguished from a
candidate with accepted empirical evidence; no profitable or selected QR strategy
is a prerequisite for the loader or its qualification. Runtime binding consumes this same
contract. Research can construct and validate a candidate without a paper runtime,
venue connection or trading credentials. These are small versioned artifacts,
not a registry service.

| Candidate content | Meaning at research/runtime handoff |
| --- | --- |
| Identity and reproduction | Candidate/component versions, code/environment identity, retrievable artifacts and accepted trial/report references; training input/split provenance remains retained |
| Runtime input requirements | Named data bindings, schema/units, supported instrument/product, cadence, knowledge/availability rules, coverage/freshness and missingness policy; runtime bindings may differ from historical snapshots but must satisfy the same contract |
| Features and fitted preprocessing | Definitions/parameters, ordered input signature, entity/schema and feature-store version bindings, accepted fitted-state bytes and fit cutoff; runtime does not refit implicitly |
| Optional model | Serialization/version, expected feature signature, output meaning and numerical contract, training/label cutoff and permitted activation time |
| Decision policy | Versioned prediction/signal-to-target-position/exposure or order/quote-intent implementation and parameters; rules need no model, and unsupported output contracts fail |
| State and qualification | Warm-up/checkpoint/reset compatibility, batch/incremental requirements, retained parity/evaluation evidence and limitations |
| Metrics and views | Versioned research/runtime metric and chart definitions, applicability, units and diagnostic thresholds; independent hard risk policy stays outside the candidate |

A model is not a trading strategy. The QR's decision policy turns then-available
predictions/signals into its declared target or order/quote-intent contract.
Shared applications apply independent risk, simulation or execution and accounting
outside that policy.
Walk-forward evaluation chooses only artifacts that could have been fitted by the
historical decision, including label availability and declared training/deployment
timing. Never use a final full-history fit for earlier decisions.

Promotion loads the accepted components and verifies compatible inputs/state;
matched inputs reproduce features, predictions and decision outputs under their
declared contracts. Artifact verification precedes deployment; runtime binding and
paper/live qualification preserve the accepted candidate. Candidate evidence grants neither release
admission nor trading authority. Retraining produces a new version and repeats
affected qualification. Rollback compatibility is explicit and cannot undo fills.

## Shared strategy and simulation parity

The strategy kernel is typed deterministic logic with injected clocks, data, positions, risk decisions, and execution
interfaces. It contains economic decision logic, not a broker client, database transaction, or self-approval path.

Target-position/exposure strategies and order/quote-intent strategies use distinct
typed outputs. Portfolio coordination resolves allocation and conflicts for each
without forcing quotes into weights. Both enter the same independent risk and
OMS boundary with instance ownership, instrument, account and version identity.
Quant development supplies an active reference consumer of each output form;
the no-trade control remains additional evidence, not the shared-account test.

The local shared-account path reuses `DecisionSession` for each selected policy
and persists one policy continuation per configured instance. `runtime`
`SharedDecisionRuntime` stages the typed decisions; `applications.paper`
`run_shared_paper` composes them with observed account quotes, complete local
account observations and normalized physical order events. This finite event
workflow does not connect to private venue streams, submit orders or infer fills
from book liquidity. Dedicated candidate supervision remains in
`PaperCandidateRuntime`.

The same kernel runs in these modes:

| Mode | Purpose and boundary |
| --- | --- |
| Unit/golden | Exact fixtures and hand-calculated behavior |
| Replay | Historical canonical events with deterministic state transitions |
| Simulation | Replay plus declared fill, latency, cost, and market-mechanics models |
| Paper | Live or delayed data with simulated order/fill lifecycle and no executable venue submission |
| Shadow | Live decisions and risk traces with venue submission suppressed |
| Canary | Bounded live venue activity under an explicit activation envelope |
| Live | Only after release, risk, reconciliation, stop, and monitoring evidence |

Simulation declares what it omits: queue priority, venue throttles, partial fills, market impact, borrow recalls,
funding timing, auctions, disconnects, or other behavior. A result cannot silently imply omitted mechanics. Replay and
paper compare decisions, target quantities, risk decisions, order intent, and state traces; differences are classified
by data, timing, randomness, market mechanics, or implementation before advancement.

Replay and research consume one [event-stepping contract](../data/point-in-time-semantics.md#chronological-ordering-and-event-stepping),
owned by chronological replay. Pipelines compose operations and retain state; the iterator and
scheduled-step library enforce source admission, expiry, pending fill, decision
and valuation order. Use fixed source/stream precedence and stable logical source
order for meaningful ties. Hashes retain provenance without allowing future byte
changes to reorder earlier economics. The [bounded spot economic consumer](../packages/simulation.md) now exercises
this contract through frozen observations, rules, independent limits, delayed fills,
exact accounting and complete checkpoints. Its installed workflow reopens saved
synthetic archives. The installed `alpha-backtest` command extends the same path with validated configuration,
durable QuantStats reports and local serial ClearML steps. `market_data.storage`
pins lakeFS dataset/feature versions without changing the existing reader clocks.

### Replay clocks and fill fidelity

Preserve exchange time, local receipt, ingestion and effective knowledge as
distinct facts under the [point-in-time contract](../data/point-in-time-semantics.md).
Retain original precision and source order. Introduce versioned integer timestamp
units only when a supported consumer needs precision beyond the current boundary;
never reinterpret existing microsecond values. Negative apparent latency is a
clock-quality observation. A correction requires an explicit versioned model
and calibration availability, retaining original clocks; a future extreme offset
must not rewrite an earlier decision's information set.

An order-book simulation distinguishes exchange-side matching state from the
strategy's then-known state. Feed delay, local processing, order entry and order
response delay have separate meanings. A fill can occur before its response is
visible locally; a cancel request is not a successful cancel. Retain send,
exchange/acknowledgement/fill and response identities/times where actually
observed, with absent clocks explicit. Constant delays are declared scenarios;
empirical latency models need source/environment identity, calibration windows,
coverage and sensitivity checks. Archive download time cannot measure historical
feed latency. Use recorded or paper/sandbox evidence first; the existing authority
rules continue to govern executable activity.

Extend replay, strategy, fill, cost and order contracts for the required reference
quoting consumer as its book, order lifecycle and product economics become available.
Introduce pure order-lifecycle contracts with an offline simulator when needed;
runtime binding remains a prerequisite
for the paper runtime, not for those pure contracts. Saved-book research does not
require a deployed collector. Define queue assumptions, maker/taker
fees, supported order types, post-only rejection, partial fills and cancel/replace
priority. For L2, position in queue is modeled; L3 requires actual order identities
and lifecycle data. Trade depletion and its matching depth decrease must not
advance the modeled queue twice. Deterministic scenarios exercise the selected
model and an alternative plausible queue/latency assumption; they are not proof
of exchange fidelity.

Historical replay does not change other participants' recorded orders when our
simulated order trades. State the no-impact and size/liquidity envelope, and reject
or visibly bound unsupported liquidity-taking/capacity claims. A partial-fill
option alone does not remove this limitation. Keep P1's declared trade-price
model intact; book-based research needs a separate versioned experiment.

The [roadmap](../roadmap/overview.md#capabilities) records paper qualification.
