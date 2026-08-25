# ADR 0002: Language and runtime boundaries

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

Research productivity, numerical safety, vendor integration, and latency-sensitive
execution have different runtime needs. One universal language/runtime would
either constrain research or contaminate hot paths with unnecessary dependencies.

## Decision drivers

- Clear ownership and one authoritative economic rule across languages.
- Pinned toolchains, narrow compatibility boundaries, deterministic conformance,
  memory safety, and measured performance.

## Considered alternatives

- **Python everywhere:** maximizes initial simplicity but does not establish every
  latency, memory, or native integration profile.
- **Native implementation everywhere:** raises research and iteration cost and can
  duplicate economic behavior.
- **Role-based languages:** use Python by default and native targets only when a
  current contract or measurement justifies them.

## Decision

Use pinned Python 3.12 for bootstrap research, orchestration, and services whose
budgets it meets. Prefer Rust for new memory-safe native components; permit C/C++
for certified vendor/native interoperability or measured latency needs. Keep one
authoritative implementation per rule. Cross-process interfaces use schemas;
in-process native integration uses a narrow C ABI or reviewed binding layer.

## Consequences

Teams can select the simplest adequate runtime while accepting cross-language
build and conformance costs. A native target is not justified by code shape alone,
and Python/native alternatives require shared golden and differential tests.

## Migration and rollout

B02 pins each admitted toolchain. B04 adds language checks and sanitizers. Native
code enters only through an owned target with ABI, ownership, error, threading,
numeric, packaging, and rollback evidence.

## Reversal plan

Disable or remove a native path when parity, safety, recovery, or performance
evidence fails; restore the last compatible authoritative implementation and
retain fixtures needed to reconcile affected artifacts.

## Review and evidence

Review at each first native boundary and when controlled benchmarks contradict
the runtime choice. Required reviewers include the owning domain and platform;
security and SRE participate according to the resulting risk class.

