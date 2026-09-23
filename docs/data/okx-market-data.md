# OKX public L2 capture and historical replay

OKX adds **L2** data: aggregate price levels and order counts, without individual
order IDs or queue priority. Bitfinex R0 and Coinbase Exchange remain the L3
sources. The acquisition/capture examples below select native **BTC-USDT spot**;
the [saved L2 backtest](../research/l2-book-backtest.md) selects **ETH-USDT spot**.
Each configuration has its own canonical listing ID. USDT is not USD.

Use the [installed commands](#installed-commands) for acquisition and the
[selection interfaces](../../src/market_data/README.md#discover-and-reopen-research-selections) for pinned dataset inspection.
Binance history and the frozen P1 baseline remain separate. Shared
[publication and book replay](../../src/market_data/README.md#published-book-queries-and-shared-stepping)
preserve OKX's distinct L2 and historical coverage limits.

## Verified source contracts

Checked 2026-09-16 against official protocols and actual public responses:

| Source | Implemented selection |
| --- | --- |
| Live JSON `books` | Public `wss://ws.okx.com:8443/ws/v5/public`; 400 levels per side, initial snapshot and nominal 100 ms updates; no authentication. |
| Historical module `4` | Public `GET /api/v5/public/market-data-history`; SPOT, daily aggregation, one native instrument and one UTC day. The returned CDN URL selects a complete `.tar.gz` archive. |

The [historical portal](https://www.okx.com/en-sg/historical-data) advertises L2
history from March 2023. The
[API contract](https://www.okx.com/docs-v5/en/#public-data-rest-api-get-historical-market-data)
describes variable availability and typical T+3 publication for books. Daily
order-book query dates are inclusive UTC dates. Module 6's 50-level history is
being deprecated; this implementation explicitly selects module 4. The maintained
BTC acquisition example fixes 8 September 2026 rather than a moving latest date;
the separate ETH backtest configuration selects 20 September 2026.

The [live channel contract](https://www.okx.com/docs-v5/en/#order-book-trading-market-data-ws-order-book-channel)
distinguishes public `books` from the authenticated VIP `books-l2-tbt` and
`books50-l2-tbt` channels; those channels are not implemented here. `books`
excludes ELP/RPI liquidity. The
[checksum deprecation notice](https://tr.okx.com/help/okx-order-book-channels-checksum-field-deprecation)
directs JSON consumers to `seqId`/`prevSeqId`. Checksum bytes remain in raw input,
including any older nonzero values; they are not the current continuity test.

## Installed commands

From the repository root:

```sh
uv run --frozen --no-editable alpha-collect probe --config configs/live/okx-btc-usdt.json
uv run --frozen --no-editable alpha-collect capture --config configs/live/okx-btc-usdt.json --output data/okx/live
uv run --frozen --no-editable alpha-collect replay --capture data/okx/live/<recording-id>

uv run --frozen --no-editable alpha-acquire archive index --config configs/history/okx-btc-usdt.json
uv run --frozen --no-editable alpha-acquire archive fetch --config configs/history/okx-btc-usdt.json --output data/okx/history
uv run --frozen --no-editable alpha-acquire archive replay --archive data/okx/history/<download-id>
```

No OKX secret file is needed. Denied public access fails visibly without a region,
credential or depth fallback. Each command runs in the foreground. `fetch`
creates a fresh directory; `replay` uses completed saved input without network
access. Change the historical configuration explicitly to select another date
or replay record budget. Current product discovery checks SPOT/live status and
native currencies; it does not certify historical listing coverage.

## Live reconstruction and persistence

The adapter shares the bounded queue, journal, raw store, epochs and offline
parity check. Acknowledgements, native frames and text `pong` messages retain
exact bytes and UTC receipt nanoseconds. Quiet sockets receive text `ping`.
Malformed input, disconnect, overload, idle failure or wrong predecessor IDs
invalidate the interval. A later snapshot recovers visible state in a fresh
epoch while earlier gaps remain visible. Exit 2 reports gaps or missing
synchronization. Disk failure propagates; an incomplete journal remains
inspectable with `alpha-collect replay --interrupted`.

Exact Decimal prices and absolute sizes replace prior levels; zero size deletes
a level. Reconstruction retains the best 400 prices per side. `prevSeqId` must
match the preceding `seqId`: numeric jumps are normal, equal IDs require empty
levels, and a lower linked sequence is a documented maintenance reset. Source
`ts` remains original Unix-millisecond text, or unknown when absent; it is never
replaced with receipt time.

For saved-request compatibility, the shared version-1 capture config retains
its `max_orders` field. For OKX it must be 800 and bounds aggregate level
entries. OKX summaries expose `levels`, `max_levels`, `representation=L2` and
`orders=null`. No level gets a fake order ID. Earlier L3 request identities
retain their original serialized shape.

## Historical storage and explicit limits

Acquisition saves the original index, exact URL, discovery receipt time, native
identity, day, limits and installed implementation hash. `RawObject` and
`RawStore` publish the original archive. A local SHA-256 identifies the retained
bytes; it is not a publisher signature. Gzip CRC, expanded size and the single
expected regular tar member are checked before a durable completion manifest.
Archive paths are never extracted. Redirects, recoded responses and oversized
or incomplete files fail. Finite retries restart partial network downloads.
Disk failures propagate without a completion manifest.

The example caps compressed input at 160,000,000 bytes and expanded tar content
at 1,000,000,000 bytes. Expansion is streamed. Staging is retained, so peak disk
use is twice the compressed cap plus metadata. The 180-second acquisition budget
covers download retries and archive validation; offline replay has a separate
180-second budget. Socket inactivity is bounded at 30 seconds. Publication and
fsync latency remain filesystem-controlled.

The observed archive has newline-delimited snapshots/updates with three-field
levels (`price`, `size`, `order_count`). It supplies source times but **no
sequence IDs or original per-record receipt timestamps**. Replay checks schema,
instrument, source day and ordering; unknown timestamps remain unknown.
Repeated archive snapshots replace state. `gaps=null` and
`continuity=unproven_no_source_sequences` express a limitation, not zero gaps.
Historical sampling is not assumed equivalent to this live channel, and an
archive does not automatically repair live gaps.

The full day is retained and its integrity verified. The example reconstructs
only its first **10,000 records**, reporting `record_limit` and
`entire_archive_replayed=false`. Its fixed request budget makes offline state
and message-boundary trace comparison deterministic. Time exhaustion raises
an error rather than returning a timing-dependent successful prefix.
Full-day semantic validation, normalized dataset publication, inferred fills,
queue priority and simulation are outside this slice.

Generated captures, archives and manifests live under ignored `data/okx/`.
Code, configs and explanatory notebooks remain tracked.
