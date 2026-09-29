# Account journal history storage

Owner: quant development. Status: **storage, governance and deployment implemented
on branches 2026-09-29, not merged; storage qualification passed, retained replay
failed and replaced by the signed cohort's own parity; signed stage-1 cohort
passed**. Stage-2 sustained operation remains separate. Policy approved by the
owner on 2026-09-29. Baseline: `main` at `9ae6fb1`. This page is a stage-2
prerequisite for
[MR15 runtime capacity](runtime-capacity.md#lifecycle-authority-and-acceptance-stages).
It grants no trading authority and changes no budget, grant or risk limit.

## Measured problem

The account journal stored the complete firm state as one JSON document in
`firm.payload` ([`account_state.py`](../../src/execution/account_state.py)). After
the v5 feature cohort (one initial and five one-minute recovery intervals) the
OKX shared journal held 1,869,654 bytes:

| Collection | Items | Encoded bytes |
| --- | ---: | ---: |
| `portfolio_batches` | 126 | 828,257 |
| `decisions` | 252 | 685,888 |
| `paper_traces` | 131 | 361,201 |
| All other fields | — | about 60,000 |

Three collections held about 97% of the document and grow with every selected
book. Orders are bounded by the 80-order daily grant; accounts, activations,
bindings and controls stay small. On that journal a fresh process decoded the
typed state in 211–222 ms. Before the incremental encoder in `e3dc3e2`, a commit
took a median 27.0 ms, mostly re-encoding; with it, 9.3 ms, almost all SQLite
work rewriting the whole blob (WAL write and fsync 3.7 ms, connection-close
checkpoint 2.5 ms, update 2 ms).

At the stage-2 selection rate the document would reach roughly 300 MB per account
per day. Per-commit I/O would then take hundreds of milliseconds and a cold
decode tens of seconds, which exceeds the 40-second recovery progress budget.

The hot path reads this history only to check idempotency by identity (batch,
instance plus decision, venue/instrument/market), to find the latest checkpoint
for an instance, and to produce reports. None needs the full history in memory.

## Policy

- `account-journal` is the only account state schema. Code, governance records,
  installation policy and `PaperDeployment.state_schema` admit nothing else, and no
  earlier journal format is read, converted or migrated.
- Every installed account release is managed: the installer passes its release
  identity to every account command, and activation is recorded only by the
  presence of `paper_activations`.
- Migration and rollback: completed 2026-09-29; journals in earlier formats are
  refused, never converted.

## Storage layout

- `firm(id=1, configuration, payload)`: the configuration column is unchanged.
  The payload is the live head: every current field except the three growing
  collections, the latest checkpoint per instance and, for each collection, its
  item count and a sha256 hash chain over its item bytes.
- `decisions(seq, instance_id, decision_identity, payload)`: unique on
  `(instance_id, decision_identity)`, indexed on `(instance_id, seq)`.
- `portfolio_batches(seq, batch_identity, payload)`: unique on `batch_identity`.
- `paper_traces(seq, account_id, venue, instrument_id, market_identity, payload)`:
  unique on the lookup key, indexed by market identity and by account.

Each `payload` holds the item's exact codec bytes. A commit inserts the
transaction's new rows and rewrites the head inside the existing `BEGIN IMMEDIATE`
transaction, so isolation and the no-over-admission guarantee are unchanged. A
fresh process decodes only the head; reads hold one read transaction per snapshot.
`AccountJournal.verify` checks every row, its key columns and the head's counts,
hash chains and checkpoints. The installer's pristine first-install comparison
hashes every table.

## Delivery

1. **History access API.** `find_decision`, `latest_checkpoint`, `find_batch`,
   `find_trace`, `iter_traces` and `append_*` on the snapshot and transaction
   replaced every direct scan of the three collections in `src/execution`, with
   stored bytes unchanged.
2. **History tables.** The store above, behind the same API. Before the whole-state
   format was removed, the same operation sequence produced identical public
   projections in both formats, the tables reproduced the whole-state document byte
   for byte, and the account-journal unit suites passed on both.
3. **Governance and deployment.** Release records, installation policy, the
   installer's paper-scope and pristine-state checks, `PaperDeployment` and the
   [operations runbook](../governance/operations.md) admit only
   `account-journal`; unmanaged installed account releases and the signed account
   installation consumer were removed.

## Qualification declaration (2026-09-29)

Declared before any measurement. One run; a missed target is recorded as a failure
and is not retried with a changed workload, method or target. The run uses the
[history capacity consumer](../../tests/integration/consumers/runtime/account_history_capacity.py)
at the commit that adds this declaration, and retains raw results under ignored
`logs/account-history/qualification-1/`; the compact record was
`docs/roadmap/account-journal-history-evidence.json` (removed 2026-09-29; kept in
git history).

**Host.** The declared Apple M1 Max, 10 logical cores, 64 GiB RAM, macOS 27.0,
APFS, on AC power. The filesystem cache is uncontrolled and warm after the first
read; this is application-cold evidence, not filesystem-cold. No collector, build,
test or other qualification runs concurrently.

**Synthetic 24-hour history, one account.** Two instances and one instrument.
30,000 portfolio batches of two decisions each (60,000 decisions) and 30,000 paper
traces: one batch and one trace every 2.88 seconds. Items are clones of the items a
real journal writes for the consumer's compact scenario (opening reconciliation, a
coordinated two-instance batch and a public market match), with fresh identities, a
recomputed trace input digest and a 675-byte synthetic checkpoint per decision. The
head is that scenario's real head. History is written through the store's own
`write()`/`append_*` path in unmeasured fill transactions of 100 batches, 200
decisions and 100 traces. Mean item bytes are reported against the measured
single-document means (batch 6,574, decision 2,722, trace 2,757).

**Measures and targets.** Percentiles are empirical nearest-rank.

| Measure | Method | Target |
| --- | --- | --- |
| Batch commit | 1,000 timed complete `write()` transactions at full history: `find_batch`, two `find_decision` and two `latest_checkpoint` lookups, append two decisions and one batch | p99 ≤ 5 ms |
| Trace commit | 1,000 timed transactions alternating with the batch commits: `find_trace` by venue/instrument and by account, newest account/instrument trace, append one trace | p99 ≤ 5 ms |
| Cold open | 1,000 in-process opens of the full journal, each with a new codec and store, through the first `read()` | p99 ≤ 100 ms |
| Fresh-process open | 20 opens in new interpreters, imports excluded | reported |
| Memory | New interpreter per history level (0, 25, 50, 75 and 100%, on copies), each opening and running 200 commits of each kind; peak RSS | 100% minus 0% ≤ 16 MiB |
| Disk | Database bytes at full history after a truncating WAL checkpoint, per account-day and for four accounts against the 120 GiB canonical budget | reported |
| Verification | `verify()` duration at full history | reported |

Report projections that return a whole history (`paper_traces()`,
`paper_report_facts()`) are excluded from the memory measure; they are
proportional to history by design.

**Retained replay.** With this code, the maintained
[economic parity consumer](../../tests/integration/consumers/runtime/capacity_parity.py)
replays the v5 cohort's `initial-steady` trial (four accounts) and, with that trial
as baseline, the `recovery-01` suffix into fresh journals. Pass requires every
account's seven economic-fact comparisons to be equal (replay hash equals signed
hash) and, for `initial-steady`, every replay hash to equal the original parity
result's. The installed-identity match is false by construction and is not a
criterion. The single-baseline suffix replay cannot rebuild the chained
`recovery-02`–`05` intervals; they are not claimed.

**Not in this run.** Fresh signed releases and deployments, and the stage-1 steady,
recovery and loaded-fault cohort under the unchanged gates, remain required before
any stage-2 use and need a separate go-ahead.

## Qualification result (2026-09-29)

One run at the declaration commit `d63f54c` on the declared host, with nothing else
running. Compact record: account-journal-history-evidence.json (removed 2026-09-29; kept in git history);
raw samples stay under ignored `logs/account-history/qualification-1/`.

**Storage: passed.** At the full 24-hour history of one account:

| Measure | p50 | p95 | p99 | Maximum | Target | Result |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| Batch commit (1,000) | 1.54 ms | 1.96 ms | 2.56 ms | 6.20 ms | p99 ≤ 5 ms | pass |
| Trace commit (1,000) | 2.61 ms | 3.05 ms | 3.39 ms | 7.73 ms | p99 ≤ 5 ms | pass |
| Cold open (1,000) | 5.03 ms | 5.54 ms | 5.79 ms | 11.57 ms | p99 ≤ 100 ms | pass |
| Fresh-process open (20) | 8.76 ms | — | — | 19.26 ms | reported | — |

Peak RSS was 53.9–54.1 MB at every level from empty to full history; growth was
0.25 MiB against the 16 MiB limit. The full-history journal occupies 726 MB, so four
accounts fit about 44 account-days in the 120 GiB canonical budget. Mean item bytes
were 9,420 per batch, 2,702 per decision and 5,788 per trace, against reference
means of 6,574, 2,722 and 2,757: the batch and trace templates are 1.43 and 2.10
times heavier, so the disk figure is conservative.

`verify()` took 126.2 s at full history because it decodes and validates every row.
It runs only in workspace backup and restore of stopped accounts, not in live
recovery or the installer's candidate check, but a 24-hour journal's backup or
restore now spends about two minutes verifying.

**Retained replay: failed.** No delivery was replayed. Every signed final result of
the v5 `initial-steady` and `recovery-01` trials records its paper deployment with
`state_schema: "account-journal-v3"`, which `PaperDeployment` no longer admits, so
all eight account replays stopped at decoding. This follows from removing every
earlier journal schema, including from retained result records. The replay checker
first rejected the original parity report, which predates the
`installed_identity_match` field; that field was made optional in the checker alone
and the check was rerun on the same outputs, failing both times.

Equivalence with the earlier format therefore rests on the delivery-step evidence
taken before it was removed: identical public projections for the same operations,
byte-identical document reconstruction, and the account-journal suites passing on
both formats. A retained-delivery replay now needs retained results written by this
code, which only a new signed cohort produces.

**Not run.** Fresh signed releases and deployments and the stage-1 steady, recovery
and loaded-fault cohort remain required before any stage-2 use.

## Decisions after qualification (2026-09-29)

The owner delegated three decisions; each follows from the code and records above.

1. **Run the signed stage-1 cohort once.** It is the remaining prerequisite, and
   earlier signed attempts stopped only because failures were being retried. This
   cohort is predeclared below, runs each trial once and records a failure without
   retrying it.
2. **Replace the retained-delivery replay.** Retained v5 results record an earlier
   journal schema that this code does not decode, by policy. The replay's purpose,
   economic equivalence on real deliveries, is served by the cohort's own parity:
   the maintained parity consumer replays each new signed trial's exact deliveries,
   and for recovery its operator controls and native suffix, into fresh journals
   and requires every economic fact to match. Stage-2 equivalence rests on that and
   on the dual-format evidence taken before the earlier format was removed.
3. **Keep `verify()` as it is.** Profiling at full history attributes the 126 s to
   strict per-field revalidation of the units models (0.4–1.9 ms per row typed
   against 7–42 µs untyped JSON), which the units library requires by design. It
   runs only for stopped-account backup and restore, which have no time budget, and
   the earlier format paid the same per-item cost on every open. Revisit only if a
   backup or restore budget is declared.

## Signed stage-1 declaration (2026-09-29)

Declared before any build or trial. The candidate is the source at the commit that
adds this declaration, frozen by hash; drivers and retained evidence live under
ignored `logs/account-history/stage1/`, ported from the candidate-10 drivers with
only these changes: new paths, a v4-only policy and build requests, a wheel fetch,
no historical one-sided replay (superseded by the
[reattribution](runtime-capacity.md#reattribution-and-harness-corrections-2026-09-29)),
and an added recovery-suffix parity.

**Candidate and authority.** Four signed execution `paper` targets (OKX shared and
isolated, Bitfinex shared and isolated) with `account-runtime` configuration and
`account-journal` state. They are built by a new ephemeral local builder,
`local-account-history`, whose private key is mode 0600 outside the repository; the
earlier builder key did not survive a host restart. Its installation policy trusts
only that builder for seven days and admits only those two schemas. Dependencies are
fetched from the lock with verified hashes. Fresh journals, disabled deployments
and ordinary one-hour grants with the unchanged 80-order and 100-unit limits; no
grant, service lifetime, budget or risk limit changes.

**Sequence, each once, stopping at the first failure.**

1. Freeze source and consumers; fetch, build, verify and install four targets.
2. Steady trial on the declared native fixture with the MR15 stage-1 shape: 120-second
   accounts, 100-second capture, 75-second supervisor, at least 60 measured seconds
   with the declared burst and four depth plus four dashboard readers at 5 Hz.
3. Steady economic parity: every account's seven economic facts equal the signed
   facts, the first-touch oracle holds and the installed identities match.
4. Steady gate assessment and topology/lifetime retention with the unchanged
   candidate-10 gates: health, receipt-to-durable, durable-to-BBO, queue, coverage,
   capture completion and size, query budgets, resources (average CPU ≤ 7 cores,
   RSS ≤ 24 GiB, occupied ≤ 320 GiB) and complete shutdown delivery accounting.
5. Recovery trial of the same candidate with replacement owners, then preservation
   and all-eight progress, the same gates, and the independent recovery-suffix
   parity against the steady trial.
6. Loaded-fault trial on separately installed targets of the same releases.
7. Cleanup audit: every observed process absent and all four accounts stopped.
8. `make check` on the unchanged frozen source.

Public routes, feature serving, cold-cache boundaries and stage 2 are not in this
cohort.

## Signed stage-1 result (2026-09-29)

Passed at declaration commit `c80912b`, installed implementation `aacae36c…`, with
four signed releases of that frozen source. Every phase ran once; the compact record
is `signed_stage1` in
account-journal-history-evidence.json (removed 2026-09-29; kept in git history).

| Phase | Result |
| --- | --- |
| Steady (60.005 measured s, 121 health witnesses) | All gates pass; CPU 2.02 cores average, RSS 2.45 GiB, occupied 0.25 GiB; query response p99 31.1 ms depth/BBO and 119.5 ms dashboard |
| Steady economic parity | Qualified: all seven facts equal and the first-touch oracle holds on all four accounts; installed identities match |
| Recovery (60.005 s, 122 witnesses) | All gates pass; economics preserved; first replacement claim to all-eight progress 7.66 s against 40 s; query p99 34.7 and 120.9 ms |
| Recovery-suffix parity | Qualified on all four accounts: baseline, operator controls and native suffix replayed into fresh journals |
| Loaded faults | Passed with no failures |
| Cleanup | Every observed process absent in all three trials; all four accounts stopped |
| `make check` | Passed on the unchanged frozen source |

One build attempt was refused before any grant or trial, because a six-day release
validity ended after the 2026-10-04 dependency-admission review date. It is
retained at `logs/account-history/stage1-build-attempt-1`; the rebuild used a four-day
validity and changed nothing else.

This characterizes the finite stage-1 envelope on the tabled journal. It is not
public-route health, integrated feature serving, cold-cache evidence or stage-2
sustained acceptance, which still needs a longer bounded service life or handoff,
signed capture rollover and extended finite grants.

