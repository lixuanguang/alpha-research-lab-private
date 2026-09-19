# Market-data foundation contracts

Owner: repository founder. Status: implemented foundation boundary for the
current candidate; acquisition, storage, local-book reconstruction, replay, and
live ingestion remain planned. Scope: immutable authored instrument metadata,
source provenance, strict Binance event records, and one-line Tardis decoding.
This page does not claim a dataset, HTTP request, or trading result.

The new bounded native L3 capture envelope and its nullable source-clock contract
are documented in [L3 collectors](l3-collectors.md). It reuses raw-object storage
and exact serialization without changing these historical canonical event schemas.

## Boundary and module ownership

The public package surface is
[`alpha_research.data`](../../src/alpha_research/data/__init__.py). Callers
construct `TardisDecoder` with a configured `BinancePayloadDecoder` and reuse
`decode_line`. Both decoders are public library types; internal modules import
their dependencies from defining modules. The
[C0 migration](../roadmap/README.md#existing-abstractions-to-retain-or-retire)
removes the composition-only subclass and compatibility import paths. Event
schemas and decoding semantics are unchanged.

| Module | Contract |
| --- | --- |
| [`data/events.py`](../../src/alpha_research/data/events.py) | Frozen `TaggedEvent` and `MarketEventRecord` templates, shared validation, and `Disconnect` |
| [`data/decoders.py`](../../src/alpha_research/data/decoders.py) | Neutral `DecodeContext` and `PayloadDecoder` protocol; no provider framing or venue schema |
| [`data/providers/tardis/decoder.py`](../../src/alpha_research/data/providers/tardis/decoder.py) | Tardis line framing, capture-time parsing, provenance construction, blank-line handling, and raw JSON handoff |
| [`data/venues/binance/events.py`](../../src/alpha_research/data/venues/binance/events.py) | `BinanceMarketEvent`, `DepthSnapshot`, `DepthUpdate`, and `Trade` with Binance symbol and event invariants |
| [`data/venues/binance/payloads.py`](../../src/alpha_research/data/venues/binance/payloads.py) | `BinancePayloadDecoder`, source envelope/payload schemas, cached source decoders, and payload-to-event mapping |
| [`data/venues/binance/codecs.py`](../../src/alpha_research/data/venues/binance/codecs.py) | Closed `MarketEvent` union and reusable strict `MarketEventCodec` |

`data.decoders` owns only the neutral context and payload-decoder protocol. The
Tardis provider owns line framing, capture parsing, provenance construction, and
blank-line handling without imposing a venue JSON envelope. The Binance payload
decoder requires Binance's combined-stream `stream`/`data` envelope and maps its
payload to canonical events. `BinanceMarketEvent.validate()` calls shared
`MarketEventRecord.validate()` before checking the Binance symbol; concrete event
validators then add snapshot, update, or trade invariants. The current candidate
adds no second venue or live-feed implementation. The boundary change preserves
source bytes, event timestamps, source order, and event identity.

## Authored catalog and identity

[`reference_data.py`](../../src/alpha_research/reference_data.py) defines frozen
`SpotInstrument` and `CatalogSnapshot` records. The authored
[`binance-spot.json`](../../configs/reference/binance-spot.json) records local
research assumptions for Binance spot: canonical instrument IDs, uppercase
symbols, complete `Currency` values, positive price ticks, UTC validity
intervals, and fixed venue/product/source metadata. It does not establish
historical exchange filters, listing membership, or venue truth.

`CatalogSnapshot` requires a nonempty tuple with unique IDs and symbols. Its
`resolve` operation returns an instrument only when the requested half-open
interval is fully covered; missing IDs, incomplete coverage, unsupported
metadata, and invalid nested records fail closed. The identity is the SHA-256 of
the canonical encoded snapshot. Catalog membership does not activate an asset or
select a strategy. The planned
[configuration boundary](../architecture/platform-design.md#configuration-and-active-workflows)
separates data jobs/universes from strategy-instance input requirements and
deployment authority. Orchestrators pass resolved instruments and bindings to
these libraries; an independent collection job may cover a broader universe.
The current catalog and decoders do not implement that activation workflow.

Capability support is scoped by source, product, representation and mode. Existing
depth decoding is not book reconstruction or live gap recovery; a different-family
fixture is not admission to the spot ledger or executable trading. The
[milestone support contract](../roadmap/README.md#shared-configuration-and-support-contracts)
assigns ingestion, query/replay, simulation and operating proofs separately.

## Historical eligibility assertions (MR 11)

[`EligibilityAssertions`](../../src/alpha_research/data/eligibility.py) reads a
version-1 or version-2 JSON file of immutable assertions plus its complete authored catalog.
`read(path, catalog=selected_catalog)` requires the complete catalog identity to
match, including currencies, unit grids, ticks and authored evidence. Each canonical
instrument must be present. This validates linkage without promoting catalog
`research_assumption` metadata to historical venue truth.

Each assertion retains `[valid_from, valid_to)` UTC, `ts_knowledge`, an explicit
`included` or `excluded` state, a reason and `EligibilityEvidence`. Evidence identifies
a retained source document/revision and distinguishes `research_assumption`,
`source_evidence` and `synthetic` bases. `available_at` cannot follow `recorded_at`;
an authored assumption is available only at its recording time. Assertion knowledge
cannot precede evidenced availability. A later recording of actual source evidence
may retain its earlier evidenced availability; validity alone never supplies knowledge.

All assertions survive in file order, including excluded/delisted members and
exclusions beyond catalog validity. Nonempty half-open intervals must not overlap
contradictorily for the same instrument while their knowledge lifetimes overlap.
Without an explicit version-2 correction, different knowledge times alone never
resolve contradictory assertions.
Adjacent intervals and overlapping agreement are retained. One evidence identity
cannot carry inconsistent metadata. Missing identities, reasons or clocks, unknown
fields/versions, malformed/unsafe nested values and files over one MiB fail closed.
An empty assertion tuple asserts nothing; the reader never infers eligibility.

The evidence identity is a caller-supplied reference, not independently authenticated
proof: the reader neither fetches the referenced document nor verifies its contents.
Source-evidence admission still requires a trustworthy retained document supporting
the claimed historical availability. The [synthetic fixture](../../tests/fixtures/mr11/eligibility.json)
and NB 11 prove temporal validation only; empirical P1 eligibility remains unresolved.
MR 12 adds the selection/correction contract below; quality acceptance and publication
remain planned. The
[usage example](../../src/alpha_research/data/README.md#read-historical-eligibility-assertions)
and [acceptance record](../roadmap/mr-11-implementation.md) identify the consumer and checks.

### Decision-time selection and corrections (MR 12)

`history.select(instrument_id, valid_at=..., known_at=...)` is a pure query over
validated history. Both clocks must be aware UTC: validity uses
`valid_from <= valid_at < valid_to`, independently of inclusive
`ts_knowledge <= known_at`. It returns the included/excluded assertion with its
reason and evidence, `"unknown"` when no known active assertion covers the instant,
or `"unsupported"` for an ID absent from the bound catalog. Callers form a universe
only from results whose state is explicitly `included`. Catalog validity does not
establish or filter historical membership; catalog/units acceptance remains a
separate contract. Known exclusions may outlive the authored catalog interval.

An assertion's `identity` hashes its canonical fields, evidence and optional
`supersedes` link. `history.append(assertion)` returns a new version-2 history,
preserving all original records and leaving the input unchanged. A correction
names its retained predecessor's identity, belongs to the same instrument, has
strictly later knowledge and distinct evidence identity, and cannot branch.
The inherited evidence clocks still apply. Missing predecessors, unsafe records,
unsupported schema versions and conflicting active assertions fail as a whole.
File order never establishes correction precedence.

At the correction's knowledge boundary the entire predecessor retires, even when
the correction changes its validity interval. Dates removed from that interval
become unknown unless another independent active assertion covers them; there is
no fallback to the superseded assertion. Earlier cutoffs reconstruct the original.
Successive corrections form a linear history with half-open knowledge lifetimes.
Agreeing independent assertions remain retained; selection chooses latest knowledge,
then greatest assertion identity for deterministic evidence attribution. Conflicts
are checked over both validity and knowledge lifetimes, not just the final head.

Version-1 files and their encoded field set remain supported (`supersedes=None`
is omitted). Corrections require version 2, which old readers reject. Evidence
authenticity remains external; these operations do not promote assumptions or
synthetic fixtures into actual P1 membership proof. Validation and selection are
bounded in-memory reference operations, with no large-history performance claim.
See the [MR 12 record](../roadmap/mr-12-implementation.md) for installed and notebook evidence.

## Provenance, events, and wire values

[`EventProvenance`](../../src/alpha_research/core/events.py) is frozen schema
`"1"`. It retains source ID/event ID, revision and sequence, raw source digest,
event, receipt, ingestion, knowledge, optional source-received, and half-open
business-validity timestamps. All instants are aware UTC values. The
`knowledge_basis` identifies whether availability is observed, source-published,
source-captured, or assumed; `is_available` requires both the knowledge cutoff
and business-validity interval.

The closed canonical event tags are `depth_snapshot`, `depth_update`, `trade`,
and `disconnect`. Non-disconnect records retain provenance, original capture
text, event-time basis, configured symbol and instrument ID, source stream, and
raw line. `Disconnect` intentionally carries null symbol/instrument IDs, the
`global` stream, an empty raw line, and a conservative capture-proxy reason.
Depth prices/quantities and trade values remain exact `Decimal` values; Python
constructors reject floats, nonfinite values, malformed levels, and unsafe
identifiers.

Captured Binance and archive trade decimals also have representation bounds at
the shared event validator: at most 40 coefficient digits and an adjusted
exponent from -30 through 30, inclusive. For zero, this bounds its stored
exponent. Values retain their original scale without rounding or normalization.
These source-data bounds are wider than the C03 accounting grid and do not grant
accounting eligibility. They reject oversized values before tick-grid or
revision-identity rational arithmetic; a saved-input reader failure produces a
rejected quality report without publishable canonical bytes.

The shared serialization boundary in
[`serialization.py`](../../src/alpha_research/serialization.py) encodes exact
Decimal text and complete Currency values with `code` and `minor_unit`.
`DomainCodec` owns domain hooks and deterministic JSON operations, caching each
requested schema for that instance. Reuse it across records. `MarketEventCodec`
compiles the closed canonical event union once per instance and exposes `encode`,
`decode` and `validate`; these replace the former module-level codec functions.
Canonical event codecs reject unknown fields. Raw vendor envelopes and private
payload schemas intentionally tolerate source extras so a generated source
snapshot with additional fields does not break decoding; known fields and
domain invariants remain strict.

## Capture and source semantics

`TardisDecoder.parse_capture_time` in
[`data/providers/tardis/decoder.py`](../../src/alpha_research/data/providers/tardis/decoder.py)
parses the leading ISO UTC capture text. Its timing contract is unchanged. A source
fraction beyond six digits rounds upward
by one microsecond whenever any discarded digit is nonzero. The original text is
retained verbatim. `DecodeContext` binds source sequence, source/raw identity,
capture time, local receipt and optional ingestion to
`EventProvenance` with `knowledge_basis="source_capture"`.

The Tardis provider decoder preserves equal-time source order. A blank source
line becomes a `Disconnect` only when the caller supplies a conservative proxy,
identified as `next_source_capture` or `interval_end`. Depth snapshots use the
capture proxy as their event time because the selected snapshot payload has no
exchange event timestamp. These rules describe source availability; they are not
network-latency measurements or exchange-clock observations. See
[point-in-time semantics](point-in-time-semantics.md).

`BinancePayloadDecoder` in `data/venues/binance/payloads.py` validates and indexes
a nonempty tuple of authored `SpotInstrument` mappings once. It accepts
only the current `tardis.binance.spot` stream forms: `trade`, `depth@100ms`, and
`depthSnapshot`. It requires lowercase stream symbols that resolve to configured
uppercase instruments and rejects unknown streams, symbols, payload mismatches,
invented snapshot timestamps, malformed decimals, and invalid level data.

An orchestrator owns the decoder's lifetime for one configured instrument
selection and supplies the metadata for each line. Input reading, source order,
blank-line capture-proxy selection, error policy, and downstream delivery belong
to that orchestrator. The decoder and its parsing, validation, and codec
dependencies remain library components without acquisition or persistence I/O.
See the [pipeline call example](../../src/alpha_research/data/README.md#pipeline-use).

## Trade duplicate and correction admission (MR 10)

[`TradeRevision`](../../src/alpha_research/data/revisions.py) is the current bounded
individual-trade admission envelope. Its economic key is source, venue, canonical
instrument, stream and trade ID. Its payload identity retains every supported
trade value, including exact source time/precision and archive quote quantity/flags;
raw position, retrieval path and decimal formatting do not establish a new trade.
All distinct original occurrences remain attached. Repeated identical occurrences
are idempotent. Instrument-less controls are rejected by trade admission and keep
their separate occurrence scope below.

The [`admit_saved_trades`](../../src/alpha_research/pipelines/dataset.py) pipeline
consumes complete saved acquisitions and an explicit `reject` or `evidenced` policy.
Unresolved conflicts return no admitted result; `RevisionConflictError.revisions`
retains the batch's economic payloads and lineage for diagnostics. Correction
records bind predecessor/replacement payload identities, UTC publication and
availability, and a retained evidence reference. Missing, branched, dangling,
cyclic or temporally reversed evidence fails. This is a pre-publication admission
gate; MR 13 adds partition quality below, while snapshot publication remains MR 15.

One returned head contributes once per economic key and embeds its immutable
`previous` history. Serialize/reopen the entire envelope using `DomainCodec`.
Consumers must use the envelope's `ts_knowledge` and revision links; an embedded
trade's original clock alone cannot establish corrected availability. Effective
knowledge is bounded by original/own capture, previous effective knowledge and
correction availability. Initial archive knowledge remains absent; explicit evidence
can establish only the corrected version's availability. Acquisition clocks never
substitute for missing market capture or historical publication evidence.

This implementation retains the complete batch in memory and admits linear histories
with distinct payload identities. A reversion to an identical prior payload requires
additional source revision evidence and fails under this bounded policy. A reference
is an assertion supplied by the caller, not independently fetched/verified proof.
The [MR 10 record](../roadmap/mr-10-implementation.md) and NB 10 label their synthetic
inputs explicitly. Shared as-of selection remains MR 17.

## Canonical partition quality (MR 13)

[`QualityPolicy`](../../src/alpha_research/data/quality.py) consumes a single
`SourceRequest`, its original occurrences, linked eligibility history and optional
MR 10 correction evidence. `use` explicitly selects exploratory or causal use;
`known_at` is the fixed eligibility cutoff, and positive `max_gap` is an observed
silence tolerance. The library keeps no mutable state between validations.
[`validate_saved_partition`](../../src/alpha_research/pipelines/dataset.py) is the
saved Binance archive consumer; it reads and verifies the entire selected source
object before returning a report. Multiple selected source partitions fail at entry.

The gate reuses record validation and source decoders to compare each occurrence
with its original bytes. Wrong schema/binding/instrument/catalog units, altered
values or capture clocks, nonfinite/nonpositive prices, off-grid prices and
nonpositive trade base quantities reject the partition. Tick arithmetic uses exact
ratios against the authored catalog. Publisher quote quantities remain source
amounts; no undocumented rounding or product-equality rule is imposed. Existing
L2 deletion quantity zero remains supported by the depth codec; this trade gate
does not add L2 normalization or book-quality acceptance.

Position/record index and event time (archive) or capture time (Tardis) must not
regress within a raw object. Equal-time source order remains in retained occurrences;
separate file traversal order does not matter. Exact repeated occurrences are
idempotent. Economic duplicates contribute once with all distinct lineage; revision
heads retain their full predecessors and effective availability through MR 10.
There is no clock-adjustment option: a changed canonical capture must still match
its original source bytes. Blank-line control proxies remain supplied context,
not evidence of continuous capture. Controls keep their request binding.

The selected half-open interval is checked at both edges and between distinct
observation times. Each silence strictly greater than `max_gap`, plus each distinct
disconnect, contributes to `gap_count`. Gaps describe observed silence, not proven
loss. Consecutive trade IDs, nonempty files, duplicates and zero observed gaps do
not establish recorder completeness. Eligibility is selected at every assertion
validity boundary within the interval, including intervals without observations;
all original assertions, exclusions, reasons and independent clocks are retained.

`QualityReport.scope` is `exploratory_degraded` (accepted for that declared use) or
`rejected`. Both supported input contracts lack complete recorder evidence and the
catalog is authored, so this implementation cannot produce a fully valid causal
partition. Exploratory use can retain gaps or unknown/excluded membership with
explicit annotations; structural errors and unresolved trade revisions reject it.
A rejected report has `canonical=None`; `require_canonical()` raises publication
refusal with the reasons. No partial output is released after a reader failure.
`invalid_count` counts observed invalid occurrences and terminal input failures;
it does not count unread rows or classify an economic conflict as a malformed row.
Raw bytes remain with the caller or immutable store, including after rejection.

Accepted deterministic JSON bytes use schema `canonical-trade-partition-v1` and
explicit scope, policy, complete request/catalog, eligibility history, selected
membership segments, reasons, full revision heads and binding-scoped controls.
Heads use MR 10's deterministic payload-identity order; source order is retained
in occurrence positions. No event or assertion is forward-filled or replaced by
its final sample value. Changed policies produce changed bytes. Reports are local
validation results, not authenticated evidence or snapshot identities. MR 14 owns
the dataset manifest reader/identity, MR 15 owns atomic publication, and MR 16 owns
the installed dataset command. This bounded in-memory path has synthetic quality
evidence and no large-partition performance or empirical P1 acceptance claim.

## Dataset manifest identity and verification (MR 14)

`DatasetManifest` version `1` binds an **ordered** tuple of `DatasetPartition`
records. Each entry retains the canonical SHA-256, complete acquisition manifest,
quality policy, eligibility history and correction evidence. The acquisition embeds
the actual resolved job, selected instruments/universe, catalog and raw descriptors;
names never stand in for this content. The manifest also binds the normalization
runtime identity, canonical schema, correction policy, availability policy and
`exploratory_degraded` scope. `DomainCodec` supplies strict cached decoding and
canonical serialization; unknown fields or unsupported versions/scopes fail.

Semantic identity is SHA-256 over this canonical manifest representation. Rebuild
wall clocks and local paths are caller metadata outside the manifest. Original raw
receipt/ingestion and reference/evidence clocks remain semantic provenance. JSON
whitespace and relocating saved files do not change identity. Reordering partitions,
changing resolved references, code or admission policy does change identity. Version 1
fixes `canonical-trade-partition-v1`, `evidenced-v1` corrections and
`original-or-evidenced-later-v1` availability; other versions require implementation
and cannot be accepted by changing a label.

`assemble_dataset` consumes ordered, complete daily Binance acquisitions
with shared quality/eligibility inputs and corrections keyed by resolved run identity.
It calls the existing quality gate and returns the manifest plus corresponding bytes
only after all partitions pass. Exact repeated inputs are reused; empty selections,
unused correction keys, rejected use or a failed later partition return no assembled prefix. The callable
writes no files and preserves raw inputs.

`DatasetManifest.read` requires an independently retained expected identity, an
explicit canonical directory, raw store and positive byte cap. It reads canonical
files by digest, verifies every referenced file, reconstructs source occurrences and
repeats quality admission, comparing the exact resulting canonical bytes. A forged
scope or altered canonical content fails even when its file digest is recomputed.
The cap bounds each manifest, canonical file and compressed/expanded archive; the
reference implementation retains bounded partitions/results in memory. The caller
excludes concurrent external file mutation, as required by `RawStore`.

This is integrity/admission verification, not source authentication or a release
attestation. It retains all eligibility exclusions and revision predecessors and
never upgrades unknown historical coverage/availability. The saved-input path uses
one completed raw archive per canonical partition; combining separately acquired
revision archives remains outside this bounded consumer. Atomic visibility and
reopening a published snapshot are supplied below by MR 15; queries and the installed dataset
command remain later consumers. See the [MR 14 record](../roadmap/mr-14-implementation.md).

## Atomic local snapshots (MR 15)

`SnapshotStore` binds an existing, durably provisioned snapshot directory and the
retained `RawStore`. `publish_dataset` composes admission, manifest assembly and
publication, returning the dataset SHA-256 only after successful synchronization.
Snapshot identity is the existing manifest identity; no mutable alias or second
identity schema is introduced. Each published directory contains `manifest.json`
and its canonical partition files named by digest. Embedded acquisition manifests
retain raw descriptors; raw bytes stay in the original immutable store.

Publication writes read-only files in a hidden same-filesystem staging directory,
flushes and synchronizes each file, and reuses `DatasetManifest.read` to verify all
bytes and reproduce admission. It synchronizes the staging directory before one
directory rename makes the complete snapshot visible, then synchronizes the parent
before returning. Existing snapshots are verified and reused, never replaced.
Concurrent publishers of the same identity verify the winning nonempty directory.
The caller excludes external mutation/removal of stores and ancestors throughout
use. Local atomic directory rename and file/directory `fsync` are required; failed
operations propagate. This is a local filesystem contract, not an object-store API.

`read(identity, max_bytes=...)` accepts only an explicit lowercase SHA-256 and
verifies the manifest, canonical files and retained raw inputs before returning.
It rejects symlinks, unavailable inputs, unsupported formats, changed bytes and
reproduced-quality disagreement. No run can silently select `latest`. Publication
keeps the original full histories, exclusions and exploratory degraded scope.

Failure before rename exposes no snapshot under its identity. Process death may
leave an orphan `.staging-*` directory, which cannot be selected by the reader;
ordinary exceptions clean up their staging directory. Failure after rename can
leave a complete visible snapshot whose durable acknowledgement is uncertain.
Retry the same inputs/identity to verify it and synchronize the parent. Both failure
and later successful publication leave earlier snapshots readable, provided their
raw inputs remain available. There is no automatic orphan collection or raw-file
deletion. Tests establish process-interruption behavior, not physical power-loss
or distributed-filesystem guarantees. See the [MR 15 record](../roadmap/mr-15-implementation.md).

## Planned boundaries

Event codecs alone do not provide acquisition, manifests, snapshot publication,
research configuration, accounting, strategy or operational workflows. Their
consumers must add their own contracts and evidence while preserving these
event tags, exact numeric values, source text, provenance, and capture-proxy
semantics.

### Control scope through queries

MR 09's [`Occurrence`](../../src/alpha_research/data/normalization.py) retains the
source, request/input binding and instrument subscription that determine a saved
control event's affected scope. It binds exact raw digest, line position and bytes
alongside the decoded record. The saved-file inputs have no live capture-session
identity; later collector adapters must retain it where applicable. The existing
`Disconnect` type stays unchanged. See the
[implemented contract](../../src/alpha_research/data/README.md#decoded-raw-occurrences-mr-09).
A null instrument or the `global` stream tag neither identifies the affected
instruments nor makes the disconnect apply repository-wide.

MRs 17 and 19 preserve all control/quality information applicable to the selected
input bindings through instrument/time filtering and column projection. Return
the applicable records or equivalent scoped, time-aware quality metadata with
the market rows, including known interval state needed at the query boundary.
Retain effective knowledge, affected interval, reason and source lineage even
when those fields are absent from the requested market columns. Unknown required
scope cannot silently become valid coverage. Replay admits this information at
its own availability time under the [shared timing contract](point-in-time-semantics.md#planned-economic-ordering-and-event-stepping).

The decisive planned fixture queries one supported instrument with its trades
and an applicable instrument-less disconnect: query/replay must invalidate the
affected observation or cancel the pending intent. A disconnect exclusive to an
unrelated input binding/session must not invalidate that instrument. Exercise
both cases with column projection; matching only non-null instrument IDs is
insufficient.

## Focused coverage

The [OKX L2 contract](okx-market-data.md) owns its bounded live price levels and
historical archive request. Historical download receipt is archive provenance,
not an invented per-record market receipt time. Missing historical sequence IDs
remain unknown; aggregate order counts are not individual order identities.

The decoding boundary is covered by
[`test_decoders.py`](../../tests/unit/data/test_decoders.py),
[`test_tardis_decoder.py`](../../tests/unit/data/providers/tardis/test_tardis_decoder.py),
[`test_tardis_binance.py`](../../tests/unit/data/providers/tardis/test_tardis_binance.py),
and [`test_binance_decoder.py`](../../tests/unit/data/venues/binance/test_binance_decoder.py).
These tests cover the library boundary; the
[P1 acceptance map](../roadmap/README.md#p1-acceptance-map)
identifies the remaining end-to-end requirements.

## Installed dataset command (MR 16)

`alpha-dataset publish` composes strict saved acquisitions, declared quality and
eligibility/correction evidence, admission, atomic publication and verified reopen.
`alpha-dataset inspect` requires an explicit snapshot SHA-256 and verifies all
retained inputs before completion. The command reuses the preceding MR 10–15
contracts; it creates no additional canonical format or historical evidence.

Exact repeated manifests are idempotent. Nonidentical overlapping instrument/time
selections are rejected rather than published as duplicate partitions. The current
consumer expands complete multi-instrument acquisitions into one instrument/day per
canonical partition. Each view narrows only the resolved instrument tuple and retains
the original job/catalog, raw descriptor, request identity and clocks. The original
manifest remains unchanged for resume. Partial/pending acquisitions are refused.
Corrections are keyed to the original input run and routed by payload identities;
unused or cross-instrument links fail before publication. Multiple compatible
acquisitions may share a dataset. Wrong schema, binding, time, units or required coverage
cannot produce an apparently valid snapshot. Exploratory gaps remain visibly
`exploratory_degraded`; causal use fails on unknown required evidence.

Flushed partition reports retain invalid/gap/duplicate counts and reasons before
admission. Persistence stages distinguish a candidate ID, durable acknowledgement
and completed verification. Failure after rename may leave a complete snapshot;
retry verifies and synchronizes it. The [command guide](../../src/alpha_research/data/README.md#publish-and-inspect-from-the-command-line-mr-16)
owns arguments, file preparation, exit codes and recovery. Actual commands and
limitations are in the [MR 16 record](../roadmap/mr-16-implementation.md).

## Point-event cutoff projection (MR 17)

`AsOfSelector` consumes verified snapshot partitions or admitted canonical bytes,
revalidates their existing quality contract, and preserves full immutable history.
Its [API guide](../../src/alpha_research/data/README.md#select-point-events-at-a-cutoff-mr-17)
owns invocation, precedence, window semantics, control boundary behavior and limits.
Availability is filtered before terminal revision, business-window and eligibility
selection. Unknown original archive availability is not inferred from event time,
local receipt or ingestion. A later evidenced version may be known even when its
original remains unavailable. Corrections and eligibility revisions cannot rewrite
an earlier cutoff; no ineligible successor falls back to its superseded original.

Returned controls retain applicable request/subscription scope, including known
state preceding the query window. Complete quality, membership and revision history
remains separately retained; it is not a cutoff projection. Economic output order
uses effective knowledge, explicit source/stream/subscription precedence, partition
start and source position. Content hashes only identify lineage. Ambiguous ties,
overlapping binding intervals and competing heads require upstream reconciliation.

The reference implementation and NB 17 have synthetic causality/control evidence
and an actual installed published-archive consumer. This does not extend the
archive-only snapshot publication boundary to captured or collector data, establish
historical P1 availability, or implement MR 19 queries/MR 20 replay. The
[MR 17 record](../roadmap/mr-17-implementation.md) retains actual validation.
