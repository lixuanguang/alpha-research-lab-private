# Experiment attempts and temporal splits

Owner: repository founder. Updated 2026-09-21. **Implemented for bounded local
research.** The curated `research.experiments` API owns semantic identities,
earlier-only temporal folds and append-only execution history. It has no command.
`applications.explore.inspect_experiment` is the first working consumer, using
`research.exploration.ExplorationStudy` and the existing pinned research reader.
The [research program](../../../docs/roadmap/research-program.md) owns methodology;
[MR 2](../../../docs/roadmap/README.md#experiment-attempts-and-temporal-splits) owns
delivery acceptance. The same application now retains
[versioned feature/label diagnostics](../features/README.md) through `FeatureStudy`.
The [model workflow](../models/README.md) now consumes these retained boundaries.
Configured economic reports and local serial pipelines are implemented below. Candidate
promotion and deployment remain separate future work.

## Bounded comparison and factor diagnostics

`ComparisonStudy` freezes 1–32 complete `BacktestRun` variants, one shared source,
validation/holdout split and report policy, exact selection/pruning thresholds,
total trial budget and an explicit GridSampler seed. `ParameterComparison` owns
the single serial Optuna controller and append-only journal. The existing
`alpha-backtest compare` action composes the causal reader, isolated rule instances,
exact ledger, vectorbt comparison and retained QuantStats report:

```sh
alpha-backtest compare --config /absolute/study/comparison.json \
  --snapshots /absolute/study/snapshots --raw /absolute/study/raw \
  --attempts /absolute/study/attempts --journal /absolute/study/optuna.log \
  --tracking /absolute/study/tracking.json --max-bytes 2000000
```

`--max-trials` bounds one invocation; it never increases the configured total
budget. Resume requires identical configuration, installed code and environment.
Keep the journal and complete attempt store together. Each trial has an immutable
attempt mapping, source selection, exact objective, partial outputs and reason.
Interrupted/pruned trials are abandoned, rejected thresholds remain rejected,
and failed evaluations remain failed. An interrupted journal trial consumes its
budget slot and cannot become a successful full evaluation. Accepted trials have
all output hashes committed before publication; ClearML receipts map attempt and
task identities. Each trial retains its actual variant configuration fingerprint;
ClearML exposes the trial number, rule, instance and exact net-return ratio, plus
a finite dashboard projection. Publication failure leaves the durable outbox
available for retry.

`alpha-backtest pipeline --comparison-config /absolute/study/comparison.json`
adds a serial comparison stage after verified inputs and the complete economic
run. It uses the same installed worker and stores `comparison-journal.jsonl` in
the selected output root. Reusing that root resumes the frozen trial budget;
new controller executions preserve original trial/task associations. The first
variant must equal the pipeline configuration. Changing a comparison in the UI
requires a new declared study and journal, rather than editing an active grid.

The objective is exact validation net return. Float projection is confined to
Optuna and analytical reports. No final holdout is read, no result is promoted,
and selected vectorbt outcomes have already passed through the authoritative
costed ledger. This initial comparison accepts local pinned snapshots; remote
lakeFS materialization is explicitly refused. The existing configured run/pipeline
retains its separately qualified lakeFS behavior.

`applications.explore.compare_factors` verifies a completed feature-result digest
and preserves its temporal split before calling `AlphalensDiagnostics`. The study
declares universe, ascending/descending factor direction, outcome horizon, frozen
base-price convention, groups, quantiles, demeaning/group adjustment and an explicit
knowledge cutoff. Alphalens receives projected exact factor/forward-label pairs;
future labels are never feature columns. JSON/HTML reports retain exclusions,
late labels, IC, quantile returns and turnover. Equal-frequency qcut can drop tied
cross-sections; undersized samples have an explicit inapplicability reason.
Turnover follows Alphalens' daily resampling convention; an intraday fixture
without a prior daily observation retains unavailable turnover values, not invented
zeroes. These factor statistics do not measure executable strategy economics.

The [installed feature consumer](../../../tests/integration/consumers/research/feature_study.py)
and [installed economic consumer](../../../tests/integration/consumers/backtest/economic_workflow.py)
exercise these paths and optionally round-trip actual ClearML artifact bytes when
`ALPHA_CLEARML_LOCAL_ENV` is supplied. Without that private configuration the
transport-failure tests establish local retention only. The maintained
[QR activity notebook](../../../examples/research-foundations.ipynb) retains a
rule-only comparison without fitting. Exact final verification and blockers are
owned by [MR 7](../../../docs/roadmap/README.md#research-comparison-and-extension).

## Reproducible inputs and execution attempts

`ExperimentSpec.identity` hashes versioned input and component fingerprints,
resolved non-secret parameter text, explicit named integer seeds, environment
identity and the full temporal split identity. Named maps and sample order do not
change the digest. Sample records include a digest of their input/label bytes;
the supplying consumer must verify those bytes and describe their true intervals.
Changing data, components, parameters, seeds, environment or split choices changes
the run. Digests identify bytes; they do not retain or prove availability of them.

An `ExplorationStudy` binds its actual `ResearchSelection.identity`, question,
partition and split to the installed `ImplementationIdentity` and interpreter,
platform and installed distribution versions. The reader re-verifies saved source
and snapshot bytes. Resource caps and batch sizes follow the existing selection
identity contract and are retained in the original request. The deterministic
inspection has an empty seed map because it uses no random computation.

Each `AttemptStore.start` creates a separate UUID execution ID. Output locations,
invocation paths, execution timestamps and generated results never enter the
semantic identity. Original request bytes and invocation are retained as attempt
metadata. Repeating a run retains another attempt; it never overwrites a failed
or successful one. The same run can produce a completed software result without
meeting any empirical research criterion.

## Temporal contract and fitting

`TimeWindow` assigns decisions to UTC **[start, end)** intervals. Validation ends
no later than holdout starts. A fitting fold requires training to end no later
than its explicit fit cutoff, and that cutoff no later than validation starts.
Compose multiple declared folds for rolling or nested work; this API does not
choose splits or tune research parameters.

`SampleInterval` records a unique row ID, byte digest, decision time, closed
information interval, feature availability and optional label availability. The
information interval includes all relevant lookback, label, publication and
execution information. Label availability cannot precede the information end.
Unknown label availability is `None`, never an assumed event-time clock.

`TemporalSplit.fitting_rows()` returns deterministic eligible records, ordered by
decision time and row ID. `exclusions()` retains the first refusal reason per row:

- Decisions outside the training partition cannot enter fitting.
- Features unavailable at their decision, information ending after the fit cutoff,
  and supervised labels unknown or late at that cutoff are excluded.
- Purging protects the declared evaluation windows and every validation/holdout
  sample's full information interval, including lookbacks. Protection is closed
  at both ends, conservatively rejecting exact endpoint ties.
- An explicit nonnegative `embargo_us` adds a symmetric conservative gap around
  that protected information; equality with the gap is excluded. Zero is allowed
  with a stated rationale. The initial bound is one year, in integer microseconds.

Consumers select actual values by admitted identities and call
`require_fit_rows(ids)` immediately before fitting. It rejects empty, duplicate
or forbidden IDs. The API cannot police arbitrary code reading unrelated files.
It does not infer information intervals or verify that a caller told the truth
about label availability. The model consumer verifies real result digests and sample records before fitting.

`fit_mode="features"` supports train-only fitting without labels; it still
checks feature and information clocks. `fit_mode="none"` requires both training
and fit cutoff to be absent and returns no fitting rows. Rules and inspection
studies document why fitting is inapplicable instead of manufacturing training.
The hand-authored [examples](../../../tests/unit/research/test_experiments.py)
admit only two early rows, including a label available exactly at cutoff, while
excluding late/unknown labels, future features, holdout/future rows, overlapping
horizons and the exact embargo edge.

## Holdout consumption and atomic outcomes

Use one retained store root for the complete related experiment family. Its first
start atomically freezes that family's final holdout window. A changed window
produces a retained rejected attempt; new untouched evidence requires an explicit
new family. Moving or deleting history, renaming a family to evade its history,
or reusing holdout observations in another study does not make evidence untouched.
This is a trusted local workflow boundary, not a global access-control service.

Call `consume_holdout` **before** exposing final evaluation values. A durable
access event survives failed reads, later failures, abandonment and process death.
Once a semantic run consumes a family's holdout, a different run cannot consume
it. An unchanged run may retain another access for reproduction. Environment or
component changes also change the semantic run and are refused at this boundary.
Earlier validation attempts remain visible and do not claim untouched final OOS.

`finish` records `completed`, `failed`, `rejected` or `abandoned`. Terminal states
are immutable. Completion includes all result bytes in the same JSON event:
bytes are staged and flushed before atomic rename, then the directory is synced.
Incomplete staging files never count as completion. A start with no terminal
event is `incomplete`, even when a holdout was consumed or result staging exists.
Readers validate semantic identities, schemas and contiguous state transitions.

If publication raises after a rename, reload the attempt to resolve its actual
state before deciding whether a failure can be recorded. A crashed attempt can
be explicitly marked abandoned with a reason; use a new attempt to reproduce it.
Preserve failure reasons and staging evidence as needed. The implementation does
not automatically resume arbitrary study computation or erase abandoned work.

`with AttemptStore(root)` holds a nonblocking POSIX advisory writer lock for the
whole workflow. Another writer fails with `BlockingIOError`; read-only inspection
needs no lock. Process death releases the writer. This initial contract supports
one local writer on macOS/Linux and concurrent readers observing a committed
prefix. Network filesystems, external concurrent mutation, hostile code,
multi-host coordination, storage corruption recovery and power-loss qualification
are outside this delivery. Retain and back up the whole root, including family
metadata, plus actual raw/snapshot and implementation artifacts.

## Inspect a retained saved-data study

`ExplorationStudy` names a family, research question, pinned selection, temporal
split and either `validation` or `holdout`. Every input's selected time window must
exactly match the chosen split partition. Trade business clocks and book receipt
clocks keep their existing meanings. The consumer only supports `fit_mode="none"`;
unsupported fitting fails explicitly. It does not create features, labels or
synthetic training rows.

The existing [installed ingestion workflow](../../../tests/integration/consumers/datasets/ingestion_workflow.py)
creates `selection.json`, `study.json`, `raw/`, `snapshots/` and `attempts/` in its
explicit output directory. Given those retained inputs, the supported invocation is:

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

A completed event's `result` contains UTF-8 JSON with the full bounded dataset,
trade summaries, split identity and explicit fitting inapplicability. Native book
values, source/quality evidence and missingness are retained; no implicit join,
forward fill, currency conversion or numerical approximation is introduced.
Complete output is materialized in memory; input byte ceilings are not an RSS
limit. Large-study scaling remains later work.

The consumer starts a retained attempt after strict configuration/identity
validation and before snapshot reads. Malformed or oversized configuration, an
unavailable retention root or writer contention fail before work starts. Valid
attempts retain read/computation failures; holdout reuse is retained as rejection.
Existing `inspect_eda` and its callback reports remain compatible exploratory
interfaces. Calling that unrestricted exploratory interface on a final holdout
still consumes evidence under the research policy; this store cannot track reads
that bypass its consumer.

Verification covers independent temporal examples, deterministic reload and
identity sensitivity, writer contention, failed/rejected/abandoned history,
consumed holdouts, real process interruption before completion and the installed
multi-input study repeated in a fresh process. Exact commands/results live in the
roadmap and implementation PR. Reverting the implementation leaves retained v1
records intact; the prior wheel cannot consume these new records. Keep the matching
wheel/environment for reproduction. No deployment or trading authority is added.

## Model evaluations and ClearML publication

The [model consumer](../models/README.md) adds exact predictive evaluations and
usable model artifacts to this same single-writer root. `retain` atomically adds
supplemental bytes, including artifacts belonging to failed/rejected executions;
an identical retry succeeds and different replacement bytes fail. `artifact` and
`artifacts` reopen only committed records. Terminal attempt events and holdout
history retain their original schemas and immutability.

Formal model workflows require `ClearMLDestination`. Existing unfitted
`inspect_experiment` callers retain compatibility; passing `tracking` opts that
invocation into the same tracked workflow. Legacy local exploration with no
tracking argument remains explicitly local. No-fit workflows need no model
artifact or invented training window.

Publication intent is saved before computation. Local completion and external
publication are distinct: a transport failure propagates and remains visible in
append-only `clearml-failure-*` metadata, while successful local state survives.
`publish_experiments` uses saved artifacts only; it never refits, reruns a study or
consumes another holdout. An incomplete attempt requires explicit abandonment.

The adapter uses pinned ClearML 2.1.12 `Task.create` with repository discovery,
requirements discovery and instrumentation injection disabled. The publication adapter never calls
`Task.init`, enables framework/argument/stream/resource capture, scans credentials,
or treats SDK task reuse as a new execution. Only the explicit non-secret retained
manifest, typed artifacts and searchable outcome/selection parameters are sent.
Dashboard MSE is a finite binary-float projection of the retained exact ratio.
Credentials stay in SDK configuration; endpoint/project identities are retained
and the resolved SDK API host must match the recorded destination.

Task names bind attempt IDs, while model names bind immutable version-manifest
hashes. Each new execution gets a new task. Creation intent precedes the remote
request; retries first query the existing task/model, verify uploaded bytes and
model associations, and save a receipt. Completed server tasks are reconciled
without reset or edits. The immutable manifest remains authoritative even though
ClearML model metadata is mutable. Input-model records link evaluations to the
same published state; output-model records identify construction. A receipt binds
server IDs to the exact terminal history. Existing receipts make replay a local
no-op; they are not a claim of ongoing server availability or integrity.

If a creation response is lost and reconciliation finds no object, publication
fails closed instead of guessing that creation never happened. Preserve the intent
and investigate the server; restore the missing object/history before retrying.
The adapter provides no automatic reset or recreate operation. Multiple matches or changed
remote bytes also fail. The initial adapter assumes the existing single-writer
store and no concurrent external writer creating the same execution names.

The [local Docker setup](../../../configs/development/clearml/README.md) owns
server start/stop and backup instructions. Local integration proves the selected
self-hosted SDK boundary; it does not qualify a shared service or clear the repository's artifact-release
restriction. The separately pinned local agent below executes configured research.

## Configured economics, reports and serial pipelines

`BacktestRun` is the strict, bounded JSON contract for the installed
`alpha-backtest` command in `applications.backtest`. It selects an existing
snapshot, `BacktestSpec`, explicit benchmark and `ReportPolicy`, optional existing
`TrailingReturn` diagnostic, and a no-fit validation split. Unknown fields, rules,
unaligned benchmark periods and holdout/fitting configurations fail before work.
This first economic rule needs no model construction, labels or learned state.
The feature snapshot is a causal diagnostic; it does not substitute a different
formula into the reviewed completed-price rule.

The [installed acceptance consumer](../../../tests/integration/consumers/backtest/economic_workflow.py)
creates `configured.json`, `tracking.json`, `raw/`, `snapshots/`, and attempt
stores from explicit synthetic fixtures. With those files retained at `$RUN`:

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

The tracking destination is mandatory; credentials remain in private SDK
configuration. Exit codes are 0 for acknowledged success, 2 for invalid inputs,
4 for execution/publication failure, and 130 for interruption. Local terminal
history is authoritative even when external publication fails. `publish` retries
that attempt's existing mapping without rerunning economics. The command never
implicitly downloads a source or benchmark.

Add `--stop-at 2024-06-01T00:02:00Z` to retain a full checkpoint in an abandoned
attempt. `alpha-backtest checkpoint --attempts ... --attempt-id ... --output ...`
exports it; `run --resume ...` starts a new attempt. Full configuration, installed
code and environment identities must agree. A changed rule, report assumption,
split or data version invalidates resumption. Output locations do not affect
semantic identity. Retain the exact wheel and lock alongside attempts.

Every successful run commits the resolved configuration, verified research
inputs, derived features, exact economic reference/trace, report inputs, typed
report and self-contained HTML before writing its completed result manifest.
`ResultManifest.read` rechecks every referenced digest. Atomic exports refuse
replacement with different bytes. Interrupted publication may leave staged or
partial artifacts, but no completed result. Original failed attempts stay failed.

QuantStats 0.0.81 receives only retained net simple returns and the explicitly
aligned benchmark. Initial wealth is anchored at one, including before the first
loss. Independent `+10%, -20%, +25%` periods compound to `+10%` with a `-20%`
peak-to-trough drawdown. Exact terminal return, turnover divided by initial cash,
fees, adverse slippage, NAV and P&L remain ledger-derived. Approximate QuantStats
return must match exact return within `1e-12` absolute/relative tolerance.
Drawdown and maximum exposure use scheduled valuation closes; they cannot claim
intraperiod extrema. Counts describe winning/losing/flat **periods**, never trades.
Missing valuations and quality reasons stay visible; missing adjacent returns
withhold aggregate sampled return, benchmark, drawdown and maximum exposure.
Cadence, annualization, risk-free assumption, UTC timezone and missing policy are
retained. This slice does not estimate Sharpe or annualized performance.

`prepare` selects and verifies the existing dataset and optional features.
`pipeline` composes that step followed by the same complete economics/report
workflow, using a dedicated serial local ClearML agent. It captures the actual
installed implementation/environment and verifies owned bytes against an explicit
wheel. Agent scripts only hand off to this installed command; requirements
inference, caches and automatic retries are disabled. Each execution has fresh
controller/step task IDs and attempt IDs. Steps retain their controller/task links,
actual server-resolved `Run/configuration`, exact upstream attempt result and
configuration/feature bytes. A downstream configuration mismatch fails visibly.
To override a shared input in the UI, change both step configurations consistently
before dispatch; the resulting semantic identities change. A failed step prevents
dependent completion. A fresh pipeline is recovery, preserving the first failure.

See the [local agent guide](../../../configs/development/clearml/README.md#serial-installed-research-worker)
and [lakeFS guide](../../../configs/development/lakefs/README.md) for the explicitly
bounded service fixtures. Model/report artifacts remain in ClearML; lakeFS pins
only dataset/source and derived feature bytes. New storage commits never replace
market availability clocks. No shared-service, deployment or trading authority is
added. Revert command/owners, lock/admission, stubs and tests together; retain old
attempts, matching wheels, data versions and private service backups for replay.
