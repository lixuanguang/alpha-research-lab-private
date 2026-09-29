# Account journal v4 migration plan

Owner: quant development. Status: **plan declared 2026-09-29; phase 1 next; v4
policy and the optional offline conversion tool await owner approval**. Baseline:
`main` at `9ae6fb1`. This page is a stage-2 prerequisite for
[MR15 runtime capacity](runtime-capacity.md#lifecycle-authority-and-acceptance-stages).
It grants no trading authority and changes no budget, grant or risk limit.

## Measured problem

The account journal stores the complete firm state as one JSON document in
`firm.payload` ([`account_state.py`](../../src/execution/account_state.py)). After
the v5 feature cohort (one initial and five one-minute recovery intervals) the
OKX shared journal held 1,869,654 bytes:

| Collection | Items | Encoded bytes |
| --- | ---: | ---: |
| `portfolio_batches` | 126 | 828,257 |
| `decisions` | 252 | 685,888 |
| `paper_traces` | 131 | 361,201 |
| All other fields | — | about 60,000 |

Three collections hold about 97% of the document and grow with every selected
book. Orders are bounded by the 80-order daily grant; accounts, activations,
bindings and controls stay small. On that journal a fresh process decodes the
typed state in 211–222 ms. Before the incremental encoder in `e3dc3e2`, a commit
took a median 27.0 ms, mostly re-encoding; now it takes 9.3 ms, almost all SQLite
work rewriting the whole blob (WAL write and fsync 3.7 ms, connection-close
checkpoint 2.5 ms, update 2 ms).

At the stage-2 selection rate the document reaches roughly 300 MB per account
per day. Per-commit I/O would then take hundreds of milliseconds and a cold
decode tens of seconds, which exceeds the 40-second recovery progress budget.
Compaction alone keeps the whole-document cost; splitting storage while still
loading all history fixes commits but not cold start or memory.

The hot path reads this history only to check idempotency by identity (batch,
instance plus decision, venue/instrument/market), to find the latest checkpoint
for an instance, and to produce reports. None needs the full history in memory.

## Policy

- v4 applies to newly installed state only. The installer already refuses a
  release whose `state_schema` differs from the installed one, and in-place
  signed v2-to-v3 migration was never admitted; v4 follows that precedent.
  Stage-2 trials use fresh journals, deployments and grants in any case.
- Retained v3 journals stay v3. v4 code keeps a read-only v3 reader so existing
  replay and parity tooling continues to work on retained evidence.
- Old releases must fail closed. The `firm` row remains, with a head payload
  declaring `schema_version: "account-journal-v4"`, which v2/v3 code rejects.
  Removing the row is not acceptable: old code would create a newly funded journal.
- Rollback never converts back. Stop, retain the v4 journal as evidence and
  reinstall the previous release on fresh v3 state.

## Storage layout

- `firm(id=1, configuration, payload)`: the configuration column is unchanged.
  The payload is the live head: every current field except the three growing
  collections, plus the latest checkpoint per instance and, for each collection,
  its item count and a running sha256 over its item bytes.
- `decisions(seq, instance_id, decision_identity, payload)`: unique on
  `(instance_id, decision_identity)`, indexed on `(instance_id, seq)`.
- `portfolio_batches(seq, batch_identity, payload)`: unique on `batch_identity`.
- `paper_traces(seq, account_id, venue, instrument_id, market_identity, payload)`:
  unique on the lookup key.

Each `payload` holds the item's exact codec bytes as they appear inside the v3
document. `materialize()` can therefore rebuild the complete v3 document byte for
byte apart from `schema_version`, which is the basis of every equivalence proof
below. Commits stay inside the existing `BEGIN IMMEDIATE` transaction, so
isolation and the no-over-admission guarantee are unchanged.

## Phases

### Phase 1 — history access API, format unchanged

Add history methods to `_AccountTransaction` and the read paths: `find_decision`,
`latest_checkpoint`, `find_batch`, `find_trace`, `iter_traces` and `append_*`.
Implement them over the existing tuples and convert every direct scan of
`decisions`, `portfolio_batches` and `paper_traces` state in `src/execution`. At
the baseline these are in `accounts.py`, `account_portfolio.py`,
`account_paper.py`, `account_reduction.py`, `account_commands.py`,
`installed_account.py` and `paper_monitoring.py`; confirm each hit is firm state,
since several unrelated objects share these attribute names. Public
`AccountJournal` signatures do not change.

Exit: journals remain byte-identical, checked by a temporary per-commit comparison
with a full encode across the whole suite; the full suite, strict typing and
engineering checks pass; retained economic replay hashes are unchanged. Phase 1
can merge on its own and also removes linear scans from the hot path.

### Phase 2 — v4 store behind the same API

Implement the history methods over the tables above; a commit writes the head and
inserted rows only, and a cold open decodes only the head. New journals are v4;
v3 files open read-only. `install_paper` binds activation without the v2-to-v3
promotion; activation is the presence of `paper_activations`. `verify()` checks
head counts and digests against the tables. One shared loader replaces every
direct `firm.payload` read in `src`.

Exit: the same operation sequence on v3 and v4 yields identical public
projections; `materialize()` of a v4 journal reproduces the v3 bytes; v3 code
fails closed on a v4 file.

### Phase 3 — governance and deployment

Admit v4 in the governance release records and release policy `state_schemas`;
widen the installer's v3-only paper-scope checks to v3 or v4; hash the head and
every history table in the pristine first-install comparison; admit v4 in
`PaperDeployment.state_schema`; document v4 installation in
[operations](../governance/operations.md).

Exit: release build, installation and inspect tests pass for v4 and still pass
for v3, including a refused in-place v3-to-v4 installation.

### Phase 4 — offline conversion, evidence only (optional)

A tool that writes a new v4 file from a v3 file, never in place and never over an
existing file. Run it on the retained stage-1 and v5 target journals to prove
`materialize()` equals the original bytes and that economic facts are identical.
It is not an operational upgrade path.

### Phase 5 — qualification

Predeclare before measurement. Provisional targets on the declared M1 Max host,
for a synthetic 24-hour history of about 30,000 batches, 60,000 decisions and
30,000 traces per account: commit p99 at most 5 ms, cold open at most 100 ms,
resident memory independent of history size, and occupied disk reported against
the 120 GiB canonical budget. Replay retained v5 deliveries into fresh v4 journals
with identical economic-fact hashes. Then issue fresh signed releases and
deployments and rerun a stage-1 steady, recovery and loaded-fault cohort under the
unchanged gates before any stage-2 use.

## Open decisions

- Approve the v4 policy: fresh installation only, retained v3 read-only, rollback
  by reinstalling rather than converting.
- Decide whether phase 4 is wanted or retained v3 evidence stays as is.

Phase 1 depends on neither decision.
