# Dedicated paper order journal

`PaperOrderJournal` owns one account, instrument and strategy instance in paper or
shadow mode. It has no venue client, credentials or submit operation. The caller
supplies a candidate binding identity, exact `SpotLimits` and a `LedgerState`.
Opening an existing journal rejects a changed binding, mode, limits or initial
ledger. `claim(owner)` takes a nonblocking POSIX file lock and increments the
persisted writer epoch. Each mutation checks both the local lock and epoch.

`commit_step` saves opaque candidate checkpoint bytes, source/result bytes, the
portable `OrderDecision`, a visible admission result and all child orders in one
SQLite transaction. A repeated step with the same bytes returns its result;
changed bytes under the same step ID fail. Child IDs are stable over restart and
quote legs are admitted together. Fixed authored spot grids without a selected
reference identity have `qualification == "fixture"`; they are usable for
modeled paper/shadow work only. A selected reference identity has
`qualification == "referenced"` but venue rule freshness remains the caller's
responsibility. Neither qualification grants executable authority.

`claim_market` binds each modeled quote identity to exact immutable bytes before
matching effects. `markets()` exposes claims in insertion order so a supervising
runtime can finish interrupted work before advancing its recovery clock. A quote
with different bytes under the same identity cannot create a new fill identity or
obtain another allowance of displayed liquidity.

Unfilled buy limit notional plus each order's unspent maximum fee reserves cash;
unfilled sells reserve inventory. An unresolved order, including an unknown
outcome or an acknowledged cancellation, keeps its reservation. Only a confirmed
fill, cancellation or rejection changes that commitment. Accepted fill identities
post to the exact spot ledger once. `events(after_sequence)` replays committed
facts and their then-current account balances after a runtime callback cursor.
A mismatch in the caller's independently
observed paper account snapshot is saved as `account_break` and rejects new risk
until a matching reconciliation; cancellation and lifecycle events remain usable.
`claim_market` binds each modeled quote identity to its exact payload in a
fenced transaction before the matcher writes any acknowledgement or fill.
`markets()` replays these claims in insertion order, including a quote interrupted
before its candidate market step; a changed retry under the same identity fails.

This bounded journal uses the existing single-instrument, cash-funded spot
ledger and nonnegative fee contract. Shared-account atomic budgets, transfers,
rebates, physical venue reconciliation, private-stream recovery, order
corrections and live submission belong to later account and adapter work. A fill
received after confirmed terminal cancellation records a durable
`late_terminal_fill` block and raises a reconciliation error; the journal does
not silently reopen a terminal order or rewrite the ledger. Local paper
snapshot matching cannot clear that contradiction.
