# Bounded crypto L3 capture and replay

Owner: repository founder. Status: bounded development capture, durability,
recovery, quality, supervision and replay are implemented. Coinbase authenticated
external acceptance remains access-blocked. This workflow records new observations;
it does not establish historical backfill, complete source coverage, a deployed
service or an execution model.

## Start here

Use the installed `alpha-collect` command below for deliberate acquisition.
For pinned dataset inspection, use the [selection interfaces](../../src/market_data/README.md#discover-and-reopen-research-selections).
The [research workbooks](../../examples/README.md) specify economic studies and
consume retained results. The former infrastructure/capture notebooks are
retired from active examples; their source remains in Git history.

[OKX public L2](okx-market-data.md) retains aggregate levels and historical source
clocks separately from these L3 order feeds. Coinbase remains available through
the installed collector and tests with the access requirements below; notebook
diagnostics do not read its credentials.
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
  flushed and fsynced before decoding or consumer use. Messages remain atomic and
  are never resorted by exchange timestamps.
- `cursor.json`: the request identity, committed byte offset, record count
  and incremental SHA-256 of that exact prefix. Each append returns only after
  journal fsync, synced `cursor.pending`, atomic replacement and directory fsync.
  New output-directory ancestors are synchronized before the writer starts.
- A SHA-256 named `RawStore` object plus `manifest.json`: exact published journal
  and descriptor. Publication verifies bytes, fsyncs files/directories and replaces
  the descriptor only after durable raw publication.
- `summary.json`: small derived counts, clocks, gaps, book/trace/input identities
  and terminal reason. The verified input is authoritative if this summary is lost.

The journal ceiling includes envelopes and reserves 4 KiB for controls. Publication
can temporarily use twice the journal ceiling plus small bounded metadata; it
retains the original journal for interrupted-input inspection. One finite recording
is one bounded segment; this adds no continuous rotation service. Neither attempts
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

The receiver and durable consumer use the existing bounded queue. Persistence and
downstream replay execute outside the receipt event loop, one record at a time.
The transport also bounds its frame queue. Memory is bounded by the configured
queue capacities, maximum message size, active record and bounded book state;
these ceilings are not measured latency or process-RSS guarantees. Queue overflow,
oversized frames, idle expiry, reconnect, malformed input and relevant sequence
breaks stop the epoch and retain scoped unknown-loss reasons. Queue contents that
cannot be persisted at a failed boundary are not called received durable data.
Persistence errors propagate, close the feed and leave an incomplete attempt;
no successful manifest is written. Disk/process failure can leave a partial final
line, or a complete uncommitted line, after its last cursor. Interrupted inspection
verifies the cursor's request, bounded prefix hash/count and message boundary
before yielding any records; it excludes the suffix and adds
`interrupted_persistence_unknown_tail`. A corrupted or truncated committed prefix
fails closed. After any persistence failure the writer refuses append/publication;
start a new UUID recording and retain the old one. No exact lost-message count is
invented for a process that died with messages in memory.

Completed legacy recordings remain verified through their unchanged manifests. Legacy interrupted recordings without `cursor.json` retain bounded newline-prefix
inspection and the unknown-loss marker, without a cursor acknowledgement claim. An empty recording that died before its first session and an end record without
verified publication both count as interrupted. Checkpoints acknowledge
saved input, not downstream consumer state. Shared book replay requires its own
consumer state beside the source cursor. No exactly-once or gap-free-history
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
executable fills, nor a simulator. Shared book publication/replay follows below.

The [shared book path](../../src/market_data/README.md#published-book-queries-and-shared-stepping)
reuses publication and chronological stepping with its own format and quality scope.

## Verified source contract

The maintained example selects the **Bitfinex spot `tBTCUSD`, R0/F0, depth 25** job for
bounded foreground verification. It reuses `CaptureConfig`, `CaptureRequest`,
`VenueTransport`, `BitfinexBook` and `collect`; no second transport or configuration
schema is added.

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

## Session recovery

The collector now drains already accepted queue entries after an invalid frame
instead of dropping the tail of a completed recording. It stops the affected
receiver and keeps the epoch's single REST request alive until its result is
persisted. Invalid state blocks that result and queued frames from changing the
book. Disk failure and storage exhaustion retain their explicit incomplete or
unknown-tail outcomes; volatile input is never described as durable.

One epoch requests at most one Coinbase snapshot, even after repeated subscription
acknowledgements. The next epoch waits for that request to complete, so recovery
requests cannot overlap. The configured `retries` gives at most `retries + 1`
connections and snapshots (maximum six); retry delays are 1, 2, 4, 8 and 16 seconds,
capped by the remaining receive interval. Existing fixed endpoints, connection and
HTTP timeouts remain. Rate-limit and protocol failures retain an invalid gap and
consume the same finite budget. These are per-invocation ceilings; there is no
shared-IP limiter within this recovery loop. Coinbase reserves one message slot per
epoch for the independent REST response, preserving `max_messages` across retries;
an unused reservation is not filled by additional stream messages.

A new connection still requires its native acknowledgement and snapshot bridge.
It never repairs the preceding unknown interval. No selected stream has a
historical backfill adapter. Snapshots retain their actual later response receipt;
no earlier knowledge timestamp is assigned. A prior-epoch or closed-epoch snapshot
is retained and counted as stale without changing current state. Canonical
knowledge/quality admission uses the book-publication contract below.

At the replay boundary, byte-identical adjacent sequenced Bitfinex/Coinbase frames
within an epoch count as duplicates and do not repeat economic mutations. Both
copies retain their bytes and original receipt instants. The one-frame cache is
bounded by the frame ceiling and resets with the epoch. A conflicting or older
repeat still invalidates the stream under its native sequence contract; OKX keeps
its existing sequence/reset semantics. Direct native decoders remain strict.
Derived summaries add `frames`, `duplicates`, `stale_snapshots` and
`retry_exhausted`; raw envelope and manifest serialization is unchanged. Old raw
input can produce a different derived trace when a formerly invalid exact repeat
is now explicitly classified as a duplicate.

These recovery guarantees do not establish Coinbase external eligibility or
complete source coverage.

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

## Continuous quality and bounded publication

`CaptureReplay.quality` is the same scoped gate used by the collector and saved
input admission. Each durable boundary exposes status, reason, scope, transition
time, last durable receipt, last economic progress and receipt/source watermarks.
Live capture binds strict zero lateness and the configured `idle_seconds` freshness
budget. Original clocks remain unchanged; Bitfinex's absent exchange time is not
invented. The standalone `ContinuousQuality` gate can exercise a positive bounded
lateness policy explicitly, but the live configuration does not enable that mode.

Coinbase snapshot bridging preserves the source timestamp of the last applied
buffered lifecycle message. Messages already covered by the snapshot do not
advance that clock, and a backwards source timestamp in the applied bridge
invalidates reconstruction. A later REST response receipt cannot freshen an old
buffered update. The snapshot's actual receipt remains its availability boundary.

A source or receipt regression beyond its watermark invalidates reconstruction.
Schema/sequence failure and gaps stay recovering until a fresh session validates
its native snapshot/bridge. Reconnect controls cannot resume use. Heartbeats and
duplicates do not update economic progress. Stale, recovering and unavailable
states refuse freshness-dependent use. `require_usable(now_ns=...,
allow_degraded=True)` permits only explicitly opted-in, fresh exploratory state;
the default refuses it. No current source has the complete evidence required to
emit `valid`, and no execution-sensitive book consumer is enabled. End-of-session
state is unavailable even when the last reconstructed book remains inspectable.

Optional installed capture flags `--snapshot-directory <existing-directory>` and
`--snapshot-records <1..10000>` publish a selected prefix after durable completion.
Both are required together. Publication uses the capture's existing byte budget,
shared `QualityReport` gate and atomic `SnapshotStore`. A publication refusal does
not remove the completed raw recording or its summary. Original raw configuration
and capture serialization remain compatible. Saved-only publication and explicit
book reopening are described in the [data guide](../../src/market_data/README.md#bounded-saved-books).

The native OKX decoder now commits both sides of a message together: a malformed
second side leaves the preceding state and source cursor intact. Native sequence
rules, visible depth and archive unknown-continuity restrictions remain unchanged.


## Independent health supervision

The optional `--health-config` capture flag selects a separate parent watchdog.
The parent owns one spawned collector and observes a fixed nine-integer shared
report; no telemetry files or unbounded message queue sit on the capture path.
The existing capture configuration and raw serialization are unchanged. A distinct
health policy is saved beside the capture configuration in a UUID supervision
directory; the child recording remains in its own UUID directory beneath it.

```sh
uv run --frozen --no-editable alpha-collect capture \
  --config configs/live/bitfinex-btc-usd.json \
  --health-config configs/live/health.json \
  --output data/bitfinex
```

This command starts a new bounded source capture. It is a usage example, not an
external-source or deployment test. The maintained health example uses
macOS's `/var/run/syslog`; select an existing local Unix datagram syslog receiver
on another supported POSIX host. No remote alert destination is contacted.
`HealthPolicy` refuses unknown fields, invalid thresholds and responses other
than `stop`. The queue threshold must be below the configured capture capacity.
Supervised capture deliberately refuses the optional book-publication flags;
the foreground capture path provides publication/replay parity separately.

The parent polls every 100 ms. Startup has its own finite allowance. The child
updates a process heartbeat every 100 ms; accepted frame receipt, successful
journal append and validated economic progress have separate clocks. Economic
freshness reuses the book source/receipt policy, projected to monotonic elapsed
nanoseconds when market progress changes. Source clocks in saved raw input remain
unchanged. Heartbeats and duplicate frames cannot refresh economic progress.
The queue metric retains peak occupancy; reconnects count epochs after the first;
the invalid counter counts retained gaps, including schema and continuity faults.
Limits are inclusive: the first value above the configured threshold stops the run.

Persistence failure takes precedence, followed by startup/heartbeat, persistence,
ingestion and market stalls, then queue/reconnect/invalid limits. If input stops,
receipt can expire before its later append; either progress reason can stop the run.
When both budgets have expired, persistence takes precedence.
Finalization no longer expects fresh market data, but still requires heartbeat
and a total deadline of startup + capture duration + progress allowance. Shared
lock acquisition is bounded to 50 ms, including after a lost writer.
The collector enters finalization before writing the capture-end record and runs
blocking publication and saved-input verification outside the event loop,
allowing the heartbeat to continue while that work completes. Storage and parity
failures still propagate; an active heartbeat does not certify successful publication.

On a failure the parent terminates the child, waits up to one second, then kills
and waits up to one further second if needed. It attempts the local syslog alert
only afterwards. The stdlib `SysLogHandler` adapter uses nonblocking Unix datagrams,
including its reconnect path. Missing/full alert sockets return failed delivery;
they cannot delay the local stop. Alerts contain only supervision UUID, venue,
symbol and a fixed reason. `health-summary.json` retains the policy and installed
implementation identities, last counters, exit status, stop result and delivery
status. The installed command exits nonzero on unhealthy completion.

A protective stop may leave accepted queue entries or an in-flight disk operation
uncommitted. Inspect the child's directory with `alpha-collect replay --capture
<child-directory> --interrupted`; the durable cursor verifies the retained prefix and
marks the unknown tail invalid. Do not treat a stopped capture as continuous or
restart by appending to it. Start a new explicitly configured recording after
addressing the cause. A failed summary write propagates after stop/alert; failed
storage cannot be relied on to record its own failure.

Alert delivery means socket acceptance, not human acknowledgement. The watchdog
still needs an external service manager for deployed availability; host loss,
remote alert routing and service activation are unproven. Artifact verification
remains required before deployment. Supervision alone does not establish
book-dependent execution or canonical parity.


## Published capture and replay parity

The foreground installed capture path accepts the existing paired
`--snapshot-directory <provisioned-directory> --snapshot-records 32` options.
After durable completion it compares the captured canonical prefix with exact
saved-frame normalization and publishes the shared immutable book snapshot.
`summary.json` reports `canonical_parity` and `snapshot_identity` on success;
`book-prefix.json` retains the original live normalization for downstream comparison.
A divergent message leaves `first-divergence.json` beside the original raw object,
with the first raw position and expected/observed states. No vendor download is
used to replace the recording. Preserve these files together when diagnosing failure.

The [book replay API](../../src/market_data/README.md#published-book-queries-and-shared-stepping)
queries atomic messages, schedules only known receipts, and restores the shared
completed cursor together with accepted snapshot and recovery epoch in consumer
state. The [recovery probe](../../tests/integration/consumers/capture/recovery_probe.py)
injects disconnects and duplicate saved frames, with explicitly new local receipt
clocks, and retains a first-divergence failure. Its focused test callers remain
the canonical executable proof; the engineer notebook covers synthetic session recovery.

The canonical proof covers the selected prefix (32 positions in acceptance), while
native summary parity covers the finite recording. Continuous service, complete
coverage, source clock accuracy and execution remain outside this acceptance.
Coinbase live acceptance still requires verified Exchange access. The existing
supervised CLI path remains raw-capture-only and refuses snapshot flags; independent
supervision follows its separate contract. Artifact verification remains required for any
deployment. No new venue connection is needed to replay an existing saved recording.
