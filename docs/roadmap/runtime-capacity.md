# MR15 runtime capacity profile

Owner: quant development. Status: **provisional, predeclared workload and
acceptance targets; no MR15 runtime capacity accepted**. Prepared 2026-09-27
after the bounded [MR14 service record](multi-instance-paper.md). The
[roadmap](README.md#runtime-operations-and-handoff) owns MR15 delivery status;
the [runtime design](../architecture/runtime-and-operations-design.md#scaling-triggers-and-technology-choices)
owns the scaling decision. The separate MR15 research slice owns multi-day
historical data, concurrent studies and offline feature capacity. This page
declares the subsequent integrated paper/shadow runtime workload before it is
implemented or measured.

These are engineering capacity targets for public-input paper operation, not
observations, trading limits, exchange fill claims or live-capital authority.
Revisions to a target require a dated rationale before the affected trial, with
the earlier target and failure retained. An installed artifact, a short native
public observation and a replayed load are different evidence classes.

## Launch workload and host

The provisional launch host is one Apple M1 Max, 10 CPU cores, 64 GiB RAM,
macOS 27 arm64, pinned CPython and a local SSD with at least 512 GiB free at
trial start. Record the exact OS, interpreter, disk/filesystem, available space,
power state, competing work, cold/warm cache state, artifact digests and input
identities for every result. No distributed service, broker or columnar database
is mandated by this profile; choose a replacement only after an owned measured
bottleneck and parity/rollback analysis.

The 24-hour integrated workload has four independently identified native spot
book sources: OKX BTC/USDT and ETH/USDT at native `books` depth 400, and Bitfinex
BTC/USD and ETH/USD at native `R0` depth 25. Four separately signed account owners
provide shared and isolated accounts for each venue. Eight active strategy
instances give each account two selected reference consumers. The workload uses
the existing [source and instance contract](../../src/configuration/paper_services.py),
[capture contract](../../src/configuration/capture.py), and
[signed activation boundary](paper-activation.md). The current
implementation ceiling of four accounts, eight sources and sixteen instances
permits these counts as configuration, but does not establish their simultaneous
capacity. USD and USDT remain separate currencies and journals. A consolidated
BBO query combines only explicitly equivalent instrument/quote-currency
identities; it must expose partial coverage rather than infer USD/USDT FX.

| Provisional launch measure | Numeric target and definition |
| --- | --- |
| Native receipt | At least 7,000,000 messages across all four sources in 24 hours, with no source below 20% of the total. The deterministic capacity input supplies 25 messages/second/source outside bursts and 100 messages/second/source for 10 seconds every five minutes. This is 2,376,000/source and 9,504,000 aggregate messages/day, giving margin above the minimum. Count socket messages, including native control records; separately count valid market books, invalids, duplicates, gaps and selected economic books. |
| Bytes and bursts | Complete encoded durable records average at most 4 KiB in the authored load, with measured p99 frame size at most 32 KiB and a hard single-frame ceiling of 8 MB. The 9,504,000-record schedule is at most about 36.3 GiB/day at that mean. Retain the actual size distribution; a smaller fixture cannot qualify a larger observed source. The 4x, 10-second burst must preserve order without unknown loss. |
| Capture segments and queue | Provisional 30-minute segments per source: `duration_seconds=1800`, `max_messages=75000`, `max_bytes=268435456` (256 MiB), `max_frame_bytes=8000000`, `queue_capacity=2048`. The authored schedule yields 49,500 records/source/segment, about 193.4 MiB at 4 KiB mean. Peak capture publication disk is bounded by about 2 GiB for four simultaneous segments under the current journal's at-most-2x rule. Queue oldest age is at most two seconds, peak occupancy at most 1,024 records/source, and no overload, frame, byte, message or duration limit ends a required interval early. |
| Book and decision work | Validate and reconstruct every admitted native message at the configured depths. Preserve exact L3 quantities/counts, per-venue BBO, provenance, revisions, clock quality and as-of eligibility. The existing three-second selected-book paper cadence is part of the signed input identity; intermediate books update monitoring without modeled fills or policy checkpoints. Target at most 40 admitted physical paper orders/account/day, within a separately authorized 80-order grant and its 100-unit-per-instrument buy cap; market-message volume does not imply order volume. Count child intents separately. |
| Features and reads | Materialize two versioned reference feature values per instrument at a declared one-second cadence: eight value updates/second across four books. Preserve source, receipt, availability, revision and TTL semantics. Serve eight concurrent instance lookups with a provisional five-second TTL; a stale or missing feature remains an explicit decision outcome. Require exact offline/online parity at matched cutoffs. The existing fixed/liquidity reference policies alone do not prove this integrated feature path. |
| Retention and disk | Retain 72 hours of replayable native records, all economically relevant canonical revisions/control events and source identities, and seven days of telemetry. At the authored encoded mean, 72 hours of native records is about 108.8 GiB. Provisional occupied-space ceilings are 160 GiB raw capture, 120 GiB canonical data, 32 GiB features/telemetry and 8 GiB active scratch, total 320 GiB; alert before any hard cap and fail visibly before evidence is discarded. Configure the [telemetry store](../../src/telemetry/store.py) for at most eight million retained events, below its ten-million hard ceiling, with explicit age-based retention. |
| Replay and resource use | Replay the exact 24-hour corpus at at least 4x recorded time (at least 440 messages/second aggregate on average for the 110/second burst-inclusive schedule), finishing within six hours with identical source/selection, feature, decision, order, fill, fee, cash, position and checkpoint identities. During the 24-hour integrated trial, total resident set size stays at or below 24 GiB, average CPU demand at or below seven of ten cores and p95 demand at or below nine cores; report disk bytes written and fsync cost separately. |

The one-day public-feed observation records actual native rate and quality for
both venues, but a venue may not produce the authored load. Use retained,
venue-conformant native-message replay or an explicitly identified local feed
fixture for the 9,504,000-message capacity input. It must include snapshot,
incremental, heartbeat/control, reconnect and adverse-size periods consistent
with each venue's supported contract. Public routing proves live input
compatibility only at its observed rate; replayed load proves only the local
processing envelope. The current [capture journal](../../src/market_data/storage/journal.py)
fsyncs each append and can use at most twice the configured bytes during
publication. Its [queue](../../src/market_data/collection/receipt.py) exposes
age/bytes and stops visibly on count overload. A 24-hour feed needs exact,
gap-aware segment rollover; restarting a finite capture and silently omitting
arrivals is not continuity.

## Provisional latency and query budgets

Measure monotonic receipt-to-durable and durable-to-derived intervals at each
source; preserve event, receipt and availability clocks rather than subtracting
unqualified exchange clocks. Record p50/p95/p99, maximum, sample count and warm
versus cold cache. Each row is a target, not an existing benchmark.

Use empirical nearest-rank percentiles only with at least 1,000 observations
per reported boundary/cache class. Retain individual durations and the actual
observation interval. During steady qualification, eight feature readers each
issue four lookups/second; four depth readers and four dashboard readers each
issue five queries/second. A 60-second stage-1 interval therefore supplies 1,920
feature requests and 1,200 requests for each query class. Separate process/service
startup from steady work. Fewer than 1,000 cold starts or recovery drills supply
totals/ranges, not p99 evidence; a warm percentile cannot qualify the cold target.
Record process-tree CPU/RSS and occupied disk at one-second intervals, plus
actual read/write counters where supported. OS cache state is uncontrolled
unless a separately documented cold experiment establishes otherwise.

| Boundary | p50 / p95 / p99 target | Workload and correctness condition |
| --- | --- | --- |
| Socket receipt to fsynced capture cursor | 50 / 250 / 1,000 ms | All four sources at the authored base and burst schedule; zero unknown loss. |
| Durable book to reconstructed per-venue BBO and eligible consolidated view | 20 / 100 / 500 ms | Native depth and all revisions; no stale, different-currency or later-available quote enters an earlier cutoff. |
| Selected economic book to committed policy/account checkpoint | 250 / 750 / 2,000 ms | Three-second selection cadence, eight active instances, account serialization and exact economic attribution. |
| Online feature retrieval | 20 / 75 / 200 ms | Eight concurrent instance reads of two values, with the stated cutoff and five-second TTL. Durable book to available materialization is at most two seconds at p99. |
| As-of depth/BBO query | 50 / 200 / 500 ms warm; 2 seconds cold at p99 | Four concurrent readers, one instrument and one cutoff, up to 25 Bitfinex or 100 OKX displayed levels; scan/returned bytes and partial coverage reported. The architecture's sub-500 ms historical-depth suggestion remains a candidate until its exact query and percentile are measured. |
| Dashboard query/render | 100 / 400 / 1,000 ms warm; 3 seconds cold at p99 | Four concurrent readers, one-hour window and at most 10,000 returned events/query using the bounded [monitoring query](../../src/telemetry/events.py); reports preserve exact currency, scope, revision and late-arrival semantics. |

Latency failure does not relax source freshness, feature TTL, quote-age or risk
checks. Measure invalids, durable lag, queue growth, RSS and disk alongside
latency; a fast result after dropping revisions fails the gate. Preserve the
[MR12 monitoring contract](../../src/telemetry/README.md), including visible
retention floors and diagnostic-only telemetry failure.

## Lifecycle, authority and acceptance stages

**Stage 1 — bounded characterization.** First run a separately signed and
authorized local fixture trial with four sources, four owners and eight
instances, but no new 24-hour claim. The provisional per-invocation shape is a
120-second account service, 100-second capture and 75-second supervisor with
at least 60 seconds of measured steady load after startup. Start the
supervisor within 20 seconds of the first account service to leave at least
25 seconds for orderly stop. Provisional per-source capture caps for this
stage are 5,000 messages, 32 MiB, an 8 MB single frame and a 2,048-record
queue; the authored 100-second input is about 3,250 messages and 12.7 MiB
per source at 4 KiB mean. A cap must never be mistaken for a healthy completed
interval. Exercise OKX and Bitfinex together, then each
venue's public-input route separately at its observed rate. Include quiet,
burst, oversize, queue/backpressure and fault cases without changing account
economics by replay accident. Retain exact input/configuration/release/grant
identities, raw and canonical cursors, selected-book flags, checkpoint and
account facts, sampled resource/latency distributions, query results, alerts,
stop reasons and cleanup. A stage-1 pass characterizes the finite envelope only.

**Stage 2 — sustained gate.** A 24-hour uninterrupted source-processing claim
requires an implemented and signed capture segment rollover. The existing
supervisor and account services each end by 120 seconds, under a 180-second
launcher ceiling; repeating them as if they were one continuous service would
introduce gaps and new owner claims. Before the 24-hour integrated trial,
implement and qualify either a longer explicitly bounded local service life or
a safe handoff that proves uninterrupted capture, one current economic owner,
no duplicate producer and exact state continuity. No indefinite daemon or
remote/distributed operation is inferred. The current one-hour MR14 grants
cannot authorize 24 hours. A provisional candidate for this paper-only trial
is an explicitly issued 26-hour finite grant/account with the same 80-order,
100-unit-per-instrument and installed risk limits, followed by stop before
expiry. The longer validity and denial at expiry/revocation need separate
qualification; the running service never renews itself. Do not mutate an old
signed envelope or relabel an older journal. A new definition, duration or
input identity receives a compatible signed artifact and fresh admission.

Retain MR14's protective targets under load: detect policy/source/account
process death and stop dependent work within two seconds; make a restarted
source usable within eight seconds while the account remains protected; fence
request-retention failure within six seconds; and reach progress for every
selected instance within forty seconds from the first actual replacement
claim request, including preparation of the remaining accounts. Stop and
settle physical outcomes, independently reconcile complete current facts,
claim a new generation, and take fresh observations after controls that advance
the account clock and before each instance restart. No uncertain account
response is retried automatically. Measure the full operator stop/settle/
reconcile/claim/progress duration separately from the forty-second clock.
The [MR14 record](multi-instance-paper.md#retained-service-observations)
observed 38.779 seconds on OKX, 38.063 on Bitfinex and 39.239 in shadow
under its smaller bounded topology; its original thirty-second target failed.
Those results are neither a four-owner recovery measurement nor a latency
distribution. A sustained gate failure retains its journal, grant, raw input
and first attempt; target revisions must precede any retry.

Research capacity is accepted separately at G2. Runtime acceptance at G4
requires the 24-hour local processing and retention result, causal/numerical
parity, both venue public routes, the loaded recovery/fencing evidence and
resource/query distributions. MR17 later composes these with a clean entry
journey. If the local path misses a target, report the exact bottleneck and
cost of a change before considering a new storage or execution service.

## Next bounded runtime prompt after the research slice

> Implement and qualify only MR15 stage-1 bounded runtime characterization on
> the declared M1 Max host. Preserve the MR14 signed authority, account risk,
> three-second selected-book semantics, latest-journal fencing and exact
> replay/economic parity. Use four venue-conformant BTC/ETH sources, four signed
> paper account owners and eight instances, with account services at most 120
> seconds, capture at most 100 seconds and a supervisor at most 75 seconds.
> Predeclare the fixture's message/byte/burst distribution, grant headroom,
> startup skew and p50/p95/p99 clocks before measurement. Implement the
> minimal probes or local changes needed to measure receipt-to-durable,
> reconstruction/consolidation, selected-book-to-checkpoint, online feature,
> query, queue, memory, disk and CPU behavior; retain actual native public
> observations separately from replayed load. Run focused correctness checks
> and the required repository gate, then retain signed identities, raw inputs,
> loss/stop reasons, parity, resource traces and failed attempts. Report which
> provisional numbers pass, fail or remain unmeasured, and specify the exact
> service-life, capture-rollover and finite-grant work needed for stage 2.
> Do not describe a <=120-second result as sustained 24-hour acceptance.
