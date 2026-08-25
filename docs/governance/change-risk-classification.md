# Change-Risk Classification and Enforcement

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | A04 |
| Operating track | Solo bootstrap |
| Package status | Partial |
| Accountable owner role | Platform |
| Change risk | R0 governance tooling with package-specific QG12 and QG15 |
| Applicable gates | QG01, QG12, QG13, QG15 |
| Machine-readable policy | [Change-risk policy](change-risk-policy.toml) |

This package implements the blueprint's deterministic R0-R4 classifier. The TOML
policy is authoritative for allowed inputs, class mappings, gates, reviewer
groups, rollout modes, retention classes, retained samples, and open findings.
The Python checker validates that the policy cannot weaken blueprint minimums.

## Classification contract

Every change supplies all five dimensions. Missing or unknown values fail closed.
The classifier assigns each dimension a minimum class and returns their maximum:

```text
required class = max(capital at risk, blast radius, data/model materiality,
                     security privilege, reversibility)
```

An author may declare a higher class conservatively. A declaration below the
computed class is rejected rather than silently corrected. Conditional facts add
gates but never remove a class gate. When the declared class is higher, the final
gate set is the union of the computed class requirements and declared class
requirements:

- Computationally material R1 work adds QG10.
- Economically or risk-relevant R2 work adds QG07-QG08.
- Model- or trading-relevant R3 work adds QG06-QG08.
- R4 always requires QG01-QG15.

### Dimension levels

| Class | Capital at risk | Blast radius | Data/model materiality | Security privilege | Reversibility |
| --- | --- | --- | --- | --- | --- |
| R0 | Absent | Documentation only | None | None | Immediate revert |
| R1 | Absent | Research only | Research-local | Research-scoped | Reproducible recompute |
| R2 | Absent | Shared domain | Shared data/schema/library or candidate | Shared sensitive boundary | Compatibility window |
| R3 | Absent | Non-capital runtime | Production-serving | Non-production privileged control | Staged operational rollback |
| R4 | Present | Capital path | Capital decision | Production or market access | Capital/state reconciliation |

Capital exposure alone sets R4. A low value in another dimension cannot offset a
higher value. Classification does not grant source, data, credential, deployment,
venue, account, capital, activation, or risk authority.

## Class control mapping

| Class | Gates | Distinct review minimum | Rollout | Evidence retention class |
| --- | --- | --- | --- | --- |
| R0 | QG01, QG13 | One Code Owner | Fast lane | Source/governance record |
| R1 | QG01-QG06, QG13; conditional QG10 | Research owner plus independent peer | Reproducible batch; no production promotion | Governed research lifecycle |
| R2 | QG01-QG06, QG09-QG14; conditional QG07-QG08 | Code Owner plus independent data/model/domain reviewer | Merged result, compatibility replay, impact analysis | Shared-contract compatibility lifecycle |
| R3 | QG01-QG05, QG09-QG15; conditional QG06-QG08 | Code Owner, independent Platform/SRE, independent Security | Staging, failure injection, shadow or synthetic | Deployable-service lifecycle |
| R4 | QG01-QG15 | Domain Owner, independent Risk/Model Validation, independent Platform/SRE, independent Security/Compliance | Full certification, paper, shadow, bounded canary, signed activation, rehearsed rollback | Release, activation, and audit lifecycle |

The R3 and R4 mappings deliberately require distinct operational and security
review identities rather than leaving applicability to the author. R4 requires at
least four distinct merge approvers, at least three independent approvers, and at
least two distinct activation approvers. The author cannot satisfy an independent
review group. Reviewer identities are normalized with Unicode NFKC, surrounding
whitespace removal, and case folding before any distinctness or group assignment.

The retention classes are minimum semantic lifecycles:

- Source/governance evidence stays with repository and change history for the
  repository lifetime.
- Governed research evidence stays through candidate or experiment retirement and
  its applicable audit window.
- Shared-contract evidence stays until every consumer, migration, compatibility,
  rollback, and audit obligation closes.
- Deployable-service evidence stays through service and artifact retirement plus
  incident, recovery, and rollback obligations.
- R4 evidence is immutable through the release, strategy, activation, market-
  access, and applicable regulatory/audit lifecycle.

Later inventory and compliance packages may set longer jurisdiction-specific
durations; they may not shorten an open dependency, rollback, incident, legal, or
audit obligation.

## Hard controls and approval evidence

Point-in-time causality, immutable artifact identity, independent hard risk, and
kill capability are the four non-waivable live-capital controls. The approval
validator requires the original change input, reclassifies it under the
authoritative policy, and rejects a stale, altered, or caller-constructed decision
that does not match that result. Reviewer and waiver checks use only the
recomputed decision. The validator also rejects an R4 merge whenever a hard
control appears in the waiver set, duplicate reviewer identities, missing reviewer
groups, an author presented as independent, or fewer than the class minimum
approvals.

`validate_activation_approvals()` separately recomputes and binds the decision,
validates canonical identities and roles, and enforces the class activation
minimum. R4 therefore cannot pass repository-local activation validation with one
identity or two textual variants of the same identity.

Callers of `validate_merge_approvals()` must pass the classification facts through
the required `change=` argument together with the decision returned by
`classify_change()`. This binding is a repository-local integrity check; it does
not authenticate whether the input facts describe the exact proposed commit.

The current API still validates identities, role claims, and classification facts
supplied by a caller. The external forge remains authoritative for authenticated
identity, approval after the last push, protected-branch enforcement, and retained
exact-commit evidence. A05 will define the MR and SHA-bound evidence inputs; A04
does not pre-empt that separate package.

## Enforcement and repository evidence

`make change-risk-check` loads the policy, validates every class and control
boundary, and reclassifies the retained R0-R4 sample changes. The same command is
included in the root check, pre-commit, and hosted-CI definitions. Focused tests
cover success, mixed-dimension boundaries, capital escalation, conditional gates,
unknown values, declared downgrades, gate preservation during conservative
escalation, policy weakening, insufficient or canonically duplicate review
evidence, decision/input mismatch, author independence, activation dual control,
and R4 hard-control waivers.

Local success proves deterministic repository behavior only. It does not prove
that the hosted forge ran the exact commit or that unavailable independent roles
approved it.

## Migration, rollout, rollback, monitoring, and runbook

Rollout is additive repository governance. It introduces no schema, persisted
state, data migration, runtime service, deployment, activation, or executable
order path. The checker fails closed on malformed or weakened policy. The
external rollout closes only after the protected forge consumes classifier output
and exercises representative R0-R4 cases.

Rollback is a reviewed revert that preserves this package record and its findings.
Any replacement must still classify existing samples and cannot lower an active
change's class without new reviewed evidence. No dashboard, alert, production
monitor, or operator runbook changes are introduced; CI failure output is the
repository-local operational signal.

## Open findings

| Finding | Owner | Unavailable evidence | Closure condition |
| --- | --- | --- | --- |
| A04-F01 | Platform/CI | Hosted-CI execution and retained exact-commit result | The reviewed commit passes the change-risk job in the protected external forge and retains the result |
| A04-F02 | Platform | Protected-forge consumption and enforcement of classifier output | Representative R0-R4 exercises prove a downgrade, a single-approver R4 change, and an R4 hard-control waiver are blocked |
| A04-F03 | Security | Independent Security, SRE/promotion-control, and Independent Risk review | Named reviewers resolve findings and record commit-bound approval of the classifier and mappings |

These are not approvals or waivers. A04 remains partial until every finding
closes against the exact reviewed commit.

## Implementation boundaries and non-goals

The Python implementation is a cohesive `alpha_research.change_risk` subpackage.
Policy parsing, classification, and approval enforcement can be reviewed
independently without changing the stable public API or command:

- `change_risk/__init__.py` is the public compatibility facade.
- `change_risk/__main__.py` preserves the repository-check command entry point.
- `change_risk/models.py` owns immutable domain values and policy types.
- `change_risk/policy.py` parses TOML and validates the complete policy.
- `change_risk/classification.py` contains the pure highest-dimension classifier.
- `change_risk/approvals.py` enforces canonical distinct reviewers, activation
  dual control, and hard-control waivers.
- `change_risk/constraints.py` retains non-negotiable blueprint lower bounds
  separately from the mutable TOML policy.

The A04 epic should still be reviewed as `A04a` for policy and package
documentation, `A04b` for the classifier and approval validator, and `A04c` for
adversarial tests and automation integration. Every slice retains A04 and no
slice alone satisfies its repository-local evidence.

A04 does not implement the A05 MR template or evidence bundle, A06 inventories,
forge configuration, signed releases, artifact promotion, deployment, activation,
credentials, external systems, market access, capital, or expanded risk authority.
