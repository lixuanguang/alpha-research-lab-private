# Development workflow

This is the active workflow for repository implementation. The
[program record](program-governance.toml) is the source of package state; the
[generated status](program-status.md) is its human-readable view. Capability rules
belong in one linked contract and, where needed, its adjacent TOML policy.

## Implement a change

1. Start with the first implementation-ready package in the generated status, or
   identify the narrower affected capability for maintenance work. Follow only its
   technical dependency edges for implementation. Read its owning contract and
   relevant ADRs, the [shared coding standards](../coding_standards/README.md),
   and the applicable language guide before editing. For Python, use the
   [Python guide](../coding_standards/python.md) and its linked enforcement contract.
2. Make one coherent behavior change and update its contract, tests, compatibility,
   migration and reversal behavior when applicable. Identify affected consumers
   and owning build/test targets before editing; keep caller and build metadata
   changes with the implementation. Preserve the shared guide's
   [behavioral coverage requirements](../coding_standards/README.md#testing-standards)
   during refactors.
3. Use the four-section [PR template](../../.github/pull_request_template.md). Add
   migration, benchmark or operational sections only when their trigger applies.
   Ordinary changes do not create package evidence manifests or prose report packs.
4. Run focused checks during development, selected from the changed contract and
   build graph. Before merge, run `make check` with the default Bazel backend
   (`make ci-full`); this is the authoritative complete lane. The
   [root command map](../README.md#development-environment) lists focused checks.
   Documentation changes require `make architecture-check` for local links and
   anchors; coding-standard changes also require `make engineering-standards-check`.
   `make governance-check` runs all shared policy readers, including both, without
   the build/test graph. Changes to global lint or typing enforcement require
   checking the complete configured static scope.
5. When demonstrated implementation state changes, edit only
   `program-governance.toml`, run `make program-status`, and commit both files. The
   checker rejects a stale or hand-edited status page.

Local pre-commit hooks select checks from affected paths. Hosted pull requests run
the affected lane and the authoritative merged-result lane. CI event JSONL stays
under ignored `build/ci/` locally; hosted runs retain it as a 30-day artifact whose
events include the exact revision, run ID and evidence URL.

Record commands, scope and results in the PR's Validation result, including failed,
skipped or unexecuted checks. Scoped pytest, selected Bazel targets, static checks
or policy readers establish only their own results. If the complete lane has not
run, report it as pending; do not describe focused validation as a complete-lane
pass or merge readiness. Historical migration results are not evidence for the
current revision.

## Completion and authority

Implementation is complete when applicable technical checks pass and no technical
finding remains. The founder may accept that implementation without unavailable
signatures. Retained institutional findings and operation prerequisites stay visible
in the generated status but do not make completed engineering partial.

Release, activation, production credentials, executable orders and capital exposure
remain separate operations. Apply the [quality-gate catalog](../architecture/operations.md#quality-gate-catalog),
[change-risk policy](change-risk-classification.md), and operation-specific controls
when one of those operations is requested.

A joined, assigned reviewer activates only the handover queue for their domain.
The [operating model](domain-ownership.md#current-operating-policy) defines that
trigger. Until then, governance is `not_required`, not overdue.

## Source map

| Concern | Authority |
| --- | --- |
| Delivery graph, package state and KPI definitions | [Program record](program-governance.toml) |
| Human-readable status and finding IDs | [Generated status](program-status.md) |
| Package objectives and dependency expressions | [Implementation roadmap](../roadmap/README.md) |
| Implementation and refactoring rules | [Shared coding standards and language guides](../coding_standards/README.md) |
| Python source rules, static checks and design exceptions | [Engineering standards](../architecture/engineering-standards.md#python-standards-enforcement-contract) |
| Engineering vs handover authority | [Domain ownership](domain-ownership.md) |
| PR body and artifact-evidence rules | [Merge evidence](merge-evidence.md) |
| Risk classes and operation-aware gates | [Change-risk classification](change-risk-classification.md) |
| QG01-QG15 definitions and operation controls | [Quality and operations](../architecture/operations.md) |
