# Governed Resource Inventory

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | A06 |
| Operating track | Solo bootstrap |
| Package status | Partial |
| Accountable owner role | Platform |
| Risk class | R2 shared registry contract |
| Applicable gates | QG01-QG06, QG09-QG14 |
| Machine-readable catalog | [Resource inventory](resource-inventory.toml) |

## Contract and scope

The catalog is the authoritative repository-local inventory of datasets, models,
strategies, services, limits, venues, releases, and controls visible in this
checkout. It is subordinate to the blueprint and the platform
[contracts](../architecture/contracts.md). Its scope does not claim an
organization-wide inventory while A01-F01 remains open.

Each resource has one stable inventory identity of the form
`inv.<kind>.<namespace>.<name>`. The identity remains unchanged when metadata is
corrected; `record_version` increments instead. A replacement resource receives a
new identity. Later domain packages may add canonical domain identifiers, but
must retain a mapping to this inventory identity rather than rewriting history.

Every record includes its kind, name, owner role, T0-T3 criticality, lifecycle
status, dependencies, retention class, source paths, lineage, deployment status
and evidence, status evidence, and ownership-review due date. Dependencies form a
directed acyclic graph. Repository paths must be contained and exist; external
evidence must use HTTPS without embedded credentials.

The catalog also records one population state for every supported kind. `empty`
is an evidence-bearing statement with an owner and rationale, not a placeholder.
Adding a real resource changes the kind to `populated` in the same change.

## Current population

The current repository has sixteen control records: A01 through A08, B01's
governed repository topology, B04's engineering standards, B05's source and
required-check policy, B07's dependency-admission control, and B08's
whole-artifact supply-chain control. B02's hermetic build graph, B03's
clean-machine environment, and B06's remote-execution proposal are retained as
`retired` historical records with their evidence links. B01c
incremented the A02-A08 control records to version 2 because their implementation
lineage named the canonical `tools/governance` targets instead of compatibility
facades. B02 and B03 are retired historical records. B04 increments the affected
A03, A04, A06, A08, and B01 records and adds its own control. B05 increments A06,
A08, and B01 for catalog state, program readiness, topology, and the required
check path, and adds its own control. B06 is a retired historical record. B07
increments the current integration records for catalog state, readiness, lock
inputs, root automation, and hosted audit execution, and adds its own control.
B08 links its control to A07 security policy and B07 dependency admission.
All other kinds are
explicitly empty because the corresponding canonical data, research, risk,
trading, deployment, and release packages do not yet exist. A Git commit, wheel,
research roadmap, evidence fixture, or proposed strategy is not silently promoted
into a dataset, model, strategy, service, limit, venue, or release.

Current controls remain `provisional`; B02, B03, and B06 are explicitly retired.
The current controls are repository-local checks, not institutionally validated,
deployed, released, or activated resources.

## Validation and query interface

`make check` validates the complete catalog and cross-checks owner roles against
the A03 ownership register. Focused `make inventory-check` remains available for
local investigation. Missing lineage, unresolved dependencies, dependency
cycles, stale or unknown ownership, overdue review, path escape, population drift,
catalog-size overflow, and deployed resources without evidence fail closed with
deterministic findings. The catalog caps version 2 at 10,000 records and retains
a deterministic 10,000-query workload with a 1,000 ms repository-test budget.

The CLI emits stable JSON sorted by inventory identity:

```sh
uv run --frozen alpha-governance-inventory --json
uv run --frozen alpha-governance-inventory --kind control
uv run --frozen alpha-governance-inventory --kind dataset
uv run --frozen alpha-governance-inventory --owner-role platform
```

An empty query returns `count: 0`; absence is not an error when the corresponding
kind state is explicitly `empty`. Repeated equivalent queries must produce
byte-identical JSON. A synthetic partial R2 bundle under
[`evidence/examples/a06-r2-partial`](evidence/examples/a06-r2-partial/manifest.toml)
exercises A04 classification, all applicable gate records, artifact digests, and
the exact A06 finding set. An immutable package profile also binds its accountable
owner, every classification fact, exact gate status, partial status, and forbids
approvals, waivers, or caller-added gates. Its all-`2` SHA is deliberately
synthetic: the bundle is repository-local validator evidence, not a commit,
review, protected-forge result, approval, release, deployment, or activation
record.

## Evidence policy

Applicable control definitions live in the
[quality-gate catalog](../architecture/operations.md#quality-gate-catalog). Exact
A06 gate state and finding closure conditions live in
[resource-inventory.toml](resource-inventory.toml); current state and finding IDs
are rendered in the [program status](program-status.md).

## Migration, rollout, rollback, monitoring, and runbook

Catalog schema version 1 remains compatible and has no persisted data, service
state, or runtime migration. Catalog version 8 records the current source and
retirement disposition while preserving stable inventory identities. B02, B03,
and B06 remain recoverable historical records; their retired status does not
serve as an active prerequisite for B04, B05, B07, or B08. B07 increments the
current integration records while adding its dependency-admission control.
Future
incompatible catalog changes require a versioned compatibility plan and retained
readers; ordinary metadata corrections increment the affected record version.

Rollout adds repository checks only. It does not deploy or activate a resource.
Rollback is a reviewed revert that preserves the prior catalog and evidence in
Git history. CI/pre-commit failure output and JSON findings are the monitoring
surface. No production dashboard, alert route, operator runbook, stop procedure,
or kill path changes in A06.

## Governance references

The [development workflow](workflow.md) owns daily evidence and validation. The
[program status](program-status.md) owns the current finding and handover view.
A06 creates repository metadata only and grants no deployment, activation,
credential, market, capital or risk authority.
