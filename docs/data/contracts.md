# Market-data foundation contracts

Owner: repository founder. Status: implemented foundation boundary for the
current candidate; acquisition, storage, local-book reconstruction, replay, and
live ingestion remain planned. Scope: immutable authored instrument metadata,
source provenance, strict Binance event records, and one-line Tardis decoding.
This page does not claim a dataset, HTTP request, or trading result.

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
| [`data/venues/binance/payloads.py`](../../src/alpha_research/data/venues/binance/payloads.py) | `BinancePayloadDecoder`, Binance combined-stream envelope decoding, and payload-to-event mapping |
| [`data/venues/binance/codecs.py`](../../src/alpha_research/data/venues/binance/codecs.py) | Private payload schemas and cached payload decoders, closed `MarketEvent` union, and strict canonical codecs |

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

The shared serialization boundary in
[`serialization.py`](../../src/alpha_research/serialization.py) encodes exact
Decimal text and complete Currency values with `code` and `minor_unit`.
Canonical event codecs reject unknown fields. Raw vendor envelopes and private
payload schemas intentionally tolerate source extras so a generated source
snapshot with additional fields does not break decoding; known fields and
domain invariants remain strict.

## Capture and source semantics

`parse_capture_time` in
[`data/providers/tardis/decoder.py`](../../src/alpha_research/data/providers/tardis/decoder.py) parses the leading
ISO UTC capture text. A source fraction beyond six digits rounds upward by one
microsecond whenever any discarded digit is nonzero. The original text is
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

## Planned boundaries

This candidate does not implement HTTP transport, checkpoints, raw-object or
dataset manifests, an order book, a research configuration loader, accounting,
strategy, replay, report persistence, or operational feed support. Those later
boundaries must add their own contracts and evidence while preserving these
event tags, exact numeric values, source text, provenance, and capture-proxy
semantics.

### Control scope through queries

MR 09 retains the source, request/input binding and, where applicable,
subscription/capture-session identity that determines a control event's affected
scope. Carry that relationship in the occurrence envelope, input manifest or
query-result quality metadata; the existing `Disconnect` type stays unchanged.
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

The decoding boundary is covered by
[`test_decoders.py`](../../tests/unit/data/test_decoders.py),
[`test_tardis_decoder.py`](../../tests/unit/data/providers/tardis/test_tardis_decoder.py),
[`test_tardis_binance.py`](../../tests/unit/data/providers/tardis/test_tardis_binance.py),
and [`test_binance_decoder.py`](../../tests/unit/data/venues/binance/test_binance_decoder.py).
These tests cover the library boundary; the
[P1 acceptance map](../roadmap/README.md#p1-acceptance-map)
identifies the remaining end-to-end requirements.
