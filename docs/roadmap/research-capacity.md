# MR15 research launch capacity

Owner: quant development. Status: numeric profiles and measured diagnostic
changes delivered; finite original-clock acquisition armed under a separate
approved 32 GiB staging cap; representative research acceptance pending. The historical R1 continuation
starts from reviewed `main` at `613bcb0` on `codex/mr15-r1-native-capacity`. Profile declared
before qualification on 2026-09-27. Baseline: `main` at `9106a48`.
MR15 remains open until both this profile and the
[runtime profile](runtime-capacity.md) pass. MR16 ownership enforcement and MR17
fresh QR onboarding remain separate, open gates. Live trading remains KIV until
untouched OOS and forward paper profitability after transaction costs, slippage
and applicable gas; this record grants no trading authority.

## Frozen launch profile

These are explicit **provisional engineering targets**, not prior achievements.
The existing architecture supplies a runtime candidate of seven million source
messages/day and sub-500 ms depth queries, but no numeric research launch budget.
Failed attempts remain evidence against this profile. Any later workload or
threshold revision requires a separately named profile and rationale.

| Dimension | Research launch profile R1 |
| --- | --- |
| Inputs | 72 consecutive UTC hours, two spot instruments, at least 100,000 admitted native trade/book records total; all six instrument-days covered; no time stretching or replicated records counted as representative input |
| Provenance | Pinned raw bytes, acquisition/capture and dataset manifests, original event/receipt/availability clocks, explicit calendars/units, revision and quality evidence; unknown historical availability remains unknown |
| Decisions | One-minute cadence, 4,320 decisions per instrument, 8,640 feature rows; two independent reference study families, two trials each, two simultaneously active workers |
| Features | Exact completed returns and a stateful reference feature; durable materialization, historical PIT retrieval for all 8,640 rows, two-entity online generation through the isolated Feast SDK worker |
| Replay/report | Four costed reference trials over the declared input; retained exact fees/slippage and applicable gas (centralized spot: no gas), reports and reopened results; untouched holdout unused |
| Retention | Raw/canonical inputs and versions 30 days; attempts, reports, configuration and provenance 90 days; local backup retained independently for the same periods. Capacity forecast must distinguish measured bytes from extrapolation |
| Publication | At most 300 seconds for all inputs; at least 333 admitted records/second including verification and durable publication |
| Features | At most 300 seconds for 8,640 rows, at least 28.8 rows/second; initial verification/indexing at most 60 seconds, reported separately |
| Scheduled closes | Warm p50/p95/p99 at most 50/100/250 ms, excluding separately reported initialization; at least 4,320 observed calls per instrument |
| PIT retrieval | Warm p50/p95/p99 at most 10/50/100 ms per entity/cutoff; 8,640 requests; cold initialization/reopen at most 60 seconds |
| Feast boundary | Three or more immutable offline chunks, each at most 4,096 cells and 16 MiB; all cells reconciled. Online generation/reopen at most 60 seconds each; SDK subprocess startup reported separately, not called steady-state serving latency |
| Studies | Four trials, two workers, all completed in at most 600 seconds; per-trial at most 300 seconds. Report/reopen at most 30 seconds each; four observations are totals/ranges, insufficient for tail percentile claims |
| Resources | Aggregate research process tree peak RSS at most 8 GiB (scheduled feature process at most 4 GiB), at most eight logical CPUs; generated workspace at most 10 GiB, source input at most 2 GiB; 30-day retained input forecast at most 100 GiB |
| Recovery | Kill/interrupted attempt retained, retry/reopen within 60 seconds excluding service provisioning; backup/restore within 120 seconds; restored result/checkpoint identities and exact accounting equal uninterrupted execution |
| Correctness | Zero unexplained failures, missing required instruments/days, cross-family writes, future leakage or exact-value differences. Expected injected failures retained separately; missing/invalid source data remains explicit |

Reference policies qualify infrastructure, not profitability. An authored scaled
fixture may diagnose implementations and test arithmetic; it cannot satisfy the
representative-input gate. A real archive with missing receipt or availability
history cannot acquire invented historical knowledge timestamps to obtain a pass.

## Measurement and implementation plan

Target host: Apple M1 Max, 10 logical CPUs, 64 GiB physical RAM; Darwin arm64,
macOS 27.0 build 26A428; standard-GIL CPython 3.14.7, uv 0.12.7 and frozen repository
locks. Initial filesystem observation: approximately 401 GiB free. Record actual
installed source/wheel/configuration identities for each attempt. This is a shared
workstation: record concurrent workload and CPU use rather than implying dedicated
hardware. No operating-system cache flush is authorized or assumed.

Measure first-process/application-cold initialization separately from warm
requests against the same pinned data. OS caches are uncontrolled/warm after the
first read; never label a fresh object or process as physical cold disk. Retain
individual monotonic latency samples, sample count, observation duration and
nearest-rank p50/p95/p99. Report percentiles only with at least 1,000 samples;
report small stage samples as totals/ranges. CPU user/system seconds, peak RSS,
logical bytes read/written, actual disk growth, failures and recovery duration
belong to each attempt. OS block-I/O counters are platform dependent and must be
reported unavailable if they do not measure the relevant I/O.

1. Inventory actual retained inputs and services, then retain baseline failures
   and profiles before changing capacity blockers.
2. Keep dataset publication/query in `market_data`; scheduled feature processing
   in `research.features`; study/result/report admission in their current owners.
   Preserve the existing JobQueue/StudyJobHandler and independently locked Feast
   and ClearML integrations. Change only demonstrated bounds and rereads.
3. Run exact causal, late-correction, concurrent-family and checkpoint/recovery
   regressions. Measure the same declared diagnostic before and after changes.
4. Exercise representative pinned inputs through publication, feature store,
   workers, costed studies, report creation and reopening wherever available.
   Missing inputs/services block their acceptance claims, not independent work.
5. Run focused validation first, then `make check` and the three existing
   performance checks. Verify installed artifacts outside the checkout.

Reversal: revert the implementation change and retain all new inputs, failed
attempts and evidence. Earlier readers will reject newly allowed oversized
studies; do not delete or relabel those results. No schema meaning, financial
arithmetic, calendar, grant or trading limit changes are authorized by this slice.

## Existing evidence and gaps

The three existing performance cases cover 10,000 symbol resolutions in one
second, 10,000 calendar projections in one second and 10,000 exact tick roundings
in two seconds. They remain useful primitive regression checks, not end-to-end
research capacity evidence.

The retained `data/silver/mr18-query-workload` snapshot is one BTCUSDT hour with
about 88.8 MB canonical and 7.3 MB raw bytes. The retained native OKX ETH archive
is one day; historical receipt clocks are unavailable. MR02 public trade capture
covers one minute, and the installed MR03 costed native-book study uses two
decisions per venue. None satisfies R1. `CapturedStudyMarket` explicitly requires
original receipt clocks, so historical archives cannot substitute for that path.
Six additional daily OKX L2 archives (BTC-USDT and ETH-USDT, September 20–22,
2026) are now retained: 764,320,959 unique compressed bytes. Acquisition verified
each compressed archive and reconstructed its first 1,000,000 records; all six
stopped at that declared record limit before the end of the day. Downloading a
whole archive does not establish full-day normalization or historical receipt
clocks. A suitable original-clock corpus remains necessary for R1. Bulk data and
mutable stores stay under ignored local workspaces.

The existing 4,096-row Feast online bound counts entities in one snapshot, so a
two-entity generation does not require relaxing it. The offline grid needs
explicit chunks. The 1,024-row model/Alphalens/window-diagnostic bounds remain
separate from the unfitted reference workload and are not silently lifted.

## Implemented capacity changes

Baseline construction rejected 4,320 decisions, 4,320 benchmark periods and
8,640 feature rows before executing work. Study schedules and report benchmarks
now admit at most 8,192 entries; feature study grids/results admit 16,384 rows.
These finite ceilings accommodate R1, not arbitrary research scale. Training
schedule admission does not qualify a fitted model or remove its independent
limits. Existing serialized smaller studies retain their meaning.

Profiling 128 scheduled closes found 128 replay constructions and 509 query
batch calls. Scheduled features now retain one causal replay, frozen closes and
compact observation state. Restarts validate the pinned input and restore its
cursor; legacy value-only checkpoints reconstruct once and check every frozen
value. Older readers reject checkpoints carrying the new optional state fields.
No financial arithmetic, temporal cutoff, calendar or cost model changed.

## Prior diagnostic results (retained)

**R1 is not accepted.** The independent numerical and recovery checks below
passed on authored inputs. Native publication/replay is measured separately and
does not yet feed the required 72-hour costed study. The
[compact evidence record](research-capacity-evidence.json) retains raw-file
digests, source/configuration identities, baseline refusals and stage samples.
All observations are local to the declared host; no distributed capacity is
inferred.

| Boundary | Observation | Budget assessment and scope |
| --- | --- | --- |
| Scheduled replay, same 128-close/three-row diagnostic | 8.833 s baseline; 0.103 s after incremental replay; replay constructions 128 → 1, query batch calls 509 → 4 | Demonstrated removal of repeated history admission; too few calls for tail claims, not a representative history |
| Installed scheduled driver, profiler disabled | 8,192 closes in 1.375 s; first close 12.129 ms, 8,191 warm calls p50/p95/p99 0.084/0.118/0.186 ms; peak RSS 57,769,984 bytes | Below the diagnostic latency/memory ceilings; only three admitted history rows, with explicit missing values beyond the one-minute source; not R1 history throughput |
| Full authored feature materialization, including real Feast subprocess generation | 8,640 rows in 26.148 s, about 330 rows/s | Below 300 s and above 28.8 rows/s; one application-cold observation, startup included |
| Warm durable PIT retrieval | 8,640 calls over 2.871 s; p50/p95/p99 0.252/0.403/0.522 ms; 2.327 s inside retrieval calls | Below 10/50/100 ms; empirical nearest-rank distribution from one short warm diagnostic, not sustained-load evidence |
| Concurrent costed reference studies | Four trials in two two-worker waves, 36.337 s total; five handler invocations including recovery, 3.360–16.525 s | Below 600 s total and 300 s/trial; actual peak active workers two; shared-process threads, not ClearML agent scaling |
| Report/result reopening | Four calls, 2.939–3.365 s | Below 30 s each; report creation is included in trial time; no four-sample percentiles |
| Recovery | One deliberately lost acknowledgement after durable trial completion; retry 3.360 s; complete backup, restore, Feast reopen and exact result comparison 34.250 s | Below 60/120 s; no duplicate family attempt or cross-family writes. This is acknowledgement loss and restore, not process-kill acceptance |
| Resources | End-to-end 113.216 s; process-lifetime CPU 100.564 user + 11.113 system seconds; parent peak RSS 481,918,976 bytes and maximum child 206,848,000 bytes | Below 8 GiB even conservatively summing these peaks; CPU average approximately one core, instantaneous eight-core ceiling not sampled |
| Retained authored workspace | 341,507,721 logical bytes; backup 337,159,081 and restored workspace 337,128,786 | Combined 1,015,795,588 bytes, below 10 GiB; excludes acquired native source; physical allocation differs because of filesystem sharing |
| Actual OKX BTC/ETH publication | 1,000 original rows each, 2,000 total; 12.686 s, about 158 records/s; 78,178,212 canonical bytes | Below the 333 records/s target even at this prefix; does not test the required 100,000 records or 72 hours |
| Actual archive queries/replay | First query 6.002–6.192 s, repeated query 5.840–6.173 s; replay 12.048–12.131 s/instrument; parent peak RSS 1,567,637,504 bytes | Only two observations/boundary; zero decision-eligible query rows because original availability is unknown; unscheduled native replay reopened exactly in a fresh process |

The native diagnostic covers approximately 25.36 BTC seconds and 21.54 ETH
seconds. It correctly refuses a 20,000-record selection under the existing
10,000-row native-book admission ceiling. A separate ETH reopen profile found
about eight million deep-copy calls, approximately 21.1 seconds in profiled book
replay and 6.7 seconds in repeated snapshot reading/admission. This identifies
bounded book storage/replay as remaining work at its owning `market_data`
boundary; lifting the limit alone would not establish the required memory or
throughput. Profile overhead is not substituted for unprofiled latency.

The authored study checks every running-mean value against independent exact
`Fraction` arithmetic. Each trial has two fills: buy 101, sell 99, fees 0.20 per
side, net −2.40 USDT, including the configured adverse slippage and one-second
execution delay. Centralized spot gas is inapplicable. Both family histories,
four reports, exact results and restored Feast latest values agree. These are
infrastructure examples, with no profitability claim or holdout consumption.

The final run used an independently installed core environment, a copied
consumer with `python -I` from `/private/tmp`, and the independently locked Feast worker. No package
or worker dependency boundary changed. Existing local lakeFS/ClearML servers
were running, but this measurement uses the supported local JobQueue/worker
and local publication policy; it makes no new lakeFS or ClearML capacity claim.
Source acquisition and other workstation activity overlapped some diagnostics;
the successful final run had no concurrent validation or environment install.
OS page caches were uncontrolled. CPU counters include process imports, whereas
elapsed timing starts at the measurement object's construction after implementation verification. The single
feature stage includes worker startup; a separate steady Feast-serving latency
distribution was not collected. Darwin block counters do not establish physical
I/O bytes; retained logical file sizes are reported instead.

### Retained failures and limits

- The original four admission failures and pre-optimization profiles are kept.
  No workload threshold was reduced or relaxed after measurement.
- Small authored harness attempts exposed a relative Feast path, prohibited
  maker slippage, a missing instrument specification and touch-limit IOC orders
  that correctly could not fill after adverse slippage. The final reference
  uses explicit price limits; financial contracts were not weakened. Each
  earlier output/log remains under `logs/research-capacity/smoke-4*`.
- Five acquisition invocations initially failed on an editable environment's
  imports before fetching data. A stable installed interpreter completed the
  remaining downloads in 140.5–159.9 seconds each. The first archive's total
  acquisition duration was not instrumented. Acquisition is not publication.
- The first full 4,320-decision diagnostic completed its assertions but failed
  while scanning implementation identity during a concurrent environment
  install. Its raw samples and traceback remain; it is a failed attempt. The
  successful reruns used a dedicated environment and verified identity at start.
  The final consumer moves constructor I/O to explicit orchestration/factories;
  its final run also uses a working directory outside the checkout.
- Two initial native ETH diagnostic attempts failed on harness identity/JSON
  decoding, before the retained successful exact reopen. A focused validation
  command named a nonexistent test file and ran no tests; the corrected run
  passed 43 tests. These failed invocations are not successful qualification.

At the reviewed baseline, the remaining R1 gaps were full-day source admission with original availability,
native book throughput/memory and admission bounds, combined representative
publication-to-study execution, three real offline Feast chunks, process-kill
recovery, sustained resource/I/O sampling and measured retention growth.
The raw archive volume extrapolates to approximately 7.12 GiB for 30 days at
these six instrument-days' compressed rate; this is **raw-only extrapolation**,
not the required raw/canonical/features/artifact retention qualification.
Current source storage occupies approximately 1.43 GiB including retained
download copies. Runtime's 512 GiB free-space prerequisite was not met by the
initial 401 GiB observation; it remains a prerequisite, not a revised target.

## Reproduction and validation

Keep each attempt in a new directory. Never synchronize an environment during
a measurement. From this checkout, prepare a dedicated core environment with
`UV_PROJECT_ENVIRONMENT=/private/tmp/research-capacity-reproduce uv sync --frozen --no-editable`.
Prepare the independently locked worker using its
[existing guide](../../configs/development/research-worker/README.md).
Copy [capacity_workload.py](../../tests/integration/consumers/research/capacity_workload.py)
and [archive_capacity.py](../../tests/integration/consumers/research/archive_capacity.py)
outside the checkout, then use the dedicated interpreter:

```sh
/private/tmp/research-capacity-reproduce/bin/python -I /absolute/capacity_workload.py \
  --output /absolute/fresh-authored-attempt --decisions 4320 \
  --worker-python /absolute/research-worker/.venv/bin/python
/private/tmp/research-capacity-reproduce/bin/python -I /absolute/archive_capacity.py \
  --archives /absolute/completed-btc-archive /absolute/completed-eth-archive \
  --output /absolute/fresh-native-attempt --max-records 1000 --max-bytes 1000000000
```

Each `archives` entry in the compact evidence record contains the original
acquisition `request.config`, URL, request identity and raw SHA-256. Write that
configuration verbatim to an external JSON file and invoke the installed
`alpha-acquire archive fetch --config /absolute/config.json --output /absolute/archives`.
Compare raw hashes before replay. A changed provider response is a new input,
not reproduction of the pinned attempt. Retain `request.json`, `summary.json`,
raw objects and index/manifest bytes together; original receipt timestamps
cannot be recovered from an archive download timestamp.

For the independent installed scheduled profile, copy
[scheduled_capacity.py](../../tests/integration/consumers/research/scheduled_capacity.py),
`configs/data-jobs/fixture-inspection.json`, `configs/reference/binance-spot.json`
and `tests/fixtures/eligibility/membership-corrections.json` outside the checkout:

```sh
/private/tmp/research-capacity-reproduce/bin/python -I /absolute/scheduled_capacity.py \
  --job-config /absolute/fixture-inspection.json --catalog /absolute/binance-spot.json \
  --eligibility /absolute/membership-corrections.json \
  --output /absolute/fresh-scheduled-attempt --count 8192
```

Use `--count 128 --profile` for the small call-count diagnosis. The original
before/after profiles used the equivalent existing test fixture, with the same
four native occurrences, one correction and three admitted rows; their retained
input/configuration identities differ from this independently installed driver.
The source remains a one-minute authored compatibility fixture in every case.
Retained interpolated percentiles from the original profiler are not acceptance
claims; the compact record omits tails below 1,000 samples and recomputes nearest
ranks for larger samples.

Validation retained for the prior delivered slice:

| Check | Result |
| --- | --- |
| Focused scheduled/parity, bounds, features, decision contracts and reports | 43 passed in 13.95 s |
| Existing `make performance-test` | 3 passed, 1,809 deselected in 4.24 s |
| Explicit real Feast serving/candidate integration | 3 passed, 1 deselected in 58.04 s |
| `make check` | Passed: all five locks, Ruff, strict mypy (596 files), native stub checks, engineering/dependency/link governance, vulnerability audit, secret scan, Bandit, and 1,807 tests passed / 2 skipped / 3 performance cases deselected in 242.75 s |
| Installed-wheel smoke | Passed: installed APIs/resources, historical snapshot and OKX book CLI; wheel/environment retained at `/private/tmp/alpha-research-wheel-smoke-if43an7s` |
| Changed Markdown links and `git diff --check` | Passed, including component and test READMEs outside the normal docs-only link scan |

The two full-suite skips are the optional Feast checks; the explicit worker
selection above ran them. Exact commands, log hashes, source/lock identities and
wheel digest are in the compact evidence record. Existing development-only
dependency restrictions remain unchanged; a passing check is not release or
trading authority. Review confirmed that source changes stay within existing
feature, study and result owners; consumer orchestration remains outside the
libraries, and no distributed infrastructure or dependency was added.

The continuation below addresses bounded native publication/replay and missing
diagnostic boundaries. To close R1, obtain a 72-hour original-clock corpus and run
the declared combined path without changing R1's thresholds. The next
[bounded runtime prompt](runtime-capacity.md#next-bounded-runtime-prompt-after-the-research-slice)
preserves MR14's finite service lifetime and makes the later sustained lifecycle
and grant qualification explicit. MR15, MR16 and MR17 remain open.


## R1 continuation from reviewed baseline 613bcb0

Status: bounded native implementation delivered; representative qualification
blocked and **R1 remains unaccepted**. The frozen workload and all thresholds above are unchanged. The
prior acknowledgement-loss diagnostic remains separate from the new actual
process-interruption drill. This continuation does not qualify runtime stage 1,
the subsequent 24-hour gate, MR16 or MR17.

### Representative input prerequisite

A new inventory rehashed the six retained OKX BTC-USDT/ETH-USDT archives for
September 20–22, 2026 against their raw manifests and pinned discovery indexes.
They contain 764,320,959 unique compressed bytes. The retained acquisition
reconstruction stopped at one million records per archive, covering only about
5.5–9.3 hours from each UTC midnight. These six million prefix records are
historical source records; their original receipt/availability and sequence
clocks remain unknown. Neither the archive download time nor the index receipt
time can supply those missing clocks. Archive hash integrity is not full-day
coverage or causal admission.

The retained native public captures cover seconds of BTC only, with original
local receipts. The MR02 backfill has 258 trades from a one-minute request,
without original row receipt; its two native captures each stopped at 100
messages after 10.294 and 3.312 seconds. The MR18 snapshot contains 27,480 BTC
trades over one hour, with unknown original knowledge clocks. No retained
candidate provides the required original-clock BTC/ETH history across all six
instrument-days. Full inventory bytes and the rerunnable verifier are retained
under `logs/research-capacity/r1-input-inventory/`, with digests in the existing
[evidence record](research-capacity-evidence.json).

The exact missing prerequisite is 72 consecutive UTC hours for both selected
spot instruments, with at least 100,000 admitted unique native records, original
event/receipt/availability semantics, explicit gaps/revisions, units/calendars,
and retained raw/acquisition manifests. A suitable existing provider recording
could meet it only after original-clock, coverage, format and access verification;
no accessible qualifying recording was found here.

The concrete own-capture route is the existing public OKX `books` adapter at
depth 400, configured separately for BTC-USDT and ETH-USDT and supervised together.
The [collector guide](../data/okx-market-data.md) documents the public route and
finite commands. The current command
`alpha-collect capture --config configs/live/okx-btc-usdt.json --output /absolute/capture-root`
is a 20-second BTC diagnostic, not a multi-day acquisition. The current schema
admits one instrument/config, at most 3,600 seconds, one million messages and
one billion bytes per invocation. An ETH instrument binding and finite, gap-aware
segment rollover/handoff must be implemented and qualified first; restarting
one-hour captures does not prove continuity. Then an explicitly authorized,
supervised run needs at least 72 elapsed hours (and sufficient alignment to cover
three complete UTC days), with gaps and overloads retained. Original receipt
cannot be recreated by processing faster or repeating records. No new capture,
unattended collection, data purchase or provider access was launched here.

### Owning implementation and validation scope

Native publication now has a versioned line stream, with raw reconstruction and
canonical verification before atomic visibility. It retains one full native
observation at a time rather than an entire history. The new path accepts a
finite selection of up to one million raw positions per input, still subject to
source and byte limits; legacy in-memory `BookInput.admit` remains capped at
10,000. This is a storage change with a measured consumer, not a cap-only fix.
Each observation preserves exact levels/orders, state identity, source position,
quality transitions and original clocks. It does not grant a new quality scope.

`BookSnapshot.read` explicitly verifies the complete snapshot once. Repeated
query/replay consumers share that session under the existing protected immutable
store contract; returned records and provenance are isolated, and changed
canonical files are refused. A session does not re-read original raw bytes on
every query; callers must keep both stores and their ancestors protected. Streamed replay retains a lookahead and delivery batch, preserves
legacy cursor identities for v1 inputs and uses a distinct v2 identity. Legacy
snapshots remain readable; older readers cannot read v2. Close an unfinished
stepping replay with `close()` to release its file stream and any tie spill;
separately obtained batch iterators must be exhausted or closed by their caller.
Resume using a completed cursor and independently retained consumer state.
Live queries perform an existence prescan before delivery so every batch retains
the legacy no-values explanation when needed; this can require two canonical
hashes and two decoding passes. The empty archive measurements below do not
measure that populated live-query cost.

The focused proof compares every selected native observation to the existing
raw reconstruction path and retained small baseline traces. Authored checks
independently verify exact Decimal book levels, deletion, gap controls, receipt
rounding, late prior-epoch snapshots, cutoff exclusion, consumer mutation
isolation, and restart/phase equivalence. Authored workflow checks exercise
actual offline Feast chunks, interruption and restore, but cannot replace the
missing representative corpus. Combined native-publication-to-research R1
execution remains pending that corpus.

Rollback restores the previous implementation and preserves v2 data and failed
attempts. Existing v1 snapshots remain usable; opening v2 after rollback requires
the newer reader. No numerical contract, timestamp meaning, threshold, trading
limit or holdout selection changes.


### New native diagnostic measurements

The first installed v2 diagnostic uses the exact two original archive prefixes
from the retained baseline: 1,000 BTC records plus 1,000 ETH records. All source
times, positions, outcomes and full-state digests match the baseline exactly.
Canonical format and normalizer identities deliberately produce a new snapshot.
Publication, including raw copying, independent native reconstruction, fsync and
atomic visibility, took **7.567 s (264.3 records/s)** versus the retained
**12.686 s (157.7 records/s)**. This improves the bottleneck but still misses
R1's 333 records/s target at this small scale; it is not a passing attempt.

Whole-snapshot admission is now explicit: **3.584 s** in this run. After that
admission, first projections took 1.223/1.049 ms and repeated projections
0.940/0.991 ms. These return zero market rows because the archives have unknown
original availability. They are neither populated depth-query latency nor R1
feature PIT retrieval evidence. The two whole-prefix replay scans took
**1.867/1.889 s**, with 213,696,512 bytes peak parent RSS; recursive parent/child
sampling over the complete 28.413-second diagnostic observed 286,474,240 bytes
peak aggregate RSS and 1.015 logical CPUs. Sample count was 125 at a nominal
0.2-second interval. Two observations supply totals/ranges, not tail percentiles.

The workspace retained 248,636,014 logical bytes, including 170,453,882 raw and
78,178,180 canonical bytes. These are measured bytes for this prefix. Disk caches
were uncontrolled; application initialization and warm projection are identified
separately. The process sampler records the observed process tree and can miss
short-lived processes or peaks between samples. Darwin block-operation counts
are recorded, but the selected platform interfaces do not provide process-level
physical read/write byte measurements; zero counters are not zero disk I/O.

The larger installed diagnostic admits **50,000 distinct source positions per
instrument**, 100,000 total, without changing timestamps or repeating inputs.
Publication took **189.938 s (526.5 records/s)**, meeting the 300-second and
333-record/second numbers for this diagnostic. Peak parent RSS during publication
was 60,555,264 bytes. This removes the measured count and publication bottleneck;
it does not establish representative acceptance. The source windows span only
2,109.263 BTC seconds and 1,967.227 ETH seconds on September 20. Original
availability is still unknown and every query correctly returns zero eligible
market rows.

Cold whole-snapshot verification took **91.233 s**. That exceeds the profile's
60-second initialization allowance and remains an integration concern; it is
native snapshot admission, not a measurement of the still-pending representative
feature/PIT initialization. Reusing the admitted session makes the two first
projections 1.057/1.062 ms and two warm projections 0.896/0.918 ms. The complete
BTC/ETH replay scans took 94.538/95.464 s. Every observation, including exact
levels, outcomes, source positions and times, matched an independently
reconstructed reference (84.779/90.508 s for those comparison passes).
An independent process reopened the same immutable identity and reproduced both
query and full replay traces exactly. Its initial re-admission took 91.548 s;
its two replay scans took 95.108/98.604 s. The complete diagnostic, including
reference comparison and process reopen, took 932.308 s. The 4,137 recursive
samples observed 287,424,512 bytes peak aggregate RSS and 1.099 logical CPUs;
parent peak RSS was 213,057,536 bytes. This diagnostic duration is not publication
time or a representative end-to-end workflow measurement.

The larger workspace retained approximately 4.080 GB logical bytes, including
170,453,882 raw bytes. This is observed prefix growth; it is not a daily retention
rate. Full-state canonical records still consume substantial disk, and no
30-day raw/canonical/features/artifact forecast is qualified by this short
prefix. The prior 7.12 GiB raw-only extrapolation remains explicitly separate.
Neither native diagnostic overlaps a test suite, acquisition or environment
installation; this is still a shared workstation with uncontrolled OS caches.

### Final authored workflow diagnostic

The final run used the independently installed root wheel and a copied consumer
outside the checkout, after the native measurements finished. Its implementation
identity is `c12b9bafa246d6558f70d7c633b2f0af3970610b6b61feffee7b5235a7a2f8ff`.
The consumer records pinned authored inputs, feature/study/cost identities,
individual durations, stage windows, SDK wire sizes and recursive process samples.
These inputs remain authored: neither their 72-hour decision grid nor their
successful checks supplies representative native history.

| Boundary | Measured result | R1 comparison, diagnostic only |
| --- | --- | --- |
| Feature materialization and online generation | 8,640 rows in 28.258 s, 305.8 rows/s; SDK online generation 3.171 s included | Below 300 s, above 28.8 rows/s; one fresh-store observation |
| Durable PIT | 8,640 warm calls, p50/p95/p99 0.264/0.428/0.556 ms; 2.746 s inside calls; maximum 23.697 ms | Below 10/50/100 ms; empirical nearest ranks from a short authored workload |
| Actual offline Feast | Three immutable chunks, 2,880 cells each; 81.151 s total, 26.930–27.123 s/chunk; all 8,640 exact cells reconciled | Three-chunk condition exercised; each request/response below 16 MiB and each chunk below 4,096 cells |
| Reopen | Feature store 0.525 ms; online generation 0.830 ms | Below 60 s each; one observation each, no cold percentile |
| Costed studies | Four trials, two families, peak two active workers; two waves total 38.530 s; five handler invocations 3.581–17.453 s including acknowledgement retry | Below 600 s total and 300 s/trial; local worker threads, not distributed scaling |
| Reports and results | Four reopened reports/results, 3.543–3.735 s each | Below 30 s each; totals/range only |
| Actual process interruption | Child exited with SIGKILL (−9) after durable attempt start; incomplete attempt retained then marked abandoned; queue retry/recovery 17.460 s | Below 60 s; recovered result and exact accounting equal the uninterrupted control |
| Backup and restore | 38.077 s including reopen and equality checks | Below 120 s; exact family histories/results/accounting and offline artifact bytes agree |
| Resource observation | 224.156 s total; 829 recursive samples; peak tree RSS 5,017,485,312 bytes, parent peak 651,558,912 bytes, peak sampled CPU 4.162 logical cores | Below 8 GiB tree, 4 GiB parent and eight-core diagnostic ceilings; sampling can miss inter-sample peaks |
| Disk growth | Workspace 428,849,998 logical bytes before final measurement JSON; backup 339,132,734 and restored tree 339,100,332 bytes | About 1.107 GB combined logical retention, below 10 GiB; separate authored roots, excludes native source and does not qualify a retention rate |

The worker's owned child is actually killed; the retained acknowledgement-loss
case remains independently labeled. The uninterrupted control is an additional
oracle, not a fifth declared trial. Each completed trial retains two fills and
exact net −2.40 USDT after fees and adverse slippage; centralized spot gas remains
inapplicable. No holdout or profitability acceptance is consumed.

SDK process-spawn durations are retained separately (ten calls, 3.083–6.199 ms).
SDK operation times include interpreter/import/SDK startup; no ready-handshake
isolates that startup from work, and no fresh-process request is called steady
serving latency. Process-tree sampling had zero enumeration/read failures and no
sampler error. CPU totals were 199.599 user plus 39.340 system seconds, including
children; host-wide sampled CPU reached 87.3%, exposing competing workstation
load. Darwin physical process I/O byte counters remain unavailable. Logical
growth and `st_blocks * 512` are recorded separately; APFS shared extents make
allocated-byte sums across backup/restore roots non-additive.
The offline registry contains absolute source paths: backup checks preserve its
exact bytes, but a relocated offline SDK query was not exercised. Restore proof
covers family histories, exact results/accounting, feature-store reopening and
online generation/retrieval, without claiming offline registry relocation.

Earlier smoke attempts and the old-installed 4,320-decision run remain in the
evidence record. The earlier run used a less complete child sampler and cannot
replace this recursive measurement. The existing 8,192-close scheduled-feature
diagnostic is reused because its owning implementation is unchanged; its tiny
authored source still cannot qualify the required native scheduled-close path.

### Acceptance still open

Final continuation validation passed:

| Check | Result |
| --- | --- |
| Integrated focused causal, numerical, boundary and recovery checks | 61 passed, 4 deselected; equal-receipt ordering/restart group also passed 8 checks |
| Final `make check` | All five locks, Ruff, strict mypy (598 files), native stubs (1,562 modules), engineering/dependency/link governance, complete dependency audit, security and secret scan; 1,814 passed, 2 optional Feast skips, 3 performance cases deselected in 219.10 s |
| Existing performance gate | 3 passed, 1,816 deselected in 2.61 s |
| Explicit real Feast serving/candidate integration | 3 passed, 1 deselected in 54.71 s, covering the optional suite skips |
| Installed artifacts | Root wheel smoke passed APIs/resources, historical snapshot and OKX book CLI; independently installed collector performed both native capacity runs, and installed root performed the full authored workflow |
| Evidence and documentation | Original R1 profile and all prior evidence values preserved; source/lock hashes, changed Markdown file targets and `git diff --check` verified |

The first final gate stopped on the stale root lock admission digest after
declaring already admitted `psutil==7.2.2` as a direct development dependency.
The two generated development-edge entries add no external version, artifact or
runtime requirement. The owning admission pin and rationale were updated, and
the complete gate passed on retry. Earlier catalog-v2 dispatch, initial tie-fixture
setup and Ruff failures remain in the evidence with their passing corrections.
The final root smoke wheel differs from the measured root wheel only in the
packaged `market_data/README.md` and wheel RECORD; installed production bytes
and metadata are identical. Unchanged scheduler and MR14 runtime evidence is
reused only within its original scope. Exact commands and artifact/log digests
are retained in the [existing evidence record](research-capacity-evidence.json).

R1 needs the original-clock corpus described above, the combined native-to-study
workflow on that corpus, representative scheduled-close and populated query
measurements, resolution of cold initialization cost, and a full retention
forecast grounded in representative growth. The unchanged 512 GiB free-space
runtime prerequisite is also unmet: the larger native attempt started with
424,159,051,776 bytes free. Runtime stage 1 and the later 24-hour gate, MR16 and
MR17 remain pending. The next independent runtime task is the existing
[bounded stage-1 prompt](runtime-capacity.md#next-bounded-runtime-prompt-after-the-research-slice);
its finite result must not be promoted to 24-hour acceptance. Live trading
remains KIV pending untouched OOS and forward-paper profitability after all
transaction costs, slippage and applicable gas.

## Original-clock acquisition continuation (2026-09-28)

The continuation starts at `ec34b8b`; R1 counts and budgets remain frozen. A fresh
60-second public OKX BTC-USDT/ETH-USDT sample preserved original socket receipts,
native event/sequence clocks, one snapshot per instrument, no gaps or duplicates,
and exact saved-input replay. Native publication and reopening admitted the real
sample; the retained assessment is under `logs/capacity-closure/`. These seconds
do not establish full-day coverage. The six September 20–22 archives still have
unknown historical receipt/availability, and their retained partial reconstructions
do not establish all six instrument-days. Free Tardis [first-day samples](https://docs.tardis.dev/api/http-api-reference)
do not supply three consecutive days; additional archive downloads cannot repair
missing original knowledge clocks.

Observed OKX encoded rates project approximately 12.1 GiB unique raw journal bytes
over 73 hours, or 24.3 GiB with retained publication copies, before metadata. This
is an extrapolation from a minute, not a guaranteed daily rate. On 2026-09-28 the
user explicitly approved a **separate 32 GiB acquisition staging cap**, retaining
R1's **2 GiB source, 10 GiB workspace and 100 GiB thirty-day input forecast** limits.
No acceptance budget is raised. At the sampled full-state canonical expansion,
representative publication/storage also needs a separate measured solution; raw
capture alone does not resolve that dependency. Lossless compression experiments
are estimates only until the actual ingestion path supports and verifies them.

The intended fixed acquisition window is **2026-09-28 23:00:00 UTC through
2026-10-02 00:00:00 UTC**, covering September 29, September 30 and October 1.
Both source processes must be ready before the first required midnight. Retain
actual startup, snapshots, segment identities, durable cursors, sequence quality
and every gap. A late start, missing interval or hard-cap stop stays incomplete;
the run never extends its deadline to conceal it. The finite public collector
may preserve a live connection across storage rollover; a process restart must
declare a gap and obtain a fresh native snapshot. Collection grants no paper or
trading authority. The durable run record will own exact commands, process
identity, progress, stop/resume behavior and final bounds before activation.


### Source coverage and admission limits

The inventory at 2026-09-28 15:00 UTC independently checks retained raw hashes,
request identities and native reconstruction. Its 78 candidate recordings include
73 completed captures and five incomplete attempts; 264 fixture or unqualified
provenance recordings are excluded. Counts below are unique admitted native
positions within each immutable recording, not asserted global exchange-event
uniqueness across overlapping recordings. Exact disjoint UTC intervals, original
IDs, sequence gaps, duplicates, outcomes and raw hashes are retained in
`logs/capacity-closure/source-inventory.json`.

| Original public source | Completed recordings | Admitted native positions | Unique raw bytes | Longest retained interval |
| --- | ---: | ---: | ---: | ---: |
| OKX BTC-USDT | 33 | 4,284 | 5,521,546 | 63.244 s |
| OKX ETH-USDT | 4 | 2,261 | 3,192,592 | 63.247 s |
| Bitfinex BTC/USD | 32 | 17,463 | 2,433,794 | 63.148 s |
| Bitfinex ETH/USD | 4 | 10,238 | 1,399,332 | 62.966 s |

These short intervals span September 15–28 and leave explicit unobserved periods;
they cannot be stitched into continuity. OKX retains native event milliseconds,
sequence and original receipt nanoseconds. Bitfinex R0 has original receipts and
sequence but no native event timestamp. Observation availability follows the
existing original-receipt contract; durable publication is separately measured.
Neither venue uses download time as historical availability.

The six September 20–22 daily archives contain 764,320,959 unique compressed
bytes and six independently verified million-record prefixes, each covering
only about 5.5–9.3 hours. The older September 8 BTC archive adds 109,423,187 unique
bytes; repeated downloads and the older ETH copy add no unique archive bytes.
All retained archive bytes total 873,744,146 after hash deduplication. Original
row receipt/availability and source-sequence continuity are unavailable, so
none supplies an admitted original-clock R1 instrument-day. The historical ETH
archive ID `5ff4f1a3-f2e1-5662-b60f-70e24d2ad521` remains distinct from the live
ETH ID `7c03e264-bd70-4e5e-bcf7-fb9db7d4c843`; USD and USDT remain distinct.

The fresh OKX sample's 1,185 frames occupy 2,981,654 raw bytes. Existing native
publication produced 46,307,308 canonical bytes in 2.740 seconds and reopened
in 1.304 seconds. A separate real 23-second rollover check preserved one
connection/snapshot across five segments per source, with no gaps; independent
chain replay, all suffix publications and reopening passed. These are small
compatibility proofs, not representative capacity. The current suffix publication
replays predecessor chains and still needs a measured compact ingestion solution
before a 73-hour corpus can meet the frozen R1 publication/storage limits.
At the observed rate, full-state canonical output projects to 188.3 GiB and
30-day raw-plus-canonical retention to approximately 1,976.9 GiB.

R1 remains pending: zero qualifying complete instrument-days in the inventory,
no accepted 72-hour corpus, and no representative 8,640-row/four-trial/two-worker
workflow. Acquisition staging approval changes none of those acceptance facts.

### Fixed window readiness correction

The September 28 23:00 UTC start was missed before any long-run collector was
armed; that planned window has zero coverage. It is retained in
`logs/capacity-closure/acquisition-window-missed.json`. The replacement window
is **2026-09-29 23:00:00 UTC to 2026-10-03 00:00:00 UTC**, with required readiness
before September 30 00:00 UTC, covering September 30, October 1 and October 2.
This is a new pre-activation declaration, not an extension or relabeling of a
running acquisition. The same 32 GiB staging cap and frozen R1 budgets apply.

### Armed acquisition and continuation

The final installed collector `fc3d794c127f9903b539f4a4d8a69dfa4bb96bbcc0914d31dcc8c6cdb40ab097`
was armed at September 28 23:51:08 UTC. BTC/ETH process IDs 65954/65956 held
exclusive run locks and reported `waiting_start`; separate finite `caffeinate`
owners keep the Mac awake while those processes live. This records ownership,
not actual startup readiness or accepted coverage. Progress is durable under
`data/okx/research-corpus-20260930/{btc,eth}/progress.json`; the exact commands,
request/config hashes, stop/resume instructions and expected completion are in
`logs/capacity-closure/acquisition-run.json`. The observed ownership proof is
`acquisition-ownership.json` in that same ignored directory.

Per source, the fixed run permits 3,000,000 messages, 7 GiB of unique encoded
records, 150 segments and at most 32 reconnects. Segments retain the declared
30-minute/75,000-message/256 MiB limits. The two-copy raw ceiling is 28 GiB; the
remaining staging reserve accounts for bounded unknown tails, sealing scratch
and metadata. No needed record is discarded. Initial/resume preflight preserves
a separate 10 GiB workspace free reserve. Actual worst-case occupied-byte
preflight passed within 32 GiB. Every manual resume must repeat that check,
including retained crash tails and temporary files.

The final real compatibility sample retained five segments/source, one original
snapshot and one session each, no gaps or duplicates, original clocks and exact
independent replay. Every suffix published and reopened through the existing
native dataset path. This renews the installed rollover proof after the final
progress-counter correction; it does not qualify multi-day publication capacity.

To stop one source, create its durable `stop-requested` file. Automatic network
reconnects preserve explicit gaps and obtain a fresh snapshot; process crashes
require an explicit budget-checked resume. From the repository root:

```sh
# Inspect both durable progress records and acquisition-run.json first.
/private/tmp/capacity-closure-collector/bin/python logs/capacity-closure/resume_acquisition.py btc
# Only after a crash, before the fixed deadline, with no live owner or stop marker:
/private/tmp/capacity-closure-collector/bin/python logs/capacity-closure/resume_acquisition.py btc --resume
# After the fixed stop, verify each retained chain separately (repeat for eth):
/private/tmp/capacity-closure-collector/bin/alpha-collect capture-run-replay \
  --run-directory data/okx/research-corpus-20260930/btc --max-seconds 7200
```

The preflight script needs Python 3.11 or later; this host's `/usr/bin/python3` is
3.9, so the collector interpreter runs it.

**Stop and exact resume (2026-09-29).** Both owners recorded `supervisor_stop` at
02:02:24 UTC, before the window opened and with no `stop-requested` marker; the host
restarted at 02:40 UTC and removed the `/private/tmp` collector environment. No
segment had been written. Installing commit `5ca22aa` reproduced the exact collector
identity `fc3d794c…`, and the owner approved resuming. Both budget preflights passed
(worst case 29.0 of 32 GiB, 547 GiB free), and at 06:36 UTC both runs resumed on the
original implementation, request and fixed window as PIDs 63739/63740 with their own
`caffeinate` owners, reporting `waiting_start`. The preflight records are
`resume-preflight-20260929T063617*.json` in `logs/capacity-closure/`.

Keep raw segments for 30 days and run/provenance records for 90 days after the
fixed stop; no automatic cleanup is configured. Retained journal/publication
copies share a disk and do not establish independent backup. Backup/restore,
retention acceptance and corpus admission remain part of R1. A gap, missed
readiness deadline or exhausted cap remains visible and cannot extend the run.

Next bounded prompt: **Read the durable acquisition record and both current
progress/summary files. After October 3 00:00 UTC, independently replay the exact
OKX chains and assess September 30–October 2 original-clock continuity, all six
instrument-days and at least 100,000 admitted unique native records. Preserve
source IDs, every gap and the unchanged R1 2 GiB/10 GiB/100 GiB budgets. Diagnose
the measured raw/canonical storage and predecessor-replay costs before attempting
representative publication. Only with a qualifying corpus and compatible budgets
run native publication → scheduled features → historical PIT/Feast → four trials
with two workers → report/reopen, exactly 8,640 feature rows, recovery, independent
backup/restore and retention checks. Keep cold initialization separate; report
remaining dependencies without claiming R1 or sustained MR15 acceptance.**

The final local `make check` and all three performance tests passed. The
[canonical evidence](research-capacity-evidence.json) appends the acquisition
assessment, exact run/ownership/status references and unchanged-budget dependency;
every pre-existing evidence value is preserved. The collectors remain
`waiting_start` at the final observation; arming is not corpus acceptance.
