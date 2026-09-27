# Bounded spot economics

Owner: repository founder. Status: implemented for synthetic/offline research;
the [verification section](#verification-and-reversal) describes its evidence.
Each study declares its own [policy and economic assumptions](../../examples/study-protocol.md#executable-economics).
This library does not establish historical source coverage, empirical
alpha, executable liquidity, release admission or trading authority.

## Offline decision-intent studies

`IntentSimulation` composes an explicitly supplied `IntentExecutionModel`,
`IntentCostModel` and the existing exact `Ledger`. The
[study application](../research/studies/README.md#generalized-decision-studies)
carries target, exposure, order and quote decisions through this public boundary.
The public `simulation` and `simulation.intents` imports remain stable. Immutable
wire records and collaborator protocols are owned by `intent_contracts.py`, while
`intent_execution.py` owns exact fee pricing and the causal L2 event engine.
`LimitOrderExecution` supports bounded long-only spot IOC and limit orders,
post-only admission, partial depth, cancellation/replacement and expiry. Independent
`SpotLimits` check tick/lot dimensions, cash and position limits. Optional retained
`ReferenceHistory` resolves limits by valid and knowledge time at each event;
missing/stale reference fails. Fixed authored limits remain a declared assumption.

The configured entry/cancel delays and lifetime are microseconds. A new order
waits for entry delay; a replacement with a pending plan or resting order waits
for cancellation and then entry delay. Books and prints become available at the
later source/knowledge clock; controls invalidate pending orders. Consumed
depth is not repeatedly offered while its level remains present. Passive orders
start behind `visible quantity * queue_ahead_fraction`; only opposite-aggressor
prints at the eligible price advance that queue. Book shrinkage is not a second
fill signal. Queue fraction is a sensitivity parameter, not measured queue position.
`SpotFeeModel` supplies explicit maker/taker costs; price arithmetic, ledger
postings and net return remain exact. Completion cancels outstanding orders and
marks retained holdings against a fresh bid; it never invents a terminal sale.

The execution identity is `l2-limit-intent-v2`, which distinguishes the corrected
idle-order timing from `v1`. Retained specifications pinned to the earlier
identity require the earlier executor or a new specification for the corrected model.

The [installed study consumer](../../tests/integration/consumers/research/decision_study.py)
tests a losing target study and passive queue sensitivity through the same
application. [Focused lifecycle tests](../../tests/unit/simulation/test_intent_simulation.py)
cover cancel/replace, partial IOC, controls, source clocks, reference changes and
target/exposure/order/quote support. `CapturedStudyMarket` can retain actual
capture bytes with an explicit receipt-as-matching assumption, aggregating L3
visible orders without inventing trades. It therefore cannot prove passive fills.
These contracts deliver MR07's offline lifecycle prerequisite slice for MR03;
shared-account OMS, venue conformance and deployed execution remain open under
MR05/MR07–MR11. The engine's one-account spot support rejects unsupported products
and does not qualify venue latency, historical queue position or empirical alpha.

The [public-input paper matcher](../execution/README.md#dedicated-paper-order-journal)
uses the same signed adverse-price and half-even quote-fee arithmetic as
`SpotCosts` when its authored scenario selects that convention. Its entry and
cancel delays choose later eligible received quotes, while the offline L2
executor uses separate source/knowledge clocks, book depth and a modeled passive
queue advanced by eligible trade prints. Paper matching caps each account's
fill at displayed best-price quantity and retains same-touch liquidity debt;
it does not classify maker/taker fills, infer queue position or model an exchange
response clock. Neither model makes observed public liquidity an executable
venue fill.

## Saved L2 IOC research

`applications.backtest.run_books` and `alpha-backtest books` now compose verified
saved OKX L2 observations with independent long-only spot accounts. The
[workflow guide](../../docs/research/l2-book-backtest.md) owns the
configured command, actual saved ETH-USDT result, fee/timing/depletion contracts,
restart procedure and limitations. `BookSimulation` keeps exchange and delivered books
separate; `BookExecution` walks depth using `SpotLimits`, `SpotCosts` and `Ledger`.
`BookCheckpoint` retains both books, pending deliveries/orders/responses, exact
postings and consumed liquidity. It does not use the trade-price vectorbt adapter.
The remaining sections describe the unchanged trade-price path.

## Compose a run

`applications.backtest.run_backtest(reader, spec, ...)` consumes an existing
verified `market_data.query.QueryReader` and a strict `BacktestSpec`. Reopen a
saved snapshot through `QueryReader.read` with its immutable identity, raw store,
source adapters, explicit precedence and byte budget. No input is downloaded
implicitly. The [installed acceptance consumer](../../tests/integration/consumers/backtest/economic_workflow.py)
publishes and reopens actual saved synthetic ZIP bytes through these boundaries.

The spec declares the instance, source/stream/instrument binding, half-open sample,
initial quote cash, strategy size, independent limits, costs and clocks. The
[synthetic example](../../tests/fixtures/economics/spec.json) uses the baseline's
spot units and costs over four minutes. Its shorter synthetic window is software
evidence, not a replacement for the frozen hour or its source requirements.
Select `completed-price-momentum-v1` or `no-trade-v1`; unknown implementations
fail. Each invocation owns independent holdings, observations and pending state.
The same path is exercised for BTC and ETH without asset-specific code.

| Functional owner | Public responsibility |
| --- | --- |
| `research.observations` | Admit scoped history, select bitemporal eligibility, freeze completed event windows, preserve missingness and future event clocks |
| `strategies` | Return absolute targets from adjacent frozen closes; no executable clients or risk approval |
| `risk` | Enforce explicit base-unit spot dimensions, lot/tick grids, maximum holdings, one pending reservation and actual fill affordability |
| `simulation` | Price adverse fills and round fees, apply scheduler phases, retain traces/checkpoints, and project the supported vectorbt comparison |
| `accounting` | Post identified fills exactly once; retain cash, position, rational basis/P&L and both gross-to-net reconciliations |
| `applications.backtest` | Resolve reviewed rules and compose collaborators; retain/publish formal comparisons through existing experiment APIs |

These owners expose one curated `__init__.py` API each. The sole installed
`alpha-backtest` application command now exposes configured execution, atomic
report publication and local serial pipelines through the
[study owner](../research/studies/README.md#configured-economics-reports-and-serial-pipelines).
The current installed Python workflow is the application consumer. The same
command also exposes `qualify-features` over an existing configured result. It
compares shared completed-price features across replay, scheduled batch calls and
serialized restart, retaining exact traces and their original source limitations;
see the [feature contract](../research/features/README.md#scheduled-completed-price-parity).

## Time, controls and completion

`Replay.step` remains authoritative for equal-clock ordering: admit all source
and control events, expire, fill, decide, then mark. Batch size does not affect
this sequence. A window ending at `t` selects the latest event in `[t-cadence,t)`
known by `t`, with causal source order breaking event-time ties. The value freezes
at that close. Missing, stale, invalid or known-gapped windows remain explicit;
they are not filled forward or turned into zero returns. A control exactly at the
close is outside the completed half-open window but independently blocks a new
intent at that clock. Unrelated source/instrument controls remain isolated.

An intent reserves one full target delta from actual holdings. Buy reservations
retain estimated cash at the decision reference; this is not a guarantee of
future affordability. The first eligible print must have both event and knowledge
clocks at least `decision + delay`; execution uses their later clock and is
strictly before expiry. An already known future event receives an explicit
scheduler wakeup. An old print cannot become eligible merely by waiting.
Every fill is checked again against actual cash, quantity and costs. Rejections
remain trace outcomes and do not resize, partially fill, borrow or mutate balances.
A newly known scoped gap cancels a pending intent. It cannot undo a prior fill.

The engine values at completed decision clocks and the terminal. Intermediate
missing valuations remain visible in the trace. Missing/stale/ineligible terminal
valuation with an open holding prevents a completed result. Flat NAV needs no
price and still retains admitted data-quality limitations. Terminal expiry keeps
holdings; it never invents liquidation. The bounded path accepts only the existing
exploratory admission scope, and does not upgrade its coverage or availability
claims even for the no-trade control.

## Exact accounting and recovery

Prices, quantities, cash, notionals and marks use existing C03 values. Fees are
rounded once to the declared quote quantum; the baseline uses half-even. The
separate hand oracle uses half-up, including the distinguishing `0.205` tie.
No ambient Decimal context controls a calculation. Basis and realized/unrealized
attribution use currency-bearing reduced rational values; their containing balance
binds the instrument through the holding. Partial sales release basis proportionally
without rounding. Returns retain canonical numerator/denominator strings.

Effective-price realized plus unrealized P&L minus fees equals NAV change exactly.
Reference-price gross P&L minus adverse slippage and fees gives the same result.
Slippage is not subtracted twice. Duplicate identities, negative cash, overselling,
unit mismatch and unrepresentable C03 results fail before a posting commits.

`stop_at` returns an `EconomicCheckpoint` after a complete replay step. Serialize
it with `DomainCodec`; resume passes it to the same application alongside the same
verified inputs and spec. It contains the source cursor, frozen observations,
latest admitted revisions, scoped controls, next decision, pending reservation,
applied fills, ledger and trace. Schema, input/configuration identity, state digest,
clocks and posting/trace consistency are checked. A cursor alone is insufficient.
The digest detects accidental byte changes; it is not authentication of hostile
state. Offline checkpoints are not an account recovery or fencing protocol.
The reference is materialized under the query's byte cap, with at most 1,024
scheduled closes; large-study scaling remains future work.

## vectorbt and tracking

`VectorbtAdapter.run(reference)` independently regenerates supported rule targets
from the verified frozen observations and selects explicitly delayed source
prints. Accepted reference fills are compared afterward, not used to generate the
orders. The adapter uses vectorbt **1.1.0**, the explicitly selected **Numba** backend,
long-only target-amount sizing, no partial fills or capital sharing, adverse prices
and already-rounded fixed fees. It records vectorbt, Numba, llvmlite, NumPy, pandas
and Plotly versions, exact order assumptions and the source result digest.

This scope requires complete observations, no gaps or available revision changes,
and initial capital covering all gross purchases without reuse of sale proceeds.
Unsupported scope fails explicitly. It does not model queues, available size,
impact, derivatives, leverage, shorting or multiple accounts. A bar library's
same-bar defaults never select an execution time here. Float output is analytical:
comparison uses absolute tolerance `1e-10` quote units and relative tolerance
`1e-12`, accounting for float operations across this bounded trace. It never
replaces the exact ledger or relaxes exact reconciliation.

`applications.backtest.compare_vectorbt` requires an explicit no-fit experiment
split, family, attempt store and `ClearMLDestination`. This first formal consumer
accepts validation-window studies only; it cannot read a held-out window. It retains
both `economic-reference` and `vectorbt-comparison` artifacts, including their
complete inputs and engine assumptions. Local completed/failed/abandoned outcomes
remain separate from publication success. Existing `ClearMLPublication` retries
publish the same attempt/task without rerunning economics. A missing server does
not prevent `run_backtest` or direct analytical projection.

The installed economic consumer tests unavailable publication. The separate
[publication verifier](../../tests/integration/consumers/research/clearml_publication.py)
uses explicitly selected local-test credentials in `ALPHA_CLEARML_LOCAL_ENV` to
reconcile retained attempts and compare downloaded artifact bytes. Credentials
never enter specs or manifests. See the [local server guide](../../configs/development/clearml/README.md).

## Verification and reversal

The [hand ledger tests](../../tests/unit/accounting/test_ledger.py) independently
check cash `798.80` / `1017.58`, P&L `17.58`, fee ties and `302/3` released basis.
The [economic tests](../../tests/unit/simulation/test_economic_replay.py) cover the
baseline's distinct half-even costs, `1/10003` return, no-trade, future information,
scoped gaps, strict expiry, delayed/unknown execution, affordability, terminal
holdings, batches, resume and the actual vectorbt backend. The installed consumer
runs from the wheel smoke's isolated environment and reopens saved inputs and a
pending checkpoint in a fresh process.

Revert the owners, application, package inventory, lock/admission records and
consumer tests together. Preserve retained results/checkpoints and ClearML tasks
as historical evidence. An older wheel must not resume the new checkpoint schema.
Existing query APIs, snapshots and previously installed commands retain their contracts. There is
no deployment, account state or trading activity to reverse.


Frozen engineering-sample execution now uses the same runner through the
[configured experiment mode](../research/studies/README.md#unfitted-engineering-samples).
Native archive witnesses carry their effective availability through observations,
delayed fills, terminal marking and complete checkpoint recovery. Economic reports
preserve admission scope and unknown coverage; completed accounting does not itself
establish empirical P1 acceptance. Frozen parameters and the original independent
hand-ledger/rounding oracles are unchanged.
