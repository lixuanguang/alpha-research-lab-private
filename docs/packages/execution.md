# Dedicated paper order journal

`PaperOrderJournal` owns one account, instrument and strategy instance in paper or
shadow mode. It has no venue client, credentials or submit operation. The caller
supplies a candidate binding identity, exact `SpotLimits` and a `LedgerState`.
Opening an existing journal rejects a changed binding, mode, limits or initial
ledger. Each event row records its kind, checked against the current order-event
vocabulary, so a journal written under another vocabulary, including one from
before terminal cancellations stated their cause, is refused as an unsupported
paper journal schema and never migrated. `claim(owner)` takes a nonblocking POSIX file lock and increments the
persisted writer epoch. Each mutation checks both the local lock and epoch.

`commit_step` saves opaque candidate checkpoint bytes, source/result bytes, the
portable `OrderDecision`, a visible admission result and all child orders in one
SQLite transaction. A target or exposure decision also names the `MarketTouch`
it was decided on, and the shared `SpotOrderLifecycle` lowers it to one IOC that
crosses the touch on its own side: a buy at the ask, a sell at the bid. Exposure
converts to whole lots at the touch midpoint, as research simulation converts
it. Dedicated and shared accounts lower identically. A repeated step with the
same bytes returns its result; changed bytes under the same step ID fail. Child IDs are stable over restart and
quote legs are admitted together. Fixed authored spot grids without a selected
reference identity have `qualification == "fixture"`; they are usable for
modeled paper/shadow work only. A selected reference identity has
`qualification == "referenced"` but venue rule freshness remains the caller's
responsibility. Neither qualification grants executable authority.

Paper matching claims each modeled quote identity with exact immutable bytes in
the same transaction as its effects; shadow mode uses `claim_market` to record a
quote before its step commits. `markets()` exposes claims in insertion order so a supervising
runtime can finish interrupted work before advancing its recovery clock. A quote
with different bytes under the same identity cannot create a new fill identity or
obtain another allowance of displayed liquidity.

Unfilled buy limit notional plus each order's unspent maximum fee reserves cash;
unfilled sells reserve inventory. An unresolved order, including an unknown
outcome or an acknowledged cancellation, keeps its reservation. Only a confirmed
fill, cancellation or rejection changes that commitment. A terminal cancellation
states its cause. `cancelled_on_request` is positive evidence that a pending cancel
request took effect; `cancelled` states no cause and covers an order that ended on
its own terms, such as an immediate-or-cancel or stranded remainder, and any
cancellation whose producer cannot attribute it. The lifecycle accepts
`cancelled_on_request` only for an order with a pending request and a known
outcome; both end in status `cancelled`. Accepted fill identities
post to the exact spot ledger once. `events(after_sequence)` replays committed
facts and their then-current account balances after a runtime callback cursor.
A mismatch in the caller's independently
observed paper account snapshot is saved as `account_break` and rejects new risk
until a matching reconciliation; cancellation and lifecycle events remain usable.

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
local paper/shadow account. It uses the same
`OrderDecision`, `OrderState`, `OrderEvent` and `SpotOrderLifecycle` as the dedicated
journal. Existing dedicated journals retain their schema and replay behavior;
they are not silently migrated into shared accounts.

[`accounts.py`](../../src/execution/accounts.py) remains the supported journal and record import
surface. The concrete wire records live in [`account_records.py`](../../src/execution/account_records.py),
while [`account_state.py`](../../src/execution/account_state.py) owns the SQLite journal and transaction
boundary. Decisions, portfolio batches and paper traces are read only through the
snapshot and transaction history lookups by identity (`find_decision`,
`latest_checkpoint`, `find_batch`, `find_trace`, `iter_traces`) and written through
`append_*`, so callers do not depend on where history is stored.

The `firm` row holds the journal head: the current state without the three history
collections and without the state that grows with history, each collection's row count
and sha256 hash chain, and every instance's latest checkpoint. The collections live in
their own tables with each item's exact codec bytes. Orders, net orders, events,
net events, reconciliations, native fills, physical reconciliations and each account's
postings are kept in `state_rows`, one row per tuple position with the item's exact
codec bytes and sha256; the head keeps each field's row count and a sha256 over its row
digests in order. A commit writes only changed or new rows and a head of bounded size;
another process reads the head, compares row digests and decodes only rows that
changed. In memory the state still holds the complete tuples, so account behavior does
not depend on this layout. Each paper trace row also records whether the trace posted
a modeled fill (`filled`), checked against its bytes on verification, and only those
rows are indexed for fills: report facts decode the fill-bearing traces alone, so a
cold read does not grow with the number of books matched. Only this `account-journal`
layout is readable: a journal with other tables, columns or indexes, including one
without `state_rows`, `dispatch_leases` or the trace fill flag, is refused as an
unsupported account journal schema and is never migrated. The head also names
the order-event vocabulary its facts are written in; a head without one, as written
before terminal cancellations stated their cause, or with another vocabulary is
refused as an unsupported account journal state schema. The journal composes admission and reconciliation from
[`account_admission.py`](../../src/execution/account_admission.py), physical fill and fee attribution
from [`account_allocation.py`](../../src/execution/account_allocation.py), and atomic portfolio order
formation and instance controls from [`account_portfolio.py`](../../src/execution/account_portfolio.py).

The configuration pins account funding, cash-funded spot grids, instance
instrument authority and [instance/account/firm budgets](risk.md).
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
held exposure; buys reserve limit notional and remaining fee allowance. Budget
ceilings bound buys only: a sell, which owned inventory bounds, never meets one,
so a strategy that price moves took over its ceiling can still reduce. Instance
positions are tagged, targets use only their own positions, and quote legs are
atomic. The direct tagged-order path rejects crossing opposite orders. The
coordinated portfolio path below adds explicit compatible crossing and physical
aggregation.

`apply_event(OrderEvent)` distinguishes request/accept/cancel acknowledgements,
partial fills, confirmed terminal outcomes and uncertainty. Here `event.at` is
the normalized knowledge/receipt cutoff and `fill.filled_at` retains economic
event time. New events cannot regress the account knowledge clock. Identical
retries and repeated fill identities do not double-post. Unknown orders and
cancel acknowledgements retain capacity over restart. A cancel request, including
one from a strategy or account stop, and a venue's acknowledgement of it are
recorded beside an unknown outcome but leave it unknown: only reconciliation
resolves it, so admission stays blocked and paper matching cannot cancel it first. Order and fill/cost postings commit
together using [AccountLedger](accounting.md).

`post(AccountPosting)` applies identified transfers, separate currency fees or
rebates, late fills, and append-only corrections. Every new administrative
posting blocks further admission until reconciliation. Fill and correction
postings retain the reserved order and instance; corrected partial quantities
become uncertain until a normalized terminal/open reconciliation resolves them.
Unpostable source facts remain visible through `failed_postings()` or
`failed_events()` with a durable block. Unsupported shorting, borrowing,
base-asset fee conversion or contradictory source facts cannot be forced into
balance by changing journal bytes. A receipt or fill identity reused with changed
content retains both the accepted fact and contradictory source fact; restart or
a matching account observation cannot clear that unresolved contradiction.

`reconcile(AccountObservation)` compares currency cash, positions, fees, rebates,
transfers, posting/fill identities and complete cumulative open-order state.
The observation must be at least as recent as the state it certifies. Matching
balances cannot clear unknown orders, an unposted failed fill, or underfunded
pending reservations. Failed observations are retained. `block(account_id,
reason)` persists a separate operator stop which successful reconciliation never
clears. It blocks new exposure; cancellation and accounting remain available.
Block, cancel and reduce-position are distinct. Managed paper activation and
local recovery use the signed managed contract documented below; this shared
account API does not grant live venue authority or submission.

This is an atomic local command service with no venue transport, credential
resolver or submission. Concurrent calls serialize at SQLite; the separately
described test-venue gateway owns its executing fence and physical reconciliation.
State is pinned
to exact configuration bytes and uses the `account-runtime` and
`account-postings` contracts. It establishes correctness for
the reference workload, not runtime throughput, bounded retention or deployment
readiness. Retain the journal with its configuration and compatible artifact;
never edit accounting history to make a rollback appear compatible.

## Public-input paper matching

`PaperExecutionScenario` pins the venue and instrument, entry and cancellation
delays, adverse price movement, fee rate, fraction of displayed touch size taken,
and an explicit reason gas is inapplicable to this off-chain spot model. The
selected `SpotLimits` lot and tick still govern quantities and prices. Entry and
cancel eligibility are evaluated at the first later received public quote; the
model invents no intervening exchange event or response clock. A cancel request
honoured at its delay ends the order `cancelled_on_request`. An immediate-or-cancel
or stranded remainder that ends first is `cancelled`, and a crossing post-only order
is `rejected`, even while a request is still pending. A quote can fill
only an older order. The modeled fill retains both observed touch reference and
adverse effective price, with exact quote-currency fee rounding. A limit or fee
reservation that cannot cover those economics cannot silently become a fill.
Admission refuses (`fee_reserve_below_worst_case`) an order whose `maximum_fee` is
below the configured worst-case fee: the whole quantity at its limit at the
instrument's rate, plus a rounding allowance. Paper and shadow accounts use the paper
model's own half-even rounding per fill: half a minor unit for each fill whose fee can
round up, which is at most `2 * fee / minor_unit` fills and at most one per lot.
`venue_test` accounts, whose venue rounds by its own rules, keep one minor unit per
lot. Account journals take the rate from `AccountConfiguration.fee_rates` (one
`InstrumentFeeRate`, such as the venue's taker rate, per instrument) in paper,
shadow and `venue_test` alike; a dedicated `PaperOrderJournal` takes its
`fee_rate`, which `PaperConfiguration.fee_rate` supplies. A matching scenario
may charge that rate or less, never more. Protective
reductions are exempt, so a risk-reducing sell is never refused over fee sizing.
A buy never fills above its limit, so its reserve then pays every fill.
`PaperFeeSchedule` takes only the whole lots whose fee, both exact and rounded on
that fill, fits the order's remaining `maximum_fee`. A sell filling above its limit
pays more per lot and can therefore leave the rest of an order resting (or
cancelled, for IOC), but never fault the account. A sell fills at or above its
limit, where one lot's fee is lowest, so once its remaining reserve cannot pay one
lot at the limit the remainder can never fill: the model cancels it at the next
eligible quote and its reservation is released. A buy may still fill below its
limit at a lower fee, so it keeps resting. The account lifecycle still refuses an
unaffordable modeled fill and rolls the whole market back.

`PaperMatchEvaluator` is the shared deterministic projection for the dedicated
and account journals. The account journal supplies physical orders in decision
time and identity order; the dedicated journal uses its admission order. Each
path consumes finite displayed liquidity across those orders. Repeated observations
at the same touch price increase the available peak only when displayed size
increases; they do not replenish already consumed size. A changed touch price
starts a new modeled segment. This no-impact top-of-book rule assumes neither
queue priority nor venue execution fidelity.

For a dedicated account, `PaperOrderJournal.match_scenario_market(epoch=...,
market=..., scenario=...)` pins the scenario and source quote, then commits all
projected lifecycle and fill effects with the liquidity cursor in one fenced
transaction. `PaperMatcher.match` does the same for a matcher bound to one
scenario and lot, and charges the scenario's own fee rate. Neither method submits
an order.

For one or several strategies on a shared account,
`AccountJournal.bind_paper_scenario(account_id, scenario)` pins the exact profile
before orders for that account and instrument. `apply_public_market(account_id,
market, scenario)` is the one command per eligible book. Inside one
`BEGIN IMMEDIATE` firm transaction it checks the current owner, generation,
restore quarantine and clock, and the bound scenario; then it resolves the
market's identity against the whole committed trace history before any effect.
- An identity this account already applied is an exact retry: the command returns
  the saved outcome and writes nothing, so valuation, liquidity, accounting and
  checkpoints are unchanged. Ageing and grant expiry do not block it; an owner
  change, quarantine or clock regression does.
- The same identity with other input, in any account, is refused.
- A new market must be fresh under managed authority; it is matched and its ask
  is observed as the instrument's valuation, both in that transaction. Projected
  facts apply to direct physical orders and to portfolio net parents. Net parent
  fills use the existing exact child quantity and fee allocation; displayed
  liquidity is consumed once per physical parent, not once per strategy child.
  Regressed availability, or a valuation at the same clock with another quote, is
  refused with no effect.
- A shadow account keeps no trace and only observes the ask; the identical quote
  at the valuation's clock changes nothing.

The command returns a `PaperMarketOutcome`: the account, the market identity and
the SHA-256 of the committed trace's exact journal bytes (none in shadow). A
modeled event that fails the account lifecycle or economic checks leaves that
quote's partial effects unapplied and commits a failed trace, rejected fact and
account fault; the command then raises, and an exact retry raises the same
failure. Unknown outcomes remain reserved; cancellation is terminal only after its
modeled confirmation.

Each trace holds the exact market, scenario, input digest, physical events,
attributed child fills and durable liquidity cursor, including no-fill markets.
The trace history grows with every eligible book, so it is read in bounded pieces,
never whole:
- `paper_trace(account_id, market_identity)` reads one market's trace, if the
  account applied it;
- `paper_trace_page(account_id, after=...)` reads at most `PaperTracePage.maximum`
  (256) traces after a journal-wide position, from -1. Each page names the
  position to continue from and the whole history's `HistoryDigest`: its count and
  the hash chain over every trace's exact bytes, so pages joined from successive
  snapshots can be checked against it. `iter_paper_traces` joins pages;
- `latest_paper_traces(account_id)` reads the newest trace of each bound instrument;
- `paper_trace_history()` reads the history's count and chain;
- `export_paper_traces(destination, account_id)` publishes the codec's encoding of
  the account's traces as one JSON array, written from their stored bytes in
  bounded memory while every row of the history extends the chain checked against
  the head; a mismatch leaves no file.

`paper_report_facts(account_id)` exposes strategy-owned fills and their current
effective fee links; a corrected-to-zero fee has an explicit zero link.
`valuation(instrument)` reads the latest observed valuation quote of one
instrument; installed clients request the `valuation` projection with only
`query_instrument`. A shadow account keeps no trace, so a shared observer
replaying into it skips a book older than that valuation as already applied.
Installed clients read one market's trace with the `market_trace` projection
(`account_id`, `query_market`), a page with the `traces` projection
(`query_after`), and the history with `trace_history`; a full inspection states
`paper_trace_history` instead of returning trace bodies, and `monitoring` adds
each bound instrument's newest trace. The one-shot `export_traces` command
(`export_path`, optional `account_id`) runs the export in the signed runner.
Reconciliation still requires a complete independently supplied
`AccountObservation` with physical cash, positions, costs, posting identities and
cumulative physical open orders. A journal report or its own modeled trace is
not an independent account observation. The `reconciliation` projection (with
`account_id`) answers one account's view, its open orders and `known_at`, its
knowledge clock, from one snapshot. An observation must be stamped no earlier than
that clock or the last reconciliation. An earlier one is stale, not evidence of a
break: it is refused with `observation_precedes_account_state`, unrecorded and
without faulting the account, and the operator observes again. A stamp at the clock
is always safe: the account already refuses
any market earlier than its own clock, so no market in flight is refused. Supported live-public-input composition
and its operating limits are documented by the
[paper application](paper-application.md).

## Portfolio coordination and recovery

`AccountJournal.coordinate(PortfolioBatch)` composes the same independent account
admission with [portfolio context and allocation](portfolio.md).
The batch retains every original `AccountDecision` and its complete
`PortfolioContext`. Its coordination time must be strictly later than each
decision cutoff. A stable batch identity binds the original bytes and outcome;
an exact retry cannot create another reservation, internal transfer or physical
order. The journal resolves that identity first: a retry equal to the saved batch,
every decision and context included, returns the saved result without a write,
and any difference rejects as reused content. Each decision's own admission
refuses only that decision, rolled back whole with its cancel requests, while the
batch's other decisions commit together;
`PortfolioCommit.refused` lists each refusal with its reason. Decisions are admitted
in batch order against the state staged so far, so when strategies contend for the
same account or firm headroom, cash or holding capacity, the earlier one is
admitted; the shared runtime orders a cohort by instance identity. Account and firm
ceilings with room for every instance's own ceiling keep per-strategy research
results free of this priority. A batch-wide
refusal leaves no partial economic effects: for example a stale strategy checkpoint,
an already admitted decision, a changed crossing policy, a decision crossing an
order of an earlier decision in the batch (the crossing policy settles it for the
whole cohort, though a crossing quote leg is dropped instead), funding, the
send-time check of the batch's own orders, a netting failure, or every decision
refused, which `refused` then lists in full.

Targets and exposures lower against only their owner's attributed holdings;
order and quote intents retain their native child legs. All pre-net children
pass instance/account/firm gross budgets, instrument authority, cash/inventory,
freshness and spot mechanics before coordination. Netting cannot create budget
headroom by hiding an opposing strategy's commitment.

`orders()` retains tagged strategy children. `net_orders()` retains physical
parents and their child allocations. A compatible group must share account,
instrument/currency, portfolio, venue, settlement, risk bucket and authority,
plus the selected order mechanics and quote. Strategy and revision identities
stay on each child. Separate accounts, venue listings or currency denominations
never net through an assumed equivalence or FX rate.

The default crossing policy rejects self-trade conflicts. Explicit
`internal_at_quote` transfers owned spot inventory between compatible opposing
strategies at their common independently observed quote, within both limits.
It posts paired, identified strategy cash/quantity effects with zero internal
fee; aggregate physical cash and inventory do not change. These are declared
internal allocations, never invented venue fills. Incompatible scope, unknown
outcomes, unavailable inventory and unsupported post-only crossing fail closed.
The selected crossing policy is pinned when the journal first admits a batch.

`apply_net_event(OrderEvent)` names a physical parent and commits its transition,
allocated child fills/costs and physical-to-child lineage in one transaction.
A terminal fact states the parent's cause by kind, never inferred from a request
that was merely pending: only `cancelled_on_request` leaves the parent's other
children to reissue. A caller confirming a requested cancellation, such as an
unmanaged application, supplies that kind; `cancelled`, `reconcile_cancelled` and
every other ending end the remaining children.
The reference policy retains prior allocations, assigns deterministic residuals
and never charges beyond reserved costs. The physical fill identity is distinct
from the allocated posting identities. Complete reconciliation checks physical
open orders and physical fill totals against the strategy ledger, alongside the
existing cash, position, fee/rebate and transfer checks.

`correct_net_fee(NetFeeCorrection)` revises the total cost of one identified
physical fill. It retains the original fill, uses the pinned original per-fill
fee-reservation weights and appends attributed ledger revisions. Repeated
corrections, voiding and restoration follow the existing current-revision
contract. Parent and child fee totals change together; unreserved costs fail
and a successful revision requires complete reconciliation before new risk.

`stop_instance(instance_id, at)` blocks new decisions for that strategy. A shared
parent must be cancelled as one physical order; when that requested cancellation
takes effect (`cancelled_on_request`, in paper once the modeled cancel delay has
elapsed), the other strategy's child reservation and remaining quantity survive.
If the parent instead ends on its own terms first, by an immediate-or-cancel or
stranded remainder or a post-only rejection, or by a reconciled or unattributed
cancellation, every child ends with it and nothing is reissued; posted fills and
fees stay, and only the unfilled reservations are released. A `venue_test`
parent's children always end this way (see test-venue execution). Neither cancel
request nor cancel acknowledgement releases uncertain exposure. After confirmed
terminal state and complete reconciliation, `reissue_pending(account_id, at)`
creates physical orders for unaffected residuals. `restart_instance(instance_id, at)` requires
the stopped strategy's unresolved orders to be settled and the account recovery
conditions to hold. Stop, physical cancellation and position reduction remain
distinct operations. Account-level protection applies throughout.
At the coordination cutoff, after all gross admissions and before any internal
allocation or physical order is created, every newly admitted child must still
have a fresh independent quote within the price-deviation bound, or the batch is
rejected: admission-time risk alone cannot authorize a later send. Residual
reissue requires funding and a current reconciliation; an old opening
reconciliation cannot authorize recovery. Netting, in both, routes only what can
be sent now. An earlier child whose quote is stale or whose limit drifted beyond
the bound, and a buy whose owner, account or the firm is now over a ceiling at
current marks, is held back without blocking any other order, so a strategy that
price moves alone took over its ceiling holds back only its own buys.
`portfolio_residuals(account_id)` and application inspection expose held-back
children with their reason, and child quantities that cannot form a valid
physical lot. These quantities stay reserved;
they are never silently rounded away or reported as a matched target. A later
coordination or reissue sends a held-back child at its original limit once it
passes these checks, while its decision is younger than the budget policy's
`max_residual_age_us`. Netting retires an older waiting child, releasing its
reservation without inventing a physical cancellation, and a batch whose own
children are already that old is rejected `expired_decision`. A paper decision
also replaces its owner's waiting children, and stopping the owning instance
retires them at once.

The [installed account command](execute-application.md#shared-account-command)
exposes these operations without a transport or credentials. The
[shared decision application](paper-application.md) stages existing
research decision policies, binds their inputs/revisions and stores per-instance
continuations in the same transaction. Compatible restart retains decisions,
reservations and allocations; a changed binding or stale continuation is refused.
Keep the journal, configuration and compatible artifact together for reversal.
Older artifacts must not be forced to read expanded portfolio state by removing
fields or rewriting accounting history.

Initial evidence is local cash-funded spot under authored OKX/Bitfinex-shaped
configurations. Physical private account observations, authenticated submission,
venue fee rules, deployment, capacity and activation remain separately qualified
capabilities.

## Test-venue execution

Owner: quant development. Status: implemented bounded software path; authenticated
venue conformance remains unqualified. `VenueGateway` connects `AccountJournal`
to `OKXSpotAdapter` and `BitfinexSpotAdapter` through the same `VenueAdapter`
contract. Existing paper/shadow journals remain non-executable. The new
`venue_test` account mode and separately supplied `VenueAuthorization` are required
for dispatch; production endpoints/authority are not exposed by this application.

Configuration pins the local and native account identities, test environment,
canonical instrument/native symbol/currency mapping, reference history, independent
account limits and credential environment-variable names. Current reference rules
must match the admitted specification at dispatch. Installing an adapter or adding
an instrument to a data universe grants no order authority. Adapter-owned capability
profiles use the existing registry and retain `fixture` qualification until actual
per-venue acceptance evidence exists.

The declared native support is cash-funded spot limit GTC, IOC and post-only,
submit/cancel requests, individual order lookup, bounded fill history, complete
open orders and trading-wallet balances. OKX requests select demo trading; Bitfinex
requires the authenticated user's paper flag. Both verify the configured native
account UID. The shared firm-journal binding refuses a second local alias for the
same physical wallet. Use one authoritative workspace and an exclusive API key for
each physical account; independent copied workspaces are not a distributed fence.

Each physical order must already be reserved through direct admission or
portfolio coordination. The gateway stores its client identity and uncertain
attempt before I/O. A kernel lock excludes another sending owner while the first
can still use its connection. The final independent risk/stop check commits in a
short journal transaction together with a durable dispatch lease; the request is
then sent with no journal transaction open, and the lease is released afterwards.
The lease is live while its holder process holds an OS lock on a
`<journal>.lease-<holder>` file, so no clock expires it and a sender that dies
frees it at once. Timing uses the holder's monotonic clock: the send must start
within 10 seconds of arming, and the TLS transport is handed an absolute deadline
five seconds before the 30-second lease ends. It connects (resolution, TCP, TLS)
first and refuses before writing any byte once that deadline has passed, then
bounds the write and every response read by it. Operator blocks, venue
invalidation, account controls and strategy stops for that account or instance
wait, outside any transaction, until the lease is released or its holder dies, so
a stop either commits before arming (arming refuses) or after the send. A stop
waits at most 35 seconds and then refuses without committing (`dispatch in
progress; stop not committed`); retry it. A crashed sender's order stays
`unknown` for reconciliation. A dispatch refused before its single send (a stop
committed before arming, a stale quote or authorization, a passed send window or
transport deadline, another held lease or a failed throttle wait) is definitely
unsent: the gateway
marks it `submission_rejected`, records the order `rejected` and faults the
account as `dispatch_not_sent`, which the next matched reconciliation clears.
Anything raised by the send or after it stays `unknown`. Cancellations hold no lease. The adapter's local
request budget is waited out before arming. Lost acknowledgements, restart and absent order lookup
never authorize another submit for that identity. Request acknowledgement is not
acceptance. Cancellation acknowledgement is not terminal cancellation. A further
explicit cancel requires successful reconciliation confirming the order is still
open. Replacement remains a new admitted order after confirmed terminal state.

A venue's terminal cancellation does not say whether our request or the order's own
terms ended it, and a cancel acknowledgement shows only that the venue accepted the
request. The gateway therefore records a validated venue cancellation as
`cancelled`, whether or not our cancel was acknowledged, and a `venue_test` account
journal refuses `cancelled_on_request` from any caller. When a netted parent ends
this way, its remaining children end with it instead of being reissued: their
posted fills and fees stay and only the unfilled reservations are released. Each
strategy decides again at its next decision. This intentionally narrows the
shared-parent survival above to paper accounts (owner decision of 2026-10-08): no
economic intent is re-sent without venue evidence of its cause. Venue-native cancel
causes, such as OKX `cancelSource` or Bitfinex's distinct `IOC CANCELED` and
`POSTONLY CANCELED` statuses, are neither parsed nor qualified; the Bitfinex adapter
currently refuses either status as unsupported, which faults the account for
reconciliation instead of ending the order.

The gateway retains exact native receipts before applying canonical events. The
account journal atomically posts `NativeFill`, fees/rebates and attributed child
effects. Positive native fees are costs; negative fees are rebates. Base costs
change inventory and native cost totals without debiting invented quote cash.
Cumulative native costs consume the order's quote-denominated fee allowance at
the actual execution prices. Quote fees use existing cash accounting. Third-asset
fees and implicit FX are rejected. `PhysicalAccountObservation` compares actual
wallet totals and physical open orders; local fill IDs are never manufactured as
external observations.

Before each first submit and after uncertain outcomes, the gateway checks native
account mode/UID, retained individual fills, order details, wallet totals and
stable opening/closing open-order snapshots. It checks every configured instrument
and refuses unknown orders, inconsistent cumulative fills, nonzero unmapped wallets,
borrowed funds, history truncation or changed economic identity. An order whose
terminal outcome is already journaled is not looked up again: later fills still
arrive through fill history and a reopened order through the open-order snapshots,
so venue lookup retention no longer limits account age. Bitfinex looks an order up
in active orders first, which has no age limit, and refuses only a lookup that
falls through to closed-order history (about two weeks) more than 13 days after
the order was last seen open by a reconciliation (or, if never, after submission):
it closed no earlier than that. Local unsent intents
remain reserved and are not represented as venue-observed orders. A broken or
unavailable observation invalidates independent account readiness before the
transport diagnostic is saved. Operator stops are never cleared by reconciliation.

Private WebSocket sessions authenticate explicitly and retain received frames;
Bitfinex sequence gaps and either venue's malformed/control/loss events require
recovery. Bitfinex follows authentication with position and funding snapshots and
sends periodic balance valuations (`bu`); these are heartbeats while flat, and any
position or funding exposure requires recovery. Private wallet frames may report
availability as not yet calculated (unknown), while REST wallets must report it.
Economic notifications mark the account stale at once and trigger the same
authoritative REST reconciliation, coalesced: once the stream has been quiet for
one second (longer than the gap between one fill's frames), at least every ten
seconds while notifications continue, and before a normal exit. Authentication
still reconciles at once. The session's five-second loss bound counts only time
spent waiting for a frame, not time spent reconciling.
The bounded session closes and invalidates account freshness on exit. Reopening a
session does not itself resume submission. This correctness-first implementation
does not qualify low-latency streaming or runtime capacity.

State consists of the account SQLite journal, account-specific `.venue.sqlite3`,
the shared `.venue-accounts.sqlite3` identity bindings and `.venue.lock`. The venue
file keeps each dispatch and each receipt as its own row, so retaining a private
frame or marking a receipt applied writes one row. Opening refuses any other layout.
Keep the whole workspace together. Nonces and conservative request intervals survive
restart; HTTP requests never hide submit retries or follow redirects. Private
receipt bytes can contain sensitive account data and belong outside Git. A restored
venue workspace requires fresh physical reconciliation. Remote venue anti-rewind
and deployed rollback qualification remain open; managed paper's local restore
quarantine is described below.

Recovery is deliberately bounded by source history retention, pagination and
configured resource limits. An empty unavailable historical window is not proof of
no fills. Fill history starts at the account opening until a reconciliation
matches the physical account. The venue journal (`venue-journal`) then retains
that window's end, and later reads restart one hour before it so late-published or
clock-skewed executions are still read; a physical break leaves the mark in place.
Repeated executions apply once by fill identity. The Bitfinex reader pages trades
forward by time and restarts each continuation inside the last millisecond of a
full page; a full page that stays within one millisecond fails closed.
No borrowing, derivatives, third-currency fee conversion, production activation or
venue-execution fidelity is claimed. External qualification is
[out of scope](../roadmap/overview.md#live-trading-kept-in-view); the
[command guide](execute-application.md#test-venue-commands) owns invocation.

Protocol references are the official [OKX V5 guide](https://www.okx.com/docs-v5/en/)
and [Bitfinex authenticated API guide](https://docs.bitfinex.com/docs/ws-auth).
Their protocols informed implementation; reading documentation is not exchange
conformance evidence.

## Account operational recovery

`AccountJournal.control(AccountControl)` commits local account phase and its
identified outcome in the same firm transaction as order and accounting state.
`startup` is the first control transition; `stop` and `fault` block admission,
coordination and residual reissue without changing economic facts. `restart`
compares the exact current stop identity, requires a newer complete independent
reconciliation and fresh marks, and rechecks gross funding. Recovery sends no
residual, so held-back residuals do not prevent it. Unknown sends, unconfirmed cancellation
and account contradictions prevent recovery. Known accepted open orders can
survive recovery with their reservations intact.
`block()` reasons remain independent and cannot be cleared by this API.

`cancel` records requests on direct orders and physical net parents without
creating terminal outcomes. Local control history and recovery generations are
retained by `controls()`. Stopping one account preserves other accounts' ability
to operate when their own state and the aggregate firm valuation remain valid.
The controls trust the local operator/source boundary; they are not a credential
or live-capital authorization mechanism.

Unknown schemas fail. `AccountJournal.verify(path, config)` performs
read-only integrity/config/schema validation and sees committed WAL state. It runs
SQLite's `integrity_check`, requires the exact layout and configuration, decodes
the head, and checks every state row against its digest and the head's row
summaries, decoding the state, ledger included, in full. It streams every history
row (decisions, portfolio batches, paper traces) once, in order: each row's exact
bytes must extend its table's hash chain to the head's count and digest, each
row's key columns must equal the keys its bytes name (a trace's fill flag
included), and the head's checkpoints must be each instance's latest decision.
History rows were validated domain records when they were encoded and committed,
and every read decodes them in full again, so verification reads only their keys:
its time is linear in the stored bytes and its memory bounded by one row, at any
history size. `storage="snapshot"` additionally requires no SQLite sidecars and
leaves a standalone snapshot unchanged. The [workspace recovery owner](runtime.md#account-workspace-recovery)
uses these checks under backup locks and before restore publication.

## Bounded paper deployment authority

`PaperDeployment` and `PaperAuthorization` are separate versioned configuration
records. The deployment is always disabled. It pins the exact account configuration,
instance/policy/candidate/model/feature identities, input binding, execution
scenario, compatible signed release digests and `paper-account-state` state ABI.
`AccountJournal.install_paper` atomically binds matching assumptions, records a
stop and retains the activation, whose presence marks the journal as managed. It
creates no orders. An incompatible deployment cannot replace that identity.

The separate grant names that deployment digest, instruments, maximum admitted
buy quantities, per-order notional, order count and a half-open UTC validity
interval. Quantities and order count are cumulative across the deployment,
including canceled, pending and uncertain orders; reductions and replacement
grants do not replenish those limits. Existing independent account/instance risk
and funded reservations still apply. Production submission authority is rejected
by both records. The trusted local operator submits these explicit records; there
is no additional authorization signer or hostile same-user isolation claim.

`authorize_paper` records a grant without clearing the stop. `claim_paper` checks
current wall time and compatible release, then uses the existing fresh independent
reconciliation/quote and restart checks before incrementing the durable owner
generation. The returned `PaperOwner` is supplied when reopening the journal.
Admission and matching recheck its generation inside the economic transaction;
new exposure also rechecks expiry/revocation and current input freshness. An
exact `admit` or `coordinate` retry, equal to the saved decision or batch, checks
only the current owner, generation, retained journal and clock, then returns the
original result with no write or economic effect. Ageing inputs and an expired or
revoked grant therefore do not block it. A superseded or stale owner, restore
quarantine or a regressed clock does; after a replacement claim, the current
successor owner retrieves the original saved outcome. A new identity takes every
admission check. Older workers cannot post effects after a replacement claim.
Repeated source identities retain the original economics and finite liquidity
cursor.

Expiry/revocation prevents new exposure and restart, but the original current
owner may continue processing existing obligations, including model matching,
on fresh eligible data. Accepted standing orders retain their reservations until
terminal outcomes are established. Operator stop, cancel and bounded reduction
remain available independently of an exposure grant. A replacement grant can be
recorded only after the account is stopped and all existing physical order
outcomes are settled. Prior grant identities remain retained, and an explicit
fresh owner claim is required before a replacement worker creates exposure.
Revoked IDs cannot be reused. Direct in-process `AccountJournal` use without an
installed release identity remains a local development interface, outside the signed
managed activation contract.

`control/stop` is the reversible block-new-exposure action. `control/cancel`
records cancellation requests, preserving reservations until the matching model
provides terminal outcomes. `reduce_paper(PaperReductionRequest)` reserves an
explicit IOC sell with a minimum price and fee bound. It checks attributable
inventory minus every outstanding sell commitment, fresh eligible market and
independent reconciliation, uncertainty and existing risk. It cannot sell another
strategy's position. Accepted means reserved, never filled or liquidated. A later
eligible public quote produces ordinary model events: partial fills and unavailable
liquidity remain visible; no fill is fabricated. Economic faults, unknown outcomes,
stale/disconnected input and insufficient inventory return explicit rejection
reasons. The permanent `block` is an independent protective fault, distinct
from the reversible operational stop.

Historical workspace restores are quarantined before publication. They remain
inspectable but cannot install/claim managed authority, reduce or match; a snapshot
cannot prove no later fills occurred. Supported local recovery uses the latest
retained journal after reconciliation and, for managed paper, an explicit new owner
claim. Signed compatible code rollback keeps that journal, including its grants,
controls, orders, costs, checkpoints and reservations.
Loss of that latest evidence requires a separate recovery decision and is not
silently repaired from a historical snapshot.

## Multiple input scopes and admission freshness

`PaperDeployment.additional_sources` optionally overrides the primary input and
scenario for a named instance. `scope_for(instance_id)` resolves its exact route;
`scenarios` exposes distinct bound scenarios. Unsupported instances, conflicting
mechanics for one instrument, venue substitutions and currency changes reject.
A deployment without overrides encodes an explicit empty tuple.
Managed shadow deployments use explicit shadow authority and cannot create paper
fills or internal crosses. Installation binds every selected scenario before orders.

Protective reduction samples current UTC inside the journal transaction. Quote,
book and independent-state ages are measured at that admission instant; future
inputs and account ordering still use the request's causal cutoff. An original
identified result remains retryable after its timestamps age or exposure authority
expires or is revoked; saved decisions and batches behave the same. Changed content
under that identity rejects. A new reduction cannot use a nine-second-old request
to admit an eighteen-second-old input under a ten-second freshness limit.

After a shared parent's requested cancellation takes effect, automatic coordination
and the explicit residual reissue command both require reconciliation covering the
terminal physical outcome.
A new strategy decision cannot bypass this recovery gate. Existing residuals remain
reserved and attributable while that gate is closed.
