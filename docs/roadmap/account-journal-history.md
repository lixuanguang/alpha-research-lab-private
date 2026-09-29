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

## Qualification

Predeclare before measurement. Provisional targets on the declared M1 Max host,
for a synthetic 24-hour history of about 30,000 batches, 60,000 decisions and
30,000 traces per account: commit p99 at most 5 ms, cold open at most 100 ms,
resident memory independent of history size, and occupied disk reported against
the 120 GiB canonical budget. Replay retained v5 cohort deliveries into fresh
journals with identical economic-fact hashes. Then issue fresh signed releases and
deployments and rerun a stage-1 steady, recovery and loaded-fault cohort under the
unchanged gates before any stage-2 use.
