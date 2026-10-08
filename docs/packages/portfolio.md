# Portfolio allocation policy

Owner: quant development. `portfolio` owns `PortfolioContext` and the exact
reference allocation policy; [`execution.AccountJournal`](execution.md#portfolio-coordination-and-recovery)
owns its atomic admission, physical orders, postings and recovery. This package
ships in the research and independent execution wheels. It introduces no new
service or data dependency.

`PortfolioContext` retains portfolio/strategy identity, model and configuration
revisions, horizon and reason, plus venue, settlement, risk bucket and authority
scope. The journal also checks account, complete instrument dimension, currency,
limit, time-in-force and observed quote before grouping physical orders. Changing
a descriptive label does not grant instrument or account authority. The initial
consumer supports cash-funded spot with explicit grids and one valuation currency;
other products and FX aggregation remain unsupported at the execution boundary.

`ProRataAllocator` uses exact integer/Fraction arithmetic with stable child
identity ordering. Its quantity operation accepts original shares, already
allocated quantities and a cumulative physical fill, returning nonnegative
increments without reallocating earlier fills. Its cost operation allocates a
nonnegative amount within each child's remaining fee reserve; deterministic
residual priority prevents rounding from creating or losing money. The journal
retains physical and child identities so allocations can be checked against
independently observed physical totals after restart. This explicit engineering
policy is not an economically optimized allocation or empirical strategy result.

Quantity increments use an explicit exact quantum and a bounded deficit-priority
allocation with stable identity tie-breaking. The journal chooses the quantum
from the physical fill price so both attributed quantities and cash remain
representable on the financial grid. An impossible exact split fails closed;
the allocator neither drops dust nor exceeds a child's remaining quantity.
Physical-lot residuals, and children held back because their quote is stale, their
limit drifted beyond the price bound, or their owner is over a budget ceiling at
current marks, remain visible and reserved in the journal until netting retires
those whose decision has outlived the budget policy's residual age. Fee capacity
also remains reserved for a completed child while its shared parent can still
receive costs. Corrections use the original per-fill reservation weights and
append attributed cost revisions without changing original execution facts.

In the [public-input paper path](execution.md#public-input-paper-matching),
the matcher consumes one finite displayed quote allowance per physical net
parent. `AccountJournal` then applies that parent's modeled lifecycle fact and
the existing child quantity, cash and fee attribution in the same SQLite
transaction. Each strategy retains its own order and posting identities; a
market quote does not create a second allowance for each child. A later cost
revision changes effective fee attribution without rewriting the original
physical or child fill. Complete independent account reconciliation still
compares the physical parent cumulative and attributed totals.

The public methods reject repeated identities, mismatched vector lengths,
negative values and totals beyond the supplied capacity. The exact-grid and
magnitude contract is owned by [financial units](../architecture/financial-units.md).
The [allocation regressions](../../tests/unit/portfolio/test_allocation.py) and
[account regressions](../../tests/unit/execution/test_portfolio_accounts.py) cover
residuals, fees, independent totals and recovery. The
[roadmap record](../roadmap/overview.md#capabilities) owns
current acceptance evidence and remaining operating qualification.
