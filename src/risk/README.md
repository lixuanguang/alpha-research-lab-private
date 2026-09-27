# Independent order and exposure risk

Owner: `risk`. Status: implemented for local cash-funded spot admission.

`risk.budgets` provides the pure limit decision used by the account journal. A
`BudgetPolicy` declares one valuation currency, a firm ceiling, account and
instance ceilings, permitted instrument IDs per instance, quote and state age
limits, maximum order price deviation in basis points, and maximum order
notional. The initial local paper accounting path is cash-funded spot. An order
in another currency is rejected until an explicit FX valuation policy exists;
the currency type and instrument identity remain general.

`BudgetEngine.evaluate(policy, request, commitments)` returns a stable rejection
reason or `None`. The request carries a portable `OrderIntent`, its account and
instance owner, a current typed quote, decision/quote/account-state UTC times,
and a fee cap. Its price and size comparisons use exact rational arithmetic.
The engine checks authorization, currency and dimensions, clock causality,
freshness, price deviation, order notional, and the nested instance, account,
and firm limits. It never clips an order.

An `ExposureCommitment` has one owner and nonnegative marked held exposure plus
unresolved reservations. Pending and uncertain orders stay in reserved exposure
until their confirmed terminal outcome; cancel acknowledgment alone does not
release it. For cash spot, a new buy consumes full limit notional plus its fee
cap. A sell consumes its fee cap, while the held position remains in marked
exposure until the confirmed fill. The execution owner independently validates
inventory, cash, venue grids and order lifecycle through `SpotLimits` and the
ledger. There must be exactly one commitment record per instance in the supplied
authoritative snapshot, including explicit zeros for flat instances; missing,
unknown or duplicate owners fail closed.

The risk engine neither reads account state nor writes a reservation. The
execution journal must obtain the authoritative snapshot, evaluate it, and
persist the admitted reservation in **one serialized SQLite transaction**.
Calling the engine outside that transaction cannot establish atomic shared
budgets. The caller must also preserve a risk block after an account break or
unresolved external outcome. This pure decision does not qualify physical
venue positions, private streams, FX, production deployment or live orders.

In [public-input paper matching](../execution/README.md#public-input-paper-matching),
the strategy first passes this independent firm/account/instance admission and
reserves its maximum fee and pending exposure. The matcher has no authority to
increase a limit or release an unknown order. Its finite quote and cost scenario
select modeled outcomes only for previously reserved physical orders; a fill
above the reserved fee fails closed and retains an account fault. A touch whose
adverse effective price exceeds the order limit produces no modeled fill.
An acknowledged or delayed cancel remains exposed until confirmed terminal.
These assumptions and simulated fills establish software behavior, not exchange
execution probability or new risk authority.

Focused validation:

```sh
TMPDIR=/private/tmp PYTEST_ADDOPTS=--basetemp=/private/tmp/mr08-risk \
  uv run --frozen --no-editable pytest -q tests/unit/risk/test_budgets.py
uv run --frozen ruff check src/risk/budgets.py tests/unit/risk/test_budgets.py
uv run --frozen mypy --strict src/risk/budgets.py tests/unit/risk/test_budgets.py
```
