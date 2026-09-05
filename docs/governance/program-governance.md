# Program dependency and KPI governance

## Contract

A08 turns the [implementation roadmap](../roadmap/README.md) into a deterministic
delivery graph and defines the blueprint's seven program KPIs. The
[versioned program record](program-governance.toml) is the single source for
implementation state, ownership, retained finding IDs, KPI definitions and the
generated-status path. The [program status](program-status.md) is rendered from that
record and must not be edited by hand.

Schema version 4 keeps the version-3 dependency purposes and non-contiguous state
records, and requires each current package state to name exactly one Markdown
capability contract. Adjacent TOML policy is part of that contract, not a second
status source. Version-1 through version-3 records remain readable with their
original institutional and dependency semantics.

Every roadmap edge is one of `implementation`, `operation/release` or
`team handover`. Untyped historical expressions are implementation edges. The
reader expands exact ranges and `any of` groups, rejects unknown or duplicate
packages, and detects cycles across every purpose. Only implementation edges enter
the active technical queue. Operation and handover edges remain visible for the
contexts that activate them.

The version-4 record also gives every retained legacy finding exactly one migration
disposition: technical issue, operation prerequisite or role handover. An empty
technical group records that the migrated baseline has no known repository-behavior
defect; any new technical finding is still recorded directly on its package state
and blocks completion.

Each explicit package state separates:

- `implementation_status` and `technical_finding_ids`, which determine engineering
  completion;
- derived `governance_status` and assigned reviewers, which describe scoped
  handover; and
- retained `status` and `open_finding_ids`, which preserve institutional or
  operation-specific obligations.

Complete implementation requires passing repository-local evidence, no technical
findings and complete implementation dependencies. Missing staff cannot satisfy an
institutional requirement, but also cannot turn passing engineering into a defect.
Release and activation continue to use all applicable operation dependencies and
controls.

## Dashboard and generated status

The JSON dashboard exposes all 96 graph nodes, purpose-specific dependencies,
package state, KPI definitions, observation summaries and both implementation and
institutional readiness:

```sh
uv run --frozen alpha-governance-program --json
uv run --frozen alpha-governance-program --wave A
uv run --frozen alpha-governance-program --ready solo
uv run --frozen alpha-governance-program \
  --metric kpi.research_reproducibility_percent
```

After editing package state, regenerate the human view with `make program-status`.
The default program check compares it byte-for-byte with a deterministic render, so
stale counts, next-package prose and hand-edited findings fail validation. Current
state belongs only in the [generated status](program-status.md).

## KPI observations

The seven definitions cover clean build duration, required-test duration,
reviewed-commit-to-deployed-digest lead time, material incident rate, confirmed
data-quality defects, governed research reproducibility, and rollback-to-healthy
time. Each definition has one owner, unit, direction, aggregation, reporting window,
minimum sample count, bounded dimensions, automatic source event, producer packages
and `hard_gate_substitute = false`.

Producers emit JSONL schema version 1. Duration comes from UTC window timestamps;
ratio events retain numerator and denominator sufficient statistics. Each event is
bound to an immutable source revision, source run ID, credential-free HTTPS evidence
location and the exact allowed dimensions. Identical retries are idempotent;
conflicting duplicates, overlapping ratio windows, invalid units, non-finite values,
zero denominators and excessive observations fail closed.

Supply observations without changing repository state:

```sh
uv run --frozen alpha-governance-program \
  --observations path/to/automatic-observations.jsonl --json
```

Local CI observations stay under ignored `build/ci/`. Hosted CI retains its event
stream as a bounded artifact and embeds the exact revision, run ID and evidence URL.
Absent target observations report `insufficient_observations`; they are never
invented as zero or treated as hard-gate success.

## Governance references

The [development workflow](workflow.md) owns day-to-day evidence and validation.
The [quality-gate catalog](../architecture/operations.md#quality-gate-catalog) owns
QG01-QG15 definitions, and the [generated status](program-status.md) owns the active
implementation, readiness, finding and handover view. Detailed A08 finding closure
conditions remain in the adjacent machine-readable program record.

Rollback is a reviewed revert of the schema, reader, renderer, generated page and
automation changes together. Historical evidence is not relabeled. A08 does not
authorize deployment, release, activation, credentials, orders, venues, accounts,
capital or expanded risk authority.
