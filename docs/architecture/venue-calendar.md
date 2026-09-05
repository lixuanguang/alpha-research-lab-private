# Venue, Session, Calendar, and Market-Status Contracts

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | C02 |
| Operating track | Solo bootstrap |
| Implementation status | Complete |
| Institutional status | Partial |
| Accountable owner role | Domain Architecture |
| Dependencies | C01, provisionally satisfied with open findings |
| Change risk | R2 shared-domain and shared-library contract |
| Applicable gates | QG01-QG06, QG09-QG14 |
| Evidence retention | Shared-contract compatibility lifecycle |

## Objective and delivery boundary

C02 establishes the owned strict immutable Pydantic venue, calendar, session,
market-status, settlement-date, and timezone contract. It distinguishes stable
repository venue identity from exact
ISO 10383 MIC-shaped values, preserves both segment and operating MICs, and makes
every schedule lookup depend on an explicit bounded calendar snapshot rather than
the host clock, host timezone, a provider SDK, or a live service.

The roadmap-required `exchange_calendars==4.13.2` dependency is isolated behind
`ExchangeCalendarsAdapter` under [ADR 0011](decisions/0011-versioned-venue-calendar-adapter.md).
It supplies base session labels, opens, breaks, closes, early closes, holidays by
session absence, and IANA timezone metadata. Owned values represent attributed
closures, auctions, halts, limit states, settlement dates, and overrides because
the source library is not authoritative for those complete venue states. No
third-party dataframe, timestamp, exception, registry, or calendar object enters
the public domain interface.

## Public interface

The owned library is `alpha_research.venue_calendar`:

| Value or operation | Contract |
| --- | --- |
| `VenueId` | Non-nil canonical UUID that is independent of a MIC or source name |
| `MarketIdentifierCode` | Exact four-character uppercase ASCII MIC-shaped value; no normalization or completeness claim |
| `Venue` | Stable ID, segment MIC, operating MIC, name, and explicit IANA timezone |
| `CalendarSourceVersion` | Calendar version plus exact base adapter/source revision and optional override source/revision |
| `TradingSession` | One session label and UTC half-open open/close interval with optional break and auction windows |
| `CalendarClosure` | Named holiday or ad-hoc non-session date with source and revision |
| `SessionOverride` | Exact add, replace, or remove action with stable ID, source revision, and reason |
| `MarketInterruption` | Source-attributed half-open halt interval |
| `PriceLimitWindow` | Source-attributed half-open limit-up, limit-down, or locked interval |
| `SettlementCalendar` | Bounded, versioned, explicit eligible-date set; no settlement convention |
| `VenueCalendarSnapshot.market_state_at` | Resolve closed, auction, continuous, break, or halted state plus independent limit state at an aware UTC instant |
| `ExchangeCalendarsAdapter.build_snapshot` | Translate one explicit inclusive label range using the exact admitted dependency and versioned overrides |

The only admitted authorities are `reference_only` and `synthetic_fixture`.
There is deliberately no `live` authority value. A snapshot may be useful input
to later replay or serving systems, but C02 alone cannot certify or activate it.

## Identity, time, and state invariants

- Venue identity is opaque. A MIC is an external standard identifier and may
  change or represent a segment under an operating MIC; neither becomes the
  repository identity.
- Venue timezone is a validated IANA name. Canonical opens, closes, breaks,
  auctions, halts, and limit windows are aware UTC datetimes. Conversion to venue
  local time names the venue timezone explicitly and never reads host-local time.
- A session label is a business `date`, not midnight in an inferred timezone. A
  session may open on the previous UTC or local date. Session membership is the
  half-open interval `[opens_at, closes_at)`.
- A break must lie strictly inside its session and is half-open. Auction windows
  are ordered, non-overlapping, and contained in the session. Repeated auction
  kinds are permitted, for example multiple reopening auctions after halts.
- Snapshot sessions are uniquely labeled, ordered by opening instant,
  non-overlapping, and inside declared label coverage. Named closures are ordered,
  unique, inside coverage, and cannot also be session labels.
- Halts and non-normal price-limit windows are source attributed, uniquely
  identified, ordered, non-overlapping within their own collection, and contained
  by exactly one session. A halt takes schedule-state precedence over an auction,
  break, or continuous phase. A price-limit state remains a separate fact.
- At an exact auction end, break end, halt end, or session close, the successor
  half-open state applies. Unknown session labels and invalid/overlapping state
  raise owned exceptions; no nearest-session or favorable-state fallback exists.
- Closed-state queries are covered only on the declared venue-local calendar
  dates. Recorded overnight sessions remain queryable across local midnight;
  other out-of-coverage instants raise `CalendarCoverageError`, not `CLOSED`.
- Settlement dates are an explicit bounded set. C02 can answer membership and the
  first available date on or after a candidate. C03 owns day-count, lag, business-
  day adjustment, currency, and other settlement conventions.

Market state is not an order-permission decision. A later venue adapter and the
independent risk/OMS path must combine certified live state, instrument support,
limits, entitlements, activation, and account authority. A C02 `CONTINUOUS` result
therefore never authorizes an order.

## Versioned source and override adapter

Every adapter call supplies explicit `start` and `end` label dates and a
`CalendarSourceVersion`. The adapter verifies the installed distribution and
claimed base-source revision are exactly 4.13.2, requests left-closed source minutes,
verifies the returned source
name and timezone, converts source values to owned UTC datetimes, and discards the
third-party objects. A one-label request gets one constructor-context day. If the
source cannot construct a closure-only schedule, the adapter retries with at most
31 extra label days and filters all context back out. Unsupported source context
still fails explicitly; no session or live status is inferred.

`SessionOverride` supports three fail-closed operations:

- `ADD` requires the label to be absent and a complete replacement session.
- `REPLACE` requires the label to exist and a complete replacement session.
- `REMOVE` requires the label to exist and forbids a replacement.

Override IDs and target labels are unique within a snapshot. Any override requires
matching override source and revision on the calendar version; applied records
remain in the snapshot and must agree with its resulting sessions. A later correction emits
a new immutable snapshot and calendar version; it does not mutate a retained
snapshot. D04 will own persistent temporal master data, priority rules, full
valid/knowledge history, impact reports, and publication.

The NumPy transitive dependency is constrained to 2.4.6 because 2.5.2 causes the
pinned XHKG source calendar to emit a deprecation warning under the repository's
warnings-as-errors policy. This is an explicit compatibility constraint, not an
ambient environment workaround. The complete source, wheel, hash, license, and
native-artifact graph remains under B07 admission.

## Golden and property evidence

The retained, explicitly synthetic
[`c02_calendars.json`](../../tests/golden/venue_calendar/c02_calendars.json)
fixture pins exchange-calendars 4.13.2 outputs for:

- XNYS before and after both 2024 US daylight-saving transitions;
- XLON before and after both 2024 UK daylight-saving transitions;
- the XNYS Thanksgiving holiday and following early close;
- an XHKG intraday break and a one-label bounded adapter request;
- synthetic opening auction, halt, overlapping limit-up, and settlement-date
  examples that claim no live authority.

Focused tests exercise exact adapter reproduction under different host timezones,
all market-state boundaries, override actions, closure/session exclusion,
settlement bounds, invalid MIC/UUID/timezone/time/interval state, unknown source
calendars, timezone mismatch, unversioned overrides, and incompatible library
versions. Two derandomized 50-example Hypothesis properties cover state projection
and explicit timezone round trips. Explicit gap/fold tests retain distinct UTC
instants across repeated local times. Strict Pydantic tests reject raw nested
mappings, extra fields, coercion, mutation, and invalid nested instances.

## Risk, quality gates, and reviewers

The authoritative A04 facts are: no capital at risk, shared-domain blast radius,
shared-library materiality, no security privilege, compatibility-window
reversibility, and no computational, economic/risk, model, or trading conditional
trigger. A04 therefore returns R2 with merged-result, compatibility-replay, and
impact-analysis rollout modes.

| Gate | Repository-local evidence |
| --- | --- |
| QG01 | Strict frozen Pydantic validation, Ruff format/lint, strict mypy, warnings-as-errors pytest, suppression expiry, and Bandit cover the library and tests |
| QG02 | Exact exchange-calendars/NumPy constraints, uv/Bazel locks, bounded source ranges, deterministic fixtures, and derandomized properties |
| QG03 | Success, boundary, adapter, override, timezone, closure, settlement, invalid-input, and error paths are tested |
| QG04 | UTC, half-open interval, ordering, overlap, identity, timezone, and deterministic projection invariants are tested |
| QG05 | Version/revision attribution, holiday/half-day/DST/break fixtures, closures, and correction-by-new-snapshot semantics are retained |
| QG06 | No feature, model, research conclusion, trial, or promotion decision is introduced |
| QG09 | Installed package, focused pytest/Bazel, source topology, evidence profile, and full graph consume the same owned API and fixture |
| QG10 | Ten thousand market-state lookups remain within the recorded one-second local diagnostic budget |
| QG11 | Unknown, incompatible, naive, non-UTC, overlapping, unattributed, or out-of-range state fails closed without partial mutation |
| QG12 | The exact dependency graph, sources, hashes, licenses, wheels/native artifacts, no-runtime-install rule, static analysis, and secrets checks remain blocking |
| QG13 | Contract, ADR, API, fixture, ownership, limitations, migration, rollback, runbook, findings, and successor are documented |
| QG14 | Typed failures and returned version/state attribution are repository-local signals; no deployed SLO, alert, or dashboard is claimed |

Institutional review requires the Code Owner plus an independent data or domain
reviewer. Platform review is also required for the new dependency and native-wheel
surface. The solo maintainer cannot satisfy those roles independently.

The diagnostic workload uses the retained 185-session XNYS range, with lookups at
session opens and closes. Session selection uses binary search over the validated
opening-order invariant; no mutable index or external cache is introduced.

## Migration, rollout, rollback, monitoring, and runbook

C02 is an additive Python API and build target. There is no existing calendar
consumer, serialized schema, database, service, order state, or deployment to
migrate. Consumers later migrate by constructing a stable `Venue`, selecting an
explicit calendar version and bounded range, applying only source-attributed
overrides, and carrying the complete snapshot/version identity with results.

Rollout is repository-local merged-result testing, golden compatibility replay,
dependency admission, and consumer impact analysis. It deploys and activates
nothing. Rollback is a reviewed revert of the library, exact dependency and lock
edges, targets, tests, architecture/ADR, status, and evidence together. Retain the
golden fixture and any failing source revision or override record needed to
explain affected results.

If adapter construction, a session lookup, or state validation fails, stop the
affected calendar path. Retain the venue, calendar version, bounded range, source
revision, override IDs, and safe exception context. Reconcile against an approved
calendar owner, issue a new versioned base/override record, rerun golden and
consumer replay, and only then publish a replacement snapshot. Never guess a
timezone, select a nearby session, suppress an unknown halt/limit, or treat the
library as live authority. C02 adds no production monitor, page, alert route, or
operator control.

## Open findings

| Finding | Owner | Unavailable evidence | Closure condition |
| --- | --- | --- | --- |
| C02-F01 | Domain Architecture | Commit-bound Code Owner, independent data/domain review, and independent Platform dependency review are unavailable during solo bootstrap | Named reviewers resolve findings and approve the exact API, time/state semantics, dependency boundary, fixtures, rollback, and evidence commit |
| C02-F02 | Platform/CI | Protected merged-result Linux execution, retained exact-commit fixture replay, and Darwin/Linux native-wheel comparison are unavailable locally | Protected CI installs the exact admitted graph, runs affected/full tests and the retained fixture on the reviewed merged result, and retains pass and blocking-mutation evidence |
| C02-F03 | Data Platform | Approved MIC registry reconciliation, authoritative venue calendars, settlement calendars, halt/limit feeds, and independent target-environment comparison are unavailable in this repository | Accountable data/venue owners reconcile representative target venues across DST, holidays, half-days, breaks, exceptional closures, auctions, halts, limits, and settlement dates and retain non-sensitive evidence |

These findings are not approvals or waivers. C02 implementation is complete;
institutional status remains `partial` until all close.
The admitted dependency graph also retains B07-F03's Security-owned qualified
license-obligation and independent vulnerability/Scorecard review; local license
dispositions and scanner results do not close that inherited finding.

## Explicit non-goals and successor

C02 does not implement C03 typed units, currencies, prices, quantities, day-count
or settlement conventions; C04 knowledge-time/bitemporal selection; C05 market or
lifecycle event schemas; D04 persistent master data, source priority, correction
history, impact reporting, or online serving; F04 market simulation; H04 live
venue adapters; or L01-L05 asset certification.

It adds no provider connection, live calendar authority, entitlement, credential,
deployment, activation, executable order permission, venue/account/instrument
expansion, capital, or expanded risk authority. The next documented selector is
typed units, currencies, prices, quantities, and conventions (`C03`).

C02 does not own A08 readiness reporting. Governance migration step 3 reconciles
this demonstrated implementation in the program registry; the A08 validator still
derives the queue. C03 is also reconciled, so the current technical successor is
C04. C02 adds no separate root command, CI lane, or resource-inventory entry.
Existing build and source-ownership registrations cover only the C02 library,
tests, and evidence inputs.
