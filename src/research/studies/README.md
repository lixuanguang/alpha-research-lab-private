# Research studies, diagnostics and reports

Owner: repository founder. Status: implemented for bounded local research;
updated 2026-09-24. This guide owns the `research.studies` records and the
comparison, diagnostic, report, publication and serial-pipeline consumers that
use them. The [experiment core](../experiments/README.md) owns semantic run
identity, temporal folds, holdout access and append-only attempt history. The
[research program](../../../docs/roadmap/research-program.md) owns methodology.

Before starting or resuming a researcher-run study, run `make local-services-up`
from the repository root and complete the
[research-session prerequisites](../../../examples/README.md#before-every-research-session).
This workflow requirement includes studies with local or deferred publication;
it does not change the API's explicit transport behavior described below.

Integration SDKs load at their operations. Opening an attempt, local
report or research selection does not initialize ClearML, Optuna, DuckDB or
Polars; those dependencies load only when publication, parameter search,
pipeline execution or the selected columnar query runs. The exact financial-unit
codec retains its foundational pandas/NumPy dependencies.

```python
from research.studies import (
    BacktestRun,
    ClearMLDestination,
    ComparisonStudy,
    ResultManifest,
    WindowDiagnosticStudy,
)
```

`research.results.FeatureStudyResult` owns the `feature-study-result` bytes
shared by feature production, model admission and diagnostics.
Model admission retains its label, ordered-row and input-digest requirements;
diagnostics retain their own missing-label and aligned-row rules.

The saved L2 `BookReport` record belongs to the [saved L2 workflow](../../../docs/research/l2-book-backtest.md),
which documents its current bundle reader and compatibility with historical
reports. This page does not duplicate that report schema.

## Generalized decision studies

`applications.explore.evaluate_study` composes the MR02 named-input feature,
fitted-transform, estimator and policy contracts with the
[offline intent simulator](../../simulation/README.md#offline-decision-intent-studies).
It accepts a `DecisionStudy` value or a path to the same strict versioned JSON.
`StudyComponents` supplies the actual source, market reader, feature, policy,
optional transform/model/outcome reader, execution/cost models and metric/chart
implementations. Every configured identity must match; missing selections fail
without substituting a built-in implementation. This is an installed callable
API; the study runs whatever components the caller supplies, and configuration
never imports code. Operating services load extension components only from signed
installed distributions, as the [runtime guide](../../runtime/README.md#research-extensions)
describes.

`StudyFold` freezes training/evaluation schedules, an authored `TemporalSplit`
with an empty sample inventory, and a label-evaluation cutoff. The application
derives sample identities and information intervals from actual feature/outcome
bytes, retains the resolved split and fitting exclusions, and passes only
admitted earlier rows to fitting. Transform/model bytes are retained before
reload-only inference. Missing learned inputs are explicitly excluded;
unavailable labels retain their reasons in exact predictive diagnostics.
Feature/policy sessions and exact cash accounts start independently in every
fold. Up to 32 nonoverlapping evaluation folds and 8,192 decisions per schedule
are supported; this is bounded materialized research, not MR15 scale acceptance.

All folds share one frozen final holdout. Validation label cutoffs must precede
it. If validation ends where holdout begins, the inclusive market-input cutoff
stops one microsecond before that boundary; terminal valuation uses the last
fresh prior book. A `partition="holdout"` study has one fold and records
consumption before any source, feature, label or market read. Failed holdout
work remains consumed. The existing family store denies a changed run another
final-sample read; an identical run can reproduce its earlier access.

Custom implementations are trusted code, not sandboxed plugins. Retain external
source/package bytes as `StudyArtifact` values in `StudyComponents.artifacts`,
with matching `DecisionStudy.extensions` fingerprints. The application checks
digests, includes them alongside the installed distribution in experiment
identity, and retains the bytes before source access. An empty extension list
is appropriate only when the installed distribution contains all component code.
These checks cannot prove arbitrary supplied Python truthfully declares its
version or obeys its pure-transition protocol. MR06 owns trusted release admission.

Publication is explicit through `PublicationPolicy`:

- `local` retains attempts/reports without initializing tracking transport.
- `deferred` retains the existing ClearML destination/outbox before computation
  and returns local completion without contacting the server.
- `immediate` publishes after local completion. Transport failure propagates,
  while the completed result remains readable and retryable.

`applications.explore.publish_experiments(attempts)` retries retained outbox bytes
without reevaluating folds or consuming holdouts. Configured backtest consumers
take a ClearML destination and publish immediately, as shown below;
`ParameterComparison` takes a publication policy.

The following is the result-reading portion of a workflow after the caller
constructs its `components` through the public protocols:

```python
from pathlib import Path
from applications.explore import evaluate_study
from research.experiments import AttemptStore
from research.studies import DecisionStudy, PublicationPolicy, StudyReportReader, StudyResult

root = Path("/absolute/path/to/study")
history = evaluate_study(
    DecisionStudy.read(root / "study.json"),
    components=components,
    attempts=root / "attempts",
    publication=PublicationPolicy(mode="local"),
)
store = AttemptStore(root / "attempts")
result = StudyResult.read(store, history.start.attempt_id)
report = StudyReportReader.read(store, history.start.attempt_id)
```

Both readers require a completed `ResultManifest` and verify every committed
artifact digest. Results retain original configuration, actual inputs, resolved
splits, fitted bytes, predictions, decisions, feature/policy state, order outcomes
and exact ledgers. Reports retain versioned exact metrics, units, missingness,
selected charts and safe self-contained HTML/SVG. `MetricDefinition` and
`ChartDefinition` (with the report contracts below, imported from `research.reports`,
which the paper services also ship) consume a typed `ReportContext` of fold ledgers, sampled marks
and predictive diagnostics. Their identities and returned definitions must
match the selections. `NetReturnMetric` and `LedgerCurveChart` are explicit
reference choices. Initial/terminal NAV points do not describe intraperiod
drawdown; separate fold returns do not describe a continuous investment account.
The [research monitoring bridge](#research-monitoring-bridge) connects selected
diagnostics to the versioned telemetry API.

`applications.explore.compare_studies` accepts a typed/serialized
`DecisionComparison`, exact variant-to-`StudyComponents` bindings, an attempt
root, Optuna journal and publication policy. It reuses `ParameterComparison`.
Variants share source, folds, capital, report definitions, extension artifacts
and authored seeds. The exact objective is the arithmetic mean of independent
fold net returns; Optuna receives only its finite float projection. The 1–32
variant grid, total budget, sampler seed, rejection threshold and optional
pruning threshold are frozen. Search never reads holdout. Failures, interruptions,
exclusions, rejected/pruned trials and publication retries preserve original
attempts and consume their budget slots. Resumption requires identical code,
configuration and environment.

QRs start from the maintained [study example](../../../examples/qr_study.py) that
the [QR quickstart](../../../examples/qr-quickstart.md#4-write-and-run-a-study)
walks through: walk-forward folds, a frozen holdout, a fitted transform, an exact
estimator, a forward label, rule and learned policies, all from an installed
extension, over published captures.

The runnable [installed extension consumer](../../../tests/integration/consumers/research/decision_study.py)
authors fresh feature, estimator, strategy, metric and chart implementations,
exercises typed/JSON inputs, walk-forward fitting, exact losing/no-trade cases,
search recovery and failed holdout access, and reopens results in a fresh process.
The [captured-source consumer](../../../tests/integration/consumers/research/captured_study.py)
uses `SavedDecisionSource` and `CapturedStudyMarket` to reopen retained
OKX/Bitfinex trades, references and native books. Its invocation and evidence
belong to the [MR03 acceptance record](../../../docs/roadmap/README.md#mr03-delivery-and-acceptance).

`CapturedStudyMarket` reads one native partition of a published book snapshot
(snapshot identity and request identity). It verifies the snapshot against its
retained raw input once, when built, and each `read(window)` streams that window
row by row. A study consumes the rows once, in availability order, so memory is
bounded by one row and the execution model's near-term events, not the window.
Each fold retains `market-NNNN` as a `StudyMarketManifest` (market identity,
window, row count, first and last clocks, SHA-256 of the consumed rows), not a copy
of the rows: they are reproducible from the pinned snapshot. An optional `max_levels` keeps only the
best levels per side; that bound is a declared modeling assumption and part of the
market identity. It requires the original capture's research universe, preserving
the separate collection, research, strategy and trading declarations. A study's
instance/entity is an offline selection, not account authorization.
The explicit `receipt-as-matching` scenario models matching at the original
receipt clock, rounded upward to microseconds; native exchange timestamps remain
retained. Bitfinex visible orders are aggregated into depth without inferring
queue priority. No trade prints are invented, so these book-only source runs
cannot prove passive fills. Unknown archive receipts are refused. Source
coverage, venue execution, profitability and deployment remain separate claims.

Reversal removes these additive APIs and consumers together; existing BacktestRun,
book, feature/model and result schemas remain supported. Preserve new attempt
roots, original data, extension artifacts and the matching wheel. Older wheels
cannot read the new schemas; do not hand-edit retained identities as a migration.

## Inspect a retained saved-data study

`ExplorationStudy` names a family, research question, pinned
`ResearchSelection`, temporal split and `validation` or `holdout` partition.
Every selected input window must exactly equal its split partition; trade
business clocks and book receipt clocks retain their existing meanings. The
first consumer supports `fit_mode="none"`: it does not create features, labels
or synthetic training rows, and unsupported fitting fails explicitly.

The installed ingestion workflow creates `selection.json`, `study.json`,
`raw/`, `snapshots/` and `attempts/` in an explicit output directory. Reopen a
retained study with:

```python
from pathlib import Path

from applications.explore import inspect_experiment
from market_data.storage import RawStore

root = Path("/absolute/path/to/retained/output")
history = inspect_experiment(
    root / "study.json",
    root / "snapshots",
    RawStore(root / "raw"),
    attempts=root / "attempts",
)
print(history.start.run_identity, history.start.attempt_id, history.status)
```

A completed result retains the bounded dataset, trade summaries, split identity
and explicit fitting inapplicability. Native book values, source/quality evidence
and missingness stay typed; no implicit join, forward fill, currency conversion
or approximation is introduced. Input byte ceilings do not bound process RSS.

The consumer validates configuration and semantic identities before snapshot
reads, starts an attempt before computation and retains read/computation
failures, holdout reuse and abandoned work. A changed code/input/split identity
creates a new attempt. Existing `inspect_eda` remains an exploratory interface;
the attempt store cannot track arbitrary reads that bypass its consumer. Keep the
matching wheel/environment with retained records.

## Research monitoring bridge

`ReportMonitoringBridge` accepts a reviewed `MonitoringMetric`, an explicit
research scope and the actual UTC import `recorded_at`. It maps only diagnostics
whose names and exact units match the metric's `MetricSpec.inputs` into
`MonitoringEvent` facts. A `ReportObservation` has no knowledge or receipt
clock or input version; the reviewed metric supplies its selected input version.
Imported diagnostics first become available at `recorded_at` with
`clock_quality="unknown"`; the bridge does not backdate them to the observation
clock. `MonitoringIdentity.study` retains the report's study identity.

`ReportMetricAdapter` and `ReportChartAdapter` expose that same metric to the
existing `StudyReportBuilder`. The metric report identity is the complete
`MetricSpec.identity`, which includes its implementation digest, input versions,
units and missingness policy. The chart identity also binds its title and kind.
Exact metric points and explicit gaps become existing `MetricValue` and
`ChartSpec` observations; a chart requires at least one point. The bridge's
`events(context)` supplies the same facts to `TelemetryStore` and
`DashboardBuilder`, with no report or dashboard renderer customization.

`StudyMonitoringExporter.export(result, scope=..., recorded_at=...)` emits the
retained prediction and `Outcome` facts from a completed `StudyResult` under
distinct fold scopes. It preserves the actual fitted model, policy, source and
study identities in `MonitoringIdentity`. Both series use the retained source
feature identity and decision clock as their shared sample. With a fitted
transform, `Prediction.feature_identity` names the transformed vector instead;
the exporter resolves its unique source row by entity and decision clock and
checks the matching committed decision. Ambiguous mappings fail. Historical
predictions do not retain a separate knowledge clock, so import makes them
available at the explicit receipt with
unknown clock quality. Observed outcomes keep their genuine `Outcome.available_at`;
a pending outcome with no availability becomes a known gap only at import. Labels
share prediction sample, context and decision clock, enabling causal
`DelayedLabelError` queries. Use `export_outcomes` for a later label revision so
the original prediction receipt stays unchanged. `recorded_at` must be the
actual import receipt; it is not reconstructed from a historical decision time.

Run `PYTHONPATH=src .venv/bin/python -m pytest -q
tests/unit/research/test_study_reports.py tests/unit/research/test_study_monitoring.py`
for focused report and delayed-label checks. The installed
`tests/integration/test_study_workflow.py` consumer reopens a real retained
study, rebuilds its report context and verifies the same custom definition in
the retained report and research dashboard. The installed
`tests/integration/test_candidate_workflow.py` consumer reopens a committed
`PaperCandidateRuntime` step from its journal and exports its prediction and
source label with `CandidateMonitoringExporter`. It evaluates that same custom
metric in a paper dashboard before and after the label becomes available. The
authored paper scenario uses modeled clocks; a real producer must supply its
receipt clock explicitly. Select the `integration` marker for both installed-wheel
consumers.

## Bounded comparison and factor diagnostics

`ComparisonStudy` freezes 1–32 complete `BacktestRun` variants, one shared source,
validation/holdout split, report policy, selection/pruning thresholds, total
trial budget and an explicit `GridSampler` seed. `ParameterComparison` owns the
single serial Optuna controller and append-only journal. The installed command
composes causal reading, isolated rule instances, the exact ledger, a vectorbt
comparison and a retained QuantStats report:

```sh
alpha-backtest compare --config /absolute/study/comparison.json \
  --snapshots /absolute/study/snapshots --raw /absolute/study/raw \
  --attempts /absolute/study/attempts --journal /absolute/study/optuna.log \
  --tracking /absolute/study/tracking.json --max-bytes 2000000
```

`--max-trials` bounds one invocation and never increases the configured total.
Resume requires identical configuration, installed code and environment. Each
trial retains its variant fingerprint, source selection, exact objective, output
hashes and reason. Interrupted/pruned trials are abandoned and consume their
budget slot; rejected thresholds remain rejected; failed evaluations remain
failed. Publication failure leaves a durable outbox for retry. No final holdout
is read and no result is promoted.

The objective is exact validation net return. Float projection is confined to
Optuna and analytical reports; selected vectorbt results must already pass the
authoritative costed ledger. The comparison accepts local pinned snapshots and
refuses remote lakeFS materialization. A pipeline comparison stage uses the same
worker and writes `comparison-journal.jsonl`; changing an active grid requires a
new study and journal.

`applications.explore.compare_factors` verifies a completed feature-result
digest, preserves its temporal split and calls `AlphalensDiagnostics`. The study
declares universe, factor direction, outcome horizon, base-price convention,
groups/quantiles, demeaning/group adjustment and a knowledge cutoff. Reports
retain exclusions, late labels, IC, quantile returns and turnover. Equal-value
qcut drops and undersized samples retain explicit inapplicability; an intraday
fixture without a prior daily observation does not invent turnover. Factor
statistics do not measure executable economics.

## Model evaluations and ClearML publication

The [model contract](../models/README.md) owns exact predictive evaluations and
model artifacts over retained feature results. `ResultManifest` rechecks every
artifact digest. `AttemptStore.retain` atomically adds supplemental bytes,
including failed/rejected artifacts; identical retries succeed, changed
replacement bytes fail, and exported hard-link aliases are immutable until a
caller copies them for editing.

Formal model workflows require `ClearMLDestination`. Passing `tracking` opts a
consumer into the tracked workflow; unfitted local inspection remains compatible
without it. Publication intent is retained before computation. A transport
failure leaves local completion and append-only failure metadata visible;
`publish_experiments` uploads saved artifacts only and never refits, reruns a
study or consumes another holdout.

The adapter uses pinned ClearML `Task.create` with repository/requirements
discovery and instrumentation injection disabled. It never calls `Task.init` or
sends credentials. Manifests, typed artifacts and explicit outcome/selection
parameters are the published boundary. Dashboard metrics are finite binary-float
projections of retained exact values. Task names bind attempt IDs; model names
bind immutable version-manifest hashes; receipts bind remote IDs to terminal
history. Lost creation responses fail closed until the intended object/history is
reconciled.

The [local ClearML setup](../../../configs/development/clearml/README.md) owns
server start/stop and backup. Local service evidence does not qualify a shared
service, artifact release or deployment.

## Offline window diagnostics

`WindowDiagnosticStudy` freezes source `DiagnosticSource` attempt IDs/digests,
reference/current half-open UTC decision windows inside validation, the original
feature split, inclusive label-evaluation cutoff, minimum counts, KS thresholds
and an exact MSE limit. The cutoff and every observation information interval
must precede the holdout. There is no fit, search, candidate selection or
automatic operational transition.

`WindowDiagnosticRun` verifies completed `feature-study-result` bytes and
retained `model-evaluation` artifacts, including scientifically rejected
evaluations, their splits/sample records, source references and model state.
Failed/incomplete or holdout-consuming sources are refused. Feature sources share
the declared split and definitions; prediction sources preserve validation/
holdout windows and reference the same feature bytes. The bounded consumer
supports 1,024 rows and at most 16 sources per role per instrument. It does not
invent predictions, labels, fitted state or arbitrary dataframe schemas.

`WindowDiagnostics` calls the admitted SciPy `ks_2samp` with
`alternative="two-sided", method="exact"`. Warnings/fallbacks fail. Finite
float projections of exact ratios produce descriptive CDF distance/p-values;
drift is true only when both `D >= ks_statistic_threshold` and
`p <= ks_pvalue_threshold`. Temporal dependence, ties and unadjusted multiple
tests prevent inferential or empirical strategy claims. Thresholds are authored
before execution.

Predictive MSE is exact rational
`mean((prediction - forward_return) ** 2)`. Only complete predictions whose
labels are known by `evaluated_as_of` enter the metric. Missing, unknown or late
labels remain excluded with reasons; `predictive_metric="inapplicable"` requires
a reason and does not disable feature diagnostics.

`applications.explore.compare_windows` retains complete upstream inputs,
selections/snapshots, model versions, source attempts, schemas/units, split and
availability policy before computation. Repository JSON and self-contained HTML
retain metric definitions, thresholds, counts, exclusions and numerical results.
They are repository reports, not Evidently output. Local bytes survive
publication failure and `publish_experiments` retries those bytes without
redoing research. Use the [study protocol](../../../examples/study-protocol.md#time-comparisons-and-uncertainty) to define comparison periods and information boundaries.

## Configured economics, reports and serial pipelines

`BacktestRun` is the strict bounded JSON contract for the installed configured
economic workflow. It selects an existing snapshot, `BacktestSpec`, explicit
benchmark, `ReportPolicy`, optional `TrailingReturn` diagnostic and a no-fit
validation split. Unknown fields/rules, unaligned benchmark periods and
holdout/fitting configurations fail before work. The first rule needs no model
construction, labels or learned state.

The installed consumer creates `configured.json`, `tracking.json`, `raw/`,
`snapshots/` and attempt stores from explicit synthetic fixtures. With those
files at `$RUN`:

```sh
alpha-backtest run --config "$RUN/configured.json" \
  --snapshots "$RUN/snapshots" --raw "$RUN/raw" \
  --attempts "$RUN/configured-attempts" --tracking "$RUN/tracking.json" \
  --max-bytes 2000000
alpha-backtest export --attempts "$RUN/configured-attempts" \
  --attempt-id "$ATTEMPT" --output "$RUN/report.html"
alpha-backtest publish --attempts "$RUN/configured-attempts" \
  --attempt-id "$ATTEMPT" --tracking "$RUN/tracking.json"
```

The tracking destination is mandatory and credentials remain in private SDK
configuration. Exit 0 acknowledges success, 2 invalid inputs, 4 execution or
publication failure and 130 interruption. `publish` retries an existing mapping
without rerunning economics; the command never downloads a source or benchmark.

`--stop-at` retains a complete checkpoint in an abandoned attempt;
`checkpoint` exports it and `run --resume` starts a new attempt. Configuration,
installed code, environment, rule, report assumptions, split and data version
must agree. Successful runs commit verified inputs, derived features, exact
economic trace, report inputs, typed report and self-contained HTML before the
completed manifest. Atomic exports refuse replacement with different bytes.

QuantStats receives retained net simple returns and the explicitly aligned
benchmark. Exact terminal return, turnover, fees, slippage, NAV and P&L remain
ledger-derived. Missing valuations or quality reasons withhold aggregate return,
benchmark, drawdown and exposure; period counts describe periods, not trades.
Cadence, annualization, risk-free assumption, UTC timezone and missing policy
remain in the report. This slice does not estimate Sharpe or annualized
performance.

`prepare` verifies the dataset/features, and `pipeline` composes that step with
the same economics/report workflow through a dedicated serial local ClearML
agent. It verifies the installed wheel and retains controller/step IDs, upstream
attempt results and configuration/feature bytes. A failed step prevents
dependent completion; a fresh pipeline is recovery. The [local agent guide](../../../configs/development/clearml/README.md#serial-installed-research-worker)
and [lakeFS guide](../../../configs/development/lakefs/README.md) own service
fixtures. No shared-service, deployment or trading authority is added.

## Unfitted engineering samples

`BacktestRun(schema_version="configured-engineering-sample", split=None,
engineering_sample=TimeWindow(...), ...)` uses an explicit half-open UTC sample
exactly equal to `economics.start/end`; it has no train/validation/holdout
interval. Reports retain sample scope, missing observations and source limits.
A completed calculation is a software check, not empirical baseline acceptance
or strategy selection.

The frozen [P1 configurations](../../../configs/backtests/p1-btcusdt-return.json)
remain unchanged `BacktestSpec` inputs. Pin the published snapshot and explicit
`ReportPolicy`; preserve the original no-interest benchmark. Engineering samples
use `experiment-engineering-sample`, keep their own attempts/failures/outbox
and cannot consume holdouts. Parameter comparison and validation diagnostics
reject this mode. Other specs record `engineering_sample` as null.

## Ownership and verification

Keep attempt identity, split/holdout rules and atomic history in the
[experiment core](../experiments/README.md). Keep feature/label schemas in their
[owning guides](../features/README.md). Keep current notebook reader journeys in
the [QR guide](../../../examples/README.md), source-specific acquisition limits
in the [market-data guide](../../market_data/README.md), and historical evidence
in dated `docs/research/` records. Focused regressions and installed consumers
are the executable evidence; local service or synthetic results do not establish
empirical alpha, source coverage or production readiness.

## Scheduled studies and reproducible workspaces

`applications.explore.schedule_study` submits a typed `DecisionStudy` and a local
or deferred `PublicationPolicy` to `runtime.JobQueue`. `StudyJobHandler` resolves
explicit `StudyComponents` by the study identity; it verifies the installed
implementation, dependency environment, configuration and both decision/economic
source identities before work. The [runtime guide](../../runtime/README.md) owns
queue scheduling, concurrency, cancellation, progress and backup interfaces.
Distinct study families can run concurrently. Each family retains one exclusive
attempt store, preserving its frozen holdout and unsuccessful attempts across jobs.
A competing writer retries through the bounded queue rather than mutating that store.

`evaluate_study(..., idempotency_key=...)` adds optional lost-acknowledgement
recovery. A completed result is validated and reopened for the same key, exact
run and publication policy. Changed selections under the key fail. Interrupted
attempts become abandoned before another attempt begins; their holdout access
and artifacts remain retained. Without a key, repeated invocations continue to
create separate attempts. A job can finish its bounded study after cancellation
is requested; cancellation prevents queue-result publication, not reversal of
already retained research evidence. Remote publication remains an explicit
`publish_experiments` operation through the existing idempotent ClearML outbox.

The [installed study consumer](../../../tests/integration/consumers/research/decision_study.py)
now injects an acknowledgement loss after the actual study completes. It requires
two job attempts to retain exactly one completed study, then verifies a backup
restored into an absent workspace reopens the same queue and typed results. Copy
that consumer and its sibling `research_workflows/` support directory outside the
checkout, preserving the directory name, and run with the installed interpreter:

```sh
/absolute/core/bin/python -I /absolute/decision_study.py /absolute/fresh-workspace
```

The generated `workspace/jobs` and `workspace/studies` directories are selected
explicitly for `WorkspaceBackup.create`. Keep separately pinned source inputs,
installed artifacts and compatible worker locks with their owners; a local
workspace manifest does not replace the lakeFS commit or ClearML remote record.
Current service evidence and outstanding deployment/capacity boundaries are in
[MR04](../../../docs/roadmap/README.md#mr04-delivery-and-acceptance).
