# Point-in-time semantics for the market-data foundation

Owner: repository founder. Status: implemented for the immutable provenance and
Tardis decoder foundation; dataset acquisition and replay consumers are planned.
The current boundary defines timestamp meaning without claiming a downloaded
sample or historical venue truth.

## Distinct clocks and validity

| Concept | Field | Meaning |
| --- | --- | --- |
| Source event | `provenance.ts_event` | Event instant reported by the source, or a documented capture proxy for snapshots/disconnects |
| Source capture | `provenance.ts_source_received` and `original_capture_time` | Vendor capture instant and its original text, used as the source-capture knowledge basis |
| Local receipt | `provenance.ts_received` | When the caller received the raw source line |
| Local ingestion | `provenance.ts_ingested` | When the caller durably ingested the line; it cannot precede receipt |
| Knowledge time | `provenance.ts_knowledge` | Earliest time the validated event could be used by a bounded consumer |
| Valid time | `valid_from` / `valid_to` | Half-open business interval to which the event assertion applies |

All supplied instants are aware and normalized to UTC. `EventProvenance` keeps
source revision, digest, and zero-based source sequence attached to the event.
`is_available(decision_time, valid_time)` is true only when knowledge is no
later than the decision cutoff and the business time lies in the half-open
validity interval.

## Capture precision and proxies

Tardis source lines begin with an ISO UTC capture string. The provider decoder
preserves it in `original_capture_time` and parses it through
`parse_capture_time` in [`data/providers/tardis/decoder.py`](../../src/alpha_research/data/providers/tardis/decoder.py). Python timestamps
represent microseconds, so a source fraction with more than six digits is
rounded **up** by one microsecond whenever any discarded digit is nonzero. This
conservative ceiling prevents availability from moving earlier than the
captured instant. A millisecond Binance `E`/`T` timestamp is converted to an
exact UTC microsecond timestamp without binary floating point.

Provider framing does not impose a venue JSON shape. Binance payload decoding
requires the typed Binance combined-stream `stream`/`data` envelope. This keeps
capture and availability semantics independent of venue payload interpretation.

Depth snapshots contain no exchange event timestamp in the selected payload.
Their `event_time_basis` is `capture_proxy`, with event and knowledge time set
to the rounded capture. A blank line is a `Disconnect`; the caller supplies its
proxy from the next nonblank source capture or the interval end, and the reason
is retained as `next_source_capture` or `interval_end`. These are source
availability proxies, not observations of an exchange clock or network latency.

## Ordering and source identity

The Tardis provider decoder preserves source-line order, including equal capture
timestamps, through the nonnegative `source_sequence`. Its immutable
`DecodeContext` retains the source ID, raw line, optional raw-object digest,
local receipt/ingestion times, capture text, and parsed capture time. Its
provenance builder uses `knowledge_basis="source_capture"`, and the decoder
rejects naive timestamps, invalid sequences, malformed capture text, and missing
blank-line proxies.

The current Binance payload adapter maps only configured lowercase stream symbols
and the `trade`, `depth@100ms`, and `depthSnapshot` streams. Source decimal text
is parsed as exact `Decimal`; unknown streams, symbols, payload mismatches, and
invented snapshot timestamps fail at the payload boundary. The adapter does not
download data or assert historical exchange metadata in this foundation
candidate.

## Planned consumers

The semantics above are inputs to the planned raw store, dataset publication,
order-book, and replay boundaries. Those consumers must preserve the original
capture text, source sequence, provenance identity, exact values, and proxy
reasons when they add persistence or point-in-time selection.
