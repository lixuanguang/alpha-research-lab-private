# Solo-founder governance audit and migration plan

Audit: 2026-09-04, revision `e3a0efd08fdc128c9a0a83dc314645da5996133f`.
Status: step 1 implemented on 2026-09-05; steps 2-5 remain pending. Audit findings
below describe the recorded baseline. The
[current operating policy](../governance/domain-ownership.md#current-operating-policy)
and [ADR 0014](../architecture/decisions/0014-founder-implementation-acceptance.md)
document the implemented authority and completion rules.

Step 1 validation: the full CI lane passed in the pinned Nix development
environment, including pre-commit, 18 Bazel test targets, 534 Python tests and
one integration test. The program now reports complete local implementation for
the 17 registered packages, with governance not required under the founder roster.

**Recommendation: make engineering completion achievable by the founder now.
Make organizational governance completion a final, conditional handover step
activated when people actually join in the relevant roles.** If no hires join,
that step remains inactive indefinitely, without making completed work overdue
or blocking further development.

## Audit findings

This is a workflow and maintainability audit against the new operating requirement.
The P2 findings below concern material process friction and incorrect planning;
they are not claims of production incidents.

| Priority | Finding and evidence | Required change |
| --- | --- | --- |
| P2 | Solo completion is deliberately impossible. The [overlay](README.md#solo-bootstrap-execution-overlay) keeps work partial; the [program parser, line 515](../../tools/governance/src/alpha_research_governance/program_governance/registry.py#L515) rejects any other implemented status and requires deferred evidence and findings. All 17 registered packages remain partial, carrying 48 finding references. | Separate implementation completion from organizational acceptance. Missing hires must not be implementation defects. |
| P2 | Every PR pays the institutional documentation cost. The [evidence policy](../governance/merge-evidence-policy.toml) defines 29 mandatory fields. The [linter, line 55](../../tools/governance/src/alpha_research_governance/evidence/mr.py#L55) requires each one; [hosted CI, line 88](../../.github/workflows/ci.yml#L88) invokes it. | Replace the default with a short founder template and conditional sections. |
| P2 | A documentation-only policy change cannot work. [Risk policy parsing, line 364](../../tools/governance/src/alpha_research_governance/change_risk/policy.py#L364) hard-codes blueprint gates and reviewer groups. [Evidence acceptance, line 485](../../tools/governance/src/alpha_research_governance/evidence/manifest.py#L485) offers either partial-with-findings or accepted-with-approvals. | Migrate policy schemas, validators, tests and entry points together. |
| P2 | The delivery graph mixes capability dependencies with organizational completion. B07 depends on remote-execution B06; D01 depends on artifact-release B08. The [state parser, line 555](../../tools/governance/src/alpha_research_governance/program_governance/registry.py#L555) additionally requires a contiguous A01-onward prefix. [Research stages](research-program.md#platform-enablement-map) also inherit independent-report prerequisites. | Use actual technical dependencies for development and separately triggered operational/review requirements. |
| P2 | The dashboard is stale despite passing validation. The program CLI reports C02 and C03 as planned and recommends C02. Their contracts and bundles exist; [C03's successor statement](../architecture/financial-units.md#open-findings-and-successor) identifies C04. | Reconcile current implementation evidence before selecting the next package; stop duplicating status manually. |

There are 114 files under `docs/governance/evidence`. Many are useful fixtures,
signatures or source records; the count alone does not justify deleting them.
The maintenance problem is repeated narrative, findings and fixture expectations
being coupled to everyday package completion. Several validators require exact
historical finding IDs, so editing an open-findings table alone can break checks.

The existing overlay already permits some provisional progress, and local checks
can pass with missing approvals. This audit does not claim that every missing
review currently fails CI. The direct PR-body gate, rigid status model and
institutional definition of readiness are distinct sources of friction.

## Target workflow

| Concern | While you are the only developer | After relevant hires join |
| --- | --- | --- |
| Decision authority | Founder decides and merges after applicable automated checks; no independent approval count | Named owners and available qualified reviewers cover their assigned domains |
| Package completion | `implementation_status`: planned, in_progress, complete or blocked | Completed implementation stays complete unless an actual technical defect is found |
| Organizational acceptance | `governance_status = not_required`; activation condition is recorded once | pending during scoped handover, complete after the applicable review |
| ADRs | Short founder decision with scope, rationale, alternatives and reversal; founder acceptance is sufficient | Review material inherited decisions in the new owner's scope |
| Evidence | Tests, fixtures, source revision and CI result; brief human explanation | Add role-specific approval and operational evidence when applicable |
| Progress reporting | Technical blockers and the next useful capability | A separate handover queue for staffed roles |

Keep R0-R4 as impact classification, but resolve required actions from the impact,
operation being attempted and active role assignments. An R2 library change can
require compatibility tests without requiring an unavailable independent reviewer.
Split gates that mix technical evidence with human approval, especially QG06,
QG08, QG10, QG12 and QG15.

Release and activation remain separate decisions. This migration addresses
development and organizational process; it does not turn a successful build into
release authorization. Existing restrictions on credentials, executable orders and
capital exposure continue to apply to those operations, rather than making all
upstream engineering permanently partial.

## Reprioritize the gaps

| Work | Priority and trigger | Treatment |
| --- | --- | --- |
| Correctness, time/PIT semantics, units, accounting, reproducibility, supported-platform compatibility, secrets and dependency integrity | Current engineering work, where the capability uses them | Keep concrete tests and actionable defects; scope checks to the change and supported use |
| Independent Code Owner/domain/Security/SRE/model-review signatures; examples A01-F03, A03-F01/F03, A04-F03, A05-F02, A06-F03, A08-F02, B01-F01, B04-F01, B05-F01, B06-F01, B07-F01, B08-F01, C01-F01, C02-F01, C03-F01 | Relevant person joins, receives responsibility and is ready to perform the review | Consolidate into role handover requirements; no per-package missing-person blocker or rolling expiry |
| Forge enforcement and organization inventory attestations; examples A01-F01/F02, A03-F02, A05-F01 | Shared write access or actual organizational inventory exists | Keep CI and founder ownership now; activate multi-user enforcement when it can be exercised |
| Remote cache/execution, signing/registry drills, deployment/incident/rollback KPI baselines; examples B06-F02/F03, B08-F02/F03, A08-F01 | Service is needed or release/operation is requested | Remove from unrelated development prerequisites; execute operational checks when that capability is introduced |
| Mixed findings, including A07-F03, B07-F02/F03, C02-F02/F03 and C03-F02/F03 | Split by obligation | Separate unavailable sign-off from platform testing, actual data entitlement, license obligations and reference-data correctness; keep technical requirements relevant to current use |
| QuantLib B07-DEP-001 | Existing development admission expires 2026-10-04 | Keep one explicit dependency decision and its current restrictions. Source-to-wheel uncertainty is not a staffing gap; resolve/replace it or explicitly revise its admission before expiry |

Record a one-time mapping from old finding IDs to retained technical issues,
operational prerequisites or role handover requirements. Preserve old records in
history; describe changed applicability honestly instead of marking missing
evidence passed. A shared issue should have one record with multiple consumers.

## Migration sequence

The founder owns steps 1-4. These are implementation slices, not additional
approval layers. Keep each slice passing against its version of the contract.

1. **Make the operating model and completion rules explicit.** Add actual role
   assignments and their effective scope to the existing domain-ownership policy.
   Add versioned implementation/governance states to the program policy and a
   shared rule resolver. Preserve the current institutional policy as the future
   profile. Update the charter, solo overlay, operations readiness/done rules and
   ADR lifecycle so the new operating policy explicitly supersedes blueprint
   organizational sequencing for solo work. Update their validators together.
   Exit: a technically complete solo package can be complete with zero external
   approvals and zero invented findings; a real technical failure still blocks.

2. **Reduce the daily evidence requirement.** Make the default PR contain four
   sections: problem/change, affected scope, validation result, and risks/reversal.
   Generate classification metadata where possible. Add migration, benchmark or
   operational sections only when applicable. No special per-package manifest
   is needed for an ordinary documentation change. Update the PR template,
   evidence policy/models/linter and hosted workflow atomically. Give founder
   implementation evidence a distinct acceptance meaning; do not reinterpret old
   institutional `accepted` bundles. Keep SHA/digest verification for artifacts
   that rely on it. Exit: a four-section founder PR passes its real CI path.

3. **Rebuild the active delivery queue around technical dependencies.** Extend
   graph edges with purpose: implementation, operation/release or team handover.
   Remove the contiguous-prefix requirement while retaining unknown-ID, cycle
   and missing-technical-dependency checks. Keep the 96 package IDs for reference.
   Reconcile C01-C03 against their current code, fixtures and focused checks;
   migrate only demonstrated implementation, then recommend C04 if those checks
   support it. Review B06→B07 and B08→D01 explicitly: remote-service acceptance
   must not block local dependency management, and signed-release acceptance must
   not block isolated raw-data implementation. Preserve required reproducible
   builds, checksums and data-access conditions. Update research-stage entry rules
   so technical validation can progress before independent institutional review.
   Exit: the dashboard's next step follows the actual technical graph.

4. **Consolidate documentation and evidence, then resume delivery.** Keep one
   short active workflow page, one program/status source and one contract per
   capability. Replace repeated gate tables, non-goals and open-review narratives
   with links. Render status/findings from the authoritative records. Keep small
   adversarial test fixtures; move fixture-only bundles into test data when
   practical, updating their consumers. Store newly generated logs in CI artifacts
   with revision/run references, retaining records required for reproducibility
   or an active dependency admission. Update Make, pre-commit, Bazel data targets,
   CI policy/runner and tests to consume the same rules. Local hooks should run
   relevant checks; the full lane retains technical coverage. Exit: ordinary
   changes stop creating parallel prose evidence packs. Continue C04 onward and
   the first reproducible research workflow without organizational closeout.

5. **Complete organizational governance only after relevant hires join.** This
   is the final conditional handover step. Activate it for the staffed scope,
   as described below. It is not a prerequisite for steps 1-4 or unrelated
   ongoing engineering, and it has no deadline while its hiring trigger is false.

Primary implementation surfaces are `program_governance/{models,registry}.py`,
`change_risk/{constraints,policy,classification,approvals}.py`,
`evidence/{models,policy,mr,manifest,package}.py`, ownership/ADR validators and the
adjacent TOML contracts. These modules live under
`tools/governance/src/alpha_research_governance/`. Also migrate package-specific
profiles that pin `partial` and exact finding IDs, plus compatibility entry points
under `src/alpha_research/`. Do not turn off all governance tests to achieve this.

Use readers that understand the new schema before migrating records. Update
writers/CLI consumers and then retire compatibility support once no consumer
needs it. Revert a migration slice with its matching policies and readers if it
breaks the normal development path; retain the prior records throughout.

## Hiring trigger and final handover

The trigger is an actual joined person with a named role, assigned domain and
working access, recorded by the founder. A planned hire, vacant title or second
person in an unrelated role does not activate every review group.

| Joined role | Handover scope |
| --- | --- |
| Engineer or platform owner | Owned code/contracts, build/CI and relevant shared-access controls |
| Researcher or model validator | Research design, reproduction and model assumptions; independent validation only where the reviewer is qualified and was not the author |
| SRE or security specialist | Operational/access boundaries and applicable recovery or security controls |
| Risk or compliance specialist | Applicable risk/control obligations within the person's assigned remit |

The new owner reviews the current baseline and material unresolved issues for
that scope, with deeper historical review where it affects current behavior.
Do not require reapproval of every historical commit in A→L order. Record one
handover acceptance against the reviewed baseline and start prospective review
rules for that scope. Existing evidence supports the review; it is not rewritten
to imply an earlier independent approval.

Full multi-layer governance becomes complete only when the necessary distinct
roles are staffed, the scoped handovers finish and applicable controls are
exercised. The first engineering hire cannot stand in for every specialist.
If a role later becomes vacant, reopen only the obligations requiring that role;
do not revert completed implementation to partial.

## Verification and completion criteria

The audit ran the program dashboard and five existing focused tests covering
partial-status enforcement, status overclaim rejection, mandatory PR fields,
required partial findings and solo validation prohibition: **5 passed**. Their
success confirms that the current restrictions are intentional and tested.
No hosted branch settings, external approvals or full domain correctness were
revalidated in this audit.

Verify the migration with behavioral cases: a solo R2 change completes without
outside approval; a failed technical prerequisite still blocks; a concise PR
passes; a hire activates only the assigned review scope; an unstaffed domain
stays inactive; release operations cannot inherit development-only acceptance;
and the dashboard agrees with the reconciled package state. Replace assertions
that freeze historical counts/finding IDs with these outcomes, retaining artifact
tamper and technical-boundary tests. Run the repository's required full lane once
the affected focused checks pass.

The migration is complete when everyday work has one concise change record,
technically complete packages show complete, the next task follows real technical
dependencies, and organizational completion appears only in the hiring-triggered
handover queue. The separate Python coding-standards migration remains unchanged;
coordinate overlapping module edits without making it a new governance blocker.
