# Canonical Instrument Identity and Temporal Symbology

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | C01 |
| Operating track | Solo bootstrap |
| Package status | Partial |
| Accountable owner role | Domain Architecture |
| Dependencies | B01-B05, provisionally satisfied with open findings |
| Change risk | R2 shared-domain and shared-library contract |
| Applicable gates | QG01-QG06, QG09-QG14 |
| Evidence retention | Shared-contract compatibility lifecycle |

## Objective and delivery boundary

C01 establishes the first implemented canonical multi-asset domain contract. An
`InstrumentId` is an opaque repository-issued UUID whose identity never derives
from a ticker, venue symbol, vendor key, contract code, or chain address. The
contract distinguishes economic instrument, share class, listing, derivative
series, and listed contract identities and links each non-root identity to its
economic root.

External identifiers exist only as adapter-boundary values and temporal mapping
assertions. Provider-specific classes, normalization rules, SDK values, and
source-priority policy do not enter the canonical model. The package has no
network, filesystem, database, clock, configuration, or validation-framework
dependency.

## Public interface

The owned library is `alpha_research.instrument_identity`:

| Value or operation | Contract |
| --- | --- |
| `InstrumentId` | Non-nil canonical UUID; stable across alias changes |
| `InstrumentIdentity` | One `instrument_kind` plus its `economic_instrument_id` root |
| `ExternalIdentifier` | Exact scheme/value/namespace at an adapter boundary |
| `SymbologyMapping` | Immutable valid-time interval, `external_identifier`, source revision, and optional `supersedes_mapping_id` correction link |
| `SymbologyCatalog.resolve_identifier_at` | Resolve the current projection at one aware UTC valid-time instant |
| `get_identifier_mappings_for_instrument` | Reverse-map a canonical ID without choosing an alias implicitly |
| `get_mapping_history_for_identifier` | Retain original and correcting assertions for audit |

The admitted external schemes are vendor identifier, venue symbol, ISIN, CUSIP,
SEDOL, ticker, contract identifier, and chain identifier. Provider-local schemes
require a stable namespace. ISIN, CUSIP, and SEDOL values reject lower-case,
malformed, and checksum-invalid input and cannot be made provider-local by adding
a namespace. Other values are preserved exactly; the library does not trim,
case-fold, or rewrite a provider value.

## Identity and temporal invariants

- An economic instrument is its own economic root. Every share class, listing,
  derivative series, and contract references a registered economic root of the
  correct kind.
- Instrument and mapping IDs are unique, non-nil UUIDs. Mappings cannot reference
  an unregistered canonical identity.
- Mapping validity is an aware UTC half-open interval `[valid_from, valid_to)`.
  Adjacent mappings are valid; zero-length, reversed, naive, non-UTC, or
  overlapping current mappings fail construction.
- Reuse of one exact external identifier is represented by non-overlapping
  intervals. Resolution at the closing boundary selects the successor interval,
  never the expired mapping.
- A namespace-free query for a provider-local scheme is intentionally broad. If
  simultaneous venue or provider mappings match, resolution raises
  `AmbiguousIdentifierError`; it never selects by input order.
- Delisting closes the relevant mapping interval. A later listing has its own
  `InstrumentId`, may reuse the symbol only in a non-overlapping interval, and
  may retain the same economic root when that relationship is known.
- Corrections append a new mapping assertion that names the retained predecessor,
  preserves exact identifier and source, changes source revision, and records a
  reason. A predecessor may have only one successor and correction cycles fail.
  Only the unsuperseded leaf participates in the current catalog projection.
- Resolution and reverse lookup return the complete mapping assertion so the
  caller retains source, revision, interval, mapping ID, and correction lineage.

The C01 current projection is not a knowledge-time query. C04 will define event,
receipt, ingestion, knowledge, valid-time, sequence, and bitemporal selection.
Until then, a historical catalog snapshot must be identified outside this library;
C01 does not reconstruct what was known at an earlier decision time.

## Golden and property evidence

The retained, explicitly synthetic
[`c01_symbology.json`](../../tests/golden/instrument_identity/c01_symbology.json)
fixture is human-auditable and covers:

- symbol reuse by unrelated listings at an exact half-open boundary;
- a delisting gap followed by a distinct relisting linked to the same economic
  instrument;
- an ambiguous namespace-free ticker query;
- a vendor correction whose original assertion remains available in history;
- all canonical identity kinds and all admitted external identifier schemes.

The fixture is engineering evidence, not a live or authoritative instrument
master. Deterministic Hypothesis tests generate exact identifier round trips and
temporal reuse boundaries with 50 derandomized examples per property. Focused
tests also cover unknown values, invalid checksums and namespaces, bad UTC
intervals, duplicate and orphaned identities, overlap, missing correction
predecessors, changed correction keys, forks, and cycles.

## Risk, quality gates, and reviewers

The authoritative A04 facts are: no capital at risk, shared-domain blast radius,
shared-library materiality, no security privilege, compatibility-window
reversibility, and no computational, economic/risk, model, or trading conditional
trigger. A04 therefore returns R2 with merged-result, compatibility-replay, and
impact-analysis rollout modes.

| Gate | Repository-local evidence |
| --- | --- |
| QG01 | Ruff format/lint, strict mypy, warning-as-error pytest, and Bandit cover the library and tests |
| QG02 | Standard-library-only domain target, pinned Python/Bazel graph, deterministic fixtures and properties |
| QG03 | Success, reverse lookup, boundary, invalid-input, ambiguity, and correction failures are tested |
| QG04 | UUID, hierarchy, checksum, interval, overlap, lineage, and round-trip invariants have deterministic property tests |
| QG05 | Valid-time reuse, delist/relist, source revision, append-only correction lineage, and the golden fixture are retained |
| QG06 | No feature, model, trial, research conclusion, or promotion decision is introduced |
| QG09 | The installed package, focused pytest, Bazel target, source topology, and full-suite paths share the same contract |
| QG10 | Ten thousand resolutions of the retained fixture stay within the recorded one-second local diagnostic budget |
| QG11 | Unknown, ambiguous, overlapping, orphaned, forked, and cyclic states fail closed without partial mutation |
| QG12 | No dependency, credential, entitlement, network, runtime install, or provider SDK is added; security/static checks remain blocking |
| QG13 | Public API, examples, ownership, scope, limitations, migration, rollback, runbook, findings, and successor are documented |
| QG14 | Typed failures and returned attribution are the repository-local operational signal; no deployed SLO or alert is claimed |

Institutional review requires the Code Owner plus an independent data or domain
reviewer. The solo maintainer cannot satisfy the independent role.

## Migration, rollout, rollback, monitoring, and runbook

This is an additive Python API and build target with no existing canonical
consumer or serialized state to migrate. Downstream adapters migrate by converting
provider identifiers into `ExternalIdentifier`, resolving at an explicit valid
time, and carrying only `InstrumentId` into canonical consumers. C05/C08 will own
cross-process schemas, compatibility versions, generated clients, and formal
migration windows.

Rollout is repository-local only: merged-result tests, compatibility replay of the
golden fixture, and consumer impact analysis. It deploys and activates nothing.
Rollback-safe rollback is a reviewed revert of the library, target registration,
tests, documentation, status record, and evidence bundle together. Retain the
fixture and any failed mapping records needed to explain affected results.

If a consumer sees unknown or ambiguous identity, it must stop that affected
resolution path and retain the error context; it must not guess a namespace or
fall back to a ticker. Inspect the returned/history mapping IDs, source and source
revision, append a corrected assertion that supersedes the bad record, rerun the
golden/property/consumer replay, and only then publish a new catalog snapshot.
There is no production service, dashboard, page, alert route, or operator control
introduced by C01.

## Open findings

| Finding | Owner | Unavailable evidence | Closure condition |
| --- | --- | --- | --- |
| C01-F01 | Domain Architecture | Commit-bound Code Owner and independent data/domain review are unavailable during solo bootstrap | Named reviewers resolve findings and approve the exact public contract, invariants, fixtures, tests, and evidence commit |
| C01-F02 | Platform/CI | Protected merged-result Linux execution, retained compatibility replay, and exact-commit evidence are unavailable locally | Protected CI runs the complete affected/reverse-dependency graph and retained fixture replay on the reviewed merged result |
| C01-F03 | Data Platform | Entitled representative source records and an independent target-environment reconciliation are unavailable in this repository | A data owner reconciles approved representative vendor/venue/global identifiers, reuse, delist/relist, and correction cases and retains non-sensitive evidence |

These findings are not approvals or waivers. C01 remains `partial` until all close.

## Explicit non-goals and successor

C01 does not implement venue identities, MICs, calendars, sessions, market status,
or timezone policy (C02); units or conventions (C03); bitemporal knowledge-time
queries (C04); event/lifecycle schemas (C05); a schema registry (C08); or the D04
master-data service, source priority, persistence, or impact reports. It adds no
provider connection, entitlement, credential, deployment, activation, market
access, capital, or expanded risk authority.

The next documented selector is venue, session, calendar, and market-status
contracts (`C02`).
