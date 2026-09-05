# Development workflow

This is the active workflow for repository implementation. The
[program record](program-governance.toml) is the source of package state; the
[generated status](program-status.md) is its human-readable view. Capability rules
belong in one linked contract and, where needed, its adjacent TOML policy.

## Implement a change

1. Start with the first implementation-ready package in the generated status, or
   identify the narrower affected capability for maintenance work. Follow only its
   technical dependency edges for implementation.
2. Make one coherent behavior change and update its contract, tests, compatibility,
   migration and reversal behavior when applicable.
3. Use the four-section [PR template](../../.github/pull_request_template.md). Add
   migration, benchmark or operational sections only when their trigger applies.
   Ordinary changes do not create package evidence manifests or prose report packs.
4. Run focused checks during development. Before merge, run `make check`; this is
   the authoritative complete lane. `make governance-check` runs the shared policy
   readers without the build/test graph.
5. When demonstrated implementation state changes, edit only
   `program-governance.toml`, run `make program-status`, and commit both files. The
   checker rejects a stale or hand-edited status page.

Local pre-commit hooks select checks from affected paths. Hosted pull requests run
the affected lane and the authoritative merged-result lane. CI event JSONL stays
under ignored `build/ci/` locally; hosted runs retain it as a 30-day artifact whose
events include the exact revision, run ID and evidence URL.

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
| Engineering vs handover authority | [Domain ownership](domain-ownership.md) |
| PR body and artifact-evidence rules | [Merge evidence](merge-evidence.md) |
| Risk classes and operation-aware gates | [Change-risk classification](change-risk-classification.md) |
| QG01-QG15 definitions and operation controls | [Quality and operations](../architecture/operations.md) |
