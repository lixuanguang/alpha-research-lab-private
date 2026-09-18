# Bounded crypto L3 capture and replay

Owner: repository founder. Status: implemented development collector slice under
MRs 22–27; Coinbase authenticated external acceptance remains access-blocked.
The [implementation evidence](../roadmap/crypto-l3-collectors.md) records actual
commands and retained inputs. This workflow records new observations. It is not
historical backfill, dataset acceptance, a deployed service or an execution model.

## Start here

Use the installed `alpha-collect` command or the same package APIs in
[market-data-capture.ipynb](../../examples/market-data-capture.ipynb).

The same notebook now includes [OKX public L2](okx-market-data.md), explicitly
distinguishing aggregate levels and historical source clocks from these L3
order feeds. It uses the existing live and acquisition pipelines.
As of the 2026-09-16 notebook migration, its default route uses public Bitfinex
and OKX only. Coinbase remains available through the installed collector and
tests, with the access requirements below; the notebook no longer reads its
credentials. Inspect saved OKX/Bitfinex inputs without network access in
[research-foundations.ipynb](../../examples/research-foundations.ipynb).
The first configured native spot identities are separate listings:

| Venue | Native symbol | Feed | Canonical listing ID | Depth |
| --- | --- | --- | --- | --- |
| Bitfinex | `tBTCUSD` | public `book`, `prec=R0`, `freq=F0` | `c87d983f-e7ec-4e64-8d54-9f2be67a64b8` | requested `len=25`; live sample contained 25 orders per side |
| Coinbase Exchange | `BTC-USD` | authenticated `level3` and heartbeat | `218142de-d549-43bb-85ba-a174fd4f798f` | complete REST level=3 snapshot; fail if configured order/byte budget is exceeded |

The listing UUIDs are authored identities, not exchange-issued UUIDs or a
historical eligibility catalog. Both configurations explicitly bind BTC and USD.
Other native spot instruments require a new configuration and a successful
`probe`; this slice externally verifies only the examples above.

From the repository root:

```sh
uv run --frozen --no-editable alpha-collect probe --config configs/live/bitfinex-btc-usd.json
uv run --frozen --no-editable alpha-collect probe --config configs/live/coinbase-btc-usd.json
uv run --frozen --no-editable alpha-collect capture --config configs/live/bitfinex-btc-usd.json --output data/bitfinex
uv run --frozen --no-editable alpha-collect capture --config configs/live/coinbase-btc-usd.json --output data/coinbase --secrets secrets/coinbase.secrets
```

Each maintained config selects a 20-second recording, at most 10,000 received
messages, a 32 MB journal, 8 MB per source message, a queue of 1,024 messages,
100,000 visible orders, 15 seconds without a received message and two retries.
These are resource ceilings, not promised exchange throughput or depth. Bounded
connection/shutdown and pending filesystem work can extend command elapsed time
past the receive interval. Review limits in the [Bitfinex configuration](../../configs/live/bitfinex-btc-usd.json)
and [Coinbase configuration](../../configs/live/coinbase-btc-usd.json)
before changing them. A reconnect starts a fresh epoch and snapshot; it does not
repair the preceding interval. Stop the foreground invocation with Ctrl-C.

## Coinbase credentials and access

Use a **Coinbase Exchange** API key with View permission and eligible Exchange
account access. The CDP `name`/`privateKey` JSON is deliberately ignored. Exchange
uses its own key, base64 HMAC secret and passphrase; neither the CDP private key
nor an Advanced Trade subscription supplies Exchange Level 3 access.

An empty, owner-only local `secrets/coinbase.secrets` was created for this work.
For a new checkout, copy the tracked empty example without overwriting a local key:

```sh
mkdir -p secrets
cp -n configs/live/coinbase.secrets.example secrets/coinbase.secrets
chmod 600 secrets/coinbase.secrets
```

Fill these fields locally, without quotes:

```text
COINBASE_API_KEY=
COINBASE_API_SECRET=
COINBASE_API_PASSPHRASE=
```

The collector reads only the explicitly supplied `--secrets` path. It performs no
shell expansion, does not accept credential values on the command line, disables
WebSocket frame logging and never persists the signed outbound subscription.
Missing or blank fields fail before opening a connection. Invalid-authentication
responses are preserved as received input and fail the subscription. No order,
account transfer or trading endpoint is called.

Both `level3` and `full` require Exchange authentication. This implementation
selects compact `level3`; it reads and saves the supplied schema. `full` is a
possible future explicitly configured alternative when compact schema compatibility
requires it, but is not an implemented fallback. There is no automatic L2 choice.
The current endpoint is the global Exchange feed; MiCA-specific DMA endpoints
and other account routing require separate verification before adding support.

## Input, persistence and failure meaning

The library owns validation in `data/live/`, venue lifecycle in
`data/venues/{bitfinex,coinbase}/`, and workflow composition in `pipelines/live.py`.
Existing `DomainCodec`, `InstrumentId`, `RawObject` and `RawStore` are retained.
The raw-store request boundary additionally accepts a frozen `CaptureRequest`.
Historical `SourceRequest`, acquisition manifests and Binance behavior are preserved.

A recording gets an exclusive UUID directory under the supplied venue output:

- `request.json`: exact non-secret selection, session identity and installed
  source fingerprint. Recorded config plus acknowledgement/schema frames bind
  subscription meaning and native identity.
- `journal.jsonl`: append-only envelopes with exact message bytes (base64 in JSON),
  receipt nanoseconds, epoch, record kind and local control reason. Each line is
  flushed and fsynced before decoding or consumer use. Journal order is the replay
  cursor; messages remain atomic and are never resorted by exchange timestamps.
- A SHA-256 named `RawStore` object plus `manifest.json`: exact published journal
  and descriptor. Publication verifies bytes, fsyncs files/directories and replaces
  the descriptor only after durable raw publication.
- `summary.json`: small derived counts, clocks, gaps, book/trace/input identities
  and terminal reason. The verified input is authoritative if this summary is lost.

The journal ceiling includes envelopes and reserves 4 KiB for controls. Publication
can temporarily use twice the journal ceiling plus small bounded metadata; it
retains the original journal for interrupted-input inspection. Neither attempts
nor previous same-day directories are overwritten. Data directories and filled
secrets are Git-ignored; maintained config, notebook and code are tracked.

Receipt is UTC Unix nanoseconds sampled after a complete message reaches the
application, not network-card timing. Source sequence/time stay in exact raw
bytes; decoded source time is optional original UTC text, including submicrosecond
precision. Bitfinex's selected flags do not supply an exchange event timestamp.
No timestamp or source sequence is invented to satisfy the existing historical
`EventProvenance` model, whose mandatory fields cannot represent that absence.
`RawObject` retains existing receipt/ingestion provenance; the capture envelope
owns the additional per-message nullable source facts. This is not canonical
historical event publication.

JSON decimal tokens parse directly to `Decimal`; binary floats are rejected.
The decoder bounds exact values to 40 significant digits and magnitude up to
10^30, with exact lifecycle subtraction under a 100-digit context. Prices,
quantities, IDs and native symbols remain independent of display formatting.

The independent receiver and durable consumer use bounded buffers. Queue overflow,
oversized frames, idle expiry, reconnect, malformed input and relevant sequence
breaks stop the epoch and retain scoped unknown-loss reasons. Queue contents that
cannot be persisted at a failed boundary are not called received durable data.
Persistence errors propagate, close the feed and leave an incomplete attempt;
no successful manifest is written. Disk/process failure can leave a partial final
line even if its preceding writes were durable. No exactly-once or gap-free-history
claim follows from a completed capture. Clean duration/message limits are intended
recording boundaries; source continuity outside those boundaries is unknown.

```sh
# Use the actual UUID directory printed by capture.
uv run --frozen --no-editable alpha-collect replay --capture data/bitfinex/RECORDING_UUID
# Explicitly inspect an attempt that has no completed manifest after interruption.
uv run --frozen --no-editable alpha-collect replay --capture data/bitfinex/RECORDING_UUID --interrupted
```

Completed replay verifies descriptor binding, byte count and SHA-256 before use.
Interrupted inspection reads only complete lines and always reports an unknown
tail, even when the process died at a line boundary. It never edits or repairs the
original input. The capture command returns exit 2 for any retained gap or an
unsynchronized final state, even if a later epoch recovered. Exit 0 therefore
means the bounded sample passed the implemented checks, not proven venue completeness.
Replay can inspect known gaps successfully and exposes them in its result.

## Reconstruction and its limits

**Bitfinex:** configure `SEQ_ALL=65536`, verify its acknowledgement, then require
the matching native R0 subscription. A heartbeat can precede subscription ack;
it establishes only liveness and must match the later channel ID. Admit the first
WebSocket snapshot, then apply each `[order_id, price, signed_amount]` update.
Positive amount is bid, negative amount ask, and price zero removes the visible
order. Every sequenced array, including heartbeats, must advance by one. A new
epoch discards the old state. Sequence guarantees are limited to Bitfinex's
server sequence feature, documented as beta; no matching-engine completeness
claim is inferred. A deletion can describe leaving the bounded feed window,
not necessarily an exchange cancellation. Native IDs do not establish queue rank.

**Coinbase:** first persist the supplied compact schema and subscription ack.
Continue WebSocket receipt while fetching the complete REST L3 snapshot. Buffer
compact updates within the configured bound, install snapshot sequence S, discard
buffered messages at or below S and require S+1 before admitting synchronized
state. A gap during the bridge fails the epoch. `noop` advances sequence without
adding an order; `open` adds a resting order; `match` reduces the maker's exact
size; `done` removes; `change` changes a resting order's size/price. Changes and
completions for non-resting orders do not create entries. An absent maker, negative
size, overfill or ambiguous duplicate invalidates the epoch. Product heartbeat
sequence can reveal a missing lifecycle message but does not itself advance the
book. Coinbase documents limits to detecting loss in authenticated-only messages;
product sequence checks do not prove absence of every possible loss.

After malformed data, partial state is marked invalid and only a fresh epoch
can recover it. The supported consumer is `CaptureReplay`, which enforces this
boundary. Its rolling trace binds original frames, output classifications and
message-boundary order-state fingerprints. Live collection replays the saved
object and compares the entire final summary and trace. This preserves visible
resting order state; it establishes neither queue priority, hidden liquidity,
executable fills, nor a simulator. General MR 20 event-time stepping and canonical
quality/publication remain separate roadmap prerequisites.

The planned [shared dataset and replay integration](../roadmap/README.md#collector-integration-with-shared-datasets-and-replay)
is an explicit MR 25/27 checkpoint, reusing MR 09–15 normalization/publication
and MR 20 replay through the existing pipelines.

## MR 22 verified source contract

MR 22 selects the existing **Bitfinex spot `tBTCUSD`, R0/F0, depth 25** job for
bounded foreground verification. It reuses `CaptureConfig`, `CaptureRequest`,
`VenueTransport`, `BitfinexBook` and `collect`; no second transport or configuration
schema is added. The [acceptance record](../roadmap/mr-22-implementation.md) binds
the actual installed candidate, acknowledgements and exact saved session.

| Boundary | Supported meaning |
| --- | --- |
| Source and session | Fixed public TLS endpoint; request hash binds config, recording UUID and installed implementation. Each connection has an epoch; acknowledged `chanId` is connection-local. |
| Format | JSON, native R0 order tuples and `SEQ_ALL=65536`; exact decimal decoding. Advertised version must be integer 2; absent version on later info messages remains allowed. Unsupported framing fails closed. |
| Time and availability | Original application-receipt Unix nanoseconds remain in every envelope. These flags provide no exchange timestamp; wall-clock resolution/accuracy is not inferred from the integer unit. Live receipt establishes this local observation only. Vendor archives retain their separate acquisition semantics. |
| Admission | Matching configuration/subscription acknowledgement precedes market admission; a racing heartbeat establishes liveness only. Snapshot, exact-unit, channel and sequence checks already exist. No new stream is admitted. |
| Permissions | Public anonymous market-data access requires no account/key. This selected workflow is bounded private development with local retention; no redistribution, commercial data licence or trading authority is claimed. See the [API requirements](https://docs.bitfinex.com/docs/requirements-and-limitations) and [API terms](https://www.bitfinex.com/legal/general/api-terms/). |

The official [limits page](https://docs.bitfinex.com/docs/requirements-and-limitations),
checked 2026-09-18 Singapore, states 20 public connections/minute and 25 concurrent
channels. The [general page](https://docs.bitfinex.com/docs/ws-general) instead says
30 channels; use the conservative 25. This job subscribes to one channel, sends
one configuration plus one subscription per epoch, and allows at most three
connections per invocation. Acceptance made one connection, without stressing a
limit. Repeated invocations or other clients sharing the IP are not globally
rate-limited by this development collector; coordinate that budget externally.

The documented heartbeat interval is 15 seconds. The existing job's 15-second
idle ceiling can expire around network jitter; such an expiry reports unknown loss,
not success. WebSocket protocol pings run at 15 seconds with a 10-second pong timeout.
The receive lifetime is 20 seconds for the maintained job; open is bounded by
10 seconds or the remaining budget, subscription sends now share the remaining
capture deadline, and close has a two-second timeout. Persistence and close may
extend command wall time. No guaranteed vendor maximum connection lifetime is
assumed. Restart/maintenance notices invalidate the session under existing behavior.

`SEQ_ALL` is documented as beta server-order evidence, not matching-engine
completeness. This bounded job is not a continuous service or historical backfill.
MR 23 and later retain durability/recovery/supervision acceptance, MR 25/27 own
canonical book publication/shared replay, and R1 still precedes deployment.

## Official protocol references

Checked 2026-09-15 UTC. Runtime `probe` also verified both configured listings.

- [Bitfinex raw books](https://docs.bitfinex.com/reference/ws-public-raw-books):
  R0 tuple, snapshot, deletion and supported depth parameters.
- [Bitfinex WebSocket general](https://docs.bitfinex.com/docs/ws-general):
  configuration flags, heartbeat and maintenance/reconnect messages.
- [Bitfinex connection requirements](https://docs.bitfinex.com/docs/requirements-and-limitations):
  public connection rate limits; the example uses one connection and bounded backoff.
- [Coinbase Exchange channels](https://docs.cdp.coinbase.com/exchange/websocket-feed/channels):
  compact schema and snapshot/lifecycle synchronization.
- [Coinbase Exchange authentication](https://docs.cdp.coinbase.com/exchange/websocket-feed/authentication):
  HMAC verification challenge and authenticated-message sequence limitations.
- [Coinbase L3 REST book](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-book):
  full, nonaggregated snapshot with sequence.
- [Coinbase WebSocket rate limits](https://docs.cdp.coinbase.com/exchange/websocket-feed/rate-limits):
  subscription and inbound message limits; this collector sends one subscription per epoch.

The Binance historical acquisition command and
[P1 experiment specification](../research/p1-baseline.md) retain their original
scope. Earlier notebook attempts retain their historical meaning; current
researcher examples use OKX and Bitfinex as described above.
