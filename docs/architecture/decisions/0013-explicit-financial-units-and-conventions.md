# ADR 0013: Explicit financial units and conventions

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | A02 |
| Status | Proposed |
| Decision owner | Domain Architecture |
| Decision date | 2026-09-04 |
| Review date | 2026-10-04 |
| Supersedes | None |
| Approval evidence | Pending; C03-F01 |

## Context

C03 requires owned money, FX, prices, quantities, yields, rates, volatility,
duration, multipliers, ticks and lots, with explicit rounding and conventions.
C01 supplies instrument identity and C02 bounded settlement calendars. Neither
owns financial dimensional arithmetic. Ambient Decimal precision or a native
library's process-wide evaluation date would make replay depend on the caller.

The maintainer explicitly selected QuantLib 1.43 instead of the roadmap's 1.40
survey baseline. On Darwin arm64 and CPython 3.12.14, 1.40 segfaulted when imported
with warnings treated as errors. Version 1.43 passes the unchanged policy.
Its publisher is now the QuantLib-SWIG release-tag workflow. Its wheel-only
admission uses the existing [ADR 0012](0012-wheel-only-source-admission.md)
bounded bootstrap profile; publication signatures are not build provenance.

## Decision drivers

- Reject unit, instrument, currency and convention mixing at construction or use.
- Keep exact monetary arithmetic independent of ambient numeric settings.
- Preserve explicit negative prices and signed quantities without order semantics.
- Reuse named native day counters without importing native state into the API.
- Retain exact dependency, source, publisher, native-component and fixture evidence.

## Considered alternatives

- Untyped Decimal or floats cannot prevent currency, instrument or unit mixing;
  implicit float/Decimal rounding is rejected.
- A general symbolic unit framework adds a dependency and broader algebra than
  this package needs; dimensioned owned values suffice for the actual operations.
- QuantLib-owned money, currencies, calendars or Settings would leak library
  identity and ambient state. Restrict its use to explicit-date day counters.
- Reimplementing every day count duplicates the roadmap's maintained candidate.
  Hand-calculated fixtures instead challenge the narrow native adapter.
- Pydantic reuses the admitted C01/C02 validation framework and exact dependency.
  Msgspec would add another framework without a measured codec requirement in C03.

## Decision

Use strict frozen Pydantic 2.13.5 `BaseModel` values, as explicitly requested by
the maintainer. Migrate all 16 C03 dataclasses, including the private numeric base
and the convention result, together. A package-local base forbids extra fields,
validates defaults, hides input values in errors and always revalidates nested
instances. Before validators retain exact Decimal and nested-model input types.
Reuse C01 `InstrumentId` and C02 `SettlementCalendar` through declared dependency
edges. This is the C03-specific validation-framework exception; it grants no
broader economic-kernel adoption. Wire serialization remains C05/C08.

Keep keyword construction, concrete-type equality, hashing and owned constructor
errors (`UnitError`, or `ConventionError` for convention results). Structured
`model_validate` reports Pydantic `ValidationError`. Override `model_copy` to
reconstruct and validate updates, including nested values; arithmetic uses that
validated path. Framework `model_construct` and explicit calls to unchecked base
primitives are outside the supported construction contract. Raw nested mappings
must be translated into owned model instances before construction.

Require Decimal construction, a 1e-18 grid and magnitude below 1e18. Use exact
rational intermediate arithmetic. Addition/subtraction requires the same type
and every dimension. Multiplication requires explicit matching price/quantity or
multiplier operations. FX conversion names its direction and rounds exactly once
to the target currency's minor unit. A result outside precision or magnitude
bounds fails rather than silently rounding. Round ticks/lots by arbitrary quantum,
with explicit floor, ceiling, toward-zero or nearest ties-to-even semantics.

Use exactly QuantLib 1.43 for five explicitly named day counters under an explicit
`EvaluationContext`; retain context, dates, day count and adapter version with the
result. Neither read nor mutate Settings, fixings, curves, native calendars or
market objects. Round native year fractions to 1e-15 years; retain scale-specific
absolute and relative tolerances. Business-day adjustments and bounded T+n
settlement dates consume the C02 eligible-date set directly.

## Consequences

Unknown or mismatched units, convention variants, versions and coverage fail
closed. The native double boundary is confined to elapsed year fractions;
monetary arithmetic remains exact until explicitly requested grid rounding.
Supported currency enums are a bounded unit vocabulary, not an ISO registry or
market entitlement. Rate/yield metadata does not calculate accrual or valuation.

QuantLib 1.43 adds a native dependency with 10 locked ABI3 wheels. The bootstrap
admission expires 2026-10-04 and keeps B07-DEP-001 open. Darwin embeds the native
library; Linux bundles an additional QuantLib shared library. Source-to-wheel and
complete build-input binding remain unverified. B08 denies creation, signing,
publication and consumer verification for the entire graph. No release exemption,
credentials, source-policy relaxation or workflow permission is introduced.

## Migration and rollout

Add C03 library/test targets, exact lock and admission, goldens, documentation and
evidence together. There is no existing financial-unit consumer, persisted schema,
service or database to migrate. Rollout is local full-lane validation, compatible
fixture replay and consumer impact review. Future consumers must carry dimensions,
convention revisions and explicit contexts rather than untyped numeric values.
Internal replacement calls use validated `model_copy(update=...)`; mutation now
raises Pydantic `ValidationError`. No dependency version or lock changes are needed
for this migration because Pydantic is already admitted. The library and test
Bazel targets declare it directly. Replay goldens, nested/copy validation, hashing,
strict typing and the unchanged 10,000-rounding workload budget before completion.

## Reversal plan

Revert C03 source, tests, targets, dependencies/locks, admission and documentation
as one change. Preserve source and failure evidence. Remove QuantLib or replace
its admission with complete authenticated build evidence before any attempt to
clear B08's release block; removing the bootstrap record alone cannot do so.

## Review and evidence

A04 classifies this shared financial and native dependency surface as R2 with
QG01-QG14, including economic/risk gates QG07/QG08. Review requires Code Owner,
independent domain, Platform/SRE and Security participation. The maintainer cannot
supply independent acceptance. See the [C03 contract](../financial-units.md) and
its evidence, limitations, findings and runbook.

Review areas are the dependency admission, value/dimension algebra, convention
adapter and tests/evidence. These are review areas within the single C03 unit,
not additional roadmap selectors. The complete behavior exceeds 400 lines because
its dimensional and precision invariants require the accompanying failure and
property tests; separating admission or adapter evidence would leave an unsafe
intermediate result. No public persistence or deployment migration is introduced.
