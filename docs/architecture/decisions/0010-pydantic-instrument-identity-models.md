# ADR 0010: Pydantic instrument-identity models

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | A02 |
| Status | Proposed |
| Decision owner | Domain Architecture |
| Decision date | 2026-09-03 |
| Review date | 2026-12-02 |
| Supersedes | None |
| Approval evidence | Pending; A02-F01 and C01-F01 |

## Context

The C01 canonical instrument-identity contract used frozen standard-library
dataclasses with validation distributed across `__post_init__` methods. These
objects accept identifiers and mapping assertions at adapter boundaries, enforce
strict runtime types, and form an immutable graph whose invalid construction must
fail closed. The repository has selected strict Pydantic models for equivalent
validation boundaries, but ADR 0008 deliberately required a separate decision
before extending that dependency into a domain library.

## Decision drivers

- Eliminate the remaining duplicated dataclass validation pattern.
- Reject coercion, unknown fields, invalid defaults, and invalid nested instances
  consistently at every direct and structured construction boundary.
- Preserve positional and keyword constructors, hashing, equality, immutability,
  canonical string forms, domain exceptions, and catalog behavior.
- Keep graph-wide identity, interval, ambiguity, and correction checks inside the
  C01 domain model rather than moving them into generic infrastructure.
- Avoid adding a second modeling framework without a measured serialization need.

## Considered alternatives

- **Retain frozen dataclasses:** remains valid for ordinary domain carriers, but
  these records are validation boundaries and repeat strict type enforcement in
  every `__post_init__` method.
- **Adopt msgspec structs:** would provide efficient typed serialization, but C01
  has no transport codec, stored wire format, or measured serialization hot path;
  introducing it would create a second general validation framework.
- **Adopt attrs:** is suitable for ordinary domain objects, but would overlap with
  the repository's established Pydantic validation boundary without improving the
  untrusted construction contract.
- **Use strict Pydantic models:** reuses the admitted dependency and uniform strict,
  frozen, extra-forbid, default-validation, and nested-revalidation behavior.

## Decision

Use Pydantic v2 `BaseModel` for `InstrumentId`, `MappingId`,
`InstrumentIdentity`, `ExternalIdentifier`, `IdentifierQuery`,
`SymbologyMapping`, and `SymbologyCatalog`. A package-local base owns strict,
frozen, extra-forbid, default-validation, input-hiding, and nested-instance
revalidation settings. Field and model validators retain the existing canonical
UUID, scheme, namespace, checksum, UTC interval, attribution, correction, and
catalog graph invariants.

The public constructors retain their current positional and keyword signatures.
Direct-construction validation continues to raise
`InstrumentIdentityValidationError` with safe domain messages and a preserved
Pydantic cause. Structured `model_validate` callers receive Pydantic's standard
`ValidationError`, enabling strict adapter validation while retaining exact nested
model types.

Pydantic becomes an exact direct dependency of `alpha-research-lab` and the C01
Bazel target. Msgspec remains unadopted until a C05/C08 transport boundary or
benchmark demonstrates a throughput requirement. This decision is limited to
C01 and does not authorize validation frameworks throughout the economic or
trading kernel.

## Consequences

All C01 model construction shares one validation configuration and supports
strict structured parsing. The models remain immutable and value-comparable, and
their existing hash-based catalog indexes continue to work. Pydantic increases
construction cost and the domain target is no longer standard-library-only, while
steady-state catalog lookups retain their existing algorithms and data shapes.

Consumers gain `model_validate` and `model_dump` surfaces. Those surfaces are not
a versioned cross-process schema; C05/C08 still own transport compatibility and
schema registration. Pydantic errors remain behind the established domain error
for existing constructor calls.

## Migration and rollout

Migrate all seven dataclasses together so nested identity and mapping graphs do
not mix modeling systems. Preserve constructor signatures, factories, string
forms, methods, and the retained golden fixture. Add direct tests for Pydantic
inheritance, strict structured input, unknown-field rejection, immutability, and
the existing domain-error messages.

Update the root distribution, Bazel dependency edge, uv and artifact lock
identities, repository documentation, and architecture log in the same change.
Roll out only through repository-local tests, deterministic property replay,
packaging smoke checks, and the existing 10,000-resolution workload budget. No
data, deployment, activation, or stored-schema migration is introduced.

## Reversal plan

If constructor compatibility, error translation, hashing, catalog correctness,
packaging, or workload budgets regress, revert the seven models, dependency edge,
lock identities, tests, and documentation together to the prior frozen-dataclass
implementation. No persisted C01 wire representation requires conversion. Retain
the failing fixture or property seed as rollback evidence.

## Review and evidence

Required review is the Domain Architecture Code Owner plus an independent data or
domain reviewer, with Platform review of dependency and packaging changes.
Repository-local evidence includes Ruff, strict mypy, warning-as-error pytest,
Bandit, Bazel tests, architecture and dependency governance, package builds, the
golden fixture, property tests, and the 10,000-resolution workload budget.

Approval is unavailable in the solo-authored workspace. A02-F01 and C01-F01
remain open; this record stays `Proposed` until named reviewers approve the exact
change. Re-review on any Pydantic upgrade, expansion beyond C01, new wire-format
use, constructor or error compatibility regression, or material performance
change.
