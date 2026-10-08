# Operations and security runbook

This runbook owns the implemented local installation and paper account recovery
lifecycle and the requirements for later deployed strategies/services. The
public-paper workflow emits a finite final monitoring view; the supervised local
deployment also samples account and instance reports while its services run.
Physical venue stop/cancel and other live operations are
[out of scope](../roadmap/overview.md#live-trading-kept-in-view).
Add the selected target, numeric limits and tested responses to the strategy's
runbook before operation. The repository does not claim live readiness.

The operating destination includes multiple strategy instances, accounts, venues
and asset classes. Quant development must deliver the initial OKX/Bitfinex spot
paper operating infrastructure before QR onboarding, using reference instances
and public-input paper environments under the [platform roadmap](../roadmap/overview.md).
Private authenticated venue qualification is out of scope. Live procedures below are retained requirements for
reconsideration, not current delivery scope.
Its commands, dashboards, default operational metrics and recovery procedures
must not wait for a selected QR strategy. QR later supplies strategy-specific
metrics, chart definitions and diagnostic thresholds through supported interfaces;
hard risk and activation authority remain independent. The
[platform design](../architecture/platform-design.md) describes the planned state,
execution and observability boundaries.

## Deploy

`make build` and `make wheel-smoke` verify the complete research development
artifact under the [dependency and release boundaries](../architecture/overview.md#dependency-and-release-boundaries).
The independent collector and execution artifacts
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
OpenSSH signing uses the namespace `alpha-research-release`. The builder owns
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
schemas. Execution uses `execution-admission`; collector uses the existing
`CaptureConfig` schema `1`; paper services use `paper-services` with state
schema `none`, and `--candidates DIR` signs that directory's candidate bundles
into the release; `--extensions DIR` builds, admits and signs the external extension
projects in that directory. An installed paper services target runs `deployment`,
`deployment-check` and `deployment-control`; the launcher binds the signed
configuration and candidates and bounds a run by the supervisor's duration plus
60 seconds. Installation runs `deployment-check` before selecting the release. Initial empty state uses `none`; `--state PATH`
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
before resumption; incompatible schema migration is not automatic. Workspace backup/restore owns data, feature and job-store
restoration. Preserve registry bytes, public trust history, manifests, locks,
audit output and known-compatible rollback releases for the operating lifetime.
Back them up with the selected local workspace; never delete the sole retained
artifact or replace an active virtual environment in place.

## Local paper operations

Owner: quant development. Scope: trusted local macOS/Linux paper/shadow accounts,
cash-funded spot, configured instruments and strategies, with normalized paper
facts. OKX/Bitfinex labels do not certify private venue behavior. The
[command guide](../packages/execute-application.md#local-operational-commands)
owns exact request fields; the [account journal](../packages/execution.md#account-operational-recovery)
owns phase, uncertainty and reconciliation semantics.

An installed account target is a signed execution `paper` or `shadow` release with
`config_schema=account-runtime` and `state_schema=account-journal`, and the
independently provisioned installation policy admits both schemas. The initial
empty state creates a journal from signed configuration under the installation
fence. Upgrade/rollback validates a consistent copy of the latest journal, including
every history table, through the candidate installed reader before switching the
release. A lost journal, incompatible config/schema or nonregular state refuses the
switch. The dedicated `paper-runtime` command remains a standalone development
interface; it is not admitted by this account installation contract. Activation,
grants and owner claims follow the
[managed procedure below](#managed-public-paper-activation-and-recovery).

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
   `quote` and complete `reconcile` requests, then activate and claim the account
   through the managed procedure below. Starting the selected runtime workload
   remains explicit. No command creates live authority.
2. **Stop or fault:** send `control/stop` or `control/fault` for the affected
   account. It blocks new exposure and retains all current economic state.
   Supply the local `alert_socket` when routing an operator alert. Inspect the
   durable control and pending/delivered/failed alert outcome independently.
   Stop an individual strategy with the existing `stop_instance` operation when
   account-wide protection is unnecessary.
3. **Cancel:** separately send `control/cancel`. It records requests and returns
   the physical order IDs. Supply subsequent identified order facts through
   `event`/`net_event`; a cancellation acknowledgement is not a terminal outcome.
   A terminal `net_event` states its cause: `cancelled_on_request` confirms that a
   pending request took effect and keeps the parent's unaffected strategy children
   for reissue, while `cancelled` or `reconcile_cancelled` ends them. A parent whose
   outcome is `unknown` can only end them; a `venue_test` account accepts no
   `cancelled_on_request`.
   These actions never imply liquidation. Managed paper reduction uses the
   separate `reduce_paper` request described below.
4. **Recover:** replay missing identified fills, fees, transfers and order facts,
   then supply a complete fresh account observation and current marks. A matching
   observation cannot clear unresolved sends, cancels, contradictions or earlier
   operator blocks. `control/restart` must name the current stop identity and
   rechecks freshness and funding. A strategy that price moves alone took over its
   ceiling does not block the restart: its waiting buys, like any residual whose
   quote is stale or whose limit drifted beyond the price bound, stay visible
   portfolio residuals, and it can still sell but cannot buy. Selective instance
   restarts remain explicit. Inspect account and strategy attribution before
   resuming work.
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
the [telemetry guide](../packages/telemetry.md). It does not keep a background
monitor running or change the account when a diagnostic fails.

The local drills exercise real process termination, SQLite capacity exhaustion,
local datagram delivery/loss and fixture market/protocol faults. They reuse
workspace, feature and job restoration and collector failure proofs. They do not
establish host-volume reliability, remote service disaster recovery, authenticated
private-stream reconnect, venue timeout behavior, remote alert acknowledgement,
deployment failover or production readiness. Private venue qualification is
out of scope.

## Managed public-paper activation and recovery

Use a fresh signed execution `paper` target with `config_schema=account-runtime`
and `state_schema=account-journal`. The independently provisioned policy must
admit both schemas. The execution/contracts wheel closure remains independent
of the collector and research distributions. The signed launcher supplies its
verified release digest and fixes configuration/state paths; installation grants
no exposure authority.

The [account command guide](../packages/execute-application.md#managed-paper-activation-requests)
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
   a fresh observed quote, explicit sell limit and maximum fee. While a shared
   observer is live it observes every eligible book, so take the quote from the
   account's `valuation` projection (`inspect` with only `query_instrument`) and
   send it unchanged; on `unobserved_quote` read it again and resend. Never send a
   `quote` of your own then: one stamped after a book's availability but applied
   before that book's own observation makes the observer's observation regress,
   which faults the account and stops its matching. Accepted means
   an IOC sell reservation. Only subsequent eligible public liquidity can create
   fills. Stale/disconnected input, unknown outcomes, unreconciled state or
   insufficient owned inventory produce explicit refusal; budget ceilings never
   refuse a reduction. Partial/unfilled quantities are reported without claiming
   liquidation. Other strategies' inventory is never used to satisfy the request.
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
venue facts before resuming. That venue qualification is out of scope. If the founder is unavailable, a deployed process must
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

The local [dashboard/metric/query/alert interfaces](../packages/telemetry.md)
include configured exact thresholds, retained input/result bytes and explicit
local routes. The public-paper workflow writes a final local snapshot and exposes
monitoring failures in its result. The installed
[monitoring command](../packages/execute-application.md#retained-monitoring)
can reopen configured telemetry without changing operating state. Socket status
means local datagram acceptance; it does not establish receiver processing or
human acknowledgement. Inspect pending/failed attempts and telemetry loss
separately from hard controls. External venue and source-clock qualification
and runtime capacity are separate work. Additional
operators and staffing-dependent approval/review programs follow actual
organizational need and remain separate from technical completion.

The dashboard/metric/query/alert infrastructure and default health, execution,
risk and account views are required before QR onboarding. Quant development tests
custom metric/chart registration and alert delivery with reference workloads;
telemetry topology follows the launch capacity budget. Minimum monitoring and
tested recovery accompany each capability as it is built. The local paper
consumer retains actual receiver observations separately from socket acceptance;
human acknowledgement and remote-service delivery remain untested.

## Supervised multi-instance paper services

Use the [service guide](../packages/paper-application.md#supervised-local-deployments)
and [account service request](../packages/execute-application.md#bounded-account-owner-service)
for the supported commands. These finite local invocations do not create a
background system daemon or grant private venue authority.

1. Install a separately signed account target for each shared or isolated account.
   Author its disabled deployment with the full provisioned instance/input/scenario
   envelope. Separately authorize, supply fresh independent quotes and account
   observations, and claim its owner generation. Preserve each target's current
   journal. Installation alone never activates scheduling. Declare each instance's
   candidate before signing: a reference formula, or a packaged candidate from the
   paper-services release (see the next section). Its cadence is bounded by source
   freshness and capture idle time, and the deployment binds the candidate's
   identity. Every native book is retained/validated; the due candidates decide on
   the first delivery after their instant, and every eligible book matches open
   orders under the scenario's entry and cancel delays. Books between instants
   update monitoring marks and can fill; source faults remain immediate.
2. Start each target through `alpha-governance-artifacts run ... -- account
   --request SERVE.json`, with action `serve_paper`, the claimed owner, absolute
   socket path and `service_seconds` no greater than 120. Start the supervisor from
   the installed paper-services target: `alpha-governance-artifacts run --target
   SERVICES --policy POLICY -- deployment --owners OWNERS.json --root ROOT --socket
   SOCKET`. The launcher binds the signed configuration and candidates.
3. Inspect `deployment-control` and the retained `status.json` during operation.
   Check policy/source process status, account heartbeat, source freshness,
   authority and generation, reconciliation, reservations and per-strategy
   report costs/net P&L separately. A successful monitoring sample in `status.json`
   includes the account activation, report and each configured instance's scope,
   orders, nonterminal reservations, residuals and stopped flag. The retained
   `monitoring/<account>.json` records those fields with the inspected account
   state; its telemetry database is a projection. A live heartbeat is not a
   current market or economic progress. The installed account journal remains
   authoritative. Check the separate diagnostic process status and actual sample
   time: full reports run outside the delivery loop, pending diagnostic samples
   may be coalesced, and a failed or delayed report does not delay the supervisor's
   account-phase protection checks. The process shares the finite shutdown bound;
   any forced fence or unfinished diagnostic batch remains visible.
4. Use `stop_instance` for a selective policy stop. Other strategies retain
   ownership, but cancellation of a shared physical parent can suspend their
   residuals until a fresh complete reconciliation. If that parent ends on its own
   terms before the cancel takes effect (an immediate-or-cancel expiry, a stranded
   remainder or a post-only rejection), their children end with it and nothing
   awaits reissue. Inspect terminal outcomes,
   independently observe the complete account, then explicitly `restart_instance`.
   An optional typed `AccountObservation` on that control makes the supervisor
   reconcile through the current signed account owner and require success
   immediately before restart, before another cohort is scheduled. The observation
   must name the instance's account; a mismatched or rejected observation starts
   no worker. Without it, the journal's prior reconciliation requirement still
   applies. A successfully applied control identity can be replayed only with
   identical content. An uncertain account response is never automatically
   retried. Restarting the
   service alone does not restore authority or clear account protection.
   Operator reduction remains a separate `reduce_paper` account request, using
   current admission-time quote/book/state freshness even if the grant expired.
5. On source loss/staleness, the supervisor stops dependent policies and faults
   the affected accounts. `restart_source` starts a fresh unsynchronized capture
   and may settle old obligations; it does not clear controls or resume policies.
   On owner loss, all dependent workers stop and no uncertain account request is
   replayed. Stop the supervisor, inspect the latest journal through the signed
   launcher, reconcile retained requests/results and independent facts, resolve
   pending/uncertain orders, then claim a fresh owner before restarting services.
   The supervisor's requests are in `<root>/requests/<account>/<log>.jsonl`: an
   `attempt` with a `request` record but no `result` or `error` record has an
   uncertain outcome. The owner service's retained requests are the lines of
   `service-requests/<life>.jsonl` beside the journal.
6. An account/delivery persistence failure stops affected admission; storage that
   cannot record a fault cannot prove a clean stop. Terminate the producer, retain
   the failure, restore writable storage, inspect current state and reconcile.
   A diagnostic/receiver failure is recorded separately and cannot clear hard
   controls, create authority or cause an execution retry.
7. To activate a provisioned inactive instance, shut down the deployment, increment
   selection revision with the previous configuration digest, and add its name to
   `active`. Preserve every account/source/policy definition and the service root.
   Reconcile and claim fresh generations, then relaunch. Unknown definitions,
   changed budgets and incompatible state fail; no journal reset is supported.
8. Use explicit `shutdown` when the trial completes. Confirm source/policy PIDs
   have exited, account services have stopped, account phases are stopped and
   unresolved obligations remain visible. Retain captures, requests, configuration
   history, service events and receiver observations before cleanup.

For an already installed, authorized and claimed deployment, these control files
show the separate operator steps. Give each new action a unique identity. Replace
the example instance, socket and paths with the deployed values. After the stop,
inspect its terminal outcomes and prepare
`/private/tmp/paper-controls/independent-observation.json` as a complete, current
`DomainCodec` JSON `AccountObservation` from independent account facts for that
instance's account. The restart file embeds that observation as a typed field:

```sh
mkdir -p /private/tmp/paper-controls
printf '%s\n' '{"action":"inspect","identity":"inspect-001"}' \
  > /private/tmp/paper-controls/inspect.json
alpha-execute deployment-control --socket /private/tmp/paper-supervisor.sock \
  --request /private/tmp/paper-controls/inspect.json

printf '%s\n' '{"action":"stop_instance","identity":"stop-001","subject":"shared-fixed-btc"}' \
  > /private/tmp/paper-controls/stop.json
alpha-execute deployment-control --socket /private/tmp/paper-supervisor.sock \
  --request /private/tmp/paper-controls/stop.json

# Inspect terminal outcomes and author the independent observation file here.
python - <<'PY'
import json
from pathlib import Path

directory = Path('/private/tmp/paper-controls')
observation = json.loads((directory / 'independent-observation.json').read_text())
control = {
    'action': 'restart_instance',
    'identity': 'restart-001',
    'subject': 'shared-fixed-btc',
    'observation': observation,
}
(directory / 'restart.json').write_text(json.dumps(control))
PY
alpha-execute deployment-control --socket /private/tmp/paper-supervisor.sock \
  --request /private/tmp/paper-controls/restart.json

printf '%s\n' '{"action":"shutdown","identity":"shutdown-001"}' \
  > /private/tmp/paper-controls/shutdown.json
alpha-execute deployment-control --socket /private/tmp/paper-supervisor.sock \
  --request /private/tmp/paper-controls/shutdown.json
```

Stop after any rejected or uncertain control response and inspect the current
journal and any retained control result before issuing a new identity. Installation,
authorization, owner claim and inactive-instance activation remain the separate
procedures above.

### Recover unsent managed shadow intents

Shadow has no paper matcher and no modeled fills. After a supervised shadow loss,
inspect the current signed journal and distinguish a never-submitted physical
parent from an acknowledged, accepted, unknown or filled order. Explicitly stop
the affected account, then selectively stop every affected instance. For each
verified unsent, zero-fill and zero-fee physical parent still at `intent` or
`cancel_requested`, send an owner-bound `net_event` with `kind="rejected"` through
the signed account launcher. Use the exact current `PaperOwner`, a nonfuture event
clock and a stable event identity; the
[typed request example](../packages/execute-application.md#shadow-unsent-intent-settlement)
shows the command. This is a local no-submission fact that releases a reservation,
not an exchange response. The operation retains the journal and strategy
checkpoints without adding economic postings. It cannot be used while the
account is running, for accepted or uncertain orders, for manual paper-mode
outcomes or to post a fill.

Inspect the resulting terminal parents and independently reconcile the complete
account with empty physical open orders. Only then explicitly claim a new owner,
start its signed service and restart selected policies. The claim and each
instance restart advance the account control clock: supply a fresh complete
observation immediately before each instance restart, preferably in that
supervisor control's `observation` field. A pre-claim reconciliation alone is
insufficient. Exact saved rejection
retries remain idempotent under the current owner after restart; a replaced owner
cannot create a new rejection.

## Take a packaged candidate to signed paper

Run these steps in order, after the QR has packaged the candidate
([quickstart](../research/quickstart.md#5-package-a-candidate)). Each command
fails closed; on any failure, fix the input and start the step again.

1. **Collect inputs.** Copy the candidate bundle directories into one `CANDIDATES`
   directory, each named by its definition identity. Copy the QR's extension
   project into an `EXTENSIONS` directory, one project per subdirectory. Author
   the `paper-services` configuration with a `PackagedCandidate` per instance
   (definition identity, extension name, grid origin and, for a served feature,
   `feature_version`), plus `features` when any candidate is feature-served.
2. **Audit the extension.** `uv run --frozen --no-editable
   alpha-governance-engineering-standards import-audit EXTENSIONS/<name>` must
   pass; the build repeats it.
3. **Fetch and build.** With a release request whose runtime application is
   `paper-services`:

   ```sh
   alpha-governance-artifacts fetch --repository . --request REQUEST.json \
     --policy POLICY.json --dependencies WHEELS
   alpha-governance-artifacts build --repository . --request REQUEST.json \
     --policy POLICY.json --configuration CONFIG.json --dependencies WHEELS \
     --audit AUDIT --key KEY --registry REGISTRY \
     --candidates CANDIDATES --extensions EXTENSIONS
   ```

   The build admits each extension only if every requirement is already in the
   paper-services lock. It signs the extension's source under
   `source/external/<name>/` with its wheel, and the candidate bundles under
   `candidates/`.
4. **Verify and install.** `alpha-governance-artifacts verify --release RELEASE
   --policy POLICY.json`, then `install --release RELEASE --policy POLICY.json
   --target SERVICES`. Installation runs `deployment-check` before selecting the
   release.
5. **Read the identities.** `alpha-governance-artifacts run --target SERVICES
   --policy POLICY.json -- deployment-check` prints each instance's candidate,
   policy, feature and model identities, each source identity, and any pinned
   feature stream.
6. **Sign and activate each account.** Author each account target's deployment
   from those identities, then follow steps 1–2 of the supervised services above:
   authorize, reconcile, claim owners, serve the accounts and start the supervisor.
   A feature-served candidate also needs its stream publisher: declare
   `features.publisher` in the configuration and run `alpha-governance-artifacts run
   --target SERVICES --policy POLICY.json -- feature-publisher --root ROOT` beside the
   supervisor, with the supervisor's `--root`. The launcher binds the signed
   configuration and candidates.
7. **Monitor and stop** as in steps 3–8 above.

## Incident record

Record the time, artifact and configuration identity, observed condition, safe
action, affected orders or state, root cause, recovery result, and follow-up
test. A material incident requires a new release or activation review before
resuming the affected capability.
