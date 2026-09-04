# ADR 0011: Versioned venue-calendar adapter

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | A02 |
| Status | Proposed |
| Decision owner | Domain Architecture |
| Decision date | 2026-09-04 |
| Review date | 2026-12-03 |
| Supersedes | None |
| Approval evidence | Pending; A02-F01 and C02-F01 |

## Context

C02 must define owned venue, MIC, session, auction, holiday, half-day, halt,
limit-state, settlement-calendar, and timezone semantics. The roadmap names
`exchange_calendars` 4.13.2 but requires a versioned source/override adapter and
prohibits treating the library as live authority. Calendar behavior is a canonical
time contract, so the architecture governance process requires an ADR before the
dependency and semantics become a shared foundation.

## Decision drivers

- Make all time behavior independent of the host timezone, host clock, import
  order, and mutable workstation state.
- Retain explicit source, library, calendar, and override revisions so calendar
  changes produce new snapshots rather than silent historical drift.
- Keep pandas and exchange-calendars types, registries, and exceptions outside the
  owned domain API.
- Represent auctions, halts, limit states, closures, and settlement dates without
  implying the base schedule library supplies complete or live venue state.
- Preserve deterministic bounded fixtures across DST, holidays, half-days, and
  intraday breaks while failing closed on incompatible dependencies.

## Considered alternatives

- **Use exchange-calendars objects directly:** reduces adapter code but exposes
  unowned mutable registries, pandas types, source exceptions, default date bounds,
  and incomplete authority semantics throughout downstream packages.
- **Implement all exchange schedules in repository code:** maximizes ownership but
  duplicates a maintained source, creates a large unaudited rule set, and still
  requires independent authoritative reconciliation.
- **Use only hand-written fixture schedules:** is deterministic but cannot provide
  a coherent reusable base across many venues or surface upstream calendar changes.
- **Use an exact pinned library behind an owned versioned adapter:** reuses the
  roadmap choice while keeping canonical identity, state, failure, attribution,
  and override behavior under repository control.

## Decision

Use `exchange-calendars==4.13.2` only inside
`alpha_research.venue_calendar.ExchangeCalendarsAdapter`. Every call requires
explicit inclusive label bounds, a stable `Venue`, and a `CalendarSourceVersion`.
The adapter verifies the installed version and claimed base revision, requests
`side="left"`, verifies source name and IANA timezone, translates schedule values to standard-library UTC
datetimes, and returns strict immutable repository Pydantic models. No unowned
calendar value or exception crosses the adapter boundary.

Use half-open `[start, end)` semantics for sessions, breaks, auctions, halts, and
limit windows. Keep session labels as dates. Halt state takes precedence over the
scheduled phase, while price-limit state remains independent. Exact boundaries
select the successor state. Invalid, overlapping, unattributed, unknown, or
incompatible state fails closed.

Allow repeated non-overlapping auction kinds. Closure-only adapter requests use
at most 31 extra source-context days when the dependency cannot construct an empty
schedule, then discard those context sessions. Queries outside snapshot coverage
fail explicitly. Binary search selects sessions from the validated opening order.

The base library supplies schedule facts only. Named closures, auction windows,
halts, price-limit windows, settlement dates, and add/replace/remove overrides are
owned values with explicit source revisions. The adapter never performs network
access or selects default date bounds. The public authority enum intentionally has
no live value.

Use strict, frozen Pydantic models with forbidden extra fields, strict input types,
default validation, and nested-instance revalidation for the C02 construction
boundary. This follows C01's already admitted validation pattern and adds no
dependency. It does not make these in-process values wire schemas; C05/C08 will
own versioned cross-process schemas and compatibility.

Constrain NumPy to exactly 2.4.6 in uv resolution. The unconstrained 2.5.2 release
causes the pinned XHKG calendar path to emit a deprecation warning, which fails the
repository's warnings-as-errors gate. B07 records the complete resulting direct,
transitive, license, hash, platform, wheel, and native-artifact surface.

## Consequences

Downstream code receives narrow stable values with deterministic UTC and failure
semantics and can retain calendar/source identity with outputs. Source calendar or
override changes require an explicit new version and fixture replay. The adapter
adds pandas/NumPy and calendar-data transitive dependencies, including native
wheels, and its source schedule coverage is only as complete as the exact pinned
library. Target use still requires authoritative independent reconciliation.

The model does not implement bitemporal knowledge history, source priority,
persistence, event transport, or live permissioning. A `CONTINUOUS` state is a
calendar fact, never authorization to trade.

## Migration and rollout

Add the new library, exact dependency/constraint, Bazel targets, topology entries,
synthetic fixture, contract/property/failure tests, documentation, package state,
and SHA-bound evidence together. There is no existing consumer, stored schedule,
wire schema, service, or deployment to migrate.

Roll out only through repository-local merged-result testing, retained fixture
compatibility replay, dependency admission, and impact analysis. No production
source, provider session, credential, deployment, or activation is introduced.

## Reversal plan

If dependency admission, cross-platform wheel installation, source compatibility,
timezone/DST behavior, half-open status boundaries, packaging, or performance
regresses, revert the C02 library, dependency and constraint, locks, targets,
fixtures, status, documentation, and evidence together. Retain the failed fixture,
source revision, and override record as recovery evidence. A replacement must
preserve the same owned contract and cannot silently fall back to host-local time
or a live provider.

## Review and evidence

Required review is the Domain Architecture Code Owner plus an independent data or
domain reviewer, with Platform review of the dependency/native-wheel surface.
Repository-local evidence includes strict static checks, warnings-as-errors pytest,
Bazel, exact lock/admission validation, host-timezone independence, DST/holiday/
half-day/break fixtures, market-state and override failures, property tests,
packaging smoke, and the 10,000-lookup diagnostic budget.

Approval and target data are unavailable in the solo-authored workspace. A02-F01
and C02-F01 through C02-F03 remain open; this record stays `Proposed` until named
reviewers approve the exact change. Re-review on any calendar, NumPy, pandas, or
timezone-data upgrade; new venue/asset use; source/override semantic change; live
consumer proposal; or target reconciliation failure.
