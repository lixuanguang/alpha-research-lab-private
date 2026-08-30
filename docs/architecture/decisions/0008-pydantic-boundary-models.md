# ADR 0008: Pydantic boundary models

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | A02 |
| Status | Proposed |
| Decision owner | Platform |
| Decision date | 2026-08-30 |
| Review date | 2026-11-30 |
| Supersedes | None |
| Approval evidence | Pending; A02-F01 |

## Context

The bootstrap governance, configuration, registry, and serialization contracts
were represented by frozen standard-library dataclasses. Their parsers checked
external data before construction, but direct construction did not reject unknown
fields or incorrect runtime types, defaults were not validated, and validation
policy was repeated outside the model definitions. These records cross parsing,
public API, evidence, and CLI serialization boundaries; they are not economic or
trading-kernel domain objects.

Adopting Pydantic repository-wide changes the direct runtime dependency policy and
the object-construction contract. The Python standards therefore require an
explicit boundary-specific architectural decision rather than treating the
migration as a mechanical dataclass substitution.

## Decision drivers

- Fail closed on wrong primitive types, unknown fields, invalid nested models, and
  invalid defaults without silent coercion.
- Preserve frozen value semantics, equality, hashing, tuple and frozenset types,
  deterministic JSON shapes, CLI output, and current workload budgets.
- Retain established domain exceptions at file, registry, and CLI boundaries
  without exposing validation-library internals or input payloads.
- Declare and exactly lock every direct runtime dependency.
- Keep graph, repository-state, external-evidence, ownership, and workload checks
  in their existing services rather than coupling them to individual records.

## Considered alternatives

- **Retain frozen standard-library dataclasses:** avoids a runtime dependency but
  leaves direct construction without a uniform fail-closed validation contract.
- **Use `pydantic.dataclasses.dataclass`:** reduces migration effort but preserves
  the old declaration style and provides less explicit model and serialization
  boundaries than `BaseModel`.
- **Use strict Pydantic `BaseModel` boundary records:** adds a pinned dependency
  and keyword-only construction while making validation, immutability, nested
  revalidation, and serialization policy explicit.
- **Create a custom validation framework:** avoids a third-party runtime package
  but adds bespoke maintenance and error/serialization behavior without a current
  institutional need.

## Decision

Use Pydantic v2 `BaseModel` for the existing Python governance, configuration,
registry, and serialization records. A small internal base may centralize only the
uniform settings `frozen=True`, `extra="forbid"`, strict validation, default
validation, rejection of non-finite numbers, and always-on nested-instance
revalidation. Unordered frozen sets use sorted JSON serializers. Pydantic is an
exact direct runtime dependency recorded in project metadata and `uv.lock`.

Models use keyword construction. Existing repository call sites are migrated;
positional construction was not a documented supported API. Trusted updates must
reconstruct or revalidate complete data because `model_copy(update=...)` does not
validate updates. An unvalidated copy is permitted only to represent explicitly
tampered or untrusted evidence in a test.

Model-local invariants belong in field or model validators. Filesystem state,
cross-record references, graph-wide uniqueness, external evidence, and workload
budgets remain in registries and services. Public loaders translate
`ValidationError` to their existing domain error and preserve the exception cause.
Existing thin `as_json()` methods remain where their field order or representation
is an established CLI contract.

This decision does not authorize Pydantic in the economic kernel or trading domain
without a separate boundary-specific decision. It does not change canonical
schemas, roadmap state, validation evidence, release, deployment, or activation.

## Consequences

Direct construction becomes deterministic and rejects coercion, missing or unknown
fields, invalid nested instances, and invalid defaults. Models remain immutable,
value-comparable, hashable where their fields are hashable, and predictably
serializable. Definitions gain a runtime dependency and Pydantic-specific validator
APIs. Keyword-only construction is an intentional compatibility constraint, and
future dependency upgrades require an explicit exact-pin and lockfile change.

The repository-local implementation can pass all automated gates while this ADR
remains `Proposed`. Passing those gates neither accepts the decision nor validates
an A02 or other roadmap package.

## Migration and rollout

Migrate all production dataclasses in one reviewed compatibility change so nested
models do not straddle two construction systems. Update internal constructors,
trusted update paths, dependency contract tests, direct validation tests, error
translation tests, and serialization snapshots together. Compare all governed CLI
JSON byte-for-byte before and after the migration and rerun inventory and program
workload budgets.

The only intentional CLI text delta is the architecture-governance success count,
which increases from seven to eight because this required ADR is now governed by
the same decision-directory contract. All JSON-producing CLI output remains
byte-identical.

The change is repository-local and has no data, state, schema, deployment, or
activation migration. Monitor CI, packaging/import smoke tests, model validation
failures at loaders, CLI snapshots, and the existing workload benchmarks. Release
or deployment remains a separate governed action.

## Reversal plan

If output compatibility, domain errors, packaging, validation correctness, or
performance budgets regress, revert the reviewed migration and exact dependency
change to the last compatible frozen-dataclass revision. No stored data requires
conversion. Retain failing fixtures and before/after CLI snapshots as recovery
evidence. The decision owner should make the rollback decision before any separate
release action; successful legacy and root checks prove repository recovery.

## Review and evidence

Required review is Platform Code Owner plus an independent affected-domain
reviewer, with security review for dependency and validation-surface findings.
Required repository evidence includes the complete test suite, strict mypy, Ruff,
Bandit, architecture and package governance checks, lock verification, import
smoke test, package build, byte-identical CLI output comparisons, final dataclass
search, and inventory/program performance budgets.

Approval is unavailable in the solo-authored workspace. A02-F01 remains open; a
named Code Owner must review the exact change and record commit-bound acceptance
before this ADR can move from `Proposed`. Re-review by 2026-11-30, on any Pydantic
upgrade, on expansion into trading-domain models, or on a compatibility or
performance regression.
