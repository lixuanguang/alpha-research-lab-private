# Development and release workflow

This repository is maintained by one founder. The workflow follows the actual
capability being built; a package catalog, role register, evidence bundle, or
institutional approval is not a prerequisite for ordinary development.

## Implement

1. State the behavior, affected data or interfaces, and a short reversal plan.
2. Change the implementation and its focused tests together. Preserve the
   existing typing, import organization, docstring, numerical, and temporal
   contracts.
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

## Build a release

Build once from the locked environment and retain one release record containing:

- commit and artifact digest;
- dependency lock and build command;
- configuration, model, and data references;
- target environment and explicit operating limits; and
- rollback artifact and state-compatibility result.

Verify installation from outside the checkout. Keep the release artifact and
record for the operating lifetime and any applicable retention requirement.

## Activate and operate

The founder makes a separate, explicit activation decision for each actual
strategy or service. Trading is off by default. Before activation, verify safe
credential scope, venue and data entitlements, order/notional/exposure/loss
limits, restart reconciliation, and a tested stop-and-cancel path.

Use the [operations and security runbook](operations.md) for deployment,
monitoring, incident response, recovery, and deactivation. An alert must have a
defined safe response while the founder is unavailable.
