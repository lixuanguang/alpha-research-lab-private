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
