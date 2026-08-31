# Governed Repository Topology

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | B01 |
| Delivery slice | B01a |
| Operating track | Solo bootstrap |
| Parent-package status | Partial |
| Slice status | Provisionally implemented |
| Accountable owner role | Platform |
| Change risk | R2 |
| Applicable gates | QG01-QG06, QG09-QG14 |
| Machine-readable registry | [Repository topology](repository-topology.toml) |

## Objective and delivery boundary

B01a defines the governed graph for the source that exists now. The registry
assigns every Python implementation, typing marker, and engineering-test source
under `src/alpha_research/` and `tests/engineering/` to exactly one stable unit.
Each unit declares its kind, dependency layer, accountable owner, supported
platform, direct dependencies, direct consumers, and exact source paths.

The `alpha_research.repository_topology` API loads the registry and fails closed
when:

- a current source is absent, duplicated, missing, outside the repository, or a
  symlink;
- a unit, owner, layer, platform, dependency, visibility entry, or evidence
  binding is invalid or stale;
- a dependency points upward, forms a cycle, or is not visible to its consumer;
- declared direct dependencies differ from the internal imports parsed from the
  registered sources; or
- package, slice, R2 gate, finding, source-root, layer-order, or evidence metadata
  weakens the B01a contract.

`load_topology()` validates a supplied registry against a repository root.
`validate_repository()` additionally validates the repository's synthetic,
SHA-bound B01 evidence fixture. B01a intentionally adds no root command or module
entry point: B01b owns tooling targets and compatibility entry points, while
B01c owns Make, pre-commit, hosted-CI, A06, and A08 consumption.

## Dependency direction and current units

The ordered layers are `foundation`, `policy`, `evidence`, `catalog`, and
`verification`. A unit may depend on the same or an earlier layer, never a later
one. Visibility is the exact reverse of declared direct edges, so unused broad
visibility cannot silently accumulate. AST validation independently derives the
current `alpha_research` import edges and rejects either missing or stale
declarations. B01a caps the scan at 1,000 source files; raising the ceiling
requires reviewed workload evidence, while B05 owns the scaled affected/full
enforcement design. The focused performance check requires full repository
validation to complete within the registry's 1,000 ms workload budget.

The current registry contains the bootstrap foundation; architecture, ownership,
and change-risk policies; evidence policy; the inventory, security-control,
program-governance, and repository-topology catalogs; and one engineering-test
unit. These are descriptions of existing source, not target-domain placeholders.
No `schemas/`, `data/`, `research/`, `simulation/`, `portfolio/`, `risk/`,
`trading/`, `platform/`, `assets/`, `strategies/`, `environments/`, or `tools/`
tree is created by this slice.

## Risk, gates, and evidence

The A04 facts are: no capital at risk, shared-domain blast radius, shared-library
materiality, no security privilege, compatibility-window reversal, and no
computational, economic/risk, model, or trading relevance. The resulting class
is R2. QG07-QG08 are not conditionally added and QG15 is not an R2 gate.

The [synthetic local evidence bundle](../governance/evidence/examples/b01a-r2-partial/manifest.toml)
binds the exact classification facts, QG01-QG06 and QG09-QG14, artifact digests,
partial status, and findings. Focused tests cover valid topology, lookup boundary,
uncovered and duplicate sources, declared/imported dependency mismatch, package-
import bypass, visibility drift, upward edges, cycles, unknown dependencies,
ownership and kind errors, path escape, source-root weakening, malformed TOML,
unknown fields, and evidence-path containment.

Repository-local success is not independent review, protected-forge execution,
or institutional validation. R2 requires the Platform Code Owner and an
independent domain reviewer.

| Finding | Owner | Unavailable evidence | Closure condition |
| --- | --- | --- | --- |
| B01-F01 | Domain Architecture | Independent domain review and commit-bound Code Owner approval | Named reviewers resolve findings and approve the exact registry and validator commit |
| B01-F02 | Platform/CI | Protected merged-result execution and retained exact-commit evidence | After B01c consumes the validator, protected CI rejects representative graph mutations on the exact reviewed merged result |

## Migration, rollout, rollback, monitoring, and runbook

This is additive repository metadata and validation logic. It changes no schema,
persisted state, data/model lineage, runtime service, deployment lane, credential,
market connection, account, venue, limit, or capital path. B01b may relocate the
transitional governance implementation out of the future runtime wheel only while
preserving this API through its owned compatibility entry points.

Rollout is repository-local use by focused tests until the successor slices add
owned targets and enforcement. Rollback is a reviewed revert to the last passing
registry and validator together; reverting only the registry or only the checker
is not a compatible rollback. A deterministic validation failure is the local
operational signal. No production monitoring, alert, dashboard, migration, or
operator runbook is introduced.

## Parent status, non-goals, and successor

B01 remains `partial`. B01a does not independently validate the parent and does
not implement B01b, B01c, B02/Bazel, the target repository skeleton, generated
code, a new dependency, clean-machine build equivalence, supply-chain admission,
deployment, activation, credentials, market access, or expanded risk authority.

The next documented selector is `B01b`, which owns governance-tooling targets,
migration out of the future runtime wheel, and compatibility entry points.
