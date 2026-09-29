# Account journal history storage

Owner: quant development. Status: **storage, governance and deployment implemented
on branches 2026-09-29, not merged; qualification next**. Policy approved by the
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

- `account-journal-v4` is the only account state schema. Code, governance records,
  installation policy and `PaperDeployment.state_schema` admit nothing else, and no
  earlier journal format is read, converted or migrated.
- Journals written before this change are not readable by this code. Retained
  evidence journals are read with the release that wrote them.
- Every installed account release is managed: the installer passes its release
  identity to every account command, and activation is recorded only by the
  presence of `paper_activations`.
- Earlier releases fail closed on these journals: the `firm` row remains, holding
  a head that whole-state decoders reject. Removing the row is not acceptable,
  because older code would create a newly funded journal.
- Rollback across this change means stopping, retaining the journal as evidence and
  installing an earlier release on fresh state.

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
   `account-journal-v4`; unmanaged installed account releases and the signed account
   installation consumer were removed.

## Qualification declaration (2026-09-29)

Declared before any measurement. One run; a missed target is recorded as a failure
and is not retried with a changed workload, method or target. The run uses the
[history capacity consumer](../../tests/integration/consumers/runtime/account_history_capacity.py)
at the commit that adds this declaration, and retains raw results under ignored
`logs/account-history/qualification-1/`; the compact record will be
`docs/roadmap/account-journal-history-evidence.json`.

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
