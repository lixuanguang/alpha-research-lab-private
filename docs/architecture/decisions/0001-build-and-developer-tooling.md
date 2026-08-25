# ADR 0001: Build and developer tooling

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

The bootstrap uv/Make package is reproducible enough for current Python checks but
cannot express the target polyglot graph, visibility, remote execution,
provenance, or affected-target and merged-result evidence.

## Decision drivers

- Hermetic, explicit, content-addressed Python, Rust and/or C++, Protobuf, SQL,
  documentation, generation, test, and artifact targets.
- One root interface with deterministic local/CI behavior and no workstation
  dependency.

## Considered alternatives

- **Retain uv and Make as the final build:** simple now, but cannot meet the target
  graph and provenance controls.
- **Adopt a different polyglot graph:** viable only with evidence equal to the
  blueprint's hermeticity, visibility, execution, and provenance requirements.
- **Use Bazel with Nix or an equivalent environment:** matches the reference
  architecture while allowing measured substitutions through a later ADR.

## Decision

B02 will establish a pinned hermetic Bazel graph. B03 will supply Nix or an
equivalent declarative developer environment. The current uv lock and Make targets
remain transitional inputs and must delegate to, or be retired by, the governed
graph without preserving a Python-only topology.

## Consequences

Build and ownership boundaries become explicit and scalable, at the cost of
tooling complexity and migration work. This ADR selects the target control model;
it does not claim that B02-B03 are implemented.

## Migration and rollout

B01 defines targets and boundaries; B02 imports pinned language/dependency inputs;
B03 proves clean-machine bootstrap. Migration keeps current checks live until
equivalent Bazel targets and rollback instructions pass.

## Reversal plan

If Bazel or the environment choice cannot meet measured correctness, platform, or
operational budgets, retain the last verified bootstrap interface and propose a
replacement ADR demonstrating equivalent hermeticity and evidence before cutover.

## Review and evidence

Platform Code Owner review, clean bootstrap, sandbox/undeclared-input tests,
cross-environment digest comparison, and rollback evidence are required by
B02-B03. Review this proposal when those measured results exist.

