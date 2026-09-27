# Operations and security runbook

This runbook owns the implemented local installation and paper account recovery
lifecycle and the requirements for later deployed strategies/services. The
public-paper workflow now emits a finite final monitoring view; continuous
operating monitoring and final deployed acceptance remain open. The
[paper-monitoring record](../roadmap/paper-monitoring.md) owns its integration
evidence and limits. Physical venue stop/cancel and other live operations are
[KIV](../roadmap/README.md#live-trading-kiv-and-reconsideration).
Add the selected target, numeric limits and tested responses to the strategy's
runbook before operation. The repository does not claim live readiness.

The operating destination includes multiple strategy instances, accounts, venues
and asset classes. Quant development must deliver the initial OKX/Bitfinex spot
paper operating infrastructure before QR onboarding, using reference instances
and public-input paper environments under the [platform roadmap](../roadmap/README.md).
Private authenticated venue qualification is KIV outside the bounded
paper-acceptance gate. Live procedures below are retained requirements for
reconsideration, not current delivery scope.
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
artifact includes independent spot admission, the durable paper OMS and shared
account controls. It has no venue submission transport.

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
restoration over an active store or rewind of an order/fill ledger. Managed paper uses its owned state reader, current grant and reconciliation
before resumption; incompatible schema migration is not automatic. MR04's workspace backup/restore still owns data, feature and job-store
restoration. Preserve registry bytes, public trust history, manifests, locks,
audit output and known-compatible rollback releases for the operating lifetime.
Back them up with the selected local workspace; never delete the sole retained
artifact or replace an active virtual environment in place.

## Local paper operations

Owner: quant development. Scope: trusted local macOS/Linux paper/shadow accounts,
cash-funded spot, configured instruments and strategies, with normalized paper
facts. OKX/Bitfinex labels do not certify private venue behavior. The
[command guide](../../src/applications/execute/README.md#local-operational-commands)
owns exact request fields; the [account journal](../../src/execution/README.md#account-operational-recovery)
owns phase, uncertainty and reconciliation semantics.

The following v2 commands retain the earlier normalized-fact engineering drills.
For managed public-paper deployment, use the [v3 procedure below](#managed-public-paper-activation-and-recovery)
with explicit deployment, authorization and owner claim.

For that v2 shared-account installation, select execution `paper` or `shadow`,
`config_schema=account-runtime-v1`, `state_schema=account-journal-v2`, and admit
both schemas in the independently provisioned installation policy. The initial
empty state creates a journal from signed configuration under the installation
fence. Upgrade/rollback validates a consistent copy of the latest journal through
the candidate installed reader before switching the release. A lost journal,
incompatible config/schema or nonregular state refuses the switch. The previous
`paper-runtime-v1` dedicated command remains a standalone development interface;
it is not silently admitted by this account installation contract.

Every installed account operation uses the same command, with a different typed
request file. The launcher fixes config and `state/accounts.sqlite3`; request
paths must be absolute, and caller config/journal overrides fail:

```sh
uv run --frozen alpha-governance-artifacts run \
  --target /absolute/account-target --policy /protected/account-policy.json -- account
uv run --frozen alpha-governance-artifacts run \
  --target /absolute/account-target --policy /protected/account-policy.json -- \
  account --request /absolute/operator-request.json
```

1. **Start:** verify the installed artifact and inspect state. Supply independent
   `quote` and complete `reconcile` requests, then the initial `control/startup`.
   Check the returned control status. This opens local admission; starting the
   selected runtime workload remains explicit. No command creates live authority.
2. **Stop or fault:** send `control/stop` or `control/fault` for the affected
   account. It blocks new exposure and retains all current economic state.
   Supply the local `alert_socket` when routing an operator alert. Inspect the
   durable control and pending/delivered/failed alert outcome independently.
   Stop an individual strategy with the existing `stop_instance` operation when
   account-wide protection is unnecessary.
3. **Cancel:** separately send `control/cancel`. It records requests and returns
   the physical order IDs. Supply subsequent identified order facts through
   `event`/`net_event`; a cancellation acknowledgement is not a terminal outcome.
   These actions never imply liquidation. Managed v3 paper reduction uses the
   separate `reduce_paper` request described below.
4. **Recover:** replay missing identified fills, fees, transfers and order facts,
   then supply a complete fresh account observation and current marks. A matching
   observation cannot clear unresolved sends, cancels, contradictions or legacy
   operator blocks. `control/restart` must name the current stop identity and
   rechecks freshness, funding and budgets. Selective instance restarts remain
   explicit. Inspect account and strategy attribution before resuming work.
5. **Back up:** stop producers and every selected account, then send `backup`
   with an absent external `backup_root`. The SQLite locks prevent a concurrent
   restart during capture. Retain its manifest digest with the compatible signed
   release, trust policy, configuration and local service backups.
6. **Restore:** send `restore` with that digest and an absent `restore_root`.
   The new workspace is verified before publication and remains stopped. It is
   not automatically selected by the installed target. Compare newer retained
   facts and authoritative observations before selection; an old backup cannot
   prove that no activity occurred after it. Never replace a running target's
   journal with a historical snapshot to implement rollback.
7. **Roll back code:** stop the account, retain the latest journal, and use the
   existing signed `alpha-governance-artifacts rollback` command. The candidate
   reader must accept the current state/config. Reconcile and explicitly restart
   through the newly selected compatible release. Code rollback preserves fills,
   late postings and stops; it does not restore old accounting bytes.

For standalone local development, the same request files run through
`alpha-execute account --config CONFIG --journal WORKSPACE/state/accounts.sqlite3
--request REQUEST`. The signed launcher is the trust boundary when installation
verification matters. The [reference consumer](../../tests/integration/consumers/runtime/account_operations.py)
generates concrete requests/results without hand-authored manifests.

The existing collector watchdog detects stalled receipt/persistence/market work,
heartbeat loss, invalid messages and bounded-queue/reconnect limits. Its parent
terminates the child before protection and local alert delivery. Paper account
workloads can supply `ProcessSupervisor.run(protect=...)` to persist the independent
account fault. Dedicated `run_live_paper` records a fault for capture/scheduler
failure before releasing its OMS fence. Disk failures remain visible even when
the failed write cannot record a block; process termination must precede recovery.
Alert failure never clears a hard control. Durable account controls and pending
orders survive restart; a new process must inspect and reconcile before admission.

The public-paper monitoring output is a finite end-of-invocation snapshot. Its
immutable receipt envelope, recovery call and dashboard files are described in
the [MR12 monitoring record](../roadmap/paper-monitoring.md) and
[telemetry guide](../../src/telemetry/README.md). It does not keep a background
monitor running or change the account when a diagnostic fails.

The local drills exercise real process termination, SQLite capacity exhaustion,
local datagram delivery/loss and fixture market/protocol faults. They reuse MR04
workspace/feature/job restoration and collector failure proofs. They do not
establish host-volume reliability, remote service disaster recovery, authenticated
private-stream reconnect, venue timeout behavior, remote alert acknowledgement,
deployment failover or production readiness. Private venue qualification remains
KIV outside paper acceptance. The
[MR10 record](../roadmap/README.md#mr10-delivery-and-acceptance)
retains the remaining integrated acceptance boundary.

## Managed public-paper activation and recovery

Use a fresh signed execution `paper` target with `config_schema=account-runtime-v1`
and `state_schema=account-journal-v3`. The independently provisioned policy must
admit both schemas. The execution/contracts wheel closure remains independent
of the collector and research distributions. The signed launcher supplies its
verified release digest and fixes configuration/state paths; installation grants
no exposure authority. Existing v2 commands remain engineering/legacy interfaces,
not a substitute for this managed operating entry point.

The [account command guide](../../src/applications/execute/README.md#managed-paper-activation-requests)
owns exact typed request fields. Each operation is one retained JSON request:

```sh
uv run --frozen alpha-governance-artifacts run \
  --target /absolute/paper-target --policy /protected/paper-policy.json -- account
uv run --frozen alpha-governance-artifacts run \
  --target /absolute/paper-target --policy /protected/paper-policy.json -- \
  account --request /absolute/operator-requests/operation.json
```

1. Install a compatible signed release, then submit `install_paper` with the
   disabled `PaperDeployment`. Inspect its immutable identity, stopped phase,
   absent authorization and owner, compatible releases and explicit state ABI.
2. Submit `authorize_paper` with an independently authored `PaperAuthorization`:
   exact deployment digest, instruments, cumulative simulated buy quantity/order
   count, maximum order notional and UTC start/expiry. The trusted local operator
   is the authorization channel; this is not a production credential or a
   separately signed approval system. Configuration is never a grant.
3. Supply a fresh independently sourced quote and complete reconciliation after
   the deployment stop. Submit `claim_paper` with a `restart` control naming that
   stop and a unique worker identity. Keep the returned generation token. A
   missing, expired, revoked, mismatched or stale token prevents new exposure.
4. Supply the claimed `InstalledPaperAccount` to `run_live_shared_paper` for the
   bounded OKX/Bitfinex input workload. Input/feature/policy bindings must match
   the deployment. The account owner rechecks actual time, freshness, generation,
   authorization, funding and risk at economic boundaries. Finite completion
   records an operational stop. Diagnostic failure does not retry execution.
5. To **block new exposure**, send `control/stop`. To **request cancellation**,
   separately send `control/cancel`. Requested/acknowledged cancellation retains
   commitments until the paper matcher produces its terminal outcome. Expiry
   and revocation also leave existing obligations and reservations intact.
6. To **request position reduction**, send `reduce_paper` with instance, quantity,
   a fresh observed quote, explicit sell limit and maximum fee. Accepted means
   an IOC sell reservation. Only subsequent eligible public liquidity can create
   fills. Stale/disconnected input, unknown outcomes, unreconciled state or
   insufficient owned inventory produce explicit refusal; partial/unfilled
   quantities are reported without claiming liquidation. Other strategies'
   inventory is never used to satisfy the request.
7. After failure, inspect retained facts and complete independent reconciliation.
   If physical order outcomes remain unresolved, use the retained current owner
   to drain existing obligations against fresh public data before replacement;
   expiry/revocation does not permit new orders but preserves this processing.
   Refresh quotes and explicitly claim a replacement generation while authority
   is valid. A new bounded grant may replace an expired/revoked one only while
   stopped and physical outcomes are settled; accepted standing orders retain
   their reservations. Prior IDs remain recorded and cumulative limits do not reset. Old
   workers and caller-invented lifecycle/fill events cannot commit managed effects.
8. For rollback, stop the workload and select a listed compatible signed release
   with the existing `rollback` command. Installation verifies the candidate
   reader against a consistent copy before switching code. It preserves the
   latest journal. Reconcile and claim through the selected release before
   resuming; old owner tokens bind the previous release/generation.

Workspace backup still requires all selected accounts to be explicitly stopped.
Restore verifies bytes into an absent destination and marks that staged copy
quarantined before publication. Historical copies are available for inspection,
not automatic managed activation; even a freshly matching local observation
cannot prove no later economics occurred. The supported local recovery boundary
is the latest retained journal plus its compatible signed code. Direct journal
replacement, loss of the latest journal, host-volume disaster recovery and
schema migration are not silently repaired or qualified by a backup.

The existing reference consumer can emit a stable account configuration and
workload identities for a local fixture drill:

```sh
uv run --frozen --no-editable python \
  tests/integration/consumers/runtime/public_paper.py \
  --config configs/live/okx-btc-usdt.json \
  --output /absolute/new-preparation --prepare --freshness-us 30000000
```

Build the two admitted releases against that exact account configuration, author
the deployment/grant using the returned identities, then use the same consumer's
`--launcher`, `--target`, `--policy`, `--account-config`, `--release`,
`--upgrade-release`, `--rollback-release`, `--deployment` and `--authorization`
options. All operating paths are absolute; target/output must be absent.
Use the same explicit `--freshness-us 30000000` selection when running this
signed reference fixture. It budgets the local signed-command round trips;
the ordinary fixture default remains 5 seconds. Freshness is an authored,
signed configuration/input assumption and must match throughout the workload.
The [MR13 record](../roadmap/paper-activation.md) retains concrete commands,
artifact identities, independently expected economics and qualification limits.
These fixture controls and public reference policies are engineering workloads,
not empirical strategy or profitability evidence.

For the reference account named `paper`, create separate stop and cancel requests
from the repository root using the public wire API:

```sh
uv run --frozen python - <<'PY'
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from execution import AccountControl, AccountExecutionRequest
from serialization import DomainCodec

root = Path("logs/paper-operator").resolve()
root.mkdir(parents=True, exist_ok=True)
for kind in ("stop", "cancel"):
    request = AccountExecutionRequest(
        action="control",
        control=AccountControl(
            identity=f"operator-{kind}-{uuid4().hex}", account_id="paper",
            kind=kind, at=datetime.now(UTC), reason="explicit operator request",
        ),
    )
    path = root / f"{kind}.json"
    path.write_bytes(DomainCodec().encode_json(request))
    print(path)
PY
```

Pass one returned absolute path to the signed `account --request` command above.
Inspect `control.status`, targeted order IDs and later order state. A successful
cancel request still needs the retained current worker and fresh eligible market
input to obtain terminal cancellation. For reduction, author
`PaperReductionRequest` with the inspected instance's owned quantity and current
quote/price/fee bounds, then submit `AccountExecutionRequest(action="reduce_paper",
reduction=request)`. The retained reference drill contains concrete examples and
their independent expected balances; do not reuse stale quote timestamps.

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

For a later authenticated venue operation, the owning runbook must stop new
orders, cancel where safe, preserve state and logs, and reconcile independent
venue facts before resuming. That venue qualification is KIV outside the current
paper-acceptance gate. If the founder is unavailable, a deployed process must
take its defined safe action automatically. Test stop, restart, backup/restore,
rollback, and reconciliation before increasing limits.

As strategies and accounts multiply, identify every event and alert by release,
strategy instance, account and venue where applicable. Reconcile both each
strategy's attributed activity and the actual account ledger; monitor aggregate
exposure, margin and pending orders across strategies. Define which failures stop
one instance, an account or all trading. A failed strategy must not disable shared
account protection or conceal another strategy's live orders.
For a first dedicated single-instance paper account, base cash/position/order
and pending-commitment reconciliation against independently supplied facts is
mandatory. This local paper contract does not require or establish private venue
access. Shared allocation/arbitration and allocation reconciliation must
additionally pass before the second instance shares the account. Stop and
recovery controls apply in either scope.

The local [dashboard/metric/query/alert interfaces](../../src/telemetry/README.md)
include configured exact thresholds, retained input/result bytes and explicit
local routes. The public-paper workflow writes a final local snapshot and exposes
monitoring failures in its result. The installed
[monitoring command](../../src/applications/execute/README.md#retained-monitoring)
can reopen configured telemetry without changing operating state. Socket status
means local datagram acceptance; it does not establish receiver processing or
human acknowledgement. Inspect pending/failed attempts and telemetry loss
separately from hard controls. Deployed routing and external venue/source-clock
qualification remain unqualified. The bounded activation/recovery evidence is
tracked in the [MR13 record](../roadmap/paper-activation.md); MR14 deployed
multi-instance operation and MR15 capacity remain separate work. Additional
operators and staffing-dependent approval/review programs follow actual
organizational need and remain separate from technical completion.

The dashboard/metric/query/alert infrastructure and default health, execution,
risk and account views are required before QR onboarding. Quant development tests
custom metric/chart registration and alert delivery with reference workloads;
telemetry topology follows the launch capacity budget. Minimum monitoring and
tested recovery accompany each capability as it is built. The local paper
consumer retains actual receiver observations separately from socket acceptance;
human acknowledgement and remote-service delivery remain untested.

## Incident record

Record the time, artifact and configuration identity, observed condition, safe
action, affected orders or state, root cause, recovery result, and follow-up
test. A material incident requires a new release or activation review before
resuming the affected capability.
