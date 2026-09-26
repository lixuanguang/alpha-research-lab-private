# Development and release workflow

This repository is maintained by one founder. The workflow follows the actual
capability being built; a package catalog, role register, evidence bundle, or
institutional approval is not a prerequisite for ordinary development.

The [platform roadmap](../roadmap/README.md#infrastructure-completion-before-qr-onboarding)
requires quant development to complete the initial OKX/Bitfinex spot stack before
QR onboarding. Quant development authors reference research/runtime consumers and
qualifies their public extension points; accepted QR strategies are not delivery
prerequisites. The final handoff demonstrates new strategy/study/metric/chart
content without changes to shared infrastructure. This policy changes planned
delivery, not current capability or trading authority.

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

`make build` and `make wheel-smoke` retain the complete research development
environment. Its QuantLib convention adapter remains restricted by
[dependency admission](../architecture/dependency-admission.md#quantlib-restriction).
`alpha-governance-artifacts release-check` still refuses release of that whole
graph; deleting an allowance cannot make it admissible.

[MR06](../roadmap/README.md#mr06-delivery-and-acceptance) adds separate
`alpha-research-contracts`, `alpha-research-collector` and
`alpha-research-execution` wheels. The two applications have independently pinned
locks and exact shared-contract versions. Their actual metadata closures must
pass the existing full admission policy and a fresh complete vulnerability scan;
an omitted dependency, unknown artifact or selected development-only package
fails. This is a genuine packaging boundary, not a release exemption for the
research graph. Feast and ClearML retain their independently locked worker
environments and existing wire-version checks.

The administrative `alpha-governance-artifacts` command now builds, signs,
verifies, installs and rolls back these operating releases. The initial target
is local Darwin arm64, standard-GIL CPython 3.14.7. Its signed record binds actual
source bytes (including uncommitted changes separately from the base commit),
build commands, root/operating locks, policy, audit, complete wheel inventory,
configuration and initial state. An independently provisioned trust policy pins
builder keys, permitted origins, target tools and compatible schemas. Verification
checks signatures, archive/RECORD safety, exact metadata dependency closure,
local source correspondence and compatibility before offline installation.
The [operating runbook](operations.md#trusted-local-installation) owns commands,
signing, rotation, retention and state-preserving rollback. Installation alone
does not start a service or grant trading authority.

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

Production deployment and trading activation remain unqualified. The
[local paper runbook](operations.md#local-paper-operations) owns implemented account
stop, cancel-request, reconciliation and recovery commands. Add venue-qualified
responses and operating thresholds before following this section in production.

Implement and qualify deployment, authorization, limits, stop/cancel and recovery
machinery with reference paper/shadow and authorized venue-test workloads before
QR onboarding. Completion of that infrastructure does not require an empirically
selected strategy or live-capital experiment. A real strategy's qualification,
deployment and activation are subsequent decisions using the completed machinery.

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
describes intended boundaries; engineering reference strategies qualify the
initial stack without limiting later QR content. Applications may have independent
artifacts and release cadences while sharing tested domain contracts and a supported
development path.

Add people-dependent process when it has real participants: individual access and
review ownership for another contributor, credential and incident handover for an
operator, and explicit cross-team contracts when separate teams exist. Independent
approvals, formal review programs and segregation of duties are the lowest
speculative implementation priority. Staffing can trigger these organizational
controls independently of technical delivery. QR's platform handoff follows the
roadmap's mandatory infrastructure gate; adding an organizational role does not
mark that technical work complete.

Data correctness, accounting, runtime limits, reconciliation and recovery remain
part of the features they protect, including during founder-only operation.
Concrete external obligations apply when encountered.
