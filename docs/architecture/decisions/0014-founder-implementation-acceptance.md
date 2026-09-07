# ADR 0014: Founder implementation acceptance

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | A02 |
| Status | Founder accepted |
| Decision owner | platform |
| Operating domain | documentation_governance |
| Decision date | 2026-09-05 |
| Review date | 2026-12-04 |
| Supersedes | Organizational sequencing in the original solo-bootstrap overlay |
| Approval evidence | founder=@lixuanguang |

## Context

The founder requested that engineering completion be achievable while working
alone, with organizational governance completed only after relevant hires join.
Existing partial-only package records mix those two outcomes.

## Decision drivers

Show actual engineering progress, preserve technical failure gates, and avoid
requiring approvals from people who have not joined the organization.

## Considered alternatives

- Retain partial-only completion and individual deferrals: keeps unavailable
  staffing on the active delivery path.
- Remove governance validation: loses useful technical and artifact controls.
- Separate implementation and organizational acceptance: expresses both outcomes
  and allows the existing institutional profile to remain intact.

## Decision

Adopt the third alternative. The version-2 ownership register records real people
and effective role scopes. The shared resolver activates governance only for
domains with an active hire. Version-2 program records declare implementation
status and technical findings; governance status is derived from staffing.
Founder acceptance completes local engineering after applicable checks pass.
Institutional evidence records, release and activation requirements retain their
existing meaning. See the [development and release workflow](../../governance/workflow.md).

## Consequences

Missing independent reviewers no longer prevent implementation completion.
Technical failures still block it. Existing institutional findings are retained
without being presented as failed engineering. Final scoped handover is a later
step, and this decision does not claim that it has happened.

## Migration and rollout

The ownership and program readers were migrated before records, retain version-1
and version-2 program reading, and expose separate status fields in the existing
CLI. Step 2 migrated the PR evidence interface; step 3 revised dependency purposes
and reconciled C02/C03.

## Reversal plan

Revert the schema, readers and records together while retaining prior evidence.
Do not reinterpret founder acceptance as historical independent approval.

## Review and evidence

The founder authorized migration step 1 in the development task. Tests cover
solo completion, real technical failures, scoped active hires, invalid identities,
version compatibility and preservation of institutional operation boundaries.
Revisit when the relevant roles join or the operating scope changes.
