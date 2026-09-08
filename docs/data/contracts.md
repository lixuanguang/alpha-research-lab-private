# Market-data foundation contracts

Owner: repository founder. Status: implemented foundation boundary for the
current candidate; acquisition, storage, local-book reconstruction, replay, and
live ingestion remain planned. Scope: immutable authored instrument metadata,
source provenance, strict Binance event records, and one-line Tardis decoding.
This page does not claim a dataset, HTTP request, or trading result.

## Boundary and module ownership

The public package surface is
[`alpha_research.data`](../../src/alpha_research/data/__init__.py). The former
monolithic [`data.models`](../../src/alpha_research/data/models.py) path remains
an import-compatibility facade; new internal code uses the defining modules.

| Module | Contract |
| --- | --- |
| [`data/events.py`](../../src/alpha_research/data/events.py) | Frozen `TaggedEvent` and `MarketEventRecord` templates, shared validation, and `Disconnect` |
| [`data/decoders.py`](../../src/alpha_research/data/decoders.py) | Neutral `DecodeContext` and `PayloadDecoder` protocol; no provider framing or venue schema |
| [`data/providers/tardis/decoder.py`](../../src/alpha_research/data/providers/tardis/decoder.py) | Tardis line framing, capture-time parsing, provenance construction, blank-line handling, and raw JSON handoff |
| [`data/providers/tardis/binance.py`](../../src/alpha_research/data/providers/tardis/binance.py) | Composition of Tardis framing and Binance payload decoding for the configured foundation symbols |
| [`data/venues/binance/events.py`](../../src/alpha_research/data/venues/binance/events.py) | `BinanceMarketEvent`, `DepthSnapshot`, `DepthUpdate`, and `Trade` with Binance symbol and event invariants |
| [`data/venues/binance/payloads.py`](../../src/alpha_research/data/venues/binance/payloads.py) | `BinancePayloadDecoder`, Binance combined-stream envelope decoding, and payload-to-event mapping |
| [`data/venues/binance/decoder.py`](../../src/alpha_research/data/venues/binance/decoder.py) | Explicit compatibility exports for the provider-facing Binance decoder |
| [`data/venues/binance/codecs.py`](../../src/alpha_research/data/venues/binance/codecs.py) | Private payload schemas and cached payload decoders, closed `MarketEvent` union, and strict canonical codecs |
| [`data/models.py`](../../src/alpha_research/data/models.py) | Compatibility imports only; it is not the defining implementation boundary |

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
the canonical encoded snapshot. A general research configuration loader is a
later planned boundary.

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

`BinanceTardisDecoder` in `data/providers/tardis/binance.py` binds a nonempty
tuple of authored `SpotInstrument` mappings. Its `BinancePayloadDecoder` accepts
only the current `tardis.binance.spot` stream forms: `trade`, `depth@100ms`, and
`depthSnapshot`. It requires lowercase stream symbols that resolve to configured
uppercase instruments and rejects unknown streams, symbols, payload mismatches,
invented snapshot timestamps, malformed decimals, and invalid level data.

## Planned boundaries

This candidate does not implement HTTP transport, checkpoints, raw-object or
dataset manifests, an order book, a research configuration loader, accounting,
strategy, replay, report persistence, or operational feed support. Those later
boundaries must add their own contracts and evidence while preserving these
event tags, exact numeric values, source text, provenance, and capture-proxy
semantics.

## Focused coverage

The decoding boundary is covered by
[`test_decoders.py`](../../tests/unit/data/test_decoders.py),
[`test_tardis_decoder.py`](../../tests/unit/data/providers/tardis/test_tardis_decoder.py),
[`test_tardis_binance.py`](../../tests/unit/data/providers/tardis/test_tardis_binance.py),
and [`test_binance_decoder.py`](../../tests/unit/data/venues/binance/test_binance_decoder.py).
These references identify coverage; candidate-specific validation results remain
in the owning roadmap record.
