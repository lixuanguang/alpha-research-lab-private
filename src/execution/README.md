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

Paper matching claims each modeled quote identity with exact immutable bytes in
the same transaction as its effects; shadow mode uses `claim_market` to record a
quote before its step commits. `markets()` exposes claims in insertion order so a supervising
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

[`accounts.py`](accounts.py) remains the supported journal and record import
surface. The concrete wire records live in [`account_records.py`](account_records.py),
while [`account_state.py`](account_state.py) owns the SQLite journal and transaction
boundary. Decisions, portfolio batches and paper traces are read only through the
snapshot and transaction history lookups by identity (`find_decision`,
`latest_checkpoint`, `find_batch`, `find_trace`, `iter_traces`) and written through
`append_*`, so callers do not depend on where history is stored.

The `firm` row holds the journal head: the current state without the three history
collections, each collection's row count and sha256 hash chain, and every instance's
latest checkpoint. The collections live in their own tables with each item's exact
codec bytes ([design](../../docs/roadmap/account-journal-history.md)). A commit inserts
only new rows and rewrites the head, reusing the encoded bytes of unchanged head fields,
and a fresh process decodes only the head. Only the `account-journal` schema is
readable; any other payload, including a whole-state document, fails closed. The journal composes admission and reconciliation from
[`account_admission.py`](account_admission.py), physical fill and fee attribution
from [`account_allocation.py`](account_allocation.py), and atomic portfolio order
formation and instance controls from [`account_portfolio.py`](account_portfolio.py).

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
atomic. The direct tagged-order path rejects crossing opposite orders. The
coordinated portfolio path below adds explicit compatible crossing and physical
aggregation.

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
the reference workload, not MR15 throughput, bounded retention or deployment
readiness. Retain the journal with its configuration and compatible artifact;
never edit accounting history to make a rollback appear compatible.

## Public-input paper matching

`PaperExecutionScenario` pins the venue and instrument, entry and cancellation
delays, adverse price movement, fee rate, fraction of displayed touch size taken,
and an explicit reason gas is inapplicable to this off-chain spot model. The
selected `SpotLimits` lot and tick still govern quantities and prices. Entry and
cancel eligibility are evaluated at the first later received public quote; the
model invents no intervening exchange event or response clock. A quote can fill
only an older order. The modeled fill retains both observed touch reference and
adverse effective price, with exact quote-currency fee rounding. A limit or fee
reservation that cannot cover those economics cannot silently become a fill.
`PaperFeeSchedule` takes only the whole lots whose fee, both exact and rounded on
that fill, fits the order's remaining `maximum_fee`. A sell filling above its limit
or fees rounding up on every partial fill can therefore leave the rest of an order
resting (or cancelled, for IOC), but never fault the account. The account lifecycle
still refuses an unaffordable fill and rolls the whole market back. Size the
reserve for the worst execution price plus one minor unit per possible fill.

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
transaction. The older `PaperMatcher.match` remains available for its existing
dedicated-journal replay contract. Neither method submits an order.

For one or several strategies on a shared account,
`AccountJournal.bind_paper_scenario(account_id, scenario)` pins the exact profile
before orders for that account and instrument. `match_public_market(account_id,
market, scenario)` applies projected facts to direct physical orders and to
portfolio net parents inside one `BEGIN IMMEDIATE` firm transaction. Net parent
fills then use the existing exact child quantity and fee allocation; displayed
liquidity is consumed once per physical parent, not once per strategy child.
Identical input retries return the original result across restart. A changed
market identity or regressed availability is rejected. A modeled event that
fails the account lifecycle or economic checks leaves that quote's partial
effects unapplied and retains a failed trace, rejected fact and account fault.
Unknown outcomes remain reserved; cancellation is terminal only after its
modeled confirmation.

`paper_traces(account_id)` exposes each exact market, scenario, input digest,
physical events, attributed child fills and durable liquidity cursor, including
no-fill markets. `paper_report_facts(account_id)` exposes strategy-owned fills and
their current effective fee links; a corrected-to-zero fee has an explicit zero
link. `paper_market_seen(account_id, market_identity)` reads fresh membership of
committed and failed traces in exactly that account. Shared observers use this
Boolean before observing a quote. Installed clients request `market_membership`
with `account_id` and `query_market`, avoiding transfer of historical trace bodies;
managed queries recheck the current bound owner generation in the same snapshot.
Reconciliation still requires a complete independently supplied
`AccountObservation` with physical cash, positions, costs, posting identities and
cumulative physical open orders. A journal report or its own modeled trace is
not an independent account observation. Supported live-public-input composition
and its operating limits are documented by the
[paper application](../applications/paper/README.md).

## Portfolio coordination and recovery

`AccountJournal.coordinate(PortfolioBatch)` composes the same independent account
admission with [portfolio context and allocation](../portfolio/README.md).
The batch retains every original `AccountDecision` and its complete
`PortfolioContext`. Its coordination time must be strictly later than each
decision cutoff. A stable batch identity binds the original bytes and outcome;
an exact retry cannot create another reservation, internal transfer or physical
order. A failed batch leaves no partial economic effects.

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
parent must be cancelled as one physical order; the other strategy's child
reservation and remaining quantity survive. Neither cancel request nor cancel
acknowledgement releases uncertain exposure. After confirmed terminal state and
complete reconciliation, `reissue_pending(account_id, at)` creates physical
orders for unaffected residuals. `restart_instance(instance_id, at)` requires
the stopped strategy's unresolved orders to be settled and the account recovery
conditions to hold. Stop, physical cancellation and position reduction remain
distinct operations. Account-level protection applies throughout.
Residual reissue also rechecks fresh independent quotes, gross budgets, price
deviation and funding; an old opening reconciliation cannot authorize recovery.
The same fresh-mark check applies at the coordination cutoff, after all gross
admissions and before any internal allocation or physical order is created.
`portfolio_residuals(account_id)` and application inspection expose child
quantities that cannot form a valid physical lot. These quantities stay reserved;
they are never silently rounded away or reported as a matched target. Stopping
their owning instance can retire an unattached reservation without inventing a
physical cancellation.

The [installed account command](../applications/execute/README.md#shared-account-command)
exposes these operations without a transport or credentials. The
[shared decision application](../applications/paper/README.md) stages existing
research decision policies, binds their inputs/revisions and stores per-instance
continuations in the same transaction. Compatible restart retains decisions,
reservations and allocations; a changed binding or stale continuation is refused.
Keep the journal, configuration and compatible artifact together for reversal.
Older artifacts must not be forced to read expanded portfolio state by removing
fields or rewriting accounting history.

Initial evidence is local cash-funded spot under authored OKX/Bitfinex-shaped
configurations. Physical private account observations, authenticated submission,
venue fee rules, deployment, capacity and activation remain separately qualified
capabilities. The [MR09 record](../../docs/roadmap/README.md#mr09-delivery-and-acceptance)
distinguishes their status from software acceptance.

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

Each physical order must already be reserved through direct admission or MR09
portfolio coordination. The gateway stores its client identity and uncertain
attempt before I/O. A kernel lock excludes another sending owner while the first
can still use its connection; a bounded account write lock protects the final
independent risk/stop check. The adapter's local request budget is waited out
before that lock is taken, so a throttle sleep never holds the shared journal; the
network request itself still runs under the lock. Lost acknowledgements, restart and absent order lookup
never authorize another submit for that identity. Request acknowledgement is not
acceptance. Cancellation acknowledgement is not terminal cancellation. A further
explicit cancel requires successful reconciliation confirming the order is still
open. Replacement remains a new admitted order after confirmed terminal state.

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
submission. Local unsent intents
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
does not qualify low-latency streaming or MR15 runtime budgets.

State consists of the account SQLite journal, account-specific `.venue.sqlite3`,
the shared `.venue-accounts.sqlite3` identity bindings and `.venue.lock`. Keep the
whole workspace together. Nonces and conservative request intervals survive
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
venue-execution fidelity is claimed. The
[MR11 roadmap record](../../docs/roadmap/README.md#mr11-delivery-and-acceptance)
owns the open external gate; the
[command guide](../applications/execute/README.md#test-venue-commands) owns invocation.

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
reconciliation and fresh marks, and rechecks gross funding and budgets. Unknown
sends, unconfirmed cancellation and account contradictions prevent recovery.
Known accepted open orders can survive recovery with their reservations intact.
`block()` reasons remain independent and cannot be cleared by this API.

`cancel` records requests on direct orders and physical net parents without
creating terminal outcomes. Local control history and recovery generations are
retained by `controls()`. Stopping one account preserves other accounts' ability
to operate when their own state and the aggregate firm valuation remain valid.
The controls trust the local operator/source boundary; they are not a credential
or live-capital authorization mechanism.

Unknown schemas fail. `AccountJournal.verify(path, config)` performs
read-only integrity/config/schema validation and sees committed WAL state; it also
checks every history row, its key columns and the head's counts, hash chains and
checkpoints;
`storage="snapshot"` additionally requires no SQLite sidecars and leaves a
standalone snapshot unchanged. The [workspace recovery owner](../runtime/README.md#account-workspace-recovery)
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
new exposure also rechecks expiry/revocation and current input freshness. Older
workers cannot post effects after a replacement claim. Repeated source identities
retain the original economics and finite liquidity cursor.

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
expires. Changed content under that identity rejects. A new reduction cannot use
a nine-second-old request to admit an eighteen-second-old input under a ten-second
freshness limit.

After shared-parent cancellation, automatic coordination and the explicit residual
reissue command both require reconciliation covering the terminal physical outcome.
A new strategy decision cannot bypass this recovery gate. Existing residuals remain
reserved and attributable while that gate is closed.
