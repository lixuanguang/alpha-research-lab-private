# Market-data foundation

Owner: repository founder. Status: implemented for the bounded foundation
candidate. This package owns immutable canonical event records, strict Binance
Tardis line decoding, source provenance binding, and the authored reference
catalog boundary. Acquisition, raw-object retention, local-book reconstruction,
replay, and live feeds remain planned consumers.

The public package surface is defined by
[`alpha_research.data`](__init__.py):

- `DepthSnapshot`, `DepthUpdate`, `Trade`, and `Disconnect` event records;
- the closed `MarketEvent` union and strict `encode_market_event`,
  `decode_market_event`, and `validate_market_event` codecs; and
- `BinanceTardisDecoder` for reusable source-line decoding.

`alpha_research.data.models` and `alpha_research.data.venues.binance.decoder`
retain compatibility imports for the event and decoder classes. The former
one-off decoding function has been removed; callers use a decoder instance's
`decode_line` method. New internal code imports from the defining modules:

| Module | Ownership |
| --- | --- |
| [`events.py`](events.py) | Frozen `TaggedEvent` and `MarketEventRecord` templates, shared field validation, and `Disconnect` |
| [`decoders.py`](decoders.py) | Neutral `DecodeContext` and `PayloadDecoder` protocol for source-independent payload decoding |
| [`providers/tardis/decoder.py`](providers/tardis/decoder.py) | Tardis line framing, capture-time parsing, provenance construction, and blank-line disconnect handling; raw exchange JSON is passed to a payload decoder |
| [`providers/tardis/binance.py`](providers/tardis/binance.py) | `BinanceTardisDecoder` composition for the configured foundation symbols |
| [`venues/binance/events.py`](venues/binance/events.py) | `BinanceMarketEvent`, `DepthSnapshot`, `DepthUpdate`, and `Trade`; shared validation runs before the Binance symbol rule and concrete validators add event invariants |
| [`venues/binance/payloads.py`](venues/binance/payloads.py) | `BinancePayloadDecoder`, Binance combined-stream envelope decoding, and payload-to-event mapping |
| [`venues/binance/decoder.py`](venues/binance/decoder.py) | Explicit compatibility exports for the provider-facing Binance decoder |
| [`venues/binance/codecs.py`](venues/binance/codecs.py) | Private source-payload schemas and cached payload decoders, the closed `MarketEvent` union, and strict canonical codecs |

## Catalog and event identity

[`reference_data.py`](../reference_data.py) owns immutable `SpotInstrument` and
`CatalogSnapshot` records. The authored
[`binance-spot.json`](../../../configs/reference/binance-spot.json) is a bounded
research assumption: it records canonical instrument IDs, uppercase symbols,
complete `Currency` values, price ticks, UTC validity intervals, and fixed
Binance spot/Tardis metadata. `CatalogSnapshot.resolve` requires one instrument
to cover the complete requested half-open interval; duplicate IDs or symbols,
unsupported metadata, and incomplete coverage fail closed. Its identity hashes
the canonical encoded snapshot. A general configuration loader is planned and is
not part of this candidate.

Every canonical event retains `EventProvenance`, the original capture text,
event-time basis, configured symbol and instrument ID, source stream, and raw
line. `Disconnect` is the intentional exception: it has null symbol and
instrument ID, the `global` stream, and an empty raw line. The closed wire tags
are `depth_snapshot`, `depth_update`, `trade`, and `disconnect`. Decimal prices,
quantities, and levels remain exact `Decimal` values; Python constructors reject
floats and malformed values. Canonical event codecs reject unknown fields, while
raw vendor envelopes and payload schemas intentionally tolerate source extras.

The Tardis provider decoder parses the leading ISO UTC capture text with
`parse_capture_time` in [`providers/tardis/decoder.py`](providers/tardis/decoder.py). Source fractions beyond
microsecond precision round upward by one microsecond when discarded digits are
nonzero. `DecodeContext` keeps source sequence, raw text, source digest, receipt
and ingestion times, and builds source-capture provenance. A blank source line
becomes an explicit `Disconnect` with a conservative proxy supplied by the
caller and reason `next_source_capture` or `interval_end`. Provider framing does
not impose a venue JSON envelope; `BinancePayloadDecoder` requires Binance's
combined-stream `stream`/`data` envelope before mapping payload fields.

`BinanceTardisDecoder` binds a nonempty tuple of authored `SpotInstrument`
mappings and accepts only the current `tardis.binance.spot` stream forms:
`trade`, `depth@100ms`, and `depthSnapshot`. It maps lowercase stream symbols to
the configured uppercase instrument and rejects unknown or mismatched payloads.
`BinanceMarketEvent.validate()` calls shared `MarketEventRecord.validate()`
before the Binance symbol check; concrete event validators then enforce their
depth and trade invariants.

## Pipeline use

An orchestrator creates one `BinanceTardisDecoder(instruments)` for its configured
instrument selection and reuses `decoder.decode_line(...)` for each source line.
The constructor validates and indexes the instrument selection once. Each call
receives its own source sequence, local timestamps, optional digest, and any
blank-line capture proxy.

The following illustrates the call boundary; `instruments`, `line`,
`source_sequence`, and `local_received` are supplied by the caller:

```python
from alpha_research.data import BinanceTardisDecoder

decoder = BinanceTardisDecoder(instruments)
event = decoder.decode_line(
    line,
    source_sequence=source_sequence,
    local_received=local_received,
)
```

The intended orchestrator owns input reading, source ordering, capture-proxy
selection, error policy, and delivery to downstream consumers. The decoder and
the lower-level parsing, validation, and codec modules are reusable library
components; decoding performs no acquisition or persistence. Orchestrator
pipelines remain planned consumers.

## Boundaries and planned consumers

`serialization.py` provides the strict exact-domain hooks used by the catalog
and event codecs, including complete currency wire values with `code` and
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
[`test_binance_models.py`](../../../tests/unit/data/venues/binance/test_binance_models.py),
[`test_binance_events.py`](../../../tests/unit/data/venues/binance/test_binance_events.py),
[`test_event_provenance.py`](../../../tests/unit/core/test_event_provenance.py),
[`test_reference_data.py`](../../../tests/unit/test_reference_data.py),
[`test_binance_decoder.py`](../../../tests/unit/data/venues/binance/test_binance_decoder.py), and
[`test_serialization.py`](../../../tests/unit/test_serialization.py), alongside
the financial-unit tests that exercise exact Currency values. These references
describe coverage. The [P1 planning verification record](../../../docs/roadmap/p1-implementation-roadmap.md#planning-verification-record)
identifies the inspected main revision and focused foundation checks; it does not
claim end-to-end P1 acceptance. The former commit-02 Currency revision record
remains in Git history at `664e501:docs/roadmap/p1-commit-sequence.md`.
