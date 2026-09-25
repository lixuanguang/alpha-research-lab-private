# Economic and market-data design

**Status: destination design.** Capabilities remain planned unless explicitly
identified as current. Quant development owns the implementation boundaries;
the roadmap owns delivery and acceptance.

[Platform design and dependency direction](platform-design.md).

## Canonical economic and temporal model

The current [instrument identity](instrument-identity.md), [venue calendar](venue-calendar.md), and [financial units](financial-units.md)
contracts remain the foundation. A future core layer extends them; it does not replace them
with vendor symbols, floating-point money, or a generic model framework.

### Identity and lifecycle

`InstrumentId` remains stable across alias changes and provider renames for the same identified instrument. A distinct
relisting has its own ID linked to the economic root, as the current identity contract requires. Planned `ContractSpec` records
add effective-dated quantity units, price units, multipliers, tick and lot rules, currencies, settlement, and lifecycle
state. A derivative references an internal underlying ID. A continuous futures series is a derived research product and
never a listed contract.

Specification revisions also retain when their source assertion became known.
Queries resolve valid time and knowledge time together, and observations, orders
and dataset manifests bind the selected version. A tick/lot change must not
rewrite an earlier run; current endpoint metadata cannot establish historical
specifications. The implemented `VenueSpecification` / `ReferenceHistory` boundary
now resolves observed OKX/Bitfinex spot rules separately from authored research
assumptions. Public trade observations retain the applicable version or explicit
unknown; `SpotLimits.from_reference` consumes complete known rules for order-grid
checks. General product lifecycle and execution adapter integration remain planned.

Future lifecycle records represent listing, activation, trading halt, expiry, exercise, assignment, delivery, delisting,
redenomination, and corporate-action effects as explicit versioned events. They retain the source assertion and
effective interval. A correction appends a revision and identifies datasets, models, positions, and releases that may be
affected.

### Market events and time

Planned `MarketEvent` schemas cover trades, quotes, books, bars, funding, fixings, settlements, corporate actions,
curves, volatility points, and venue state. Every event carries at least:

| Field | Contract |
| --- | --- |
| `ts_event` | When the economic event occurred, at source precision |
| `ts_received` | When the platform first received the payload |
| `ts_ingested` | When the payload entered governed storage |
| `ts_knowledge` | Earliest time a validated version could be used |
| `valid_from`, `valid_to` | Business interval for reference state |
| `source_revision` | Source sequence, file, or revision identity |
| `schema_version` | Version of the canonical event shape |
| `correction_id` | Link to an append-only correction when applicable |
| `source_digest` | Identity of the raw payload or source partition |

For a decision at `decision_time`, every feature input, reference record and risk value consumed by that decision must
satisfy `ts_knowledge <= decision_time`. Forward labels become available later: training may use a label only after its
outcome is knowable at the fitting cutoff; retrospective evaluation keeps those outcomes separate from decision inputs.
Event time is not knowledge time, and valid time is not receipt time. A source that
cannot support the required availability semantics is usable only for an explicitly limited engineering or exploratory
result.

Point-in-time selection resolves the record valid at the requested business time from revisions known at the requested
knowledge cutoff. It returns the selected revision, source digest, transformation version, and quality state, so a later
correction can invalidate affected products without rewriting the original result.

## Data source, storage, and lineage design

Every source adapter is responsible for authentication, rate limits, pagination, source-specific identifiers, source
timestamps, and raw payload capture. It does not expose its SDK models to research or execution code.

The planned data flow is:

```text
source adapter
    -> immutable raw landing + receipt metadata + source digest
    -> normalization and validation
    -> canonical events/reference state
    -> correction-aware PIT partitions
    -> dataset manifest and quality report
    -> feature/label products and research consumers
```

Raw inputs are append-only and retain entitlement, license, encryption, and retention metadata. Canonical records retain
source pointers and deterministic transform versions. Curated partitions are immutable products identified by a manifest
of partition digests, specification, code, dependencies, and source revisions. Publications are atomic: readers see
either the old manifest or the new manifest, never a partially written partition.

Storage technology follows the declared launch workload. Provisioning, discovery,
durable data/artifact storage, versioned offline/online feature-store access,
concurrent job execution, retention and backup/restore are mandatory before QR
onboarding. Preserve the existing lakeFS, Feast and experiment-store integrations
and extend their owned interfaces. A bounded topology may use files and local
services, but must supply all required retrieval, materialization, concurrency
and recovery behavior. Quant development supplies infrastructure for its declared
volume and latency budgets without waiting for a QR to encounter a bottleneck;
changing a backend requires compatibility and migration evidence.

Dataset specifications declare universe eligibility, event fields, source priority, schedule, timezone, calendar,
interval, lookback, warm-up, availability cutoff, correction policy, adjustment/roll policy, missing/stale rules,
expected partitions, and quality thresholds. A new specification or policy produces a new dataset identity.

Quality states are explicit: informational records remain visible; degraded data may be used only with a visible
limitation and stated scope; hard failures prevent publication; and an incident identifies affected products,
experiments, candidates, and releases for replay.

Existing normalization, quality checks, atomic publication, bounded queries and
replay support offline inspection without a live-feed dependency. Current source
scope and limitations live in the [data contracts](../data/contracts.md).
Market-event access and feature serving are distinct contracts even when they
share storage.

Historical ingestion and live capture converge on compatible envelopes while
retaining source/receipt/availability differences. Each enabled book consumer
requires tested quality transitions, backpressure and synchronization under its
source contract. Replay exact locally captured inputs and receipt order; a later
vendor archive cannot establish what the local system knew. A decoded depth update
alone does not establish a valid book after a gap. The contracts below govern
source extensions; [scaling decisions](runtime-and-operations-design.md#storage-and-performance-decisions) govern
infrastructure selection.

### Collection scope and source contracts

Source configuration records each enabled combination in the existing source/job configuration:
venue, product, canonical instrument, source/access mode, stream representation,
timestamp units and meaning, sequence/reset guarantees, depth coverage, supported
intervals, backfill limits and permitted use. Record unsupported and unknown
coverage explicitly. Revalidate the adapter's protocol assumptions when admitting
a changed source schema; retain the last working fixture and source version.

| Representation | Required distinction before claiming coverage |
| --- | --- |
| Individual trades | Retain trade identity, exact units, maker/aggressor meaning and correction policy. Aggregated trades cannot silently stand in for every individual trade; specify whether separate trade channels belong to the selected universe. |
| L2 market by price | Snapshot plus ordered changes reconstruct quantities at prices within declared coverage. This does not establish individual-order queue positions or L3 market-by-order history. |
| Tickers | Best bid/offer, last trade and rolling statistics are distinct products. Record the chosen fields/window, update semantics, age and source; one cannot certify another's completeness. |
| Klines | Enumerate the selected venue-supported intervals, timezone/boundaries and whether provisional updates or only closed bars are retained. Preserve close/finality and revision availability. Trade-derived bars have separate lineage and are not relabeled exchange klines. “Every kline” means the declared intervals and retained coverage, not an unspecified promise. |

The initial OKX/Bitfinex data gate includes selected public trades alongside books,
with explicit per-feed coverage and availability evidence. Non-book inputs use
their own typed schemas and availability rules; a small reference dataset proves
this extension boundary without claiming a new production source. Bitfinex's
current R0 raw-book path and OKX L2 retain their distinct semantics; adding a
representation never silently relabels either as a complete matching-engine log.

For execution-sensitive inputs, prefer the direct feed for the actual venue and
product, with its native order adapter. An aggregator remains useful for research
and historical backfill. Any alternative execution input needs explicit freshness,
ordering and provenance acceptance; switching providers cannot silently preserve
the old source identity or measured latency. Endpoint, heartbeat, connection
lifetime and request limits are verified for the selected product during source negotiation,
not copied from another venue or an old example.

### L2 synchronization and recovery

Validate continuity against the source stream's documented contract, including
batched sequence ranges, resets and checksums where supplied. The local raw-record
position and a broker offset are not exchange sequence numbers. A stream without
consecutive IDs needs its documented integrity checks and an honest unknown-
coverage outcome; do not manufacture a universal per-message counter rule.

The reconstruction library consumes saved snapshots, updates and session controls;
the live pipeline owns network requests, rate limits, retries and persistence.
The same reconstruction library serves saved-input replay. Its supported book
carries instrument, session/recovery epoch, snapshot/raw identity, applied source
cursor, known depth coverage, effective availability and quality status.

1. On startup, a proven gap, checksum failure or unusable book, immediately block
   affected book-dependent consumers and enter `recovering`. Preserve raw input
   and the failure boundary. Keep independent healthy bindings usable.
2. Buffer updates within explicit memory/time bounds while requesting a fresh
   snapshot through the venue's supported recovery mechanism. For a REST-based
   adapter, coalesce recovery to one in-flight request per binding, respect the
   shared endpoint budget and retry/backoff policy, and discard responses from
   superseded session epochs. Overflow or exhausted recovery stays unavailable.
3. Reconcile snapshot and buffered updates under the venue-specific bridge rule;
   reject stale/incompatible snapshots and gaps in the retained suffix. Apply a
   complete source message atomically, including all bid/ask changes. Downstream
   decisions must not observe a half-applied message or snapshot.
4. Validate the reconstructed state and coverage, then resume at its actual
   availability time. A repaired book cannot restore observations or decisions
   inside the earlier missing interval. Persist enough snapshot/cursor/epoch
   identity for deterministic reconstruction after restart.

For Binance spot, the documented procedure buffers depth events before obtaining
a REST snapshot, removes updates covered by the snapshot, reconciles the first
remaining range and restarts if a subsequent `U` exceeds the local update ID plus
one. Updates set absolute quantities; zero quantity deletes a level. Snapshot
depth is limited, so untouched levels outside it remain unknown. Use the current
documented bridge rule and distinguish it from futures continuity fields.
[Official spot procedure](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md#how-to-manage-a-local-order-book-correctly)
(reviewed 2026-09-15; recheck during adapter implementation).

For a newly supported live book, combine a hand-reconstructed saved trace with
one permitted capture. Offline reconstruction can use verified saved inputs with
declared quality; synthetic traces prove the algorithm only. Exercise a gap during
snapshot fetch, stale-session response, duplicate/overlapping updates, deletion,
malformed level, interrupted message, rate-limited recovery and buffer overflow.
Resume must reproduce the same book and quality boundaries as uninterrupted replay.
Select analogous cases for another venue only where its protocol differs.

### Ingestion quality

Historical partition and continuous-capture checks share schema/unit and
source policies. Reject nonfinite or nonpositive trade prices and invalid trade
quantities under that representation's contract; zero L2 update quantity remains
a deletion. Preserve rejected raw records, reasons and binding-scoped counts.
An invalid required update invalidates dependent book state. Do not silently
drop an anomaly, forward-fill it or mark the stream healthy after reconnect.
Keep the existing frozen `msgspec.Struct` and explicit invariant requirements;
this design does not migrate market events to Pydantic.
