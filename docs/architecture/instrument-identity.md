# Canonical Instrument Identity and Temporal Symbology

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
network, filesystem, database, clock, or configuration dependency. Its strict
immutable Pydantic construction boundary is governed by
the [current architecture decision](README.md#current-architecture-decisions).

## Public interface

The owned library is `reference_data.instruments`:

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

The C01 current projection is not a knowledge-time query. A future data layer may
define event, receipt, ingestion, knowledge, valid-time, sequence, and bitemporal
selection.
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

## Migration, rollout, rollback, monitoring, and runbook

Financial-unit dimensions already consume `InstrumentId`. There is no external
strategy/service or persisted state to migrate. C01 and C02 now share a private
redacted Pydantic error formatter, with the owned
exception type supplied explicitly. Field ordering, locations, owned causes and
exception chaining are preserved. Domain bases remain separate, and C01/C02
framework `model_copy` operations remain trusted and unchecked; C03 reconstructs
and validates its copies. UUID parsing and identifier checksum/namespace mechanics
have private class owners; concrete IDs and namespace-broad queries remain distinct.

The internal model implementation moved
from frozen dataclasses to strict immutable Pydantic models without changing the
public constructors or domain exceptions. Downstream adapters migrate by converting
provider identifiers into `ExternalIdentifier`, resolving at an explicit valid
time, and carrying only `InstrumentId` into canonical consumers. A future
cross-process boundary can define versioned schemas, compatibility versions,
generated clients, and migration windows.

Rollout uses focused tests, compatibility replay of the golden fixture, and
consumer impact analysis. It deploys and activates nothing. Rollback is a
reviewed revert of the library, tests, dependency declarations, and documentation
together. Retain the fixture and any failed mapping records needed to explain
affected results.

If a consumer sees unknown or ambiguous identity, it must stop that affected
resolution path and retain the error context; it must not guess a namespace or
fall back to a ticker. Inspect the returned/history mapping IDs, source and source
revision, append a corrected assertion that supersedes the bad record, rerun the
golden/property/consumer replay, and only then publish a new catalog snapshot.
There is no production service, dashboard, page, alert route, or operator control
introduced by C01.
