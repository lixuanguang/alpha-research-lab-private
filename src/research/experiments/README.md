# Experiment attempts and temporal splits

Owner: repository founder. Updated 2026-09-20. **Implemented for bounded local
research.** The curated `research.experiments` API owns semantic identities,
earlier-only temporal folds and append-only execution history. It has no command.
`applications.explore.inspect_experiment` is the first working consumer, using
`research.exploration.ExplorationStudy` and the existing pinned research reader.
The [research program](../../../docs/roadmap/research-program.md) owns methodology;
[MR 2](../../../docs/roadmap/README.md#experiment-attempts-and-temporal-splits) owns
delivery acceptance. Feature/label generation, fitted transforms, model training,
economic reports, candidate promotion and deployment remain separate future work.

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
about label availability. No model training consumer is claimed by this delivery.

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
limit. Large artifact/report storage remains later work.

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
