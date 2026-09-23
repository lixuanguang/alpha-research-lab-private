# Research studies, diagnostics and reports

Owner: repository founder. Status: implemented for bounded local research;
updated 2026-09-23. This guide owns the `research.studies` records and the
comparison, diagnostic, report, publication and serial-pipeline consumers that
use them. The [experiment core](../experiments/README.md) owns semantic run
identity, temporal folds, holdout access and append-only attempt history. The
[research program](../../../docs/roadmap/research-program.md) owns methodology.

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

`research.results.FeatureStudyResult` owns the unchanged
`feature-study-result-v1` bytes shared by feature production, model admission
and diagnostics. `FeatureLabelPayload` remains an alias for existing callers.
Model admission retains its label, ordered-row and input-digest requirements;
diagnostics retain their own missing-label and aligned-row rules.

The saved L2 `BookReport` record belongs to the [saved L2 workflow](../../../docs/research/l2-book-backtest.md),
which documents its current bundle reader and compatibility with historical
reports. This page does not duplicate that report schema.

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
matching wheel/environment with retained v1 records; an older wheel cannot
consume newer records.

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

`WindowDiagnosticRun` verifies completed `feature-study-result-v1` bytes and
retained `model-evaluation-v1` artifacts, including scientifically rejected
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

`BacktestRun(schema_version="configured-engineering-sample-v1", split=None,
engineering_sample=TimeWindow(...), ...)` uses an explicit half-open UTC sample
exactly equal to `economics.start/end`; it has no train/validation/holdout
interval. Reports retain sample scope, missing observations and source limits.
A completed calculation is a software check, not empirical baseline acceptance
or strategy selection.

The frozen [P1 configurations](../../../configs/backtests/p1-btcusdt-return-v1.json)
remain unchanged `BacktestSpec` inputs. Pin the published snapshot and explicit
`ReportPolicy`; preserve the original no-interest benchmark. Engineering samples
use `experiment-engineering-sample-v1`, keep their own attempts/failures/outbox
and cannot consume holdouts. Parameter comparison and validation diagnostics
reject this mode. Existing v1 inputs omit the field and retain their identities.

## Ownership and verification

Keep attempt identity, split/holdout rules and atomic history in the
[experiment core](../experiments/README.md). Keep feature/label schemas in their
[owning guides](../features/README.md). Keep current notebook reader journeys in
the [QR guide](../../../examples/README.md), source-specific acquisition limits
in the [market-data guide](../../market_data/README.md), and historical evidence
in dated `docs/research/` records. Focused regressions and installed consumers
are the executable evidence; local service or synthetic results do not establish
empirical alpha, source coverage or production readiness.
