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
network, filesystem, database, clock, or configuration dependency. Its strict
immutable Pydantic construction boundary is governed by
[ADR 0010](decisions/0010-pydantic-instrument-identity-models.md).

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

## Evidence and governance

The C01 evidence manifest retains exact classification, gate and artifact state.
Gate definitions live in the [quality-gate catalog](operations.md#quality-gate-catalog);
current package state and finding IDs are rendered in the
[program status](../governance/program-status.md).

## Migration, rollout, rollback, monitoring, and runbook

This remains an additive Python API and build target with no existing canonical
consumer or serialized state to migrate. The internal model implementation moved
from frozen dataclasses to strict immutable Pydantic models without changing the
public constructors or domain exceptions. Downstream adapters migrate by converting
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

## Governance references

Finding detail remains in the retained
[C01 evidence manifest](../governance/evidence/examples/c01-r2-partial/manifest.toml).
The [development workflow](../governance/workflow.md) owns daily evidence. C01
defines identity behavior only and grants no provider, credential, deployment,
activation, market or capital authority.
