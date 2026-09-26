# Exact spot accounting

`accounting` owns exact cash-funded spot postings and attribution. The current
source has two distinct ledgers. [`ledger.py`](ledger.py) retains the original
single-instrument simulation and dedicated paper contract;
[`accounts.py`](accounts.py) adds a normalized account posting history for
multiple instruments and currencies. These schemas are not interchangeable, and
the new account ledger does not calculate P&L or marks. The
[MR08 roadmap record](../../docs/roadmap/README.md#mr08-delivery-and-acceptance)
owns the wider risk and reconciliation acceptance status.

## Single-instrument ledger

The package-level `Fill`, `LedgerState`, `Ledger`, `LedgerBalance`, `LedgerMark`
and `RationalMoney` exports preserve the existing API. `LedgerState` binds one
initial `Money` balance, one `Dimension`, a complete ordered fill history and
the `spot-ledger-v1` schema. `Ledger.apply(fill)` posts a signed quantity once,
rejects insufficient cash or inventory, and updates exact cash, holdings, fees,
turnover, basis and realized attribution. Its `Fill` combines the execution
price and a nonnegative quote-currency fee. It requires a strictly later UTC
fill than decision and currently rejects favorable effective prices relative
to its reference price.

`Ledger.mark(price)` values an open position at a supplied compatible positive
price. Basis and realized/unrealized attribution use currency-bearing rational
values, so proportional sales never depend on Decimal division or ambient
precision. Effective-price realized plus unrealized P&L minus fees equals the
NAV change exactly; reference-price gross P&L minus slippage and fees gives the
same result. This ledger remains the owner used by
[simulation](../simulation/README.md#exact-accounting-and-recovery) and the
[dedicated paper journal](../execution/README.md). It has no transfer, rebate,
correction, multi-instrument or multi-currency API.

## Normalized account postings

Import `AccountPosting`, `AccountState`, `AccountLedger`, `AccountSnapshot` and
`EffectiveAccountPosting` from `accounting.accounts`. `AccountState` declares an
account ID, a nonempty ordered tuple of complete `Currency` values with unique
codes, every posting in knowledge order, and the `account-postings-v1` schema.
It starts with zero cash and zero inventory. An identified `transfer` posting
supplies initial capital; no implicit funding or FX conversion occurs.

Each `AccountPosting` carries a stable identity, account ID, UTC source
`event_at`, UTC local `known_at`, a kind, and a signed `Money` cash effect. The
knowledge time cannot precede the event time and must be nondecreasing through
the account history. A delayed event may have an earlier source time than a
previously posted event. The economic rules are:

| Kind | Required effect and lineage |
| --- | --- |
| `fill` | Nonzero signed `Quantity`, positive dimension-matched execution `Price`, instance ID and order ID. Cash equals `−price × quantity` exactly; a buy debits cash and a sale credits it. No reference-price or adverse-price assumption is imposed. |
| `fee` | A separate strictly negative cash effect in a declared currency. An instance and order may attribute the cost. |
| `rebate` | A separate strictly positive cash effect in a declared currency. An instance and order may attribute the credit. |
| `transfer` | A separate nonzero signed cash effect without an order ID. An unowned transfer affects physical cash but no instance's attributed cash. |
| `correction` | References the current revision of one original posting through `corrects`. `replacement_kind` either retains that original economic kind with replacement terms or is absent to void its effect. The correction keeps the original account, instance, order, currency and, for fills, instrument dimension. |

`AccountLedger.post` stages and validates the whole resulting state before it
commits. A repeated identity with identical canonical `DomainCodec` bytes is a
no-op; changed bytes under that identity fail. Corrections append a new record
and atomically remove the previous effect before applying replacement terms.
They may form a chain by referencing the latest correction. Neither retries nor
corrections erase the earlier history. After every fact, physical cash in each
currency and both aggregate and instance inventory must stay nonnegative.
Unsupported amount grids or magnitudes fail before state changes. This is an
unlevered, long-only spot accounting boundary, not a borrowing or shorting
model.

`snapshot()` returns physical currency cash in the declared currency order,
nonzero per-instrument positions, cumulative positive fees and rebates, signed
transfers, active original fill IDs and every historical posting ID. Positions
are sorted by their canonical dimension wire representation. For
`snapshot(instance_id)`, only that instance's postings contribute; unowned
funding is excluded, so its attributed cash can be negative even when physical
account cash is funded. `effective_postings()` exposes the current economics
under each original `identity` and names the active `revision_id`. A corrected
fill therefore keeps its original fill identity; a voided fill leaves the
effective set. Account-level and instance projections are distinct views of the
same retained posting history.

Shared portfolio execution allocates a physical fill into identified strategy
postings before calling this ledger. The [account journal](../execution/README.md#portfolio-coordination-and-recovery)
retains the original physical fill and its child mapping and verifies their
quantity, cash and cost totals. Ledger fill IDs therefore identify attributed
effects; physical source IDs remain at the execution boundary. Explicit
internal crossing uses paired owned inventory/cash postings with zero fee and
no aggregate physical cash or position change. It is not a venue execution.

Revise a shared physical fill's fee through `AccountJournal.correct_net_fee`
with an identified `NetFeeCorrection`. The journal applies the original
per-fill allocation weights, appends fee revisions here, updates order cost
reservations and requires reconciliation before new risk. Repeated and voided
revisions retain their original posting lineage. Editing an allocated fee
independently cannot establish agreement with its physical source total.

The [financial-unit contract](../../docs/architecture/financial-units.md#public-values-and-operations)
defines `Money`, `Price`, `Quantity`, `Currency`, `Dimension` and the exact
1e-18 grid. Account balances and cost totals remain separate by currency;
accounting does not silently choose a valuation currency, FX source, fee
rounding rule or display precision. Fee and rebate postings here change
currency cash; representing a native base-asset fee as a position deduction
requires an explicit instrument-to-currency mapping before venue qualification.

## Recovery and consumers

`AccountLedger.state` is the complete immutable replay input. Encode and decode
it with `DomainCodec`, then construct a new `AccountLedger` to revalidate every
posting, clock, correction and balance. The ledger itself has no database,
fencing lease, order reservation or external observation authority. The
[`execution.accounts.AccountJournal`](../execution/accounts.py) composes it
with order state and admission in a SQLite transaction; that owner must retain
unknown exposure and compare an independently supplied whole-account snapshot
and open orders before clearing a break. A local paper observation is not an
authenticated OKX or Bitfinex account observation. Venue adapters, base-asset
fee rules and physical reconciliation still require their own qualification.

The MR11 software increment adds `AccountPosting.asset_change` for identified
base-asset fees/rebates. Such a posting records the native signed cost and changes
inventory, without inventing a debit or credit to quote cash. Cash and asset
effects remain distinct in replay, corrections and snapshots. The execution owner
atomically combines these costs with `NativeFill` and deterministic direct/net
child attribution; positive cost consumes a cumulative quote-denominated fee
allowance valued at each actual fill price. A rebate does not authorize new
orders or silently enlarge that allowance. Third-currency conversion remains
unsupported. `PhysicalAccountObservation` compares actual wallet totals to cash
plus mapped spot holdings, with no fabricated external posting identities.
See the [native execution contract](../execution/README.md#test-venue-execution).

The [single-instrument hand ledger tests](../../tests/unit/accounting/test_ledger.py)
cover exact basis, P&L and fees. The
[account posting tests](../../tests/unit/accounting/test_accounts.py) cover
multiple currencies and instruments, retries, corrections, delayed event times,
funding and inventory failures, restart encoding, and low Decimal precision.
Run those focused tests from the repository root with a short pytest temporary
path on macOS:

```sh
uv run --frozen --no-editable pytest -q --basetemp=/private/tmp/ar-account-test tests/unit/accounting/test_ledger.py tests/unit/accounting/test_accounts.py
```

The [engineering guide](../../docs/coding_standards/README.md#commands-and-enforcement)
owns source checks and the complete local validation gate. Source tests establish
software arithmetic behavior within their fixtures; the roadmap records broader
account, source and operating evidence separately.
