# MR15 runtime capacity profile

Owner: quant development. Status: **stage-1 probes and consumers implemented;
bounded characterization failed unchanged targets; no runtime capacity accepted**. Updated 2026-09-28 (Singapore; observations use UTC)
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

### Validation of the delivered state

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
