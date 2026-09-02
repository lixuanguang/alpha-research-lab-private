# Program Dependency and KPI Governance

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | A08 |
| Operating track | Solo bootstrap |
| Package status | Partial |
| Accountable owner role | Platform |
| Risk class | R2 shared governance and measurement contract |
| Dependencies | A01-A07, provisionally satisfied with open findings |
| Applicable gates | QG01-QG06, QG09-QG14 |
| Machine-readable policy | [Program governance policy](program-governance.toml) |

## Contract and scope

A08 turns the implementation roadmap into a deterministic delivery graph and
defines the seven non-vanity program KPIs required by the blueprint. The roadmap
tables remain the single source of package identifiers, objectives, and dependency
expressions. The checker expands exact ranges, represents conditional asset
dependencies as explicit `any of` groups, rejects unknown or duplicate packages,
and fails on self-dependencies or cycles.

The program policy records implementation state only for A01-B06. Packages without
an explicit state remain `planned`; no empty package is treated as implemented.
Every partial dependency records passing repository-local evidence, its retained
finding IDs, and only the deferred evidence classes permitted by the solo-bootstrap
overlay. A partial package is never reported as validated or wave-complete.

## Delivery dashboard and readiness

The JSON interface exposes all 96 nodes, exact mandatory and any-of dependencies,
current status, evidence paths, open findings, KPI definitions, observed baseline
state, and the next package ready under institutional or solo-provisional rules.
Readiness is derived from the graph:

- Institutional readiness requires every dependency to be `validated`.
- Solo readiness accepts a `partial` dependency only when its repository-local
  status is `passed` and its remaining evidence is explicitly external,
  organizational, independent, qualified, or target-environment evidence.
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

With B06 repository-local evidence present, B01-B06 remain `partial` and the next
solo-provisionally ready package is B07. C01 is independently ready because its
roadmap dependencies stop at B05. Institutional readiness remains empty because
none of the provisional A01-B06 states is validated.

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

Schema version 1 is additive and has no database, runtime state, generated client,
or existing observation consumer to migrate. B01c and B02-B06 add their partial
package states without changing graph or observation schemas. Future
incompatible graph or event changes require a versioned compatibility window and
retained old readers.

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

These findings are not waivers or approvals. A08 remains partial until all close.

## Non-goals

- Implementing B07 or any later build, data, research, deployment, observability,
  incident, or rollback producer package.
- Creating a production dashboard service or accepting manually curated KPI values.
- Treating throughput, commit count, coverage percentage, PnL, Sharpe ratio, or a
  weighted score as a substitute for mandatory gate evidence.
- Claiming a wave exit, release, promotion, deployment, activation, market access,
  credentials, capital, or expanded risk authority.
