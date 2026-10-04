# Market-data capability and command map

Owner: repository founder. Status: bounded saved-data acquisition, publication,
query/replay, EDA and native book capture are implemented. This page is the
short entrypoint for current consumers and their contracts. Detailed semantics
live in the [market-data contracts](../../docs/data/contracts.md), [point-in-time
guide](../../docs/data/point-in-time-semantics.md), [L3 collector guide](../../docs/data/l3-collectors.md)
and [OKX guide](../../docs/data/okx-market-data.md).

`market_data` is an inert grouping package. Import records from
`market_data.contracts`, dataset services from `market_data.datasets`, query and
replay from their public APIs, and concrete provider/venue decoders from their
owned adapter packages. Application composition belongs to
`applications.acquire`, `applications.collect`, `applications.publish_dataset`,
`applications.inspect_fixture` and `applications.explore`.

MR06 also ships `alpha-collect` in the independent `alpha-research-collector`
distribution with exact shared-contract and locked dependency versions. It
contains the market-data owners needed by capture/replay and retains lakeFS
storage; unrelated research, notebook, model-training and reporting packages
are absent. The full research distribution retains the wider command
map below. Use the [trusted installation runbook](../../docs/governance/operations.md#trusted-local-installation)
for signed builds, offline placement and compatible rollback. Installed capture
and probe runs use the signed `CaptureConfig`; saved replay takes an explicit
retained capture path. Packaging evidence does not renew historical source
quality or qualify venue order execution.

## Capability and command map

| Capability | Public boundary | Installed entry point or deeper home |
| --- | --- | --- |
| Authored instruments and historical membership | `CatalogSnapshot`, `EligibilityAssertions`, `EligibilityAssertion` | [Eligibility contracts](../../docs/data/contracts.md#historical-eligibility-assertions) |
| Canonical events and source decoding | `MarketEventCodec`, `BinancePayloadDecoder`, `TardisDecoder` | [Event/wire contracts](../../docs/data/contracts.md#provenance-events-and-wire-values) |
| Raw bytes and request binding | `RawFiles`, `RawStore`, `RawObject` | [Raw storage sections](#saved-raw-object-verification) |
| Historical acquisition and resume | `fetch_partition`, `acquire`, `AcquisitionManifest` | `alpha-acquire`; [source limits](#installed-acquisition-command) |
| Canonical dataset admission | `DatasetPublication`, `DatasetInput`, `DatasetManifest` | `alpha-dataset publish`; [quality contract](../../docs/data/contracts.md#canonical-partition-quality) |
| Atomic snapshots and reopening | `SnapshotStore`, explicit snapshot identity | `alpha-dataset inspect`; [snapshot contract](../../docs/data/contracts.md#atomic-local-snapshots) |
| Cutoff/history queries | `AsOfSelector`, `QueryReader` | [Point-in-time semantics](#select-point-events-at-a-cutoff) |
| Chronological stepping | `Replay`, `ReplayCursor` | [Replay contract](#chronological-event-stepping) |
| Named trade/book research inputs | `ResearchSelection`, `inspect_eda` | [Selection reference](#discover-and-reopen-research-selections) |
| Captured book and trade publication, book replay | `publish_captures`, `CaptureInput`, `BookReplay` | `alpha-dataset capture-publish`; [captured inputs](#bounded-saved-books) |
| Book registry and consolidated BBO | `BookRegistry`, `BookRegistryConfiguration`, `BookAsOfIndex` | [Registry queries](#book-registry-and-consolidated-bbo) |
| Per-book depth and BBO | `BookDepth`, `BookProjection.quote`, `BookQuote` | [Shared book quotes](#shared-book-quotes) |
| Reviewed source evidence | `ArchiveCapture`, `SourceQualification`, `QualityPolicy` | [Qualification sections](#witnessed-archive-availability) |
| Public OKX/Bitfinex trades and observed rules | `PublicDataJob`, `PublicIngestion`, `PublicTradeManifest` | [Public data plane](#public-spot-data-plane) |
| Four scoped universes and adapter admission | `UniverseSelection`, `DataCapability`, `BookAdapters.capability` | [Reference and scope contracts](../../docs/data/contracts.md#versioned-venue-specifications-and-scoped-universes) |

The currently installed commands are `alpha-inspect-fixture`, `alpha-acquire`,
`alpha-dataset`, `alpha-collect` and `alpha-backtest books`. Their command
shapes below are examples with explicit paths and limits; they do not acquire
data merely by appearing here.

## Shared contract rules

Publication is composed as `DatasetPublication(SourceAdapters(),
ImplementationIdentity.sha256())`. Saved readers receive
`readers=SourceAdapters()`; native book reconstruction receives
`book_factory=BookAdapters.create`. Applications supply
`ImplementationIdentity.sha256()` to `Configuration.resolve` and use the
source-only `InstalledIdentity` for capture. These explicit capabilities keep
provider selection, native re-decoding and raw/canonical verification visible.

`market_data.collection.CaptureRunner` owns the same bounded durable collection
and replay-parity path used by `alpha-collect`. An application binds a complete
`CaptureRequest` before opening the feed, then injects the native book factory,
public transport and venue subscription policy. Its optional `CaptureObserver`
receives each original record and canonical book row after durable append and
native apply, including session, gap and terminal controls. An observer failure
propagates and leaves an inspectable interrupted journal. `alpha-collect` alone
adds optional snapshot publication; another consumer can reuse the collection
service without importing that application.

`CaptureRunRunner` supplies the separate finite public collection path with
fixed UTC start/readiness/stop and durable segment lineage. Storage rollover
preserves the open socket and native state; explicit resume retains an
interruption gap before acquiring a fresh native snapshot. A segment whose
provisioning died before its first cursor commit holds no acknowledged record;
resume moves it to `interrupted-segments/` rather than failing, and refuses any
other segment that lacks a cursor. `CaptureInput` and
`SourceAdapters` reconstruct suffix segments from their original predecessors,
while `SavedCaptureRun` independently verifies the completed live trace. The
[collector guide](../../docs/data/l3-collectors.md#finite-public-collection-with-segment-rollover)
owns limits, process ownership and stop/resume commands. This collection path
does not extend any paper-service lifetime or grant corpus acceptance.

Raw bytes are bound to the complete `SourceRequest` and its request identity.
Historical manifests and old reports retain their original implementation
identity; resume with the matching wheel/configuration or start a new run. Do
not relabel an old manifest after code, catalog, source policy or selected input
changes.

Across all boundaries, prices and quantities stay exact `Decimal` values, clocks
are aware UTC, research windows are half-open `[start, end)`, and knowledge
cutoffs are separate from event, receipt, ingestion and acquisition clocks.
Missing, unknown and degraded outcomes remain typed reasons. Byte limits bound
the declared files or retained canonical inputs; they are not a process RSS
limit. No API here resamples, forward-fills, converts USD/USDT or turns an empty
result into a coverage claim.

## Shared book quotes

Owner: quant development. `market_data.books.VisibleBook` maintains exact L3
aggregate `bids`/`asks` alongside native `orders`. An order replacement removes
its previous side/price contribution before adding the new size; deletion removes
the level when its last order leaves. Counts are visible native orders, not queue
rank. Fraction arithmetic and exact Decimal conversion preserve quantities
independently of the caller's Decimal precision. OKX L2 updates still set absolute
size and source-reported counts; they do not become order deltas.

`BookProjection.quote(position, record, outcome, replay, source_id=...,
available_ns=...)` reads those cached levels after `CaptureReplay.apply` completes.
The caller supplies the same just-applied boundary and explicit source identity.
The frozen `market_data.contracts.BookQuote` carries venue, canonical instrument,
source/channel, raw position, sequence/epoch, native source timestamp text,
original receipt, explicit delivery availability, state identity and quality.
Bid/ask sides carry exact price, quantity and count in the instrument's native
units. There is no currency conversion or cross-venue equivalence inference.

`market_state` distinguishes `unavailable`, `empty`, `one_sided`, `locked`,
`crossed` and `two_sided`. Only accepted degraded snapshot/update boundaries
expose sides; controls, gaps, stale and recovering states expose none. A fresh
session replaces the native book; earlier gaps remain in history. This per-boundary
API is not a freshness scheduler: callers must apply their own cutoff and age
policy. `LiveBookDecisionSource.current_quote` applies the existing live causal
and freshness gates and preserves the original market delivery clock.

`BookDepth.from_observation` provides the same exact aggregate representation
for retained L2 or L3 observations; `BookDepth.project` serves research depth
consumers. Conversion retains original quality and clocks, including stale
observations, while `BookDepth.quote` suppresses ineligible prices. Unknown
availability remains `None` unless an explicit original delivery clock is supplied.
Source time and receipt never silently stand in for that clock.

Native/canonical schemas, order IDs, fingerprints, source requests and paper
journal envelopes are unchanged. L3 canonical rows remain order-only; cached
levels are reconstructed from the original journal rather than persisted into
old rows. Consequently no saved-state migration is needed. Research projection
and live paper matching share these APIs without adding research dependencies to
the collector or market-data dependencies to the portable execution wheel.

A capture may instead select the venue's public `trades` channel (OKX and Bitfinex
only, with `depth` 0). Its native state is a `TradeTape`: no depth, the trades the
last message added, and an identity over every applied trade. The common runner
journals, replays and quality-checks it exactly as a book. OKX `trades` is ready at
its acknowledgement and has no snapshot, so earlier trades are unknown; Bitfinex
starts from its recent-trade snapshot and treats the later of an execution (`te`)
and its confirmation (`tu`) as a duplicate. A trade repeated within the bounded
recent window applies once.

The declared initial qualification remains OKX `books` L2 and Bitfinex `R0` L3.
Coinbase lifecycle fixtures retain software coverage only; live Coinbase
collection is deferred and not required. Per-book visible depth does not establish complete venue
coverage, queue priority, executable liquidity or strategy performance. The registry below
owns cross-venue consolidation; MR15 owns capacity measurement. The
[roadmap acceptance record](../../docs/roadmap/README.md#mr07a-common-bbo-and-incremental-l3-aggregates)
retains commands and evidence.

## Book registry and consolidated BBO

Owner: quant development. `market_data.books.BookRegistry` owns independent
`(venue, instrument_id)` state and exposes `lookup(key, cutoff_ns=...)` and
`consolidated(name, cutoff_ns=...)`. Both use cached common quotes; no execution
routing, FX conversion or shared-account allocation is performed.

`configuration.BookRegistryConfiguration` pins `BookSelection` records, explicit
`BookEquivalence` mappings and a positive per-book `history_capacity`. Serialize
and reopen it with the cached `DomainCodec`; `identity` hashes the entire resolved
selection and policy. Each selection binds an `InstrumentDefinition`, exact
recording/source identity, admitted `DataCapability`, native `QuantityKind`,
`max_age_ns` and explicit `allow_degraded`. `BookSelection.from_capture` validates
an existing spot capture selection against the caller's installed capability.
There is exactly one selected source/channel per book. Other sources/products
need compatible declared capabilities; configuration alone does not qualify them.

An equivalence mapping carries an authored economic reference, one selected
listing per venue, an inclusive knowledge cutoff and a half-open validity
interval. Matching product, base asset, quote currency and quantity unit is
mandatory, while the explicit reference asserts economic comparability; symbol
spelling never establishes it. BTC-USD and BTC-USDT cannot share a mapping. There
is no contract-multiplier or quantity conversion. A mapping unavailable at the
query time produces `reference_unavailable` for its selected coverage.

Attach a native recording with `attach(request, book_factory=BookAdapters.create)`
and feed `apply(key, record, available_ns=...)`. Alternatively, use `accept(quote)`
for each externally reconstructed whole-message boundary, including controls.
Attached native books use `apply` exclusively. Positions begin at zero and advance
contiguously per book; repeating the exact latest externally supplied boundary is
idempotent. Original receipt/delivery clocks cannot regress. Unknown availability
is rejected; unknown receipt and declared-but-missing source time are explicit
query exclusions. None of these APIs opens a feed or starts a service.

Cutoffs are inclusive exact Unix nanoseconds and may be queried in any order.
A query selects the latest retained boundary available by that cutoff. It never
falls back through a disconnect to an older priced state. Same-epoch heartbeat,
control and duplicate boundaries can retain an unchanged book, including its
original market clocks; they cannot refresh its age. Freshness is checked at
every query against original receipt, delivery and the declared source clock,
with equality at the age limit eligible. Future source times are excluded.
Expiry therefore works without a new message. Disconnect, gap and recovering
boundaries exclude the venue until a synchronized native snapshot restores it.
Queries before retained history return `history_evicted`; rebuild a fresh registry
from original inputs for older queries. At equal timestamps, the last delivered
boundary wins; callers serialize delivery and queries.

`latest(key)` returns the newest accepted boundary with the priced market it
carries. `BookAsOfIndex` persists those pairs for one delivery log in SQLite with each
delivery's byte range: `create(path)` opens its single writer, `append(boundary,
market, offset=..., length=...)` requires contiguous positions and byte ranges and
nondecreasing availability, and `lookup(selection, cutoff_ns=...)` returns the same
`BookLookup` as a registry that retained every boundary, plus the delivery range of
the selected market. It never evicts history. The owner appends only after a
delivery is durable, so the index can lag its log but not lead it; `covered_bytes()`
reports the described prefix.

`BookLookup` retains the selected source, latest known boundary, eligible original
quote or refusal reason. A consolidated result retains every selected lookup and
its reason, `selected_keys`, `eligible_keys` and `partial`. Empty or one-sided
accepted books remain eligible coverage. `bid` takes the highest eligible price;
`ask` takes the lowest, each retaining all tied original `BookQuote` contributions
in stable venue order and exact summed quantity. Currency and quantity units come
from the selected reference definitions. Totals obey the existing exact financial
grid and fail on overflow instead of rounding. `market_state` explicitly reports
unavailable, empty, one-sided, locked, crossed or two-sided results. Partial
coverage is relative to selected books, not proof of full venue/feed coverage.

State is reconstructed, not migrated: replay the original journals with their
original delivery envelopes for actual availability. Native capture journals alone
retain receipt; using that clock for an exploratory saved replay must be labeled
as a receipt-clock assumption. It cannot become historical delivery evidence.
No native, canonical, dataset or paper-journal wire format changed.

`run_live_paper` constructs a registry for its admitted source, or accepts an
explicit caller-owned `books` registry. The observer updates that selected book
and matches only its eligible per-venue quote. Other selected books can be fed
through the same registry and inspected through explicit mappings; a consolidated
quote never becomes the paper account's matching market. The application returns
the resolved registry configuration for retention alongside capture evidence.
The installed [registry consumer](../../tests/integration/consumers/capture/book_registry.py)
reopens both native source paths separately and uses authored comparable fixtures
for consolidation and selected-venue paper matching. The
[roadmap](../../docs/roadmap/README.md#mr07b-book-registry-and-consolidated-bbo)
records actual acceptance and remaining operating/capacity limits.

## Captured public trades

A captured websocket trades feed publishes into the same `public-trades` schema as
REST acquisitions. Each `PublicTradeObservation` has exactly one origin: a REST
`receipt` or a `capture` record (`CaptureTradeOrigin`: recording request, message
position, index within the message, receipt nanoseconds and raw digest). A
captured trade's knowledge time is its durable receipt rounded up to microseconds.
Captured trades carry no reference data.

Publication replays the whole segment chain through the venue `TradeTape` the live
trade source uses, numbering messages from zero across segments, and retains one
`TradeBoundary` per message: its receipt and the receipt that opened its
synchronized interval (`TradeTapeCoverage`). Coverage closes at a gap, invalid
frame, session end or capture end. Reopening replays the raw input again and
refuses any difference. A trades capture needs declared universes; research access
requires its research membership.

`PublicTradeReader` returns a captured source's boundaries known by the cutoff and
its capture idle time. `SavedDecisionSource` then applies the live trade source's
rules: no field before the first boundary, while unsynchronized, or when the last
boundary is older than the idle time, and no `signed_flow` unless its whole window
lies inside one covered interval. The latest trade is ordered by venue time, then
knowledge, then message position and index, on both paths. At matched cutoffs,
saved and live trade fields have equal values and equal missing fields; missing
reasons can differ in wording.

## Public spot data plane

Owner: quant development. Implemented read-only scope: OKX native spot public REST
trades/history and `books` L2 capture; Bitfinex native spot REST trades/history and
R0 raw-book capture. Public REST polling is explicitly sampled capture, not a
WebSocket trade feed or complete tape. Existing OKX module-4 book archives retain
their separate source/sequence/availability limits. Bitfinex historical books are
not advertised. Current-source contracts were checked on 2026-09-23 against
[OKX market data](https://www.okx.com/docs-v5/en/#order-book-trading-market-data-rest-api-get-trades-history),
[Bitfinex trades](https://docs.bitfinex.com/reference/rest-public-trades) and
[Bitfinex configuration](https://docs.bitfinex.com/reference/rest-public-conf).

`PublicDataJob` pins authored listing definitions, four independent universes,
event/capture interval, adapter limits and an access/use/retention reference.
The maintained [two-venue job](../../configs/data-jobs/public-spot-trades.json)
collects BTC on both venues and also defines inactive OKX ETH. Selecting ETH is a
configuration change using the same decoder and workflow; listing it activates
nothing. Product, native units, calendar, channel and mode compatibility fail
before source access. Only the continuous-UTC spot profile is admitted by these
adapters. Other calendar/product implementations remain explicit extension work.

From a clean local working directory, provide the absolute paths to a copied job
and the installed commands. The output parent must already exist:

```sh
alpha-acquire public --config /absolute/public-spot-trades.json --output /absolute/run
mkdir /absolute/run/snapshots
alpha-dataset public-publish --acquisition /absolute/run/acquisition.json \
  --store /absolute/run/raw --snapshots /absolute/run/snapshots --max-bytes 32000000
alpha-dataset discover --snapshots /absolute/run/snapshots \
  --max-entries 100 --max-bytes 32000000
alpha-dataset public-read --query /absolute/pinned-query.json \
  --store /absolute/run/raw --snapshots /absolute/run/snapshots --max-bytes 32000000
```

Within the checkout, prefix commands with `uv run --frozen --no-editable`.
`mode="backfill"` selects `[start,end)` in UTC milliseconds, at most one day.
OKX's history endpoint advertises a rolling three-month limit; expired or empty
responses do not prove complete/quiet coverage. OKX pages backwards by native
trade ID after the initial timestamp request, with at most 100 rows per response.
Bitfinex pages forwards with inclusive timestamp overlap and at most 10,000 rows;
a saturated single millisecond fails rather than skipping its remaining trades.
Increase the page size in a new job when that diagnostic occurs. Each venue's
native ordering, IDs, exact price/size and aggressor side remain distinct.

For polling, select `mode="capture"` and explicit current/future UTC start/end
times. The worker polls recent trades in round-robin order, under the same page
and aggregate raw-byte budgets. It waits at least the configured five-second
minimum between trade requests. Network inactivity is bounded; transient
429/5xx responses receive at most two bounded retries. A paused process cannot
repair an uncaptured interval. Publication retains unknown completeness and
polling-loss reasons even when every request succeeded.

Every run retains `acquisition.json` plus the existing content-addressed `raw/`
store. Before validation, a pending response saves exact bytes and its original
receipt through atomic replacement/fsync. After raw publication, the completion
prefix is checkpointed. Re-run the identical command with the matching installed
implementation to verify completed objects, reconcile a pending response without
refetching it, and continue from the checked native cursor. Malformed saved bytes,
changed jobs/implementations, missing objects or exhausted budgets fail closed.
Backwards receipt/durable clocks fail without clamping timestamps; a publication
clock failure leaves the original pending response available for recovery.
Invalid responses stay pending for diagnosis; use a new output for a corrected
job instead of rewriting the retained attempt. Exit 0 acknowledges completion,
2 reports a retained failure, and 130 reports handled interruption.

`PublicTradeManifest` pins the publishing implementation as well as acquisition
provenance, using the existing atomic `SnapshotStore`, catalog discovery and raw
re-decoding. `PublicTradeQuery` selects a pinned snapshot, instruments,
half-open event window, inclusive knowledge cutoff and `research` or `strategy`
purpose. It checks that purpose's saved universe. The result retains exact values,
definitions, reference versions, selected duplicate counts and missingness reasons.
Native pages, including values outside the query window, remain retained so a
later observed correction is resolved **before** window filtering. Repeated
identical values retain their first known version. `ts_knowledge` is the actual
local durable observation, never inferred historical availability or exchange time.

`PublicTradeReader.replay` preserves observed versions in knowledge/source-position
order. It also delivers out-of-window revisions of selected trade IDs so consumers
can retire earlier values. Save the returned `PublicReplayCursor` with consumer
state; a different query identity refuses the cursor. This is data replay, not an
execution model or a replacement for the simulation event scheduler.

`ResearchSelection` now accepts named `PublicTradeSelection` and
`ReferenceSelection` alongside existing trades/books. The latter exposes typed
bitemporal venue metadata as a non-book input; it does not force reference facts
into market-event rows. All inputs share a knowledge cutoff and retain independent
windows, units, source clocks and quality. Missing/invalid bytes fail the complete
assembly. Historical book availability remains unknown rather than acquiring
receipt clocks from a trade input.

New foreground book captures can use
`--universes /absolute/public-spot-universes.json`, with the maintained
[scope example](../../configs/live/public-spot-universes.json). The complete scope
is part of `CaptureRequest` and therefore of raw, snapshot and query provenance;
collection and research membership are enforced separately. A request without
this field is unscoped and records `universes` as null.
Scoped supervised capture is explicitly unsupported until its runtime consumer
retains the scope too.

Quant development's [installed reference consumer](../../tests/integration/consumers/datasets/public_data.py)
publishes completed input, discovers identities, writes pinned queries/selections,
invokes the real CLI readers, assembles trade/book/reference inputs and checks
replay continuation. It requires no notebook-authored manifest:

```sh
/absolute/environment/bin/python -I /absolute/public_data.py \
  --acquisition /absolute/run/acquisition.json --raw /absolute/run/raw \
  --output /absolute/new-inspection \
  --books /absolute/okx-recording /absolute/bitfinex-recording
```

The output is an engineering data-plane report, with all source limits visible.
See the [roadmap acceptance record](../../docs/roadmap/README.md#mr01-delivery-and-acceptance)
for observed inputs, validation and remaining infrastructure ownership.

## Read historical eligibility assertions

Use an explicitly selected catalog and `EligibilityAssertions.read(path,
catalog=catalog)`. It validates the complete catalog before returning any
history. Each assertion keeps evidence, a half-open valid interval and an
inclusive aware-UTC `ts_knowledge`; the reader fetches no source evidence.
Missing files raise `OSError`; malformed files, bad linkage and invalid clocks
raise `ValueError` without retaining partial state. The [eligibility contract](../../docs/data/contracts.md#historical-eligibility-assertions)
owns the record schema and evidence meaning.

## Select membership at a decision

Call `history.select(instrument_id, valid_at=..., known_at=...)` with aware UTC
clocks. The result is an included/excluded assertion, `unknown` when membership
is uncovered at the knowledge cutoff, or `unsupported` for an ID absent from the
bound catalog. Only explicit inclusion is eligible. `history.append(correction)`
requires later knowledge, new evidence and `supersedes=prior.identity`; it
retains predecessors and retires the prior assertion when the correction becomes
known. Dangling, branched, cross-member or same-time corrections fail.

## Catalog and event identity

`CatalogSnapshot` and `SpotInstrument` own canonical IDs, symbols, currencies,
ticks, validity intervals and source metadata. `Configuration` resolves a
complete requested interval and `SourceRequest` derives immutable per-instrument
partitions. Catalog/source mismatches, duplicate IDs/symbols and incomplete
coverage fail closed.

Canonical events retain `EventProvenance`, source stream, configured symbol,
instrument ID, original capture text and raw line. The closed wire tags are
`depth_snapshot`, `depth_update`, `trade` and `disconnect`; a disconnect is an
explicit global control with no symbol/instrument. Canonical codecs reject
unknown fields and binary floats; vendor envelopes may keep source extras. The
[contract page](../../docs/data/contracts.md#provenance-events-and-wire-values)
owns provenance and wire-value details.

## Pipeline use

An orchestrator constructs a `BinancePayloadDecoder(instruments)`, passes it to
`TardisDecoder(payload_decoder=..., source_id=...)` and reuses `decode_line` for
each input line. The caller owns ordering, capture proxies, I/O and error policy.
Decoders validate and transform; they do not acquire or persist data.

```python
from market_data.adapters.providers.tardis import TardisDecoder
from market_data.adapters.venues.binance import BinancePayloadDecoder, MarketEventCodec

codec = MarketEventCodec()
decoder = TardisDecoder(
    payload_decoder=BinancePayloadDecoder(instruments),
    source_id="tardis.binance.spot",
)
event = decoder.decode_line(line, source_sequence=sequence, local_received=received)
encoded = codec.encode(event)
restored = codec.decode(encoded)
```

The installed fixture and dataset applications own composition and exit codes;
no forwarding decoder wrapper is required. See the [engineering guide](../../docs/coding_standards/README.md#orchestrator-pipelines-and-libraries)
for library/orchestrator ownership.

## Boundaries and planned consumers

The foundation records do not by themselves provide a dataset manifest, book
replay, research selection, accounting consumer or operational feed. Those
boundaries are implemented by the sections below and by the linked source
guides. A new provider, product, revision policy or execution mechanic needs its
own schema, adapter, identity, tests and evidence; it must not widen the current
Binance or book contracts silently.

## Configured fixture command

`alpha-inspect-fixture` reads one explicitly configured saved frame. It resolves
the job/catalog, verifies the source binding and emits one JSON report on stdout:

```sh
uv run --frozen --no-editable alpha-inspect-fixture \
  --config configs/data-jobs/fixture-inspection.json \
  --catalog configs/reference/binance-spot.json --job btc-fixture \
  --fixture tests/fixtures/market_data/tardis/btcusdt.txt \
  --received 2026-09-14T00:00:00Z --ingested 2026-09-14T00:00:01Z --sequence 0
```

The version-1 configuration separates available universes from named jobs.
Unknown fields, duplicate IDs, missing bindings and unsupported source/product/
stream/mode/pipeline choices fail before frame access. Job intervals are
minute-aligned, UTC, half-open, nonempty and at most one day; a universe has
1–32 canonical IDs. The fixture mode accepts one nonblank UTF-8 trade frame and
does not acquire, decompress, publish, process depth or authenticate history.
Config/catalog/frame reads are capped at one MiB.

Exit codes are 0 for success, 2 for usage/configuration, 3 for frame/decoding/
clock validation and 4 for local I/O. A failure retains no mutable state. The
returned manifest/request identities describe resolved content, not an
authenticated signature or historical eligibility.

## Saved raw-object verification

`RawObject` binds a saved binary file to SHA-256, byte size, `SourceRequest.identity`,
retrieval reference and original aware-UTC receipt/ingestion clocks. Use
`RawFiles.describe(..., request=request.binding, ...)` with caller-supplied
metadata and `RawFiles.verify(descriptor, path, request=expected.binding)` to
reopen it. Verification hashes one binary stream in one-MiB chunks, including
compression headers/trailers and line endings; it does not decode or decompress.
Changed bytes, truncation, append, wrong request binding or invalid metadata
raise `ValueError`; access failures raise `OSError`.

This checks observed bytes and declared metadata. It does not prove transport
completeness, provider authenticity or semantic membership. Empty files are
representable without claiming a quiet interval. Acquisition and dataset
quality own the next checks.

## Durable raw-byte store

`RawStore` takes an existing caller-provisioned directory and publishes a verified
descriptor under its digest name. It stages on the same filesystem, flushes and
syncs, marks the object read-only, verifies again, and uses a no-clobber hard link
followed by directory synchronization. Matching objects are reused only after
verification; conflicting bytes are never overwritten.

`open` accepts only the digest-named regular file, rejects symlinks/directories,
verifies the complete object and returns a read-only stream at position zero.
Interruption can leave a staging orphan or a visible object whose acknowledgement
was lost; retry by verifying the object or republishing from the source. The
store does not own acquisition manifests, garbage collection, transport or
dataset validity.

## One-partition acquisition

`fetch_partition` composes an admitted `historical` / `acquisition.fetch`
configuration, `TardisTransport`, `RawObject` and `RawStore`. The caller supplies
the request, existing store, owned HTTPS connection, UTC clock, report sink,
positive timeout/max-byte limits and a rights reference covering access, intended
use, retention and destination. Credentials are passed directly and never saved
in reports. One request is issued to the configured raw endpoint with the fixed
job origin/offset, lower-case symbol and gzip. HTTP/gzip metadata, CRC and both
compressed/expanded bounds are checked; invalid responses publish nothing.

Transport state is separate from row decoding, canonical validation and coverage.
Transient fetch failures identify retryable network/HTTP conditions; storage,
checkpoint, schema and callback failures remain terminal for that invocation.
An empty response may be retained without a coverage claim. A post-publication
acknowledgement failure leaves the verified object for manifest reconciliation.

## Sequential acquisition and resume

`acquire` consumes one resolved manifest, the same store/admission/bounds and an
exclusive manifest path. It returns an `AcquisitionManifest` with a completed
prefix and at most one pending receipt. Receipt persistence precedes raw
publication; completion is appended only after verified durable publication.

On reopen, completed descriptors are verified and skipped, pending receipts are
refetched only when bytes are absent, and a present pending object is verified and
completed with its original receipt clock. A changed resolved run, foreign
request, invalid ordering/clock/schema or missing completed object fails. A
complete manifest returns without another fetch. Retry delays are explicit and
finite; no automatic migration or latest-file selection occurs.

## Installed acquisition command

`alpha-acquire` resolves an explicit job from a config/catalog and runs the same
acquisition operation. The command shape below is for already admitted source
inputs; paths, rights and limits must be supplied by the caller:

```sh
alpha-acquire --config /protected/jobs.json --catalog /protected/catalog.json \
  --job admitted-job --manifest /protected/run/manifest.json --store /protected/run/raw \
  --rights-reference admitted-evidence-reference --api-key-env TARDIS_API_KEY \
  --timeout-seconds 30 --max-bytes 16777216 --retry-delays 1 2 \
  >> /protected/run/attempts.jsonl 2>> /protected/run/errors.jsonl
```

The manifest/store and their ancestors are caller-owned and must remain stable.
`max-bytes` applies per compressed/expanded partition, not to total elapsed time
or process memory. Progress is flushed JSON; credentials are never echoed or
stored. Exit 0 means every expected partition is verified, 2 setup/usage, 3
acquisition validation, 4 I/O/transport/runtime failure and 130 handled
interruption. Process loss may emit no terminal record; use the last flushed
report and saved checkpoint to resume.

## Binance public daily archive acquisition

`BinanceArchiveTransport` is the bounded public `data.binance.vision` path for
the authored archive job. It binds the filename and SHA-256 sidecar, validates a
single-member unencrypted deflate ZIP/CRC and sends no credentials. The supported
combination is `binance-archive/binance/spot/raw/trade`,
`historical/acquisition.fetch`, `utc-day`, `exchange-time-only`, with a
minute-aligned nonempty selection inside one UTC day. Each selected instrument
uses a full-day request; cross-midnight/Tardis policies fail before HTTP.

The transport verifies compressed and expanded limits and publishes no raw
completion on checksum, ZIP, member or size failure. Archive rows expose exchange
event time only; local acquisition time is not historical knowledge, and the
transport does not validate CSV semantics, eligibility or coverage. Those belong
to the decoded dataset's [quality and admission rules](#reviewed-provider-qualification).

## Saved Binance archive rows

`BinanceArchiveRows.from_manifest(manifest)` selects expected daily partitions
from an explicit complete acquisition. Each `ArchiveRow` retains raw digest,
request identity, acquisition clocks, half-open research selection, zero-based
position and exact CSV bytes. It preserves source order and decimal text; it
does not sort equal timestamps, interpret events or filter outside the request.

The reader requires one correctly named unencrypted deflate ZIP member, separate
compressed/expanded caps and a per-row cap (default 4,096 bytes). Exhaust the
iterator for complete CSV/CRC validation. Empty CSV yields zero rows without a
coverage claim; missing/pending objects, malformed rows and binding conflicts
fail without mutating the manifest or raw store.

## Decoded raw occurrences

`DatasetPublication.occurrences` uses the persisted Binance daily-trade reader to
decode every selected row in original partition/row order. `BinanceArchiveTrades`
preserves timestamp unit (`ms` before 2025, `us` from 2025), exact Decimal price/
quantity, publisher quote quantity, trade ID and maker flags. It rejects
nonfinite values, wrong units, invalid flags and timestamps outside the requested
UTC day with the original row position.

`ArchiveTrade.ts_source_received` and `.ts_knowledge` remain `None`; acquisition
receipt/ingestion stay on the raw origin. `Occurrence` retains the request,
descriptor, row bytes, position, decoded record and record index. Occurrence
identity is positional and distinct from economic revision identity. Unknown
availability and empty archives remain explicit; correction, eligibility, quality
and publication are separate gates.

## Validate a canonical partition

`QualityPolicy` validates an explicit batch or an acquisition through
`DatasetPublication.validate_partition`. The caller chooses `use="exploratory"`
or `"causal"`, an aware-UTC `known_at` and positive `max_gap`, then inspects
scope, reasons, invalid/gap/duplicate counts before `require_canonical()`.
The gate re-decodes original bytes, preserves duplicate/correction lineage and
never treats zero observed gaps as recorder completeness. Current archive inputs
remain exploratory/degraded without sufficient source evidence.

`exploratory_degraded`, `causal_witnessed` and `causal_qualified` scopes retain
their own evidence and limitations. Quality validation creates no snapshot and
does not authorize research claims, execution or publication by itself. See the
[quality contract](../../docs/data/contracts.md#canonical-partition-quality).

## Identify and verify a dataset manifest

`DatasetInput` keeps each acquisition, policy, eligibility and correction history
with the input that owns it. `DatasetPublication.assemble` returns a validated
`DatasetManifest` and canonical payloads; `publish` adds atomic snapshot
publication. Exact repeated selections are reused in first-seen order;
nonidentical overlaps within one source/stream/instrument fail rather than being
merged.

`DatasetManifest.read` verifies manifest identity, raw/canonical bytes, source
readers and admission before returning. Trade manifests name their evidence
`tier`; book publication uses the separate `book-dataset` format. A
manifest path or `latest` alias is never a substitute for an explicit identity.

## Publish and reopen an atomic snapshot

`DatasetPublication.publish` stages canonical files and the manifest in a hidden
directory, synchronizes them, then publishes one directory rename. A matching
retry verifies/reuses the existing snapshot; changed policy or inputs produce a
new identity, and prior snapshots remain readable. `SnapshotStore.read(identity,
...)` re-verifies every raw/canonical file and repeats admission. Callbacks receive
`started`, `persisted` and `complete` only at their documented durability
boundaries; callback failure does not imply rollback.

The byte cap applies per manifest/canonical/raw declaration and the reference
implementation materializes bounded inputs in memory. Same-filesystem rename and
file/directory synchronization are required. Staging directories are not
automatically garbage-collected.

## Publish and inspect from the command line

`alpha-dataset` consumes completed acquisitions and their raw store; it does not
download data or resolve a mutable latest tag:

```sh
alpha-dataset publish \
  --manifests /saved/acquisition.json \
  --store /saved/raw --snapshots /saved/snapshots \
  --policy /saved/policy.json --eligibility /saved/eligibility.json \
  --max-bytes 268435456
alpha-dataset inspect \
  --snapshot-id <explicit-lowercase-sha256-from-complete-record> \
  --store /saved/raw --snapshots /saved/snapshots --max-bytes 268435456
```

Use `--inputs` with strict `DatasetInput` records instead of mixing
`--manifests`, policy, eligibility and corrections. Incomplete/pending
acquisitions, wrong identities, malformed evidence and admission conflicts fail
before a prefix is exposed. Reports retain scope, gap/duplicate/invalid counts,
reasons and source identities; zero gaps do not prove coverage. Exit 0 means a
complete verified publication/inspection, 2 usage/configuration, 3 admission or
verification failure, 4 I/O/unexpected failure and 130 handled interruption.

## Select point events at a cutoff

`AsOfSelector.read` opens an explicit snapshot identity and precedence tuple of
`(source, stream, instrument)` bindings. `select` first walks each revision chain
back to the latest version known by the cutoff, then applies the half-open business
window and membership at that instant. Unknown archive knowledge selects no
version; download time and event time never substitute for knowledge time.

The immutable result includes `TradeRevision` envelopes and applicable controls
in effective-knowledge, precedence, partition and source-position order.
Known controls before the window remain boundary state, and terminal controls at
the exclusive endpoint remain visible. Ambiguous equal-time heads, overlapping
partitions and competing economic revisions fail upstream. `history` retains
complete canonical bytes and evidence and must not be used as a cutoff projection.

## Bounded reference queries

`QueryReader.read` verifies one explicit snapshot and retains admitted canonical
bytes under its aggregate byte budget. `batches` supports columns
`identity`, `ts_knowledge`, `price`, `quantity` and `revision`, exact domain
values, explicit instruments/window/cutoff and bounded delivery. Controls count
toward `batch_size`; an empty selection returns one evidence-bearing empty batch.

`mode="history"` requires `revision` and returns retained chains through the
knowledge bound, including unknown-availability predecessors. A query identity
binds snapshot, precedence, instruments, bounds, cutoff, columns and mode;
batch size/cancellation do not change it. Cancellation is cooperative before
selection or between batches, and no source I/O occurs after admission. This is
a bounded in-memory reference reader, not a columnar backend or streaming RSS
guarantee.

## Chronological event stepping

`Replay` consumes an admitted `QueryReader`, explicit business bounds, inclusive
terminal knowledge time, consumer configuration identity and positive batch size.
Each `step` advances to the earliest outstanding consumer wakeup, next source
availability or terminal. Equal-time callbacks run `source`, `expiry`, `fill`,
`decision`, `mark`; all source ties retain original positions. Unknown original
availability is unschedulable, and phase callbacks are not orders or fills.

`ReplayCursor` binds the query, consumer configuration and
`reference-replay` ordering policy. Restore it with consumer observations,
pending intents, schedules, applied fills and ledger state; identity, clock and
source-prefix checks must agree. A callback failure poisons the instance until
restoration. Replay owns event stepping; later consumers own risk, fills,
valuation and external-state recovery.

## Configured EDA and extension boundaries

`applications.explore.inspect_eda` receives a strict `EdaQuery`, explicit
snapshot/raw stores and caller-owned `report`/`consume` callbacks. The query
binds snapshot identity, complete precedence, instruments, UTC business bounds,
inclusive `known_at`, columns, cutoff/history mode, batch size and byte limit.
It does not acquire data or select a latest snapshot. A complete report retains
resolved configuration, implementation identity, query/summary identities,
quality, units and membership evidence. Invalid configuration, failed reads or
observer failure produce a failed record and no complete summary.

`QuerySummary` retains per-binding counts, exact projected min/max and controls;
it does not sum quantities/currencies across instruments. Report timing, batch
size and RSS observations are descriptive diagnostics, not query identity or
pushdown/performance guarantees. The [EDA and research selection callers](#discover-and-reopen-research-selections)
own named assembly.

## Discover and reopen research selections

`SnapshotCatalog.discover` lists typed `DatasetManifest` or `BookDatasetManifest`
metadata in identity order under entry/aggregate-byte caps. It checks committed
manifest identities but does not verify raw/canonical availability until opening;
staging names and mutable `latest` aliases are never selected.

`ResearchSelection` combines uniquely named `TradeSelection` and `BookSelection`
records. Trade inputs bind snapshots, precedence, selected universe, fields,
window and one shared inclusive knowledge cutoff. Book inputs bind one native
request, instrument, receipt-clock window and bounded columns. `inspect_eda`
reopens the explicit selection and retains typed per-input coverage, quality,
units and missingness. It does not forward-fill, resample, currency-convert,
coerce trade/book rows or return a partial dataset when bytes are missing.

Book results retain native receipt/source fields, sequence/position and controls;
unknown archive availability yields an empty value result with a reason. L2
fields are `bids`/`asks`, L3 fields are `orders`; incompatible fields and
contradictory currencies fail. See the [research selection contract](../../docs/architecture/platform-design.md#current-and-planned-repository-shape)
and [research study protocol](../../examples/study-protocol.md#research-ticket).

## Bounded saved books

`DatasetPublication.publish_captures` accepts completed Bitfinex R0, Coinbase
Exchange L3 or OKX native book capture/archive directories and OKX or Bitfinex
public `trades` capture directories, an existing `RawStore`, an existing snapshot
directory and explicit `max_records`/`max_bytes`. Every input is a `CaptureInput`
(original request, raw object, bounded prefix and segment chain). Book inputs
publish together as one book snapshot; each trades capture chain publishes as its
own `public-trades` snapshot (see [captured public trades](#captured-public-trades)).
The same path is the installed command:

```sh
alpha-dataset capture-publish --captures /absolute/run/segment-a /absolute/run/trades \
  --store /absolute/run/raw --snapshots /absolute/run/snapshots \
  --max-records 1000000 --max-bytes 1000000000
```

It prints the book snapshot identity (or `null`) and each trades snapshot identity.
The `book-dataset` format writes a typed source header followed by one exact
`BookObservation` JSON line per original raw position. Publication keeps one
observation plus the native visible state in memory, then independently replays
the retained raw input against every staged line before the directory is made
visible. The manifest and partition digests identify exact bytes. Any other
book dataset schema is refused.

At most 1,000,000 raw positions per input are selectable for streamed publication,
subject to each source's own record limit and the caller's raw/canonical byte cap.
The in-memory `CaptureInput.admit` reference envelope is limited to 10,000
positions; the online `BookCapture` parity buffer retains its own 10,000
position bound. Publication reports use `BookAdmissionReport` with counts and a
digest, without carrying the whole canonical file in memory. L3 orders keep native
IDs and sizes; L2 levels keep aggregate sizes and counts; zero-size updates delete levels. Adjacent duplicates retain positions
without repeating mutations, and conflicting native sequences reject the whole
partition. Full visible state is a bounded reference representation. Transport
gaps, unknown availability and selected-prefix limits remain quality controls.

Only `exploratory_degraded` book publication is supported. Historical eligibility,
complete coverage, full depth, causal use, trade queries, fills and execution are
not admitted by this boundary. The [OKX guide](../../docs/data/okx-market-data.md)
and [L3 collector guide](../../docs/data/l3-collectors.md) own source-specific
commands and recovery.

## Published book queries and shared stepping

`BookReplay.read` verifies a complete `BookDatasetManifest` and selects one
explicit request identity. `batches` yields original messages and controls with
raw/source/depth evidence; it opens no source connection. `step` reuses shared
replay phases and `ReplayCursor` identity rules. `received_ns` remains exact in
each observation; scheduling rounds up to the shared microsecond UTC clock and
never exposes input early.

`BookSnapshot.read` admits the complete pinned snapshot once and provides
`selection`, `partition` and `observations` for repeated queries and replay.
Returned evidence is independently decoded. Each observation traversal checks
the selected file digest on an open descriptor before yielding its first row;
the cheap `verify_partition` check detects a replaced or modified path after
session opening under the required protected immutable-store contract. Its
`require_limit` check applies a consumer's per-file cap to actual manifest,
canonical and retained raw sizes. Optional `BookSnapshot.read(report=...)` sinks
receive `BookAdmissionReport` values; the generic snapshot report sink, which
requires full `QualityReport.canonical` bytes, is refused for books. Sessions
require protected stores and never grant a source availability clock that was not
captured originally.

`BookQueryReader.open` owns a reusable verified session; `batches(query)` yields
bounded, isolated projections. The existing `read` convenience method still
collects its result in memory. A live query first checks whether any market value
qualifies, preserving the no-values reason on every batch; this prescan and the
delivery pass each verify the canonical digest and can each traverse the history.
Constructing `BookReplay` from an admitted `BookSnapshot` shares its admission
while owning a separate cursor. Receipt ties preserve the reference epoch/position
order using a temporary disk spill with a 2 MiB SQLite page cache; ordinary
receipt progression retains one lookahead. Call `close()` on an unfinished
stepping replay to release its canonical file and temporary spill. A separately
obtained `batches()` iterator owns its stream and must itself be exhausted or
closed by its caller. Raw and canonical stores and
their ancestors must remain protected throughout the session; a warm query does
not re-normalize original raw bytes.

Unknown archive receipt/availability remains queryable but unschedulable.
Snapshot/configuration/input/terminal changes invalidate a cursor; batch-size
changes do not. Save consumer state, visible book and quality/session boundaries
with a completed cursor. Cursor restoration never reconnects or resynchronizes a
live feed. Capture publication compares a selected prefix against independent raw
replay and retains the first divergence on failure.

## Pinned external dataset versions

`LakeFSStorage` resolves a branch/tag reference to an immutable `DatasetVersion`,
verifies lengths/digests and materializes a bounded cache for existing readers.
It does not convert storage commit clocks into market knowledge, relax admission
or change snapshot identity. The [local lakeFS guide](../../configs/development/lakefs/README.md)
owns retention/restore fixtures. Model/report artifacts remain separate.

## Witnessed archive availability

`ArchiveCapture` and `CaptureSlice` bind an exact archive request/raw identity,
public-access reference, retrieval clocks and complete uncompressed native
response slices. Slices must be contiguous, cover the selected interval and
contain timestamps inside their response intervals. Re-decoding must match every
selected economic version; missing/extra/conflicting messages, disconnects and
wrong bindings reject the partition.

With `QualityPolicy(use="witnessed", ...)`, a match plus source-evidence
eligibility and no observed policy gap admits `causal_witnessed`. This is scoped
corroboration, not proof of uninterrupted upstream completeness, exhaustive
revisions or live readiness. The [point-in-time guide](../../docs/data/point-in-time-semantics.md#corroborated-archive-availability)
owns clock and ordering implications.

## Reviewed provider qualification

`QualityPolicy(use="causal", ...)` admits `causal_qualified` only from an
explicit `SourceQualification` bundle. The bundle retains exact request identity,
all archive digests, selected interval, expected count, exhaustive history
cutoff, instrument/coverage/revision citations, version facts, reviewer and
review time. Its supporting records are `ProviderDocument`, `EvidenceCitation`
and `TradeAvailability`; each document is nonempty, hashed and bounded (16 MiB).

Qualification must substantiate historical instrument status, positive interval
coverage and exhaustive original/corrected values. Eligibility assertions use
`basis="source_evidence"` and document digests; a present-day listing or an
empty correction list is insufficient. `DatasetInput.qualification` carries the
bundle, and `prior_acquisitions` may retain complete earlier archives for the
same request. Reopening/query/replay reproduce the qualification identity.

The installed form is:

```sh
alpha-dataset publish --inputs /absolute/reviewed/dataset-input.json \
  --store /absolute/saved/raw --snapshots /absolute/saved/snapshots \
  --max-bytes 134217728
```

This is a bounded evidence gate, not an evidence registry or provider
authentication service. Mixed admission scopes in one snapshot remain
unsupported. A successful software fixture does not
supply the historical evidence needed to admit a real sample.

For deeper implementation coverage, use the focused [unit and integration
tests](../../tests/README.md). The application owns command composition and exit
codes; the library contracts above own identities, clocks, quality, recovery and
failure meaning.
