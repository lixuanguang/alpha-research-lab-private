# Typed Financial Units and Conventions

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | C03 |
| Operating track | Solo bootstrap |
| Implementation status | Complete |
| Institutional status | Partial |
| Accountable owner role | Domain Architecture |
| Dependencies | C01-C02, provisionally satisfied with open institutional findings |
| Change risk | R2, shared financial library and native dependency boundary |
| Applicable gates | QG01-QG14 |
| Evidence retention | Shared-contract compatibility lifecycle |

## Objective and boundary

`alpha_research.financial_units` owns immutable in-process financial values and
explicit convention adapters under [ADR 0013](decisions/0013-explicit-financial-units-and-conventions.md).
It supplies the blueprint's money, FX, price, yield, volatility, rate, duration,
multiplier, lot, tick and quantity abstractions. It adds no wire schema, position,
cash ledger, valuation engine, executable order, risk decision or market authority.

The maintainer selected `QuantLib==1.43` for C03. Version 1.40 failed the pinned
Python 3.12.14 warnings-as-errors import check with a native segmentation fault;
1.43 passes without changing warning filters. B07's existing bounded publication
profile admits 1.43 only for isolated development and CI, through 2026-10-04.
Authenticated wheel publication is not authenticated build provenance. B08's
existing guard blocks artifact creation, signing, publication and verification
for the whole graph while this admission remains. No production use is permitted.

## Public values and operations

| Interface | Meaning and invariant |
| --- | --- |
| `Currency` | Explicit supported USD/EUR/GBP/JPY/CHF/SGD/AUD/CAD/HKD/CNY unit; JPY quantum is 1 and other supported currency quanta are 0.01 |
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

Currencies are a deliberately bounded unit vocabulary. They do not reconcile an
ISO registry, currency lifecycle, cash-payment rounding rule, entitlement or venue.
Unsupported currencies and variants must be added with owned source, compatibility
and fixture evidence; raw strings or unknown values are rejected. An instrument
reference does not certify that instrument or grant its use in trading.

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

`adjust_business_day` uses the bounded C02 `SettlementCalendar` eligible-date set
for unadjusted, following, modified following, preceding and modified preceding.
Modified adjustments reverse direction when the primary result changes year or month.
It never guesses weekends or holidays. Missing primary/alternate dates or dates
outside coverage fail, including when a modified adjustment cannot establish the
primary result from the bounded snapshot. Unadjusted still checks coverage.

`settlement_date` first applies the explicit adjustment and then counts the
requested 0-366 eligible-day lag strictly after the adjusted anchor. Zero returns
the anchor; positive lags exclude it even when unadjusted leaves it ineligible.
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

Tests also cover currency/instrument/convention mixing, type coercion, immutable
values, non-finite/overflow/precision inputs, invalid native results, version and
native failures, calendar limits, settlement lags, unchecked C01/C02 model copies,
multi-year modified adjustments, and independence from Decimal
context and QuantLib's evaluation date across concurrent calls. A bounded local
performance check is diagnostic; it supplies no target latency/SLO certification.

A04 facts are no capital, shared-domain blast radius, shared-library materiality,
shared-sensitive native admission, compatibility-window reversibility, and
computational/economic relevance. Classification is R2 with QG01-QG14. Code Owner
and independent domain review are mandatory; Platform/SRE and Security assess the
native dependency and inherited B07 obligations. No independent approval exists.

Applicable gate definitions live in the
[quality-gate catalog](operations.md#quality-gate-catalog). Exact dependency,
classification, artifact and finding state remains in the machine-readable
admission and evidence records; current package state and finding IDs are rendered
in the [program status](../governance/program-status.md).

The [evidence example](../governance/evidence/examples/c03-r2-partial/manifest.toml)
is a hash-bound partial A05 fixture with an explicitly synthetic SHA, not approval
of uncommitted code. Its reports identify the actual implementation base and
executed local checks. Exact-commit protected evidence remains C03-F01/F02.
A separate `working-tree-inputs.json` artifact binds the changed implementation
inputs to their actual SHA-256 digests and base commit. The manifest also retains
hashes of the actual vulnerability scan, native observations and publication
verification results; none is an independent approval.

## Migration, rollout, rollback and runbook

This is an additive API with no existing consumer or persisted state to migrate.
The requested migration replaces every C03 dataclass with Pydantic and replaces
internal `dataclasses.replace` calls with validated `model_copy`. Pydantic is
already exactly pinned; only its direct Bazel dependency edges are added. Msgspec
is not introduced because C03 has no codec requirement or measured serialization
need. QuantLib remains exactly 1.43.
Rollout is repository-local full-lane validation, golden replay and consumer impact
review. No runtime, root command, CI lane, A06 inventory or A08 readiness update is
owned here. Build/source registrations cover only C03 and its required inputs.

Rollback reverts source, tests, dependency declarations/locks/admission, build
registrations and documentation together, preserving diagnostic evidence. A later
consumer migration must first account for dimensions, precision, convention
revisions and replay obligations. No deployment or activation is introduced.

On `UnitError` or `ConventionError`, stop the affected calculation. Retain safe
instrument/currency dimensions, explicit context and source/calendar revisions,
operation, adapter version and exception cause. Reconcile inputs with the domain
owner, issue corrected versioned inputs and replay goldens and consumer tests.
Never substitute a unit, infer a calendar, suppress a warning, mutate global
Settings or round implicitly to recover. Admission expiry or evidence mismatch
stops validation; Platform must renew with actual review or replace/remove the
dependency. It does not renew automatically or permit artifact release.

## Governance references

Finding detail remains in the retained
[C03 evidence manifest](../governance/evidence/examples/c03-r2-partial/manifest.toml)
and [dependency admission](dependency-admission.toml), including `B07-DEP-001`.
The [development workflow](../governance/workflow.md) owns daily evidence and the
[program status](../governance/program-status.md) owns readiness. C03 grants no
release, deployment, activation, credential, market or capital authority.
