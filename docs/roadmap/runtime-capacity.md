# Runtime capacity

Owner: quant development. Status: **open.** The baseline and sustained runs are
qualified. The counted day run, its 4× replay and its 72-hour retention remain, on a
static host ([remaining work](overview.md#remaining-work-before-qr-onboarding)).

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
  - latency in every 300 s window;
  - checkpoints, reconciliation and orders.
- Checkpoint percentiles: selected book to committed checkpoint at 250/750/2,000 ms over
  the whole counted run, and in every window with at least 1,000 samples. Each account
  needs at least 1,000 committed checkpoints. Rehearsals report this and do not grade
  it.
- Segments: at least 48 a source (counted), with exact chained replay.
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
economic replay. `capacity_retention.py` runs the retention check. A counted attempt runs
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
6. **Counted run** (owner-booked, about 25 hours): the same command with
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
