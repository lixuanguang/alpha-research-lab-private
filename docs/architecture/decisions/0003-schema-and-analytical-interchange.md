# ADR 0003: Schema and analytical interchange

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | A02 |
| Status | Proposed |
| Decision owner | Platform |
| Decision date | 2026-08-25 |
| Review date | 2026-11-25 |
| Supersedes | None |
| Approval evidence | Pending; A02-F01 |

## Context

The thin waist needs cross-language contracts for events and control messages plus
efficient analytical interchange for point-in-time datasets. Language-native
objects and storage-vendor structures are not stable shared contracts.

## Decision drivers

- Versioned compatibility, deterministic generation, explicit units/time, unknown
  field behavior, broad language support, and columnar analytical efficiency.
- Separation between wire/domain contracts and bulk analytical representation.

## Considered alternatives

- **JSON or language objects as canonical contracts:** accessible but weaker for
  typed compatibility and generated consumers.
- **One columnar format for every boundary:** efficient for analytics but not a
  complete control/event API contract.
- **Protobuf plus Arrow/Parquet:** separates versioned service/event schemas from
  analytical memory and persisted interchange.

## Decision

Use Protobuf as the default versioned cross-process schema technology and
Arrow/Parquet for governed analytical interchange. Translate generated types into
domain types at boundaries. C01-C08 own the actual canonical schemas, registry,
compatibility policy, fixtures, and migration windows.

## Consequences

Consumers gain typed generation and shared compatibility evidence, while schema
governance and code generation become mandatory build inputs. This ADR does not
define a schema prematurely or permit lossy conversion between representations.

## Migration and rollout

Wave C introduces schemas additively, generates clients reproducibly, and applies
expand-migrate-contract with dual-read/write where required. Current bootstrap
objects remain non-canonical until migrated and covered by conformance fixtures.

## Reversal plan

A replacement format requires a compatibility bridge, dual fixtures and readers,
consumer inventory, digest-stable migration, and verified rollback before the old
representation is deprecated.

## Review and evidence

Review when C08 supplies compatibility matrices, generated-client digests, replay
fixtures, and measured serialization evidence. Domain, data, and platform owners
must challenge unsafe unknown-field or time/unit behavior.
