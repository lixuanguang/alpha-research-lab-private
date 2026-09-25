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
ledger and nonnegative fee contract. Shared-account atomic budgets, transfers, rebates and correction posting use
the separate shared account journal below. Physical venue reconciliation,
private-stream recovery and live submission remain adapter work. A fill
received after confirmed terminal cancellation records a durable
`late_terminal_fill` block and raises a reconciliation error; the journal does
not silently reopen a terminal order or rewrite the ledger. Local paper
snapshot matching cannot clear that contradiction.

## Shared account admission and reconciliation

Owner: `execution`. `AccountJournal(path, AccountConfiguration)` implements the
local paper/shadow account increment recorded under
[MR08](../../docs/roadmap/README.md#mr08-delivery-and-acceptance). It uses the same
`OrderDecision`, `OrderState`, `OrderEvent` and `SpotOrderLifecycle` as the dedicated
journal. Existing dedicated journals retain their schema and replay behavior;
they are not silently migrated into shared accounts.

The configuration pins account funding, cash-funded spot grids, instance
instrument authority and [instance/account/firm budgets](../risk/README.md).
Multiple instruments and accounts share one explicit valuation currency. Other
currency cash transfers and rebates can be reconciled; order fees use the quote
currency. Trading
or aggregate risk requiring FX conversion is rejected. Authored grids establish
paper software behavior; they do not qualify current OKX or Bitfinex rules.

`observe(AccountQuote)` is the independent market input. `admit(AccountDecision)`
requires the exact previously observed quote; a decision cannot replace its own
risk mark. UTC quote availability, complete account observation freshness, price
deviation, order size, instrument authority, lot/tick, physical cash, owned
inventory and maximum positions are checked before admission. A decision older
than known account facts cannot use capacity released by a later cancellation.
Trusted source/operator code owns observation, events, reconciliation and block
operations; candidate code supplies intents. These interfaces protect supported
trusted interactions, not hostile code in the same process.

One `BEGIN IMMEDIATE` transaction reads every account, computes exact marked
holdings plus pending/uncertain reservations, checks all three budget levels,
and commits all child legs and the opaque candidate checkpoint. Competing
clients cannot both consume the same headroom. An unfilled sell does not offset
held exposure; buys reserve limit notional and remaining fee allowance. Instance
positions are tagged, targets use only their own positions, and quote legs are
atomic. Crossing opposite orders in an account are rejected. Allocation and
compatible netting remain MR09 work.

`apply_event(OrderEvent)` distinguishes request/accept/cancel acknowledgements,
partial fills, confirmed terminal outcomes and uncertainty. Here `event.at` is
the normalized knowledge/receipt cutoff and `fill.filled_at` retains economic
event time. New events cannot regress the account knowledge clock. Identical
retries and repeated fill identities do not double-post. Unknown orders and
cancel acknowledgements retain capacity over restart. Order and fill/cost
postings commit together using [AccountLedger](../accounting/README.md).

`post(AccountPosting)` applies identified transfers, separate currency fees or
rebates, late fills, and append-only corrections. Every new administrative
posting blocks further admission until reconciliation. Fill and correction
postings retain the reserved order and instance; corrected partial quantities
become uncertain until a normalized terminal/open reconciliation resolves them.
Unpostable source facts remain visible through `failed_postings()` or
`failed_events()` with a durable block. Unsupported shorting, borrowing,
base-asset fee conversion or contradictory source facts cannot be forced into
balance by changing journal bytes.

`reconcile(AccountObservation)` compares currency cash, positions, fees, rebates,
transfers, posting/fill identities and complete cumulative open-order state.
The observation must be at least as recent as the state it certifies. Matching
balances cannot clear unknown orders, an unposted failed fill, or underfunded
pending reservations. Failed observations are retained. `block(account_id,
reason)` persists a separate operator stop which successful reconciliation never
clears. It blocks new exposure; cancellation and accounting remain available.
Block, cancel and reduce-position are distinct; broader resume/activation and
operational commands remain MR10/MR13.

This is an atomic local command service with no venue transport, credential
resolver or submission. Concurrent calls serialize at SQLite; an executing
venue owner's fence and physical reconciliation remain MR11. State is pinned
to exact configuration bytes and uses the `account-runtime-v1` and
`account-postings-v1` contracts. The initial store retains one complete firm
state document and histories per transaction. It establishes correctness for
the reference workload, not MR15 throughput, bounded retention or deployment
readiness. Retain the journal with its configuration and compatible artifact;
never edit accounting history to make a rollback appear compatible.
