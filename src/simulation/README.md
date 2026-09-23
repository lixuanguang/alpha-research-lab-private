# Bounded spot economics

Owner: repository founder. Status: implemented for synthetic/offline research;
verification is recorded in [MR 5](https://github.com/lixuanguang/alpha-research-lab-private/blob/31fcc842fa5a55daafe0764dd4d99912d082329c/docs/roadmap/history-mr1-to-mr9a.md#first-economic-backtest).
The [frozen baseline](../../docs/research/p1-baseline.md) owns the experiment's
assumptions. This library does not establish historical source coverage, empirical
alpha, executable liquidity, release admission or trading authority.

## Saved L2 IOC research

`applications.backtest.run_books` and `alpha-backtest books` now compose verified
saved OKX L2 observations with independent long-only spot accounts. The
[usage and acceptance record](../../docs/research/l2-book-backtest.md) owns the
configured command, actual saved ETH-USDT result, fee/timing/depletion contracts,
restart procedure and limitations. The [notebook](../../examples/orderbook-research.ipynb)
uses that same implementation. `BookSimulation` keeps exchange and delivered books
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

The installed consumer tests unavailable publication first. With explicitly
selected local-test credentials in `ALPHA_CLEARML_LOCAL_ENV`, it also reconciles
the retained attempt to the existing local server and compares downloaded artifact
SHA-256 values. Credentials never enter specs or manifests. See the
[local server guide](../../configs/development/clearml/README.md).

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
