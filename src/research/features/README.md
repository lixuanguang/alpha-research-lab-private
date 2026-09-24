# Versioned features and research lifecycle

Owner: repository founder. Implemented bounded research contract, 2026-09-20.
`research.features` owns `TrailingReturn` and its shared `WindowPolicy`;
[`research.labels`](../labels/README.md) owns separate forward outcomes.
`research.exploration.FeatureStudy` aligns them with saved inputs and temporal
partitions. The existing `applications.explore.inspect_experiment` orchestrates
admission, installed identities, retained attempts and holdout consumption.
The observed-trade study introduces no model, strategy, fit, incremental engine
or deployment. The separate scheduled completed-price path is documented below.

## Generalized feature lifecycle

Owner: quant development. Implemented research SDK, 2026-09-24. The original
observed-return, completed-price, scheduled and Feast bridge contracts below
remain supported. `FeatureSchema`, `FeatureKernel`, `FeatureSession` and
`FeatureVector` add an independent generalized schema; they do not force custom
implementations into `TrailingReturn` settings.

A definition pins implementation/version, ordered named input requirements,
ordered output names/units, parameters, batch/incremental mode and TTL. Inputs
arrive through the [named observation boundary](../observations/README.md).
An exact vector carries entity, definition/schema, value/missing reasons, event,
information-start, availability and expiry clocks, admitted input/state digest,
and optional fitted-transform identity. Availability and TTL are inclusive.
Incremental information intervals conservatively retain the earliest consumed
input, including across missing resets, for temporal purge admission. Outputs
are available at the authored decision clock; this is a research processing
assumption, not a measured runtime latency.

Kernels implement a pure `step(inputs, state)` returning values and successor
bytes. `FeatureSession` owns state per instance/entity and validates all outputs
before advancing. Decisions must strictly increase; an emitted cutoff cannot be
revisited. Batch kernels start with empty state at each decision; incremental
kernels receive the committed state. Checkpoints retain version, instance, entity,
cutoff, information interval and state digest. Changed definitions, wrong instances,
corrupt or incompatible state fail; inference/restart never silently refits.

`ProjectionFeature` retains arbitrary named scalar inputs in declared order.
`RunningMeanFeature` computes exact expanding means per column, resetting a column
on missing input. Batch application iteration and checkpoint continuation use
these same transitions. Fresh kernels can change formulas and output width through
the public protocol without adding branches to shared runners.

`FittedTransform` admits only `TemporalSplit.fitting_rows()` via actual vector
identities and clocks. `TransformAdapter` supplies its own state/semantics;
`CenterColumns` is the exact train-only centering reference. `TransformVersion`
retains implementation, input/output signatures, split, fit rows/cutoff, availability and actual
state bytes. `apply` refuses future fitted state. `training_apply` is explicitly
retrospective and restricted to admitted fitting rows before model availability;
its later availability prevents those transformed rows from posing as historical
decision inputs. Missing inference values stay missing; missing training values
are refused. Adapters explicitly declare fitted output names/units and may select columns or
normalize dimensions; the returned values must match that retained output schema.
The regression consumer selects and normalizes one column using only training data.

The store-facing `FeatureVector`/`VectorSignature` contracts bind entity,
feature/schema and fitted version, source/revision lineage, clocks, TTL and
missingness. The [versioned feature-store path](#versioned-feature-store-and-local-feast-serving)
now consumes these vectors. The older offline Feast bridge remains a separate
supported contract; it does not accept the new vector schemas automatically.

`applications.explore.run_decisions` and `inspect_decisions` are the first
integrated consumers; the [strategy guide](../../strategies/README.md) owns
configuration, intent and retained-attempt semantics. Execute the complete fresh
extension example outside the checkout with the installed interpreter:

```sh
cp tests/integration/consumers/research/decision_extensions.py /private/tmp/decision_extensions.py
uv run --frozen --no-editable python -I /private/tmp/decision_extensions.py \
  /private/tmp/decision-reference-output
```

The [consumer source](../../../tests/integration/consumers/research/decision_extensions.py)
shows typed configuration, independent exact expectations, generic label/estimator
implementations, retained transform/model bytes and reload-only continuation.
The installed integration test performs this copy in an isolated temporary root.
No service or profitable strategy is required. Keep result/config/state bytes,
source inputs, custom implementation code and matching wheel for reproduction.
The caller owns explicit retention and the bounded in-memory schedule; MR15
capacity qualification and MR03 full study/report integration remain open.

Reversal removes these additive exports and consumers together. Existing retained
schemas need no migration. Preserve the matching new wheel for new vector/state
records; prior wheels cannot interpret them. Checkpoint digests are integrity
checks, not a trust or signing boundary.

## Versioned feature store and local Feast serving

Owner: `research.features`, composed by `applications.explore`; implemented local
MR04 feature-store slice, 2026-09-24. `FeatureStoreDefinition` pins a name, entity
type, `FeatureSchema`, an instance for incremental state, and an optional fitted
transform identity with its ordered served output fields. `StoredFeature` binds an
exact `FeatureVector` to caller-supplied source and dataset versions/digests plus
a correction revision. `VersionedFeatureStore.open(path)` keeps definitions, rows,
checkpoints, staged snapshots and the active version in durable SQLite state.

`append(definition, feature, checkpoint=...)` commits an incremental vector and
its successor checkpoint in one transaction. A restart calls
`get_checkpoint(definition, instance, entity, source_version=...,
source_sha256=..., dataset_version=..., dataset_sha256=...)`; changed lineage is
rejected before skipping completed cutoffs. Incremental definitions require an
instance, so two strategy instances cannot share one state stream. An exact row
retry is idempotent; a conflicting retry fails. For an incremental stream with
changed source or dataset bytes, choose a new instance and replay the affected
history. A late correction to an already checkpointed incremental decision
cannot rewrite its successor state in place; regenerate the affected and later
decisions under that new instance. A batch `StoredFeature` can retain a correction
for the same decision only when its `available_at` advances beyond the prior
revision.

`retrieve_offline(definition, entity, at)` selects the latest decision and
revision whose decision and availability clocks are no later than `at`.
Knowledge-time corrections therefore leave earlier cutoffs unchanged. It never
falls back to an older value when the latest eligible vector is expired or
missing. `FeatureStoreResult` retains exact values, reasons, clocks, source and
dataset lineage, definition identity, and explicit `ready`, `partial`, `missing`
or `expired` quality. The served path also reports `future`, `stale` and
`unmaterialized`. `require_ready()` admits only a complete fresh vector.

`materialize(definition, version, at, entities)` stages one immutable named
snapshot without changing the active version. The application projects it with
`FeastServingSnapshot.from_materialization`, writes and reads a separate local
Feast 0.66 generation through `FeastServingBridge`, verifies every entity's
exact values, then calls `activate_if_current` with the active version observed
before preparation. A competing worker's newer publication makes the older
activation fail; an exact retry is idempotent. Failed or partial publication
leaves the previous active pointer intact. `get_materialization` reopens a pinned
version after restart; explicit `activate` rolls back to an older complete
version. `retrieve_online` reads only the active snapshot and can apply
an explicit maximum materialization age; a missing or future value is never
silently recomputed. The local store's `backup`/`restore` preserves SQLite
history; `WorkspaceBackup` retains both that history and the Feast generations.

`applications.explore.materialize_features` is the executable source →
`FeatureSession` → store → Feast composition. It requires a matching source
identity and schema, an incremental instance, and ordered decisions; it resumes
a checkpointed incremental stream and activates only after Feast parity. The
currently composed path runs unfitted kernels; fitted vectors use the explicit
definition/output-signature and append boundary. `run_served_decision` verifies
the pinned Feast generation before passing a ready vector to the same
`DecisionSession` used in research. It returns a visible pause with unchanged
decision state on missing, expired or unavailable serving; it emits intents and
grants no order or account authority. This runtime consumer currently relies on
the vector expiry policy; callers needing a shorter materialization-age limit
can supply it to `retrieve_online` and must carry that policy into their
serving composition.

The [installed workspace consumer](../../../tests/integration/consumers/research/feature_workspace.py)
uses independently locked core and Feast interpreters. From installed wheels,
copy the consumer outside the checkout and use a fresh output directory:

```sh
cp tests/integration/consumers/research/feature_workspace.py /private/tmp/feature_workspace.py
/absolute/core-environment/bin/python -I /private/tmp/feature_workspace.py \
  /private/tmp/unused-feature-workspace \
  --worker-python /absolute/feast-environment/bin/python
```

The retained local [run output](../../../logs/mr04/feature-workspace-2.log) from
the installed `/private/tmp/ar04-core` and `/private/tmp/ar04-feast` environments
passed against real Feast 0.66. It checked two entities, exact matched-cutoff
offline/online values, checkpoint restart and retry, a late batch correction,
active-version pointer rollback, an intent at a later consuming time, expiry and
service-loss pauses, and restored local Feast access. This is authored-input
software evidence. Caller-supplied source/dataset digests must come from
retained bytes; the run does not qualify OKX/Bitfinex source clocks, a profitable
strategy, deployed service recovery or live orders. MR06 installation/deployment
and MR15 capacity acceptance remain open in the
[infrastructure roadmap](../../../docs/roadmap/README.md#delivery-order-and-dependencies).

## Compatible implementations and offline reuse

`FeatureRegistry` accepts an explicit implementation ID and a typed factory over
the existing `TrailingReturn` settings. `FeatureStudy.feature_implementation`
defaults to the maintained engine. A supplied registry can select a compatible
engine without changing shared runners; it must preserve the declared definition,
units, schema, window and timing contract. The implementation ID enters the study
specification while the original feature definition stays in retained output.
Unregistered engines and duplicate registration fail explicitly.

`OfflineFeatureDefinition` pins definition/registry bytes, SDK version, exact
source version/digest, entity type/join key, units and TTL. `OfflineFeatureBridge`
validates the versioned subprocess response; `OfflineFeatureAccess` owns causal
admission and parity against retained observations. Exact feature values cross
the worker boundary as reduced numerator/denominator strings. Unknown, missing,
late and expired observations stay explicit; no zero fill is introduced.

The [separate local worker](../../../configs/development/research-worker/README.md)
keeps Feast's pandas-below-3 dependency out of the core pandas 3.0.5 runtime.
The selected legacy offline path requires an eligibility-filtered immutable source
and pins actual registry/source state. A normal event-time join alone is insufficient
for delayed availability or revisions. The generalized local online path above
publishes its own immutable, causally selected Feast generation.

## Formula and clocks

For decision `t`, feature processing delay `d` and lookback `w`, the feature
queries **[t − d − w, t − d)** with inclusive knowledge cutoff **t − d**.
It computes `last_price / first_price − 1` over the selected observed trades.
The feature is declared available at `t`; `d=0` explicitly assumes no additional
processing delay for this offline diagnostic, not measured production latency.

`WindowPolicy.clock="query-business"` preserves `QueryReader` semantics:
captured trades use `provenance.valid_from` (the capture-validity clock in the
current Tardis adapter); archive trades use `ts_event`. These clocks are not
silently interchangeable. `PricePoint` retains business time, original exchange
event time where present, effective revision availability, revision identity and
exact price. Staleness is measured on the business clock, not exchange latency.
An exchange-event-window feature needs its own supported query/clock contract.

Points are ordered by business time, then the admitted query's stable
knowledge/precedence/raw-position order. Windows never combine bindings or
currencies. `WindowPolicy` requires an explicit lookback, minimum trade count
(at least two for a trailing return) and maximum final-price age. Age equality
is admitted. The following produce a missing value, never zero or forward fill:

- The full lookback lies outside the union of declared saved request coverage.
- A binding-scoped disconnect survives the query, including earlier boundary
  controls. Recovery is conservatively unproven for this diagnostic.
- Too few then-available trades, including unknown availability or membership.
- A stale final trade, or nonpositive prices unsupported by this return formula.

Retain and inspect the accompanying source, membership and quality evidence even
when a value exists. Request coverage and observed prices do not prove empirical
completeness. These are observed-price diagnostics, not fixed-interval bar returns,
executable returns, fills or P&L. No price adjustment or currency conversion occurs.

Both features and labels use `financial_units.ExactRatio`, computed with `Fraction`
directly from exact Decimal prices. Its wire representation is reduced integer
strings: `{"numerator":"1","denominator":"10003"}` for 100.03 → 100.04.
No Decimal-context rounding or numerical tolerance applies. Formula/schema version,
units, cadence, delay and window policy determine the feature definition identity.

## Configure and retain a study

Supply a `FeatureStudy` with family/question, pinned `ResearchSelection`, no-fit
`TemporalSplit`, selected validation/holdout partition, half-open `decisions`,
`TrailingReturn`, and an optional `ForwardReturn`. Decisions start at
`decisions.start` and advance by the explicit feature cadence while before the end.
The selection's window is an input envelope containing all lookback/outcome
windows; its shared `known_at` is the observation cutoff for pending labels.
Every trade input must project `revision`. Book and macro inputs fail explicitly;
their first working formulas/adapters remain future work.

For example, after constructing those records from the intended pinned inputs:

```python
from pathlib import Path

from applications.explore import inspect_experiment
from market_data.storage import RawStore
from serialization import DomainCodec

# study is a validated research.exploration.FeatureStudy supplied by the researcher.
root = Path("/absolute/path/to/retained/study")
config = root / "study.json"
config.write_bytes(DomainCodec().encode_json(study))
history = inspect_experiment(
    config, root / "snapshots", RawStore(root / "raw"), attempts=root / "attempts"
)
print(history.start.run_identity, history.start.attempt_id, history.status)
```

The [installed consumer](../../../tests/integration/consumers/research/feature_study.py)
is the complete executable example: it publishes two configured instruments with
explicit synthetic correction availability, authors the study, calculates
nonmissing features/labels and reproduces the exact result in a new process.
Its copied inputs and invocation are documented in the [tests guide](../../../tests/README.md).
It runs through the integration test and isolated wheel smoke, without network
or live-source evidence. The ordinary unknown-availability archive path remains
missing; correction fixtures do not establish historical source knowability.

The result uses `feature-study-result-v1`, with separate ordered `features` and
`labels` arrays sharing stable row IDs, full definitions, selection/split identities
and generated `SampleInterval` records. In-process `NamedTuple` values serialize
as arrays in their declared field order; the exported types own those layouts.
Features contain no label values or label definition identities. A sample digest
binds both feature and optional label bytes for future consumers. Information
intervals include lookback, horizon and label publication delay. Missing labels
have unknown availability and cannot enter supervised fitting. Time admission
alone is not value admission; any future fitter must apply its missing-value policy.

The declared split has no authored samples; this consumer produces truthful
intervals from actual windows. It performs no fitting. Validation outcomes whose
closed information interval reaches the frozen holdout are rejected before data
access. Holdout studies record consumption before reading values, and changed
studies cannot reuse consumed final evidence under the existing
[attempt-store contract](../experiments/README.md#holdout-consumption-and-atomic-outcomes).

Semantic run identity includes the selection, decision window, feature/optional
label definitions, split, question, installed implementation and environment.
Paths, batch sizes, byte caps and attempt clocks are excluded. A changed source
snapshot changes identity even if an earlier value is unaffected. The start event
retains exact configuration bytes; completion atomically retains full result bytes.
Failures and rejected holdout reuse remain inspectable.

## Bounds, verification and reversal

This is a materialized reference implementation with at most 1,024
decision/binding rows. Windows, cadence and delays are bounded integer microseconds;
source byte ceilings remain explicit. Each cutoff reopens/verifies its pinned
selection. Batch size changes query delivery shape only; it does not reduce total
result memory. Large studies, caching and incremental execution need their own
measured consumer and are not claimed here.

The [domain examples](../../../tests/unit/research/test_features.py) independently
check exact ratios, future perturbations, late corrections, clock distinctions,
tie ordering, warm-up, stale/missing data, configuration identities, schedules,
pending labels and retained failures. The owning roadmap/PR records exact command
results, initial failures and installed verification.

Revert the implementation to remove the new interfaces; preserve retained stores
and matching wheels/environments for reproduction. Older code cannot read the
new study schema. Existing EDA, `ExplorationStudy`, raw/snapshot and attempt schemas
remain compatible. Source evidence limitations and the separate deployment/trading
authority boundary remain unchanged.

`applications.explore.compare_offline_features` is the formal parity consumer.
It verifies an existing completed feature attempt, its exact result digest, family
and validation split, then derives the complete native reference grid. The request
must identify the retained trailing-return definition, instrument keys and units.
One SDK retrieval is retained with the full request, native reference, source
result and exact comparison. Mismatches remain rejected; successful results commit
a manifest before ClearML publication. The
[installed acceptance program](../../../tests/integration/consumers/research/offline_features.py)
exercises this workflow with the separately locked worker. No holdout, online
store or remote source is selected by this action.

## Scheduled completed-price parity

Owner: `research.features`, composed by `applications.backtest`; bounded saved-input
implementation, 2026-09-22. `CompletedReturn` versions the P1 return of two adjacent
**frozen completed event-time closes**. This differs from `TrailingReturn`'s
observed-trade query-business window. `SpotSimulation` and `ScheduledFeatures`
call the same exact formula; existing economic results/checkpoints retain their
schemas and values. No model is fitted or inferred for this rule-only consumer.

`ScheduledFeatureSpec` pins an instance, source/stream/instrument, price dimensions,
sample, cadence and maximum event age. Its version fixes the
`completed-price-return-v1` formula and the existing observation policy. The first
close is `start + cadence`; closes are strictly before `end`, with at most 1,023
closes in a sample of at most 1,024 cadences. `ScheduledFeatures.evaluate(t)` accepts
only the next scheduled UTC close. Skipped/repeated/reversed/end clocks fail;
explicitly process missed scheduled closes against the same retained input before
continuing. Each evaluation reconstructs the then-known source prefix through
`Replay`, then calls `Observations.close` for `[t-cadence,t)`. This deliberately
bounded batch path rereads admitted history per close; it makes no throughput or
latency-budget claim and does not acquire or subscribe to data.

Availability at `t` is inclusive, event-window end is exclusive, ties use existing
causal logical source order, and unknown availability remains excluded. Missing,
stale, ineligible, invalid or gapped observations stay explicit. Returns are missing
until two adjacent valid closes exist. A late correction can affect newly evaluated
windows but cannot change an already frozen endpoint. A disconnect at the exact
close is retained separately as `has_current_gap`, preserving the economic rule's
current-decision control even though that event is outside the half-open window.
Fresh valid adjacent windows restore a return after a gap; this is the existing
completed-observation policy, not a new source-completeness guarantee.

`ScheduledFeatureCheckpoint` retains the full frozen trace, definition, source
identity and value digest. Reload rejects changed instance, source bytes, timing,
units, version, incompatible schedules, stale endpoints or inconsistent exact
returns. Failed evaluation leaves prior state unchanged. Restore with the same
`QueryReader`, definition and serialized checkpoint; changing batch size is allowed.
The digest detects corruption, not hostile forgery. Independent instances have
independent frozen state; no account or order recovery is provided.

`applications.backtest.qualify_scheduled_features(reader, reference)` verifies the
retained economic reference's source cursor, compares its full feature trace with
uninterrupted scheduled batches and reload-only batches, and returns a
`ScheduledFeatureParity`. It retains all three traces, reference/implementation
identities and original evidence limitations. Inspect `is_equal` and
`first_divergence`; disagreement is retained, not converted to success. A fresh
process is exercised by the installed acceptance consumer. Prediction parity is
inapplicable to the unfitted rule. These traces qualify saved-input software only;
actual runtime source/cadence qualification and P1 empirical acceptance remain open.

Use the existing command with a retained configured economic reference and its
original saved stores:

```sh
alpha-backtest qualify-features \
  --config /absolute/path/to/configured.json \
  --snapshots /absolute/path/to/snapshots \
  --raw /absolute/path/to/raw \
  --reference /absolute/path/to/economic-reference.json \
  --max-bytes 2000000 \
  --output /absolute/path/to/scheduled-feature-parity.json
```

The command verifies config/reference agreement and source identity before comparing.
It atomically exports the report, returns zero for equality and two for divergence
or invalid inputs (four for execution/I/O failure). It does not rerun economics,
consume labels/holdout outcomes or publish tracking messages. Keep the report with
its referenced result, source stores and matching wheel; a digest alone is not
reproduction evidence. The installed
[economic consumer](../../../tests/integration/consumers/backtest/economic_workflow.py)
exercises this exact invocation and rejects an incompatible reference.

[Independent feature examples](../../../tests/unit/research/test_scheduled_features.py)
cover `100.03 → 100.04 = 1/10003`, delayed and equal-clock corrections, event ties,
missing/stale/gapped windows, recovery, two instruments, isolated instances,
failed-call atomicity, corrupt state and incompatible restart.
[Application parity checks](../../../tests/unit/simulation/test_scheduled_parity.py)
compare complete replay and batch traces and locate the first differing decision.
The roadmap records exact validation results. Revert these APIs, their command
branch and shared formula use together; preserve matching wheels and retained state.
Older wheels cannot read these new feature-state/parity schemas. Existing study
and economic schemas are unchanged. For this completed-price consumer,
incremental execution remains separate from the generalized feature lifecycle
above. The local Feast serving path is described above;
[candidate packaging and binding](../../runtime/README.md#candidate-loading-and-intent-evaluation)
now consume these definitions and fitted versions. Deployment and trading remain
subsequent work.
