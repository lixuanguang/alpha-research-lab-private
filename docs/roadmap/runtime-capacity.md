# MR15 runtime capacity profile

Owner: quant development. Status: **bounded stage-1 processing, native/economic
parity, four-owner recovery, receipt/BBO latency and warm queries qualified;
feature serving implemented with partial qualification; cold-cache, public-route,
checkpoint/CPU sampling and sustained-operation gaps remain; stage 2 gated; the
retained Bitfinex one-sided fault is reattributed to a transient per-order state,
with its unsigned correction pending requalification**. Updated 2026-09-29 (Singapore; observations use UTC)
after the bounded [MR14 service record](multi-instance-paper.md). The
[roadmap](README.md#runtime-operations-and-handoff) owns MR15 delivery status;
the [runtime design](../architecture/runtime-and-operations-design.md#scaling-triggers-and-technology-choices)
owns the scaling decision. The separate MR15 research slice owns multi-day
historical data, concurrent studies and offline feature capacity. This page
retains the predeclared integrated paper/shadow workload and the bounded
[stage-1 results](#stage-1-characterization-results).

The target tables are engineering capacity targets for public-input paper
operation, not observations, trading limits, exchange fill claims or live-capital
authority. Measured outcomes appear separately below.
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

## Stage-1 implementation declaration (2026-09-27)

The bounded implementation uses four independently signed venue/account targets,
eight fixed/liquidity reference instances and four native BTC/ETH sources. Each
venue has a BTC shared owner and an ETH isolated owner, each with two instances.
Account, source capture and supervisor limits stay 120/100/75 seconds, with the
supervisor launched within 20 seconds of the first account and a measured
60-second interval after all eight checkpoints exist. The local fixture has
25 scheduled messages/second/source, with 100/second during seconds 40–50; the
100-second schedule has 3,250 slots/source. Exact encoded frame sizes, fixture
identity and signed input/configuration identities are written before each trial.
Native initial books contain 400 levels/side on OKX and 25 orders/side on Bitfinex;
control records count toward socket receipt, not economic books. A subsequent
high ask ladder prevents recovery from replaying the initial economic touch.
The three-second selected-book cadence and unchanged 80-order/100-unit grants
remain binding. A 75-second service supplies at most 26 economic selections per
source, so its checkpoint latency cannot supply 1,000 observations per account;
only totals/ranges may be reported for that boundary.

Opt-in source probes retain monotonic receipt, fsynced cursor and reconstructed
book clocks; supervisor probes retain BBO and checkpoint acknowledgement clocks.
One-second process-tree resource samples and four depth plus four dashboard
readers at five requests/second run over actual retained service facts. The
existing signed reference service has no online feature-store binding; this
implementation must explicitly report that integrated budget unmeasured unless
a real binding is implemented and exercised. Warm readers do not qualify cold
cache budgets. Source startup, protection and recovery retain separate clocks.

The observed host is the declared M1 Max with 10 cores and 64 GiB RAM, macOS
27.0 build 26A428, on AC power. The retained preflight records 598,016,000,000
free bytes (about 557 GiB), above the unchanged 512 GiB prerequisite. The earlier
389 GiB commentary was inconsistent with this retained measurement; a separate
post-trial recheck also passed and is retained without replacing the preflight.
OS caches remain uncontrolled. The finite trial proceeds
within its four 32 MiB capture caps; it cannot establish 72-hour retention or
24-hour capacity. Original failed attempts and cleanup remain under ignored
`logs/runtime-capacity/`; the final compact evidence index will retain identities
and results. Reversal removes opt-in probes/consumers without changing MR14
signed authority, matching, journal schemas or budgets.

## Stage-1 characterization results

The signed candidate was exercised on 2026-09-27. **Stage 1 is implemented and
measured, but is not accepted against the unchanged targets.** The
[compact evidence index](runtime-capacity-evidence.json) binds the retained
local runs, configuration/grant identities, four release identities, source
measurements, failed attempts and validation. Large native journals, account
facts, query results and individual samples remain in ignored
`logs/runtime-capacity/`; the index retains file hashes rather than copying
those journals into Git.

The final installed runtime identity is
`3df726175795b311b2e3c457290afb1fb6c762832564d8d8557a64954a6c2402`.
The final fixture run (`attempt-5/steady`) starts eight instances on four signed
owners and measures **62.109 seconds after startup**. First account launch to
supervisor launch is 1.226 seconds. Observed launcher lifetimes are
65.588–65.881 seconds for accounts and 64.661 seconds for the supervisor;
source children end inside that supervisor interval, below their 100-second
capture bounds. The four journals finish stopped, and the retained PID audit
finds none of the 21 observed account, launcher, policy, source or supervisor
processes alive. These are finite lifetime observations, not a completed
100-second capture or healthy continuous operation.

| Boundary | Final fixture observation | Status against unchanged target |
| --- | --- | --- |
| Input schedule and continuity | 390/390 OKX and 414/411 Bitfinex native frames become durable; source receipt spans only about 15.6–16.6 seconds within the 62.109-second measurement. | **Fail.** The authored base/burst schedule is not sustained. |
| Queue | Peaks are 1,157–1,237 records; oldest queued age is 29.61–29.94 seconds. | **Fail** versus 1,024 records and two seconds. |
| Receipt to durable; BBO; checkpoint latency | Receipt-to-durable maxima approach 30 seconds. Each source boundary has fewer than 1,000 samples; eligible BBO counts are 267–269 and committed checkpoint counts 2–3 per account. | **Unmeasured percentiles**, with severe observed delay. No pooled-source percentile substitutes for a source boundary. |
| Warm query schedule | Depth completes 578/1,200 attempts, dashboard 203/1,200. Maxima are 1.143 and 3.070 seconds. | **Fail schedule; unmeasured percentiles.** Cache state is uncontrolled; cold targets remain unmeasured. |
| Online features and consolidation | Signed reference policies have no integrated versioned feature-serving path. USD and USDT are kept separate. | **Unmeasured feature budgets.** No invented cross-currency consolidated view. |
| Resource observer | 15/60 intended one-second samples; peak sampled RSS 1,986,068,480 bytes, sampled CPU mean 1.73 cores, peak scoped occupied bytes 114,483,200. OS process I/O counters are unavailable. | **Insufficient sampling.** These sparse values do not qualify resource ceilings; CPU p95 also lacks 1,000 samples. |
| Native replay parity | Every retained delivered prefix reconstructs exactly; 3/3 OKX and 20/20 Bitfinex durable native frames have no retained supervisor delivery. | **Full-stream parity unqualified.** Shutdown does not drain the published source tail. |
| Economic oracle | OKX owners each retain two units, cash 99,798.799 USDT, fees 0.201 USDT. Bitfinex owners each retain four units, cash 99,597.44 USD, fees 0.40 USD. | **Fail predeclared first-touch oracle** on both Bitfinex accounts. |

The Bitfinex mismatch is an invalid fixture assumption, not evidence that account
arithmetic changed. Updating 25 individual R0 ask orders exposes an intermediate
best ask of 100.08; a second selected opportunity can consume two more units
before the whole ladder reaches 104. The original two-unit expectation and the
second fill are both retained. A future fixture must predeclare and qualify its
entire economic path under receipt/selection timing; changing the expected
balance after this run would not establish parity.

The observed processing bottleneck precedes journal append. In the earlier
measured candidate (`attempt-4`), append/fsync means are about 1–3 ms and native
reconstruction below 1 ms, while source wait grows to many seconds. Each
supervisor pass handles one delivery per source and then sleeps 20 ms.
Synchronous monitoring and selected account/checkpoint operations consume the
remaining base-rate headroom. After freshness protection, another 100–107
unique `public_input_invalid` controls per account amplify the backlog. This is
an inference from retained boundary clocks and control records, not an isolated
profiler attribution. The full measured diagnosis is retained in
`logs/runtime-capacity/bottleneck-analysis.md`.

The smallest next performance experiment is a work-conditional supervisor sleep
that preserves per-source ordering, fairness and periodic protection checks.
Its cost is a focused fairness/control regression, exact source/account parity,
a fresh signed installed candidate and another bounded 60-second run. Draining
published source deliveries at shutdown needs a separately bounded lifecycle
proof. Suppressing repeated controls changes durable history and is not an
accepted shortcut. No runtime optimization or budget relaxation was applied to
make this characterization pass.

### Consumers and retained attempts

The maintained consumer files are in
[`tests/integration/consumers/runtime`](../../tests/integration/consumers/runtime/capacity_trial.py):
`capacity_inputs.py` prepares the exact four-source configuration, distributions,
separately bound releases and finite grants; `capacity_trial.py` owns signed
startup, measurement and cleanup; `capacity_recovery.py` owns one-shot fault and
replacement-claim observations; `capacity_reads.py` reads retained depth and
monitoring facts; `capacity_results.py` joins durable cursors to measured
boundaries; and `capacity_source_cases.py` runs bounded native adapter cases.
This is substantial local characterization harness work in addition to the
small opt-in runtime probe surface. It is not a new operating service.

Copy these consumers together with `paper_services.py` outside the checkout and
use the pinned installed research interpreter. Prepare with
`CapacityWorkload.prepare`, build/verify/install each account using the existing
signed artifact workflow, then call `CapacityWorkload.finalize` with the four
verified release identities. Every fresh journal trial needs a fresh socket
root; an existing scheduler-owner fence must not be deleted or reused with a
lower generation. Invoke `capacity_trial.py run --root <prepared-root>
--output <new-evidence-directory> --launcher <installed-artifact-launcher>`.
`--public-venue okx` or `bitfinex` replaces only that venue's fixture transports;
`--faults` requests distinct one-shot protection probes; `--recover` requires
retained exact facts, stop/settlement/reconciliation and new owner claims.
An uncertain account response is retained and never retried automatically.

`measurement_root` is an opt-in argument to `run_paper_services`; capture and
shared-paper observers accept process-owned `RuntimeMeasurementJournal`
instances. The probes retain monotonic boundary clocks and selected/checkpoint
facts separately from economic inputs. Their file writes have measurement cost.
Probe-close failure cannot skip source/worker fencing or account shutdown.
Disabled probes retain the original runtime path and signed MR14 contracts.

Attempts 1–3 retain, respectively, local socket-access denial, the observer's
incorrect nested capture discovery, and correct rejection of a fresh generation
against an older scheduler fence. Attempt 4 retained 61.695 seconds, two-unit
account economics and delivered-prefix replay parity, but failed load, complete
parity and resource/query sampling. Attempt 5 retained the final signed runtime
and the additional Bitfinex oracle failure. These attempts are not overwritten
or combined into a reliability success rate. A final full repository gate and
focused regressions cover the delivered probes and consumers; exact results are
in the evidence index.

The resource observer was subsequently moved into a separate process, with one
root process tree and per-phase timings. This removes query-thread GIL contention
and repeated descendant traversal from its sampling loop. It does not change
queries or budgets and cannot repair the original sparse traces. The maintained
reader shutdown uses a shared interval deadline so a stalled reader cannot add a
new full timeout for every thread before requesting service shutdown.

### Public routes, adverse inputs and recovery

Both venue routes were exercised separately with the final installed runtime,
four owners and eight instances; the other venue retained the declared local
fixture. Public rates below are observations, not authored schedule shortfalls.
Both runs lost active service and therefore failed integrated acceptance.

| Observation | OKX public route | Bitfinex public route |
| --- | ---: | ---: |
| Measured interval | 61.740 s | 62.646 s |
| Durable native BTC / ETH frames | 408 / 407 | 403 / 358 |
| Steady native arrivals BTC / ETH | 400 / 400 (6.48 Hz each) | 389 / 340 (6.21 / 5.43 Hz) |
| Invalid native outcomes | 0 / 0 | 0 / 0 |
| Oldest queue age BTC / ETH | 16.74 / 16.87 s | 29.97 / 29.96 s |
| Unmatched durable native tail BTC / ETH | 2 / 2 | 17 / 16 |
| One-second resource samples | 60 / 60 | 60 / 60 |
| Peak sampled RSS | 2,176,778,240 bytes | 2,223,915,008 bytes |
| Mean sampled CPU demand | 1.78 cores | 1.74 cores |
| Peak scoped occupied bytes | 119,742,464 | 146,501,632 |

Snapshots, incremental updates and native control/heartbeat messages were
retained. Public owners committed no selected checkpoints; the eight-instance
startup witness is not proof of continued public economic progress. Each live
source has fewer than 1,000 latency observations. These resource values are
below their ceilings under the **observed failed workload**, not proof of the
authored healthy processing envelope; CPU p95, process I/O counters, cold cache,
complete capture and full parity remain unqualified. The first two public
collector summaries mistakenly compared live arrivals with fixture due slots;
they are retained separately and corrected summaries explicitly mark live
provenance. No source or budget changed for that correction.

Four source-only cases ran all four native adapters, producing **16/16 expected
failure-detection and native-replay passes**. Quiet input retained `idle_timeout`
within 35.1 seconds; oversize retained `frame_limit_unknown_loss` within 25.1
seconds; backpressure reached the hard 2,048-record queue and retained
`overload_unknown_loss` within 25.9 seconds; reconnect retained
`disconnect_unknown_loss`, two epochs and synchronized native books within 55.5
seconds. Raw cursors, complete manifests, request/fixture identities, individual
measurements and stop reasons remain under `source-cases`. Signed-target
installation overlapped these component cases; no account-load or resource
qualification is inferred from them. A visible expected loss is a protection
pass for the case, not a continuity pass.

The first loaded fault trial measured source protection at 1.021 seconds,
protected source restart at 1.259 seconds and owner-death protection at 0.983
seconds. Policy and request-retention verification used an offline installed
read while the live account held its installation fence, so those checks failed
in the harness and request-retention was not injected. The consumer now uses the
same owner's live socket for such reads. The original failures and subsequent
fresh-target retry are retained separately. The corrected fresh-target trial
measured policy stop **0.879 s**, source protection **1.139 s**, protected source
restart **1.279 s**, request-retention fencing **2.362 s**, and owner-death
protection **1.150 s**: all five timing assertions pass their original 2/8/6-second
budgets. Retention obstruction was restored and committed economics/checkpoints
were unchanged. These are individual drills during initial base load, not a
healthy 60-second or burst-load recovery qualification. Its overall summary
remains failed because cleanup sent a second shutdown after the first had
already succeeded. All processes still exited inside their bounds and all
journals stopped. The maintained driver now records that shutdown was requested
before sending it and never resends it; this recorder fix does not erase either
fault-trial summary or require repeating the measured fault injections.

Four-owner recovery remains **unqualified**. Its first attempt hit unchanged
price-deviation protection: the harness had observed 104 against retained sell
intents at 98. After correcting only that observation to the original reference
100, a second attempt retained two actual replacement claims, then refused the
Bitfinex economic oracle mismatch before claiming those owners. The refusal was
28.136 seconds after the first replacement request (38.029 seconds from operator
start); cleanup completed at 46.446 operator seconds with all four journals
stopped. There is no all-eight progress endpoint and therefore no forty-second
recovery pass. Prior generations were checked as fenced for the two successful
claims. No uncertain operation was retried and the original grants were not
renewed or expanded.

Stage 2 still requires exact, gap-aware capture segment rollover; a separately
qualified longer finite service lifetime or handoff with one economic owner and
uninterrupted source processing; and newly issued finite 26-hour authority with
unchanged order/quantity/risk limits plus expiry/revocation denial proof. The
stage-1 load, fixture parity, query, feature and complete recovery failures must
also be resolved before claiming integrated capacity. Nothing in this record
qualifies 24 hours of processing or 72 hours of retention.

### Processing, parity and recovery requalification (2026-09-28)

The follow-up keeps every target above unchanged and retains the original
characterization rather than replacing it. The candidate removes the fixed idle
sleep after a productive supervisor pass. Cooperative source shutdown drains
accepted receipts and published deliveries before account services close, with
explicit terminal records and complete cursor accounting inside the same finite
lifetime. Forced or incomplete shutdown remains a failure.

The first fresh signed attempt still failed during the declared burst and
exceeded the supervisor lifetime. Its traces isolated repeated full-depth
projection in the parent observer. The subsequent candidate retains and validates
each complete canonical book, derives the exact touch without reconstructing
unused aggregate depth, and calculates exact imbalance when a decision reads it.
Eligibility, native depth, clock/provenance semantics and the three-second
selection interval remain unchanged. The earlier signed attempt and its partial
delivery tails remain failed evidence.

The second signed attempt retained that quote/input parity and completed the
supervisor lifetime in 74.399 seconds, but still lost all eight active instances
during the burst. Its four source queues reached 877–897 records and about
28 seconds of oldest age. Economic replay matched the delivered prefixes, while
all four native streams remained incomplete. This remains a failed attempt;
meeting the process bounds and a prefix oracle does not qualify the load.

Whole-observer profiling then identified repeated validation of the same frozen
book after typed envelope validation. The next repair keeps checks at public
entry points and serialized boundaries, and shares internal projection cores
only after the enclosing delivery has validated its complete native book.
It also records one confirmed public-input fault per observer lifetime. A
rejected or uncertain control response is surfaced without setting that latch;
every subsequent native delivery is still retained. This explicitly changes
the repeated fault-record amplification described in the original diagnosis,
while preserving the initial durable protection and owner fencing.

The third signed attempt (`requalification-3`, implementation
`fe559e3e9f7295a602416dae4704fab363e6d45eb5cd636a919b493cf87a78da`)
proved complete native and economic parity for all four streams, including all
declared burst slots and every shutdown delivery. The supervisor exited after
66.047 seconds and account launchers after 66.812–66.988 seconds. It nevertheless
failed healthy processing: queue occupancy reached 382–399 records and oldest
age 6.022–6.256 seconds, and all four owners became protected during the burst.
The 60.196-second interval is therefore measured load, not sixty healthy seconds.
Recovery was withheld. Its OKX public route passed the finite health/lifetime
checks, its Bitfinex route failed final health, and all four explicit fault probes
completed inside the declared burst window. All 21 observed PIDs per trial were
absent afterward and the four journals were stopped. These records are retained
without replacing the earlier failures.

The fourth signed attempt (`requalification-4`, implementation
`a7206c00c33cab9ece5a3197fb3864dfc6d0455f0c4cf4264e4b1ea4195a5485`)
separated full read-only diagnostics from synchronous account-phase protection.
It retained 60.053 healthy seconds and complete native/economic parity, with
supervisor lifetime 63.610 seconds and account lifetimes 64.491–64.686 seconds.
Its queue peaks were 312–330 records, but oldest ages were 4.300–4.690 seconds,
so the unchanged two-second queue budget still failed and recovery was withheld.
Both public-route observations passed their finite health/lifetime checks. The
burst request-retention probe remains failed in its original summary. Read-only
attribution subsequently proved unchanged ledger, orders, fills, costs and final
checkpoint; one benign trace came from an already retained request between the
probe reads. The revised probe freezes request bytes at obstruction, requires
exact economic/checkpoint preservation, and admits only matching pre-obstruction
trace appends with no economic events. It retains full witnesses before asserting. All 22 observed runtime PIDs per steady/public
trial and 23 in the source-restart fault trial were absent afterward; all four
journals were stopped. Its complete repository gate passed 1,864 tests (two
skipped, three deselected), and all 138 affected checks passed. A passing driver
health result is not a passing queue or integrated-capacity result.

The version-2 Bitfinex fixture starts with one ask at 100 and the remaining 24
asks at or above 104. At the original reprice slot it updates that one R0 order
to 104 atomically. This prevents an intermediate 100.08 touch from supplying a
second fill while keeping native depth, rates, burst, three-second selection,
and the independently declared two-unit oracle unchanged. Each closed fixture
epoch retains its original monotonic schedule anchor, emitted slot indices and
frame hashes; qualification compares these with the complete durable capture.
The fixed oracle must also pass against the actual retained selection clocks.
The atomic update removes the observed intermediate-price race; it does not
claim that arbitrary timing jitter anywhere inside the queue-age ceiling yields
the same selection path.

The four independent recovery workflows run concurrently. Within each account,
stop, cancellation settlement, independent reconciliation, replacement claim,
fresh restart observations and former-owner fencing retain their original order.
The first actual replacement claim starts the unchanged forty-second clock;
the endpoint requires eight live active instances and eight nonempty changed
checkpoints. Operator preparation is measured separately.

The final repair removes repeated native-book validation inside private delivery
wrappers after the typed pipe boundary has validated every nested record. Public
constructors and public observer/replay entry points still validate complete
books; malformed or mutated wrappers cannot bypass retention checks. The account
store reuses an immutable state only after its exact serialized bytes commit.
Every read still checks the current SQLite configuration and payload, and every
write retains the serialized transaction and schema/activation invariant. Tests
cover another writer, changed configuration, malformed payload and rollback.
No owner, grant, risk or selection check moves into an unchecked cache.

Component measurements on the same retained 4,000 burst rows reduced decode plus
observer time from 11.050 seconds to 9.635 seconds after delivery repair, then
7.849 seconds with the commit cache. Native, retained-delivery and economic hashes
matched for all four streams. These diagnostic measurements excluded live IPC
and did not qualify capacity. The subsequent signed run below supplies that
evidence; all intermediate profiles and failed checks remain retained.

#### Fresh signed result

The fifth candidate, implementation
`b0398cf0a17f7f60a607268fac1be3a19f7957fc024977f491d7a0f4a967d73c`,
ran from four fresh signed account releases under `requalification-5`. All 336
runtime source files matched each signed archive and the installed identity;
the maintained consumers matched their retained run copies. Fresh one-hour
grants were issued after validation, with the same 80-order, 100-unit and
installed risk limits. Exact release, configuration, authority and fixture
identities are in the [evidence index](runtime-capacity-evidence.json), under
`requalification`; its original characterization fields and attempts remain
historical evidence.

| Bounded measure | Initial run | Replacement-owner run |
| --- | ---: | ---: |
| Healthy measured load, four sources/four owners/eight instances | 60.036 s | 60.008 s |
| Maximum source queue age / occupancy | 1.283 s / 113 records | 1.563 s / 132 records |
| Supervisor lifetime, 75 s ceiling | 62.846 s | 62.928 s |
| Account launcher lifetimes, 120 s ceiling | 63.718–63.852 s | 63.975–64.070 s |
| Complete native streams / shutdown tails | 4 / 0 | 4 / 0 |
| One-second resource samples | 60 | 60 |
| Mean / peak sampled CPU, logical cores | 1.983 / 3.194 | 2.125 / 3.166 |
| Peak sampled RSS, bytes | 3,973,824,512 | 4,018,192,384 |
| Peak scoped occupied bytes | 280,100,864 | 303,853,568 |

Both runs received every required authored slot, including all 1,000 burst slots
per source during seconds 40–50, with exact native frame hashes. All sources
finalized complete manifests, exited cleanly and drained every durable record
through the supervisor into retained account deliveries. They started after the
supervisor and exited before it, so their lifetimes also remain below the
unchanged 100-second capture bound. The initial capture retained 2,287 native
messages for OKX BTC and 2,286 for each other source; three lifecycle records per
stream bring complete durable/delivery counts to 2,290 and 2,289 respectively.
Encoded size and queue budgets passed without relaxing any target.

Complete independent unmanaged replay matched all four initial accounts across
ledger, child orders, physical orders, fills, costs, paper traces and all eight
checkpoints. Each account also matched the independent two-unit fixture oracle.
This comparison was retained before recovery changed the original journals.

All four owners then advanced exactly one generation, with unchanged checkpoint
bytes at claim and exact stale-owner denials. All eight replacement instances
produced nonempty changed checkpoints **9.148 seconds after the first actual
replacement claim**, within 40 seconds; the full operator sequence to that
endpoint took 21.352 seconds. The exclusive recovery preservation witness links
the baseline replay hashes to settled and final facts: ledger, fills and costs
remain exact across settlement; ledger, orders, physical orders, fills and costs
remain exact after settlement; prior trace bytes remain exact prefixes. Grants,
deployment, risk, native depth and three-second selection remain unchanged.
This proves recovery preservation and progress alongside complete native parity;
it does not claim an independent replay of the recovery trace suffix.

#### Remaining measured gaps and public observations

Processing success does not satisfy every latency target. The initial run had
at least 2,262 samples at each listed native/BBO boundary:

| Initial-run boundary, p50 / p95 / p99 in ms | BTC | ETH | Result |
| --- | --- | --- | --- |
| Bitfinex receipt to durable | 1.43 / 765.54 / 1,036.62 | 1.39 / 766.64 / 1,036.37 | Fail |
| OKX receipt to durable | 1.67 / 965.73 / 1,200.89 | 1.78 / 968.14 / 1,207.12 | Fail |
| Bitfinex durable to BBO | 25.11 / 470.58 / 1,020.23 | 25.49 / 472.55 / 1,062.24 | Fail |
| OKX durable to BBO | 18.54 / 88.76 / 473.98 | 19.14 / 98.09 / 452.45 | Pass |

Recovery receipt and BBO latency distributions also missed their targets. The
initial depth readers completed **362/1,200** scheduled queries, with maximum
22.022 seconds; dashboard readers completed **180/1,200**, maximum 9.671 seconds.
Recovery completed 350 depth and 188 dashboard queries, maxima 18.923 and 7.158
seconds. Successful calls had no reported exceptions, but the request-rate gate
failed; fewer than 1,000 samples cannot establish the required percentiles.
CPU has only 60 samples/run. Each initial account had only two committed
checkpoint measurements (20–21 selections acknowledged, the remaining decisions
rejected under the existing account state); recovery had no newly committed
economic orders. Changed policy checkpoints prove instance progress without
inventing additional fills or a checkpoint latency distribution.

Integrated versioned feature materialization/retrieval remains absent. Cold
cache is uncontrolled, process I/O counters are unavailable on this host, and
no 24-hour replay, continuous capture or 72-hour retention claim is made.
The resource ceilings pass only for the sampled bounded workload above.

| Fresh public observation | OKX BTC / ETH | Bitfinex BTC / ETH |
| --- | ---: | ---: |
| Measured interval | 60.006 s | 60.897 s |
| Actual steady native arrivals / rate | 510 / 8.50 Hz; 490 / 8.17 Hz | 1,538 / 25.26 Hz; 1,147 / 18.84 Hz |
| Complete captured native messages | 519 / 501 | 1,574 / 1,159 |
| Maximum public-source queue age | 0.126 s | 0.573 s |
| Finite health result | Pass | Fail: ETH account became protected |

All four streams in both public trials retained complete native parity and
bounded shutdown. The Bitfinex health failure remains a failed observation;
public activity is not substituted for the declared fixture load. Individual
resource/query measurements and source-quality facts remain in each collector.
The retained ETH R0 update at source position 275 deleted its last visible bid.
The resulting one-sided book triggered the existing `public_input_invalid`
control, observed as account protection at 04:47:34.321 UTC. Neither public
stream had a native gap or invalid reconstruction outcome. The exclusive
attribution record pins the exact frame, delivery and durable control; no risk
or public-input quality rule was relaxed to turn this into a healthy result.
The [2026-09-29 reattribution](#reattribution-and-harness-corrections-2026-09-29) shows this was a sub-millisecond intermediate
per-order state rather than a one-sided market.

The final fault trial injected all four probes inside the authored burst.
Policy death fenced in **0.106 s**; source death protected in **1.012 s** and its
replacement became usable in **1.046 s** while the account stayed protected;
request-retention failure fenced in **0.972 s**; owner death protected in
**0.952 s**. These pass the original 2/8/6-second limits. Retention obstruction
was restored, with exact economic/checkpoint preservation and a retained frozen
request witness. The probes are sequential: later probes use the surviving
topology, not a new all-eight health claim. All 22 observed runtime PIDs per
steady/recovery/public trial and all 23 in the source-restart fault trial were
absent afterward; all four final account phases were `stopped`.

The frozen candidate passed **209 affected tests** and the complete `make check`:
**1,885 passed, two skipped, three deselected** (250.75 seconds for pytest), plus
strict typing, stubtest, formatting/lint, engineering/dependency/architecture,
security/secret checks and installed-wheel smoke validation. Earlier failed
attempts and checks are retained individually. MR15 integrated capacity remains
open. Stage 2 stays gated on the existing capture-rollover, longer finite
service/handoff and separately qualified 26-hour authority requirements, as well
as the remaining latency, query, feature and public-health gaps.

### Validation of the original delivered state

The final `make check` passed with **1,837 tests passed, two skipped and three
deselected** (265.61 seconds for pytest), plus frozen-lock checks, Ruff, strict
mypy, stubtest, engineering/dependency/architecture checks, security/secret
checks and installed-wheel smoke validation. The original access, formatting,
interrupted-gate and documentation-link failures remain retained. Focused
regressions cover native replay with probes, probe-close cleanup, source fixture
identity/restart behavior, causal query cutoffs, honest partial-parity/sample
reporting, isolated process sampling and a blocked reader at the shared shutdown
deadline. Later collector/recorder changes preserve the original run copies and
measurements rather than relabeling them as successful reruns.

The final PID audit covers every observed runtime PID from attempts 1–5, both
public routes and both fault trials: all are absent; every retained final
account phase is `stopped`. Prelaunch failures are labeled as having no observed
running-service PID. This cleanup result does not upgrade any failed capacity
or recovery criterion.

### Latency and warm-query closure declaration (2026-09-28)

This follow-up closes only the measured receipt/BBO latency and warm-query gaps.
The original budgets, native depth, signed authority, risk limits and three-second
selection cadence above remain binding. Qualification requires four sources,
four owners and eight instances, at least 60 continuously healthy measured
seconds including the declared burst, and complete native/economic parity.
Four depth and four dashboard readers each complete 300 requests scheduled
200 ms apart within that minute. Service and scheduled-arrival response latency
must both pass; each claimed percentile needs at least 1,000 observations.

The final signed implementation must pass steady and replacement-owner recovery
measurements, the affected loaded fault checks and retained Bitfinex one-sided
protection. Account/capture/supervisor lifetimes remain bounded by 120/100/75
seconds. Run affected checks before freezing, establish steady and recovery
viability before full local `make check`, and run no hosted CI. Builds, tests,
profiling and source edits must not overlap measured intervals.

Unchanged source-protocol/oversize/reconnect and public-route evidence remains
historical with its original identity and limitations. Feature serving, cold-cache
qualification, fresh successful Bitfinex public health, sustained processing,
capture rollover, longer service/handoff and extended authority remain open.
Stage 2 stays gated. No account journal, grant or durable capture migration is
introduced by these repairs.

The [canonical index](runtime-capacity-evidence.json) retains the original
characterization and processing/recovery requalification sections. Its unchanged
artifact lists moved to the hash-linked
[historical manifest](runtime-capacity-artifact-manifest.json) to keep each file
within the existing 1 MB scanner limit. The 442 original and 2,050 requalification
entries remain exact; restoring both lists reconstructs the pre-split JSON.
Current closure evidence should link retained reports rather than duplicate
their raw rows or inventory every reproduced installation.

#### Retained follow-up attempts

All attempts and their original traces remain under
`logs/runtime-capacity/latency-query-N`. The earlier detailed narrative is
retained in `latency-query-9/retained-followup-history.md`; diagnostic profiles
remain in `logs/runtime-capacity/latency-query-diagnosis`.

| Candidate | Outcome and next diagnosed cause |
| --- | --- |
| 1 | Failed. Both query classes completed 1,200 requests; depth response p95/p99 was 1,644.548/3,026.238 ms, queue age reached 6.330 seconds and health ended early. Native/economic parity and bounded cleanup passed. A depth reader held a shared lock while draining a moving file end. |
| 2 | Failed before launch. Four signed builds were retained; local checks rejected a cross-owner private decoder import. No paper authority was granted. |
| 3 | Failed before launch. The relocated decoder left an extra terminal blank line rejected by formatting. No paper authority was granted. |
| 4 | Failed. Depth response p95/p99 was 776.430/1,756.544 ms and a 2.296-second observation gap broke health. Retained replay identified costly GC over complete native-book histories; parity and cleanup passed. |
| 5 | Failed. Encoded histories brought depth response to 12.631/96.439/164.937 ms, but source latency failed, dashboard completed only 1,193 requests and health ended early. A separate instrumented run remained diagnostic only; account calls serialized independent selected-book work. |
| 6 | Failed. Health, both 1,200-request classes, parity, resources and lifetimes passed; Bitfinex BBO p95 was 223.610/224.729 ms and OKX receipt p95 was 270.026/272.750 ms. Per-pass joins still serialized work. |
| 7 | Failed. Health, query capacity and parity passed, but source receipt p95 regressed to 2–3 seconds. Completion polling and repeated owner-file reads delayed admission. Its separately instrumented attempt also failed health and remains retained. |
| 8 | Steady passed; recovery failed Bitfinex BTC BBO p95 at 101.929 ms against 100 ms. Recovery retained health, query capacity, economic facts, owner fencing and all-eight progress. Loaded faults and one-sided replay were not run for this failed candidate. |

Failed setup, local-CI, profiling and network attempts remain in their respective
candidate directories. Their successful reruns do not replace the first result.
The one-sided replay on candidate 1 preserved `public_input_invalid` across
1,162 retained Bitfinex ETH deliveries; it is protection evidence, not a fresh
successful public-feed observation.

#### Repairs supported by the retained profiles

Receipt delay lay mainly outside durable append: retained burst append means
were 1.21–1.38 ms. The L2 touch path now constructs only its selected sides, and
the private source-pipe decoder validates native children once while public
entries retain full validation. Decoder microprofile gains alone were small in
the complete burst replay (7.653 to 7.525 seconds).

Readers capture finite file prefixes and retain explicit partial coverage.
Complete native history is stored as validated bytes and decoded at the selected
causal row, avoiding repeated GC scans without dropping revisions or changing
history limits, cutoffs or freshness. All 1,200 controlled same-prefix results
matched; three older diagnostic outputs still lack enough prefix evidence to
reconcile their mismatch. Dashboard work reuses bounded exact payload/render
work while current SQL revisions, retention, availability, metrics and alerts
are reevaluated.

Independent accounts may keep one source observation in flight across supervisor
passes. Per-source/shared-account order remains serial; lifecycle changes join
outstanding work. Completion notifications and owner-file checks scheduled within
the existing 20 ms idle bound avoid unnecessary waiting. Source/worker health
and account RPC authority checks remain active.

### Fresh signed latency and warm-query follow-up

Candidate 9 retained the fresh account-and-market membership repair but failed
recovery BBO p95 at 131.288 ms for Bitfinex BTC and 121.677 ms for ETH. Its
separate diagnostic recovery located repeated installed-source hashing in the
selected-account telemetry path. Twenty-one uninstrumented hash calls averaged
14.652 ms; this diagnostic is not a qualification percentile. All three candidate
9 runs retain their original results and clean process audits.

Candidate 10 binds the telemetry fingerprint once per account application lifetime,
while every operation still reads current account facts and verifies authority.
It retains full trace reporting and uses fresh Boolean membership only where the
observer previously transferred history to answer that question. Four newly
signed releases bind implementation
`7f31316338bacfb945de79d00ac87b7460739a0087e7e91b3f64294e9e6e68bb`.
The [canonical index](runtime-capacity-evidence.json) links the compact closure
record at `logs/runtime-capacity/latency-query-10/closure-evidence.json`.

| Measured boundary | Steady | Replacement-owner recovery |
| --- | --- | --- |
| Continuously healthy interval | 60.004 seconds | 60.003 seconds |
| Receipt p95 across four sources | 2.697–3.422 ms | 4.949–79.402 ms |
| BBO p95 across four sources | 21.250–23.467 ms | 32.473–81.215 ms |
| Depth scheduled-arrival response p50/p95/p99 | 8.747/21.648/29.336 ms | 7.618/22.922/35.697 ms |
| Dashboard scheduled-arrival response p50/p95/p99 | 55.351/106.615/126.875 ms | 53.925/114.585/144.647 ms |

Both trials pass every declared receipt/BBO and warm-query percentile, including
service latency. Each source supplies 2,250 receipt and 2,228 BBO samples in the
measured minute; each query class completes 1,200 requests, 300 per reader.
Complete native parity and steady economic replay pass. Recovery preserves the
baseline economic facts, fences former owners and advances all eight instances
within the original recovery budget. Independent recovery-suffix economic replay
remains unqualified.

Average CPU was 2.063/2.191 logical cores and peak RSS 2.472/2.483 GiB for
steady/recovery. Account lifetimes were at most 63.616 seconds, and enclosing
supervisor lifetimes at most 62.429 seconds also bound all capture children.
All original queue, disk and lifetime limits pass. Loaded policy/source/owner and
request-retention faults pass; the retained 1,162-delivery Bitfinex ETH replay
preserves `public_input_invalid`. Every observed PID is absent after cleanup and
all four accounts are stopped in every trial.

Final local `make check` passed: 1,958 passed, 2 skipped
and 3 deselected; installed-wheel smoke passed. All measured runtime source bytes
remain identical to the four signed archives. No hosted CI ran. This closes the
bounded stage-1 latency and warm-query slice only; the feature, cold-cache,
fresh public-health, sustained-service and other limitations declared above
remain open, and stage 2 stays gated.

### Remaining bounded stage-1 declaration (2026-09-28, baseline ec34b8b)

This continuation preserves candidate 10 and its historical manifests. The
milestones are public-source qualification and finite corpus acquisition;
integrated feature serving; independent recovery-suffix and populated-history
query evidence; then representative R1 only after corpus admission. Collector
rollover is public-data acquisition only. Account lifetimes, grants, risk limits,
four owners, four sources, eight instances and three-second selection are unchanged.
Reversal retains new recordings and failed attempts and restores the previous
implementation; old recording/request identities must remain readable and exact.

The feature sampling plan declares one initial 60-second steady interval and
seventeen separate, homogeneous 60-second replacement-owner intervals. Each uses
the same installed bytes, native fixture, four two-value feature definitions,
one-second per-instrument cadence, five-second TTL, eight readers at four
lookups/second, and concurrent depth/dashboard readers. Each interval requires
1,920 retrieval calls; the replacement-owner materialization cohort supplies
1,020 two-value publications **per source**, without counting the two scalar
values as two observations. Keep initial steady and replacement-owner cohorts
separate and refuse incompatible definitions, clocks, cache classes or input
configurations. Scheduled response and operation durations remain separate.
Only complete healthy intervals contribute to a passing cohort; retain failures
and do not silently replace them. Existing cumulative 80-order/100-unit limits
and the original one-hour authority expiry remain binding. Refuse another
invocation without the existing authority headroom; do not extend a service or
grant to finish a percentile. Diagnose the first failing boundary before a retry.

Independent replay must include the recovery operator controls and exact native
suffix, not only prefix preservation. Populated-history queries must retain the
actual history size and returned/scan bytes, distinguish application initialization
from warm requests, and label filesystem caches uncontrolled. A fresh object is
not physical cold disk. Fewer than 1,000 compatible observations leave percentile
claims pending, including CPU and checkpoint boundaries. Unsupported physical I/O
byte counters remain unavailable; logical bytes and block operations are separate.

Candidate-10 processing, native/economic parity, recovery preservation/fencing/
progress, latency, warm-query and adverse-input evidence remains valid for its
unchanged installed bytes. New integrated feature load needs fresh qualification;
new collector rollover needs its own continuity, interruption and ingestion proof.
The later sustained lifetime/handoff, extended finite grants, 24-hour integrated
trial, 72-hour runtime retention, seven-day telemetry and 4x replay stay in stage 2.


The first feature consumer cohort retained an initial pass and one replacement
pass, then stopped on replacement interval 2: 1,919 of 1,920 reads passed. One
reader sampled its cutoff before a concurrently activated version. The store
correctly returned `future` with no value; the observer incorrectly compared it
with the value available offline at that later version cutoff. The retained
clocks locate activation inside that read. This is a consumer coordination defect,
not evidence of a native/economic regression or a store causal leak.

Before requalification, the corrected consumer serializes each source's activation
and query-cutoff selection; queue/lock waiting remains inside measured response
and service latency. Its deterministic concurrent-publication regression must
pass before another signed run. A separate initial-plus-seventeen cohort uses
fresh ordinary one-hour grants and fresh account journals, unchanged 80-order /
100-unit limits, and the same candidate-10 signed releases. Existing grants and
service lifetimes are not extended. Preserve all first-cohort attempts and exclude
them from the changed-consumer materialization/CPU populations. The original
sampling counts, stop-on-first-failure rule and percentile thresholds remain.

The corrected consumer's initial trial passed, but its first recovery stopped
before measurement when two dashboard readers encountered the telemetry file
before the writer committed its schema. The next cohort adds only a committed
schema readiness wait within the existing shared five-second startup deadline;
steady queries are not retried. It retains the failed startup and cleanup record,
uses a fresh initial-plus-seventeen cohort, and pools no earlier observations.

### Independent suffix, fresh routes and populated-history boundaries

The new independent replay of candidate 10's original recovery suffix qualifies.
For each of four accounts it replays the baseline, the seven retained operator
controls and the exact selected native suffix in a fresh unmanaged oracle.
Ledger, orders, net orders, fills, costs, traces, checkpoints and original
source/selection identities match exactly. The 84 selections in each prefix or
suffix are recomputed, not copied from a preservation assertion. The report is
`logs/runtime-capacity/bounded-evidence/recovery-suffix-final.json`; unmanaged
replay adds no trading authority. Original signed owner fencing/progress and
protection evidence remains applicable to the unchanged implementation.

Fresh OKX public operation supplied 606 BTC and 608 ETH messages and a complete
healthy 60.005-second interval with 121 health witnesses. Both native streams
have complete delivery parity, drained shutdown and bounded queues. The other
venue remained the authored load in this route-specific trial. The public sample
counts do not establish 1,000-sample latency percentiles. Fresh Bitfinex ETH hit
the unchanged 5,000-message ceiling after 59.313604 seconds (84.30 messages/s),
ending before a healthy minute was complete. Its last observed book was two-sided;
this is a finite source-envelope incompatibility, not the earlier one-sided case.
All trial PIDs are absent and all four accounts stopped after both attempts.
Keep the prior one-sided Bitfinex ETH protection proof as historical evidence; the
[2026-09-29 reattribution](#reattribution-and-harness-corrections-2026-09-29) replaces its protection claim. Another healthy public
Bitfinex trial requires a specific source-budget decision or qualifying observed
rate; no cap is silently increased and no failed attempt is discarded.

The populated-history diagnostic retained actual native source histories of
2,286 rows/source (about 73.5 MB per OKX source and 8.22 MB per Bitfinex source)
and separate, explicitly authored one-hour dashboards with 10,000 events/account.
Four application-cold observations per query class gave depth ranges of
4.043–4.135 seconds for OKX and 0.816–0.986 seconds for Bitfinex; dashboard range
was 0.865–0.868 seconds. Warm dashboard calls on this larger history took
0.675–0.679 seconds. Exact cutoff/result parity passed. These are diagnostic
ranges, not percentile acceptance or a percentile runtime failure. Profiling
attributes approximately 99.9% of cold depth time to complete native index
loading, including decoding/validation. The retained cold-query dependency
record gives a fresh-output continuation for 1,000 observations per boundary;
resolve the demonstrated OKX initialization cost before that expensive run.
Filesystem-cache state is uncontrolled, and actual multi-day populated native
history remains unavailable. Earlier warm qualification retains its original
history scope only.

Checkpoint timing still has two actual committed observations/account initially
and zero new committed observations in recovery. Acknowledged rejected requests
and 21 selected books are not additional committed checkpoints. The current
finite economic workload cannot supply 1,000 per-account committed observations
without a separate workload/authority decision. Darwin physical read/write byte
counters are unsupported; logical file bytes, occupied storage and fsync durations
are reported separately and never relabeled as physical I/O or a runtime failure.

The v3 consumer initial run passed all 1,920 feature retrievals, independent
economics and existing measurement/topology gates. Its grants expired before
recovery launch; no recovery was attempted under expired authority. The unchanged
v3 consumers are frozen for `closure-features-v4`, using fresh ordinary one-hour
grants and the same predeclared initial-plus-17 recovery schedule. The initial
run remains excluded from recovery materialization/CPU aggregates. The driver
stops on first failure or insufficient original grant headroom; no grant,
service lifetime, threshold, source or risk limit is extended.

The v4 initial and first recovery passed. The second recovery retained nine
Bitfinex ETH missing feature versions and 72 non-ready lookups. Exact native
lineage shows sequence-only heartbeats, not durable I/O loss: the generic book
registry erased a legal unchanged-market boundary. The v5 consumer reuses the
existing causal native decision source, preserves the prior market clock, and
refreshes the retained prefix at each publication. All nine retained prefixes
now admit the original genuine market update; 63 affected tests and strict
static checks pass. This change renews the entire homogeneous initial-plus-17
recovery cohort. No v1–v4 materialization or CPU rows enter v5 aggregates. Two
independently owned public collectors are waiting for their fixed future start
during v5; no market acquisition, builds or other qualification run concurrently.
The existing runtime limits and one-hour grants remain unchanged.

### Next bounded continuation after this closure

Read the current runtime/research capacity summaries and durable acquisition
record. Keep candidate-10's signed qualification and the passing feature
intervals within their exact measured scope. While the fixed public collection
waits or runs, resolve the measured full-index cold depth initialization cost
using the populated-history diagnostic, then renew application-cold/warm
proofs with 1,000 observations per boundary/cache class. Treat a controlled
filesystem-cold protocol as separate evidence. The current paper workload
yields only two committed checkpoints/account; identify a compatible finite
workload/authority decision before checkpoint percentile sampling. Healthy
Bitfinex public operation needs a specific source-envelope decision or an actual
qualifying lower rate, plus fresh signed releases covering the
[2026-09-29 reattribution](#reattribution-and-harness-corrections-2026-09-29); retain the previous one-sided case as reattributed evidence.

At acquisition completion, follow the exact R1 continuation in
[research capacity](research-capacity.md#armed-acquisition-and-continuation).
Do not extend the acquisition deadline, paper service lifetimes, grants or risk
limits. Keep sustained stage 2—longer service handoff, extended finite grants,
24-hour integrated operation, 72-hour runtime retention, seven-day telemetry
and 4x replay—as a separate milestone.

### Final bounded feature outcome and stop decision

The v5 initial interval and four recovery intervals passed all 1,920 ready
feature lookups each, exact offline/online parity, source/selection identity,
existing receipt/BBO and warm-query gates, topology and economic preservation.
The initial interval remains separate. The fifth recovery returned all 1,920
lookups ready with exact parity, but response p95/p99 was **106/207 ms**, exceeding
75/200 ms; the attempt remains a measured latency failure. Both Bitfinex books
had 60 version observations but only 59 distinct native input positions. These
are not admitted as 60 independent durable materialization observations.

Only four recovery intervals qualified: **240 materializations/source and 236
CPU deltas**, insufficient for the required percentile claims. The fifth sampler
retained 58 rows, missing seconds 23 and 26 after observed process-discovery and
occupied-disk scans exceeded one second at seconds 22 and 25. No rows are
invented and no CPU percentile failure is inferred from missing measurements.
Persistent service-request files grew across recoveries; per-trial dashboard
telemetry did not grow. Their scan cost and broader
scheduling/store contention are observed, but a single causal bottleneck is
not established. Native admission already runs outside the publication lock.
Only 18 of 213 responses above 75 ms overlapped the inferred same-source
publisher window, so a producer-lock-only explanation is unsupported.

After the user identified repeated qualification attempts as a loop, further
signed runs and implementation expansion stopped. The final v5 consumer is
retained with its passing checks and failed fifth interval. The remaining bounded
dependency is a focused contention/sampler diagnosis with a concrete correction
and adequate predeclared sampling before another signed run—not another full
cohort retry. `logs/capacity-closure/feature-partial-final.json` holds compact
per-interval results and exact retained-report hashes. Integrated feature
capacity, materialization p99 and CPU p95 are **not fully qualified**.

Final local validation on September 29: `make check` passed all static, typing,
governance, dependency/security and installed-wheel smoke checks, with **1,987
tests passed, two optional skips and three performance deselections**. The
separate `make performance-test` passed all three tests. No hosted CI ran. All
observed paper-trial processes exited and all four accounts stopped. The
[canonical evidence](runtime-capacity-evidence.json) appends this closure without
changing any historical evidence value; bulk records stay outside Git.

Candidate-10's signed implementation and financial/runtime algorithms remain
unchanged. Additive collector lineage and public-run paths preserve legacy
serialized identities; affected capture/publication/replay regressions and the
final installed real sample cover those changes. The new feature consumer's
passing and failing loaded intervals are separately retained. Existing protection,
processing, native/economic parity and recovery evidence is reused only within
its original scope, not promoted to full feature or sustained acceptance.

### Reattribution and harness corrections (2026-09-29)

Recorded after the stop decision above. No signed run, grant, budget, target or
historical value changes; every earlier result keeps its original scope.

**Bitfinex one-sided fault.** The `public_input_invalid` control retained on the
requalification-5 public Bitfinex ETH route was not a one-sided market. R0 at
length 25 sends one WebSocket message per order change. By source position 275
a sweep had removed all 25 visible bids as separate deletions; four ask deletions
followed, then Bitfinex's refill inserts restored a bid 0.169 ms of receipt time
later and all 25 bids within about one millisecond. The same journal holds two more
such episodes (positions 334–340 and 869–877, 0.258 and 0.320 ms); none was
crossed. Other retained public ETH journals dip to 5 and 10 visible bids. The
observer evaluated every intermediate message and treated the first unpriceable
book as invalid input.

`SharedPaperCaptureObserver` now treats a valid (`degraded`) snapshot or update
whose visible book is one-sided or crossed, and the heartbeats or controls that
follow it, as having no eligible market. It faults only when the delivery clock
exceeds the last eligible market by more than the smaller of source freshness and
capture idle time, the tolerance already applied at a finite session end. Gaps,
session loss, stale or invalid rows and other ineligible books still fault
immediately. The rule reads retained delivery clocks, so replay stays deterministic.
Regressions cover transient one-sided and crossed rows, a persistent one-sided book
reaching a stale heartbeat, and a gap during an episode.

Replaying the retained 1,162 deliveries through the corrected observer leaves the
account unblocked. Its economic facts hash, `c05bc64a…`, equals the original
protection replay's, so only the protection decision changes. The compact record
is `logs/runtime-capacity/bounded-evidence/bitfinex-one-sided-reattribution.json`.
The earlier `latency-query-10/one_sided_replay.py` asserts the old fault and now
fails by design; it remains evidence of the previous rule, not a requirement for
later candidates.

This correction changes installed runtime bytes, which candidate-10's signed
releases do not cover. Fresh Bitfinex public health still needs new signed
releases and a new public trial; the 5,000-message ETH source-envelope decision
remains open.

**Collector receiver failure.** A receipt task that raised an exception outside
the handled transport errors ended without its terminal `session_end`. The durable
consumer could then wait indefinitely, including a finite rollover collection past
its fixed stop. Receipt now ends such a session with `receiver_failed_unknown_loss`,
retained as an ordinary visible gap before the existing bounded reconnect or run
end. Regressions cover failure before and after the first snapshot. Running and
retained collections keep their original implementation identities.

**Resource sampler.** The two missing fifth-recovery slots came mainly from
whole-host process discovery (0.823 and 0.704 seconds at slots 22 and 25, against
about 0.06 seconds typically); disk scans took 0.194 and 0.430 seconds. The
consumer sampler now refreshes process-tree membership every five seconds or after
a tracked process exits, reads CPU/RSS counters for every tracked process each
second and retains `process_tree_age_seconds` per sample. The occupied-disk walk
stays one-second and uses one directory scan per entry. A process started less
than five seconds before a sample may be absent until the next refresh. The
retained 58-row interval is unchanged.

**Account journal growth.** Each account journal is one JSON document rewritten
on every commit; after the v5 cohort it held 1.87 MB, and at the stage-2 selection
rate it would reach roughly 300 MB per account per day. A separate commit now
encodes only changed fields and history items, cutting the median commit on that
journal from 27.0 to 9.3 ms with byte-identical stored bytes, but whole-document
writes and full cold decode remain. The
[account journal history record](account-journal-history.md) moves the growing history into
indexed tables; its storage qualification and a fresh signed stage-1 cohort passed on
2026-09-29, and stage 2 remains separate.

Local validation: format, lint, strict typing, stubtest and engineering checks
passed; `make test` passed 1,991 tests with two optional skips and three
performance deselections. Three alert-socket tests first failed only because the
session's temporary path exceeded the Unix socket path limit and passed with a
short base directory. No hosted CI or signed run occurred.

### Stage-1 residual decisions and declaration (2026-09-29)

The owner decided the three remaining stage-1 gaps after their costs were reported.

1. **Cold depth/BBO query: durable as-of index.** A cold reader decoded and validated
   every retained full book to rebuild its touch index: 1.35 ms per OKX row, so 4.0–4.1 s
   for about 100 s of history and linear in history length. The shared paper service now
   writes a [`BookAsOfIndex`](../../src/market_data/books/as_of.py) beside each delivery
   log. After a delivery's bytes are fsynced, it appends that boundary's validated quote,
   the market it carries and its byte range. A lookup equals a
   [`BookRegistry`](../../src/market_data/books/registry.py) lookup that kept every
   boundary, and depth decodes only the selected delivery with full validation. The
   index is derived, so it commits without an fsync; a crash can leave it behind the log,
   and the reader reports the unindexed suffix as partial coverage. The live feature
   path keeps its incremental in-memory registry.
2. **Checkpoint percentiles: deferred to stage 2.** A 60-second trial acknowledges 21
   durable checkpoints per account but commits only two (the rest are persisted
   rejections), so 1,000 committed observations per account cannot be reached within
   stage-1 service lives and unchanged 80-order grants. A 24-hour stage-2 run supplies
   them without an authority change; the boundary stays unmeasured for stage 1.
3. **Public Bitfinex capture cap: 12,000 messages per 100-second capture.** Fresh public
   Bitfinex ETH (R0, 25 levels) sent 84.3 messages/s and reached the 5,000-message cap
   after 59.3 s. Only Bitfinex sources of a public Bitfinex route receive the new cap,
   42% above the observed rate; bytes stay far below 32 MiB. Fixture routes keep 5,000.

**Declared cohort.** Declared before any build or trial. The candidate is the source at
the commit adding this section, frozen by hash, with drivers and evidence under ignored
`logs/runtime-capacity/stage1-residual/`, ported from the
[account journal stage-1 drivers](account-journal-history.md#signed-stage-1-declaration-2026-09-29).
Four signed `paper` targets with `account-runtime-v1` configuration and
`account-journal-v4` state, built by the ephemeral local builder key with a new
seven-day policy trusting only it; fresh journals, disabled deployments and ordinary
one-hour grants; no grant, lifetime, budget or risk limit changes. Each step runs once
and the cohort stops at the first failure.

1. Freeze; fetch, build, verify and install the four targets.
2. Steady fixture trial with the unchanged stage-1 shape and gates, then economic parity.
3. Recovery trial with preservation, all-eight progress, the same gates and the
   independent recovery-suffix parity.
4. Loaded-fault trial on separately installed targets of the same releases.
5. Populated-history queries on the new steady trial:
   [`capacity_history_queries.py`](../../tests/integration/consumers/runtime/capacity_history_queries.py)
   with 250 samples per reader, giving 1,000 per boundary and cache class. Pass requires
   no failed request, matched-cutoff parity, and `pass` for both service and scheduled
   response latency in all four classes against the budgets above: depth/BBO cold p99
   2 s and warm 50/200/500 ms, dashboard cold p99 3 s and warm 100/400/1,000 ms.
   Filesystem-cold stays unmeasured.
6. Public Bitfinex route trial on separately installed targets with the 12,000 cap.
   Pass requires the trial to pass with health covering its 60-second measured interval;
   each public Bitfinex capture to end without a message, byte or frame cap and with
   complete native delivery parity for its account and bounded queues; and the fixture
   OKX sources to meet their unchanged source gates. Public latency samples are reported,
   not graded.
7. Cleanup audit over every trial, with all four accounts stopped.
8. `make check` on the unchanged frozen source.

Checkpoint percentiles, filesystem-cold queries, renewed public OKX health, integrated
feature serving and stage 2 are outside this cohort.

#### Residual cohort result (2026-09-29)

The cohort at declaration commit `20d5b27`, installed implementation `51063b91…`,
stopped at step 5; the compact record is `stage1_residual` in the
[canonical evidence](runtime-capacity-evidence.json).

- **Requalification of the changed runtime passed.** Steady (60.003 s, 121 health
  witnesses) and recovery (60.001 s, 122 witnesses) met every unchanged gate, with
  durable-to-BBO p99 of 31–50 ms and steady query response p99 of 29–34 ms for depth/BBO
  and 112 ms for dashboards. Steady economic parity, recovery preservation (first
  replacement claim to all-eight progress 7.66 s against 40 s), the independent
  recovery-suffix parity and the loaded-fault trial all passed.
- **Cold depth/BBO now meets its target.** All 1,000 application-cold depth/BBO queries
  on the durable index succeeded: p50 7.44 ms, p95 13.60 ms, p99 21.82 ms, maximum
  36.92 ms, against 2 s at p99 and the earlier 4.0–4.1 s. The consumer's summary was not
  written; these nearest-rank values come from its retained 1,000 samples.
- **Step 5 stopped on a harness defect.** The history-query consumer waits 30 s for its
  dashboard reader processes after the depth workers finish. Depth used to take about
  1,000 s and now takes about 50 s, while 250 serial application-cold dashboard requests
  at about 0.73 s need about 190 s. The four readers were terminated after 107–109
  requests each; every completed request succeeded, the slowest in 0.956 s against the
  3 s cold budget. Dashboard cold and both warm classes are therefore unmeasured, not
  failed.

As declared, no step was retried, so the public Bitfinex route, the cleanup audit step
and `make check` did not run. A read-only cleanup audit run afterwards found every
observed process absent and all four accounts stopped in each completed trial. A new
measurement needs a corrected consumer and a fresh declaration.

