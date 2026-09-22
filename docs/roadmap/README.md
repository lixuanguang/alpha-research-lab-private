# Platform infrastructure roadmap

Owner: repository founder. Updated 2026-09-22. **MRs 1–7 are implemented; MR 8 has
scoped causal integration with empirical acceptance open; MR 9 has bounded saved-input
batch parity with runtime qualification open; MR 9A has completed local L2
backtesting acceptance; MRs 10–21 are planned.**
Numbering identifies the selected delivery slices; completed capabilities become
the current platform without renumbering the remaining backlog. MR numbers identify delivery
work, not packages, APIs, notebook sections or experiment versions.

This is the quant developer's infrastructure plan. The
[QR implementation guide](../../examples/README.md) explains how researchers use
available capabilities and prepare research for promotion. The
[research program](research-program.md) owns methodology and experimental choices;
the [platform design](../architecture/platform-design.md) owns shared contracts.

## Current platform

The working path is configured acquisition or capture → retained raw inputs →
validation and versioned publication → explicit snapshot queries/replay → EDA,
model studies or configured bounded spot economics → retained costed reports.

| Available capability | Researcher benefit | Current limit |
| --- | --- | --- |
| Instrument identity, calendars and exact financial units | Shared identifiers, clocks and numerical conventions | These foundations do not constitute a strategy ledger or execution engine |
| Bounded historical acquisition and native capture | Retained source bytes, request identities and explicit failure/recovery behavior | Supported sources and products only; source-specific limits remain visible |
| Occurrences, revisions, eligibility and dataset publication | Trace observations and reopen a verified snapshot | Empirical historical eligibility, coverage and revision availability remain unresolved for the frozen sample |
| Trade cutoff/history queries and chronological replay | Inspect what is knowable and retain corrections and scoped controls | Bounded reference implementation; replay alone does not simulate economic fills |
| Book reconstruction, publication and replay | Inspect visible books, recovery and matching saved state | Exploratory degraded scope; no queue position or executable-fill claim |
| Retained experiment attempts and temporal splits | Reproduce semantic inputs, inspect all attempts and enforce declared fit/holdout boundaries | Local single-writer store; current consumers are unfitted exploration and price diagnostics, with bounded model and economic consumers |
| Versioned observed-price features and separate forward labels | Inspect exact returns, causal windows, missingness and delayed outcome availability | Bounded unfitted trade-price diagnostic; no economic, book/macro, model or runtime claim |
| Saved L2 IOC backtesting | Run saved-book EDA, isolated rules, depth fills and exact cash/positions/P&L | Constant research delays; unknown source receipt/continuity; no-impact visible-size model |
| Exact trade-price spot economics and bounded vectorbt comparison | Reconcile delayed target execution, costs, cash, holdings and retained analytical output | Synthetic/offline spot scope; no liquidity, empirical or execution qualification |
| Configured economics, QuantStats reports, local ClearML pipelines and lakeFS input pins | Run, repeat, resume and inspect exact costed output with retained failures and immutable storage versions | No-fit validation studies, one serial local worker and synthetic retention/restore qualification |
| Retained comparisons, factor/window reports and offline feature parity | Reproduce Optuna trials, Alphalens and SciPy diagnostics, and causal Feast retrieval through installed research APIs | Bounded local synthetic scope; diagnostic thresholds confer no promotion authority |
| Pinned research selections, configured EDA and maintained notebooks | Discover saved snapshots and reopen named trade/book inputs with identities, units and missingness | Bounded exploratory assembly; shared large-study orchestration and empirical acceptance remain planned |

The [data command reference](../../src/market_data/README.md) owns current usage.
The [frozen P1 experiment](../research/p1-baseline.md) retains its own identity,
source sample and economic assumptions. It is not renumbered with this roadmap.
No empirical strategy, paper deployment or live trading acceptance is claimed.

## Platform and researcher responsibilities

| Boundary | Quant researcher owns | Platform infrastructure owns |
| --- | --- | --- |
| Data | Required universe, fields, horizon, quality and source/use requirements | Adapters, provenance, revisions, publication, discovery and causal assembly |
| Features and labels | Hypothesis, formula, target, windows and missingness policy | Reusable execution, alignment, lineage and applicable state handling |
| Models and rules | Estimator/rule, comparison space, metrics and selection choices | Temporal splits, fit/inference lifecycle, complete attempts and reproducible artifacts |
| Backtesting | Signal-to-target policy and declared economic assumptions | Shared runner, independent risk, simulated fills, exact accounting and reporting |
| Promotion | Frozen candidate and accepted research evidence | Compatibility checks, artifact loading, runtime binding and qualification |
| Operation | Investigate attributed behavior and propose a new candidate | Execution, reconciliation, monitoring, recovery and separate activation controls |

A supported new feature, estimator or rule should plug into existing interfaces
without modifying shared runners. A new source/schema or execution mechanic needs
its missing platform capability first. Add interfaces with concrete consumers;
do not build an empty feature catalog, registry service or generic plugin framework.

## Delivery order and dependencies

The first useful outcomes are researcher data access, auditable comparisons and a
small economic backtest. Those tracks share contracts but do not force every
candidate through model training. Source onboarding is driven by an actual missing
input. The synthetic economic path can begin with existing saved fixtures while
source evidence and researcher access improve independently.

| MR | Delivery outcome | Prerequisites |
| --- | --- | --- |
| 1 | [Research dataset access and source onboarding](#research-dataset-access-and-source-onboarding) — implemented | Current query/publication APIs |
| 2 | [Experiment attempts and temporal splits](#experiment-attempts-and-temporal-splits) — implemented | Existing saved inputs; integrates with MR 1 |
| 3 | [Versioned features and labels](#versioned-features-and-labels) — implemented | MR 1; MR 2 for formal comparisons |
| 4 | [Model records, evaluation and ClearML tracking](#fitted-preprocessing-and-model-evaluation) | MR 2 for tracking; MR 3 for feature-consuming models; fitting only where applicable |
| 5 | [First economic backtest and vectorbt research adapter](#first-economic-backtest) | Existing replay and financial contracts; MR 4 for tracked vectorbt runs; no fitted-model dependency |
| 6 | [Configured runs, ClearML pipelines and versioned reports/data](#configured-runs-and-durable-reports) | MRs 1–2, 4–5; lakeFS adapter preserves existing dataset contracts |
| 7 | [Research comparison, offline diagnostics and Feast retrieval](#research-comparison-and-extension) — implemented | MRs 1–6; fitted-state requirements only where applicable |
| 8 | [Frozen baseline acceptance](#frozen-baseline-acceptance) — scoped causal integration delivered; acceptance open | MRs 5–6 plus required actual source evidence |
| 9 | [Runtime feature parity and applicable Feast online retrieval](#runtime-feature-parity) — saved-input batch slice delivered; runtime acceptance open | MRs 3–4; MR 7 for a Feast consumer; qualified runtime input, only if required |
| 9A | [L2 order-book backtesting](#l2-order-book-backtesting) — implemented; local acceptance complete | Saved L2 reader and MRs 5–6; before MR 10 for order-book strategies |
| 10 | [Candidate packaging and runtime binding](#candidate-packaging-and-runtime-binding) | MRs 6–7 and accepted candidate evidence; MRs 4/9 where applicable; MR 9A for order-book strategies |
| 11 | [Trusted deployment artifact](#trusted-deployment-artifact) | Dependency admission and a concrete deployable consumer |
| 12 | [Paper order lifecycle and recovery](#paper-order-lifecycle-and-recovery) | MR 10; MR 11 before deployment |
| 13 | [Independent risk and account reconciliation](#independent-risk-and-account-reconciliation) | MRs 5 and 12 |
| 14 | [Shared account allocation](#shared-account-allocation) | MR 13; only before multiple instances share an account |
| 15 | [Operations and paper qualification](#operations-and-paper-qualification) | MRs 10–13; MR 14 if sharing an account |
| 16 | [Executable venue adapter](#executable-venue-adapter) | Order/risk/reconciliation contracts from MRs 12–13 |
| 17 | [Live monitoring and controls](#live-monitoring-and-controls) | MRs 15–16 |
| 18 | [Bounded activation and recovery](#bounded-activation-and-recovery) | MRs 11, 15–17; explicit operating authorization |
| 19 | [Additional compatible live instance](#additional-compatible-live-instance) | MR 18; MR 14 if sharing an account |
| 20 | [Measured storage and computation growth](#measured-storage-and-computation-growth) | A measured workload exceeding an accepted budget |
| 21 | [Python ownership and enforcement](#python-ownership-and-enforcement) | Existing engineering rules and tooling/tests |

Numbers provide a fresh backlog order, not a requirement to wait for every lower
number. MR 11 must move forward before any actual deployment, including a collector.
MR 21 can proceed independently. MR 8 accepts the specific frozen experiment;
MR 7 separately accepts the reusable research workflow. Neither substitutes for
the other's evidence. Conditional work stays dormant until its consumer exists.
MR 9A implements the saved ETH-USDT order-book workflow independently of MR 8
and the runtime portion of MR 9. Its local acceptance is complete; hosted merge
gates remain required. MR 10 can package an order-book candidate after those
gates; trade-price candidates retain their existing prerequisites.

## Selected research integrations

This revision starts at MR 4. MR 3's feature/label scope and acceptance remain
unchanged by these plans; later adapters consume its delivered public outputs.
MR 4's ClearML/Pandera, MR 5's bounded vectorbt, and MR 6's report/pipeline/storage
consumers have concrete implementations and evidence below; MR 7 is delivered in its bounded scope,
MR 9A also delivers bounded L2 economics; the remaining later entries stay planned.
Deliver the named consumers in bounded slices within the existing MR numbers.

Use **ClearML** for experiment tracking, model records and research orchestration.
This supersedes the earlier MLflow-plus-Aim proposal and removes Dagster from the
selected stack. Do not add aimlflow or a second experiment/orchestration backend.
The comparison below is an architectural assessment for this repository, based on
upstream documentation checked on 2026-09-20, not a measured performance ranking.

| Candidate | Relevant strengths | Fit for the selected workflow |
| --- | --- | --- |
| [MLflow](https://mlflow.org/docs/latest/ml/tracking/) | Parameters, metrics, artifacts, dataset-linked evaluations and a [versioned model registry](https://mlflow.org/docs/latest/ml/model-registry/) | Strong choice for tracking and model packaging alone; a separate workflow execution solution would still need selection |
| [Aim](https://github.com/aimhubio/aim) | Interactive metric histories, context-aware queries, grouping and run comparisons | Useful experiment exploration; not selected as the model-lifecycle and orchestration foundation |
| [ClearML](https://clear.ml/docs/latest/docs/fundamentals/task/) | Experiment tasks, explicit artifacts, [input/output model records](https://clear.ml/docs/latest/docs/fundamentals/models/), [agents](https://clear.ml/docs/latest/docs/clearml_agent/) and [pipelines](https://clear.ml/docs/latest/docs/pipelines/pipelines_sdk_tasks/) | Selected: one researcher-facing system covers tracking and queued workflow execution; its self-hosted server has more infrastructure than a local tracking library |

All three can record numerical experiments without ML training. Custom analytical
and statistical models still need explicit state serialization, provenance and
evaluation definitions; framework autologging does not supply these contracts.
ClearML's model IDs are not a substitute for immutable model-version manifests.

| Selected tool or capability | Researcher outcome | First integration and later extension |
| --- | --- | --- |
| ClearML | Find attempts, models, diagnostics and reports; repeat declared workflows | MR 4 tracking/model records; MR 6 pipelines/agents; MRs 10–11 frozen artifacts and service qualification |
| [vectorbt](https://vectorbt.dev/) | Rapid supported strategy/parameter exploration | MR 5 bounded adapter against the reference ledger; MR 7 tracked parameter comparisons |
| [Alphalens Reloaded](https://github.com/stefan-jansen/alphalens-reloaded) | Factor information coefficients, quantile returns, turnover and grouped diagnostics | MR 7 consumes MR 3 outputs and publishes retained reports to ClearML |
| [lakeFS](https://docs.lakefs.io/) | Reopen the exact data/feature snapshot used by an experiment | MR 6 versioned dataset storage adapter; MR 10 pins commits and retention; MR 20 scales storage |
| [Feast](https://docs.feast.dev/getting-started/concepts/point-in-time-joins) | Reuse feature definitions and retrieve aligned historical feature values | MR 7 offline consumer; MR 9 online retrieval only for a candidate that needs it |
| [Pandera](https://pandera.readthedocs.io/en/stable/) | Validate dataframe schemas, nullability and declared constraints at research boundaries | MR 4 model/evaluation input adapters; later reporting/feature-store adapters consume the same contracts without reopening MR 3 |
| [SHAP](https://shap.readthedocs.io/en/latest/) | Inspect feature contributions to a selected model's predictions | MR 4 conditional explanation consumer; MR 7 comparisons use the same retained explanation specification |
| [QuantStats](https://github.com/ranaroussi/quantstats) | Portfolio statistics and HTML performance reports | MR 6 consumes retained costed returns from MR 5 |
| [Optuna](https://optuna.readthedocs.io/en/stable/) | Search declared model, calibration or strategy parameter spaces | MR 7 after retained evaluations; ClearML owns execution/tracking and Optuna owns sampling/pruning |
| [marimo](https://docs.marimo.io/) | Reactive Python notebooks and interactive research controls | MR 7 optional interface alongside maintained notebooks, calling the same installed research APIs |
| [DuckDB](https://duckdb.org/docs/current/data/overview) / [Polars](https://docs.pola.rs/user-guide/lazy/using/) | SQL exploration of research files and dataframe transformations | MR 7 bounded analysis adapters over verified inputs; MR 20 for replacement of performance-sensitive internals |
| [Offline window diagnostics](#diagnostic-tool-requirement-amendment), using admitted computation dependencies | Data quality, distribution drift and applicable predictive-performance reports | MR 7 retained reference/current-window reports; MRs 15/17 scheduled evaluation. Evidently is optional and remains unadmitted |
| [skfolio](https://skfolio.org/) | Portfolio allocation research under declared objectives and constraints | MR 7 conditional multi-asset portfolio consumer; MR 14 retains independent account allocation/risk authority |

Feast and lakeFS are complementary. lakeFS versions stored bytes; Feast describes
and retrieves features. Neither replaces the existing knowledge-time, revision,
historical-universe or holdout contracts. Keep one dataset versioning authority:
ClearML tasks reference lakeFS commits and repository manifests rather than adding
a parallel ClearML Data version hierarchy for the same datasets. Model/report
artifacts remain accessible through explicit retained locations and content digests.

At each tool's first consumer, pin SDK/server versions and verify the actual install,
serialization and reopen path on the supported environment. Preserve Python 3.14,
strict typing, the dependency-admission rules and numerical contracts. Check native
dependencies, including vectorbt's chosen computation backend. If an integration
requires another interpreter, use a separately locked worker with versioned input/
output records and prove the boundary rather than silently changing the core runtime.
Confirm required capabilities in the selected self-hosted edition. Use ClearML's
[Python scheduling interface](https://clear.ml/docs/latest/docs/getting_started/task_trigger_schedule/);
its no-code scheduling application is an Enterprise feature.

SSPL and Commons Clause components are eligible under the founder's stated
infrastructure preference: [ClearML Server uses SSPL](https://github.com/clearml/clearml-server#license-and-legal-information)
and [vectorbt uses Apache 2.0 with Commons Clause](https://vectorbt.dev/terms/license/).
Record the exact admitted component's license; eligibility does not imply that
commercial-only features or vectorbt PRO are included. Shared/operated services
still need MR 11 before deployment; local integration evidence does not qualify them.

The earlier tool shortlist's version numbers are research observations, not a
compatible dependency lock. Admit the versions actually exercised by each slice.
Analytical libraries do not each require a service: start with local adapters and
retained artifacts. Conditional explanation, drift and allocation tools need the
specific model/data/portfolio consumer described below, not every experiment.

## Research infrastructure

### Research dataset access and source onboarding

**MR 1 — implemented (bounded software acceptance).** Give the QR one bounded way to discover saved datasets, select explicit
snapshots/universes/fields/time ranges and assemble compatible research inputs.
Use existing publication, trade and book interfaces; do not merge incompatible
schemas by pretending every source is a trade. Retain query/input identities,
units, quality, historical membership and missingness alongside the values.

Exercise one demanded source or dataset extension from acquisition through
publication and the same research interface. Additional supported instruments or
intervals should require configuration; new providers/data families require the
adapter, schema and temporal semantics they actually lack. Preserve access and
retention limits. A future macro/fundamental input must expose release/revision
availability, not merely a business date.

Acceptance: a QR can reopen a pinned multi-input selection; a late correction or
unavailable input cannot appear at an earlier decision; missing coverage remains
visible; a supported extension works without changing the research runner.
Own this in `market_data/` and `research/`, composed by `applications/`.

Delivered through `SnapshotCatalog`, `ResearchSelection` / `ResearchReader`, native
book cutoff projections and the existing `inspect_eda` entry. The configured
`spot-comparison` job exercises BTC/ETH acquisition through publication and a
pinned selection alongside a synthetic OKX book, reopened in a fresh process.
The [installed workflow](../../tests/integration/consumers/datasets/ingestion_workflow.py)
and [access regressions](../../tests/unit/data/test_research_access.py) cover the
acceptance boundaries; the [QR guide](../../examples/README.md#select-and-inspect-research-data)
and [command reference](../../src/market_data/README.md#discover-and-reopen-research-selections)
own current use. The maintained [QR notebook](../../examples/research-foundations.ipynb)
follows research activities; the [engineer notebook](../../examples/infrastructure-diagnostics.ipynb)
owns infrastructure diagnostics. Each journey also has a live public-capture version:
[QR live](../../examples/research-foundations-live.ipynb) and
[engineer live](../../examples/infrastructure-diagnostics-live.ipynb). They reuse the
existing bounded collector/publication APIs and retain selections for offline reopening.
Future research stages are labeled planned rather
than accumulated as infrastructure milestone sections. Validation commands/results
and the failed development attempts
are recorded in the implementation PR, rather than a separate MR archive.

The dataset-extension acceptance is synthetic software evidence. Live notebook runs
add bounded public-source observations, without establishing empirical acceptance.
Source coverage, book historical membership
and archive revision availability remain unproven where documented. Unknown
availability yields no earlier values; no new provider, macro schema, empirical
P1 acceptance, deployment or execution capability is claimed.

### Experiment attempts and temporal splits

**MR 2 — implemented (bounded software acceptance).** Introduce shared attempt and split records before formal feature/model
comparison. Separate reproducible semantic run identity from execution attempt
identity. Hash inputs, components, configuration and seeds; exclude output paths,
wall-clock attempt times and generated results from the semantic input identity.
Retain influencing failed, rejected and abandoned attempts and consumed holdouts.

Temporal splits carry information intervals and label availability, with purging
and embargo when applicable. Train-only fitting and untouched evaluation boundaries
must be enforceable by the consumer. A rule with no fit records inapplicability
rather than inventing training rows. Define atomic completion and the initial
single-writer/concurrency boundary; incomplete attempts remain inspectable.

Acceptance: reload the same inputs/splits deterministically; future/holdout rows and
late labels cannot enter fitting; changed inputs produce a new identity; interrupted
attempts cannot appear completed. `research/experiments/` owns the reusable core.

Delivered by the [experiment core](../../src/research/experiments/README.md) and
`applications.explore.inspect_experiment`, composing existing pinned MR 1 inputs.
`ExperimentSpec` separates semantic inputs/components/configuration/seeds from
UUID execution identity; `TemporalSplit` retains information/availability clocks,
purge/embargo and enforceable admitted fit IDs. The first `ExplorationStudy`
consumer explicitly has no fit. `AttemptStore` retains all committed attempts,
freezes family holdout windows, records consumption before reads and atomically
publishes completion with result bytes. An interrupted attempt remains incomplete.

Verification on 2026-09-20: the prerequisite research-access suite passed **6 tests**
before implementation. During development, the affected suite
`uv run --frozen --no-editable pytest -q -m 'not performance' tests/unit/research/test_experiments.py tests/unit/data/test_research_access.py tests/integration/test_ingestion_workflow.py`
passed **15 tests**, with no skips or deselections. It includes independent fitting
examples, real process death before completion, failed holdout consumption and
installed fresh-process identity/result reproduction. Focused strict mypy passed
all **12 selected source/test files**. Final `TMPDIR=/private/tmp make check`
passed: **1,079 correctness/integration tests, 3 performance tests deselected,
no skips**, all required static/governance/security/dependency checks and the
isolated installed-wheel smoke. This final suite also includes the subsequent
interrupted-rejection regression. Strict typing covered **247 source files** and
native stub validation **1,548 modules**. The standard link check passed **32 docs**;
explicit checks also passed the component, example and test READMEs outside its
discovery scope. The implementation PR retains development failures and hosted
CI status. No notebook cells or live-source paths changed; earlier live evidence
is unchanged and no new empirical or performance claim is made.

The initial store is a trusted local POSIX single-writer boundary, not distributed
coordination or a global holdout access service. Research consumers must supply
truthful sample intervals and verify sample-byte digests; MR 1 verifies the actual
saved inputs for this consumer. Models, fitted preprocessing, economic reporting and candidate promotion remain
their owning future MRs; MR 3 now supplies retained feature/label diagnostics.
Empirical source limitations remain unchanged; completion grants no deployment
or trading authority. Existing exploratory `inspect_eda` calls remain compatible
and are not automatically retained formal attempts.

### Versioned features and labels

**MR 3 — implemented (bounded software acceptance).** Add a versioned feature interface for a concrete diagnostic, signal,
factor study, rule or model. Inputs, formula, units, windows, cadence, warm-up and
missing/stale policy are explicit. Label generation is a separate capability with
outcome horizon, information interval and time of availability. Forward outcomes
cannot enter the earlier feature vector. No model is required for feature research.

Acceptance: hand-inspectable window/label examples, future-input perturbation,
missingness and repeated-execution parity; retain dataset/definition identities.
Notebook prototypes become shared operations when formal retained consumers need
them. Own formulas in `research/features/` and `research/labels/`; applications
compose them. Incremental execution is deferred unless a runtime consumer needs it.

Delivered by `TrailingReturn` / `WindowPolicy`, separate `ForwardReturn` labels,
and `FeatureStudy` through the existing `applications.explore.inspect_experiment`.
The [owning contract](../../src/research/features/README.md) defines the exact
last/first observed-price formula, units, schedule, warm-up and missing/stale
rules. Each feature reads its own cutoff; forward outcomes use an independent
fixed cutoff and frozen base. Both business-validity and exchange-event clocks
remain visible. `ExactRatio` preserves canonical rational returns. Definitions,
dataset/query identities, source/quality evidence, generated sample intervals,
failed attempts and consumed holdouts are retained. Models and fitting are inapplicable.

Prerequisites were verified on then-current main `2753efbb`: saved readers filter
availability before revision selection and retain coverage/membership/control
evidence; the attempt store retains incomplete outcomes and enforces family
holdout consumption. Before implementation, the affected prerequisite command
`uv run --frozen --no-editable pytest -q tests/unit/data/test_research_access.py tests/unit/research/test_experiments.py`
passed **14 tests, 1 integration case deselected, no skips**. The affected
development suite
`uv run --frozen --no-editable pytest -q -m 'not performance' tests/unit/research/test_features.py tests/unit/research/test_experiments.py tests/unit/data/test_research_access.py tests/integration/test_ingestion_workflow.py`
passed **25 tests, no skips or deselections**. Strict mypy passed all **10 selected
files**. Independent examples include 100.03 → 100.04 = 1/10003 and a forward
100.04 → 100.05 = 1/10004 under low Decimal precision. The installed two-instrument
consumer publishes evidenced synthetic revisions and reproduces exact results
in a fresh process. Final `TMPDIR=/private/tmp make check` passed **1,088
correctness/integration tests, 3 performance tests deselected, no skips**; all
required static/governance/security/dependency checks and isolated installed-wheel
smoke passed. Strict typing covered **255 files** and stub validation **1,548
modules**. The normal link check passed **32 docs**; explicit checks covered the
**5 changed component/example/test READMEs** outside its discovery scope. After
the final roadmap/status prose update, link and secret checks were renewed;
source and installed-artifact evidence remains valid. Development failures and
hosted CI status are retained in the PR. Integrating main `d639ee92` preserves
the subsequent MR 4 onward plans and changes only three documentation files;
source, tests, configuration and build inputs are unchanged. Local links and
secret scanning are renewed for that integration; hosted checks must pass on
the updated merged result before merge.

The initial diagnostic is materialized and limited to 1,024 decision/binding
rows. It conservatively marks scoped disconnects as missing, preserves unknown
archive availability, and rejects unsupported book/macro inputs. Its query
business clock is not an exchange-event resampling engine. Source coverage,
historical eligibility and real revision-availability evidence remain unproven
where already documented. Existing EDA/notebook and live-source paths are
unchanged; their prior evidence is not replaced by these synthetic diagnostics.
Fitted preprocessing/models, economic backtesting, runtime parity, large-study
optimization and additional formulas remain with their owning future consumers.
No empirical alpha, deployment or trading authority is claimed.

### Fitted preprocessing and model evaluation

**MR 4 — complete (bounded software and local ClearML acceptance).**
Extend the retained attempt core with ClearML tracking and model records
for configured analytical, calibrated statistical and learned models. Tracking is
required for supported formal workflows; fitting remains conditional on the model.
Keep the existing no-fit path usable. Own retained identities/evaluation records in
`research/experiments/`, model lifecycle in `research/models/`, and compose the
ClearML adapter in research applications. Retain the MR 2 store and its single-writer
contract; external task state cannot rewrite terminal evidence or holdout history.

Deliver tracking, model serialization and evaluation as separate bounded steps:

- Record each supported invocation automatically, including failed, aborted and
  rejected attempts. Map its attempt ID to a ClearML Task ID and keep semantic run
  identity distinct from execution identity. Retain resolved non-secret configuration,
  input/split/feature identities, code and environment, seeds and outcome. Configure
  automatic capture explicitly so it cannot replace the resolved manifest or upload
  secrets. Dashboard numeric values are projections of retained typed results.
- Distinguish model definition, configured/calibrated/fitted state, creation attempt
  and evaluation. Retain each newly created state, including usable rejected variants,
  with retrievable bytes, digest, signature, assumptions and numerical conventions.
  Link ClearML input/output model IDs to that version manifest. Failed calibration
  retains diagnostics without inventing a usable model. No-fit models have no invented
  training window; rule-only strategies need no model artifact.
- Fit preprocessing/models only on permitted rows and then-available labels. Retain
  fit/calibration window and availability cutoff where applicable. Inference loads
  accepted state without implicitly fitting. A calibration/refit or changed configured
  state creates a new recorded version; evaluations reference the exact version.
- Record evaluation dataset, window, fold/split, metric definition, units and outcome
  availability separately from construction. Distinguish calibration diagnostics,
  predictive/pricing metrics and later strategy economics. Evaluation failures and
  selection/rejection reasons remain searchable alongside successful results.

Keep local retained completion separate from ClearML publication completion. Persist
publication identity/receipts so a transport retry reconciles the existing task/model
before creating another. A publication failure is visible and recoverable without
refitting or repeating a holdout read. New executions create new attempts/tasks;
do not reset historical tasks or rely on SDK task reuse to represent a rerun.
ClearML defaults and mutable model records do not establish append-only history.

Use Pandera at the dataframe boundary of the selected model/evaluation consumer.
Validate column order/types, nullability and declared value constraints against the
MR 3 output contract; do not infer a new feature schema or replace domain validation.
Acceptance includes a valid frame and decisive malformed/missing-value cases without
silent coercion of financial precision or timestamps.

Add SHAP only for a selected prediction explanation question. Retain model version,
explainer/options, feature order, output scale and background/explained sample IDs.
Background selection respects the permitted fit/selection window. Verify a small
known model's contributions on the chosen output scale; record approximation limits.
Explanations do not establish causality or profitable tradability. Analytical models
can retain their native sensitivity/residual diagnostics without an unnecessary SHAP
wrapper.

Acceptance: a no-fit invocation and one selected mathematical/statistical model
construction/evaluation are traceable in ClearML from verified inputs to artifacts
and metrics. Fixed-input inference after reload agrees under a declared numerical
contract. Held-out/future perturbations cannot change fitted state; incompatible
feature order, units or state fails explicitly. Walk-forward decisions use only
artifacts available by that decision, never a final full-history fit. Exercise a
failed attempt and interrupted publication/reconciliation without duplicate retained
versions or erased outcomes. Verify backup/reopen of metadata and actual artifact
bytes. These checks establish the integration, not empirical model quality.

Implementation and evidence, 2026-09-20 (branch `codex/mr-04-model-evaluation`,
based on main `7b2ee466`):

- MR 2 retained attempts/splits and MR 3 feature/label consumers were inspected
  and exercised before implementation: **22 passed, 1 integration deselected**.
  Existing local no-fit calls and MR 28 ownership/command boundaries remain intact.
- [Model lifecycle](../../src/research/models/README.md) now owns bounded exact
  centered least squares and configured coefficients, explicit signatures, fitted
  cutoffs/rows, immutable state/version manifests, reload-only inference and
  walk-forward availability. Pandera validates the real MR 3 result adapter,
  including column order/dtypes, UTC clocks and explicit missingness without
  float conversion or imputation. Native residuals answer the selected engineering
  question; no SHAP explanation question was selected.
- [Experiments](../../src/research/experiments/README.md) owns separate predictive
  evaluations, immutable attachments, publication intent/failure/receipts and the
  explicit ClearML adapter. Existing `applications.explore` composes construction,
  reload and publication without another command. Tracked no-fit/model invocations
  retain completed, rejected, failed and abandoned outcomes; holdout consumption
  survives failed reads and publication retries. Historical tasks are never reset.
- The [local Docker server](../../configs/development/clearml/README.md) uses pinned
  ClearML Server 2.4.0, MongoDB, Redis and Elasticsearch images, loopback listeners,
  private local credentials and retained named volumes. There is no agent or shared
  service activation. SDK 2.1.12 and Pandera 0.33.1 were exercised on CPython 3.14.7
  / Darwin arm64; the server image uses Linux amd64 emulation.
- The installed `research/feature_study.py` consumer passed the actual server
  scenario: six attempts (no-fit, fitted, reload, rejected, failed calibration,
  abandonment), two usable model records, exact fresh-process prediction reload,
  and a lost local receipt after remote completion reconciled without another
  task/model or fit. The rejected model remains downloadable. Stopped volumes were
  backed up and restored into the separate `alpha-clearml-reopen` project;
  fresh SDK/HTTP reads verified all six outcomes, model associations, dashboard
  projections and actual artifact/model SHA-256 values. Fitted creation task
  `ac93bea587274e399cc44bfcd9177b95` and reload task
  `f637e64ee8034c7cb593b43c865efc58` share model
  `dab08e9e532e4900a43c0c136c0c51c4`. Local-only evidence is retained under
  `/private/tmp/alpha-model-integration-06` and
  `/private/tmp/alpha-clearml-backup-20260920`; it is not a durable shared evidence
  service and must be preserved before temporary-file cleanup.
- Focused final command `uv run --frozen --no-editable pytest -q
  tests/unit/research/test_models.py tests/unit/research/test_experiments.py
  tests/unit/research/test_features.py tests/unit/data/test_research_access.py`:
  **33 passed, 1 integration deselected, no skips**. Independent `y=2x+1` examples
  prove fitted centering, exact prediction/error, future/held-out isolation and
  incompatible-state rejection. The final tracked holdout regression additionally
  covers no-fit rejection before data access.
- Initial `UV_CACHE_DIR=/private/tmp/alpha-mr04-uv-cache TMPDIR=/private/tmp make check`
  passed locked resolution, Ruff, format, strict mypy (268 files), native stubtest
  (1,548 modules) and engineering rules, then **failed** dependency admission:
  `clearml lacks a digest-bound source distribution`. The remaining checks were
  run explicitly: final Ruff/format, mypy (268 files), native stubtest (1,548 modules),
  engineering rules, links (38 documents including component guides), Bandit and
  secret scans (371 governed paths after staging) passed.
  Initial complete `TMPDIR=/private/tmp make test`: **1,098 passed, 1 failed, 3 performance
  deselected, no skips** in 77.14 seconds. The sole failure is the repository's
  dependency-admission test reporting the same missing ClearML source distribution. Isolated `make wheel-smoke` passed the installed runtime and existing
  four commands, including the model consumer with explicitly unavailable transport.
  That mock does not stand in for the separate actual-server proof above.
- The exact 88-package external lock graph was audited with
  `pip-audit --no-deps --disable-pip -r <exact-locked-requirements> --format json`:
  **88 covered, zero vulnerability findings**. This is independent vulnerability
  evidence; the admission audit wrapper was blocked by the missing source at that stage.

Earlier live runs exposed SDK created-to-completed transitions, completed-task edit
refusal, literal model-name matching and stale input-model associations; those were
corrected and the retained uncertain outcomes reconciled before the successful full
scenario. One concurrent editable-install harness run was invalidated; the live
acceptance now uses a separate installed environment. A focused run accidentally
using an editable install failed the required wheel-inventory boundary and was
rerun with `--no-editable`. These are corrected integration/harness failures, not
measured service reliability. Final schema/holdout and immutable-state/evaluation-integrity guards are covered by focused
checks and renewed wheel smoke; the unchanged publication and Docker restore proof
is reused.

The initial dependency blocker above was resolved with explicit founder approval:
schema 5 now enforces [verified upstream source admission](../architecture/dependency-admission.md#verified-upstream-source-archives)
for the exact ClearML wheel. Actual archives are checked on every admission,
including cached runs; the complete 283-file runtime matches the pinned source.
Final local verification after that change:

- `uv run --frozen --no-editable pytest -q tests/engineering/test_dependency_admission.py
  tests/engineering/test_source_archives.py`: **70 passed**, no skips/deselections.
- `UV_CACHE_DIR=/private/tmp/alpha-mr04-uv-cache TMPDIR=/private/tmp make check`:
  **passed** end to end. Strict mypy checked 270 source files, native stubtest
  checked 1,548 modules, dependency admission/audit covered all 88 external
  packages with no unresolved findings, and the correctness/integration suite
  reported **1,131 passed, 3 performance deselected, no skips** in 75.80 seconds.
  The clean installed-wheel smoke passed all existing consumers, including model
  construction/reload and fresh-process attempt backup.
- Expanded local-link verification: **38 documents passed**. The source verifier
  separately reopened the cached actual archives and reported **283 matching
  runtime files**, demonstrating that a cache hit still performs the comparison.

The earlier live Docker/model proof remains valid: this completion changes only
source admission and documentation, not the runtime model/tracking behavior or
server topology. On implementation commit `9c949f08ab598abdd1f6e3871771d45be909f1da`,
[hosted CI run 35491535898](https://github.com/lixuanguang/alpha-research-lab-private/actions/runs/35491535898)
passed **Source validation**, **macOS wheel smoke**, and the **Authoritative
merged-result full lane**. MR 4 acceptance is met in
[PR 65](https://github.com/lixuanguang/alpha-research-lab-private/pull/65); subsequent
completion-document edits preserve this implementation evidence. Final staged
secret scanning covered **373 governed paths** with no findings.
QuantLib's pre-existing release block remains. The original attempts, stopped-volume
backup, matching installed runtime snapshot, credentials and validation logs have
been preserved under the original
checkout's ignored, owner-only `logs/clearml-acceptance/2026-09-20/` directory;
temporary paths in the earlier evidence remain historical identities.
Uncertain remote creation with no discoverable object deliberately stops for manual
reconciliation; it does not guess that a retry is safe. Larger models, automated
orchestration, shared-server qualification, economics and empirical research remain
with their owning MRs. No deployment or trading authority is granted.

## Economic research

### First economic backtest

**MR 5 — implemented; accepted with complete local validation.** Deliver a small integrated path: saved verified synthetic inputs → completed
observations → no-trade and fixed momentum rules → independent limits → positive-delay
fills → exact cash, positions, costs and NAV. Reuse the existing chronological
iterator. This proves economics without waiting for fitted features or live data.

Keep observation construction in `research/observations/`, decisions in `strategies/`,
fills/costs in `simulation/`, accounting in `accounting/` and limits in `risk/`.
`applications/backtest/` composes them. The strategy returns targets and cannot
bypass independent risk. Introduce only the frozen baseline's product mechanics.

Acceptance follows the [frozen economics](../research/p1-baseline.md) and
[clock/fill contract](../architecture/platform-design.md#replay-clocks-and-fill-fidelity):

- Decisions use completed windows; positive delay prevents same-observation fills.
  Equal-time source/control events precede expiry, fill, decision and mark phases.
  A later gap cannot retroactively cancel an already applied fill.
- Preserve all applicable scoped controls through instrument/field projection.
  Unrelated bindings remain isolated. Expiry is strict; pending reservations and
  at most the supported pending intents are explicit.
- Reconcile the independent hand ledger, no-trade case and gross-to-net attribution.
  Money follows explicit quantum/rounding; basis and returns use exact rational
  representation where division is not finite. Ambient Decimal context must not
  change results. Keep the hand oracle's half-up and baseline's half-even distinct.
- Reject unaffordable intents without changing cash/holdings. Expected risk rejection
  can belong to a completed run; invalid accounting or missing required valuation
  cannot. Terminal marking is not an invented liquidation.
- Whole, single-row and tied-group batches produce the same trace. Resume preserves
  consumer state, schedules, applied-fill identities and ledger alongside the source
  cursor. A cursor alone is not an economic checkpoint.

Add vectorbt as a separate, bounded research adapter after the reference economics
work. Supply verified observations, explicit signal timing, costs, sizing and capital
sharing assumptions; retain engine/version and supported execution scope with each
result. Compare one supported simple strategy to independently reconciled ledger
cases under matched assumptions. Expose timing, rounding and execution differences;
do not present a vectorized bar result as queue/fill fidelity or exact accounting.
No default same-bar fill may bypass the declared positive delay. Unsupported product
mechanics fail explicitly. ClearML integration uses MR 4; the reference economic
path remains usable without fitted models or an available tracking service.

Implementation, 2026-09-20, from main `ff4e1f4`:

- [Spot economics](../../src/simulation/README.md) now composes completed observations,
  fixed rules, independent limits, delayed fills and exact accounting under the named
  functional owners. The existing replay iterator owns phase order. Complete economic
  checkpoints retain schedules, reservations, applied fills, ledger and observations.
- The independent hand ledger, distinct fee ties, nonterminating basis/returns,
  no-trade, strict expiry, scoped controls, future isolation, batch/resume parity,
  unaffordable rejection and terminal holding cases have focused coverage. Installed
  acceptance publishes/reopens saved synthetic archive bytes and resumes a pending
  intent in a fresh process. No synthetic result establishes frozen-source acceptance.
- vectorbt 1.1.0 uses the pinned Numba backend and explicit positive-delay target orders.
  Exact order assumptions and approximate output remain separate from the reference
  ledger. Supported formal comparisons retain both artifacts through MR 4's attempt
  store and recoverable ClearML publication. Reference economics has no model or
  tracking-service prerequisite.
- Prerequisite source inspection and focused checks: **50 passed, 1 integration
  deselected**. Final focused command `.venv/bin/pytest -q tests/unit/accounting
  tests/unit/simulation tests/unit/data/test_event_stepping.py
  tests/engineering/test_source_layout.py`: **54 passed**, no skips/deselections.
- `TMPDIR=/private/tmp make check`: **passed**; Ruff and formatting (295 files),
  strict mypy (288 files), native stubtest (1,562 modules), ownership/clarity,
  architecture links, Bandit, admission (**131 external locked packages**),
  audit (**no unresolved vulnerabilities or coverage gaps**), secret scanning,
  **1,146 tests passed / 3 performance cases deselected**, and clean wheel installation
  outside the checkout. The installed economy publishes/reopens actual saved ZIP
  inputs, repeats the exact result, resumes pending state in a fresh process and
  runs the real vectorbt engine and failed-publication recovery consumer.
- Actual loopback ClearML SDK acceptance passed with attempt
  `56959ccc7305465f819d4cf4646e21c9`, task `fdd2f23bc12e4fcda16d3d607635d7d8`.
  Repeated publication returned the same receipt; downloaded exact and vectorbt
  artifacts matched retained SHA-256 values. Private local evidence is preserved
  under `logs/economic-acceptance/2026-09-20/` in the founder's original checkout;
  credentials are excluded.
- [PR 66's initial hosted run](https://github.com/lixuanguang/alpha-research-lab-private/actions/runs/35510740477)
  did not allocate a runner or execute any source steps. GitHub's failure annotation
  reports failed recent account payments or an insufficient spending limit.
  Source validation and the authoritative gate failed at scheduling; macOS smoke
  was skipped. The founder explicitly authorized merge after successful complete
  local validation when GitHub CI is unavailable. This exception applies to this
  PR; hosted Linux/macOS and merged-result execution remain unproven, and the
  repository's workflow/protection configuration is unchanged.
- Final staged secret scan: **397 governed paths passed**; final documentation
  links: **32 documents passed**. The original checkout remains unchanged apart
  from ignored private evidence; all implementation is isolated on
  `codex/mr-05-economic-backtest`.
- Earlier attempts remain disclosed: Plotly 7.1.0 failed vectorbt import, corrected
  by the exercised 6.3.1 pin; initial fixture/probe construction errors and a
  concurrent editable-environment mutation were corrected before final verification.
  The first full run had **1,144 passed / 2 failed / 3 deselected**: the old admission
  count and macOS's Unix socket temporary-path length. Updating the expected count
  and selecting a short temporary root produced the successful complete run above.

Notebook integration, 2026-09-20: the existing [QR workflow](../../examples/research-foundations.ipynb)
now executes one saved synthetic trade study through retained feature/label attempts,
train-only and configured model comparison, exact model reload, no-trade/momentum
economics, complete checkpoint resume and bounded vectorbt comparison. Fitted models
and fixed trading rules remain separate consumers of that input. The
[developer workflow](../../examples/infrastructure-diagnostics.ipynb) runs the installed
feature/model and economic consumers and can reopen the QR's actual retained directory
for exact model evaluation and whole/resumed economic reproduction. Both use existing
public libraries and applications; no runtime, runner or dependency changes were needed.

Fresh-kernel QR execution passed **17 code cells**; developer execution with the saved
QR handoff passed **15 code cells**. Four notebooks passed Ruff/format checks; local
links passed for both guides and all four notebook narratives. Real tracking was
explicitly skipped in favor of a named offline publication-failure fixture, with
completed local results and pending outboxes retained. The optional saved-capture
diagnostic was skipped. Live executable cells are unchanged and were not rerun;
their updated prose identifies the trade-input prerequisite without upgrading book
data to economic evidence. Historical live outputs were cleared instead of claiming
a new live run. Failed notebook attempts (overlapping sample information intervals,
then an unsupported generic decoder call in the handoff) remain retained alongside
the corrected successful runs under ignored `examples/runs/`. The
[operations guide](../../examples/notebook-operations.md#retained-research-and-economic-studies)
owns exact commands, saved artifacts, optional tracking and the QR-to-QD selector.
`TMPDIR=/private/tmp make check` also passed: **1,146 tests / 3 performance cases
deselected**, strict source/dependency/security checks and isolated installed-wheel
verification. Final source matches the executed notebook code; the QR notebook's
execution metadata discloses a subsequent retention-wording clarification only.
The successful and failed artifacts were preserved in the original checkout's
ignored `examples/runs/`, with logs under `logs/notebook-acceptance/2026-09-20/`.

Remaining boundaries: MR 6 configured command, atomic reports and pipelines; MR 8
actual source/eligibility/coverage and empirical baseline acceptance; MR 11 release
qualification. vectorbt excludes gaps, missing observations, available revision
changes and contingent reuse of sale proceeds. QuantLib's existing development-only
release restriction remains. No deployment or trading authority is granted.

### Configured runs and durable reports

**MR 6.** Expose the economic path through validated configuration and one installed
command, reusing the attempt core and explicit data selection. Retain immutable
input/configuration/component identities, event/decision/fill trace and a readable
costed report. Write results atomically before recording successful completion.
A failed attempt remains a failed attempt even if some output files exist.

Acceptance: run from an isolated installed artifact outside the checkout; repeat
and resume reproduce declared results; malformed configuration, missing bytes,
interrupted report publication and incompatible checkpoints fail visibly. Compare
net return, turnover, drawdown and exposure only where the selected experiment's
observations support them. Reports must expose invalid/missing periods and limitations.

Deliver the report, orchestration and data-storage integrations as separate slices:

- **QuantStats reports.** Feed the platform's retained net return series and an
  explicitly aligned benchmark to the reporting adapter. Retain return convention,
  cadence, annualization, risk-free assumption, timezone and missing-period policy.
  Period win/loss statistics must not be labeled trade statistics. Check selected
  return/drawdown results against a small independent example, and retain the HTML
  report and inputs as ClearML artifacts. Reporting cannot recalculate or replace
  the exact economic ledger; do not fetch an unpinned benchmark implicitly.
- **ClearML pipelines and agents.** Compose installed acquisition/selection,
  features, applicable model construction, evaluation/backtest and report entrypoints.
  Pipeline/step IDs reference retained attempt IDs and exact upstream outputs.
  Use a local worker first and serialize workflows sharing MR 2's single-writer store.
  Retain the actual resolved configuration after any UI override; changed parameters
  produce a new semantic identity. Launch the pinned environment/artifact rather than
  treating auto-detected requirements as a reproducible dependency lock. Initially
  disable step caching. A later cache must include immutable data/model/split/config/
  code identities and preserve holdout access records even on a cache hit. A fresh
  execution gets a fresh attempt/task; retrying a publication resumes its existing
  mapping. Exercise failed-step recovery without erasing the first failure or falsely
  completing dependent work. Local CLI and pipeline runs must agree on results.
- **lakeFS dataset versions.** Wrap storage access for one existing published dataset
  and its derived feature snapshot, retaining repository commit ID, object paths and
  the current manifests/digests in ClearML. Resolve mutable branch/tag names before
  execution. Preserve existing reader validation and availability semantics; a storage
  commit time is not a market observation's knowledge time. Prove that a correction
  on a new data branch cannot alter a pinned historical run, and that retained bytes
  remain retrievable after backup/restore and configured retention/garbage collection.
  Keep model/report artifact storage separate where simpler; no automatic second
  dataset catalog is required in ClearML Data.

**Status: complete for the bounded local research scope, 2026-09-20.**
Prerequisite verification reopened actual MR 1 dataset readers, MR 2 attempts/splits,
MR 3 features, MR 4 model/publication boundaries and MR 5 economics/accounting;
37 focused tests passed, one deselected. The selected economic rule is explicitly
no-fit validation, so neither model construction nor final holdout access is
applicable. Source acquisition remains explicit upstream work; this pipeline
selects a previously published dataset instead of silently downloading data.

`applications.backtest` owns the single installed `alpha-backtest` command with
run/prepare, checkpoint/export, publication retry and pipeline/worker actions.
`research.experiments` owns `BacktestRun`, reporting assumptions, durable result
manifests and ClearML pipeline metadata. `market_data.storage` owns immutable
lakeFS resolution and bounded materialization. Existing simulation, accounting,
observation, risk and source-clock contracts remain unchanged. Library APIs remain
curated, libraries have no command and applications do not import sibling workflows.
See the [configured behavior and invocation contract](../../src/research/experiments/README.md#configured-economics-reports-and-serial-pipelines),
[local worker](../../configs/development/clearml/README.md#serial-installed-research-worker)
and [storage/restore contract](../../configs/development/lakefs/README.md).

Validation on CPython 3.14.7 / Darwin arm64:

- `uv run --frozen --no-editable pytest -q tests/unit/simulation/test_economic_replay.py`:
  **12 passed**. Independent `+10%, -20%, +25%` returns give `+10%` compounded
  return and `-20%` drawdown; a first-period loss includes initial capital in the peak.
  Missing valuation periods and explicit benchmark alignment are checked.
- The complete local lane through `TMPDIR=/private/tmp
  PYTEST_ADDOPTS=--basetemp=/private/tmp/alpha-mr06-final-pytest make check` passed
  **1,148 tests, three performance cases deselected**, with no test skips.
  Type checking, native/pandas stub conformance, admission of 146 dependencies,
  vulnerability coverage, architecture, security and secret checks passed.
  Its wheel smoke also passed the isolated, governance-free, hash-locked installed
  wheel. Its 102 installed distributions were compatible.
  The first lane caught stale dependency expectations and a macOS temporary socket
  path limit; the first wheel run caught an incorrect test expectation for the
  existing reader's validation exit code. All were corrected without relaxing gates.
- The installed `economic_workflow.py` consumer, run outside the checkout, passed
  full/repeat/checkpoint/fresh-process resume parity, malformed configuration,
  missing bytes, incompatible checkpoint and interruption at the actual HTML atomic
  rename. Partial artifacts never became a successful result. Actual ClearML task
  `4945108a43554f4b8e5b18f0394be0d2` returned identical HTML, report inputs and ledger bytes.
- The actual `pipeline_workflow.py` consumer passed CLI/agent result-manifest parity,
  failed selection with no dependent completion, fresh recovery preserving failure
  `42d0ac329d2941b08803ec7e9693555b`, and a server-resolved rule override producing new
  identity/economics in task `56bcaaf8c4894bee994121eff496a48f`. Six distinct attempts
  were retained. One dedicated local agent ran steps serially; caching/retries were off.
  The independently audited 12-package worker graph has no unresolved findings;
  patched Requests/Setuptools overrides and their upstream metadata limitation are
  documented in its guide.
- Combined versioned CLI/pipeline execution passed exact result parity and downloaded
  identical `dataset-version` artifacts from three ClearML attempt tasks. Controller
  `c554d2e576084102aa613d68ad1faea7` consumed the restored pinned local version
  `d7f4bed16b1c68fe9cd350b3439fbddcf772a8ba5780ef36237f42660b5b7695`.
- The actual lakeFS/S3 consumer resolved branch/tag identities and rejected corrected
  feature bytes against the original inventory. Separate metadata/object volume backups
  restored version `7c30643adad6827d90b2afabb56ac129e36b9c17e030abc8a3998dc059dd8c52`.
  Spark mark/sweep `fufg7npn6p5c73cha9tg` completed successfully, deleted one expired
  disposable object (subsequent HTTP 410), and every pinned source/snapshot/feature
  object reopened unchanged afterward. Test policy: default retention zero days,
  retained branch 365 days, positive one-second synthetic GC age. Both SDK families
  required by actual deletion are pinned in the fixture; no no-op sweep is substituted.

Retained local acceptance output, logs, wheel, locks, manifests and private service
backups are under ignored `logs/configured-research/2026-09-20/` in the founder's
primary checkout. Credentials remain separate and private. For
[PR 68](https://github.com/lixuanguang/alpha-research-lab-private/pull/68), the founder
explicitly authorized merge on the complete local validation because GitHub CI
credits were exhausted; hosted Linux/macOS execution remains unproven for this MR.
Local service containers were removed after acceptance; named volumes and evidence
remain available for reproduction.

Remaining boundaries: empirical frozen-source acceptance is MR 8; extension/
comparison and learned backtest consumers remain conditional future work. Reports
measure sampled closes, not intraperiod extrema, capacity or real execution.
The local worker overrides need requalification on agent upgrades. Shared services,
long-lived storage/deletion operation and container security qualification remain
MR 11/20 work. QuantLib's existing development-only release restriction remains.
Implementation adds no deployment or trading authority. Revert owners, command,
package/lock/admission and tests together; preserve attempts, storage versions,
matching wheels and backups rather than rewriting historical outcomes.

### Research comparison and extension

**MR 7.** Let QRs register compatible features, estimators and rules through narrow
public interfaces and configuration. Exercise a second genuinely distinct research
consumer and compare declared attempts with the same split/report semantics.
Shared runners must not acquire model-specific branches or copied notebook logic.

Acceptance: EDA, offline replay and formal backtest retain the same selection
identity; one compatible extension works without runner edits; two instances can
share immutable inputs while their mutable state, random streams, pending intents
and outputs remain isolated. Retain selection/rejection reasons and holdout use.
The maintained QR guide and activity notebook demonstrate this path with applicable
features/models; a rule-only example must remain possible.

Extend that comparison workflow in independently reviewable slices, with the existing
CLI/report path remaining the reference consumer:

- **Factor diagnostics with Alphalens Reloaded.** Adapt MR 3 factor/label outputs
  for one declared cross-sectional study. Retain eligible universe, factor direction,
  forward horizon, price convention, groups, quantile rules and dropped observations.
  Publish IC, quantile-return and turnover diagnostics plus report artifacts to ClearML.
  Verify a small independently calculated factor/forward-return example and a boundary
  case with unavailable or missing observations. Future labels are evaluation inputs,
  never contemporaneous features. Factor tear sheets do not substitute for costed
  executable strategy results. Mark cross-sectional statistics inapplicable when the
  sample lacks the required cross-section.
- **Parameter comparisons with vectorbt and Optuna.** Track each evaluated parameter
  combination/trial, including pruned, failed and rejected outcomes. Optuna supplies
  sampling/pruning for a declared objective; ClearML supplies task execution and the
  experiment UI. Avoid two independent search controllers for one study. Persist
  study/sampler state and map trial IDs to retained attempts/tasks. Fix the search
  space, budget, objective, splits and seed policy; do not optimize on the final
  holdout. Verify resume retains trial history and that an interrupted/pruned trial
  cannot appear as a successful full evaluation. Re-evaluate selected vectorbt
  candidates through the qualified economic path before promotion.
- **Feast offline retrieval.** Register a versioned view of MR 3 features for a second
  consumer, with explicit entity keys, types, source snapshot, timestamps and TTL.
  Pin feature definitions/registry state and resolved source versions in each run.
  Compare retrieved values with the existing causal reader on a fixture containing
  late corrections, missing entities and TTL expiry. Feast's default event-time join
  is insufficient for delayed availability: use the pinned backend's supported
  created-time filtering with truthful, non-null availability timestamps, or an
  explicitly eligibility-filtered immutable source. Prove the chosen path handles
  revisions; do not silently fall back when a backend cannot enforce the contract.
- **Research access and interface.** Add DuckDB SQL and Polars transformations over
  verified, permitted snapshots/results for a bounded comparison. Preserve identities,
  units, timestamps, null semantics and declared precision across dataframe conversion;
  compare results to the reference path. Add a marimo example using these same public
  APIs alongside the maintained notebook. An explicit run action creates a retained
  formal attempt; reactive display updates must not silently refit or consume a
  holdout. Fresh-process script execution reproduces the example's retained result.
- **Offline reference/current diagnostics.** Compare explicitly declared windows
  using retained features/predictions and labels available by the declared evaluation
  cutoff. Retain schema, units, lineage, exclusions, metric/test definitions, frozen
  thresholds, computation versions and reports. Publish through the existing ClearML
  outbox and artifact reconciliation. Verify shift/control, delayed labels,
  predictive inapplicability, untouched holdouts and failure/recovery with an
  installed consumer and downloaded report hashes. The
  [accepted tool amendment](#diagnostic-tool-requirement-amendment) makes Evidently
  optional; the diagnostic outcome and verification remain mandatory. Drift grants
  no automatic retraining, promotion, deployment or trading authority.
- **skfolio allocation research, conditional.** For a selected multi-asset portfolio,
  fit estimators on permitted history and retain objectives, constraints, asset order,
  covariance/return assumptions and solver settings/status. Use the repository's
  temporal split rules. Check feasibility and a simple known allocation, retain
  infeasible outcomes, and evaluate turnover/costs in the shared economic runner.
  Proposed weights cannot bypass independent risk or MR 14's account allocation.

All comparison artifacts resolve model versions, dataset/feature snapshots, metric
definitions, windows and attempt IDs through ClearML and the retained manifests.
Large trial grids may be stored as indexed artifacts, but every evaluated variant
must remain individually attributable; retaining only the winning curve is insufficient.

#### Diagnostic tool requirement amendment

Accepted by explicit founder instruction on **2026-09-21**: replace the mandatory
Evidently SDK integration with **offline reference/current diagnostics implemented
by the existing research owners using admitted computation dependencies**. This
supersedes the named-tool requirement in the original MR 7 acceptance and its
completion request. Evidently may be added only after its full dependency closure
passes admission; it is no longer a prerequisite for completing MR 7. The
[rejected dependency evidence](../architecture/dependency-admission.md#evidently-prerequisite-recheck)
remains valid for the reviewed candidates.

The following outcomes remain binding:

- Compare explicit reference/current windows from verified retained feature and
  prediction results. Retain source snapshots, upstream attempts, applicable model
  versions, windows, schema, units and availability policy. Admit delayed labels
  only when available at the declared evaluation cutoff; preserve missing and
  excluded observations and reasons.
- Retain the actual computation package versions, metric/test definitions, frozen
  thresholds and applicability rules, numerical results and reproducible report
  inputs. Use an honestly named repository report; do not claim Evidently output
  when Evidently did not generate it. Missing labels or an inapplicable predictive
  metric must remain explicit, without suppressing applicable feature diagnostics.
- Publish the generated report through existing ClearML publication and artifact
  reconciliation. Preserve failed attempts and publication retries; retry saved
  report bytes without rerunning research or consuming a holdout. Drift remains
  diagnostic and cannot trigger retraining, promotion, deployment or trading.
- Keep reusable validation, calculations and state transitions in cohesive
  `research.experiments` classes, composed by existing application workflows.
  Preserve MR 28 public APIs and entrypoint boundaries. Add a useful consumer to
  the QR guide and an existing maintained notebook/interface.
- Verify a known distribution shift and unchanged control, missing labels and
  later availability, explicit predictive inapplicability, preserved temporal
  splits and untouched holdouts, retained failure/recovery, and reproducible
  inputs/results. Exercise the selected computation library from an installed
  artifact outside the checkout, publish to actual local ClearML, and download
  the report artifacts to verify retained hashes. Renew affected proofs, run
  `make check` and applicable installed consumers, and inspect hosted CI.

The first implementation should reuse the admitted numerical stack where suitable;
SciPy **1.18.1** is already in the reviewed core lock. This amendment is not SDK
verification or admission of a new graph: any direct dependency use must be
declared in owning metadata and its complete closure verified under current policy.
CPython **3.14.7**, pandas **3.0.5**, vulnerability rules and QuantLib's release
restriction remain unchanged. SHAP/skfolio remain conditional; MR 8 empirical
acceptance, online serving, account allocation and shared-service qualification
remain outside MR 7.

At amendment time, diagnostic implementation and acceptance remained open; changing
the tool choice did not satisfy the requirements or authorize a merge. The
[completed implementation and acceptance](#offline-diagnostic-completion-and-final-reconciliation)
below supplies the owned consumer, installed computation and ClearML proofs and
resolves the local smoke timeout. Hosted scheduling remains an external merge
boundary. Reversing this amendment restores the Evidently-specific requirement
while retaining this decision and historical evidence.

Historical PR 69 delivery status (2026-09-21): **partial; acceptance was not complete.** The owning
libraries now expose compatible feature/estimator/rule registration and the
existing backtest application consumes a distinct completed-price reversal rule.
`research.experiments` owns retained Alphalens reports and bounded Optuna grid
comparisons; `research.features` owns the offline feature contract and
`research.exploration` owns bounded DuckDB/Polars analysis. Applications compose
these APIs and preserve the single command entry per workflow.

The prerequisite audit checked actual temporal/attempt, feature/model and exact
economic implementations, with **37 passed, 1 deselected** in the focused
prerequisite lane. The deselected performance case is not behavioral evidence.
No merged-PR count was used as a substitute for that audit. The core interpreter
and dataframe pins remain CPython **3.14.7** and pandas **3.0.5**.

Under the original tool requirement, the Evidently slice was blocked by dependency
admission. The compatible resolver candidate, Evidently 0.4.36, requires NLTK;
the latest 0.7.23 release also
requires it unconditionally. NLTK 3.10.3 is the latest published release and has
the unresolved [GHSA-8mgp-746c-j5xp / CVE-2026-81726](https://github.com/advisories/GHSA-8mgp-746c-j5xp)
finding (also PYSEC-2026-3740), with no patched release listed on this date.
The repository blocks unresolved vulnerabilities and has no waiver mechanism.
Evidently and its unused transitive graph were removed; no substitute adapter or
unexecuted diagnostic scaffold is claimed. The
[subsequent tool amendment](#diagnostic-tool-requirement-amendment) permits an
admitted implementation without Evidently; the missing diagnostic consumer and
its verification are still required before completing MR 7.

Feast 0.66.0 requires pandas below 3 and therefore uses an explicitly separate
local research-worker lock. It cannot downgrade the runtime's dataframe pin.
SHAP and skfolio remain conditional: this delivery selects no explanation-dependent
model or multi-asset allocation consumer. MR 8 empirical acceptance, MR 9 online
retrieval and MR 14 independent account allocation are not expanded here.

Verified delivery evidence, 2026-09-21:

- `TMPDIR=/private/tmp PYTEST_ADDOPTS=--basetemp=/private/tmp/research-final-pytest
  make check`: **passed**, with **1,190 passed / 3 performance cases deselected /
  no skips** in 119.29 seconds. Ruff/format covered 336 files, strict mypy checked
  329 source files, native stubtest checked 1,562 modules, and ownership, links,
  Bandit and secret checks passed. Core admission/audit covered **179 external
  locked packages** with no unresolved vulnerability or coverage finding.
- Clean wheel smoke installed **135 runtime packages** outside the checkout and
  exercised public APIs, all six commands, exact economics, the actual vectorbt
  engine, comparison resume and historical snapshots. The separately locked Feast
  worker audit covered **64 external locked packages** with no findings; its
  installed platform selects 63 packages. These counts describe different graphs.
- Independent factor cases verify IC +1/-1, demeaned quantile returns -0.05/+0.05,
  daily membership turnover 1.0, pending labels, ties and an inapplicable single
  asset. Intraday-only turnover remains unavailable when Alphalens' daily resample
  lacks prior daily membership; it is never relabeled as intraday turnover.
- Actual local ClearML feature/factor and economic consumers passed publication
  and downloaded-artifact hash checks. Two fresh processes retain the same
  comparison history: momentum exact net return -0.000007235 and reversal
  0.00000188599. Every trial retains its own configuration, objective and task;
  no selected winner replaces the other outcomes.
- The final installed Feast 0.66.0 consumer created its actual registry and
  Parquet source from verified MR 3 output. Baseline retrieval matched two exact
  values and one explicit missing entity; a delayed correction became `9/10`
  only after `2024-06-01T00:00:10.250000Z`, and the one-second TTL case expired.
  Formal attempt `b3d1b68c75d0423dba90182d7abd0aa0` published to ClearML task
  `1c58dfe1bf194ad4b5322a384000af3b`; all five downloaded artifact hashes matched.
  The retained request pins both registry and source bytes. The current SDK view
  has no registered revision-ID field; immutable source/registry digests and
  explicit created-time filtering prove the exercised revision boundary.


- The final installed local ClearML pipeline passed exact initial-run parity,
  missing-input failure/downstream suppression, recovery preserving the failed
  history, and a real server-side no-trade configuration override. Its comparison
  step executed attempts `821a9413129c41bc8781ed69c6a3e6e5` and
  `cbedc28d66b942878b5d4618045a85ee`, with actual UI variant/rule/objective metadata.
  Resuming the same output root preserved both histories byte for byte.
- marimo's read-only preview created no attempt; two explicit fresh-process runs
  produced equal report manifests and distinct completed attempts with actual
  ClearML publication. The maintained QR notebook completed **18/18 code cells**
  in a fresh kernel, attempt `dfd2e123-d034-4e5d-8c6d-a012fc764dcc`, source digest
  `00c81e8ec984feefb009187080a0b08030f898ee757bc7957abee114089fc82d`.
  It retained both rule trials and completed synthetic model/economic handoff.
  Notebook tracking deliberately used its named offline failure fixture and
  retained pending outboxes; actual service evidence comes from the installed
  consumers above. Live notebooks were unchanged and were not rerun.

Successful and failed local output, logs, notebook attempts, locks and matching
wheels are preserved under the original checkout's ignored, owner-only
`logs/research-comparison-acceptance/2026-09-21/` directory. Credentials and SDK
caches are excluded. The task's local agent and service containers were stopped;
named service volumes remain. The original checkout's tracked files are unchanged.

[PR 69](https://github.com/lixuanguang/alpha-research-lab-private/pull/69)
contains this partial delivery. Its [initial hosted CI run](https://github.com/lixuanguang/alpha-research-lab-private/actions/runs/35561256394)
on implementation commit `e157d270ad878aa6d550ca3d847670e47175a38c` did not
allocate runners or execute source steps. GitHub annotations cite recent account
payment failure or an insufficient spending limit: source validation and the
authoritative merged-result job failed at scheduling; macOS smoke was skipped.
The complete local lane above passed, but hosted Linux/macOS and merged-result
execution remain unproven. On 2026-09-21, after the complete local validation
and these limitations were reported, the founder explicitly instructed merging
this partial delivery to main. This authorization applies to PR 69; MR 7 remains
incomplete until the diagnostic acceptance slice is delivered under the
[current tool requirement](#diagnostic-tool-requirement-amendment). The repository's
workflow/protection configuration is unchanged, and no deployment or trading
authority is granted.

Final review also preserved publication compatibility for existing experiments
whose free-form parameters contain `search` without a trial. The added regression
and comparison tests passed **15 tests / 1 performance case deselected**, followed
by the complete final lane above and a fresh wheel smoke. This one-condition
publication guard does not change the exercised service adapters; their actual
service evidence is reused, and both matching wheel versions are retained.
Final staged secret scanning passed **447 governed paths**; local links passed
for the standard **32 documents** and **7 additional owning guides**.

Development failures remain retained: initial typing stubs, a cross-directory
test-helper import, and security lint were corrected before the complete passing
lane. Earlier notebook and pipeline executions overlapped a package reinstall and
failed while installed modules were absent; the final service/notebook phases run
serially with installation. Those failures are harness evidence, not service
reliability measurements. Performance tests, empirical source acceptance and shared
service qualification are not claimed. The comparison adapter currently consumes
local pinned snapshots; remote lakeFS materialization is explicitly unsupported,
while MR 6's configured versioned workflow remains intact.

Implementation
grants no deployment or trading authority; the existing QuantLib release restriction
remains. Revert the owners, consumers, examples and dependency/admission changes
together. Preserve attempt stores, Optuna journals, source/registry versions,
matching installed wheels and service evidence to reproduce historical results.

#### Completion attempt and acceptance reconciliation

Historical prerequisite attempt, 2026-09-21, before the tool amendment: rechecked
from latest main
`3ebd6a4bdb5722117e66dca830af28ee140b9f52` in isolated branch
`codex/mr-07-completion`. **MR 7 remains incomplete.** The
[dependency prerequisite review](../architecture/dependency-admission.md#evidently-prerequisite-recheck)
retains fresh wheel metadata, upstream advisories and resolver/audit evidence:
Evidently 0.4.36 resolves with all existing pins but its complete 216-package
external graph fails the NLTK advisory; 0.7.23 additionally conflicts with the
core Plotly pin. Neither candidate is admitted. A separate worker cannot resolve
the vulnerability. No replacement diagnostic or unexecuted consumer was added.

The existing source, application composition, tests and retained service results
were inspected directly. All **930** files in the prior acceptance inventory
still match their hashes. All **196** runtime files in the retained final wheel
match this checkout's source; wheel SHA-256 is
`c24bbdd67b4b893c89752d2f3d974b6d383374d2fd8ecddf666ae0fe212f14d1`.
These checks justify reusing the unchanged implementation's prior service and
notebook evidence summarized below; they do not claim a fresh ClearML or Feast
service run or override the fresh smoke failure recorded after the table.
The table reflects the [amended acceptance](#diagnostic-tool-requirement-amendment);
the historical verification results below retain their original scope.

| Mandatory outcome | Implementation and inspected evidence | Acceptance status |
| --- | --- | --- |
| Shared selection, distinct consumer and isolated instances | `EconomicComparison`, `RuleRegistry`, completed-price reversal; [comparison tests](../../tests/unit/simulation/test_comparison.py) and [extension tests](../../tests/unit/simulation/test_extensions.py) preserve selection, separate checkpoints/pending state and exact results. Rules are deterministic; the Optuna sampler has a declared retained seed/journal. | Delivered in the bounded synthetic scope |
| Compatible extension without runner edits; guide and rule-only notebook | Feature/estimator registries and injected rule factories retain public owner boundaries; [QR guide](../../examples/README.md), [activity notebook](../../examples/research-foundations.ipynb) and the retained 18/18-cell run exercise the path. | Delivered; no arbitrary new schema or empirical model claim |
| Full parameter trial history, frozen choices, resume and holdout discipline | `ParameterComparison` and `EconomicComparison` retain accepted/pruned/rejected/failed/interrupted trials, fixed budget/split and exact ledger evaluation; installed comparison and serial pipeline histories remain in the prior archive. | Delivered; validation only, no promotion |
| Alphalens factor diagnostics and ClearML reports | `AlphalensDiagnostics` and `compare_factors`; [independent numerical tests](../../tests/unit/research/test_diagnostics.py) cover IC, quantile returns, turnover, unavailable labels and inapplicability. Installed feature-consumer evidence includes actual artifact-download hashes. | Delivered; intraday turnover limitation retained |
| Feast offline availability, revision, missing-entity and TTL parity | `OfflineFeatureAccess`, `OfflineFeatureBridge` and `compare_offline_features`; retained final SDK report pins registry/source and five ClearML artifacts for task `1c58dfe1bf194ad4b5322a384000af3b`. | Delivered; separate audited worker, offline only |
| DuckDB/Polars precision and marimo explicit execution | `BoundedFeatureAnalysis` and [analysis tests](../../tests/unit/research/test_analysis.py); marimo's verified validation preview is separate from its formal run action. Prior fresh-process equal-report evidence is retained. | Delivered; no reactive fit or holdout read |
| Offline reference/current diagnostics and actual report publication | The founder-authorized amendment permits an admitted computation library instead of Evidently. The consumer, declared windows/schema/units/availability, feature/prediction/model lineage, frozen metric/test thresholds, exclusions, shift/control, delayed-label and predictive-inapplicability cases, failure/recovery and downloaded ClearML report hashes remain unimplemented/unproven. | **Open; mandatory capability and acceptance unmet** |
| Conditional SHAP and skfolio | No selected explanation-dependent model or multi-asset allocation consumer. | Inapplicable under the existing conditional criteria |

Historical local verification before the tool amendment:

- `UV_CACHE_DIR=/private/tmp/alpha-completion-uv-cache TMPDIR=/private/tmp
  PYTEST_ADDOPTS=--basetemp=/private/tmp/alpha-completion-pytest make check`:
  **failed, exit 2**, at installed-wheel smoke. All preceding checks passed:
  locked resolution, Ruff/format (336 files), strict mypy (329 files), native
  stubtest (1,562 modules), engineering rules, 179-package admission/audit with
  no findings or coverage gaps, links, Bandit, secrets (447 paths), and
  **1,190 tests passed / 3 performance deselected / no skips** in 176.96 seconds.
- The clean wheel installed 135 runtime packages and passed `uv pip check`.
  Its bytes equal the retained final wheel above. The existing installed
  `feature_study.py` consumer exceeded its 60-second timeout; later economic
  and recovery consumers in that smoke sequence were not reached.
- A copied diagnostic consumer in a separate installed environment completed
  feature/factor/model and fresh-process assertions. Added stack dumps showed
  time in dependency compilation/native imports; the sandboxed diagnostic also
  used a temporary Matplotlib cache. This is diagnosis, not standard smoke
  acceptance. The focused retry, `UV_CACHE_DIR=/private/tmp/alpha-completion-uv-cache
  UV_COMPILE_BYTECODE=1 TMPDIR=/private/tmp make wheel-smoke`, also **failed,
  exit 2**, at the same 60-second boundary. Install-time compilation did not
  resolve it. The cause of the remaining timeout is unproven; assertions and
  timeouts were not weakened, and the complete lane is not reported as passing.
- Final local-link checks explicitly include the QR guide: **33 documents
  passed**. New source tests and live service/notebook runs are unnecessary for
  these documentation-only edits; the required Evidently SDK, shift/control,
  delayed-label, failure/recovery and real ClearML report checks remain blocked,
  not skipped tests or substituted Alphalens results.

Both smoke failures, diagnostic output, the matching wheel and dependency
evidence are preserved under the primary checkout's ignored, owner-only
`logs/research-completion-prerequisite/2026-09-21/` directory. The original
acceptance archive and unrelated running notebook environments are preserved.

The reusable attempt/split and ClearML outbox implementations retain failures and
reconcile saved artifacts without rerunning research. That existing behavior is
not evidence of the missing reference/current diagnostic integration. This
prerequisite and requirement-amendment change affects only
documentation/evidence; source, dependency locks/admission rules, commands,
notebook cells and QuantLib's release restriction are unchanged. The next work
is the owned consumer and installed computation/local ClearML acceptance defined
in the amendment, with the existing validation failures still unresolved. MR 8,
online serving, allocation, shared-service qualification and trading remain out
of scope. Reversal is to revert these documentation updates while preserving
both historical evidence archives.

The tool amendment was checked with the existing local-link validator over
**33 documents**, including the QR guide, and
`uv run --frozen --no-sync alpha-governance-ci scan-secrets --all` over
**447 governed paths**; both passed. `git diff --check` passed. Source, tests,
notebook code, package metadata and locks are unchanged, so this documentation
amendment does not rerun research or the full suite. The earlier failed smoke
and hosted scheduling evidence remain applicable validation limitations.

#### Offline diagnostic completion and final reconciliation

Final local acceptance, 2026-09-21, from main
`507b1c4de00ef9ac51a39412185c88ecaab564f7` in isolated branch
`codex/mr-07-diagnostics`: **MR 7 acceptance is complete under the amended tool
requirement, within the declared local synthetic scope.** This does not complete
MR 8, qualify shared services, authorize a merge, or establish hosted CI success.
The historical partial deliveries and failed checks above retain their original
meaning; this record supersedes their outstanding local implementation boundaries.

`WindowDiagnosticStudy`, `WindowDiagnostics` and `WindowDiagnosticRun` own frozen
policy, calculations, lineage checks and terminal state transitions in
`research.experiments`. The existing `applications.explore.compare_windows`
workflow composes them with the existing attempt store, ClearML publication and
artifact reconciliation. There is no new command or runner. The
[QR consumer](../../examples/README.md#compare-reference-and-current-windows),
[component contract](../../src/research/experiments/README.md#offline-window-diagnostics)
and existing [marimo interface](../../examples/research-comparison.py) explain the
explicit saved request and run action.

The report retains pinned source bytes and histories, snapshot/query identities,
feature/label definitions, model manifests and state, original splits, windows,
cutoff, units, availability and applicability rules, thresholds, exact inputs,
exclusions, actual computation versions and numerical results. SciPy **1.18.1**
performs the two-sided exact KS calculation per instrument; predictive MSE uses
exact rational arithmetic only for labels available at the declared cutoff.
These descriptive diagnostics neither establish statistical independence nor
correct multiple comparisons. Insufficient samples and inapplicable metrics stay
explicit. No result can retrain, promote, deploy or trade.

| Mandatory outcome | Final implementation and evidence | Acceptance |
| --- | --- | --- |
| Shared selection, distinct consumer, isolated state and compatible extensions | Existing registry/comparison owners inspected directly; full source suite and final installed economics/pipeline exercise both rules, exact costed results, independent histories and resume. | Complete in supported synthetic scope |
| Retained trials, frozen configuration, temporal boundaries and untouched holdouts | Comparison tests retain accepted/pruned/rejected/failed/interrupted outcomes; actual installed pipeline proves original failure/downstream suppression, recovery and real server override. Repeated comparison preserves trial histories. New diagnostic source/history assertions reject holdout use and preserve source splits. | Complete; no empirical or promotion claim |
| Useful guide, rule-only path and maintained interface | QR guide and existing feature consumer extended; marimo preview creates zero attempts, and two explicit fresh processes produce distinct completed attempts with equal manifests. The unchanged QR notebook's earlier 18/18-cell evidence is reused only for its existing path. | Complete; live notebooks unchanged and not rerun |
| Alphalens factor diagnostics and actual publication | Existing independent IC, quantile-return, turnover and missingness cases pass; renewed final installed feature consumer publishes and checks downloaded artifacts. | Complete; daily-resample turnover limitation unchanged |
| Feast offline availability, revision, missing entity and TTL | Renewed installed Feast 0.66.0 worker passes actual registry/Parquet retrieval, native parity, delayed correction, missing entity and TTL checks, with ClearML artifact verification. | Complete; separate worker, no online serving |
| DuckDB/Polars precision and explicit marimo execution | Existing numerical conversion tests pass; final installed feature consumer and copied maintained marimo interface run outside the checkout. Display controls create no formal attempt. | Complete; no reactive fit or holdout read |
| Reference/current diagnostics, availability and applicability | Independent disjoint supports give KS D=1 and p=2/binomial(20,10); identical control gives D=0, p=1. Delayed-label case admits 36 then 38 labels, retaining two permanently missing labels; exact MSE=1. Installed artifact repeats these results. Missing labels and predictive inapplicability leave applicable feature diagnostics active. | Complete |
| Retained diagnostic inputs, actual reports, failure and recovery | Final wheel computes repository JSON/HTML, publishes to actual local ClearML, downloads every declared artifact and checks its hash. Retained computation failure and publication/lost-receipt failures recover saved artifacts while recomputation is patched to fail. A separate installed process reproduces JSON and HTML byte for byte from retained inputs. | Complete; no Evidently-output claim |
| Dependency admission and installed boundary | SciPy is now direct metadata; no external locked version/artifact changed. Full all-marker audits cover core 179, Feast 64 and agent 13 packages, with zero findings or skipped packages. Final installed runtime checks 135 packages and actual SciPy, CPython 3.14.7 and pandas 3.0.5. | Complete; rejected Evidently evidence and QuantLib restriction preserved |
| Full validation and hosted CI inspection | Complete `make check` and applicable final installed/service consumers pass. GitHub is inspected and reports the account billing blocker before executing jobs. | Local acceptance complete; hosted Linux/macOS and merged-result execution unproven |
| Conditional SHAP/skfolio | No selected explanation-dependent model or multi-asset allocation consumer. | Inapplicable under unchanged conditional criteria |

The old 60-second feature-consumer failure was isolated to cold dependency imports
and Matplotlib font-cache construction. Retained import timing measured 16.614
seconds in `matplotlib.font_manager`; a writable cache measured 17.644 seconds
first use and 0.120 seconds on reuse. The unchanged earlier consumer then completed
in 9.469 seconds. The smoke owner now compiles **all** installed dependency and
runtime bytecode during installation and supplies one writable, retained
`MPLCONFIGDIR` per smoke. Existing 60-second subprocess limits and assertions are
unchanged. The complete fresh smoke passed the feature, model, diagnostic, economic
and recovery consumers. The older bytecode-only retry remains a failure; it did
not establish that font-cache setup was resolved.

Final commands and observable results:

- `TMPDIR=/private/tmp MPLCONFIGDIR=/private/tmp/alpha-diagnostics-evidence/full-check-fonts
  make check`: **passed**, **1,196 tests passed, 3 performance cases deselected,
  no skips**, 145.85 seconds for pytest. Ruff/format covered 339 files, strict mypy
  332 files, stubtest 1,562 modules; source, ownership, admission, vulnerability,
  security and installed-wheel checks passed. Performance acceptance is not claimed.
- Final wheel SHA-256:
  `2f448a87f6bd73eb6609329609ae02f968d7b891690cf3534e35285d9d6ad0fe`.
  Core lock SHA-256:
  `67f115cf2763eaec492defa8b2245b20ea282876d235a45c2ecb28044cd58d37`.
  All 198 runtime files in this wheel match final source. Final local links pass
  for 37 documents, including five additional owning guides; the staged secret
  scan passes for 450 governed paths.
  The wheel's isolated Python ran the copied `feature_study.py`,
  `economic_workflow.py`, `offline_features.py` and `pipeline_workflow.py` against
  actual local ClearML. Exact NAV, vectorbt, both comparison trials, fresh-process
  resume, model/report uploads, offline retrieval and failure/recovery passed.
- Window attempt `71fa54be917641a486ec165b6cec7a7b` published to task
  `103732f96bfd4299acec5b8495f3fe92`; the downloaded JSON SHA-256 is
  `591d1f1d66d3bd1bf953b264e11f25134ae07b380fd73866bd803afadf88aa99`.
  Later-cutoff attempt `7e46c0f172584258aa19fa01ea422ff1` published to task
  `9db9139d4a4043308dd5faff9cda16ae`; its JSON SHA-256 is
  `45600ea7f541722435e548332c2c31e208137a45ca0b6e03555fd60040cbc6a6`.
  Explicitly inapplicable attempt `4d573df66d4747be8100bb91f35fab94` and failed
  computation `1b5292727db14973b722d60b5ea32b3c` retain separate tasks and histories.
- All **930** earlier inventory files still match their hashes. Their unchanged
  notebook/source-specific evidence is reused only within the recorded scope;
  affected installed and service proofs above are fresh. No active environment
  was reinstalled. New development failures, including the initial saved-model
  decoder and verification-helper selector mistakes, are preserved with corrections.
- `alpha-governance-artifacts release-check` still fails closed on QuantLib's
  existing development-only admission, as required.

Evidence, exact inputs, both failed and successful smoke artifacts, matching wheels,
locks, commands, report downloads and hash inventory are retained outside Git in
the primary checkout's owner-only ignored
`logs/research-diagnostics-acceptance/2026-09-21/`. Credentials and SDK caches are
excluded. The task's serial agent and service containers are stopped after
verification, with named volumes, environments and prior attempts preserved.

The inspected main [hosted run](https://github.com/lixuanguang/alpha-research-lab-private/actions/runs/35573331304)
failed before source or authoritative jobs executed; macOS was skipped. GitHub's
annotation identifies failed recent account payments or an insufficient spending
limit. The owner must resolve **Billing & plans**, then rerun required checks;
repository changes cannot repair that account condition. Protection settings and
checks remain unchanged. Prior merge authorization applied only to PRs 69 and 70.

Reversal removes the new diagnostic owners, exports, consumer/interface and direct
dependency declaration together, restoring the matching lock/admission digest.
The smoke cache/compilation fix can be reverted independently if its measured
cause is resolved elsewhere. Preserve all attempt stores, reports, immutable
model/source artifacts, failed evidence and matching wheels when reversing.

### Frozen baseline acceptance

**MR 8 — source verification implemented; empirical acceptance open.** Run `p1-btcusdt-return-v1` unchanged against the permitted actual source
and an isolated installed candidate. Resolve or explicitly leave unresolved the
[experiment's source and acceptance requirements](../research/p1-baseline.md#acceptance-and-research-discipline).
Saved ZIP integrity does not prove historical membership, coverage or revision
availability. Assumed event-time availability remains exploratory.

Acceptance requires the complete saved-source path, causal eligibility and revision
evidence, declared quality, exact no-trade/economic reconciliation, durable reports
and fresh-process reproduction. Synthetic software evidence is reusable for its
scope but cannot supply missing empirical source evidence. A negative costed result
can satisfy the engineering criterion; tuning the frozen experiment to pass cannot.
If a required source fact is unavailable, record the gap and leave acceptance open.

Acceptance attempt, 2026-09-22, from main `86835ee8`: the
[frozen specification and source record](../research/p1-baseline.md#saved-source-verification)
now link explicit momentum/control `BacktestSpec` configurations and a manual
installed consumer. Existing `market_data` readers, quality/publication/query
owners and `applications.backtest.run_backtest` compose the actual saved-source
check. Reusable domain behavior, curated APIs and application entrypoints remain
unchanged; no alternate economic runner or synthetic source-evidence adapter was
introduced.

The founder requested setup of obtainable data/evidence. The original daily ZIP
is retained and matches the freshly fetched publisher checksum. Independent
ZIP/CRC/CSV inspection found 638,484 daily rows and 27,480 selected-hour rows,
seven fields, consecutive observed trade IDs and no timestamp regression.
Pinned official archive documentation, checksum headers and a historical listing
announcement review are retained with explicit evidence limits. A 2017 listing
announcement does not establish continuous 2024-hour eligibility; checksum and
row continuity do not establish recorder coverage or historical receipt/revisions.

Required completion remains blocked on those source facts and their causal
admission contract. Current quality admission rejects causal use; current
configured economic attempts require validation/holdout windows that frozen P1
does not define. Do not backdate assertions, invent split windows, or report
unchanged cash from unavailable observations as a costed strategy result. Fitted
models, online features, shared services and deployment remain outside this slice.

Verification on CPython 3.14.7 / Darwin arm64:

- `uv run --frozen --no-editable pytest -q tests/unit/simulation/test_economic_replay.py
  tests/unit/accounting/test_ledger.py tests/unit/financial_units/test_p1_hand_ledger.py`:
  **15 passed**, including the independent hand ledger and fee-rounding distinction.
- `uv run --frozen --no-editable pytest -q tests/unit/data/test_quality.py
  tests/unit/data/providers/binance/test_archive_occurrences.py`: **18 passed**.
- `TMPDIR=/private/tmp
  PYTEST_ADDOPTS=--basetemp=/private/tmp/alpha-mr08-final-pytest make check`:
  **1,196 passed, three performance tests deselected, no skips**. Ruff, strict
  typing, stub conformance, engineering/architecture checks, Bandit, secret scan,
  admission of 179 locked packages and vulnerability coverage passed. The isolated
  installed-wheel smoke passed; all 135 installed distributions were compatible.
- The installed actual-source consumer exhausted the full daily reader and selected
  **27,480 rows**. Causal publication was rejected with zero observed invalid rows,
  duplicates or gaps; unknown eligibility, original availability and recorder
  coverage remained explicit. No causal snapshot was published. The exploratory
  snapshot is `f08458988126c3402655b336eeeee741411e3f143332e26dba7f93b083b6226b`.
  Both frozen instances retained 59 missing completed observations, zero fills and
  NAV `1000 USDT`. These are source non-admission results, not measured performance.
  The successful refusal scenario exits **3**, keeping baseline acceptance open.
- A second isolated process rebuilt the same snapshot, reopened the first saved
  snapshot and checkpoint, and reproduced all 11 deterministic artifact digests.
  Resuming at the halfway checkpoint with batch size one reproduced the complete
  momentum trace exactly. It also exited **3**; reproduction proves the retained
  non-admission outcome, not an economic run with historically available inputs.
- The first manual invocation failed because the consumer omitted the required
  empty correction map. Its script, partial output and log are preserved. After
  supplying the explicit empty map, focused Ruff/mypy and the complete engineering
  checker passed before rerunning. Runtime, package, dependency and ordinary-test
  inputs are unchanged, so the full-lane and wheel evidence remains applicable;
  manual installed execution covers the changed consumer integration.

The wheel SHA-256 is
`2f448a87f6bd73eb6609329609ae02f968d7b891690cf3534e35285d9d6ad0fe`;
installed implementation identity is
`4ec2e0eb245e81ca5ce82632ed7fef21650dafa9e3b717bd4cd1db9378e3394d`.
The isolated environment and original smoke outputs remain under
`/private/tmp/alpha-research-wheel-smoke-ha38ceas/`. The matching wheel, locked
runtime requirements, test logs and source research are also retained in ignored
`logs/frozen-baseline/2026-09-21/` in the primary checkout. Its `installed-source/`
directory preserves the failed first invocation, successful refusal run and
fresh-process reproduction with configs, script, outputs and inventories. Final
architecture/link checks and `git diff --check` passed after the evidence update.
Live ClearML/lakeFS services were not restarted: this change does not alter their
MR 6/7 contracts and cannot produce a source-qualified economic report to publish.
QuantLib's existing development-only release restriction remains. Hosted CI is
not established by this local lane.

The source record owns reproduction, retained local evidence and reversal. Preserve
matching artifacts and partial attempts when reverting the new consumer/configs.
This work grants no deployment or trading authority. **MR 8 is not complete.**


### Frozen baseline continuation

**MR 8 — software integration delivered; empirical acceptance open.** Continued
existing PR #72 and worktree from `2c93536` after fetching main; main remained its
existing parent, `86835ee`. The [source continuation](../research/p1-baseline.md#source-investigation-continuation)
records retrievable native capture evidence, exact applicability and remaining gaps.
All 27,480 frozen archive trades match independently captured decision-relevant
fields and have recorder timestamps. Historical eligibility/reference availability,
positive coverage and exhaustive correction/version history remain unestablished.
No actual-source baseline result or profitability claim is made.

Delivered integration: native archive witnesses in existing contracts/adapters and
validation, scoped causal publication/query/replay with retained limitations,
unfitted engineering-sample configuration, semantic identities, retained attempts,
complete checkpoint recovery and atomic costed reports through the existing backtest
workflow. Strict full-source causal admission stays closed on missing evidence;
scoped captured-row agreement cannot satisfy the full frozen acceptance requirement.
Existing exploratory saved-input identities and holdout controls are preserved.

Final local source lane (`make check`, attempt 4): lock, Ruff, formatting, strict
mypy (335 files), native stubtest, engineering standards, dependency admission/audit,
architecture links, Bandit and secret scanning passed; **1,199 tests passed,
3 performance cases deselected, zero skips**. The unchanged performance lane is
outside this required check. Two installed-wheel attempts timed out at the existing
feature-study consumer's 60-second bound during cold startup. The diagnostic passed
and populated the Matplotlib cache; the complete unchanged `wheel_layout.py` then
passed with fresh output directories and the same installed wheel, preserving the
60-second consumer bounds. Thus source and installed components passed; neither
original timed-out `make` invocation is reported as a successful command.

The retained wheel SHA-256 is
`dc81101c2d5561f918114f4ace6807ea5b7967e8ab57dfba1b389eee4142010e`.
Both build attempts produced identical wheel bytes. Runtime requirements differ
only in their generated output-path comment. Evidence, commands, initial lint/doc
failures, the corrected legacy error-message test and timeout attempts are retained
under primary-checkout `logs/frozen-baseline/2026-09-22/`. Final documentation-only
edits do not change the tested runtime identity. The separately inspected hosted CI
at the preceding head was blocked by GitHub billing; final-head status and any
founder-authorized merge are recorded on existing PR #72, without changing billing
or bypassing configured merge requirements.

The new installed synthetic consumer checks both unchanged frozen configurations,
exact negative gross-to-net/cash/position/NAV reconciliation, no-trade, no partial
publication and fresh-process resume/repeat report parity. It is included in wheel
smoke. Prior source-refusal evidence is reused only for its historical scope.
The external prerequisite and version-2 rollback boundary are in the owning P1 page.
No deployment, purchase, source substitution or trading is authorized by this evidence.

## Candidate promotion and operation

### Runtime feature parity

**MR 9, conditional.** Add incremental features only for a candidate that needs them;
a scheduled batch candidate can retain a qualified batch path. Use qualified inputs
with explicit clocks, cadence, missingness, late-data, warm-up and recovery behavior.

Acceptance: historical, replay and runtime feature/prediction traces agree under
the declared contract, including ordering, gaps, corrections and restart. Never
infer live readiness from the existence of a historical adapter. Keep one versioned
formula and explicit state compatibility; investigate the first divergence.

For a candidate that needs online feature retrieval, extend the MR 7 Feast adapter
with an explicit online store/materialization consumer. Qualify historical/online
parity, freshness, TTL, correction handling and restart at the decision boundary.
Retain which feature version and materialization supplied each decision. A latest-value
online store cannot answer arbitrary historical as-of queries. A qualified batch
candidate does not need an online store, and Feast does not move feature formulas
out of their existing owner.

MR 9 implementation status (2026-09-22): **bounded saved-input batch parity
delivered; full runtime acceptance remains open.** The concrete software consumer
is P1's existing scheduled, unfitted completed-price rule. `research.features`
owns `CompletedReturn`, `ScheduledFeatures`, versioned state and parity records;
`research.observations` retains source admission and completed-window semantics.
`simulation` calls the same formula, and the existing `applications.backtest`
Python API and `alpha-backtest qualify-features` command compose the comparison.
There is no incremental engine, online store, new runner or deployment consumer.
The [owning contract](../../src/research/features/README.md#scheduled-completed-price-parity)
defines clocks, freshness, missingness, correction freezing, recovery, bounds,
invocation and reversal.

Prerequisites were checked against `92de67c` (latest main when the isolated branch
was created), not inferred from merged PR numbers. MR 3's exact feature/label
contracts, MR 4's model construction/reload and MR 7's offline Feast admission
remain present: the focused prerequisite command passed **59 tests**. P1 consumes
completed event-time closes rather than MR 3's query-business trailing window;
those definitions remain distinct. No accepted candidate needing incremental or
Feast online retrieval exists. MR 4 prediction/fitted-state parity and Feast
materialization/freshness/TTL are therefore not activated by this rule-only slice.
MR 8's historical eligibility, positive coverage and exhaustive revision evidence
are still missing; neither this parity report nor a native capture witness supplies
them. Actual runtime source binding and measured cadence/recovery qualification
remain required before full MR 9 acceptance. MR 10 packaging and MR 11 deployment
admission are not implemented here.

Verification: focused development checks passed **20 tests**, including independent
exact ratios, equal-clock and late corrections, ordering, stale/missing/gapped
windows, fresh-window recovery, BTC/ETH and instance isolation, rejected state,
failed-call atomicity, full replay parity and first-divergence reporting. Initial
lint/type failures were corrected; one test originally omitted a complete source
partition and was corrected after the unchanged admission gate rejected it.
Final required source lane, `env TMPDIR=/private/tmp make check`: lock,
Ruff/format (347 files), strict mypy (340 files), native stubtest (1,562 modules),
engineering rules, dependency admission/audit, architecture links, Bandit and
secret scan passed; **1,207 tests passed, 3 performance tests deselected, zero
skips**. The unchanged performance lane is outside this check. Component README
links were also checked explicitly (2 documents), because the default link checker
covers only `docs/`.

The command subsequently timed out at the unchanged installed feature-study
consumer's 60-second cold-start bound. A diagnostic using the same installed wheel
confirmed Matplotlib font-cache construction and passed. The complete unchanged
`wheel_layout.py` then passed with a populated cache and fresh output directories,
retaining every 60-second bound. This includes installed feature API/CLI equality,
fresh-process feature-state reload and incompatible-reference refusal. The full
source and installed components passed; the timed-out `make check` invocation is
not reported as a successful command. No actual ClearML, Feast online, live feed,
deployment or trading qualification is claimed by this synthetic installed suite.

Wheel SHA-256:
`3e6eec8f8c0432ae8730853cdbd68d40a2bdde432b3032d5871d16914e5dfaf4`.
Installed implementation identity:
`5e22ec59af8931bb897f076f2060a10a921a10527c8c11e60fdccfefa94406b5`.
Matching wheel, runtime requirements, synthetic saved inputs, reports/checkpoints,
commands and all validation attempts are retained locally in the primary checkout's
`logs/scheduled-features/2026-09-22/`; this is local evidence, not a hosted artifact.
Final roadmap evidence edits do not change the tested package/runtime bytes.

Two earlier full attempts remain recorded: a concurrent default `uv run` replaced
the noneditable test installation (147 failed, 791 passed, 268 setup errors), then
a sequential run passed 1,205 tests but failed the existing Unix-socket test because
the macOS temporary path exceeded its bound. Isolating environment changes and
using `/private/tmp` resolved those harness/environment failures. A final source-unit
rejection regression increased the passing count to 1,207. Source/admission gates
and test timeouts were not weakened.

Exact focused commands (all zero skips/deselections):

```sh
uv run --frozen --no-editable pytest -q tests/unit/research/test_features.py tests/unit/research/test_models.py tests/unit/research/test_offline_features.py tests/unit/simulation
# Prerequisite state: 59 passed.
uv run --frozen --no-editable pytest -q tests/unit/research/test_scheduled_features.py tests/unit/simulation/test_scheduled_parity.py tests/unit/simulation/test_economic_replay.py
# Final changed-domain state: 20 passed.
```

Hosted source/macOS/merged-result CI remains a required pre-merge boundary; its
PR status is reported separately and local checks do not bypass it. Full MR 9 is
not marked complete while the runtime prerequisites above remain open.

### L2 order-book backtesting

**MR 9A, implemented; local acceptance 2026-09-22.** The saved-book workflow is runnable end to end:
verified L2 archive → book observations and EDA → strategy targets → independent
risk checks → simulated orders and fills → cash, positions and P&L report.
The existing OKX reader supplies books to a separate L2 economic path; MR 5's
trade-price runner remains supported. This closes the gap before an order-book candidate in
MR 10. It does not depend on a live collector, fitted model, online feature store
or MR 8 baseline acceptance.

**First supported scope.** Reuse the saved OKX ETH-USDT spot archive for
2026-09-20 selected by the [order-book study](../../examples/notebook-operations.md#historical-order-book-study).
Start with its explicit 10,000-message window and a simple, configured book-based
rule plus a no-trade control. The window is an engineering demonstration; neither
profitability nor full-day coverage is a completion condition. Instrument, window,
rule parameters, initial cash, limits, fee rates and timing assumptions belong in
versioned configuration. Shared libraries must not hardcode this pair or date.

The first simulator supports long-only spot orders that execute immediately on
arrival: buys consume available asks and sells consume available bids, walking
price levels in order. Partial fills are supported; cancel the unfilled remainder
of each immediate-or-cancel order. Enforce configured size and cash limits, tick
and lot rules and taker fees through the existing exact financial contracts.
Do not fill at a midpoint or grant unlimited liquidity. Retain consumed liquidity
so successive simulated orders cannot repeatedly spend the same displayed size;
declare how later source updates affect that state. State the no-market-impact
assumption and supported order-size envelope. Resting limit orders, queue position,
maker fills, cancel/replace and derivatives require a separate supported slice
before a strategy can rely on them.

Follow the existing [replay clocks and fill contract](../architecture/platform-design.md#replay-clocks-and-fill-fidelity).
Keep exchange-side book state separate from the information available to the
strategy. Declare feed, processing, order-entry and response delays, deterministic
tie ordering, stale/invalid-book handling and terminal valuation. Preserve the
archive's missing receipt times and unproven sequence continuity. Model timing in
a separate versioned research scenario; download time is not historical receipt
time, and existing source-admission rules must not be relaxed. Keep the frozen P1
trade-price experiment and its results unchanged.

**Implementation owners.** Extend the existing owners through their public APIs:
`market_data` for verified book replay; `research` for reusable observations,
features and experiment records; `strategies` for the rule; `simulation` for order
arrival, fills, costs and checkpoints; `risk` and `accounting` for reservations
and exact postings; `configuration` and `applications.backtest` for configured
composition and reports. Reuse the existing installed `alpha-backtest` entry point
and make [the notebook](../../examples/orderbook-research.ipynb) call the shared
implementation. Introduce only the pure offline order state needed here; MR 12
still owns paper-runtime journals, reconciliation and recovery from unknown sends.
Do not route unsupported L2 runs through the trade-price vectorbt comparison.

**Acceptance.** Deliver one configured command and notebook journey over the saved
archive, retaining input/configuration/code identities, source limitations, timing
and fill assumptions, decisions, orders, fills and an exactly reconciled report.
The complete and interrupted/resumed runs must agree, including pending orders,
consumed liquidity and independent instance state. Focused hand-calculated cases
must cover depth walking, insufficient size/partial fills, fees and cash/position
postings; causal checks must show that future changes cannot alter earlier
decisions or fills, and decisions see only book updates delivered by the modeled
feed clock. Exercise invalid/stale inputs and a different
declared delay, preserving failures instead of silently filling gaps. Use bounded
configuration/fixture cases to verify another supported spot instrument and
isolated strategy instances; reject unsupported product mechanics explicitly.
Retain the existing trade-price regression evidence and renew affected checks.
Run the real saved-data example through the installed package; small fixtures
prove mechanics but do not replace that integration proof. Keep raw market data
and bulk results outside Git. Hosted source/macOS/merged-result CI remains the
pre-merge gate; update this section with actual commands, results and limits.

**Delivered evidence.** The configured command is:

```sh
uv run --frozen --no-editable alpha-backtest books \
  --config configs/backtests/okx-eth-usdt-book-v1.json \
  --archive data/okx/history/f62e64b7-1b40-4869-8b05-2ca911fefcef \
  --output logs/book-backtest/runs
```

The [completed notebook](../../examples/orderbook-research.ipynb) calls the same
installed `run_books` orchestrator. The 10,000-message source interval is
00:00:00.001–00:06:00.252 UTC. The fixed imbalance rule submitted **62 orders**,
received **78 level fills**, ended flat with **998.35849845 USDT NAV** and
**-1.64150155 USDT net P&L**, including **1.62998455 USDT taker fees**. The no-trade
control stayed flat at **1,000 USDT**. No parameter tuning or empirical alpha claim
is part of acceptance.

The [acceptance record](../research/l2-book-backtest.md) owns the exact financial,
timing and depletion assumptions, retained artifact identities, commands and
limits. Focused existing/new regressions passed **79 tests**, with **1 deselected**;
the outside-checkout installed CLI fixture passed for ETH-USDT, BTC-USDT, three
isolated accounts, complete restart equivalence and retained source failure.
Strict typing, formatting, native stub checks, security and engineering rules passed.
The real-data notebook completed in a fresh kernel; the interrupted/resumed real
run matched both account checkpoints, EDA and reports byte for byte. Final
installed fixture recovery passed after the validation-guard cleanup. Hand cases cover partial
fills, exact postings, fees, affordability, depleted liquidity and source updates;
causal cases cover delayed information, pending responses and changed future data.
Original receipt and sequence fields remain unknown; archive continuity and
full-day semantic coverage remain unproven. This is long-only, no-impact IOC
research with explicit participation caps, not resting-order or runtime recovery
support. Hosted source/macOS/merged-result CI remains required before merge.

Reversal: remove the new configuration/consumer and book-specific implementation
together while preserving saved inputs and run records. Reject incompatible
checkpoint versions explicitly. The existing trade-price path remains supported.

### Candidate packaging and runtime binding

**MR 10.** Freeze the [candidate contract](../architecture/platform-design.md#candidate-promotion-contract):
input requirements, features/preprocessing, optional model, signal-to-target policy,
state/warm-up rules and accepted experiment evidence. Retain artifact bytes as well
as hashes. A rule has no invented model artifact. Reuse the accepted components in
research and runtime applications; no translation into separate production formulas.

For an order-book candidate, complete [MR 9A](#l2-order-book-backtesting) before
starting this packaging work. Bind its supported order types, book requirements,
timing/fill model and accepted backtest evidence in the candidate contract. A
strategy requiring resting orders must also have that execution model implemented
and tested; the first immediate-execution slice cannot qualify it. Candidates
using the existing trade-price model keep their current acceptance path.

Acceptance: reconstruct a candidate from retained bytes without a notebook or
credentials; reject incompatible schemas, units, timing, state or outputs; bind a
compatible runtime input and reproduce matched decisions. Deployment configuration
selects candidate instances and resources separately from research selection and
trading authority. Retraining creates a new candidate and renews affected evidence.

Pin the ClearML model/task IDs, immutable model manifest and bytes/digests, relevant
lakeFS commits, feature definitions and accepted evaluation/report IDs. ClearML model
publication can protect model contents, but tags/metadata are not an immutable
candidate identity. Reconstruct from retained bytes when the UI is unavailable;
verify content rather than resolving a mutable "latest" name. Catalog publication,
research selection, deployment and trading activation remain separate actions.

### Trusted deployment artifact

**MR 11, before any deployment.** Supply a concrete build/install/verify consumer
that binds exact artifact bytes, source, dependency lock, provenance, platform and
trusted origin. Enforce inventory, safe archive paths and configuration/state
compatibility. Verification fails before loading incompatible or untrusted content.

The [dependency/release boundary](../architecture/README.md#dependency-and-release-boundaries)
currently blocks release. Clearing that restriction alone does not implement this
consumer. Exercise the actual isolated installed artifact and failure boundary.
A collector pulled forward for a data need must meet the same applicable deployment
requirement; it need not wait for a strategy or executable venue adapter.

Apply the same concrete deployment boundary to operated ClearML server/agent,
lakeFS and applicable Feast services. Pin their images/configuration, admit the
actual edition and dependencies, and verify access boundaries, artifact retrieval,
backup/restore and upgrades for the selected topology. ClearML is one selected
product, not one process; include its backing services and retained artifact storage.
Workers execute trusted research entrypoints in the declared environment. A service
deployment or queued research task does not confer trading authority.

### Paper order lifecycle and recovery

**MR 12.** Compose a paper/shadow runtime with stable order identity, acknowledgement,
fill, reject, cancel/replace and unknown-outcome states. Retain orders, fills and
state in a durable journal with idempotency and writer fencing. Paper and replay
reuse strategy decisions; their execution adapters expose different assumptions.

Acceptance: delayed/duplicate messages cannot duplicate orders or fills; unknown
sends reconcile before retry; crash/restart preserves commitments and economic state.
Qualification may introduce an offline order lifecycle earlier when a selected
simulator needs it, without implying deployment acceptance or live authority.

### Independent risk and account reconciliation

**MR 13.** Enforce independent account/instance limits including pending exposure.
Reconcile authoritative cash, positions, open orders and unknown/pending commitments
before continuing after startup, disconnect or a break. An instance cannot raise
its own limits or erase reservations by restarting.

Acceptance: rejected or duplicate activity cannot bypass limits; stale/missing state
and reconciliation breaks trigger the specified protective response. Record the
resolution and owner. Base reconciliation is mandatory for one instance; shared
allocation is an additional requirement, not a reason to postpone the base control.

### Shared account allocation

**MR 14, conditional.** Before a second instance shares an account, define allocation,
arbitration, netting and attribution while preserving each strategy's intent.
Reconcile allocated commitments/positions/cash with authoritative account state.

Acceptance: conflicting targets, partial fills, restarts and allocation changes
cannot double spend capital or conceal exposure. Shared inputs stay immutable;
strategy state and limits remain attributable. New accounts/asset mechanics need
their own applicable qualification rather than blanket platform acceptance.

### Operations and paper qualification

**MR 15.** Deliver an owned runbook and independent health/alert path with the
paper/shadow candidate. Observe data freshness, decision progress, errors, journal
persistence, reconciliation, limits and alert delivery. A live process may be stalled;
failed alert delivery must not silently disable protection.

Acceptance: compare matched replay/paper input, feature, prediction and target traces;
qualify start, stop, cancel, disconnect, restart and compatible rollback. Retain the
first divergence and every material failed attempt. Simulated fills qualify only
their declared model. Stop, cancel and flatten remain distinct operations. Actual
paper/shadow deployment also requires MR 11.

Schedule retained evaluation/report tasks through the qualified ClearML worker path.
Reuse MR 7 reference/current diagnostic reports for feature quality, distributions
and model performance where labels exist, keeping reference windows and thresholds versioned. Record stale,
missing-label and failed-report outcomes. These jobs may lag or fail independently;
they do not replace the health/alert path or sit in the order/decision hot path.

### Executable venue adapter

**MR 16.** Implement one selected venue/product/account boundary with supported
order types, precision, limits, authentication and authoritative reconciliation.
Keep vendor state behind the order contract. Market-data capture is not an order
adapter. Preserve partial fills, cancel races and unknown outcomes.

Acceptance: the appropriate permitted environment demonstrates the actual adapter
boundary and its failure/recovery behavior. Offline mocks alone cannot establish
venue compatibility. Retain the operating environment and observed limitations;
this package does not grant live activation.

### Live monitoring and controls

**MR 17.** Bind the qualified operations path to actual execution/account state.
Retain artifact, candidate and instance identities with stale inputs, failed inference,
orders/fills, rejects, cash/position breaks, P&L attribution and limit events.

Acceptance: fault scenarios demonstrate independent detection, alert delivery and
the configured stop/cancel response, including alive-but-stalled processing.
Delayed-label/model monitoring is applicable only to candidates that use it.
Keep controls effective through disconnects and operator/restart transitions.

Link realized performance and applicable reference/current diagnostic findings
to the exact deployed candidate/model version and observation window in ClearML. Distinguish delayed
outcomes from missing data. A drift finding can request research investigation;
automatic retraining, candidate replacement or live activation is not implied.

### Bounded activation and recovery

**MR 18.** Add an explicit activation decision binding artifact/configuration,
account, venue, instruments, capital, exposure/loss limits, duration and credential
scope. Deployment alone must leave executable authority disabled. Invalid or
incompatible startup state is refused.

Acceptance: authorized bounded operation demonstrates stop/cancel, reconciliation,
recovery and rollback with retained external fills. Rollback cannot undo venue
activity. The [workflow](../governance/workflow.md#activate-and-operate) and
[operations runbook](../governance/operations.md) own authority and response rules.
This roadmap authorizes implementation work only when requested, not live orders.

### Additional compatible live instance

**MR 19.** Add one real compatible strategy/instrument instance through configuration
and accepted components. Qualify isolation, resource/risk attribution and required
shared-account controls. New product mechanics require new simulation, accounting,
risk and execution capabilities before admission; do not conceal them as configuration.

Acceptance: starting/stopping/updating one instance cannot mutate another's strategy
state or bypass account controls. Extend only the affected source, economic and
operational evidence for the added scope.

## Maintenance and growth

### Measured storage and computation growth

**MR 20, conditional.** Revisit the reference reader or computation lane only when a
representative workload misses an accepted latency, throughput, memory or storage
budget. Compare verified end-to-end behavior, including loading, integrity, causal
selection, controls and retained lineage. Output batch size is not a total-RSS bound.

Use [query workload evidence](../../examples/notebook-operations.md#query-workload-evidence)
for its original measured scope; it does not benchmark current code. A Parquet scan
alone is not a replacement for the reader. Columnar/distributed/native/GPU paths
must preserve relevant exact arithmetic, timing, identity and recovery contracts.
The selected integrations above address concrete traceability and research consumers;
they do not need to wait for a scale bottleneck. This MR owns their measured growth:
DuckDB/Polars replacements for expensive reader/transformation paths, larger lakeFS
storage, shared Feast stores and additional ClearML workers. Benchmark the full
validated path and conversion costs against the retained reference. Preserve original
data/model identities and numerical/temporal behavior when moving storage or engines.
Qualify writer coordination and restart before multiple workers write shared attempt
state; MR 2's local single-writer store is not a distributed trial database. Process
isolation for trusted research is not a malicious-code sandbox.

### Python ownership and enforcement

**MR 21.** Complete the existing [Python ownership requirements](../coding_standards/README.md#python-scope-and-migration)
in developer tooling, tests and maintained snippets. Reusable behavior belongs to
cohesive classes; bare functions serve actual orchestration. Preserve pytest
discovery, callback signatures, isolation and native stub contracts.

Add focused enforcement for non-orchestrator bare functions without weakening
existing typing, import or documentation checks. Update permissive cases and run
the configured static scope. Class cohesion still requires review; moving unrelated
helpers into one static-method collection is not acceptance.

### Further scope needs a consumer

The platform can grow toward multi-asset research, portfolios and independently
operated strategies. New financing, derivatives, corporate-action, session, currency,
margin, queue/impact or lifecycle behavior needs an explicit consumer and its own
bounded contract and independent numerical/causal proof. Existing spot or visible-book
evidence cannot qualify those mechanics. Reuse mature libraries behind narrow
adapters where they satisfy the required semantics.

Team ownership, independent approvals and organizational controls are introduced
as actual contributors/operators join. They do not replace the technical integrity,
reproduction and safety controls required by the first real consumer.

## Execution and maintenance

For each MR, select one observable consumer outcome, its dependencies and the
smallest sufficient proof. Split an oversized implementation before starting it;
keep this backlog as the canonical list and use stable capability names elsewhere.
Do not create a permanent roadmap file or notebook for each completed MR.

Follow the [engineering guide](../coding_standards/README.md) and
[development workflow](../governance/workflow.md). Preserve functional ownership,
public APIs and application composition boundaries. Keep definitions separate from
selections, shared inputs immutable and mutable state per instance. Unsupported
capabilities and invalid configuration fail explicitly.

Acceptance records identify source/artifact, environment, configuration, inputs,
attempt, command, result and limitations. Reuse unaffected evidence and renew the
proof changed by code/data/configuration/dependency/artifact changes. Retain failed
attempts; a new success does not rewrite measured reliability. Run expensive checks
only for a concrete boundary that cheaper evidence cannot establish.

Update the current architecture/component documentation and QR guide when behavior
becomes usable. Keep empirical research acceptance, software correctness, artifact
admission, operating qualification and actual activation distinct. Completed MR
history remains in version control; active READMEs describe current behavior and
active plans. Preserved content-addressed fixtures and measured evidence retain
their original identities and do not serve as roadmap navigation.
