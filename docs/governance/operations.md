# Operations and security runbook

This runbook owns the implemented local MR06 installation lifecycle and the
requirements for later deployed strategies/services. Activation, operating
monitoring, venue stop/cancel and account recovery remain future capabilities.
Add the selected target, numeric limits and tested responses to the strategy's
runbook before operation. The repository does not claim live readiness.

The operating destination includes multiple strategy instances, accounts, venues
and asset classes. Quant development must deliver the initial OKX/Bitfinex spot
operating infrastructure before QR onboarding, using reference instances and
authorized test environments under the [platform roadmap](../roadmap/README.md).
Its commands, dashboards, default operational metrics and recovery procedures
must not wait for a selected QR strategy. QR later supplies strategy-specific
metrics, chart definitions and diagnostic thresholds through supported interfaces;
hard risk and activation authority remain independent. The
[platform design](../architecture/platform-design.md) describes the planned state,
execution and observability boundaries.

## Deploy

`make build` and `make wheel-smoke` verify the complete research development
artifact. The [QuantLib restriction](../architecture/README.md#dependency-and-release-boundaries)
still applies to that graph. MR06's independent collector/execution artifacts
have their own complete admitted closures and use the trusted lifecycle below.
Remote/production deployment and service startup require separate authority.

Build and verify one immutable artifact. Record its commit, digest, dependency
lock, configuration/model/data references, target environment, limits, and
rollback artifact. Keep credentials outside source control and grant only the
permissions needed by the process. Confirm state compatibility before restart.

## Trusted local installation

Owner: quant development. Target: a trusted single-user local Darwin arm64
workspace, standard-GIL CPython 3.14.7, uv 0.12.7 and OpenSSH Ed25519 signatures.
The installer is administrative governance tooling; operating applications do
not install their own dependencies. `packages/collector` and `packages/execution`
have separate locks and both depend on an exact `alpha-research-contracts`
version. The collector keeps market-data/storage functionality; the execution
artifact evaluates spot limit intents against existing exact risk/reference
contracts and suppresses submission. It is not an OMS or a venue adapter.

Provision an `InstallationPolicy` outside the untrusted registry, through a
trusted local configuration channel. Pin the absolute Python, uv and ssh-keygen
paths and SHA-256 values, target, permitted configuration/state schemas, and
`TrustedBuilder` public Ed25519 keys with explicit builder identity, origin,
allowed application distributions and UTC validity interval. A bundle cannot
add a key or change this policy. Protect the target and policy with local account
permissions; this scope does not provide hostile same-user process isolation.

Keep builder private keys outside source and release directories, with mode 0600.
OpenSSH signing uses the namespace `alpha-research-release-v1`. The builder owns
source/build and vulnerability evidence; the signature authenticates that
assertion, not an independent hosted builder or reproducible native dependency
build. For rotation, provision the replacement public key through the same trusted
channel, permit a bounded overlap, then remove the old key. Verification and
installed launches recheck current trust and expiry; removing a compromised key
also rejects its retained rollback releases. Rebuild/re-sign reviewed retained
inputs with the replacement identity rather than editing old manifests.

The supported command sequence is:

```sh
uv run --frozen alpha-governance-artifacts fetch \
  --repository /absolute/checkout --request /absolute/build-request.json \
  --policy /protected/target-policy.json --dependencies /absolute/verified-external-wheels
uv run --frozen alpha-governance-artifacts build \
  --repository /absolute/checkout --request /absolute/build-request.json \
  --policy /protected/target-policy.json --configuration /absolute/config.json \
  --dependencies /absolute/verified-external-wheels \
  --audit /absolute/new-attempt/audit.json --key /protected/builder-key \
  --registry /absolute/local-registry
uv run --frozen alpha-governance-artifacts verify \
  --release /absolute/local-registry/RELEASE_SHA256 --policy /protected/target-policy.json
uv run --frozen alpha-governance-artifacts install \
  --release /absolute/local-registry/RELEASE_SHA256 --policy /protected/target-policy.json \
  --target /absolute/operating-target
uv run --frozen alpha-governance-artifacts run \
  --target /absolute/operating-target --policy /protected/target-policy.json -- inspect
uv run --frozen alpha-governance-artifacts rollback \
  --release /absolute/local-registry/PRIOR_SHA256 --policy /protected/target-policy.json \
  --target /absolute/operating-target
```

These are parameterized commands, not authorization for a new deployment.
`ReleaseBuild` selects identity/origin/expiry and `ReleaseRuntime` selects
application, mode, target, shared-contract version and configuration/state
schemas. Execution uses `execution-admission-v1`; collector uses the existing
`CaptureConfig` schema `1`. Initial empty state uses `none-v1`; `--state PATH`
can bind an explicitly quiesced snapshot. The initial state envelope must not be
supplied by that directory. The application owns the meaning of a nonempty state
schema; a declared schema alone is not reconciliation or migration evidence.

`fetch` exports the locked application graph for the actual target and downloads
only matching immutable PyPI wheel URLs with verified hashes. No source build or
alternate index is used. A retained wheelhouse is reverified on reuse.

Each build runs the pinned scanner against every admitted root dependency and
preserves fresh JSON and scanner diagnostics at a new audit path. It rebuilds
the two selected local wheels once and verifies every supplied external wheel
against the frozen graph. Signatures cover retained source bytes, actual build
commands, both locks, policy, audit, wheel inventory, configuration and initial
state. Dirty source is recorded explicitly alongside the base commit. The
installer rejects signature/origin/key failures, stale policy, unknown records,
unsafe or duplicate archive paths, hooks, RECORD corruption, source/metadata
mismatch, incomplete dependency graphs and incompatible target/configuration/state.

Installation copies authenticated bytes into a new private slot, creates a clean
environment, installs offline with hashes, checks dependency metadata and calls
the installed application before selecting it. The active pointer changes
atomically. Failed stages remain for diagnosis; the previous environment/state
remain selected. Runs and installation share a nonblocking exclusive fence.
Use the `run` entrypoint to participate in this fence and retain the signed
configuration binding. Invoking a raw environment directly bypasses supervision
and is outside the qualified installation workflow.

Rollback verifies the prior release again and selects its code/configuration;
it preserves the latest mutable state. Only exact application, mode and state
schema compatibility is accepted. There is no automatic schema migration,
restoration over an active store or rewind of an order/fill ledger. MR07/MR10/MR13
must add their owned state readers and reconciliation before any such state is
resumed. MR04's workspace backup/restore still owns data, feature and job-store
restoration. Preserve registry bytes, public trust history, manifests, locks,
audit output and known-compatible rollback releases for the operating lifetime.
Back them up with the selected local workspace; never delete the sole retained
artifact or replace an active virtual environment in place.

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
and pending-commitment reconciliation is mandatory. Shared allocation/arbitration
and allocation reconciliation must additionally pass before the second
instance shares the account. Stop and recovery controls apply in either scope.

The dashboard/metric/query/alert infrastructure and default health, execution,
risk and account views are required before QR onboarding. Quant development tests
custom metric/chart registration and alert delivery with the reference workloads;
telemetry topology follows the launch capacity budget. Minimum monitoring and
tested recovery accompany each capability as it is built. Additional operators
and staffing-dependent approval/review programs follow actual organizational need
and remain separate from technical completion.

## Incident record

Record the time, artifact and configuration identity, observed condition, safe
action, affected orders or state, root cause, recovery result, and follow-up
test. A material incident requires a new release or activation review before
resuming the affected capability.
