# Governed Repository Topology and Enforcement

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | B01 |
| Delivery slice | B01c |
| Operating track | Solo bootstrap |
| Parent-package status | Partial |
| Slice status | Provisionally implemented |
| Accountable owner role | Platform |
| Change risk | R2 |
| Applicable gates | QG01-QG06, QG09-QG14 |
| Machine-readable registry | [Repository topology](repository-topology.toml) |

## Objective and delivery boundary

B01c completes B01's repository-local delivery slices. It preserves B01a's
complete current-source registry and B01b's owned `tools/governance` targets and
compatibility facades, then makes the repository root, pre-commit, hosted CI,
A06 inventory, and A08 program dashboard consume and enforce those canonical
targets.
Retired build, environment, remote-execution, and custom scheduler surfaces
remain historical records and are not current topology requirements.

The root `alpha-research-lab` distribution declares exact
`alpha-research-governance==0.1.0` and `pydantic==2.13.5` runtime dependencies. The canonical
implementation remains in that non-editable repository path package.
Compatibility APIs under `alpha_research.*` remain available for existing
callers and rollback, but no B01c enforcement consumer uses an ambient
`PYTHONPATH` or a compatibility module command.

B01c did not create the target domain skeleton or introduce a build, domain, or
external dependency. The active source and policy graph is checked through the
pinned uv environment and the single required `make check` command. The
compatibility facades remain available for existing callers and rollback until a
separately reviewed compatibility change retires them.

## Canonical targets and enforced consumers

The tool distribution owns the active governance entry points, including the
B05, B07, and B08 package controls added after B01:

```text
alpha-governance-architecture
alpha-governance-artifacts
alpha-governance-change-risk
alpha-governance-dependencies
alpha-governance-engineering-standards
alpha-governance-evidence
alpha-governance-inventory
alpha-governance-ownership
alpha-governance-program
alpha-governance-security
alpha-governance-topology
```

Make delegates each active governance target directly to its installed executable.
`make topology-check` is a blocking dependency of `make check`. Root formatting,
lint, strict typing, and Bandit coverage include `tools/governance/src` as well as
the compatibility source and engineering tests. Tests and smoke imports use uv's
non-editable installed-project mode without source-path injection, avoiding
workstation-specific editable-install behavior.

Pre-commit invokes the same canonical commands. The topology hook is
`always_run`, so an added, moved, uncovered, cyclic, upward, invisible, or stale
source edge cannot avoid graph validation because of a filename filter. The
hosted workflow installs the frozen workspace and invokes the same commands,
including topology, on pull requests and pushes to `main`. The workflow
definition is repository-local evidence only; protected-branch, merge-result,
and retained exact-commit execution remain open external findings.

A06 initially inventoried nine provisional controls: A01-A08 and B01. The A02-A08
records use canonical implementation paths and increment their record versions;
the new B01 record links the registry, validator, root, hook, workflow, tests,
and B01c evidence. A08 records B01 as `partial` with passing repository-local
evidence and the exact B01 findings. The active queue is derived from the current
technical graph; retired B02, B03, and B06 records remain in the program for
historical provenance, while institutional readiness remains empty.

Unknown arguments, missing repositories, invalid topology, stale inventory
lineage, unsupported program state, and canonical command failures return a
nonzero result. No automation surface silently falls back to a compatibility
module.

## Dependency direction and current targets

The ordered source layers remain `foundation`, `policy`, `evidence`, `catalog`,
`compatibility`, and `verification`. Canonical tools depend only on same or lower
tool layers. Compatibility targets depend on exactly one canonical tool target;
canonical tools never depend back on compatibility code. Engineering tests are
the only current reverse consumer of both surfaces.

The registry now assigns every Python implementation, facade, typing marker,
engineering-test source, and C01-C02 unit-test source under
`tools/governance/src/alpha_research_governance/`, `src/alpha_research/`,
`tests/engineering/`, and `tests/unit/` to exactly one of 28 owned targets. Each
target declares kind, layer, accountable owner, supported platform,
direct dependencies, exact reverse visibility, and exact source paths. The
validator derives direct imports for both namespaces with deterministic AST
parsing and rejects missing or stale declarations.

C01 and C02 add owned `library` kinds for foundational instrument-identity and
venue-calendar targets with their direct unit-test consumers. This is
current-source registration, not a new B01 delivery slice or a change to B01's
partial status and findings.

`load_topology()` validates a supplied registry against a repository root.
`validate_repository()` also validates the B01c synthetic SHA-bound evidence
bundle. Validation fails closed when:

- a source is absent, duplicated, missing, outside the repository, or a symlink;
- a target, kind, owner, layer, platform, dependency, visibility entry, or
  evidence binding is invalid or stale;
- a dependency points upward, forms a cycle, or is not visible to its consumer;
- declared direct dependencies differ from imports parsed from registered
  sources; or
- package, B01c slice, R2 gate, finding, source-root, layer-order, completed-slice,
  or evidence metadata weakens the contract.

The scan remains capped at 1,000 source files and the focused full-validation
budget remains 1,000 ms. Raising either bound requires reviewed workload evidence;
B05 owns the current source-validation and installed wheel-smoke checks.

No target-domain placeholder directory is created. B01's only populated target
addition is `tools/governance`. B01 did not create `schemas/`, `data/`,
`research/`, `simulation/`, `portfolio/`, `risk/`, `trading/`, `platform/`,
`assets/`, or `strategies/` source trees. The historical B03 environment files
are retired and no longer belong to the current source registry.

## Packaging and compatibility contract

The root distribution declares exact `alpha-research-governance==0.1.0`,
`pydantic==2.13.5`, and `exchange-calendars==4.13.2` runtime dependencies for its
compatibility facades and C01-C02 domain boundaries. C02 constrains NumPy to the
admitted `2.4.6` compatibility version. The governance tool target owns the same
exact Pydantic input and uses the same pinned Python and Hatchling versions.
The lock records the governance tool as a non-editable repository-local path
package, so canonical commands do not depend on ambient source paths, the
caller's working directory, or a network.

Compatibility facades contain no policy, parser, classifier, registry, or model
implementation. They remain registered and tested because B01c changes consumers,
not the public compatibility window. Removing them before B02 provides reviewed
replacement and rollback evidence would be an out-of-scope breaking change.

## Evidence and governance

The [B01c synthetic local evidence bundle](../governance/evidence/examples/b01c-r2-partial/manifest.toml)
binds those facts, QG01-QG06 and QG09-QG14, artifact digests, partial status, and
findings. Deterministic tests cover canonical root/hook/workflow selection,
topology enforcement, A06 canonical lineage and B01 population, A08 B01-to-B02
readiness, completed-slice metadata, compatibility parity, invalid input, missing
roots, uncovered and duplicate sources, dependency drift, upward edges, cycles,
path escape, malformed TOML, workload bounds, and failure propagation. Gate
definitions live in the [quality-gate catalog](operations.md#quality-gate-catalog);
current state and finding IDs are rendered in the
[program status](../governance/program-status.md).

## Migration, rollout, rollback, monitoring, and runbook

Migration is repository-local. Enforcement consumers move from compatibility
module commands to installed canonical executables; A06 preserves stable IDs while
versioning changed lineage; A08 adds B01's partial state. There is no schema,
database, persisted state, data/model lineage, runtime service, deployment lane,
credential, market connection, account, venue, limit, or capital migration.

Rollout is limited to root, hook, and workflow definitions. Rollback is a reviewed
revert of the consumer migration, registry metadata, inventory/program records,
tests, documentation, and evidence together. Reverting only one surface would
create drift and fail deterministic checks. Root, hook, hosted-check, inventory,
and dashboard failures are the repository-local operational signals. There is no
production monitor, alert, dashboard service, data migration, or operator runbook
impact.

## Governance references

The [development workflow](../governance/workflow.md) owns daily evidence and the
[program status](../governance/program-status.md) owns the current queue. B01
defines repository structure only and grants no release, deployment, activation,
credential, market or capital authority.
