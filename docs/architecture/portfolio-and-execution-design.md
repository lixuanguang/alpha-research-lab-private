# Portfolio and execution design

**Status: destination design.** Capabilities remain planned unless explicitly
identified as current. Quant development owns the implementation boundaries;
the roadmap owns delivery and acceptance.

The initial delivery is research and paper trading. Live execution, authenticated
venue qualification and real-account recovery are
[out of scope](../roadmap/overview.md#live-trading-kept-in-view). Their destination
contracts below remain requirements only if that work is reopened; existing
test-adapter implementation and evidence retain their stated limits.

[Platform design and dependency direction](platform-design.md).

## Portfolio, accounting, and position state

Portfolio construction consumes forecasts, current positions, risk budgets, costs, liquidity, financing, and
constraints. It produces dimensioned desired exposures or quantities with a validity interval and fallback. It never
places orders. An infeasible or stale input takes a deterministic conservative path.

That economic portfolio optimizer remains planned. The implemented local
`portfolio` package supplies shared-account metadata compatibility and
`ProRataAllocator`; `execution.AccountJournal` owns the account transaction,
order lifecycle and physical-to-child posting boundary that consumes them.

The planned accounting boundary owns positions, lots or contract quantities, cash by currency, accrued amounts,
margin/collateral, financing, fees, dividends, coupons, funding, variation margin, exercise, assignment, delivery, and
settlement events for supported asset classes. Money and quantities use the current exact financial-unit contract;
weight-only state cannot replace an economic position.
The implemented bounded spot [arithmetic contract](financial-units.md#planned-research-and-accounting-arithmetic)
keeps cash/notional/marks on the exact C03 grid and uses dimensioned rational
basis/P&L attribution where proportional division is nonterminating. Exact
returns use reduced fractions; display/model approximation has a separate
declared representation. P1 NAV and gross-to-net reconciliation are exact.

Each accepted fill changes economic state exactly once. Rejected or canceled quantity never becomes a position. Realized
and unrealized P&L use one authoritative definition. Base-currency translation names its FX source and timestamp. NAV
reconciliation checks beginning NAV plus external cashflows, trading/marking P&L, financing, and lifecycle cashflows
against ending NAV within a declared tolerance.

State is event-identified and restartable. A durable snapshot records the last applied event sequence, release identity,
account/venue identity, and schema version. Recovery replays subsequent events idempotently; order, fill, cancel,
correction, and ledger-event identities are unique across retries.

An active process carries a fencing epoch or lease. A restarted process cannot write orders or ledger state after its
epoch is revoked. Startup validates release/schema compatibility, loads the latest valid snapshot, reconciles open
orders and positions with the venue, and enables only explicitly allowed actions. A mismatch pauses new risk and orders.

## Multi-strategy netting and isolated risk

Every strategy intent retains strategy ID, model/config revision, decision time, account, portfolio, instrument, side,
quantity or exposure, horizon, and reason metadata. Allocation and execution may net compatible intents to reduce cost,
but the ledger keeps pre-net intents and post-net order lineage.

Netting is permitted only when account, currency, venue, instrument contract, settlement, risk bucket, and authority
scope are compatible. It never erases strategy attribution, prevents a strategy-level stop, or transfers a loss budget
without policy. Residual and shared costs use a stable documented method and remain reversible for reconciliation.

The current local increment coordinates a finite selected batch of spot decisions
through one `AccountJournal` transaction. It first reserves gross child intent
under the existing account budgets. Same-side children become one physical parent
only when they share an account, exact observed quote, compatible
portfolio/venue/settlement/risk/authority context, instrument, limit and
time-in-force. `PortfolioContext` retains each child's strategy and revision
metadata even when those values differ across compatible children. Opposite
interests are rejected by default; the explicit `internal_at_quote` policy can
cross compatible, non-post-only children at their common observed quote when
their limits allow it.

Each physical parent retains its child IDs and reserved quantities. Cumulative
partial fills are allocated on the exact financial grid in proportion to the
original child quantities, without reversing earlier child fills. Physical fees
are split against remaining child fee reservations, with residual atoms assigned
by stable child identity. A physical event and all child fill/cost postings commit
together. Local account observations can verify the resulting physical and
per-instance projections; they are supplied paper facts, not authenticated venue
observations.

The implemented local account boundary enforces marked gross exposure and pending
commitments across instance/account/firm budgets, authorized instruments, price,
size, freshness, inventory and cash. Its [account guide](../packages/execution.md#shared-account-admission-and-reconciliation)
records the normalized reconciliation and correction contracts. Broader risk
views remain planned: net exposure, leverage,
concentration, liquidity, margin, stress loss, sensitivities, and loss limits as applicable. Strategy budgets nest under
account and firm limits. A strategy can be disabled while others continue only if resulting net exposure and shared
limits remain safe; otherwise the account or venue is fenced as a whole.

Risk consumes authoritative positions, pending orders, market state, limits, entitlements, and activation state. Missing
or stale inputs, unavailable limits, timeout, unknown instrument, or failed authorization rejects new risk with a
visible reason. Kill and cancel controls remain reachable when a strategy process is unhealthy.

Admission reserves strategy/account/firm capacity atomically, including submitted
orders with uncertain outcomes. A concurrent 8,000 + 8,000 request fixture under
a shared 10,000 account-currency limit cannot admit both in full. Explicit conflict
and self-trade policy applies across instances. Reservations survive restart and
are released only after the corresponding outcome is established; database
atomicity alone does not make an external submission exactly once.

The dedicated single-instance paper account qualifies durable state, pending
reservations, hard limits and base account reconciliation. The local shared-account
increment adds tagged child orders, atomic budgets, conflict handling, attribution,
compatible netting and deterministic allocation of fills, fees and residual units.
Acceptance requires two distinct active reference strategies on the
same instrument/account to reconcile separately and together, including selective
stop/restart with ownership and account safety. A stopped child in a physical
parent retains its reservation until a terminal outcome. Unaffected residuals
survive only a requested cancellation that took effect, which a terminal fact
states by its kind, and are reissued only after reconciliation and current
mark/budget/funding checks; a parent ending on its own terms, or a venue
cancellation of unattributed cause, ends every child.
Unroutable physical-lot residuals stay visible and reserved; a completed child
retains fee capacity while its physical parent can still receive costs.
The [roadmap](../roadmap/overview.md#capabilities) records
the qualified scope and remaining limits. Quant development supplies the deterministic
reference policy; QR later supplies economic allocation choices within limits.
This local paper/software proof does not establish OKX or Bitfinex private-stream,
order, fill or account conformance; that authenticated qualification is out of scope.
Each venue has separate installed public-input paper execution and account
evidence, with two active reference policies sharing one account.

Initial strategies are trusted founder-authored code. Logical separation,
immutable limits, per-instance state and final risk enforcement outside strategy
logic protect supported interactions and failures. They do not isolate hostile
code. Before admitting adversarial or untrusted strategies, require a privilege
boundary with controlled communication and credentials/limits outside that
code's authority. A separate class or same-privilege process does not establish
this stronger guarantee; no sandbox platform is a P1 prerequisite.

## OMS and venue adapter design

The [`execution` owner](../packages/execution.md) implements a durable,
fenced dedicated-account paper/shadow OMS. It owns intent, request acknowledgment,
acceptance, partial fill, cancel request/acknowledgment/confirmation, rejection,
unknown outcomes and local reconciliation. Candidate checkpoints and child order
admission commit together; stable IDs and recorded event bytes reject conflicting
retries. Independent spot limits reserve pending and uncertain exposure. The OMS
does not decide economic targets or override risk. The additional `AccountJournal`
shares the same intent/lifecycle owner and adds
atomic instance/account/firm admission, tagged child orders and postings, compatible
physical net orders, deterministic fill/fee allocation, append-only corrections
and complete local reconciliation. An implemented test-venue gateway adds
both native protocols, signed native fees and wallet/order comparison through
these same owners. Its scripted conformance remains software evidence; actual
authenticated venue qualification is out of scope. The
[test-venue contract](../packages/execution.md#test-venue-execution) owns
supported operations, separate authority and recovery limits.

[`runtime.PaperCandidateRuntime`](../packages/runtime.md#paper-candidate-supervision)
delivers lifecycle, timer, market, order and account callbacks to the same
candidate components used by replay. Public native feed collection connects
through a post-persistence observer and retains actual local availability.
Paper matching uses finite displayed touch liquidity and exact fees; explicit
`PaperExecutionScenario` profiles add causal entry/cancellation delays, adverse
prices, take fractions and gas inapplicability. The pure evaluator serves both
journal transaction owners. `run_live_shared_paper` connects the native public
source and book registry to existing shared decisions, independent risk, matching,
attribution and retained cost/net-P&L reports. Last-eligible-bid marks are explicit;
slippage already included in execution prices is not deducted twice. Shadow mode
never matches. Both modes suppress executable submission. A contradictory fill
after confirmed cancellation durably blocks the account pending later correction
support rather than rewriting terminal state. The
[roadmap](../roadmap/overview.md#capabilities)
records the bounded scope; source observations stay separate from modeled fills.

The supervised local composition retains this same coordinator and journal. Each
instance selects its own input, reference policy and explicit instrument through
typed configuration. Netting requires compatible economic context and identical
venue/instrument identity; separate instruments never become one physical order.
Each account service atomically reserves instance/account capacity, including
pending and uncertain orders. Separate service journals protect isolated accounts;
their individual firm limits do not constitute one atomic budget across journals.
USD and USDT remain separate currencies without implicit conversion.

Selective worker loss stops that instance and cancels its accepted shared parent
where necessary, retaining residual ownership for the surviving children. A new
decision cannot bypass the requirement for reconciliation after the terminal
parent outcome before residual reissue. Source loss faults all dependent accounts;
an owner failure terminates every dependent policy. Independent accounts continue
only with their own healthy source and current authority. Shadow records decisions
and reservations without paper matching or internal crossing fills. Measured installed service observations are kept
separately from these implementation contracts.

The retained live adapter contract below applies if live work is reopened.
Venue adapters translate canonical orders into one broker or venue protocol. They own credentials, throttles, sequence
numbers, venue-specific timeouts, retry rules, idempotency keys, and source errors. They expose normalized events back
to the OMS and retain raw protocol messages for investigation.

A retry cannot create a duplicate economic order. Where a venue lacks a native idempotency key, the adapter uses durable
client identity and reconciles before retrying. Partial multi-leg fills remain explicit; temporary leg exposure is
visible to risk. Decision, arrival, fill, fee, and benchmark prices are retained for transaction-cost analysis.

Request acknowledgement, venue acceptance and final economic state are distinct.
A cancel acknowledgement is not confirmed cancellation and cannot alone free a
reservation. Private-stream loss, cancel/fill races and process restart reconcile
against venue state before retry or resumption. One fenced owner may execute for
an account. Any reopened live scope must qualify the first venue end to end, then
the second through the same contracts. This native venue conformance is out of scope;
initial onboarding instead requires both venues' public-input paper conformance.

## Asset-class specializations

The canonical model is shared, but each asset class owns lifecycle and market mechanics. Unsupported features fail
explicitly rather than falling back to equity-like behavior.

**Equities — PLANNED.** Add identifiers, listings and delistings, corporate actions, auctions, short-sale and borrow
state, dividends, settlement, and jurisdiction-specific restrictions. Raw prices and actions remain beside derived
adjusted series.

**Futures and commodities — PLANNED.** Add expiries, delivery and last-trade lifecycle, multipliers, tick values,
variation margin, rolls, spreads, settlement, and delivery risk. Continuous series remain derived.

**FX — PLANNED.** Add base/quote direction, holiday-center combinations, spot dates, forwards, swap points, broken
dates, funding curves, and venue conventions. FX conversion cannot rely on an implicit global currency.

**Options and volatility — PLANNED.** Add point-in-time chains, underlying and forward links, exercise and settlement,
corporate-action adjustment, surfaces, Greeks, multi-leg orders, assignment, and margin. Covariance and full-revaluation
stress remain distinct calculations.

**Fixed income and rates — PLANNED.** Add schedules, accrued and clean/dirty price, discount/projection curves, fixings,
resets, issuer hierarchy, embedded options, financing, DV01, key-rate, and scenario risk.

**Digital assets — CURRENT bounded spot; full initial stack PLANNED and required.**
Complete OKX/Bitfinex spot data, simulation, paper account/risk and paper execution
interfaces under the roadmap's pre-onboarding gate. Perpetuals and other later extensions add
funding, index/mark prices, collateral haircuts, liquidation and venue credit risk. For on-chain strategies, add chain
and token identity, finality, reorgs, gas, nonce and custody state, AMM/oracle semantics, MEV, and bridge/transfer risk.
Apply stablecoin FX and venue/chain outage scenarios where relevant. Only the selected operating scope is required.

**Low-latency market making — OPTIONAL PLANNED.** Keep L2/L3 reconstruction, queue priority, cancel/replace latency,
inventory, adverse selection, and venue throttles in a specialized subsystem. Do not distort a medium-frequency
simulator for an unmeasured hot path.
