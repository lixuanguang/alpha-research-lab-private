# Platform infrastructure roadmap

Owner: repository founder. Updated 2026-09-20. **MRs 1–3 are implemented; MRs 4–21 are planned.**
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
validation and versioned publication → explicit snapshot queries/replay → EDA.

| Available capability | Researcher benefit | Current limit |
| --- | --- | --- |
| Instrument identity, calendars and exact financial units | Shared identifiers, clocks and numerical conventions | These foundations do not constitute a strategy ledger or execution engine |
| Bounded historical acquisition and native capture | Retained source bytes, request identities and explicit failure/recovery behavior | Supported sources and products only; source-specific limits remain visible |
| Occurrences, revisions, eligibility and dataset publication | Trace observations and reopen a verified snapshot | Empirical historical eligibility, coverage and revision availability remain unresolved for the frozen sample |
| Trade cutoff/history queries and chronological replay | Inspect what is knowable and retain corrections and scoped controls | Bounded reference implementation; replay alone does not simulate economic fills |
| Book reconstruction, publication and replay | Inspect visible books, recovery and matching saved state | Exploratory degraded scope; no queue position or executable-fill claim |
| Retained experiment attempts and temporal splits | Reproduce semantic inputs, inspect all attempts and enforce declared fit/holdout boundaries | Local single-writer store; current consumers are unfitted exploration and price diagnostics, with models still planned |
| Versioned observed-price features and separate forward labels | Inspect exact returns, causal windows, missingness and delayed outcome availability | Bounded unfitted trade-price diagnostic; no economic, book/macro, model or runtime claim |
| Pinned research selections, configured EDA and maintained notebooks | Discover saved snapshots and reopen named trade/book inputs with identities, units and missingness | Bounded exploratory assembly; fitted model workflows and economic backtesting remain planned |

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
| 7 | [Research comparison, Alphalens and Feast offline retrieval](#research-comparison-and-extension) | MRs 1–6; fitted-state requirements only where applicable |
| 8 | [Frozen baseline acceptance](#frozen-baseline-acceptance) | MRs 5–6 plus required actual source evidence |
| 9 | [Runtime feature parity and applicable Feast online retrieval](#runtime-feature-parity) | MRs 3–4; MR 7 for a Feast consumer; qualified runtime input, only if required |
| 10 | [Candidate packaging and runtime binding](#candidate-packaging-and-runtime-binding) | MRs 6–7 and accepted candidate evidence; MRs 4/9 where applicable |
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

## Selected research integrations

This revision starts at MR 4. MR 3's feature/label scope and acceptance remain
unchanged by these plans; later adapters consume its delivered public outputs.
These are planned integrations, not installed dependencies or accepted capabilities.
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

| Selected tool | Researcher outcome | First integration and later extension |
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
| [Evidently](https://docs.evidentlyai.com/introduction) | Data quality, distribution drift and applicable predictive-performance reports | MR 7 offline reference/current-window reports; MRs 15/17 scheduled evaluation |
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

**MR 5.** Deliver a small integrated path: saved verified synthetic inputs → completed
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
- **Evidently offline diagnostics.** Compare one declared reference/current window
  using retained feature/prediction data, and delayed labels only when available.
  Pin the reference, schema, metrics/tests and thresholds; save the report to ClearML.
  Exercise a known shift and missing-label case. Drift is a diagnostic finding, not
  evidence of strategy failure or an automatic retraining/activation instruction.
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

### Frozen baseline acceptance

**MR 8.** Run `p1-btcusdt-return-v1` unchanged against the permitted actual source
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

### Candidate packaging and runtime binding

**MR 10.** Freeze the [candidate contract](../architecture/platform-design.md#candidate-promotion-contract):
input requirements, features/preprocessing, optional model, signal-to-target policy,
state/warm-up rules and accepted experiment evidence. Retain artifact bytes as well
as hashes. A rule has no invented model artifact. Reuse the accepted components in
research and runtime applications; no translation into separate production formulas.

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
Reuse MR 7 Evidently reports for feature quality, distributions and model performance
where labels exist, keeping reference windows and thresholds versioned. Record stale,
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

Link realized performance and applicable Evidently findings to the exact deployed
candidate/model version and observation window in ClearML. Distinguish delayed
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
