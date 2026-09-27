# MR15 research launch capacity

Owner: quant development. Status: numeric profiles and measured diagnostic
changes delivered; representative research acceptance pending. Profile declared
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

## Qualification results

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

The remaining R1 gaps are full-day source admission with original availability,
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

Validation on the final source:

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

To close R1, obtain a 72-hour original-clock corpus and qualify bounded native
publication/replay at its owning storage boundary, then run the declared combined
path, offline chunks and loaded recovery/resource checks without changing R1's
thresholds. The next
[bounded runtime prompt](runtime-capacity.md#next-bounded-runtime-prompt-after-the-research-slice)
preserves MR14's finite service lifetime and makes the later sustained lifecycle
and grant qualification explicit. MR15, MR16 and MR17 remain open.
