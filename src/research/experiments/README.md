# Experiment attempts and temporal splits

Owner: repository founder. Updated 2026-09-23. **Implemented for bounded local
research.** The curated `research.experiments` API owns semantic identities,
earlier-only temporal folds and append-only execution history. It has no command.
`applications.explore.inspect_experiment` is its first working consumer, using
`research.exploration.ExplorationStudy` and the existing pinned research reader.
The [research program](../../../docs/roadmap/research-program.md) owns
methodology; [MR 2](https://github.com/lixuanguang/alpha-research-lab-private/blob/31fcc842fa5a55daafe0764dd4d99912d082329c/docs/roadmap/history-mr1-to-mr9a.md#experiment-attempts-and-temporal-splits)
owns delivery acceptance. Feature/label definitions, model evaluations,
comparisons, diagnostics, configured reports and pipelines have their own
[study guide](../studies/README.md).

## Import boundary

The package exports only the lightweight records needed to describe and retain
an experiment:

```python
from research.experiments import (
    AttemptStore,
    ExperimentSpec,
    Fingerprint,
    TemporalSplit,
    TimeWindow,
)
```

Comparison, reporting, diagnostics, pipeline and ClearML types belong to the
curated `research.studies` API:

```python
from research.studies import ClearMLDestination, ComparisonStudy, ResultManifest
```

This replaces their former `research.experiments` imports; maintained callers
and examples migrated together without changing retained record schemas.
Opening an attempt store does not initialize ClearML, Optuna or study
implementations. `research.results.FeatureStudyResult` retains the unchanged
`feature-study-result-v1` shape shared by feature production, model admission
and diagnostics. Existing `research.studies.FeatureLabelPayload` callers remain
supported as an alias.

## Reproducible inputs and execution attempts

`ExperimentSpec.identity` hashes versioned input and component fingerprints,
resolved non-secret parameters, named integer seeds, environment identity and
the full temporal split. Named maps and sample order are deterministic. Sample
records include input/label byte digests; the supplying consumer verifies those
bytes and declares their true intervals. Changing data, components, parameters,
seeds, environment or split choices changes the run. A digest identifies bytes;
it does not retain or prove their availability.

`ExplorationStudy` binds its `ResearchSelection.identity`, question, partition
and split to the installed `ImplementationIdentity`, interpreter, platform and
distribution versions. The reader re-verifies saved source and snapshot bytes;
resource caps and batch sizes remain part of the original selection contract.
The deterministic no-fit inspection has an empty seed map because it performs no
random computation.

Each `AttemptStore.start` creates a separate UUID execution ID. Output locations,
invocation paths, execution timestamps and generated result bytes do not enter
semantic identity. Original request bytes and invocation are retained as attempt
metadata. Repeating a run retains another attempt and never overwrites a failed
or successful one. A completed software result does not by itself meet an
empirical research criterion.

## Temporal contract and fitting

`TimeWindow` assigns decisions to UTC **[start, end)** intervals. Validation ends
no later than holdout starts. A fitting fold ends no later than its fit cutoff,
which ends no later than validation starts. The API consumes declared folds; it
does not choose splits or tune research parameters.

`SampleInterval` records a unique row ID, byte digest, decision time, closed
information interval, feature availability and optional label availability. The
information interval includes lookback, label, publication and execution
information. Label availability cannot precede the information end; unknown
availability is `None`, never an assumed event-time clock.

`TemporalSplit.fitting_rows()` returns deterministic eligible records ordered by
decision time and row ID. It excludes decisions outside training, unavailable
features, information ending after the fit cutoff, and unknown/late labels.
Purging protects every validation/holdout information interval, including
lookbacks; closed endpoint ties are rejected. A nonnegative integer-microsecond
`embargo_us` adds a conservative gap around protected information, with zero
allowed only for an authored rationale.

Consumers select actual values by admitted IDs and call `require_fit_rows(ids)`
immediately before fitting. It rejects empty, duplicate or forbidden IDs. The API
cannot police unrelated files or infer whether a caller described availability
truthfully. `fit_mode="features"` permits train-only fitting while checking
feature clocks; `fit_mode="none"` requires no training rows or fit cutoff and
returns no fitting rows. Rules and inspection studies retain why fitting is
inapplicable instead of manufacturing training data.

## Holdout consumption and atomic outcomes

Use one retained `AttemptStore` root for an experiment family. Its first start
atomically freezes the family's final holdout window. A changed window is a
retained rejected attempt; new untouched evidence requires a new family. Moving
or deleting history, renaming a family or reusing holdout observations does not
make evidence untouched. This is a trusted local workflow boundary, not a global
access-control service.

Call `consume_holdout` before exposing final evaluation values. The access event
survives failed reads, abandonment and process death. A different semantic run
cannot consume the same family holdout; an unchanged run may record another
access for reproduction. Earlier validation attempts remain visible and do not
claim untouched final OOS.

`finish` records immutable `completed`, `failed`, `rejected` or `abandoned`
states. Completion includes all result bytes in one JSON event: bytes are staged,
flushed, atomically renamed and directory-synced before the terminal record.
Incomplete staging never counts as completion; a start without a terminal event
is `incomplete`, even after holdout consumption.

If publication raises after a rename, reload the attempt to determine actual
state before recording a failure. A crashed attempt may be marked abandoned with
a reason; reproduction uses a new attempt. `publish_experiments` in the
[studies guide](../studies/README.md) retries retained bytes and never reruns
research.

`with AttemptStore(root)` holds a nonblocking POSIX advisory writer lock for the
workflow. A competing writer fails with `BlockingIOError`; read-only inspection
needs no lock, and process death releases the lock. This initial contract
supports one local writer on macOS/Linux and concurrent readers of a committed
prefix. Network filesystems, hostile mutation, multi-host coordination,
corruption recovery and power-loss qualification are outside the boundary.
Back up the complete root together with raw/snapshot and implementation artifacts.

## Inspect a retained saved-data study

Study-specific inspection and its executable example moved to the [studies
guide](../studies/README.md#inspect-a-retained-saved-data-study). This anchor is
kept so historical links continue to land on the owning page.

## Bounded comparison and factor diagnostics

Comparison and factor diagnostics moved to the [studies guide](../studies/README.md#bounded-comparison-and-factor-diagnostics).
The experiment core still supplies their semantic attempt, split and holdout
boundaries.

## Model evaluations and ClearML publication

Model evaluation, artifact manifests and ClearML publication moved to the [studies
guide](../studies/README.md#model-evaluations-and-clearml-publication); exact
model state remains documented by the [model contract](../models/README.md).

## Offline window diagnostics

The diagnostic study/run contract and report publication moved to the [studies
guide](../studies/README.md#offline-window-diagnostics). This pointer preserves
the historical anchor while the owning package documents thresholds, exclusions
and availability rules.

## Configured economics, reports and serial pipelines

Configured `BacktestRun`, report policies, checkpoint/export/retry semantics and
serial pipelines moved to the [studies guide](../studies/README.md#configured-economics-reports-and-serial-pipelines).
The experiment core continues to own their attempt identity and holdout policy.

## Unfitted engineering samples

Engineering-sample mode moved to the [studies guide](../studies/README.md#unfitted-engineering-samples).
It remains a distinct no-holdout software sample and cannot be converted into a
validation family to bypass evidence controls.
