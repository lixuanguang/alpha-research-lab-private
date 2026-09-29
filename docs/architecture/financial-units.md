# Typed Financial Units and Conventions

## Objective and boundary

`financial_units` owns immutable in-process financial values and
explicit convention adapters under the [current architecture decision](README.md#current-architecture-decisions).
It supplies the repository's money, FX, price, yield, volatility, rate, duration,
multiplier, lot, tick and quantity abstractions. It adds no wire schema, position,
cash ledger, valuation engine, executable order, risk decision or market authority.

The convention adapter uses `QuantLib==1.43`. Version 1.40 failed the pinned
Python 3.12.14 warnings-as-errors import check with a native segmentation fault;
1.43 passes without changing warning filters. The dependency policy's bounded
profile admits 1.43 only for isolated development and CI through 2026-10-04.
Authenticated wheel publication is not authenticated build provenance. The
release boundary blocks production release, signing and publication while this
admission remains. Development wheel builds and installation tests are permitted.

MR06 separates the operating value closure from this optional adapter:
`alpha-research-contracts` ships exact values, ratios and currency definitions,
without `conventions.py` or QuantLib. The complete research wheel retains both.
Existing explicit public convention imports remain available in that research
environment through Python's lazy module-attribute hook; ordinary financial-value
imports no longer initialize the native adapter. Requesting a convention API in
an operating-only environment fails because its implementation is absent. The
[selected-closure admission](dependency-admission.md#first-deployment-dependency-decision)
qualifies actual installed operating artifacts and preserves the separate
QuantLib restriction.

## Public values and operations

| Interface | Meaning and invariant |
| --- | --- |
| `Currency` | Frozen `(code, minor_unit)` value with a valid uppercase ASCII code and positive finite exact accounting quantum; immutable configured defaults come from the packaged [`default_currencies.json`](../../src/financial_units/default_currencies.json) definitions and are selected by code |
| `Dimension` | C01 instrument identity plus share, contract, base-unit or face-amount kind; different instruments never share a dimension implicitly |
| `Money` | Signed Decimal amount and currency; `rounded(mode=...)` explicitly rounds to its accounting minor unit |
| `Quantity` | Signed Decimal amount and native dimension; `rounded(lot, mode=...)` requires matching dimensions |
| `Price` | Signed currency per dimension; negative commodity prices are representable; `amount(quantity)` cancels matching dimensions exactly |
| `Tick`, `Lot` | Strictly positive price and quantity increments, respectively; no order-side or venue acceptance inference |
| `Multiplier` | Strictly positive output units per input unit; `apply(quantity)` names both dimensions and returns the output dimension |
| `FXRate` | Strictly positive quote units per base unit; `convert(money, target=..., mode=...)` accepts either explicit pair direction and rounds once |
| `Rate`, `Yield` | Distinct signed annual fractions, with explicit `RateConvention`; 0.05 means five percent, with no implicit percent/basis-point conversion |
| `RateConvention` | Exact day count and simple, continuous or periodic compounding; periodic quotes require 1, 2, 4 or 12 payments/year |
| `Volatility` | Nonnegative annual fraction per square-root year, with explicit day-count year basis; no pricing model or annualization estimator |
| `Duration` | Nonnegative elapsed year fraction with day-count basis; no Macaulay/modified/effective bond sensitivity is computed |
| `EvaluationContext` | Explicit evaluation date and bounded convention-revision token; no wall clock or process global |

`Currency` is a value object rather than an ISO registry, currency lifecycle,
cash-payment rounding rule, entitlement or venue authority. Its code and exact
minor unit are both part of identity, so a custom value such as
`Currency(code="GRID", minor_unit=Decimal("0.05"))` is valid without changing a
global registry. A code with a different minor unit is a different currency
dimension and cannot be mixed implicitly. The packaged JSON supplies only the
retained compatibility definitions; `Currency.from_code("USD")` selects a
known configured default, while authored values pass both `code` and
`minor_unit` explicitly. Duplicate or invalid definitions fail package loading.
Python constructors require complete `Currency` values, so raw strings and
unknown values are rejected at this boundary. An instrument reference does not
certify that instrument or grant its use in trading.

The authored reference catalog carries a complete USDT `Currency` object as a
distinct token unit. Its eight-decimal accounting quantum is an accounting
convention for the bounded foundation metadata; the bounded quote-currency spot ledger now consumes it under the frozen baseline's
explicit assumptions. This does not identify USDT with USD,
define blockchain transfer precision, or certify historical venue fee/settlement
rules. New authored settings belong in the catalog and do not require changing
packaged compatibility definitions.

All numeric inputs must be finite `Decimal` objects with representation exponent
between -18 and 18 and magnitude strictly below 1e18. Floats, strings, booleans,
NaN/Inf and excessive precision/magnitude fail construction. Exact results must
fit the same 1e-18 grid and magnitude; no hidden quantization rescues overflow or
underflow. Numeric zero, including signed zero, compares as zero. Returned exact
values use the 1e-18 representation; that scale is not itself currency precision.

Addition and subtraction require identical concrete types and all dimensions,
including currency, instrument, unit and convention metadata. Other operator
algebra is unsupported. Price/quantity, multiplier and FX operations make allowed
unit cancellation explicit. The types are frozen; no public mutation or ambient
Decimal precision changes can alter their arithmetic.

All C03 values use strict frozen Pydantic 2.13.5 `BaseModel` construction, with
unknown-field rejection, default validation, input-hiding errors and nested-instance
revalidation. Constructors retain `UnitError` and convention results retain
`ConventionError`; structured `model_validate` calls report `ValidationError`.
Field mutation raises `ValidationError`. Equality and hashing retain value semantics
and distinguish concrete types. Nested fields require exact owned model instances;
callers translate nested mappings before constructing a parent model.

`model_copy(update=..., deep=...)` reconstructs and validates the complete value,
including changed and nested fields. Numeric operations use this validated path.
Do not use `model_construct` or call unchecked framework base primitives directly
to supply domain inputs. Those low-level methods are outside this API contract.
`model_dump` is a local inspection surface, not a versioned transport schema.

`Rounding` distinguishes mathematical floor, ceiling, toward-zero and nearest
with ties to an even grid index. Arbitrary increments such as 0.05 are handled
by exact rational quotient/remainder, not `Decimal.quantize`'s exponent alone.
Negative values obey the same mathematical rules. FX division is exact until
its single requested target-quantum rounding; no intermediate inverse quote is
rounded. No netting, spread, fee or cashflow convention is inferred.

## Planned research and accounting arithmetic

`ExactRatio` is now the public dimensionless rational record used by retained
[feature/label diagnostics](../../src/research/features/README.md). Its
`from_fraction` factory preserves an exact calculation; constructors and the
existing domain codec reject noncanonical or unreduced integer strings and
nonpositive denominators. The [accounting consumer](../../src/simulation/README.md#exact-accounting-and-recovery)
now supplies currency-bearing rational basis/P&L and exact spot postings. C03
financial-unit conventions and grids remain unchanged.

Decision date: 2026-09-14. This originally resolved the P1 consumer contract before observations and ledger
implementation. The consumer now implements it without widening C03's decimal
grid. The [simulation verification guide](../../src/simulation/README.md#verification-and-reversal)
describes its accounting and recovery evidence.

| Quantity | Representation and boundary |
| --- | --- |
| Prices, quantities, cash postings, notional and marks | Existing exact C03 values. Supported products must fit its grid and magnitude or fail. Cash changes retain exact notional; P1 rounds only each fee once to the quote quantum with half-even. No automatic rounding of cash or valuation to a display quantum. |
| Exact returns and proportional attribution | Reduced rational values computed from exact Decimal inputs using `Fraction`, never a prior Decimal division or float conversion. Returns are dimensionless; cost basis and realized/unrealized P&L retain their currency, with basis bound to the position's instrument. These are attribution values, not rounded cash postings or C03 `Money` values. |
| Analytical/model outputs | Each consumer declares representation, units and justified tolerance. Approximate presentation or model output cannot replace exact decision, posting or reconciliation values. |

For a sale of quantity `q` from holding `Q` with rational basis `B`, release
`B * q / Q` exactly and retain `B - B * q / Q`. Zero holdings have zero basis;
a full sale releases all remaining basis. Fees remain separate immediately
recognized costs. Realized plus unrealized attribution minus fees equals the
exact NAV change, with no tolerance on this P1 identity. Any conversion back to
C03 must prove grid/magnitude representability or reject it; ambient Decimal
precision never chooses an allocation or realized P&L.

Planned records serialize a rational as a canonical numerator/denominator pair
of base-10 integer strings, with a positive denominator, coprime terms and zero
encoded as `0/1`. Preserve dimensions and schema version in the containing
record. Constructors/codecs reject malformed, noncanonical or zero-denominator
values. Decimal displays are explicitly derived, with named precision/rounding,
and excluded from authoritative reconciliation and decision inputs.

Decisive consumer cases include the return from `100.03` to `100.04`, exactly
`1/10003`, and buys of one unit at `100` and two at `101`, followed by a one-unit
sale releasing basis `302/3` and retaining `604/3`. Round-trip and resumed state
must preserve these fractions under changed Decimal contexts. For fees, a true
tie of `0.205` at quantum `0.01` yields `0.21` under the independent oracle's
half-up and `0.20` under P1's half-even. Existing oracle amounts remain unchanged;
`simulation.SpotCosts` now supplies the explicit half-up fee operation alongside
the baseline half-even policy without changing C03. These cases are covered by the
[accounting consumer tests](../../tests/unit/accounting/test_ledger.py); foundation
unit tests alone do not establish economic transitions.

## Convention adapter

`QuantLibConventions.year_fraction` requires context, start, end and one of:
Actual/360, Actual/365 Fixed, Actual/Actual ISDA, 30/360 Bond Basis or 30E/360.
Each has its own enum; generic Actual/Actual and 30/360 aliases are unsupported.
Dates must be plain `date` values within 1901-2199, with end at or after start.
`time_to` uses the supplied evaluation date as start. Zero-length periods return
zero; reversed intervals fail. No coupon schedule or reference period is guessed.

The adapter checks both installed distribution and library version, constructs
only local date/day-counter objects and never reads or writes QuantLib Settings,
fixings, calendars, curves or pricing handles. `DayCountResult` retains the exact
context, interval, day-count basis, owned duration and adapter version. Native
exceptions become `ConventionError` with their cause; invalid native results fail.

The double result is rounded once to 1e-15 years. Hand-calculated goldens require
absolute tolerance 1e-12 years and relative tolerance 2e-15 over the supported
maximum 299-year scale. These budgets allow native double division and final
rounding; they never apply to money, quantities or dimensional checks.

`SettlementConventions(calendar)` owns adjustment and lag operations for one
explicit C02 calendar. Construction revalidates and retains an independent
calendar copy; operations use that immutable snapshot without retaining
intermediate results. Invalid calendars fail at construction.
The module-level `adjust_business_day` and `settlement_date` forwarding APIs and
their package exports have been retired. Construct a service once and reuse its
methods for the selected calendar.

Construction now precedes operation arguments: an invalid calendar fails before
an invalid candidate, convention or lag can be checked. This deliberately retires
the wrappers' earlier argument checks. On a valid service, adjustment still checks
candidate type, convention type, then coverage; settlement still checks lag before
calling adjustment. Domain errors, chained calendar-validation causes and bounded
selection failures retain their existing meanings.

`SettlementConventions.adjust_business_day` uses the bounded C02
`SettlementCalendar` eligible-date set for unadjusted, following, modified
following, preceding and modified preceding.
Modified adjustments reverse direction when the primary result changes year or month.
It never guesses weekends or holidays. Missing primary/alternate dates or dates
outside coverage fail, including when a modified adjustment cannot establish the
primary result from the bounded snapshot. Unadjusted still checks coverage.

`SettlementConventions.settlement_date` first applies the explicit adjustment
and then counts the requested 0-366 eligible-day lag strictly after the adjusted
anchor. Zero returns the anchor; positive lags exclude it even when unadjusted
leaves it ineligible.
The caller chooses this convention explicitly. There is no joint-calendar, spot
FX, end-of-month schedule, settlement engine or authoritative value-date service.

## Tests, risk and evidence

The synthetic [golden fixture](../../tests/golden/financial_units/c03_units.json)
contains hand-calculated leap-day, year-boundary, zero-period and distinct 30/360
cases, plus signed ties and non-power-of-ten rounding. Deterministic properties
check tick/lot grid membership, idempotence, rounding direction/error and FX
forward/reverse error propagation. Monetary results are exact; nearest FX
conversion permits at most half a target minor unit, and round-trip error permits
that error translated back plus half a base minor unit.

The requested Currency revision generalizes coverage to code/quantum identity,
custom values and non-power-of-ten rounding grids, while retaining
currency/instrument/convention mixing, type coercion, immutable values,
non-finite/overflow/precision inputs, invalid native results, version and native
failures, calendar limits, settlement lags, unchecked C01/C02 model copies,
multi-year modified adjustments, and independence from Decimal context and
QuantLib's evaluation date across concurrent calls.
Current coverage is organized by [arithmetic and rounding](../../tests/unit/financial_units/test_financial_units.py),
[model validation](../../tests/unit/financial_units/test_unit_model_contracts.py),
[settlement](../../tests/unit/financial_units/test_settlement_conventions.py),
[native conventions](../../tests/unit/financial_units/test_quantlib_conventions.py),
and [currency identity](../../tests/unit/financial_units/test_currency_units.py).
A bounded local performance check is diagnostic and supplies no target latency/SLO
certification.

The direct [golden fixture](../../tests/golden/financial_units/c03_units.json)
and focused tests are the behavioral evidence for this contract. Dependency and
artifact checks retain the exact lock, source-origin and hash checks, vulnerability coverage,
and release block described in the [dependency policy](dependency-admission.toml)
and [release workflow](../governance/workflow.md#build-a-release).

## Migration, rollout, rollback and runbook

`Currency` replaces enum semantics with a complete immutable value. Named class
attributes have been removed: callers using `Currency.USD` must migrate to
`Currency.from_code("USD")` for a known configured default, or construct the
full `Currency(code=..., minor_unit=...)` value for an authored unit. Use
`.code` for text and explicit `code`/`minor_unit` fields for authored units.
Enum iteration and string equality are no longer supported.

Currency remains a strict frozen Pydantic C03 value; this candidate's shared
`msgspec` serialization boundary supplies its exact wire hooks alongside the
canonical market-event codecs. Currency wire values persist both `code` and
`minor_unit`; at currency, money, and price boundaries, a bare code string is
rejected as an unsupported currency schema. Market-event codecs preserve their closed tags and exact Decimal
text. Configured backtests, simulated orders/fills, checkpoints and retained
reports now use the shared serialization boundary; venue execution remains
planned. The packaged currency JSON is an owned preset input;
changing it changes package content and invalidates the corresponding uv cache
key. QuantLib remains exactly 1.43. New consumer schemas require their own
versioned compatibility and evidence.
No deployment or activation is introduced.

Rollback reverts Currency source, packaged definitions, shared serialization and
market-event codecs, tests and documentation together, preserving historical
candidate evidence. A later consumer migration must first account for dimensions,
precision, convention revisions, wire compatibility and replay obligations.

On `UnitError` or `ConventionError`, stop the affected calculation. Retain safe
instrument/currency dimensions, explicit context and source/calendar revisions,
operation, adapter version and exception cause. Reconcile inputs with the domain
owner, issue corrected versioned inputs and replay goldens and consumer tests.
Never substitute a unit, infer a calendar, suppress a warning, mutate global
Settings or round implicitly to recover. Admission expiry or evidence mismatch
stops validation; resolve the dependency evidence or replace/remove the
dependency before any artifact release.
