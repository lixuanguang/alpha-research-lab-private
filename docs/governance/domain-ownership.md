# Domain Ownership and Independent Review

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | A03 |
| Operating track | Solo bootstrap |
| Package status | Partial |
| Accountable owner role | Platform |
| Risk class | R0 governance change |
| Applicable gates | QG12, QG13 |
| Machine-readable policy | [Domain ownership register](domain-ownership.toml) |

The register is authoritative for path ownership, required review roles,
independent-review roles, escalation roles, forge enforcement, and open findings.
The root `CODEOWNERS` file must mirror its ordered patterns and principals exactly.
The ownership checker rejects mapping drift, missing required domains, role
conflicts, and any non-ignored repository path without an owner.
Catch-all patterns are prohibited because they would make the configured
`unmatched_path_policy = "reject"` ineffective. Root files are enumerated
explicitly, so a new root file or top-level domain fails closed until ownership is
recorded deliberately.

## Review and escalation policy

- The accountable role owns contract clarity, compatibility, tests, operations,
  and the disposition of findings for its domain.
- Every required review role must be represented before institutional acceptance.
  A role listed as independent must be distinct from the accountable role, and
  the change author may not satisfy it.
- The last matching `CODEOWNERS` pattern determines routing. Narrow security paths
  intentionally follow broader platform paths so their rule takes precedence.
- An unavailable owner or unresolved disagreement escalates to the ordered roles
  in the register. Escalation cannot lower the risk class, waive a hard control,
  or substitute the author for an independent reviewer.
- Source visibility and Code Owner status grant no data entitlement, credential,
  deployment, activation, venue, account, capital, or risk authority.

The current `@lixuanguang` principal is the real solo-maintainer routing identity,
not evidence of independent review. It must be replaced by provisioned role
principals when the organization establishes the team-based operating model.

## Enforcement and evidence

`make ownership-check` validates the register, `CODEOWNERS`, role separation, and
coverage of tracked plus non-ignored files. Pre-commit and hosted CI invoke the
same command. Local success proves policy consistency only; protected-branch
configuration, principal resolution, review identity, and approvals live in the
external forge and remain pending in A03-F01 through A03-F03.

Rollout is additive repository governance. External closure provisions the exact
roles, updates principals, enables Code Owner review and approval after the last
push on protected `main`, and exercises representative protected paths. Rollback
is a reviewed revert that preserves this package record and its findings. A03
changes no schema, data, state, runtime, deployment, monitoring, or runbook.

## Review split plan

Because the complete A03 epic exceeds the preferred 400-line review target, it
should be reviewed as `A03a` for the register, policy, and `CODEOWNERS`, followed
by `A03b` for the checker, adversarial tests, and automation integration. Both
slices retain A03 as their package; neither alone satisfies its local evidence.

## Non-goals

A03 does not implement A04 risk classification, A05 evidence bundles, A06
inventories, B01 target directories, production RBAC, secrets, deployment,
activation, market access, or trading authority. It remains partial until all
findings close with commit-bound external evidence.
