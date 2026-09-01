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

The current repository has ten provisional controls: A01 through A08 plus B01's
governed repository topology and B02's hermetic build graph. B01c incremented the
A02-A08 control records to version 2 because their implementation lineage named
the canonical `tools/governance` targets instead of compatibility facades. B02
increments the affected A03, A06, A08, and B01 records. All other kinds are
explicitly empty because the corresponding canonical data, research, risk,
trading, deployment, and release packages do not yet exist. A Git commit, wheel,
research roadmap, evidence fixture, or proposed strategy is not silently promoted
into a dataset, model, strategy, service, limit, venue, or release.

All ten control records remain `provisional`. Their source checks are active
repository-local controls, but they are not institutionally validated, deployed,
released, or activated resources.

## Validation and query interface

`make inventory-check` validates the complete catalog and cross-checks owner roles
against the A03 ownership register. The same command runs in pre-commit, hosted
CI, and the root check. Missing lineage, unresolved dependencies, dependency
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

## Quality-gate evidence

| Gate | Repository-local evidence |
| --- | --- |
| QG01 | Ruff formatting/lint and strict mypy cover the API, CLI, and tests |
| QG02 | The locked Python environment and byte-identical repeated TOML/JSON behavior use no network, wall clock, or workstation input |
| QG03 | Success, boundary, invalid-input, and failure-path tests cover parsing, queries, and automation |
| QG04 | Stable-ID uniqueness, kind matching, dependency acyclicity, and population invariants are enforced |
| QG05 | Source, lineage, version, ownership, status, and evidence references fail closed; positive and negative deployed-resource fixtures exercise evidence linkage |
| QG06 | Dataset/model/strategy absence is explicit; no research or model result is claimed |
| QG09 | Root, pre-commit, and hosted-CI interfaces execute the same repository validator |
| QG10 | Catalog size is capped; a deterministic 10,000-query workload must complete within the retained 1,000 ms repository-test budget |
| QG11 | Missing, malformed, cyclic, stale, or unresolved state blocks validation and is recoverable by reviewed Git rollback |
| QG12 | Paths cannot escape the repository; external evidence URLs cannot contain credentials; Bandit scans production Python |
| QG13 | This package record, catalog contract, commands, ownership, and non-goals are documentation-link checked |
| QG14 | Machine-readable query output exposes query limits, while stale-owner/review findings provide the repository-local monitoring signal |

QG07 and QG08 are not applicable because A06 defines metadata and evidence
linkage only; it creates no cost model, economic decision, executable limit, risk
calculation, or risk envelope.

## Migration, rollout, rollback, monitoring, and runbook

Catalog schema version 1 remains compatible and has no persisted data, service
state, or runtime migration. Catalog version 2 adds one B02 control record after
B01c added B01. It increments A03, A06, A08, and B01 for B02's ownership, catalog,
program-state, and topology changes; all stable inventory identities are preserved.
Future
incompatible catalog changes require a versioned compatibility plan and retained
readers; ordinary metadata corrections increment the affected record version.

Rollout adds repository checks only. It does not deploy or activate a resource.
Rollback is a reviewed revert that preserves the prior catalog and evidence in
Git history. CI/pre-commit failure output and JSON findings are the monitoring
surface. No production dashboard, alert route, operator runbook, stop procedure,
or kill path changes in A06.

## Review split plan

Review the A06 epic as `A06a` for the contract, stable identifiers, catalog,
population claims, and package record, followed by `A06b` for the validator,
query API, adversarial tests, and automation. Both slices retain A06 and neither
alone satisfies its repository-local evidence.

## Open findings

| Finding | Owner | Unavailable evidence | Closure condition |
| --- | --- | --- | --- |
| A06-F01 | Platform | Organization-wide and external-control-plane reconciliation while A01-F01 remains open | Named owners reconcile every kind and empty declaration against organization and target-system inventories and resolve omissions or stale records |
| A06-F02 | Platform/CI | Local stale-owner and missing-lineage mutations block validation; protected merged-result execution and exact-commit retention remain unavailable | Protected CI runs the exact reviewed merged result and retains corresponding pass and blocking-mutation evidence |
| A06-F03 | Model Validation | Independent data/model/domain/operations review during solo bootstrap | Named independent reviewers resolve findings and approve the exact catalog contract, population, retention, and closure evidence |

These are not waivers or approvals. A06 remains partial until all three close.

## Non-goals

- Creating B03 clean-machine provisioning, later target domain directories, canonical
  schemas (C), data/model registries (D/E), services, limits, venue adapters, or
  releases.
- Connecting an external catalog, forge, deployment registry, identity system,
  venue, broker, account, credential, or telemetry backend.
- Treating provisional records as validated, released, promoted, deployed, or
  activated, or granting market, capital, credential, or risk authority.
