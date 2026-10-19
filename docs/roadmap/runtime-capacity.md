# Runtime capacity

Owner: quant development. Status: **open.** The baseline and sustained runs are
qualified. The counted day attempt `day-counted-2` failed on 2026-10-12
([failed attempts](#failed-attempts)). The counted day run, its 4× replay and its
72-hour retention remain, on the frozen final candidate and the
[declared day-run host](#day-run-host-checklist)
([remaining work](overview.md#remaining-work-before-qr-onboarding)).

This record holds the integrated paper/shadow capacity targets, the accepted results
and the declaration of the day run. The
[runtime design](../architecture/runtime-and-operations-design.md#scaling-triggers-and-technology-choices)
owns the scaling decision; [research capacity](research-capacity.md) is separate.

This profile remains required for full integrated paper qualification and G5.
[Bounded offline research](overview.md#bounded-offline-research) may proceed on
validated data and workflows while it is open. The counted 24-hour run, 4× replay,
72-hour retention check, budgets and quiet-host rules remain unchanged. The
retention interval requires preserving the artifacts and checking them later;
it does not require running the paper services for another 72 hours.

The targets are engineering capacity targets for public-input paper operation. They are
not trading limits, exchange fill claims or live-capital authority. A revised target
needs a dated rationale before the affected run, and the earlier target and its failure
are kept. An installed artifact, a short public observation and a replayed load are
different evidence classes.

## Launch workload

**Host.** Every result records the exact OS, interpreter, CPU and RAM, disk and
filesystem, free space, power state, competing work, cache state, artifact digests and
input identities.
- Development host: Apple M1 Max, 10 cores, 64 GiB RAM, macOS 27 arm64, local SSD.
- Day-run host: the development host, declared on 2026-10-12 with the owner's iCloud
  waiver ([checklist](#day-run-host-checklist)). It needs at least 512 GiB free at the
  start.
- No distributed service, broker or columnar database is mandated. A replacement is
  chosen only after a measured bottleneck and a parity and rollback analysis.

**Topology.**
- Four native spot book sources: OKX BTC/USDT and ETH/USDT at `books` depth 400, and
  Bitfinex BTC/USD and ETH/USD at `R0` depth 25.
- Four separately signed account owners: shared and isolated accounts for each venue.
- Eight active strategy instances, two per account.
- USD and USDT stay separate currencies and journals. A consolidated BBO combines only
  explicitly equivalent instruments, and shows partial coverage rather than inferring
  USD/USDT FX.

| Measure | Target |
| --- | --- |
| Native receipt | At least 7,000,000 messages across the four sources in 24 hours, with no source below 20% of the total. The capacity input supplies 25 messages a second a source, and 100 a second for 10 seconds every five minutes: 2,376,000 a source and 9,504,000 a day. Socket messages count, including control records; valid books, invalids, duplicates, gaps and selected economic books are counted separately |
| Bytes and bursts | Encoded durable records average at most 4 KiB, with p99 frame size at most 32 KiB and a hard single-frame ceiling of 8 MB. The 4× 10-second burst preserves order without unknown loss |
| Capture segments and queue | 30-minute segments: 75,000 messages, 256 MiB, 8 MB frames, a 2,048-record queue. Queue oldest age at most 2 s, peak occupancy at most 1,024 records a source, and no limit ends a required interval early |
| Books and decisions | Every admitted native message is validated and reconstructed at the configured depth, with exact L3 quantities, per-venue BBO, provenance, revisions, clock quality and as-of eligibility. The three-second selected-book cadence is part of the signed input identity. At most 40 physical paper orders an account a day, inside an 80-order grant with a 100-unit-per-instrument buy cap |
| Features and reads | Two versioned feature values per instrument at a one-second cadence. Eight concurrent instance lookups with a five-second TTL; a stale or missing feature is an explicit decision outcome. Exact offline/online parity at matched cutoffs |
| Retention and disk | 72 hours of replayable native records and every economic revision and control event, and seven days of telemetry. Occupied-space ceilings: 160 GiB raw capture, 120 GiB canonical data, 32 GiB features and telemetry, 8 GiB scratch (320 GiB in all). The telemetry store holds at most eight million events with an age bound |
| Replay and resources | Replay the 24-hour corpus at at least 4× recorded time, within six hours, with identical source, selection, feature, decision, order, fill, fee, cash, position and checkpoint identities. During the day, total RSS at most 24 GiB, mean CPU at most 7 cores and p95 at most 9; disk bytes written and fsync cost are reported |

The capacity input is a venue-conformant native-message fixture with snapshot,
incremental, heartbeat, reconnect and adverse-size periods. Public routes prove live
input compatibility only at their observed rate; replayed load proves only the local
processing envelope. A process restart is a declared gap that needs a fresh snapshot,
never continuity.

## Latency and query budgets

Intervals use monotonic receipt-to-durable and durable-to-derived clocks; exchange
clocks are never subtracted. Percentiles are nearest-rank, with at least 1,000
observations per boundary and cache class. A warm percentile cannot qualify a cold
target. Steady readers: eight feature readers at four lookups a second, four depth and
four dashboard readers at five queries a second.

| Boundary | p50 / p95 / p99 | Condition |
| --- | --- | --- |
| Socket receipt to fsynced capture cursor | 50 / 250 / 1,000 ms | Four sources at base and burst rates; zero unknown loss |
| Durable book to per-venue and consolidated BBO | 20 / 100 / 500 ms | Native depth and every revision; no stale, different-currency or later quote enters an earlier cutoff |
| Selected book to committed checkpoint | 250 / 750 / 2,000 ms | Three-second selection, eight instances, account serialization, exact attribution |
| Online feature retrieval | 20 / 75 / 200 ms | Eight concurrent readers of two values, five-second TTL; durable book to available materialization at most 2 s at p99 |
| As-of depth/BBO query | 50 / 200 / 500 ms warm; 2 s cold at p99 | Four readers, one instrument and cutoff, up to 25 Bitfinex or 100 OKX levels |
| Dashboard query | 100 / 400 / 1,000 ms warm; 3 s cold at p99 | Four readers, one-hour window, at most 10,000 events a query |

Protective targets under load: a policy, source or account process death stops
dependent work within 2 s; a restarted source is usable within 8 s; a request-retention
failure is fenced within 6 s; every selected instance progresses within 40 s of the
first replacement claim. No uncertain account response is retried automatically.

A latency failure never relaxes freshness, TTL, quote-age or risk checks. A fast result
after dropping revisions fails.

## Accepted results

| Run | Scope | Result | Evidence |
| --- | --- | --- | --- |
| Baseline latency and warm queries | Four sources, four owners, eight instances; 60 s steady and replacement-owner recovery | Every receipt, BBO and warm-query percentile passed; native and economic parity; recovery within budget | `logs/runtime-capacity/latency-query-10/` |
| Baseline dashboard and Bitfinex route | Populated-history queries; public Bitfinex route | Depth/BBO and dashboard, warm and application-cold, inside budget (warm dashboard p99 111.6 ms) | `logs/runtime-capacity/stage1-dashboard-2/` |
| Baseline public OKX route | 60 s public OKX route | 44/44 gates; observed rate under 9 Hz, so it does not qualify the authored load | `logs/runtime-capacity/public-okx/` |
| Baseline filesystem-cold queries | Depth/BBO and dashboard over non-resident files | p99 14.7 ms and 229.4 ms against the 2 s and 3 s budgets | `logs/runtime-capacity/filesystem-cold/` |
| Baseline feature serving | One materializer, one reader per account, 17 chained recoveries | Every gate passed; durable-to-available p99 at most 221 ms | `logs/runtime-capacity/features-cohort/` |
| Sustained (counted 2026-10-03) | About 50 minutes under one-hour grants: segment rollover in signed capture, an order-light mix, an injected owner death and four-owner recovery | Every latency target in every 300 s window; recovery progressed in 11.06 s | `logs/runtime-capacity/stage2a-counted/` |
| Grant denial (2026-10-06) | Signed 26-hour grant form: a 10-minute grant after expiry, and a revoked 26-hour grant | New exposure and claims refused; protective stops applied; neither grant renewed | `~/AlphaResearchEvidence.noindex/runtime-capacity/stage2b-denial-2` |

Every result above was measured while the shared paper observer matched only the
grid-selected books: the first eligible book at or after each crossing or decision.
Shared paper now matches every eligible priced book (step 2 of the paper remediation
plan, `logs/audits/2026-10-08-paper-orders-accounts-recovery-remediation-plan.md`),
which raises matching and account-transaction frequency. These results remain evidence
for their own revisions, not for the current per-book path, which that plan's step 3
measures; the budgets are unchanged. In this profile a "selected" book is one that
decides a three-second grid instant; the per-book `market_selected` measurement now
equals `market_eligible`, so selected economic books are the deciding books.

**Step-3 development diagnostics (uncounted, 2026-10-09, not results).** One 300 s
interval of the sustained input, including one 10 s burst at 100 messages a second a
source, on the development host; then a synthetic day of account history.
- **Per-book path.** A matched book is one fenced account command that resolves the
  market identity, matches and observes the ask in one transaction: about 2.8 ms of
  service time and 4 ms round trip at p50, against three requests and 25 ms before.
  Every source took the burst at 100 books a second without a backlog, and no
  account faulted. Receipt to durable (p99 2.4 ms) and durable to BBO (p99 28 ms)
  passed; selected book to checkpoint (at most 63 ms) needs 1,000 checkpoints, more
  than 300 s gives, so it stays unmeasured.
- **Account journals** grew about 39 MB an account in 300 s (2.6 KB a trace), an
  estimated 11 GB an account-day. `capacity_retention.py` reports them per account as
  their own class; no ceiling names them, so they are not graded.
- **A day of history** (2.2 million traces an account). Monitoring, facts and the
  full inspection (which now states the trace history's count and hash chain) take
  10–13 ms; full verification 21 s and the trace export 7 s, in bounded memory.
  Account backup (87 s) and restore (83 s) of the 10 GB journal exceeded the 30 s the
  installed account adapter waited. By owner decision the adapter now waits 300 s for
  backup and restore only, within the signed launcher's own bound. Through the adapter
  and launcher the same journal backed up in 87.0 s and restored in 83.1 s, verified
  and quarantined. 300 s does not qualify a larger journal. The existing D-b trace-commit target
  (p99 at most 5 ms) passed on this host at 2.96 ms (`qualified: true`).
- **Retained scratch bytes.** About 28 MB a 300 s interval (492 MB before step 3),
  an estimated 7.2 GiB a day: 89 % of the 8 GiB scratch ceiling, so within it but
  above the 80 % investigation threshold, with the cost attributed. Request logs keep
  each request's bytes once (the client keeps their SHA-256 and length) and an exact
  repeated result once; protection reads omit the ledger, which grows with every
  fill; the trial's timing copies are compressed. The owner services' request logs,
  about 14 MB an account an interval, stay beside the journals.
- **Shared delivery logs (found by the day-run rehearsal, 2026-10-09).** Every
  eligible book was retained with its full reconstructed depth: about 32 KB a line
  at OKX depth 400. Both OKX accounts reached the log's bound (four times the 1 GiB
  rehearsal chain) after 81 minutes and faulted. The 300 s diagnostic stayed far below
  it, and these canonical-class files were outside the scratch projection. Each line
  now holds the book row as a checksummed zstd frame. On the rehearsal's books a line
  averages 2,591 bytes at OKX and 1,060 at Bitfinex: an estimated 5.8 and 2.4 GiB a
  source-day, within the counted chain's 16 GiB bound and the 120 GiB canonical
  ceiling. The rehearsal is repeated before the counted run.

## Failed attempts

A failed counted attempt is kept as it ended. Diagnostics on its data never regrade it.

**`day-counted-2` (2026-10-11 to 2026-10-12): failed.**
- Candidate 72a74e3 (#120) on the development host, with the owner's recorded iCloud
  waiver (`icloud_criterion: waived_by_owner`). Launched 01:22:11 GMT+8 on 11 October
  after a 300 s preflight (idle 0.26 cores); the measured day ran from 01:30 on
  11 October to 01:30 on 12 October.
- The day step failed at 06:18:43 GMT+8 on 12 October. 19 of its 20 gates passed: the
  trial, fixture slots, native delivery parity, segment rollover, every latency window
  (receipt to durable, durable to BBO, feature durable to available, feature
  retrieval, dashboard and depth/BBO reads), complete reads, checkpoints without
  rejection, committed checkpoints and checkpoint percentiles per account,
  reconciliation cadence, orders (opening only, within the grant and the daily target)
  and receipt volume (9,504,484 messages, 25% a source).
  `recordings_complete_with_replay_parity` failed: every source's `replay_parity` was
  false. The cleanup audit passed. The host gate, the resource gate and the 4×
  economic replay did not run.
- Cause, confirmed by regression tests: no source retained `source-result.json`. All
  four sources sealed their chains and wrote `run-summary.json` within the same second
  of the stop (01:30:09), then replayed the whole chain before writing the result. A
  day chain takes 33 s (Bitfinex) to 78 s (OKX) to replay; the supervisor's drain gives
  a stopping source up to 10 s and then terminated all four (its shutdown ended at
  01:30:18 to 01:30:19). The counted sustained run's 50-minute chains replayed inside
  that budget. Two regressions fail on 72a74e3 and pass on the fix: an in-process stop
  whose chain replay raises, and a spawned source under the real supervisor shutdown
  whose replay outlasts the drain.
- Fix: a source's stop only seals. `source-result.json` keeps the live summary with
  verification pending and no parity claim; `alpha-execute source-verification`
  replays the capture explicitly after the run and retains `source-verification.json`
  bound to that result; the recordings gate reads parity only from that record
  ([paper application](../packages/paper-application.md)).
- Diagnostics on the preserved data (not counted): the unchanged `SavedCaptureRun`
  verified all four chains (complete, terminal, within limits, every summary field
  equal) in 33.1 to 77.5 s. With each source's sealed result reconstructed from its
  `run-summary.json`, `source-verification` verified all four in 78.6 s in parallel and
  refused a summary mismatch, one corrupted segment byte and a chain without its final
  summary.
- Storage at the end of the day (diagnostic, not a retention result): raw capture
  2.02 GiB of 160; canonical 28.5 of 120; features and telemetry 25.6 of 32; scratch
  7.07 of 8 (88%, above the 80% investigation threshold); account journals 56.8 GiB,
  about 14.2 an account, ungraded; the whole attempt 120.6 GiB. Telemetry held 821,878
  events, 5.75 million projected over 7 days against 8,000,000. Each delivery log
  matched its estimate (5.74 GiB an OKX book, 2.36 a Bitfinex book); each delivery
  index held 3.08 GiB.
- Separate findings, not fixed with this cause: account-journal growth (each per-book
  paper trace repeats its quote and the unchanged scenario, under four indexes), the
  delivery index (larger than the Bitfinex log), grading time (about 2 h 35 min
  after the trial ended, almost all of it collecting `results.json`), and the
  supervisor's own source-completeness verdict (`source_delivery_incomplete`), which no
  cohort gate graded (review finding; it predates this attempt; graded from the commit
  after a939db5 by `supervisor_source_delivery_complete`).
- Evidence: `~/AlphaResearchEvidence.noindex/runtime-capacity/day-counted-2/` (also
  `logs/runtime-capacity/day-counted-2/`), with `PRESERVATION.md`. Its bulk data (output,
  layout and socket base, with the journals and request timings) was removed by the
  owner's cleanup on 2026-10-12; `kept-records/` keeps the gate assessment, summary, step
  log and chain verification. The diagnostics folder (`day-counted-2-diagnostic/`) was removed
  in the same cleanup; its chain verification is kept in `kept-records/`.

## Uncounted integration checks

These checks qualify the source shutdown and verification path for the next counted day
attempt. They do not replace the day's resource gate, its 4× economic replay or its
72-hour retention, and they change nothing about `day-counted-2`, which stays failed.

Candidate `d91d7cd` (merge of #122, installed identity `1e938579…4abf`), prepared at
`~/AlphaResearchCandidates/d91d7cd/` and run on the development host on 2026-10-12 with
the owner's recorded iCloud waiver; every other limit unchanged.

| Check | Result | Evidence |
| --- | --- | --- |
| `sustained-integration-1`: `--stage sustained`, signed launch, two phases with the injected owner death and four-owner recovery, explicit shutdown | Passed: every step; phase A 19/19 gates, phase B 18/18; both cleanup audits; host gate. Sources sealed in the stop's second; 8/8 explicit verifications passed (exit 0). `supervisor_source_delivery_complete` excepted only the declared, fenced (0.117 s) owner's feed, an exact prefix; phase B complete with no failure events | `~/AlphaResearchEvidence.noindex/runtime-capacity/sustained-integration-1/` |
| `natural-expiry-2`: one 300 s sustained-profile trial whose supervisor reached its own 360 s life with no shutdown request (diagnostic driver over the unchanged consumers) | Passed: 7/7 gates; supervisor exit 0 at life end; all four sources sealed (`supervisor_stop`) within 24 ms, inside the end-of-life drain reserve; supervisor accounting complete; 4/4 explicit verifications passed; cleanup audit and host gate passed | `~/AlphaResearchEvidence.noindex/runtime-capacity/natural-expiry-2/`, driver in `natural-expiry-tools/` |
| `natural-expiry-1` | Failed on a defect in the diagnostic driver (spawned children re-ran its argument parsing), not the product; fixed and rerun as `natural-expiry-2` | `~/AlphaResearchEvidence.noindex/runtime-capacity/natural-expiry-1/` |

Remaining before QR onboarding: the counted day run on the frozen final candidate, which
will very likely supersede `d91d7cd`, with its resource gate and 4× replay, and its
72-hour retention, at an owner-booked slot.

## Storage efficiency measurements

Uncounted developer measurements on the development host, 2026-10-13, of the storage
changes made after `day-counted-2`'s separate findings; they change no target, budget,
ceiling or gate, and `day-counted-2` stays failed. Inputs are read-only copies of
`sustained-integration-1`'s retained journal, delivery indexes and phase-A evidence;
baseline `c1d9c0b`. Record, tools and raw results:
`~/AlphaResearchEvidence.noindex/runtime-capacity/storage-efficiency-1/`.

| Change | Measured on the same inputs | Equivalence |
| --- | --- | --- |
| Account journal: each paper trace is a zstd frame against the journal's first trace; the market index is dropped (the unique key leads with the market) | 65,519 real traces: 4,432 → 513 bytes a trace (−88 %); commit p50 183 → 173 µs; verify 0.71 → 0.63 s; export 0.22 → 0.36 s | Export byte-identical; hash chain over the same bytes |
| Delivery index: a carried market is stored as its boundary's position; boundaries are frames against the first market; lookups binary-search the position key | 49,604 OKX / 49,602 Bitfinex rows: 1,391 → 153 / 151 bytes a row (−89 %); lookup p50 351 → 369 µs | 4,002 lookups each identical; covered bytes equal |
| `results.json` collection: one process per source; streamed rows, records and digests; no second validation of a decoded delivery | 198,399 deliveries: 188 → 78 s; peak RSS 742 MiB → at most 116 MiB a process | Output byte-identical |

At day size (`account_history_capacity.py`, 2,376,000 traces, whose synthetic traces
overstate compression, so read it for time): journal 10.77 → 1.41 GB, verify 22.3 →
21.8 s, export 7.7 → 11.9 s, account backup 91 → 51 s, restore 85 → 67 s, trace commit
p99 2.30 → 0.39 ms, retry lookup p99 625 → 729 µs.

Storage by category, per book and per account (one bound book source). Bytes a book
are measured on `sustained-integration-1`'s retained okx-shared account (65,518 books)
before, and by replaying its traces after; day values multiply by the declared
2,376,000 books and are projections, not observations:

| Category | Before, bytes a book | After, bytes a book | Before, GiB a day | After, GiB a day |
| --- | --- | --- | --- | --- |
| Trace table and indexes | 4,431 measured | 513 measured | 9.81 | 1.14 |
| Complete account journal | 4,706 measured | 788 (traces measured, other history assumed unchanged at 275) | 10.41 | 1.74 |
| Owner-service request logs | 1,730 measured | unchanged | 3.83 | 3.83 |
| Account state (`target-<account>/state`: journal and request logs) | 6,436 | 2,518 | 14.24 | 5.57 |

`day-counted-2` observed 14.2 GiB of account state an account, the same category: the
method reproduces it from the baseline bytes, so 5.57 GiB is the comparable
projection. A delivery index projects to about 0.34 GiB a source-day against the 3.08
observed, and collection to about 62 minutes against about 2 h 35 min.

Still open:
- the owner-service request logs, now the largest account-state class: their exact
  bytes are the operator's lookup by SHA-256, so a compact form is a procedure change;
- collection's remaining cost: the shared delivery decoder validates each full book
  three times;
- device writes, real-market framing (the fixture books repeat few prices), and the
  account-journal and request-log storage classes, which no ceiling names.

*Reconciled with D2 (`storage-efficiency-2`, uncounted, 2026-10-13).* D2 was rebased
onto these changes; its per-row trace frame was removed in favour of the reference frame.
On the reconciled tree:
- the same 65,519 real traces take 513 bytes a book with an identical export, as before;
- D2's real-path anchor (`d2-grading-tools/fixture.py anchor`, 90 minutes of day input,
  four accounts, 147,014 books each) writes 159.8–167.3 MB a journal against 283.4–288.1
  MB on the D2 tree with per-row frames (`d2-grading-2`), with identical commit and
  arrival outcomes; `verify_anchor.py` passed. Checkpointed, the okx-shared journal holds
  1,058 bytes a book: 513 for traces and their indexes, 535 for D2's decision and batch
  rows, 10 other;
- at day size (`account_history_capacity.py`, synthetic): journal 1.41 GB, verify 21.5 s,
  export 11.9 s, backup 51 s, restore 66 s, trace commit p99 0.43 ms.

Projected to the declared day (2,376,000 books an account; not observations):

| Category | Bytes a book | GiB a day | Basis |
| --- | --- | --- | --- |
| Trace table and indexes | 513 | 1.14 | measured on the reconciled tree |
| D2 decision and batch rows | 535 | 1.18 | measured (anchor) |
| Complete account journal | 1,058 | 2.34 | measured (anchor, checkpointed) |
| Owner-service request logs | about 1,730 | about 3.85 | measured before D2 on signed services; D2's quiet advances add about 19 MB a day; not remeasured on the reconciled tree |
| Account state | about 2,790 | about 6.2 | sum; compare with the 14.2 GiB observed in `day-counted-2` |

The next candidate contains these changes, so its 2-hour day rehearsal is required
before a counted run.

## Day run

The approved declaration (owner, 2026-10-07). Targets and budgets are the launch
workload's, unchanged and not waived.

**Authority.**
- Per account, new grants in the existing signed form: 80 orders, 100 units per
  instrument, 1,000 notional per order and the installed risk limits.
  - counted run and rehearsals: a 26-hour life;
  - each rehearsal service stops after its 2-hour life.
- Each account configuration declares `service_life_seconds` 90,000, the 25-hour cap.
- The counted run invokes 87,600 s owners and an 87,000 s supervisor; the launcher's
  outer bound is the cap plus 60 s. Rehearsals invoke 8,400 s owners and a 7,800 s
  supervisor.
- No service renews itself, and each refuses a life past its grant's expiry.

**Workload.**
- `DayNativeFixture`: 291 periods of 300 s (87,300 s), 2,400,750 messages a source
  and 9,603,000 in total. `DayRehearsalFixture`: 26 periods.
- The `target_clip` order mix, with paper adverse cost 0 and reconciliation every 60 s.
- Segments: 30 minutes, 75,000 messages, 256 MiB. Counted chain: 2,500,000 messages,
  4 GiB and 50 segments a source. Rehearsal chain: 250,000 messages, 1 GiB and 6
  segments.
- One measured phase with no injected fault: 86,400 s (288 windows) counted, 7,200 s
  (24 windows) for a rehearsal. Readers, samplers, feature processes and reconciliation
  run throughout.
- The telemetry store declares 8,000,000 events and 7 days.

**Gates.**
- Every sustained phase gate:
  - run, inputs, parity and reads;
  - the supervisor's own final source-delivery accounting
    (`supervisor_source_delivery_complete`): every configured feed sealed, retained,
    drained, exited cleanly and delivered every durable record to every configured
    account, with no `source_delivery_incomplete` event. Offline verification never
    stands in for it. Only the sustained profile's phase A excepts the declared,
    fenced owner death, whose feed may end with that owner's exact retained prefix;
  - latency in every 300 s window;
  - checkpoints, reconciliation and orders. Every strategy decision of every selected
    checkpoint in the interval must be admitted (`reserved` or `target_matched`) in
    the stopped account journal, at once or at its own arrival; a pending commit alone
    never passes. Opening orders are counted per admitted decision.
- Checkpoint percentiles: selected book to committed checkpoint at 250/750/2,000 ms over
  the whole counted run, and in every window with at least 1,000 samples. Each account
  needs at least 1,000 committed checkpoints. Rehearsals report this and do not grade
  it.
- Segments: at least 48 a source (counted), with exact chained replay, verified
  explicitly after the day; a source's stop only seals.
- Receipt: at least 7,000,000 messages, no source below 20%.
- Resources: total RSS at most 24 GiB, mean CPU at most 7 cores and p95 at most 9;
  disk written and fsync cost reported.
- Orders: at most 40 an account for the day.
- Quiet host:
  - Before the start, the interactive processes in `INTERACTIVE_PROCESSES` are closed.
  - iCloud Drive is off or paused, unless an owner waiver recorded for that attempt
    covers this one criterion ([day-run host](#day-run-host-checklist)); a waived run
    records it as waived, never as paused or met.
  - `caffeinate` is held.
  - A 5-minute idle check shows non-trial load averaging at most 1 core.
  - During the run, non-trial load above 2 cores for longer than 60 continuous seconds
    fails the attempt, with attribution.

**After the counted run.**
- **4× replay.** The retained chains replay offline through the installed
  reconstruction, the shared paper observer, the account journal and the selected
  policies, at least 4× recorded time (within 6 hours). Every source, selection,
  feature, decision, order, fill, fee, cash, position and checkpoint identity must be
  identical. It runs while retention elapses. Rehearsals replay their own 2-hour corpus.
- **72-hour retention.** At least 72 hours after the day ends:
  - every chain still replays exactly;
  - occupied space is graded against the 160/120/32/8 GiB ceilings;
  - the telemetry store's events are projected to 7 days against 8,000,000.

**Running it.** `capacity_sustained_cohort.py --stage day|day-rehearsal` runs freeze,
candidate, quiet host, grants, the day, cleanup audit, host gate, resource gate and the
economic replay. Within the day step, after the trial, every source recording is
replayed by `alpha-execute source-verification` (in parallel, about 80 s for a day)
before the day's gates read it. `capacity_retention.py` runs the retention check. A counted attempt runs
once and stops at its first failure. It needs an owner-booked slot.

**Gate defect fixed (found and fixed 2026-10-13; exercised only by uncounted developer
diagnostics).** Under
D2 arrival-time admission a paper decision with an entry delay commits as
`arrival_pending` (or `replacement_pending`) and is admitted, or refused, at its
arrival in a separate journal row saved under an identity derived from the decision's
own. `checkpoints_commit_without_rejection` graded only each selected book's
decision-time batch commit and accepted only `committed:reserved` and
`committed:target_matched`, so it failed every valid D2 phase: a focused test on
phase A and B evidence shaped like the profile (every batch `arrival_pending`)
reproduced the failure. Two related gaps had the same cause. `orders_only_at_opening`
counted batch-level `committed:reserved`, which a pending batch never shows, so it
passed vacuously. And a batch commits even when one of its decisions is refused, so a
per-decision refusal was never graded.

The fix:
- Each `paper_book` measurement row of the shared observer now names the journal batch
  identities its delivery committed (`checkpoint_batches`). It is opt-in measurement
  only: trading behaviour and the journal format are unchanged.
- `SustainedResults.decisions` takes each account's batches from the selected books in
  the interval and opens the stopped journal named by `final-<account>.json`
  read-only (`AccountJournal.read_history`). `DecisionAdmissions` resolves every
  decision of those batches, once each, by its own row. A pending decision is resolved
  only by the row under `AccountJournal.arrival_identity`, the owner's rule, so an
  arrival after its checkpoint, or after the interval, stays attributed to that
  decision. A decision of an earlier checkpoint whose arrival falls inside the interval
  is not counted. Another decision's or another account's rows never resolve it.
  Missing batches or rows, unnamed batches, rows that differ from their batch, and
  unreadable evidence are reported, never passed.
- The cutoff is the stopped journal the trial retains after shutdown. There is no grace
  period, and no threshold changed. The next phase reuses the same journal (found by
  `d2-lifecycle-1`, below), so the trial's cleanup also retains the stopped journal's
  committed history digests (`final-<account>.history.json`: decision, batch and trace
  row counts and hash chains, read through `AccountHistory.digests`). A journal is graded
  only while it holds exactly that history and the trace history its final state names;
  otherwise its evidence is unreadable and the gate fails. The graded row counts are kept
  with the decision facts.
- `checkpoints_commit_without_rejection` passes only if both hold for all four
  accounts:
  - every selected batch committed (`reserved`, `target_matched`, `arrival_pending` or
    `replacement_pending`);
  - every decision is admitted, at once or at arrival.

  A refusal, an unresolved arrival, `no_fresh_book_at_arrival`,
  `replaced_before_arrival`, a withdrawal or any missing evidence fails it.
  `orders_only_at_opening` counts decisions admitted with `reserved`, at decision time
  or at arrival. `committed_checkpoints_per_account` still counts batches. The phases,
  the counted day and the rehearsal share this one evaluation (`SustainedGates.phase`).
- The sustained projection now derives arrival identities through
  `AccountJournal.arrival_identity` instead of its own copy of the rule, and can retain
  measurement rows.

Automated verification, 2026-10-13, on the shared-replacement working tree:
- Gate tests on authored evidence: the reproduction, immediate and replacement
  admissions passing, and 19 refusal, unresolved and missing-evidence cases.
- Real account journals, read back through `read_history`:
  - immediate admission;
  - `arrival_pending` admitted at its +1 ms arrival;
  - beta refused at arrival (`order_notional_limit`) in the same batch as alpha's
    admission;
  - `replacement_pending` released by its cancellation at +8 ms and admitted at
    +9 ms;
  - a trailing decision left unresolved;
  - a foreign batch, a foreign account and an exact retry.
- An end-to-end run of one account's minute of the sustained mix through the real
  shared observer, D2 journal and measurement rows. Interval cuts show a decision's
  arrival after the interval still counting for it, and an earlier checkpoint's
  arrival inside the interval not counting.
- Focused suites: `test_capacity_sustained_cohort`, `test_capacity_day`,
  `test_capacity_sustained_results`, `test_capacity_sustained` (the 240-decision
  projection), `test_public_paper` and `test_shared_decisions`: 129 passed, 1
  performance case deselected by the marker filter. Format, lint, strict typing,
  stubtest, engineering standards, architecture, dependency admission and bandit
  pass.

The stopped-journal binding adds a regression on the real path (one more committed book
after the final state, or absent retained digests, fails closed) and an owner test of
`AccountHistory.digests`. Focused suites with it: 202 passed, 3 performance cases
deselected by the marker filter; the same static checks pass.

**Developer diagnostics (uncounted, 2026-10-13).** These ran the uncommitted
shared-replacement working tree, not a frozen candidate. Signed owners were built from a
snapshot of it (HEAD `c1d9c0b` with 55 dirty paths, recorded as `source_dirty`); there was
no quiet-host step, host gate or iCloud attestation. They are neither signed-candidate nor
acceptance evidence. Evidence: `~/AlphaResearchEvidence.noindex/runtime-capacity/`.
Their bulk data (journals, captures, delivery logs) was deleted at the owner's request on
2026-10-13; records, results, verification and measurement rows remain, with a
`CLEANUP-2026-10-13.md` manifest in each folder.
- **Lifecycle** (`d2-lifecycle-1`, `d2-lifecycle-2`; driver `d2-lifecycle-tools/`, run as
  `~/AlphaResearchCandidates/dev-d2-lifecycle-2/ops/launch-d2-lifecycle-2.sh`). It runs the
  shipped cohort steps with 300 s phases: phase A with the declared `bitfinex-isolated`
  death (fenced in 0.56–0.57 s), phase B with the four-owner recovery. The shipped
  `SustainedCohort.phase` graded both phases:
  - Phase A: 18/19 gates. Only `segments_rolled_over` failed, expected at 300 s.
  - Phase B: 18/18 gates.
  - In each phase every account committed 100 batches as `arrival_pending`, and all 200
    decisions were admitted at arrival as `target_matched`.
  - All eight final states, the killed owner's included, are `stopped` and name the
    installed target's journal, as the post-shutdown read does.
  - `d2-lifecycle-1` found that phase B's recovery and trading rewrite all four journals
    phase A's final states name. Phase A was still graded correctly, because it is graded
    before phase B, but a later regrade, or any reordering, would have read the later
    state. In `d2-lifecycle-2`, with the binding, phase A's regrade after phase B fails
    closed for all four accounts.
- **Grading cost** (`d2-grading-1`, corrected real-path reference in `d2-grading-2`;
  tools `d2-grading-tools/`; bounds set before
  generation in its `PLAN.md`, none exceeded). Four accounts, warm cache, fresh process,
  two runs each:

  | Journals | Decisions | Resolver | Gate evaluation | Peak RSS |
  | --- | --- | --- | --- | --- |
  | Real path, 1,800 batches/account | 14,400 | 12.0–13.6 s | 13.4–13.5 s | 66 MiB |
  | Generated, 1,800 batches/account | 14,400 | 11.9–13.3 s | 13.4–13.6 s | 66 MiB |
  | Generated, 7,200 batches/account | 57,600 | 47.5–52.2 s | 53.0–53.4 s | 71 MiB |
  | Generated, 28,800 batches/account (a day) | 230,400 | 191–193 s | 213–214 s | 94 MiB |

  The real path is the projection's shared observer and D2 journal on 90 minutes of day
  input. Generated journals use real account-journal commands templated on it: two
  chained-checkpoint decisions a batch, each resolved at its 1 ms arrival. Gate evaluation
  is the measurement scan, journal resolution and the two gates. Cost is linear at about
  0.83 ms a decision, and the measurement scan takes 11 s a day.

  Generation is measured separately: the real path ran about 6 minutes per 1,800 batches
  per account. Generation through the journal ran at 8.2 ms a batch, and four day-sized
  accounts took 239 s in parallel.

  Generated journals hold no per-book traces: 1.2 GiB an account-day against an estimated
  4.4 GiB for the real path. So the grading time on real day-sized journals, from a cold
  cache, is extrapolated, not measured. No optimization was made, and no time threshold is
  set.
- **Projection reconciliation clock (found and fixed 2026-10-13).**
  - *Cause.* Over 90 minutes, `_replay_mix` refused one batch per account at decision
    time with `decision_precedes_account_state`. In okx-shared:
    - knowledge clock at the previous round: 00:50:02.961001;
    - a delivery authored exactly on the 00:51:03 instant, available 1 ms later, so it
      crosses that instant;
    - before processing it, the harness reconciled, stamped at that delivery's clock,
      00:51:03.001001;
    - the delivery's decision, dated at the instant 00:51:03.000000, was earlier than
      the account's new knowledge and was refused.

    The harness used one clock both to schedule a round and to date its evidence.
    `AccountReconciler` stamps at the later of the account's `known_at` and its last
    accepted market. A delivery decides every instant it crosses before its market is
    accepted, so that stamp never passes an undecided instant; an equal time is admitted
    because the refusal is strict.
  - *Scope.* Harness only. Production code never stamps a reconciliation: operator,
    opening and recovery observations carry their caller's stamp. The live reconciler
    follows the rule above, and `d2-lifecycle-1/2` and day-counted-2's full day passed
    the no-rejection gate. The operator contract stated only the lower bound;
    [execution](../packages/execution.md) now also states the upper bound. A
    later-stamped observation still refuses an earlier decision by design.
  - *Fix.* Rounds are still scheduled on the delivery clock, every 60 s. Their evidence
    comes from one `reconciliation` projection snapshot and is stamped by
    `AccountReconciler.observation`, the live reconciler's rule now shared by both.
    Admission, refusals, gates and D2 arrival semantics are unchanged. The scheduler no
    longer consumes a clock tick per round, so a delivery exactly one period after the
    last round now starts one.
  - *Regression* (`test_capacity_sustained.py`, about 24 s). A 2 s cadence lands on four
    crossing deliveries in three minutes: before the fix 4 of 60 batches were refused,
    after it none. Expectations are derived from the fixture schedule:
    - 60 batches, all pending;
    - 120 decisions admitted at arrival (2 reserved);
    - 89 rounds, all matched;
    - two filled orders and the oracle's economics, also equal to a 60 s cadence.

    Run it with
    `TMPDIR=/private/tmp uv run --frozen --no-editable pytest -m integration
    tests/integration/consumers/runtime/test_capacity_sustained.py -k crossing_delivery`.
    `test_capacity_reconciler.py::TestReconciliationStamp` covers, on a real D2 account:
    - a decision crossed after a shared-rule round, admitted at its arrival;
    - the delivery-clock stamp refusing it;
    - an equal time admitted, and one microsecond earlier refused;
    - the stamp's choice of clock.
  - *Verification run* (`d2-grading-2`, uncounted). The fixed harness replayed the four
    accounts over the original 90-minute span in 455 s. Every expectation derived from
    the schedule and the fixed economics held (`anchor-90m/verification.json`):
    - 1,800 batches per account, all pending;
    - 3,600 decisions admitted at arrival, none waiting;
    - 89 matched rounds;
    - two filled orders and the oracle's cash, fees and position.

    Graded again, the corrected fixture passes the gate: resolver 12.0 s, gate
    evaluation 13.7 s, 66 MiB, the same cost as `d2-grading-1`.
  - *Earlier evidence.* `d2-grading-1/anchor-90m` keeps its results, with an addendum:
    its refusals were this harness defect and its gate failure was correct. Its cost and
    the generated fixtures stand; those were templated on a batch before the refusal and
    graded fully admitted.

Not yet evidenced:
- no signed final candidate has run this gate in a sustained campaign, a rehearsal or a
  counted day;
- grading time on real day-sized journals is unmeasured;
- the efficiency measurements below leave a full real day's journal and its cold-cache grading,
  storage classes (D4) and day-sized backup unmeasured.

### Efficiency measurements

Measured before the freeze and final acceptance runs, on bounded workloads over the shared
and dedicated paper paths, so the counted run does not discover these costs. No target,
budget or ceiling changed.

**`d2-efficiency-1` (uncounted developer diagnostic, 2026-10-13)**
(`~/AlphaResearchEvidence.noindex/runtime-capacity/d2-efficiency-1/RECORD.md`; plan and
bounds set before generation, none exceeded). Its journals and delivery logs were deleted
afterwards at the owner's request; the record, raw measurement rows, analysis and
verification remain.

*Baseline.* day-counted-2's journals and request timings no longer exist (owner cleanup,
2026-10-12). The baseline is therefore revision `d91d7cd`, whose execution, runtime and
account code equals day-counted-2's `72a74e3`, with neither D2 nor trace frames. Both
revisions ran the projection's real loop on the same day input, verified against
expectations derived from the schedule and the first-touch oracle. Coverage:
- four accounts, 240 minutes (4,800 checkpoints and 392,039 traces an account), on each
  revision, plus two 30-minute repetitions each;
- the dedicated path (`PaperCandidateRuntime` and `PaperOrderJournal`, not in the day
  topology) for 30 minutes at OKX and Bitfinex;
- 600 s of a quiet but valid OKX feed (a book every 2 s, a capture clock every 250 ms),
  then 60 s of outage, in real time through the installed `alpha-execute account` service
  and `SocketPaperAccount`;
- the signed 300 s phases of `natural-expiry-2` (d91d7cd) and `d2-lifecycle-2` (D2),
  re-read.

Every counted run passed. One quiet run at 4 s book spacing was not counted: an authored
heartbeat left an 8 s book gap past the 5 s idle bound. That was a defect in the driver's
schedule, and the run was repeated at 2 s.

| Measure (per account) | Before D2 | D2 (current tree) |
| --- | --- | --- |
| Decision tables per strategy decision | 4.87 KB | 9.75 KB (pending and arrival rows) |
| Batch tables per checkpoint | 10.4 KB | 20.7 KB |
| Trace with indexes (frames, not D2) | 2.99 KB | 1.13 KB |
| Account head | 11.3 KB | 14.3 KB while an arrival waits, 11.3 KB after |
| Decision commit p50: in process; signed service | 1.77–1.96 ms; 4.9–5.0 ms | 2.02–2.11 ms; 5.1–5.2 ms |
| Book commit that resolves the arrival, p50 in process | not applicable | 4.8–5.1 ms (1.5 ms without), once a checkpoint |
| Quiet `advance_paper` | none | 0.31 a second in the profile, 3.5 a second in the quiet feed; a no-op one writes no journal data and takes 1.13 ms of service time (2.2 ms round trip) and 2 fsyncs, with 416 B of service log and 304 B of client log |
| Dedicated journal per decision | timer step | +1 arrival step (3.4 KB); peak waiting state 1 plan and 1 arrival; +0.06–0.09 ms a step |

Costs were flat from 30 to 240 minutes of history. Account services get no telemetry path
from the signed launcher, so account requests (advances included) add no telemetry events;
the signed runs' telemetry rate is unchanged.

*Projected to the declared day* (projections from measured per-unit costs; these are not
observations):
- D2 adds 0.54 GiB per account-day of decision and batch rows, while trace frames save
  4.1. These two bullets assumed per-row trace frames, which the reference frames of
  [storage efficiency](#storage-efficiency-measurements) replaced; the reconciled
  measurement there supersedes them.
- An account journal then holds about 4.2 GiB a day, plus its unchanged 3.9 GiB service
  request log: about 8.1 GiB in all, against the 14.2 observed in day-counted-2. The same
  method on the baseline revision reproduces 14.3.
- Quiet advances add 19 MB a day per account in the profile, and 218 MB with 606,000
  fsyncs if quiet all day. Their client-log share is scratch: at that bound, +0.34 GiB
  for four accounts on the 7.07 GiB (88 % of 8) day-counted-2 reached.
- Telemetry stays within budget: 5.75 million events over 7 days, against 8,000,000.
  Guardrail: an account service given a telemetry path would record 20 events for each
  non-inspection request. The profile's advances alone would then reach 14.8 million
  events over 7 days, so account services must keep running without one.

*Findings not caused by D2:*
- Per-book commits write about 79 GiB of WAL per account-day (90 before), with about
  84 fsyncs per checkpoint; the in-process kernel-attributed writes were higher still. The
  day's resource gate should confirm device writes.
- The dedicated journal stores every delivery whole: about 127 GiB per instance-day at
  OKX depth 400 on both revisions, so that path cannot run a day at this depth.

Still open:
- a full day's real journal: 28,800 checkpoints are projected from 4,800, and real
  day-sized grading from a cold cache is unmeasured;
- service-path latency at large history;
- device flush cost;
- quiet costs on Bitfinex;
- a separately timed cancellation and release through an advance (reached once, at 4 s
  spacing);
- storage classes and ceilings for account journals and owner service request logs
  (D4), and the peak-space scan's omission of diagnostic client logs;
- account backup and restore, qualified only on a 10 GB journal (about 87 s each against
  300 s). The projected 4.2 GiB day journal is smaller, but differently shaped, and has
  not been backed up.

Features and telemetry storage (25.6 of 32 GiB, an accepted risk) is unchanged by this
work; the delivery index is reduced separately
([storage efficiency](#storage-efficiency-measurements)).

Earlier measurements (uncounted, small journals, 2026-10-12 and 13):
- `d4-measurement-1` (with its addendum): the per-book paper trace dominated shared
  journals at 4,342 bytes with indexes.
- `trace-frames-1`: storing each trace as one compressed frame took the same workload to
  1,058 bytes, with unchanged logical traces and unchanged read and write latency. That
  per-row frame was replaced by the reference frame when D2 was rebased onto it.
- `client-log-archive-1`: sealed socket-client logs, which the retention gate counts as
  scratch, are now archived losslessly after the run, about 80 % fewer retained bytes,
  with no effect on the run's peak.

## Day-run host checklist

The day-run host is the development host, declared by the owner on 2026-10-12: Apple M1
Max, 10 cores, 64 GiB RAM, macOS 27.0.1 (26A434) arm64, CPython 3.14.7, internal APFS
SSD, on mains power. Its one exception is the owner's recorded iCloud waiver
(`~/AlphaResearchEvidence.noindex/runtime-capacity/day-counted-3/day-counted-3.host-exception.json`):
iCloud Drive syncing stays enabled, the run uses `--icloud-waived`
(`icloud_criterion: waived_by_owner`), it is never reported as paused, and it does not
meet the unmodified iCloud-off requirement. As recorded, the waiver names one attempt,
`day-counted-3` (candidate `d91d7cd`), and covers only the iCloud criterion. It does not
cover the rehearsal, another counted attempt or any other run; each of those either
meets the iCloud criterion (syncing actually paused, attested with `--icloud-paused`) or
has explicit owner waiver coverage recorded before it launches. Active syncing is never
reported as paused. Every other host, resource and acceptance gate is unchanged,
including 512 GiB free at launch, and the counted journey's host is chosen separately.

`day-counted-3/PREPARATION.md` beside that record holds the launch path prepared for
`d91d7cd` (verification, booking, launcher and preflight); nothing is booked. Pointing it
at the final candidate and repeating its dry run, free-space reading and stale-launcher
check belong to final candidate preparation (step 2 below).

1. **Quiet host.** Review `INTERACTIVE_PROCESSES` in `capacity_sustained_cohort.py`
   against the host's interactive and background processes. Any change is a commit made
   before the freeze.
2. **Freeze and verify one candidate**, before the counted journey and the counted day
   run, which both qualify it:
   - a clean worktree at the frozen commit outside any synced folder, such as
     `<root>/frozen`;
   - a non-editable environment outside the checkout:
     `UV_PROJECT_ENVIRONMENT=<root>/env uv sync --frozen --no-editable`, from the frozen
     worktree (the freeze step refuses an editable install), and the
     [Feast worker](../local-services/feast-worker.md);
   - `tests/integration/consumers/runtime/` copied to `<root>/consumers`;
   - the four validation lanes pass at the frozen commit on this host;
   - recorded identities: the commit, the built artifacts' digests and installed
     identity, and the configuration and evidence identities (consumer copy, account
     configurations, grants and fixtures);
   - `secrets/` copied by the owner only (mode 600; nobody else reads it), a short socket
     base such as `/private/tmp/day`, and durable key and output roots such as
     `<root>/keys` and `<root>/evidence`.
3. **Rehearsal** (2 hours, about 2.5 hours in all) on the frozen candidate, from
   `<root>/consumers`:

   ```sh
   caffeinate -dims <root>/env/bin/python capacity_sustained_cohort.py \
     --stage day-rehearsal --label day-rehearsal-1 \
     --output <root>/evidence/day-rehearsal-1 \
     --repository <root>/frozen \
     --launcher <root>/env/bin/alpha-governance-artifacts \
     --python <root>/env/bin/python \
     --key-root <root>/keys --socket-base /private/tmp/day <icloud>
   ```

   `<icloud>` is `--icloud-paused` only when iCloud syncing is actually paused. Otherwise
   the rehearsal needs explicit owner waiver coverage recorded for it before launch, and
   then uses `--icloud-waived`; the `day-counted-3` waiver does not cover it. A code fix
   makes a new candidate: return to step 2
   ([candidate changes and reruns](overview.md#remaining-work-before-qr-onboarding)).
4. **Counted journey** ([counted attempt](qr-onboarding.md#counted-attempt)): separate
   owner approval and host choice. It finishes before the counted day starts; no fault
   injection overlaps the measured day.
5. **Counted day run** (owner-booked; the day and its 4× replay take an estimated 32–34
   hours, so the slot is about 36 hours): the same command with `--stage day --label
   day-counted --output <root>/evidence/day-counted` and the iCloud flag its own
   coverage allows (`--icloud-waived` under the recorded waiver for that attempt). The
   driver runs the 4× replay after the day, while retention elapses.
6. **Retention**, at least 72 hours after the counted day ends, with no further wait
   after the replay. A replacement counted day starts its own clock at its measured
   day's end:

   ```sh
   <root>/env/bin/python capacity_retention.py \
     --day <root>/evidence/day-counted/candidate/day \
     --output <root>/evidence/day-retention --hours 72
   ```

7. **Measured research capacity.** The
   [72-hour run](../research/program.md#measured-research-capacity) may start on this
   host once the day and its replay release it, and may overlap the rest of the
   retention interval.
