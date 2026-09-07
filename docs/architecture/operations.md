# Operations boundary

The repository currently contains research-domain foundations and development
checks. It does not implement a strategy runtime, broker session, risk gateway,
deployment service, or live monitoring system. The minimum behavior required
when one is introduced is recorded in the [operations and security runbook](../governance/operations.md).

For ordinary development, use the [development and release workflow](../governance/workflow.md):
make a focused change and run only its affected tests and static checks. Hosted
CI runs the complete required lane before merge; retain the release identity
and rollback information for a real deployment.

Before activation, the founder records a separate decision and verifies the
actual venue, data rights, credentials, limits, stop path, reconciliation, and
monitoring for that strategy or service. Numeric thresholds belong to the
selected target and are not invented by this repository-wide document.

The runbook is deliberately concrete about secrets, access, dependency issues,
deployment, stop, recovery, and incidents. It becomes an operational contract
only when the corresponding runtime behavior exists and its focused tests pass.
