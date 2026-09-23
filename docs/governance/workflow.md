# Development and release workflow

This repository is maintained by one founder. The workflow follows the actual
capability being built; a package catalog, role register, evidence bundle, or
institutional approval is not a prerequisite for ordinary development.

## Implement

1. State the behavior, affected data or interfaces, and a short reversal plan.
2. Change the implementation and its focused tests together. Preserve the
   existing typing, import organization, docstring, numerical, and temporal
   contracts. Assign module responsibilities according to the
   [orchestrator pipeline and library boundary](../coding_standards/README.md#orchestrator-pipelines-and-libraries).
   Review class ownership and reserve bare functions for actual orchestration;
   the checker does not yet enforce this rule. Migrate affected APIs with their
   callers and follow the [remaining OOP work](../roadmap/README.md#delivery-order-and-dependencies).
3. Use the four sections in the pull-request template: problem/change,
   affected scope, validation result, and risks/reversal. Add migration,
   benchmark, or operational detail only when the change needs it.
4. During development, run only the affected tests and static checks for faster
   feedback; record the exact commands and results in the validation section.
   Hosted CI runs the complete required lane before merge. `make check` remains
   the local command for reproducing that lane when a full local check is useful.

Cross-cutting choices may be recorded in a short ADR when they are expensive to
reverse. ADRs are explanatory records and are not approval or staffing gates.
The architecture checker validates only repository-local links.

Follow the [engineering guide](../coding_standards/README.md) for retained source
requirements and the [platform roadmap](../roadmap/README.md) for current work.
Keep secrets, private data, bulk research outputs and mutable operational state
outside Git; retain small provenance and release identities with durable output
references. Source access does not grant data, deployment, broker or capital
authority.

## Build a release

`make build` and `make wheel-smoke` build and test installation for development.
Release use remains blocked by [dependency admission](../architecture/dependency-admission.md#quantlib-restriction)
and the absence of a trusted release consumer. The diagnostic
`uv run --frozen alpha-governance-artifacts release-check` checks admission, then
rejects the absent consumer even if dependencies pass. It produces no artifact;
unsupported invocations return a usage failure. Development wheel builds remain
available under the existing allowance.

[MR11](../roadmap/README.md#delivery-order-and-dependencies) owns the first
trusted build/install consumer and must precede any deployed collector or
paper/shadow runtime. It verifies trusted origin and builder identity, exact
digests, provenance/inventory, safe archive members and configuration/state
compatibility before installation. Tests must reject tampering, unexpected
origins, unsafe paths, missing/unknown records and source/dependency mismatches.
Its runbook owns signing, identity rotation, registry retention and rollback.
Clearing the dependency restriction alone cannot supply this consumer.

Build once from the locked environment and retain one release record containing:

- commit and artifact digest;
- dependency lock and build command;
- configuration, model, and data references;
- target environment and explicit operating limits; and
- rollback artifact and state-compatibility result.

Promote the same built bytes and verify installation from outside the checkout.
Keep the release artifact and record for the operating lifetime and any applicable
retention requirement.

## Activate and operate

Deployment and trading operation are planned; there are no activation, monitoring
or stop commands in this repository yet. Add tested commands and venue-specific
thresholds to the strategy's runbook before following this section in operation.

The founder makes a separate, explicit activation decision for each actual
strategy or service. Trading is off by default. Before activation, verify safe
credential scope, venue and data entitlements, order/notional/exposure/loss
limits, restart reconciliation, and a tested stop-and-cancel path.

Use the [operations and security runbook](operations.md) for deployment,
monitoring, incident response, recovery, and deactivation. An alert must have a
defined safe response while the founder is unavailable.

## Growth and organizational controls

Preserve technical design detail as the repository adds assets, strategies,
packages and applications. The [platform design](../architecture/platform-design.md)
describes intended boundaries; implementing one strategy first does not limit
the eventual platform. Applications may have independent artifacts and release
cadences while sharing tested domain contracts and a supported development path.

Add people-dependent process when it has real participants: individual access and
review ownership for another contributor, credential and incident handover for an
operator, and explicit cross-team contracts when separate teams exist. Independent
approvals, formal review programs and segregation of duties are the lowest
speculative implementation priority. Onboarding can trigger this work at any
technical stage; it does not wait for every platform capability to finish.

Data correctness, accounting, runtime limits, reconciliation and recovery remain
part of the features they protect, including during founder-only operation.
Concrete external obligations apply when encountered.
