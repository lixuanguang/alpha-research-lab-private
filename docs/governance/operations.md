# Operations and security runbook

This runbook applies to a real deployed strategy or service. The repository
does not claim live readiness until the behavior below is implemented and
tested for the selected venue and environment.

## Deploy

Build and verify one immutable artifact. Record its commit, digest, dependency
lock, configuration/model/data references, target environment, limits, and
rollback artifact. Keep credentials outside source control and grant only the
permissions needed by the process. Confirm state compatibility before restart.

## Security controls

- Store secrets in the selected secret store or environment, rotate them, and
  never place values in source, logs, fixtures, or issue text.
- Grant separate read, research, deployment, broker, and emergency access as
  the actual system requires. Review access after changes and revoke unused
  credentials.
- Confirm data rights, venue permissions, account scope, and retention before a
  data source or broker is used. Keep dependency source, license, vulnerability,
  and integrity decisions in the dependency checks.
- Limit deployment privileges and keep a tested rollback artifact. Treat any
  dependency, credential, access, or entitlement issue as a release blocker
  until it is resolved or the affected capability is disabled.

## Activate

Keep trading disabled until the founder records the activation decision. Verify
feed freshness, clock and availability assumptions, order sizing, notional,
exposure, loss, and rate limits. Run a bounded paper or canary period with an
explicit duration and stop conditions. Keep risk enforcement outside strategy
decision logic.

## Monitor and stop

Alert on stale data, missing heartbeat, reject or error bursts, position or cash
mismatches, reconciliation breaks, and limit breaches. Retain orders, fills,
state transitions, and alert outcomes for the operating lifetime.

On an alert, stop new orders, cancel where safe, preserve state and logs, and
reconcile against the venue before resuming. If the founder is unavailable,
the process must take its defined safe action automatically. Test stop,
restart, backup/restore, rollback, and reconciliation before increasing limits.

## Incident record

Record the time, artifact and configuration identity, observed condition, safe
action, affected orders or state, root cause, recovery result, and follow-up
test. A material incident requires a new release or activation review before
resuming the affected capability.
