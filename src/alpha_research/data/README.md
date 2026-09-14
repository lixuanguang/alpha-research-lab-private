# Market-data foundation

Owner: repository founder. Status: implemented for the bounded foundation
candidate. This package owns immutable canonical event records, strict Binance
Tardis line decoding, source provenance binding, and the authored reference
catalog boundary. The M0 dataset pipeline now consumes these libraries for
configured saved-fixture inspection. Acquisition, raw-object retention, local-book reconstruction,
replay, and live feeds remain planned consumers.

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
| [`providers/tardis/decoder.py`](providers/tardis/decoder.py) | Tardis line framing, capture-time parsing, provenance construction, and blank-line disconnect handling; raw exchange JSON is passed to a payload decoder |
| [`venues/binance/events.py`](venues/binance/events.py) | `BinanceMarketEvent`, `DepthSnapshot`, `DepthUpdate`, and `Trade`; shared validation runs before the Binance symbol rule and concrete validators add event invariants |
| [`venues/binance/payloads.py`](venues/binance/payloads.py) | `BinancePayloadDecoder`, source envelope/payload schemas, cached source decoders, and payload-to-event mapping |
| [`venues/binance/codecs.py`](venues/binance/codecs.py) | The closed `MarketEvent` union and reusable strict `MarketEventCodec` |

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
[`SourceRequest`](requests.py) derives immutable per-instrument minute requests.

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
`minor_unit` and exact Decimal text. This candidate does not implement an HTTP
transport, checkpoint/raw store, dataset manifest, order book, research
configuration loader, replay runner, accounting consumer, or operational feed.
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
multiple frames, compression, acquisition, durable raw verification/publication,
resume and dataset-level validation are later consumers. A fixture digest does
not replace MR 03's raw-object descriptor/verifier. No transport or credentials
are read. Existing decoder/provenance/event wire contracts remain unchanged.
