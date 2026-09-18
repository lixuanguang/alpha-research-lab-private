# Market-data foundation

Owner: repository founder. Status: implemented for the bounded foundation
candidate. This package owns immutable canonical event records, strict Binance
Tardis line decoding, source provenance binding, and the authored reference
catalog boundary. The M0 dataset pipeline now consumes these libraries for
configured saved-fixture inspection. MR 03 adds saved raw-object description and
verification; MR 04 adds durable raw-byte publication and verified reads.
MRs 05–06 add bounded partition acquisition, durable manifests and sequential resume.
MR 07 adds the installed command and founder-selected Binance public daily archive acquisition.
MR 08 adds verified saved-row reading with exact bytes and unknown recorder coverage.
MR 09 adds archive-trade decoding and stable occurrences from those saved inputs.
MR 11 adds strict file-backed historical eligibility assertions with separate evidence clocks.
MR 12 adds pure decision-time membership selection and retained, explicitly linked corrections.
MR 13 adds canonical partition quality, explicit degraded use and publication refusal.
MR 14 adds versioned dataset manifests, deterministic identity and saved-input verification.
MR 15 adds atomic local snapshot publication and verified reopening by explicit identity.
MR 16 exposes saved-acquisition publication and quality inspection through installed commands.
Local-book reconstruction, replay and live feeds remain planned consumers.

The current public package surface is defined by
[`alpha_research.data`](__init__.py):

- `DepthSnapshot`, `DepthUpdate`, `Trade`, and `Disconnect` event records;
- the closed `MarketEvent` union and `MarketEventCodec`, with `encode`, `decode`,
  and `validate` methods; and
- `TardisDecoder` and `BinancePayloadDecoder` for reusable source-line decoding.

The [OOP policy](../../../docs/coding_standards/README.md#orchestrator-pipelines-and-libraries)
assigns reusable behavior to cohesive classes. `MarketEventCodec` owns canonical
event validation and encoding; `DomainCodec` owns exact domain hooks and JSON
serialization under the [wire contract](../../../docs/data/contracts.md#provenance-events-and-wire-values).
Reuse each codec instance
across records; its compiled schemas survive both successful and rejected calls.
The two configured decoder classes retain their separate provider-framing and
venue-parsing responsibilities. Repository-wide tooling/test migration and OOP
enforcement remain separate work.

Callers compose the retained decoders directly and reuse `decode_line`. The
[C0 migration](../../../docs/roadmap/README.md#existing-abstractions-to-retain-or-retire)
removes the composition-only subclass and compatibility import paths without
changing serialized events. Internal code imports from defining modules:

| Module | Ownership |
| --- | --- |
| [`events.py`](events.py) | Frozen `TaggedEvent` and `MarketEventRecord` templates, shared field validation, and `Disconnect` |
| [`decoders.py`](decoders.py) | Neutral `DecodeContext` and `PayloadDecoder` protocol for source-independent payload decoding |
| [`raw_objects.py`](raw_objects.py) | Immutable `RawObject` descriptors and bounded verification of exact saved bytes against an expected request |
| [`inputs.py`](inputs.py) | Source-neutral saved-partition, fixture and occurrence-verification contracts |
| [`providers/catalog.py`](providers/catalog.py) | Explicit installed source capabilities; provider and venue selection stays inside adapters |
| [`providers/binance/occurrences.py`](providers/binance/occurrences.py) | Archive row decoding, half-open selection, original lineage and reader cleanup, shared by assembly and verification |
| [`datasets.py`](datasets.py) | Ordered dataset identity, retained admission inputs and verified saved-manifest reading |
| [`snapshots.py`](snapshots.py) | Atomic directory publication, immutable retry and explicit-ID snapshot reopening |
| [`manifests.py`](manifests.py) | Validated acquisition completion prefixes, write-ahead receipts and durable checkpoint replacement |
| [`raw_store.py`](raw_store.py) | Content-addressed `RawStore` publication, verified reads and no-overwrite retry after interruption |
| [`eligibility.py`](eligibility.py) | Strict file-backed membership, catalog/units linkage, bitemporal selection and append-only corrections; unknown and unsupported remain explicit |
| [`providers/tardis/decoder.py`](providers/tardis/decoder.py) | Tardis line framing, capture-time parsing, provenance construction, and blank-line disconnect handling; raw exchange JSON is passed to a payload decoder |
| [`venues/binance/events.py`](venues/binance/events.py) | `BinanceMarketEvent`, `DepthSnapshot`, `DepthUpdate`, and `Trade`; shared validation runs before the Binance symbol rule and concrete validators add event invariants |
| [`venues/binance/payloads.py`](venues/binance/payloads.py) | `BinancePayloadDecoder`, source envelope/payload schemas, cached source decoders, and payload-to-event mapping |
| [`venues/binance/codecs.py`](venues/binance/codecs.py) | The closed `MarketEvent` union and reusable strict `MarketEventCodec` |

## Read historical eligibility assertions

Use the defining-module API with an explicitly selected catalog. From the repository
root, the following reads the retained synthetic example against an installed package:

```python
# standard library imports
from pathlib import Path

# project library imports
from alpha_research.data.eligibility import EligibilityAssertions
from alpha_research.reference_data import CatalogSnapshot
from alpha_research.serialization import DomainCodec

codec = DomainCodec()
catalog = codec.decode_json(
    Path("configs/reference/binance-archive-spot.json").read_bytes(), CatalogSnapshot
)
history = EligibilityAssertions.read(Path("tests/fixtures/mr11/eligibility.json"), catalog=catalog)
for assertion in history.assertions:
    print(assertion.state, assertion.ts_knowledge, assertion.evidence.basis)
```

The four retained assertions compare 2026-authored knowledge with synthetic
2024 availability, and keep a hypothetical delisting exclusion. The source document
identity and clocks are explicit author attestations; the reader does not fetch or
authenticate source evidence. It reuses `DomainCodec` for exact round trips and
validates the complete selected catalog before returning any history. Missing files
raise `OSError`; invalid files or linkage raise `ValueError`. A failed read retains no
partial state, so correcting the input and calling `read` again is sufficient.

The [contract](../../../docs/data/contracts.md#historical-eligibility-assertions-mr-11)
defines evidence/interval rules; [NB 11](../../../examples/research-foundations.ipynb)
shows required failures. [Installed acceptance](../../../docs/roadmap/mr-11-implementation.md#installed-wheel-outside-the-checkout)
copies these files outside the checkout and invokes the retained consumer there.

## Select membership at a decision

MR 12 uses the same history object; queries and appends keep no mutable selection
state. Continue the example above with the separate synthetic correction fixture:

```python
# standard library imports
from datetime import UTC, datetime

# project library imports
from alpha_research.data.eligibility import EligibilityAssertion

history = EligibilityAssertions.read(Path("tests/fixtures/mr12/eligibility.json"), catalog=catalog)
members = []
for instrument in catalog.instruments:
    result = history.select(
        instrument.instrument_id,
        valid_at=datetime(2024, 6, 1, 2, tzinfo=UTC),
        known_at=datetime(2024, 6, 1, 12, tzinfo=UTC),
    )
    if isinstance(result, EligibilityAssertion) and result.state == "included":
        members.append(instrument.symbol)
print(members)  # ['ETHUSDT']; before noon the same validity instant includes BTC too.
```

The result is an assertion with evidence/reason, `"unknown"` for uncovered known
membership, or `"unsupported"` for an ID absent from the bound catalog. Treat only
explicit inclusion as eligible. Both clocks require aware UTC, with a half-open
valid interval and inclusive knowledge cutoff. Naive/non-UTC queries fail without
changing history. Invalid input must be corrected before retrying.

To record a correction, create an `EligibilityAssertion` with new evidence,
strictly later knowledge and `supersedes=prior.identity`, then call
`updated = history.append(correction)`. This returns a validated version-2 history;
all predecessors remain available. The whole prior assertion retires when the
correction becomes known, including any validity dates removed by the correction.
Dangling, cross-member, same-time, unevidenced or branched corrections fail.
Version-1 inputs remain supported; only version 2 admits corrections.

The [selection contract](../../../docs/data/contracts.md#decision-time-selection-and-corrections-mr-12)
defines precedence and unknown outcomes. [NB 12](../../../examples/research-foundations.ipynb)
displays both clocks' boundaries and controlled failures; the
[installed record](../../../docs/roadmap/mr-12-implementation.md) runs the same contract
outside the checkout. This is synthetic membership evidence, without historical
source authentication, quality acceptance or publication.

## Catalog and event identity

[`reference_data.py`](../reference_data.py) owns immutable `SpotInstrument` and
`CatalogSnapshot` records. The authored
[`binance-spot.json`](../../../configs/reference/binance-spot.json) is a bounded
research assumption: it records canonical instrument IDs, uppercase symbols,
complete `Currency` values, price ticks, UTC validity intervals, and fixed
Binance spot/Tardis metadata. `CatalogSnapshot.resolve` requires one instrument
to cover the complete requested half-open interval; duplicate IDs or symbols,
unsupported metadata, and incomplete coverage fail closed. Its identity hashes
the canonical encoded snapshot. [`Configuration`](../configuration.py) resolves
explicit data-job/universe selections against that complete interval;
[`SourceRequest`](requests.py) derives immutable per-instrument source requests: Tardis
minutes or Binance daily archives. The separate archive catalog uses
`binance.archive.spot`; resolution rejects a provider/catalog source mismatch.

Every canonical event retains `EventProvenance`, the original capture text,
event-time basis, configured symbol and instrument ID, source stream, and raw
line. `Disconnect` is the intentional exception: it has null symbol and
instrument ID, the `global` stream, and an empty raw line. The closed wire tags
are `depth_snapshot`, `depth_update`, `trade`, and `disconnect`. Decimal prices,
quantities, and levels remain exact `Decimal` values; Python constructors reject
floats and malformed values. Canonical event codecs reject unknown fields, while
raw vendor envelopes and payload schemas intentionally tolerate source extras.

The current Tardis implementation parses the leading ISO UTC capture text with
`TardisDecoder.parse_capture_time` in
[`providers/tardis/decoder.py`](providers/tardis/decoder.py). Source fractions beyond
microsecond precision round
upward by one microsecond when discarded digits are nonzero. `DecodeContext`
keeps source sequence, raw text, source digest, receipt
and ingestion times, and builds source-capture provenance. A blank source line
becomes an explicit `Disconnect` with a conservative proxy supplied by the
caller and reason `next_source_capture` or `interval_end`. Provider framing does
not impose a venue JSON envelope; `BinancePayloadDecoder` requires Binance's
combined-stream `stream`/`data` envelope before mapping payload fields.

`BinancePayloadDecoder` binds a nonempty tuple of authored `SpotInstrument`
mappings and accepts only the current `tardis.binance.spot` stream forms:
`trade`, `depth@100ms`, and `depthSnapshot`. It maps lowercase stream symbols to
the configured uppercase instrument and rejects unknown or mismatched payloads.
`BinanceMarketEvent.validate()` calls shared `MarketEventRecord.validate()`
before the Binance symbol check; concrete event validators then enforce their
depth and trade invariants.

## Pipeline use

An orchestrator constructs `BinancePayloadDecoder` with its instrument selection,
passes it to `TardisDecoder`, and reuses `decoder.decode_line(...)` for each
source line. The payload decoder validates and indexes the instrument selection
once. Each line call receives its own source sequence, local timestamps, optional
digest, and any blank-line capture proxy.

The following illustrates the call boundary; `instruments`, `line`,
`source_sequence`, and `local_received` are supplied by the caller:

```python
# project library imports
from alpha_research.data import BinancePayloadDecoder, MarketEventCodec, TardisDecoder

codec = MarketEventCodec()
decoder = TardisDecoder(
    payload_decoder=BinancePayloadDecoder(instruments),
    source_id="tardis.binance.spot",
)
event = decoder.decode_line(
    line,
    source_sequence=source_sequence,
    local_received=local_received,
)
encoded = codec.encode(event)
restored = codec.decode(encoded)
```

The intended orchestrator owns input reading, source ordering, capture-proxy
selection, error policy, and delivery to downstream consumers. The decoder and
the lower-level parsing, validation, and codec modules are reusable library
components; decoding performs no acquisition or persistence. Orchestrator
composition is now implemented by [`pipelines/dataset.py`](../pipelines/dataset.py)
for the M0 fixture consumer. Its `main` orchestrator owns configuration/catalog
loading, explicit selection, output and exit codes; `inspect_fixture` owns
bounded frame I/O and direct decoder construction. No replacement decoder wrapper is needed.

## Boundaries and planned consumers

`DomainCodec` in `serialization.py` provides the strict exact-domain hooks used by
the catalog and event codecs, including complete currency wire values with `code` and
`minor_unit` and exact Decimal text. The acquired raw inputs do not yet supply a
dataset manifest, order book, research configuration loader, replay runner,
accounting consumer or operational feed.
Those later boundaries must add their own schemas, tests, and evidence without
changing the meaning of the foundation records or silently widening the Binance
source selection.

Focused coverage is in
[`test_decoders.py`](../../../tests/unit/data/test_decoders.py),
[`test_tardis_decoder.py`](../../../tests/unit/data/providers/tardis/test_tardis_decoder.py),
[`test_tardis_binance.py`](../../../tests/unit/data/providers/tardis/test_tardis_binance.py),
[`test_binance_events.py`](../../../tests/unit/data/venues/binance/test_binance_events.py),
[`test_event_provenance.py`](../../../tests/unit/core/test_event_provenance.py),
[`test_reference_data.py`](../../../tests/unit/test_reference_data.py),
[`test_binance_decoder.py`](../../../tests/unit/data/venues/binance/test_binance_decoder.py), and
[`test_serialization.py`](../../../tests/unit/test_serialization.py), alongside
the financial-unit tests that exercise exact Currency values. These references
describe library coverage. The
[P1 acceptance map](../../../docs/roadmap/README.md#p1-acceptance-map)
identifies the remaining end-to-end requirements.

## Configured fixture command

Use the installed `alpha-inspect-fixture` command with an explicit configuration,
catalog, job and saved frame. For a development checkout:

```sh
uv run --frozen --no-editable alpha-inspect-fixture \
  --config configs/data-jobs/fixture-inspection.json \
  --catalog configs/reference/binance-spot.json --job btc-fixture \
  --fixture tests/fixtures/m0/btcusdt.txt \
  --received 2026-09-14T00:00:00Z --ingested 2026-09-14T00:00:01Z --sequence 0
```

Select `eth-fixture` with `ethusdt.txt`, or `both-fixture` with either saved frame,
to exercise the same implementation. These timestamps and revision/rights
references describe authored synthetic fixtures; provide actual retained receipt,
ingestion and line-position metadata for any other saved input. The complete
[outside-checkout workflow and results](../../../docs/roadmap/m0-implementation.md)
include controlled failures.

The version-1 JSON [configuration](../../../configs/data-jobs/fixture-inspection.json)
separates available `universes` and named `jobs`; `--job` alone selects a run.
Unknown fields, schema versions, duplicate names/IDs, missing universe bindings
and unsupported provider/venue/product/dataset/stream/mode/pipeline/policies fail
before fixture access. Only selected instruments are resolved against the catalog.
M0 supports Tardis/Binance spot raw trades in `fixture` mode through
`dataset.inspect`, with `utc-minute` partitions and `source-capture-v1` semantics.
An unsupported depth frame is rejected even though the retained decoder can parse it.

Job intervals are UTC, minute-aligned, half-open, nonempty and at most one day;
a universe contains 1–32 unique canonical IDs. Requests use the fixed job start
and integer offsets, in minute-major then canonical-ID order. The supplied hour
yields 60 requests per instrument. Capture time, conservatively rounded by the
existing decoder, determines request membership; an exchange event may precede
the capture interval. No historical eligibility claim follows from catalog coverage.

A `ResolvedManifest` retains the complete job, actual sorted instruments,
full catalog with evidence and a hash of installed runtime Python/assets plus
package/codec versions. Its identity ignores input JSON formatting and universe
ordering; changed actual selections, catalog, policies, revisions or code change it.
Request identities also bind the actual instrument, catalog, source selection,
fixed origin and offset, but exclude job/universe names and unrelated selected
instruments. Renaming a job or inspecting the same partition within a wider
universe therefore preserves its request identity. These identities describe
configuration/request content; they are not an authenticated artifact signature.

Success prints one JSON report to stdout containing the manifest/run identity,
request identity/bounds, the exact saved-byte SHA-256 and canonical trade. Input
bytes and original clocks are separately attributable; an invocation time never
replaces them. Failure prints a JSON diagnostic to stderr, including the stage,
job and run identity when resolution completed. CLI syntax errors use argparse's
usage diagnostic. Exit codes are **0** success, **2** configuration/usage,
**3** frame/decoding/clock validation and **4** local I/O. A failed invocation
retains no mutable state; fix the reported input and rerun.

Config, catalog and frame reads are each capped at one MiB. Inspection accepts
one nonblank UTF-8 trade frame, with an optional line ending. Blank disconnects,
multiple frames, compression and acquisition remain unsupported by this command.
Raw-object verification and durable publication are the separate libraries below;
acquisition resume and dataset-level validation remain planned. No transport or credentials
are read. Existing decoder/provenance/event wire contracts remain unchanged.

## Saved raw-object verification

[`RawObject`](raw_objects.py) describes one retained binary file with SHA-256,
nonnegative byte size, `SourceRequest.identity` (including the instrument and
minute partition), an opaque non-secret retrieval reference and original local
receipt/ingestion times. Both times must be timezone-aware UTC and ingestion
cannot precede receipt. Verification never substitutes the current time.

Use `RawObject.from_file(path, request=request, retrieval_reference=reference,
ts_received=received, ts_ingested=ingested)` with explicit saved-file provenance,
then `descriptor.verify(path, request=expected_request)` to reopen and verify it.
Successful verification returns the same immutable descriptor. The existing
`DomainCodec.encode_json` / `decode_json(..., RawObject)` provides strict version-1
serialization, rejecting unknown fields and invalid types, values or clocks.

The factory and verifier hash/count one binary stream in one-MiB chunks, including
compression headers/trailers and line endings. No decompression or decoding occurs.
The verifier revalidates metadata and checks the independently expected request
before file I/O. Changed bytes fail SHA-256; truncation or append fails byte size;
another instrument, partition or source policy fails request identity. These are
`ValueError` diagnostics; file access/read failures propagate as `OSError`.
After a failed check the descriptor remains reusable with the original bytes.

The caller must supply trusted metadata and exclude concurrent writers during
description/verification. This checks observed bytes, not later reads, provider
authenticity or semantic membership of the payload in the assigned request.
Describing already incomplete bytes cannot prove transport completeness. Empty
files are representable without claiming a quiet interval. MR 04 supplies the
store below; transport validation remains owned by MR 05.

The [MR 03 acceptance record](../../../docs/roadmap/mr-03-implementation.md) records
focused tests, outside-checkout wheel verification and
[companion notebook](../../../examples/foundation-contract-checks.ipynb) section 11
(NB 03), including a changed gzip header with identical decoded content.


## Durable raw-byte store

[`RawStore`](raw_store.py) binds an explicit existing directory on the destination
filesystem. The caller must durably provision that directory and its ancestors;
the constructor performs no I/O. Use a caller-controlled local filesystem with
atomic hard links and file/directory `fsync`, and keep the directory path stable.
Unsupported filesystem operations propagate failures instead of weakening the
publication guarantee. Import from `alpha_research.data.raw_store`.

Given the descriptor and expected request from the preceding section:

```python
# project library imports
from alpha_research.data.raw_store import RawStore

store = RawStore(storage_directory)
published = store.publish(saved_path, descriptor=descriptor, request=expected_request)
with store.open(descriptor=descriptor, request=expected_request) as stream:
    first_chunk = stream.read(1_048_576)
```

`publish` copies in one-MiB chunks into a unique `.staging-*` file in the same
directory. It flushes buffers, marks the staged file read-only (`0444`), synchronizes
it and calls `RawObject.verify` before linking it to `root/<sha256>`. The hard link
never replaces an existing name. A concurrent winner must pass the same verifier.
Normal completion removes this invocation's staging name and synchronizes the
published file and directory before returning its path. An existing matching
object is reused without reading the source, preserving its inode and modification
time; retries still verify and synchronize it before acknowledging completion.

`open` accepts only the digest-named regular file, rejects symlinks and directories,
verifies all bytes against the trusted descriptor and expected request, then
returns a read-only binary stream at position zero. The caller closes the stream.
Metadata, request, file-kind and byte conflicts raise `ValueError`; missing files
and copy/link/synchronization failures propagate `OSError`. Conflicts are retained
unchanged, never repaired or overwritten automatically. Descriptor serialization,
retrieval reference and original receipt/ingestion clocks are unchanged.

After an abrupt exit before the link, a staging orphan may remain but the object
is absent to readers. After the link, a complete verified object may be visible
without acknowledged durable completion. Retry from the source if absent, or
verify/resynchronize the existing object if present. Staging names are never
adopted or automatically swept: another publisher may still own one. With writers
stopped, remove known orphan staging names; removing their hard links does not
remove a published object. Ordinary exceptions clean this invocation's staging
file when filesystem access permits, but an I/O error after publication does not
imply rollback.

Concurrent writers using this API never mutate published bytes. External writers,
removal/replacement of objects or directory ancestors, and hostile directory access
must be excluded during verification and reads. Mode `0444` guards accidental
writes; it cannot constrain the owner. Durability relies on the filesystem/device
honoring synchronization; process-interruption tests do not prove physical
power-loss behavior or network/object-store support. This MR adds no persistent
descriptor/manifest, garbage collector, acquisition transport or dataset validity.

The [MR 04 acceptance record](../../../docs/roadmap/mr-04-implementation.md),
[storage tests](../../../tests/unit/data/test_raw_store.py) and companion notebook section 12
retain the publication, reuse, conflict and interruption evidence.


## One-partition acquisition

[`fetch_partition`](../pipelines/acquisition.py) composes the configured Tardis
transport, `RawObject` and `RawStore`. Resolve a `Configuration` job with
`mode="historical"` and `pipeline="acquisition.fetch"`, then select one of its
`SourceRequest.partition(manifest)` requests. All existing provider, venue,
product, stream, interval and catalog checks remain active. Fixture inspection
accepts only `dataset.inspect`; changing a job selection cannot silently use the
wrong consumer. The sequential callable below adds the persistent manifest; the
installed acquisition CLI remains MR 07 work.

Supply the callable with the request, an existing `RawStore`, an unopened
`HTTPSConnection("api.tardis.dev")`, a UTC clock, a synchronous JSON report sink,
positive `timeout_seconds` and `max_bytes`, and `permitted_rights_reference`.
The rights reference must match the job and represent caller-confirmed evidence
covering access, intended use, retention and the destination. Empty, mismatched
and explicit `unresolved`/`unknown`/`pending` markers fail. This is explicit caller
admission, not a legal-policy engine: another arbitrary matching string does not
establish permission. Optional `api_key` is supplied directly, never discovered
from environment/configuration or included in reports/descriptors. Disable HTTP
debugging and keep the caller's connection exclusively owned during the attempt.

[`TardisTransport`](providers/tardis/transport.py) sends exactly one GET to the
raw data-feeds endpoint, fixing `from` to the job origin, using the selected
integer offset, one-minute slice, lowercase Binance symbol filter and gzip.
It checks HTTP 200, gzip encoding, one-minute response metadata when present,
Content-Length when present, and the gzip trailer/CRC. Compressed and expanded
representations each have the caller's byte cap; empty gzip content is retained
without a coverage claim. The timeout bounds socket inactivity, not total elapsed
time or DNS resolution. There are no retries or redirects. Invalid HTTP/gzip
responses publish nothing; semantic frame validation and bounded saved-line
iteration remain MR 08/09 work. A gzip-wrapped invalid exchange message may be
retained as raw evidence, never labeled a validated dataset.

The pipeline emits JSON with run/request identity, partition start, stage,
status and byte count. Status progresses from `started` to `received` to `stored`;
exceptions emit `failed` with an error type, without response bodies or credentials.
The original local receipt clock is sampled after fetch validation; ingestion is
sampled after durable publication. Successful return is an immutable `RawObject`;
retain it with its resolved request. Transport state and temporary files belong
to this invocation. Connections close after attempted HTTP operations.

A storage, clock or report-sink failure after publication can leave a verified
object without successful acknowledgement. Preserve those bytes and diagnose the
failure; do not infer rollback or advance a checkpoint. Use the sequential
acquisition callable below for durable manifest reconciliation, restart and retry. The caller must keep the report sink
available; a failing sink propagates and can prevent terminal telemetry delivery.

The [MR 05 record](../../../docs/roadmap/mr-05-implementation.md) contains exact
verification commands, the source-documentation investigation, and the open
rights/retention and actual-source framing/timestamp boundaries. Notebook section
13 calls the installed implementation with synthetic HTTP responses and then
uses the retained decoders on the saved bytes.


## Sequential acquisition and resume

[`acquire`](../pipelines/acquisition.py) consumes one expected `ResolvedManifest`
with the existing `historical` / `acquisition.fetch` selection. It uses the same
connection, store, admission, byte bounds, UTC clock and report sink as
`fetch_partition`. Additionally supply `manifest_path` in an existing durable
directory, an explicit `sleep(seconds)` callback, and optionally `retry_delays`.
The default `(1.0, 2.0)` permits two additional attempts for the active partition.
It returns an [`AcquisitionManifest`](manifests.py) with one completed descriptor
per request in minute-major/instrument order.

The caller exclusively owns the manifest path throughout the invocation and
protects it and the store from external mutation/removal. Resume requires the same
resolved run identity, including implementation, actual universe/catalog, rights
and policies. Unknown schemas/fields, invalid nested values, foreign requests,
duplicate/out-of-order completions and invalid clocks fail. An absent manifest
starts a new empty run; preserve this file with its stored objects. No migration
of a manifest to another implementation identity is implied.

The manifest stores the full resolved run, a completed prefix and at most one
pending receipt. Each atomic file replacement retains that full completion history.
Receipt persistence precedes raw publication; completion is appended only after
verified durable publication. The file is staged on the destination filesystem,
flushed and synchronized, replaced atomically, then its parent directory is
synchronized. This requires local atomic replacement and file/directory `fsync`.
The bounded manifest is read, validated and rewritten in memory; this is not a
concurrent-writer journal or a large-history storage backend. Ignore leftover
`.checkpoint-*` staging files; remove them only after their writer has stopped.

| Reopened state | Behavior |
| --- | --- |
| Completed descriptor | Verify bytes before new source access; skip its request. Missing, mutated, truncated or nonregular objects fail. |
| Pending receipt, raw bytes absent | Fetch that request again; persist the new receipt before publication. No completion was previously claimed. |
| Pending receipt, raw bytes present | Verify and synchronize the existing object, preserving its bytes/inode and original receipt; append one completion. Corrupt pending bytes fail. |
| Complete manifest | Verify all objects and return without another fetch or logical completion. |

For recovered pending objects, `ts_received` remains the original receipt instant;
`ts_ingested` records recovery's post-synchronization confirmation. The pending
record's provisional ingestion value is never a completed-ingestion claim.
Already completed clocks remain unchanged. Fixed-clock interruption fixtures yield
byte-identical resumed/uninterrupted manifests; actual recovery clocks can differ.

`TransientFetchError`, an `OSError` subtype, identifies HTTP 408/429/500/502/503/504,
socket timeouts, connection failures and HTTP protocol failures. These failures
consume the explicit finite nonnegative backoff tuple. `fetch_partition` now wraps
socket timeouts in this type, preserving the original exception as its cause;
callers that previously caught only `TimeoutError` must catch `TransientFetchError`.
HTTP 401/403 remain terminal `PermissionError`; other unclassified statuses and
OS failures are terminal, as are schema/gzip, storage, checkpoint and callback
errors. Exhaustion propagates the last transient error with the manifest incomplete.
No retries occur after a storage or checkpoint failure within the invocation;
reopen before retrying uncertain persistence.

Existing partition reports are retained. Retry reports include run/request identity,
attempt and delay; `checkpointed` includes the durable completion count. Propagated
exceptions remain the failure boundary; a failed report sink cannot guarantee its
own telemetry. The installed command below adds whole-job reporting in MR 07.
The [MR 06 record](../../../docs/roadmap/mr-06-implementation.md) and companion notebook
section 14 contain actual synthetic commands/results. No source acceptance,
canonical dataset, frame iteration or coverage claim is added.

## Installed acquisition command

`alpha-acquire` (or `python -m alpha_research.pipelines.acquisition`) resolves the
explicit `--job` from `--config` against `--catalog`, then calls the same `acquire`
operation above. Use a `historical` / `acquisition.fetch` job and an existing,
durably provisioned manifest directory/raw store under exclusive caller control.
Config/catalog reads retain the one-MiB limit. The manifest cannot overwrite
these input paths. No manifest format or event serialization changes in MR 07.

For **admitted source inputs only**, the installed command shape is:

```sh
alpha-acquire --config /protected/jobs.json --catalog /protected/catalog.json \
  --job admitted-job --manifest /protected/run/manifest.json --store /protected/run/raw \
  --rights-reference admitted-evidence-reference --api-key-env TARDIS_API_KEY \
  --timeout-seconds 30 --max-bytes 16777216 --retry-delays 1 2 \
  >> /protected/run/attempts.jsonl 2>> /protected/run/errors.jsonl
```

These paths, limits and admission are illustrative, not a performed source probe.
Supply actual reviewed rights evidence matching the job; a string is an attestation,
not automatic admission. Existing synthetic rights references authorize only the
injected fixture. `--api-key-env` names an already provisioned environment variable;
its value is read without echoing or saving it. Omit this option only for an admitted
keyless request. Timeouts bound socket inactivity, and `max-bytes` bounds each
compressed/expanded partition. Defaults allow two extra attempts with delays of
one and two seconds; `--retry-delays` with no values disables retry. Invalid limits
and delay values fail. No total elapsed-time or throughput guarantee is made.

Repeat the same command after correcting a failure. The existing manifest verifies
all acknowledged bytes before fetching, recovers a published pending object, and
skips completed requests. Missing/mutated stored objects or a changed resolved
run fail; they are never automatically redownloaded or migrated. Keep the manifest,
objects, original configuration/catalog and command output together.

Every record is flushed JSON. Progress goes to stdout; terminal errors go to
stderr. The startup record includes the normalized command and its SHA-256:
resolved run identity, absolute manifest/store destinations, non-secret limits,
retry delays, admission reference and credential-variable name. The resolved
manifest saves the selected job/catalog/code identity. JSON formatting and input
file location do not change the resolved identity; destination/limit changes
change command identity. Neither identity includes credentials or attempt time.

| Field / record | Meaning |
| --- | --- |
| `scope`, `stage`, `status` | Job or partition progress through configuration, resume, fetch, store, checkpoint and completion. A partition `failed` can precede a permitted retry; only job terminal status ends an invocation. |
| `run_identity`, `command_identity`, `request_identity`, `partition_start` | Resolved input, normalized invocation and active partition correlation. Partition start is present on fetch/store records. |
| `total`, `completed` | Expected partitions and acknowledged completion prefix. Totals remain null until resume verification succeeds. |
| `bytes` | Compressed bytes of the active received/stored response; starts at zero. No cumulative network-byte count is claimed. |
| `persisted_bytes` | Sum of compressed sizes in acknowledged descriptors, including the resumed prefix; separate completions can reference shared bytes. Not physical disk usage. |
| `last_persistence` | UTC ingestion instant of the last acknowledged raw descriptor, preserved on repeats; null when none is acknowledged or verification failed. Not the checkpoint file's modification time. |
| `retries`, `attempt`, `delay_seconds` | Invocation retry count, active-partition retry ordinal and its selected delay. Previous invocations' retry history remains in saved reports. |
| `checkpointing` / `checkpointed` | Before/after durable manifest save. A stored object alone cannot advance acknowledged totals. |

Exit **0** means all expected raw partitions are verified; **2** means setup/configuration
or argument syntax failed; **3** means acquisition validation failed; **4** means
I/O, exhausted transport retries or another runtime failure; **130** means keyboard
interruption. Syntax errors use argparse's usage diagnostic. Other failures include
JSON stage/error type and a diagnostic; raw OS/transport exception text is withheld.
Value validation errors identify the invalid input. Inspect retained state and
repeat after correction. SIGKILL/process loss cannot emit a terminal record; use
the process exit, last flushed report and saved checkpoint. A failed output sink
is terminal; reporting cannot guarantee its own availability.

The [MR 07 acceptance record](../../../docs/roadmap/mr-07-implementation.md) and
companion notebook section 15 exercise the installed command outside the checkout through
synthetic HTTP, abrupt interruption, retries, repeats and damaged-byte rejection.
The [main notebook](../../../examples/research-foundations.ipynb) now connects actual
archive acquisition, verified cache reads, row previews and exact financial units.
Each section explains the operation; the linked record retains prior verification.
This is an intermediate raw-acquisition workflow; canonical row decoding, coverage
validation, dataset publication and M1/P1 acceptance remain later work.


## Binance public daily archive acquisition

The founder amended the [P1 source contract](../../../docs/research/p1-baseline.md)
on 2026-09-15. [`BinanceArchiveTransport`](providers/binance/transport.py) owns
public `data.binance.vision` HTTPS, exact filename-bound SHA-256 sidecar checks and
single-member unencrypted deflate ZIP/CRC validation. It never extracts a path or
sends credentials. The existing pipeline selects this adapter from the resolved
job; the raw store, manifest, retry/recovery and CLI exit contracts above are reused.
`TransientFetchError` now lives in `data.providers.transport`; the old Tardis
module import remains the same class for existing callers.

Select [binance-archive.json](../../../configs/data-jobs/binance-archive.json) with
[binance-archive-spot.json](../../../configs/reference/binance-archive-spot.json).
The supported combination is `binance-archive/binance/spot/raw/trade`,
`historical/acquisition.fetch`, `utc-day`, `exchange-time-only-v1`. Select a
minute-aligned nonempty interval within one UTC day, for one or more supported
catalog instruments. Each instrument produces one full-day source request with
`offset_minutes=0`; `request.start/end` describe the downloaded day while the job
retains the research selection. Both boundaries participate in identity. A
cross-midnight selection or Tardis capture policy fails before HTTP.

The notebook provisions durable directories and saves inputs before this command:

```sh
alpha-acquire --config <run-directory>/jobs.json --catalog <run-directory>/catalog.json \
  --job btc-archive --manifest <run-directory>/manifest.json \
  --store <data-directory>/raw \
  --rights-reference binance-public-data-2026-09-15-private-research \
  --timeout-seconds 10 --max-bytes 67108864 --retry-delays 1 2
```

Replace the angle-bracket paths with the notebook's displayed paths before using
a shell. No API key option applies. The reviewed access reference binds the
founder's private research selection to dated public documentation; it does not
automatically establish long-term retention or redistribution rights. The chosen
ignored directory holds a local working copy with no automatic expiry.

Both checksum and ZIP are fetched with identity content encoding and bounded
reads; transient status/network errors retry the complete attempt. Compressed
bytes are buffered up to `max_bytes`; expanded integrity verification uses one-MiB
chunks and the same total bound. SHA mismatch, ZIP/CRC/member/size errors are
terminal and publish no raw completion. The descriptor SHA equals the verified
publisher checksum; the exact ZIP, resolved request and receipt remain saved.
Repeats verify local bytes without consulting a mutable current publisher checksum.
A later publisher revision needs a separately identified acquisition; it must not
silently overwrite this run. CSV semantics and historical coverage are not validated
by the transport. The notebook streams a bounded feasibility inspection separately.

Binance archive rows provide exchange event time (milliseconds before 2025,
microseconds from 2025), no recorder timestamp and no disconnect markers. Neither
today's local receipt nor an event-time simulation assumption establishes historical
knowledge. Existing Tardis fixtures, source-capture decoding and their wire meanings
are unchanged. The MR 08 reader is described below; MR 09 owns canonical row decoding
and absent-capture provenance below, with availability/quality consumers later.

## Saved Binance archive rows

[`BinanceArchiveRows`](providers/binance/rows.py) selects expected daily partitions
from an explicit `AcquisitionManifest` using its existing prefix validation.
Its consumers include the offline notebook's NB 08 checks, the retained
[installed consumer](../../../tests/fixtures/mr08/read_saved.py) and MR 09's
persisted dataset pipeline. The reader constructs no acquisition or event decoder.

For an independently resolved `run`, explicit `manifest_path` and `store`:

```python
# project library imports
from alpha_research.data.manifests import AcquisitionManifest
from alpha_research.data.providers.binance.rows import BinanceArchiveRows

manifest = AcquisitionManifest.read(manifest_path, run=run, store=store)
for partition in BinanceArchiveRows.from_manifest(manifest):
    print(partition.request.start, partition.request.end, partition.recorder_coverage)
    row_count = 0
    for row in partition.read(store, max_bytes=64 * 1024 * 1024):
        row_count += 1
    print(row_count)
```

Each frozen `ArchiveRow` retains the complete `RawObject` origin (digest, request
identity and acquisition clocks), half-open UTC research selection, zero-based
position and exact CSV bytes including LF/CRLF. `columns()` returns seven nonempty
text fields without numerical or event interpretation. Original order and decimal
text survive; the reader neither sorts equal timestamps nor filters the research
interval. Use the shared cached `DomainCodec` for strict round trips.

The reader requires one correctly named, unencrypted deflate ZIP member. Separate
compressed/expanded caps and a configurable per-row cap (default 4096 bytes) bound
reads. Only single-line individual-trade CSV is supported. A final complete row
without a newline is allowed; embedded-newline fields are unsupported. UTF-8 and
CSV syntax/shape failures report the zero-based row. Digest, ZIP CRC, truncation,
member, size and binding failures raise `ValueError`; storage failures propagate
as `OSError`. Exhaust each iterator for full CSV/CRC validation and close it if
stopping early. A yielded prefix is never a published or accepted dataset.

Missing completions (including pending receipts) and missing completed objects
raise `FileNotFoundError`. A valid archive with an empty CSV yields zero rows; zero
raw bytes are an invalid ZIP. Neither empty nor nonempty content supplies recorder
evidence: `recorder_coverage` is always `"unknown"`. No disconnect, capture/knowledge
timestamp or price padding is synthesized. Invalid input remains in immutable
storage, with no checkpoint or dataset mutation. MR 09 adds numeric/time decoding
below; correction, eligibility, quality and publication retain their later owners.

The [MR 08 acceptance record](../../../docs/roadmap/mr-08-implementation.md)
identifies the tested candidate, commands, notebook outputs and limitations.

## Decoded raw occurrences (MR 09)

[`iter_occurrences`](../pipelines/dataset.py) consumes an explicit saved
`AcquisitionManifest` and `RawStore`. The manifest retains the resolved universe
and source bindings. Its persisted adapter is the MR 08 Binance daily-trade reader;
Tardis fixture inspection and public decoders retain their existing behavior.
No acquisition is performed. With the saved manifest, independently retained `run`,
`manifest_path` and `store` from the example above:

```python
# project library imports
from alpha_research.pipelines.dataset import iter_occurrences

manifest = AcquisitionManifest.read(manifest_path, run=run, store=store)
for occurrence in iter_occurrences(manifest, store, max_bytes=64 * 1024 * 1024):
    print(occurrence.identity, occurrence.position, occurrence.event)
```

[`ArchiveTrade.from_row`](providers/binance/trades.py) parses individual trades,
preserving integer timestamps and their `ms`/`us` unit, exact `Decimal` price,
base quantity, publisher quote quantity, trade ID and both flags. The timestamp
unit follows the archive date (microseconds from 2025); it is never guessed by
digit count. Malformed/nonfinite amounts, invalid flags, wrong units and timestamps
outside the requested UTC day fail with the original row position. The pipeline
decodes every row, then yields only the half-open research interval in original
partition/row order, including equal timestamps and repeated trades.

`ArchiveTrade.ts_source_received` and `.ts_knowledge` remain `None`. Acquisition
receipt/ingestion remain on the raw origin. This separate tagged record preserves
the captured `Trade`/`EventProvenance` invariants and wire schema. The existing
`DomainCodec` caches strict typed schemas and emits decimal strings; its retained
JSON-number input support parses exact decimal text without a binary float.
Call constructors/validators before encoding unsafely modified objects, as required
by that codec's validated-input contract.

[`Occurrence`](normalization.py) retains the complete request and raw descriptor,
exact row/line bytes, zero-based position, decoded record and `record_index` (zero
for the current one-record adapters). Its message identity hashes schema, request
identity, raw digest and position; occurrence identity also includes record index.
Identical saved inputs reproduce identities. A different raw object or binding
cannot collide merely because sequences restart at zero. These are positional
occurrence identities, **not** MR 10 economic trade/revision keys. Original capture
text and message grouping survive without changing `Disconnect`.

For a Tardis trade or disconnect, supply its explicit request, raw descriptor,
line bytes and sequence to `Occurrence`. It validates instrument/source, digest,
sequence, acquisition clocks and capture partition. A null instrument/`global`
control applies to that request's instrument subscription; it is not repository-wide.
These saved-file bindings have no live session ID. Collector/session adapters and
query propagation remain with their roadmap owners.

Exhaust the iterator to validate all inputs; close an abandoned prefix. Missing
completions/objects, incompatible bindings and corrupted or malformed inputs fail
without mutating raw storage or the acquisition manifest. Empty archives yield no
occurrences and prove no coverage. Rebuild after correcting/selecting explicit
input; no mutable normalization checkpoint exists. Revisions, eligibility, quality,
snapshot publication and the dataset command remain MRs 10–16.
See the [MR 09 evidence](../../../docs/roadmap/mr-09-implementation.md) and
[NB 09](../../../examples/research-foundations.ipynb), section 9.

## Validate a canonical partition (MR 13)

Import `QualityPolicy` from [`quality.py`](quality.py). For saved Binance inputs,
call `validate_saved_partition` from `alpha_research.pipelines.dataset` with one
explicit acquisition manifest, its `RawStore`, the matching `EligibilityAssertions`,
a positive archive byte cap and a policy. For an already decoded bounded batch,
call `policy.validate(request, occurrences, eligibility=history, corrections=links)`.
The latter admits multiple original/revised raw objects for the same exact request.

The policy supplies `use="exploratory"` or `use="causal"`, an aware UTC `known_at`
eligibility cutoff and positive `timedelta` `max_gap`. Inspect the returned
`scope`, `reasons`, `invalid_count`, `gap_count` and `duplicate_count` before using
`require_canonical()`. The gate raises on rejection, retaining the report; accepted
bytes explicitly retain `exploratory_degraded` scope, all histories and limitations.
There is no current source evidence sufficient for causal acceptance, even when
the observed gap count is zero. This call creates no published dataset or snapshot.

Original source bytes are re-decoded to reject changed clocks or values. Positive
trade quantities are distinct from zero-quantity depth deletions. Repeated identical
occurrences are idempotent; different duplicate origins survive. Wrong records and
unevidenced conflicts return no bytes; terminal saved-reader failures reject the
entire prefix and mark unread rows unvalidated. The originals remain in the store.
See the [quality contract](../../../docs/data/contracts.md#canonical-partition-quality-mr-13)
for interval, units, ordering and count semantics, and the
[retained installed consumer](../../../tests/fixtures/mr13/validate_partition.py)
for a complete synthetic saved-input example. NB 13 in
[research-foundations.ipynb](../../../examples/research-foundations.ipynb) displays
both declared uses and the required failures.


## Identify and verify a dataset manifest (MR 14)

The assembly boundary accepts an ordered tuple of `DatasetInput` records from
[`datasets.py`](datasets.py). Each record retains its own `acquisition`, `policy`,
`eligibility` and `corrections`. This allows independently evidenced inputs to share
one dataset without substituting one catalog, cutoff or correction history for
another. Both `assemble_dataset(inputs, raw_store, max_bytes=limit)` and
`publish_dataset(inputs, raw_store, destination, max_bytes=limit)` consume this form.
Do not also supply shared policy/evidence arguments with these records.
Both entry points reuse exact repeated selections in first-seen order and reject
nonidentical overlaps within the same source, stream and instrument before reading.

Dataset assembly and reopening use the source-neutral reader contract selected by
the installed provider catalog. Provider/venue decoding stays under `providers/`
and `venues/`; a future source does not require a branch in either workflow.
Partitions retain their source, stream, instrument, raw ordering and quality evidence.
Independent streams are not merged into a consolidated cross-venue book.
The currently installed saved adapter and version-1 canonical format still support
archive trades only. MR 25 owns actual LOB adapters, book admission and the versioned
canonical/manifest extension needed for book partitions; configuration alone cannot
enable them. MR 19/20 own later query/replay composition.

The existing shared-evidence call remains supported:

Call `assemble_dataset` from `alpha_research.pipelines.dataset` with an ordered tuple
of complete daily acquisitions, their `RawStore`, a positive raw byte
cap, shared `QualityPolicy`/`EligibilityAssertions`, and correction evidence keyed
by `acquisition.run.identity` (an empty mapping when absent). It returns a
`DatasetManifest` and an equally ordered tuple of canonical bytes after every
quality gate passes. It performs no file writes or snapshot publication.

For working-file verification, serialize the manifest with `DomainCodec`, retain
its `identity` independently, and save each canonical payload under its entry's
`sha256` filename. Import `DatasetManifest` from [`datasets.py`](datasets.py) and
call `DatasetManifest.read(path, identity=expected, partitions=directory,
store=raw_store, max_bytes=limit)`. The limit applies per manifest, canonical file
and compressed/expanded raw archive, so allow enough for the retained full histories.
Missing files, unknown versions, wrong identity, damaged bytes and mismatched
quality admission fail; restore the expected bytes before retrying. Local paths
and build time are not semantic fields. Original evidence clocks are retained.

The reader reuses existing archive, occurrence, eligibility and quality contracts.
It verifies all raw/canonical files and reproduces admission before returning the
manifest. Only `exploratory_degraded` is supported; historical evidence limitations
remain visible. This is a bounded in-memory reference path with one saved raw
archive per partition, not a query API or an atomic snapshot. The
[manifest contract](../../../docs/data/contracts.md#dataset-manifest-identity-and-verification-mr-14)
explains identity and version semantics; the
[isolated consumer](../../../tests/fixtures/mr14/identify_dataset.py) and NB 14 in
[research-foundations.ipynb](../../../examples/research-foundations.ipynb) provide
complete saved-input examples. Atomic publication follows below.

## Publish and reopen an atomic snapshot (MR 15)

Call `publish_dataset(acquisitions, raw_store, destination, max_bytes=limit,
policy=policy, eligibility=history, corrections=corrections)` from
`alpha_research.pipelines.dataset`. Inputs match `assemble_dataset`; `destination`
is an existing, durably provisioned snapshot directory. The result is the explicit
dataset SHA-256 after all selected partitions pass admission and publication succeeds.
This is also the workflow used by `alpha-dataset publish`. Exact repeated inputs
are reused in first-seen order; nonidentical overlapping selections within the same
source/stream/instrument fail. The optional `report(run_identity, quality)` sink
receives admission outcomes, and `progress(status, manifest)` receives `started`
with the candidate identity and `complete` only after durable publication and
verified reopening. A callback failure propagates, including after publication.
Keep that ID with the research inputs. Reopen using
`SnapshotStore(destination, raw_store).read(identity, max_bytes=limit)` from
[`snapshots.py`](snapshots.py). The reader verifies every canonical/raw file and
repeats admission before returning the manifest. `latest` and filesystem paths
cannot stand in for the ID. The MR 16 command below exposes this consumer.
An optional `report(run_identity, quality)` sink on `SnapshotStore.read` or
`DatasetManifest.read` receives each reproduced report after its canonical bytes
match. Inspection uses those reports directly. An earlier partition's report does
not certify a later partition or the complete dataset.

For an already assembled manifest and ordered canonical tuple, use
`snapshots.publish(manifest, payloads, max_bytes=limit)`. A hidden directory stages
its synchronized files; one directory rename publishes all of them together.
Identical retries verify and reuse the existing snapshot. A changed policy yields
a new identity while the old snapshot stays readable. Missing or damaged retained
inputs fail visibly and are never overwritten by a retry.

Keep both stores and their ancestors stable and protected from external changes.
Raw inputs remain in the existing raw store; the snapshot stores canonical files
and the manifest, including the original raw descriptors. The byte cap applies
per file, including expanded raw input. This remains a bounded in-memory reference
consumer. Same-filesystem atomic rename and file/directory synchronization must be
supported. After a reported failure, retry the same inputs: before rename no
snapshot is visible, while after rename a complete snapshot may need its parent
synchronization acknowledged. Abrupt process exits can leave hidden staging
directories; no garbage collection is introduced.

The [snapshot contract](../../../docs/data/contracts.md#atomic-local-snapshots-mr-15),
[isolated installed consumer](../../../tests/fixtures/mr15/publish_snapshot.py) and
NB 15 in [research-foundations.ipynb](../../../examples/research-foundations.ipynb)
show interruption, retry and prior-snapshot preservation. These synthetic snapshots
retain exploratory degraded scope; they do not establish empirical coverage,
historical eligibility, M1 completion or P1 acceptance.

## Publish and inspect from the command line (MR 16)

`alpha-dataset` consumes saved `alpha-acquire` manifests and their retained raw
store. It does not download data or resolve a mutable latest tag. Install the
candidate with `uv sync --frozen --no-editable`, then use an existing snapshot
store directory on a filesystem supporting the MR 15 synchronization/rename contract.

Prepare a strict `QualityPolicy` JSON file with `DomainCodec.encode_json`, for example
`QualityPolicy(use="exploratory", known_at=sample_start, max_gap=timedelta(seconds=30))`.
The cutoff is an explicit UTC decision time; gap tolerance measures observed silence,
not recorder completeness. Supply a strict `EligibilityAssertions` JSON file with
the same catalog as the acquisition. Empty assertions retain unknown membership;
never substitute synthetic assertions for actual historical evidence. NB 16 demonstrates
preparing these files and inspecting their consequences without network access.

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

These are command shapes; replace paths, selected ID and resource limit with the
retained inputs for the run. `max_bytes` bounds each declaration, manifest, canonical
file and compressed/expanded raw archive; it is not a total-memory limit. The
current reference implementation retains admitted partitions in memory and may
verify them several times during publication/reopening. It is not a scalable query API.

`--manifests` accepts complete Binance daily acquisitions with one or more selected
instruments. Assembly uses `AcquisitionManifest.partitions()` to narrow the resolved
instrument tuple for each partition, preserving the job, catalog, implementation,
raw descriptors, request identities and original clocks. Keep the original complete
manifest for acquisition resume; publication never rewrites it. A partial or pending
acquisition fails before its partition views are admitted. Jobs still select one UTC
day; separate days need separate acquisitions.

Exact repeated manifests are reused in first-seen order. Nonidentical acquisitions whose
instrument/time selections overlap fail instead of adding duplicate economics.
Arbitrary overlap reconciliation remains unsupported. Within a partition, MR 10
retains duplicate lineage and evidenced correction histories. Supply each correction as
`--correction <resolved-acquisition-run-sha256> /saved/correction.json`; it is a
strict `Correction` record keyed to the original input run. Multi-instrument evidence
is routed by economic payload identity; dangling, cross-instrument and unused links
fail the whole publication. Routing evidence performs an additional bounded raw
decode for each instrument only when a multi-instrument input supplies corrections.
Omission means no correction evidence; conflicts and unknown run keys fail.
No correction/availability policy is silently relaxed.

Alternatively, use `--inputs /saved/input-a.json /saved/input-b.json` with strict
`DatasetInput` JSON records encoded by `DomainCodec`. Each embeds its acquisition,
policy, eligibility and corrections. This option replaces `--manifests`, `--policy`,
`--eligibility` and `--correction`; mixing the two selection styles fails. The same
installed adapter and canonical-format limits apply to both forms.

Every JSON line is flushed. Normalization emits one quality report per reached
partition, including `run_identity`, `scope`, `invalid_count`, `gap_count`,
`duplicate_count` and retained `reasons`, before its publication gate. These
partition reports use the narrowed run identity, which is also embedded in the
snapshot; source-request identities still match the original acquisition. Invalid
counts cover observed failures, not unread records following a terminal error.
Zero gaps do not prove recorder coverage. Rejected late partitions cannot expose
an accepted dataset prefix. Exploratory gaps remain explicitly degraded; causal
coverage requirements reject the current archive inputs.

Publication reports its candidate snapshot ID before persistence; `persisted`
acknowledges synchronization and `complete` follows the publisher's verified reopening.
Both records use stage `publish`; publication no longer starts another `reopen`
pass after the publisher has already verified the final snapshot. Inspection
verifies raw/canonical bytes and reports quality using the embedded policies and
histories, without the original build-time policy or acquisition files. Exit codes
are 0 for completion, 2 for configuration/usage, 3 for admission/verification, 4
for I/O/unexpected failure and 130 for a handled keyboard interruption. Failure
records go to stderr and include stage, error type, diagnostic and recovery guidance.
Abrupt process death may leave only the last progress record. A failed publication
can leave a complete visible snapshot after rename; repeat the same command to
verify and synchronize it. Preserve both stores and earlier snapshots.

The [MR 16 implementation record](../../../docs/roadmap/mr-16-implementation.md)
records installed synthetic/retained-source results and NB 16. The fixture inspector
`alpha-inspect-fixture` is unchanged. MR 17 owns event selection as of a cutoff.

## Select point events at a cutoff (MR 17)

`AsOfSelector` in `data/asof.py` reads an explicitly identified snapshot or a tuple
of existing admitted canonical partition bytes. It reuses `SnapshotStore`, the
strict cached codecs and the quality/revision/eligibility gates. The notebook and
installed consumer exercise the same selection method:

```python
from alpha_research.data.asof import AsOfSelector

# snapshot_directory, raw_store, snapshot_id and request are explicit saved inputs.
binding = (request.instrument.source, request.manifest.job.stream, request.instrument.instrument_id)
selector = AsOfSelector.read(
    snapshot_directory,
    raw_store,
    identity=snapshot_id,
    max_bytes=262_144,
    precedence=(binding,),
)
events = selector.select(
    (request.instrument.instrument_id,),
    start=request.manifest.job.start,
    end=request.manifest.job.end,
    known_at=decision_time,
)
retained_history = selector.history
```

The caller freezes precedence as an ordered tuple of source ID, stream and
instrument subscription, covering each retained binding exactly once. It is an
explicit input, not inferred from file order or content digests. Selection orders
by effective knowledge, binding precedence, partition start and source position
(including record index). Equal-time ambiguity, overlapping partitions of one
binding and competing economic heads fail and require reconciliation upstream.
Independent bindings have configured precedence, not an asserted global arrival order.

Selection first walks back from each revision head to the latest version whose
effective knowledge is no later than `known_at`. It then checks the half-open
business window and membership at that point's business instant and the independent
cutoff. Captured points use the earliest retained `valid_from` of their duplicate
occurrences; archives use event time. It does not forward-fill one-microsecond
point validity or test availability at `(decision_time, decision_time)`. A known
correction moved outside the window or excluded by membership never falls back
to its retired predecessor. Unknown archive knowledge selects no version; download
and event time are never substituted. This API does not implement an assumed-time
policy or certify historical eligibility.

The immutable returned tuple contains `TradeRevision` envelopes and applicable
`Occurrence` controls in economic order. Inspect a trade envelope's effective
`ts_knowledge`, not only its embedded original event clock. Disconnect occurrences
retain the source/request/instrument binding despite null event instrument IDs.
Known controls before the window start survive as boundary state, and a known
terminal control at the exclusive market endpoint is retained. Unrelated bindings'
controls are excluded. Applying observation invalidation or canceling intents is
owned by later consumers.

`history` remains the complete immutable canonical bytes, with degraded scope,
quality policy/reasons, eligibility histories, controls and revision predecessors.
Keep these quality annotations with any downstream interpretation. They contain
future information and are distinct from the selected event tuple; never use a
terminal-cutoff projection as replay history or treat an empty result as valid
coverage. Each call reconstructs a private validated view, so unsafe mutation of
an earlier returned record cannot affect subsequent queries.

This is a bounded in-memory reference API, without column projection, batching,
query identities, cancellation, event stepping or a performance claim. The MR 19 query consumer below adds bounded batches; MR 20 owns event stepping.
MR 18 requires a measured workload. Snapshot publication
currently supports archive inputs; captured trades and scoped controls are tested
using admitted synthetic canonical bytes, without extending publication support.
See the [acceptance record](../../../docs/roadmap/mr-17-implementation.md) and
[notebook section 7](../../../examples/research-foundations.ipynb).

## Bounded reference queries (MR 19)

`QueryReader` in `data/query.py` opens an explicit snapshot ID through the existing
complete raw/canonical verification. Its constructor also accepts admitted canonical
bytes for synthetic captured-input exercises. `max_bytes` bounds each verified file
and the **sum of retained canonical bytes**. Oversized reference inputs fail; the
reader does not stream an arbitrarily large dataset or impose a process RSS limit.
Memory includes retained bytes, cached admitted partitions, selected rows and copied
evidence. Files close before
`read` returns; subsequent queries do no file I/O.

```python
from contextlib import closing

from alpha_research.data.query import QueryMarketRow, QueryReader

query = QueryReader.read(
    snapshot_directory,
    raw_store,
    identity=snapshot_id,
    max_bytes=262_144,
    precedence=(binding,),
)
with closing(
    query.batches(
        (request.instrument.instrument_id,),
        start=request.manifest.job.start,
        end=request.manifest.job.end,
        known_at=decision_time,
        columns=("price", "quantity", "ts_knowledge"),
        batch_size=32,
    )
) as batches:
    for batch in batches:
        for row in batch.rows:
            if isinstance(row, QueryMarketRow):
                source, stream, instrument = row.binding
                price, quantity, effective_knowledge = row.values
            else:
                control = row  # Full Occurrence: binding, clocks, reason and raw lineage.
```

Available market columns are `identity`, `ts_knowledge`, `price`, `quantity` and
`revision`. Values remain exact `Decimal`/UTC/domain records; `row.binding` always
identifies their source, stream and instrument. `batch.evidence` retains selected
bindings' request/unit definitions, exploratory degraded scope, policy, reasons and
complete membership history. These are in-process typed result containers, not a
new wire format. Original event/revision codecs remain authoritative.

Cutoff mode delegates eligibility, revision selection and ordering to `AsOfSelector`
**before** projecting columns. A price-only query still returns applicable full
control occurrences, including boundary state; unrelated bindings' controls are
absent. Controls count toward `batch_size`. An empty selection emits one empty
batch with its evidence, never a coverage-success claim.

`mode="history"` requires the `revision` column. It returns retained chains through
the inclusive knowledge bound, including unknown-availability originals, along with
full membership evidence and applicable known controls. A chain touching the business
window keeps a later correction that retires its earlier in-window value. Terminal
membership exclusions do not erase that history. Unknown originals remain unusable
until actual evidence permits selection. History is **replay input, not an eligible
cutoff projection**; its partition/head order is not chronological replay order.
MR 20 owns ordering, membership application and shared event stepping.

Every batch carries a versioned query SHA-256 covering input/snapshot identity,
precedence, selected instruments, business bounds, knowledge cutoff, columns and
mode. Batch size and cancellation do not change semantic identity. A cooperative
`cancelled` predicate raises `InterruptedError` before selection or between batches;
`close()` ends iteration and releases local selection state. Loading/selection are
synchronous bounded reference operations, not interruptible mid-validation. Repeated
queries reuse the admitted private partitions and copy returned records/evidence;
unsafe mutation of a result cannot change a later query. History copies records
as each output batch is built. Admission still runs completely when the reader is
constructed; caching never invents knowledge or bypasses snapshot verification.
MR 18 measures this reference optimization and the separate pre-admission Parquet
experiment in its [workload record](../../../docs/roadmap/mr-18-implementation.md).

See [NB 19, section 8](../../../examples/research-foundations.ipynb),
[focused tests](../../../tests/unit/data/test_query.py), and the
[acceptance record](../../../docs/roadmap/mr-19-implementation.md) for measured
memory/read counts, installed-consumer evidence and limitations. MR 19 introduces
no columnar backend or publication adapter; EDA and replay consumers follow below.


## Chronological event stepping (MR 20)

`Replay` in `data/replay.py` consumes an admitted `QueryReader`, explicit instrument
and business bounds, inclusive terminal knowledge time, resolved consumer
configuration SHA-256 and query batch size. It expands retained revision chains
and reuses `AsOfSelector`'s knowledge/precedence/partition/source-position ordering.
Unknown original availability is unschedulable; a later evidenced revision retains
its own availability. Applicable instrument-less controls keep their binding.
Ambiguous source positions fail before any step. The query reader and all existing
wire formats remain unchanged.

Call `step(scheduled_at, consume)` in a loop. Supply the earliest outstanding
consumer decision, expiry or additional fill-eligibility time, recomputed after
each completed step; use terminal if there is no earlier wakeup. The clock moves
to the earliest of that wakeup, next source availability and terminal. Callback
arguments are `(phase, UTC_clock, event_or_none)`: every equal-time `source` event
is delivered first, followed by `expiry`, `fill`, `decision`, `mark`. The consumer
executes only due decisions and uses its owning libraries for expiry, eligibility,
risk, fills and valuation. In particular, phase callbacks are not implemented
orders or fills. Do not use a newly created decision to fill at its own timestamp.

The initial `cursor` is `None`: reading ahead does not advance knowledge. Each
successful step returns a frozen `ReplayCursor`; terminal is processed once and
later calls return `None`. Source callbacks are isolated copies. Complete
membership and quality evidence remains available through `evidence`; callers
use the cutoff selector at the current clock to evaluate eligible observations.
Evidence is retained history, not advance permission to use future assertions.

Serialize cursors with the existing cached `DomainCodec`. Identity binds the
query (including selected snapshot, bounds and precedence), resolved consumer
configuration and `reference-replay-v1` ordering/phase policy. Position is the last
complete logical source key, never a digest tie-breaker. Restore the cursor with
the consumer's observations, pending intents, outstanding schedule, applied-fill
identities and ledger. Resume checks identity, clock and completion of all source
positions through that clock; it cannot certify external state it does not own.
A callback failure propagates and blocks further stepping/checkpointing of that
instance. Recover both consumer state and a new replay from the last completed
checkpoint. Reentrant calls, naive clocks and repeated/backward wakeups fail.

The reference materializes selected history and its sorted index within the
reader's aggregate canonical-byte budget; memory is proportional to bounded input,
not to batch size. It performs no source I/O during stepping. Cancellation is
cooperative during query admission; a consumer can abort a step by raising, with
the same incomplete-step recovery rule. Cursor/phase callbacks expose progress
and failure context without a second telemetry framework.

[NB 20](../../../examples/research-foundations.ipynb) and the
[installed consumer](../../../tests/fixtures/mr20/replay_consumer.py) exercise the
same operation. This trade/control scope rejects unsupported canonical book
inputs. L2/L3 publication/adapters and accepted-snapshot/recovery-epoch state
remain with the later collector consumers. E1/MR 44 own economic batch/resume
proofs; MR 21 consumes this boundary for standalone EDA replay.


## Configured EDA and extension boundaries (MR 21)

`pipelines.eda.inspect_eda(config, snapshots, raw, report=..., consume=...)` is the
installed Python orchestration entry. Supply a strict `data.eda.EdaQuery` JSON
file, an explicit saved snapshot root and its retained `RawStore`. The schema
requires snapshot SHA-256, complete binding precedence, selected instruments,
UTC business bounds `[start, end)`, inclusive `known_at`, columns, cutoff/history
mode, batch size and canonical-byte limit. Unknown fields/capabilities fail; this
entry neither acquires data nor discovers a mutable latest snapshot. The current
selection limit reuses `Universe`'s 32-instrument bound.

The required synchronous `report` callback owns retention. Append its records to
an attempt-specific JSON-lines file with `DomainCodec`; keep the final `complete`
record, which includes resolved config and its identity, installed implementation
identity, semantic query/summary identities and full scoped quality/unit/membership
evidence. Timing and batch-size observations are excluded from semantic identities.
The config identity intentionally includes delivery/budget choices. Failed reads,
invalid config and observer failures emit `failed` with stage, duration and reason,
then propagate; no partial query summary is declared complete. If the report sink
itself fails, delivery cannot be guaranteed: repair it and rerun. Input snapshots
remain immutable; the pipeline owns no persistent mutable analysis state.

`QuerySummary.collect` consumes the same projected batches in the notebook and
standalone workflow. It retains per-binding row counts and exact min/max prices
when projected; quantities/currencies are never summed across instruments. Controls
remain counted and hashed with full lineage. An empty query still retains its
evidence. History summarizes retained heads, not every predecessor or an eligible
economic projection. `Replay` expands versions using their actual availability.
The optional `consume` callback receives each batch for plotting/export and must
not mutate it; any buffering there belongs to the consumer.

Reports include total/query duration, rows, controls, batches, largest batch,
process lifetime peak RSS bytes (macOS/Linux) and OS input-block delta. RSS is not
per-query allocation; input blocks are not application reads and can be zero with
cached inputs. Snapshot admission still verifies full saved inputs; projection
claims no I/O pushdown. The reader's canonical-byte cap is not an RSS bound.

The [standalone consumer](../../../tests/fixtures/mr21/eda_consumer.py) builds a
small deterministic synthetic archive, publishes two instruments, retains EDA
records and replays outside Jupyter. [NB 21](../../../examples/research-foundations.ipynb)
plots the same bounded interval. The [contract fixture](../../../tests/fixtures/mr21/contract.json)
exercises neutral identity, exact quantity/multiplier and projected-batch summaries
only, with no spot-record coercion. It is not admitted to the spot reader/replay;
unsupported source products, lifecycle/adapter fields and unit combinations fail.
See the [acceptance record](../../../docs/roadmap/mr-21-implementation.md) for
commands, observations, justified review size and remaining scope.

## Bounded saved books (MR 25)

`pipelines.dataset.publish_book_dataset` accepts completed native capture or OKX
archive directories, an existing `RawStore`, a provisioned snapshot directory and
explicit `max_records` / `max_bytes` limits. Capture adapters cover Bitfinex R0,
Coinbase Exchange L3 and OKX books. The archive adapter preserves unknown original
availability and sequence. It never applies trade-ID revision rules to order
lifecycles. Exact adjacent duplicates retain raw positions and do not repeat
mutations; conflicting native sequences fail admission.

```python
from alpha_research.data.book_datasets import BookDatasetManifest, BookHistory
from alpha_research.data.raw_store import RawStore
from alpha_research.data.snapshots import SnapshotStore
from alpha_research.pipelines.dataset import publish_book_dataset

# directories, raw_directory and snapshot_directory are explicit caller-owned Paths.
raw = RawStore(raw_directory)
identity = publish_book_dataset(
    directories, raw, snapshot_directory, max_records=32, max_bytes=600_000_000,
)
manifest = SnapshotStore(
    snapshot_directory, raw, manifest_type=BookDatasetManifest,
).read(identity, max_bytes=600_000_000)
```

The separate `book-dataset-v1` format leaves trade manifests and default trade
readers unchanged. Each partition binds the original request, raw descriptor,
selected prefix, normalized complete message states and quality. A `BookHistory`
can be decoded from its verified partition using `DomainCodec`; controls carry
empty state and must not be interpreted as an empty book. L3 orders keep their
native IDs and exact sizes; L2 levels keep aggregate sizes/counts. Zero-size
updates delete levels, while nonpositive prices and zero snapshot sizes fail.

The limit is at most 10,000 raw positions per input (archive configuration may
further restrict it). Complete raw digests are checked; only the selected prefix's
native messages are admitted. A malformed selected frame rejects the whole
partition, and transport gaps remain quality-annotated controls. Full visible
state per market message is a bounded reference representation: byte limits can
refuse a large prefix, and no throughput claim is made. Prior snapshots survive
failure, and reopening reproduces admission from retained original bytes.

Only `exploratory_degraded` publication is supported. Historical eligibility,
complete coverage, full depth, causal use, trade queries, shared chronological
book stepping, fills and execution are not admitted. The
[MR 25 record](../../../docs/roadmap/mr-25-implementation.md) retains acceptance.
