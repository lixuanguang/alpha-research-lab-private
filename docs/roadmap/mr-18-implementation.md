# MR 18 — Evaluate the retained trade-query workload

Owner: repository founder. Status: workload registered before measurement on
2026-09-17; results pending. Branch: `codex/mr-18-query-backend`. Base: freshly
fetched `main` at `0898d0a532235b68972590526ce92673b6f8bfee`.
Prerequisites MR 14 (`746e002`, PR #38), MR 15 (`69a45eb`, PR #39), MR 17
(`3deb34b`, PR #42) and MR 19 (`0898d0a`, PR #44) are merged ancestors.
The [roadmap](README.md#m2-research-data-access-and-replay) owns this conditional MR.

## Problem / change

Decide whether a single researcher can inspect retained trade history through
the supported `QueryReader.read` / `batches` interface within an explicitly bounded
offline workflow. The research operation is inspecting exact prices, quantities
and provenance for the opening minute and full hour, then checking whether any
of those observations can support a historical cutoff. This is input diagnosis,
not strategy selection, replay or empirical P1 acceptance.

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

Pending the measurements, preserve the reference reader and existing contracts.
The maintained [benchmark driver](../../examples/query_workload.py) uses installed
APIs without private selector access or runtime instrumentation changes. No backend
or dependency is admitted unless these measurements justify a bounded candidate.

## Validation result

Pending measurements and fresh-kernel checkpoint.

## Risks / reversal

This workload cannot qualify depth analytics, concurrency, sustained ingestion,
7M-message days, historical availability or P1. No saved format or production
implementation changes are planned for a deferral. Reversal removes the benchmark
and record; existing snapshots remain readable. Stop after MR 18; next is
**MR 20 — Replay with shared event stepping**.

### Reference failure and bounded candidate protocol

The first reference open took **155.167771 s**, with **1,261,649,920 bytes** peak RSS.
The first minute-history query took **85.890403 s**, returning **1,236 rows / 5 batches**,
and raised process high-water RSS to **1,267,417,088 bytes**. Memory alone violates
the fixed acceptance rule. Remaining timing repetitions were interrupted (exit 130)
during the first hour-history query to avoid an already-disqualified, roughly
45-minute repetition plan. This is an explicit protocol deviation; no completed
reference p95 or warm-performance claim is made. A separate instrumentation run
still consumes all three queries and retains actual read counts and result identities.

Before candidate measurement, select **DuckDB 1.5.5 + ZSTD Parquet**, one file for
this one partition, source-position order, 2,048-row groups, one engine thread,
512 MiB engine memory setting (not a process RSS limit). Retain each complete revision
JSON plus exact VARCHAR price/quantity and a UTC timestamp index. The native scan
experiment reads/decodes full revision payloads in 256-row batches, validates exact
projection and fingerprints output in source order. A separate untimed verification
pass checks full revision codec round trips so these extra checks do not distort query latency.
Use the same minute/hour windows and thirty observations each (three fresh processes,
ten repetitions); instrument native scan bytes separately with DuckDB's profiler.
Measure conversion separately. Cutoff/control/eligibility selection is **not**
implemented in this storage experiment, so it cannot replace `QueryReader` by itself.

The hypothesis is that a compact columnar representation reduces storage/read cost
and makes the selected exact history scans feasible. Fast native scans alone are
insufficient: the full verified input/semantic contract, including source verification,
revisions, eligibility, controls, immutable identity and recovery, must fit the budget
before backend admission. Preserve the existing verified reader as the conservative
end-to-end boundary; its known memory cost cannot be subtracted from candidate
qualification. No dependency is added to runtime metadata or the lock for this
pre-admission experiment. Broader validation redesign is not silently accepted as
part of a scan benchmark.

The [DuckDB Python API](https://duckdb.org/docs/stable/clients/python/overview),
[Parquet documentation](https://duckdb.org/docs/current/data/parquet/overview) and
[conversion rules](https://duckdb.org/docs/current/clients/python/conversion) were
checked on 2026-09-17. Dependency admission would additionally require the repository's
[artifact/license/platform/source and vulnerability checks](../architecture/dependency-admission.md),
plus maintained adapter typing and cross-platform installed parity. A single-user
trade workload supplies no reason to introduce ClickHouse or a service here.

### Reference reuse candidate registered before remeasurement

The bounded Parquet scan shows promising storage/query costs but does not replace
verified loading or implement the entire query contract. Test the cheaper admitted-
partition reuse candidate under the **same** workload, repetitions and budgets
before any dependency admission. Complete admission stays at reader construction;
`AsOfSelector` caches its admitted partitions and deep-copies selected results.
`QueryReader` copies evidence and history rows at the output-batch boundary. Thus
returned unsafe mutations cannot poison later queries. Canonical admission compares
deterministically encoded fields as raw JSON bytes rather than allocating two
additional complete Python dictionary trees. No value, clock, revision, membership,
control, identity or persistence rule changes.

Before measurement, **113 focused tests passed, 3 unchanged process-interruption
integration tests deselected**, and changed source/test Ruff/format/strict mypy checks
passed. Existing unsafe revision-mutation checks pass; a new regression mutates
returned policy/membership and confirms subsequent queries remain identical.
The candidate remains conditional until an installed wheel meets the original
budgets. Failed baseline/candidate attempts remain part of this record.
