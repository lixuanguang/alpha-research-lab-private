# Versioned observed-price diagnostics

Owner: repository founder. Implemented bounded research contract, 2026-09-20.
`research.features` owns `TrailingReturn` and its shared `WindowPolicy`;
[`research.labels`](../labels/README.md) owns separate forward outcomes.
`research.exploration.FeatureStudy` aligns them with saved inputs and temporal
partitions. The existing `applications.explore.inspect_experiment` orchestrates
admission, installed identities, retained attempts and holdout consumption.
The observed-trade study introduces no model, strategy, fit, incremental engine
or deployment. The separate scheduled completed-price path is documented below.

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
The selected offline path requires an eligibility-filtered immutable source and
pins actual registry/source state. A normal event-time join alone is insufficient
for delayed availability or revisions. This is offline research only; an online
store and runtime consumer remain conditional MR 9 work.

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
and economic schemas are unchanged. Incremental computation, fitted preprocessing,
Feast online retrieval/materialization, candidate packaging, deployment and trading
remain conditional or subsequent work.
