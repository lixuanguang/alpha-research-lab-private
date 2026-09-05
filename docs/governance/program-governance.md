# Program Dependency and KPI Governance

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | A08 |
| Operating track | Solo bootstrap |
| Implementation | Complete for the repository-local A08 contract |
| Governance | Not required until a relevant hire joins |
| Institutional acceptance | Partial |
| Accountable owner role | Platform |
| Risk class | R2 shared governance and measurement contract |
| Dependencies | A01-A07, provisionally satisfied with open findings |
| Applicable gates | QG01-QG06, QG09-QG14 |
| Machine-readable policy | [Program governance policy](program-governance.toml) |

## Contract and scope

A08 turns the implementation roadmap into a deterministic delivery graph and
defines the seven non-vanity program KPIs required by the blueprint. The roadmap
tables remain the single source of package identifiers, objectives, and dependency
expressions. Schema version 3 assigns every edge an `implementation`,
`operation/release`, or `team handover` purpose. Untyped historical expressions
remain implementation edges. The checker expands exact ranges, represents
conditional dependencies as explicit `any of` groups per purpose, rejects unknown
or duplicate packages, and fails on self-dependencies or cycles across the full
graph.

The version-3 program policy records demonstrated implementation state for
A01-C03. Packages without an explicit state remain `planned`; no empty package is
treated as implemented. States must be unique and in roadmap order, but they need
not form a contiguous prefix. This allows an independently implementable package
to be recorded without inventing completion for an unrelated service.
Each state separates `implementation_status`, `technical_finding_ids` and
`domain_id` from its retained institutional `status`, findings and deferred
evidence. Governance status and assigned reviewers are derived from the
[current operating policy](domain-ownership.md#current-operating-policy).
Completed implementation requires passing local evidence, no technical findings
and complete implementation dependencies. Operational/release and team-handover
edges do not enter the active delivery queue. Completion does not require an external approval or
an invented finding. A failed local result requires blocked implementation.

Version-1 records remain readable with their original partial/validated meaning.
Existing evidence manifests still prove their original institutional contract;
they are not rewritten as founder approvals. In JSON, `status` and `package_status`
remain compatibility fields for institutional acceptance; use the explicit
`implementation_status` and `governance_status` fields for current work. Unregistered
packages have planned implementation and no evaluated governance status.

## Delivery dashboard and readiness

The JSON interface exposes all 96 nodes, exact mandatory and any-of dependencies,
current status, evidence paths, open findings, KPI definitions, observed baseline
state, and the next package ready under institutional or solo-provisional rules.
Readiness is derived from the graph:

- Institutional readiness retains the compatibility rule that every dependency,
  independent of purpose, is `validated`.
- Solo/implementation readiness requires complete implementation of only its
  implementation dependencies. Pending
  organizational handover does not change technical readiness.
- A later package cannot make an earlier partial package validated and cannot
  hide a missing dependency behind a score.

Current dashboard queries include:

```sh
uv run --frozen alpha-governance-program --json
uv run --frozen alpha-governance-program --wave A
uv run --frozen alpha-governance-program --ready solo
uv run --frozen alpha-governance-program \
  --metric kpi.research_reproducibility_percent
```

The 19 registered A01-C03 states show complete local implementation and no active
governance requirement under the current founder assignment. C02 and C03 were
reconciled only after their code, goldens, focused checks, architecture contracts,
and retained evidence bundles were confirmed. Their institutional acceptance
remains partial. The active delivery graph now returns C04. Institutional
readiness remains empty.

## KPI and observation contract

The seven definitions are clean build duration, required-test duration,
reviewed-commit-to-deployed-digest lead time, material incident rate, confirmed
data-quality defects, governed research reproducibility, and rollback-to-healthy
time. Each has one accountable owner, unit, direction, aggregation, reporting
window, minimum observation count, bounded dimensions, automatic source event,
producer packages, baseline state, target state, and an explicit
`hard_gate_substitute = false` control.

Producers emit newline-delimited JSON version 1. Duration values are derived from
UTC window timestamps rather than accepted as manual measurements. Rate metrics
carry numerator and denominator sufficient statistics so aggregation does not
average ratios incorrectly. Every event is bound to a full source revision, a
source run ID, a credential-free HTTPS evidence location, and exactly the bounded
dimensions declared by its KPI. Identical retries are idempotent by event ID;
conflicting duplicates fail closed. Dashboard aggregation uses each KPI's rolling
reporting window, anchored to its latest eligible event. Ratio observations for
the same metric and dimensions must not overlap or exceed one reporting window,
preventing the same evidence interval from being counted twice. Non-finite,
negative, zero-denominator, unit-drift, timestamp, identity, cardinality, and
schema failures are rejected.

An observation file can be supplied without changing repository state:

```sh
uv run --frozen alpha-governance-program \
  --observations path/to/automatic-observations.jsonl --json
```

No eligible retained target observations exist yet. B05 emits local unretained
build/test events and configures hosted events; B06 defines remote build/test
producers, but its guarded target lane is not provisioned. Protected-forge evidence
remains open. The dashboard therefore reports
`insufficient_observations`, not zero. Baselines remain
`awaiting_target_observations`, and numeric targets remain
`pending_owner_approval`; fabricating either would be a control failure.
The synthetic A08 bundle is separately checked against an immutable package
profile binding its roadmap ID, accountable owner, every classification fact,
exact gate statuses, partial findings, and the prohibition on approvals, waivers,
or caller-added gates.

## Quality-gate evidence

| Gate | Repository-local evidence |
| --- | --- |
| QG01 | Ruff, formatting, strict mypy, and deterministic source tests cover the API and CLI |
| QG02 | Roadmap parsing, compact JSON, and fixture aggregation use pinned offline inputs and byte-stable ordering |
| QG03 | Success, boundary, invalid input, retry, filter, and command failures are tested |
| QG04 | Package identity, range expansion, acyclicity, ratio, time, and aggregation invariants fail closed |
| QG05 | Package evidence, source revisions, producer packages, event types, units, and dimensions remain linked |
| QG06 | Reproducibility has an explicit numerator/denominator contract; no research result is claimed |
| QG09 | Root, pre-commit, hosted CI, inventory, roadmap, evidence, and CLI consumers use the same validator |
| QG10 | Observation count is capped at 10,000 and aggregation is tested against the retained 1,000 ms repository budget |
| QG11 | Malformed graphs/events block reporting; identical retries are idempotent; reviewed Git revert remains available |
| QG12 | Repository paths are contained, evidence URLs reject credentials, revisions are immutable full digests, and Bandit scans source |
| QG13 | This contract documents scope, interfaces, status, ownership, limitations, rollout, rollback, and findings |
| QG14 | The deterministic JSON dashboard exposes owned KPI definitions, missing baselines, findings, and readiness without score substitution |

QG07 and QG08 are not applicable. A08 adds no cost/capacity model, economic
decision, executable limit, risk calculation, order path, or activation envelope.
QG15 remains external because the package is not deployed and protected
merged-result evidence is unavailable.

## Migration, rollout, rollback, monitoring, and runbook

Schema version 3 adds dependency purposes and non-contiguous state records while
retaining version-1 and version-2 program reading and observation schema version
1. Version 2 keeps its original contiguous-prefix and all-edge completion rules.
The ownership roster is evaluated at the current date; it is independent of the
observation snapshot's `as_of_date`. A later handover implementation will record
governance completion against reviewed evidence.

B06 remote-service acceptance is an operation/release dependency of B07, not a
prerequisite for implementing local dependency admission. B08 signed-artifact
acceptance is likewise an operation/release dependency of D01; isolated raw-data
contract implementation depends technically on C04. The operation-specific edges
preserve reproducible-build, checksum, entitlement, and release restrictions when
those operations are actually requested.

Rollout adds one repository validator to the root, pre-commit, and hosted-CI
interfaces. It does not connect a target telemetry backend or deploy/activate a
service. Rollback is a reviewed Git revert that retains prior graph, policy, and
evidence history. Current monitoring is the JSON dashboard and failing checker;
no production page, alert route, operator runbook, kill path, credential, venue,
account, capital, or risk authority is created.

## Review split plan

Review A08 as `A08a` for exact dependency semantics, package states, KPI
definitions, ownership, and findings; `A08b` for strict parsing, aggregation,
readiness, and CLI behavior; and `A08c` for adversarial tests, evidence, inventory,
and automation integration. Every slice retains A08, and no slice alone satisfies
its repository-local evidence.

## Required reviewers and open findings

The eventual R2 review requires a Code Owner plus an independent domain, data, or
model reviewer. Platform, SRE, Data Quality, and Quantitative Research approve the
metrics they own after representative target baselines exist.

| Finding | Owner | Unavailable evidence and closure |
| --- | --- | --- |
| A08-F01 | Platform | Connect automatic CI, deployment, incident, data-quality, research, and rollback events in target control planes; exercise every KPI and retain representative immutable baselines |
| A08-F02 | Domain Architecture | Named metric owners, Code Owner, and independent reviewer resolve findings and approve the exact graph, definitions, baselines, and numeric targets |
| A08-F03 | Platform/CI | Protected CI validates the exact merged result, publishes the commit-bound dashboard, and retains pass and blocking-mutation evidence |

These findings retain institutional acceptance obligations. They do not prevent
local implementation completion or make an unstaffed role an active blocker.

## Non-goals

- A08 itself implementing C01 or any later data, research, deployment,
  observability, incident, or rollback producer behavior; its state records do
  not absorb those packages.
- Creating a production dashboard service or accepting manually curated KPI values.
- Treating throughput, commit count, coverage percentage, PnL, Sharpe ratio, or a
  weighted score as a substitute for mandatory gate evidence.
- Claiming a wave exit, release, promotion, deployment, activation, market access,
  credentials, capital, or expanded risk authority.
