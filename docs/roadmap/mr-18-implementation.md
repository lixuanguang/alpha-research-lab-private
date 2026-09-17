# MR 18 — Measure the trade workload and retain the reference reader

Owner: repository founder. Status: implemented and locally verified for review on
2026-09-17; **columnar backend deferred for the measured workload**, not implemented.
Branch: `codex/mr-18-query-backend`. Base: freshly fetched `main`
`0898d0a532235b68972590526ce92673b6f8bfee`. Prerequisites MR 14 (`746e002`, PR #38),
MR 15 (`69a45eb`, PR #39), MR 17 (`3deb34b`, PR #42) and MR 19 (`0898d0a`, PR #44)
were merged ancestors before branch creation. Runtime candidate: `cae1b06`.
The [roadmap](README.md#m2-research-data-access-and-replay) owns scope and acceptance.

## Problem / change

The original reader failed the founder-approved offline workload: its first verified
open peaked above 1 GiB, and its first minute-history query took 85.890 s. A bounded
DuckDB/Parquet experiment reduced scan cost and produced a compact sidecar, but did not supply the complete
verified query contract. A smaller reference change now meets the **original**
300 s open, 30 s query-p95 and 1 GiB process-memory budgets. No runtime dependency,
saved format, historical availability or economic identity changed.

`AsOfSelector` retains its fully admitted private partitions and copies returned
selections. `QueryReader` copies evidence and history records at the output boundary.
Repeated queries no longer decode and reproduce the entire admission twice. The
admission check compares deterministic field encodings without allocating two extra
nested dictionary trees; it still reconstructs and compares the complete admission.
Unsafe result mutations cannot affect later queries. No validation was removed.

The selected research operation is inspecting exact trade prices, quantities and
provenance for a minute/full hour, then checking whether those observations were
historically knowable. This is input diagnosis, not strategy selection or replay.
Backend adoption is deferred because the optimized reference meets this bounded
consumer's requirements. Reopen MR 18 when a concrete larger, concurrent, depth or
stricter-latency workload requires it; do not treat this as universal performance.

### Workload registered before timing

The founder accepted these **proposed usability assumptions** in this task before
benchmarking: verified opening at most **300 seconds**, fully consumed query
**p95 at most 30 seconds**, process peak RSS at most **1 GiB (1,073,741,824 bytes)**.
No existing trade-query SLA was found. The roadmap's proposed 7M+ messages/day and
sub-500ms depth-query target concerns a different, not yet supported query consumer;
this experiment neither evaluates nor relaxes that target.

| Dimension | Fixed selection |
| --- | --- |
| Representative input | The retained permitted MR 16 Binance BTCUSDT archive snapshot, 2024-06-01 00:00–01:00 UTC. One instrument/partition, 27,480 original trade revisions, no controls/corrections, 88,792,611 canonical bytes. Daily raw ZIP: 7,308,819 bytes / 638,484 CSV rows. No replication, sampling by observed timing or synthetic amplification. |
| Use / retention | Private offline engineering/research, as retained in the acquisition's `use-and-retention.json`; local working copy, no automatic expiry, long-term archival rights unestablished. No download or redistribution. |
| Queries | History for [00:00,00:01) and [00:00,01:00); cutoff for [00:00,01:00). `known_at=01:00 UTC`; columns `revision, price, quantity`; batch size 256. Fully consume and fingerprint exact projected price/quantity strings. |
| Results | Full history: 27,480 heads; minute count determined by the data and reported, not used to select the window. Cutoff: zero eligible rows because original availability and eligibility are unknown; evidence still returns. No synthesized historical clocks/membership. |
| Repetition / concurrency | Three fresh serial processes, each loads once and issues ten cycles of the three queries in fixed order. Concurrency one, no ingestion, no request burst or artificial sleep. Thirty observations per query, three verified opens. First query of each kind per process reported separately. |
| Cache | Reader-cold = fresh process, no retained canonical objects. OS file cache uncontrolled/warm from retained local inputs; no privileged cache eviction. Warm = repeated queries through the same reader; decoding/admission still runs. This does not establish cold-device latency. |
| Hardware | Apple M1 Max, 10 logical CPUs, 64 GiB RAM; macOS 27.0 (26A428), arm64, local APFS storage. Ordinary desktop background load, no competing benchmark/pytest/notebook while timing. CPython 3.14.7, pinned lock. |
| Metrics / decision | Monotonic elapsed seconds, per-query nearest-rank p50/p95/p99 (ceil(p*n)); p99 with 30 samples is only the maximum, not a reliable tail estimate. Every load must meet 300 s; each query p95 must meet 30 s; all process high-water RSS must meet 1 GiB. RSS includes native allocations/imports and allocator retention, not just live objects. |
| Reads | One additional untimed instrumentation process counts actual binary file opens/read calls/returned bytes by path during verified open and one cycle. Includes raw hashing and ZIP access; queries must show whether further reads occur. Application bytes include repeated reads; physical device traffic and decompressed CSV bytes are not inferred from them. |
| Bounds | Existing 256 MiB canonical/per-file admission limit; it is not an RSS ceiling. Load excludes interpreter imports and setup manifest selection, but includes complete `QueryReader.read` verification/materialization. Query timing includes full iteration and result fingerprinting, excludes JSON telemetry. |

The [MR 16 record](mr-16-implementation.md#retained-permitted-binance-sample)
retains original acquisition/quality evidence. Snapshot
`c0f8f3953dee8a15a79d1e9a597e37220c094b3d3c555c8f06d0ec366d3ed278`;
canonical `edf34ab6ea9c74174ec2bf7374a2f49f05781c77d229651a50d8d79cf6496dc5`;
raw `c9c333f58fe33faaa0a34d526c61b13f5648b908c4ad341dd6556e15c5bcc46a`.
Original acquisition run:
`acb948277201cc169d32c2bb874fb40ce9e9c33c893e56a992faa47853147f80`.
Unknown availability, membership and coverage remain explicit degraded scope.
The separate MR 19 synthetic consumer and notebook scenarios establish corrections,
controls, exact values, identity, cancellation and rejection behavior. They are
correctness fixtures, not representative performance evidence.


## Affected scope

Runtime changes are confined to `data/asof.py` and `data/query.py`, with a focused
returned-evidence mutation regression. Existing configuration, codecs, quality,
revision admission, manifest verification and atomic snapshot storage remain the
owning implementations. The [API guide](../../src/alpha_research/data/README.md#bounded-reference-queries-mr-19),
[researcher guide](../../examples/README.md), [NB 18 section 9](../../examples/research-foundations.ipynb)
and [operations guide](../../examples/notebook-operations.md#mr-18-query-workload)
explain the delivered behavior. The frozen P1 specification is unchanged.

Against `0898d0a`, production code-bearing changes are **291 additions + 13 deletions
= 304 lines** under the roadmap's convention: **19 + 13 = 32 runtime lines**, plus
**126** lines in the [reference driver](../../examples/query_workload.py) and **146**
in the [columnar experiment](../../examples/query_columnar_candidate.py). Tests,
notebook scenarios, comments and docstrings are excluded; executable measurement
tooling is included. No declarative runtime configuration, dependency or lock changes.
The small JSON file is measurement evidence, not runtime configuration.

The 154-line overage comes from retaining both reproducible measurements: actual
file-read accounting and fully consumed queries, plus bounded columnar conversion,
exact payload verification and separate scan/profiling modes. Neither is scaffolding.
The workload/driver, bounded candidate and 32-line runtime change have separate
review commits (`1e273ed`, `0180275`, `cae1b06`); each declaration has its working
consumer. Omitting those drivers would make the decision harder to reproduce, and
no invariant or validation was weakened to reduce the count.

## Validation result

### Registered experiment and measured outcome

The original protocol and agreed assumptions were committed at `1e273ed` **before
benchmarking**. The native experiment was registered at `0180275`. After the baseline
failure, admitted-partition reuse was registered/tested at `cae1b06` before its timing.
Budgets, real input and query windows stayed fixed. All raw attempts remain separate;
the small [measurement record](mr-18-measurements.json) retains identities, counts and
individual samples rather than only favorable summaries.

**Optimized installed reference: all three fresh processes and all 90 queries pass.**
Verified-open seconds: **152.080, 152.575, 152.621**. Peak RSS across timing processes:
**819,986,432 bytes**. Thirty fully consumed observations per query:

| Query | Rows | Batches | p50 s | p95 s | p99 s |
| --- | ---: | ---: | ---: | ---: | ---: |
| minute_history | 1,236 | 5 | 4.408 | 4.477 | 4.487 |
| hour_history | 27,480 | 108 | 18.648 | 19.019 | 19.022 |
| hour_cutoff | 0 | 1 | 1.878 | 1.912 | 1.938 |

Nearest-rank percentiles include each process's first call, retained as index zero
in the record; later calls reuse the same reader. At this sample size p99 is the
maximum, not a tail-reliability claim. All query IDs and exact projected-value
fingerprints match the original reference's instrumentation run. History contains
unknown original availability; the empty cutoff still returns degraded evidence.

Verified opening makes **5 file opens, 1,801 read calls and 192,206,647 returned
application bytes**: manifest 3,767; canonical 177,585,222 (two full reads); raw
14,617,658 (hashing plus ZIP access, including repeated ZIP metadata). The optimized
instrumentation run confirms **zero additional file reads** for all three queries.
These are application-level reads, not physical device traffic or decompressed CSV
volume. Both versions read the same inputs; this change reduces repeated admission
CPU/peak allocation, not loading I/O. The cache retains decoded state for the
reader's lifetime; lower peak RSS does not imply lower idle retained memory.

The original reference run stopped with exit 130 after its first load's
**1,261,649,920-byte** RSS failure and first minute query (**85.890403 s**, 1,236 rows).
This is a recorded protocol deviation: remaining planned repetitions were unnecessary
to disqualify memory, and **no baseline p95 is claimed**. Its separate complete I/O
run returned 1,236 / 27,480 / 0 rows with 5 / 108 / 1 batches; instrumented times
85.578 / 90.667 / 83.839 s are diagnostic, excluded from latency acceptance.

### Bounded columnar experiment, not dependency admission

DuckDB **1.5.5**, one thread, 512 MiB engine setting, ZSTD Parquet, 2,048-row groups,
source-position order and exact VARCHAR prices/quantities. The complete revision
payload is retained; timestamp indices use exact integer microseconds. Corrected
conversion took **6.591 s**, peaked at **454,868,992 bytes**, and produced
**2,135,861 bytes** versus 88,792,611 canonical bytes. One fresh process completed ten
minute and ten hour scans with the same counts/value fingerprints. Native scan maxima (nearest-rank p95 for ten samples) were 0.465 s for the minute and 9.987 s for the hour. Individual scan
samples and native profiling observations are in the measurement record. The sidecar
adds storage while original snapshot/raw bytes remain retained; no source is pruned.
DuckDB reported 38,680 / 0 bytes read for minute/hour queries in one profiled connection,
with 27,480 rows scanned reported for each. These cache-sensitive engine counters
are not comparable to Python file-read counts and do not establish physical I/O savings.

This is a scan experiment, not an implementation of cutoff, membership, controls,
verified loading or recovery behind the query API. Native scans exclude those costs
and cannot establish end-to-end backend parity. Full source-payload comparison and
exact revision codec round trips passed separately, without inflating timed scans.
Further planned native timing processes were not run after the smaller complete
reference candidate met the workload; native numbers have **10 samples/query**, not
30, and are not backend qualification. There is no columnar runtime writer/reader
or supported Parquet snapshot format in this change.

Retained failures: the first whole-object native JSON conversion exhausted the
fixed 512 MiB engine budget; bounded 256-row insertion with existing `msgspec`
resolved that. The next conversion indexed the computed `ts_event` property as if
it were serialized; row-count parity failed before acceptance. The retained wire
uses `timestamp` plus `timestamp_unit`; the corrected exact integer index passed.
A later inspection found that the first successful native timing attempt also ran
extra codec round-trip checks. The corrected timed mode was rerun as `candidate-scan-3`;
the separate `verify` and native I/O paths were unchanged and their evidence reused.
Earlier candidates/logs remain separately retained and source snapshots were never
modified. These are experiment/harness failures, not successful backend acceptance.

Executed from `/private/tmp/mr18-validation` (the scan-3 command corrects timing
only; unchanged verification/I/O results are reused):

```sh
uv run --project '/Users/lxg/Documents/GitHub/Alpha Research/alpha-research-lab-private' --frozen --no-sync --with 'duckdb==1.5.5' python -I query_columnar_candidate.py permitted convert > candidate-convert-3.jsonl
uv run --project '/Users/lxg/Documents/GitHub/Alpha Research/alpha-research-lab-private' --frozen --no-sync --with 'duckdb==1.5.5' python -I query_columnar_candidate.py permitted scan > candidate-scan-3.jsonl
uv run --project '/Users/lxg/Documents/GitHub/Alpha Research/alpha-research-lab-private' --frozen --no-sync --with 'duckdb==1.5.5' python -I query_columnar_candidate.py permitted verify > candidate-verify.jsonl
uv run --project '/Users/lxg/Documents/GitHub/Alpha Research/alpha-research-lab-private' --frozen --no-sync --with 'duckdb==1.5.5' python -I query_columnar_candidate.py permitted io > candidate-reads.jsonl
```

The optional package exists only in the isolated `uv run --with 'duckdb==1.5.5'`
environment (14.8 MiB download observed). Admission would add a native dependency,
platform/typing maintenance, source/artifact/license and vulnerability checks, plus
full contract/recovery evidence. That cost is not justified by this workload after
reference reuse. See the checked [Python API](https://duckdb.org/docs/stable/clients/python/overview),
[Parquet documentation](https://duckdb.org/docs/current/data/parquet/overview) and
[repository admission policy](../architecture/dependency-admission.md). The selected
single-user trade operation supplies no ClickHouse/service requirement.

### Tests, static checks and installed consumer

```sh
uv run --frozen --no-editable pytest -q tests/unit/data/test_query.py tests/unit/data/test_asof.py tests/unit/data/test_revisions.py tests/unit/data/test_eligibility_selection.py tests/unit/data/test_quality.py tests/unit/data/test_datasets.py tests/unit/data/test_snapshots.py --tb=short
uv run --frozen --no-sync ruff check src/alpha_research/data/asof.py src/alpha_research/data/query.py tests/unit/data/test_query.py examples/query_workload.py examples/query_columnar_candidate.py examples/research-foundations.ipynb
uv run --frozen --no-sync ruff format --check src/alpha_research/data/asof.py src/alpha_research/data/query.py tests/unit/data/test_query.py examples/query_workload.py examples/query_columnar_candidate.py examples/research-foundations.ipynb
uv run --frozen --no-sync --with 'duckdb==1.5.5' python -m mypy --strict src/alpha_research/data/asof.py src/alpha_research/data/query.py tests/unit/data/test_query.py examples/query_workload.py examples/query_columnar_candidate.py
uv run --frozen --no-sync alpha-governance-engineering-standards
uv run --frozen --no-sync bandit -q -c pyproject.toml src/alpha_research/data/asof.py src/alpha_research/data/query.py
uv run --frozen --no-sync alpha-governance-architecture
```

**113 passed, 3 deselected, no skips.** The unchanged snapshot process-interruption
integration tests retain their existing evidence; no persistence code changed.
Existing tests cover exact revisions, future-only changes, membership, scoped
controls, window-retiring corrections, cancellation, close/reuse, byte bounds,
immutable identity and malformed/tampered admission. The new regression corrupts
returned policy/membership and verifies subsequent queries remain identical. Static
checks passed; native mypy runs through the isolated interpreter that has DuckDB.
Initial formatting/type-boundary findings were corrected. The documentation skill's
referenced `documentation.md` is absent; the engineering guide's owning rules apply.

```sh
uv run --frozen --no-sync uv build --no-build-isolation --wheel --no-sources . --out-dir /private/tmp/mr18-validation/reuse-dist
uv run --frozen --no-sync python /private/tmp/mr18-validation/install_reuse.py
cd /private/tmp/mr18-validation
./reuse-installed/venv/bin/python -I inputs/query_consumer.py inputs
./reuse-installed/venv/bin/python -I query_workload.py permitted timing > reuse-timing-1.jsonl
./reuse-installed/venv/bin/python -I query_workload.py permitted timing > reuse-timing-2.jsonl
./reuse-installed/venv/bin/python -I query_workload.py permitted timing > reuse-timing-3.jsonl
./reuse-installed/venv/bin/python -I query_workload.py permitted io > reuse-reads.jsonl
```

Use a fresh external directory for reproduction; the paths above identify this
executed attempt. The installer is the following existing verification entry:

```python
from pathlib import Path
from alpha_research_governance.wheel_smoke import _InstalledWheelCheck
base = Path("/private/tmp/mr18-validation")
_InstalledWheelCheck.validate(
    Path.cwd(), base / "reuse-installed", next((base / "reuse-dist").glob("*.whl"))
)
```

The temporary installer calls existing `_InstalledWheelCheck.validate(checkout,
external_directory, wheel)`. It exports frozen runtime requirements, installs
hash-locked binary dependencies and the wheel without resolving new dependencies,
and checks compatibility, public imports, exact codecs and governance-free runtime.
All **74 packaged files** match the source, wheel and external installation. Copied
fixture inputs are the existing MR 19 consumer, Binance job/catalog and MR 12
eligibility fixture. This installed consumer passes all its synthetic assertions,
with known eligible counts **0, 0, 0, 64, 32, 0** at seconds 0/5/9/10/43200/9.
It also reopens, rejects tampering, and preserves history after cancellation/close.
Synthetic ZIP metadata varies by attempt; these IDs are per-run correctness evidence,
not the pinned real-data performance input.

Wheel SHA-256: `97be91a0678301d362e863b6ef2ec4deedcb8b8b398a1a616e36124663893355`.
Runtime content SHA-256: `7c03512d77fa1152dc7feb945d708c3a2e794599eb00e09546b204c57c29f9e7`.
Lock SHA-256: `e6cd3a169ff4b6850bcb5b09e38c44e1179b0dc1fb7c6a9bd95d2c4a058595e4`.

### Fresh-kernel NB 18 and retained inputs

```sh
ALPHA_OKX_ARCHIVE_DIRECTORY=data/okx/history/802967bb-05eb-4b7b-9c90-2c964f22e41f ALPHA_BITFINEX_CAPTURE_DIRECTORY=data/bitfinex/a5116c5a-b7d6-4e2b-9ee6-c79839c80f43 uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/research-foundations.ipynb
```

Attempt **`e481c5ec-37d6-435f-a126-28ea73a10eba`** passed all
**40 cells / 21 code cells** in a fresh CPython 3.14.7 kernel. It verified **73 installed runtime files**,
recomputed the decision from retained samples, displayed actual reads and baseline
failure, and reran every earlier contract/failure example. NB 18 deliberately
corrupts a returned synthetic policy: that copy refuses validation, while the next
query remains valid with identical identity and revisions. Tooling stays separate
from the unchanged runtime lock; the runner closes the kernel.
Notebook source SHA-256: `3a1d3b4d1ded24447187a2dab6f8bb79d7937bfadf15dab351e479dcb037bc43`.

The notebook recomputes retained metrics; it does not rerun the expensive benchmark.
Real saved OKX/Bitfinex inputs use the pinned paths above; no new acquisition or
strategy comparison occurs. Pinned trade inputs are retained locally under ignored
`data/silver/mr18-query-workload/`, with original raw acquisition/rights references
under `data/binance-archives/`. Generated full logs, native profiles, failed candidate
and wheel artifacts remain under ignored `examples/runs/mr18-query-workload/` and
`/private/tmp/mr18-validation/`. These local copies are not a backed-up release archive.
If the canonical snapshot is absent, the exact MR 16 publication commands linked
above rebuild it from retained raw/acquisition inputs and explicit empty eligibility.

Maintained `.ipynb`, `.py` and `.md` examples and the small measurement record are
tracked. Generated runs/kernel/checkpoints remain ignored under unchanged policy.
Local links, notebook schema/source/counts/errors, Git diff whitespace, package bytes
and the frozen P1 hash were checked before handoff. P1 SHA-256 remains
`7feb8039724001889060dfeb79138fb4bc78764dcca6683297bc64fb2bd0192d`.
The additional verifier ran as:

```sh
uv run --frozen --no-sync --with 'nbformat==5.10.4' python /private/tmp/mr18-validation/verify.py
git diff --check
git ls-files -- examples/
git check-ignore data/silver/mr18-query-workload/acquisition.json examples/runs/example.ipynb examples/.kernel-example/kernel.json examples/.ipynb_checkpoints/example.ipynb
```

The first component-link verification exposed the checker's file-only limitation
on the existing `../tests/unit/data/` directory link. The final verifier checks
existing directory targets as well as file/heading links; no global checker rule
was changed. All 40 notebook cells, 21 sequential execution counts, source identity,
outputs, links and 74 packaged files passed.

Hosted full checks remain required before merge; no local full `make check` is claimed.

## Risks / reversal

This qualifies one saved, degraded trade-history inspection on the identified host.
It does not qualify physical-cold I/O, sustained ingestion, concurrent analytics,
7M-message days, depth queries, known-availability large selections or P1. `max_bytes`
is a canonical-input budget, not a process RSS ceiling; retained cached state and
future result sizes still need measurement. No historical clocks or membership were
invented. The existing QuantLib release restriction remains unchanged.

Revert the reference-reuse change and examples to restore the prior reader. Snapshot,
query and raw identities/bytes remain compatible; no migration or deletion is needed.
Work stops at MR 18. **MR 20 — Replay with shared event stepping** is next and has
not been started.
