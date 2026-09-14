# Operations and security runbook

This runbook states requirements for a future deployed strategy or service.
Deployment, activation, monitoring, stop/cancel and recovery commands are not
implemented. Add the selected target, actual commands, numeric limits and tested
failure responses to the strategy's runbook before operation. The repository
does not claim live readiness.

The operating destination includes multiple strategy instances, accounts, venues
and asset classes. Start with the selected first deployment and add the relevant
operational behavior with each capability in the
[platform roadmap](../roadmap/README.md). The
[platform design](../architecture/platform-design.md) describes the planned state,
execution and observability boundaries.

## Deploy

Current `make build` and `make wheel-smoke` commands verify development artifacts.
The [QuantLib restriction](../architecture/README.md#dependency-and-release-boundaries)
blocks release use until its source-to-wheel uncertainty is
resolved. Passing development checks or deleting the allowance does not satisfy
source admission or remove that block.
The [R1 trusted consumer](../roadmap/README.md#r1-trusted-artifact-before-first-deployment)
is also required before an actual collector or paper deployment. Clearing the
dependency restriction alone does not implement artifact verification. MR 59
subsequently binds executable trading authority to the verified release.

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
The initial scope trusts founder-authored strategy code and tests logical
separation and final risk enforcement. It does not claim hostile-code isolation;
untrusted strategies require the actual privilege boundary described in the
[platform design](../architecture/platform-design.md#multi-strategy-netting-and-isolated-risk)
before admission.

## Monitor and stop

Alert on stale data, missing heartbeat, reject or error bursts, position or cash
mismatches, reconciliation breaks, and limit breaches. Retain orders, fills,
state transitions, and alert outcomes for the operating lifetime.

On an alert, stop new orders, cancel where safe, preserve state and logs, and
reconcile against the venue before resuming. If the founder is unavailable,
the process must take its defined safe action automatically. Test stop,
restart, backup/restore, rollback, and reconciliation before increasing limits.

As strategies and accounts multiply, identify every event and alert by release,
strategy instance, account and venue where applicable. Reconcile both each
strategy's attributed activity and the actual account ledger; monitor aggregate
exposure, margin and pending orders across strategies. Define which failures stop
one instance, an account or all trading. A failed strategy must not disable shared
account protection or conceal another strategy's live orders.
For a first dedicated single-instance paper account, base cash/position/order
and pending-commitment reconciliation is mandatory. MR 54 allocation/arbitration
and MR 55 allocation reconciliation must additionally pass before the second
instance shares the account. Stop and recovery controls apply in either scope.

Add dashboards, centralized telemetry and additional operators when the workload
needs them. Minimum health, financial monitoring and tested recovery accompany the
first live path. Staffing-dependent approval and review programs follow actual
onboarding and are a separate, lower-priority workstream.

## Incident record

Record the time, artifact and configuration identity, observed condition, safe
action, affected orders or state, root cause, recovery result, and follow-up
test. A material incident requires a new release or activation review before
resuming the affected capability.
