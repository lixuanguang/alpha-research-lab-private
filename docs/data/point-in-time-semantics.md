# Point-in-time semantics for the market-data foundation

Owner: repository founder. Status: implemented for the immutable provenance and
Tardis decoder, saved datasets, queries, replay and bounded spot economic consumers.
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

## Binance archive source amendment

On 2026-09-15 the founder selected public Binance daily trade archives for the
[P1 sample](../research/p1-baseline.md). Acquisition downloads and retains exact ZIP
bytes. The archive `time` is exchange event time: milliseconds for the selected
2024 sample, microseconds for spot archives from 2025-01-01. These rows supply
neither recorder capture nor historical knowledge clocks or disconnect markers.
Do not pass them through the Tardis decoder or invent its required capture prefix.

`exchange-time-only-v1` is the acquisition selection's explicit time policy.
Local receipt/ingestion describe acquisition today and remain preserved on repeat.
The row decoder preserves absent-capture provenance and the cutoff selector
preserves unknown availability. An explicit `event-time-assumption-v1` research
scenario may assume event-time availability without claiming historical knowability.
The Tardis-specific capture rules below remain valid for their existing inputs.

## Capture precision and proxies

Tardis source lines begin with an ISO UTC capture string. The provider decoder
preserves it in `original_capture_time` and currently parses it through the
`TardisDecoder.parse_capture_time` method in
[`data/providers/tardis/decoder.py`](../../src/market_data/adapters/providers/tardis/decoder.py).
The provider owns this parsing behavior and preserves the timing rules. Python
timestamps represent microseconds, so a source fraction with more than six digits is
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

### Chronological ordering and event stepping

[`AsOfSelector`](../../src/market_data/query/asof.py) supplies the reference cutoff
order; the bounded [`Replay`](../../src/market_data/replay/events.py) iterator
supplies the clock/cursor and scheduled-step operation. Economic composition through that operation is implemented in the
[spot consumer](../../src/simulation/README.md). The [cutoff guide](../../src/market_data/README.md#select-point-events-at-a-cutoff)
defines the implemented projection and its separate retained history.

Order admitted events by effective knowledge time, then predefined source/stream
precedence, stable logical partition/session order and source-local sequence.
Freeze precedence in the resolved input configuration before a run. For P1's
single stream, use partition start and zero-based raw line position within each
partition. Deduplicate/reconcile object versions before scheduling; unresolved
competing versions or ambiguous logical ordering fail admission. Preserve each
admitted revision and its effective availability in replay history: a
latest-revision projection at one cutoff is a distinct query result, not a
history for replay through earlier cutoffs. Query and replay consumers must not collapse history
at the terminal cutoff before advancing the clock. Instrument/column selection
also preserves [applicable control information](contracts.md#control-scope-through-queries).
Content hashes, whole-snapshot identities and digest-derived occurrence IDs identify retained
bytes and lineage; they must not resolve an economically meaningful tie. This
does not claim an observed global arrival order across independent sources.

Advance the replay clock chronologically to the next relevant source-availability
time, decision time, pending-intent expiry or terminal time. Schedule any
additional fill-eligibility time required by the timestamp model explicitly;
P1's candidate fill time is `max(ts_event, effective_knowledge)` after both
timestamps satisfy its positive-delay rule. Waiting does not make an otherwise
ineligible old trade eligible. A query batch is only a delivery unit: read-ahead
must not make later information available at an earlier step or defer an earlier
fill until the next decision boundary.

At each simulation timestamp, admit all then-known source events in that order
(including gap/correction information), expire old intents, apply a still-eligible pending
fill, evaluate any scheduled decision, then mark NAV. A fill at exact expiry is
ineligible. A gap becoming known at the same time cancels the pending intent
before a prospective fill. A new decision cannot fill at its own step. The
scheduler owns this phase order; libraries compute the operations and pipelines
own composition and per-instance economic state.
Complete source admission for that timestamp across batch boundaries before
applying the remaining phases. Phase precedence applies within one timestamp,
never across an entire batch or decision interval.

The tested synthetic chronology case creates an intent at `00:02:00`, fills on an
eligible trade known at `00:02:01`, then admits a gap at `00:02:30`. The later
gap cannot undo the accepted fill, although its coverage/valuation consequences
remain visible. With identical saved inputs, config and ordering policy, batch
size `1` and batch size `k` must produce the same economic trace: decisions,
rejections, accepted fills, costs and balances. Diagnostic batch counts may differ.
Include a batch boundary within
an equal-time trade/control group, alongside exact-expiry and resume cases.

A cursor binds the input/configuration and ordering-policy versions and a stable
logical source position. Resume at a completed step, with the clock, frozen
observations, pending intent, outstanding scheduled times, applied-fill identities
and ledger supplied by the consumer; otherwise reject the incomplete/incompatible
checkpoint. Existing replay checks cover event/cursor parity; the economic consumer additionally verifies that complete resumed economic state
equals uninterrupted state, including fresh-process installed recovery.
Offline replay state is separate from durable account recovery.

Test future perturbations at the selector and economic consumer: changing only
information strictly after cutoff `t`, including a later row that changes an
object's digest, cannot change decisions, fills or balances through `t`. Full
provenance/run identities may change. Do not label a changed knowledge assertion
at or before `t` a future-only perturbation.

## Consumer obligations

Storage, dataset publication, order-book and replay consumers preserve original
capture text, source sequence, provenance identity, exact values and proxy reasons.
The current price diagnostic preserves the query's business clock and separate
exchange-event and availability clocks; its [contract](../../src/research/features/README.md#formula-and-clocks)
explains this distinction. Economic consumers must preserve these semantics end to end.

A selected input must satisfy `available_at <= decision_time` under its declared knowledge model;
derived features also include their processing/availability assumptions. Dataset
identity makes a result reproducible but cannot make an event-time-only join causal.

For live capture, retain actual local receipt/order and durable progress,
then replay those exact captured inputs through the shared downstream contracts.
Historical vendor capture, local live receipt and later archive ingestion have
different meanings. Do not backdate a late correction or recovery backfill, or
claim that a subsequently downloaded vendor archive reproduces the original
local information set. Preserve source-local order and explicitly define any
cross-source tie rule rather than inventing a total observed arrival order.
