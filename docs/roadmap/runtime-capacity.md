# Runtime capacity

Owner: quant development. Status: **open.** The baseline and sustained runs are
qualified. The counted day attempt `day-counted-2` failed on 2026-10-12
([failed attempts](#failed-attempts)). The counted day run, its 4× replay and its
72-hour retention remain, on a static host
([remaining work](overview.md#remaining-work-before-qr-onboarding)).

This record holds the integrated paper/shadow capacity targets, the accepted results
and the declaration of the day run. The
[runtime design](../architecture/runtime-and-operations-design.md#scaling-triggers-and-technology-choices)
owns the scaling decision; [research capacity](research-capacity.md) is separate.

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
- Day-run host: the static host, declared before any run on it
  ([checklist](#static-host-handoff-checklist)). It needs at least 512 GiB free at the
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
  `logs/runtime-capacity/day-counted-2/`), immutable, with `PRESERVATION.md` and SHA-256
  manifests. Diagnostics: `~/AlphaResearchEvidence.noindex/runtime-capacity/day-counted-2-diagnostic/`.

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

Remaining before QR onboarding: the counted day run on this or a later candidate, with its
resource gate and 4× replay, and its 72-hour retention, at an owner-booked slot.

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
  - checkpoints, reconciliation and orders.
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
  - iCloud Drive is off or paused.
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

## Static-host handoff checklist

Development continues on the laptop. Three runs move to the static host: the day-run
rehearsal, the counted day run, and its retention with the replay. Code freezes when
the counted day run passes, and fixes found by the rehearsal come back as commits.

1. **Declare the launch host.** Record the OS and version, the interpreter, CPU model and
   core count, RAM, the disk and its free space (at least 512 GiB), and the power supply
   (mains, sleep disabled). iCloud is absent or off. Targets, budgets and gates are
   unchanged.
2. **Install.**
   - A fresh clone at the frozen commit, outside any synced folder.
   - The owner copies `secrets/` (mode 600). Nobody else reads it.
   - The project environment (`uv sync --frozen --no-editable`) and the
     [Feast worker](../local-services/feast-worker.md).
   - The four validation lanes pass on the new host.
3. **Quiet host.** List the host's own interactive and background processes, and review
   `INTERACTIVE_PROCESSES` in `capacity_sustained_cohort.py` against them. Any change is a
   commit on the laptop, made before the freeze.
4. **Freeze.**
   - A clean worktree at the frozen commit, such as `<root>/frozen`.
   - A non-editable environment outside the checkout:
     `UV_PROJECT_ENVIRONMENT=<root>/env uv sync --frozen --no-editable`, from the frozen
     worktree. The freeze step refuses an editable install.
   - Copy `tests/integration/consumers/runtime/` to `<root>/consumers`.
   - A short socket base, such as `/private/tmp/day`, and durable key and output roots,
     such as `<root>/keys` and `<root>/evidence`.
5. **Rehearsal** (2 hours, about 2.5 hours in all), from `<root>/consumers`:

   ```sh
   caffeinate -dims <root>/env/bin/python capacity_sustained_cohort.py \
     --stage day-rehearsal --label day-rehearsal-1 \
     --output <root>/evidence/day-rehearsal-1 \
     --repository <root>/frozen \
     --launcher <root>/env/bin/alpha-governance-artifacts \
     --python <root>/env/bin/python \
     --key-root <root>/keys --socket-base /private/tmp/day --icloud-paused
   ```

   Fixes go back to the laptop as commits, then step 4 again.
6. **Counted run** (owner-booked, about 25 hours; latest prepared candidate `d91d7cd`, see
   [uncounted integration checks](#uncounted-integration-checks)): the same command with
   `--stage day --label day-counted --output <root>/evidence/day-counted`. The driver
   runs the 4× replay after the day.
7. **Retention**, at least 72 hours after the counted day ends:

   ```sh
   <root>/env/bin/python capacity_retention.py \
     --day <root>/evidence/day-counted/candidate/day \
     --output <root>/evidence/day-retention --hours 72
   ```

8. **Measured research capacity.** The
   [72-hour acquisition](../research/program.md#measured-research-capacity) also runs on
   this host.
