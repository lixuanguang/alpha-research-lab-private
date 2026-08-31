# Governed Repository Topology and Tooling Targets

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | B01 |
| Delivery slice | B01b |
| Operating track | Solo bootstrap |
| Parent-package status | Partial |
| Slice status | Provisionally implemented |
| Accountable owner role | Platform |
| Change risk | R2 |
| Applicable gates | QG01-QG06, QG09-QG14 |
| Machine-readable registry | [Repository topology](repository-topology.toml) |

## Objective and delivery boundary

B01b preserves B01a's complete current-source graph and separates repository
governance from the platform package. Canonical implementation now belongs to the
`alpha-research-governance` path target under `tools/governance/`, with source in
`alpha_research_governance`. The root `alpha-research-lab` distribution has no
runtime dependency and retains only narrow `alpha_research.*` compatibility
facades for the existing public APIs and module commands.

The tool distribution owns eight executable entry points:

```text
alpha-governance-architecture
alpha-governance-change-risk
alpha-governance-evidence
alpha-governance-inventory
alpha-governance-ownership
alpha-governance-program
alpha-governance-security
alpha-governance-topology
```

The canonical topology command is also available as
`python -m alpha_research_governance.repository_topology`. The previous
`python -m alpha_research.repository_topology` form delegates to the same
`main()` object under the existing root command environment (`PYTHONPATH=src`),
and all prior public package-level APIs delegate to the same canonical functions,
models, constants, and domain errors. Unknown arguments, missing repositories,
invalid topology, and dependency drift fail closed with a nonzero result.

B01c, not this slice, owns switching Make, pre-commit, hosted CI, A06, and A08 to
the canonical targets and enforcing the topology there. Existing root commands
therefore continue through the compatibility facades during this bounded window.

## Dependency direction and current targets

The ordered layers are `foundation`, `policy`, `evidence`, `catalog`,
`compatibility`, and `verification`. Canonical tools depend only on same or lower
tool layers. Compatibility targets depend on exactly one canonical tool target;
canonical tools never depend back on compatibility code. Engineering tests are
the only current reverse consumer of both surfaces.

The registry assigns every Python implementation, facade, typing marker, and
engineering-test source under `tools/governance/src/alpha_research_governance/`,
`src/alpha_research/`, and `tests/engineering/` to exactly one of 19 owned
targets. Each target declares kind, layer, accountable owner, supported platform,
direct dependencies, exact reverse visibility, and exact source paths. The
validator derives direct imports for both namespaces through deterministic AST
parsing and rejects missing or stale declarations.

`load_topology()` validates a supplied registry against a repository root.
`validate_repository()` also validates the B01b synthetic SHA-bound evidence
bundle. Validation fails closed when:

- a source is absent, duplicated, missing, outside the repository, or a symlink;
- a target, kind, owner, layer, platform, dependency, visibility entry, or
  evidence binding is invalid or stale;
- a dependency points upward, forms a cycle, or is not visible to its consumer;
- declared direct dependencies differ from the imports parsed from registered
  sources; or
- package, slice, R2 gate, finding, source-root, layer-order, remaining-slice, or
  evidence metadata weakens the B01b contract.

The scan remains capped at 1,000 source files and the focused full validation
budget remains 1,000 ms. Raising either bound requires reviewed workload evidence;
B05 still owns scaled affected/full enforcement.

No target-domain placeholder directory is created. B01b adds only the populated
`tools/governance` target required by this slice. It does not create `schemas/`,
`data/`, `research/`, `simulation/`, `portfolio/`, `risk/`, `trading/`,
`platform/`, `assets/`, `strategies/`, or `environments/` source trees.

## Packaging and compatibility contract

The root distribution declares no Pydantic or governance-tool runtime dependency.
The tool target declares the existing exact `pydantic==2.13.5` input and uses the
same pinned Python and Hatchling versions; the lock records it as a non-editable
repository-local path package so canonical commands do not depend on ambient
`PYTHONPATH` or the current working directory. Transitional root compatibility
commands retain the existing source-path environment until B01c migrates their
consumers. No external dependency was added.

The compatibility facades contain no policy, parser, classifier, registry, or
model implementation. Selected legacy registry paths remain executable facades so
the unchanged A06 inventory remains valid without B01b consuming or rewriting it.
Removal is blocked until B01c migrates every root/pre-commit/CI/A06/A08 consumer,
the canonical and compatibility suites pass on the merged result, and rollback no
longer requires the old module paths. B02 may then remove the facades only through
a separately reviewed compatibility change.

## Risk, gates, and evidence

The A04 facts are: no capital at risk, shared-domain blast radius, shared-library
materiality, no security privilege, compatibility-window reversal, and no
computational, economic/risk, model, or trading relevance. The resulting class
is R2. QG07-QG08 are not conditionally added and QG15 is not an R2 gate.

The [B01b synthetic local evidence bundle](../governance/evidence/examples/b01b-r2-partial/manifest.toml)
binds those facts, QG01-QG06 and QG09-QG14, artifact digests, partial status, and
findings. Focused tests cover canonical success, API identity, legacy command
parity, owned console entry points, distribution boundaries, exact dependency
placement, lock identity, invalid arguments, missing roots, uncovered/duplicate
sources, undeclared/stale dependencies, upward edges, cycles, unknown targets,
path escape, malformed TOML, workload bounds, and evidence containment.

Repository-local success is not independent review, protected-forge execution,
or institutional validation. R2 requires the Platform Code Owner and an
independent domain reviewer.

| Finding | Owner | Unavailable evidence | Closure condition |
| --- | --- | --- | --- |
| B01-F01 | Domain Architecture | Independent domain review and commit-bound Code Owner approval | Named reviewers approve the exact target registry, tooling migration, compatibility facades, and validator commit |
| B01-F02 | Platform/CI | Protected merged-result execution and retained exact-commit evidence | B01c makes protected CI reject representative graph and compatibility mutations on the exact reviewed merged result |

## Migration, rollout, rollback, monitoring, and runbook

Migration is repository-local and preserves the old API and command behavior while
changing implementation ownership and package dependency placement. It changes no
schema, persisted state, data/model lineage, runtime service, deployment lane,
credential, market connection, account, venue, limit, or capital path.

Rollout remains local/focused until B01c changes enforcement consumers. Rollback is
a reviewed revert of the tool package, facades, lock, registry, validator, tests,
documentation, and evidence together; reverting only an implementation or facade
would violate compatibility. Deterministic command or topology failure is the
repository-local operational signal. There is no production monitor, alert,
dashboard, data migration, or operator runbook impact.

## Parent status, non-goals, and successor

B01 remains `partial`. B01b does not independently validate the parent and does
not implement B01c, B02/Bazel, the target repository skeleton, generated code, a
new external dependency, clean-machine equivalence, affected/full build policy,
supply-chain admission, deployment, activation, credentials, market access, or
expanded risk authority.

The next documented selector is `B01c`, which owns root, pre-commit, hosted-CI,
A06, and A08 enforcement of the governed topology and canonical tool targets.
