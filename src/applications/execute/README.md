# Installed execution admission and paper accounts

Owner: quant development. The original `inspect` and `admit` commands accept
exact spot limit intents through the existing capability, reference and
independent risk contracts. Their output is either a rejection or a suppressed
admissible intent. The separate `paper` command owns a durable local order
journal and account state. These original commands retain no venue submission
authority. The separate test-venue command below adds authenticated test-account
operations; production trading remains unavailable.

## Retained monitoring

`account` and `venue` accept optional `--telemetry /absolute/monitor.sqlite3`.
They project committed state into a separate versioned journal after the
authoritative operation. `telemetry_error` reports persistence failure without
undoing a stop, changing account state or retrying venue activity.
An account application binds its telemetry implementation fingerprint on first
use and retains it for that application lifetime. Each operation still reads
current account facts; launcher verification and owner fencing are unchanged.

`MonitoringConfiguration` selects a bounded UTC query, exact implementation-pinned
metric definitions, panels and optional local alert rules. Its `defaults` method
creates editable operating views without routes. The
[telemetry guide](../../telemetry/README.md#operating-signals-and-commands)
owns the configuration example, clocks, retention and missingness contracts.

```sh
alpha-execute monitor --config /absolute/view.json \
  --journal /absolute/monitor.sqlite3 --output /absolute/retained-view
```

This command writes verified `snapshot.json`, `dashboard.html`, `provenance.jsonl`
(the selected events) and `manifest.json` and returns their directory and snapshot
identity. Identical retries do not
overwrite content. Add `--alerts /absolute/alerts.sqlite3` only to attempt the
configured local syslog routes. The command grants no venue or hard-control
authority; local datagram acceptance is not remote or human acknowledgement.
It is available in the independently installed execution wheel without research
dependencies. The programmatic `MonitoringApplication` is exported with the
other execution application APIs.

`ExecutionConfiguration` (`execution-admission`) binds the environment,
research/paper/shadow mode, mode-scoped credential reference, execution capability
profile, reference history, maximum quantity and quote currency. Credential
values never appear in the configuration. A production mode, executable profile,
foreign environment or mismatched credential mode fails before reading an intent.
The admission state schema is `none`; admission requests do not mutate the
paper order journal.

`ExecutionRequest` separately supplies an `OrderIntent`, account cash/holdings,
maximum fee, pending-intent flag, reference valid/knowledge cutoffs and maximum
reference age. The application resolves the causal venue specification, checks
capability/product/calendar/order support, then applies the existing exact spot
grid, holdings and affordability rules. Missing or unknown historical order rules
remain a refusal. The request's mode must match the installed configuration.
Accepted requests retain specification/profile identities and always report
`submission_attempted=false`; this is software admission evidence, not a venue
acknowledgement, fill, paper performance or empirical strategy result.

The standalone development commands are:

```sh
alpha-execute inspect --config /absolute/config.json
alpha-execute admit --config /absolute/config.json --request /absolute/request.json
alpha-execute paper --config /absolute/paper-config.json \
  --journal /absolute/paper.sqlite3 --instance example-instance \
  --request /absolute/paper-request.json
alpha-execute paper --config /absolute/paper-config.json \
  --journal /absolute/paper.sqlite3 --instance example-instance
```

The last form inspects the local paper account without a request. `paper` loads
`PaperConfiguration` (`paper-runtime`) with a dedicated flat initial account,
fixed spot tick/lot/holding limits, bounded fee and market scenario. The journal
binds the full configuration identity and explicit instance; changing either
cannot reopen the same state. Fixed authored grids have `qualification=fixture`
and do not establish venue rule fidelity. Each result reports
`submission_attempted=false`, current exact cash/holdings, pending reservations,
orders, event sequence and any durable account break.

The `PaperExecutionRequest` JSON selects one action. `decide` supplies a portable
`OrderDecision`, a stable request identity, optional target conversion price and
opaque checkpoint bytes; the command atomically journals the candidate
continuation, admission result and child orders. `replace` supplies the old
order ID plus a new decision, optional reference and checkpoint; it admits a
replacement with durable lineage only after the old order has a confirmed
terminal outcome. A cancel request or acknowledgement alone does not permit
replacement. `market` supplies a finite
`PaperMarket` quote for deterministic paper matching; shadow mode rejects this
action. `event` applies an identified lifecycle fact, including acceptance,
partial fill, rejection and confirmed cancellation; shadow mode refuses fills.
`cancel` records a cancel request and keeps the reservation until a later
confirmed outcome. `reconcile` compares caller-observed paper cash, holdings
and open order IDs, blocking new risk on a break. `inspect` is read only. The
request uses the shared exact `DomainCodec` wire representation. Decision,
replacement and
market step IDs reject changed retry bytes; order event IDs reject changed
event payloads. Reconciliation accepts a fresh caller-observed account snapshot.

Paper matches are bounded top-of-book assumptions with finite displayed
liquidity. Order acknowledgement, acceptance, fill and cancellation remain
distinct durable events. See the [paper journal](../../execution/README.md) for
reservations, fencing and known reconciliation limits. Physical venue account
reconciliation and venue adapters remain separate work.

Every `PaperConfiguration` requires an `execution` scenario; a configuration
without one is refused. The scenario selects its explicit venue/instrument,
entry/cancel delays, adverse price, fee rate, take fraction and off-chain gas
reason. Tick/lot rules come from the existing spot limits. A changed scenario or
quote identity cannot reopen prior matched state. The same evaluator serves
`AccountJournal` direct and shared net orders. Native source orchestration and
policy loading use the [paper application](../paper/README.md#automatic-public-input-accounts)
in the research wheel; the portable execution command continues to accept
explicit market requests without importing the public collector or research stack.

A trusted installation supplies its signed configuration automatically:

```sh
uv run --frozen alpha-governance-artifacts run \
  --target /absolute/execution-target --policy /protected/target-policy.json -- inspect
uv run --frozen alpha-governance-artifacts run \
  --target /absolute/execution-target --policy /protected/target-policy.json -- \
  admit --request /absolute/request.json
```

The application returns JSON on success and a nonzero exit with a scoped error
on malformed/incompatible input. The installed runner refuses a caller-supplied
configuration override. Do not run the raw virtual environment when relying on
its installation fence and configuration binding.

The independent wheel depends on the exact shared-contract version and its
admitted value/codec dependencies. It omits market data, research, notebook,
training and reporting packages. The complete research environment
also includes the application for development. Source public APIs preserve
optional research imports through Python's module-attribute loading protocol;
this narrow hook selects/imports explicitly named owned implementations, while
ordinary behavior remains class-owned. The static checker verifies the typed
imports, complete name map and unknown-name rejection used by those hooks.

The [trusted installation runbook](../../../docs/governance/operations.md#trusted-local-installation)
owns build/sign/install/rollback. [MR06's acceptance record](../../../docs/roadmap/README.md#mr06-delivery-and-acceptance)
tracks installed proof. MR07 owns supervised runtime and durable OMS; MR08 owns
atomic account reservations/reconciliation; MR11 owns OKX and Bitfinex private
execution conformance. The bounded managed-paper activation and local recovery
contract is documented in this guide's managed requests section; it does not
qualify venue execution or deployed-service disaster recovery.

## Shared account command

`alpha-execute account` operates the independent
[shared account journal](../../execution/README.md#shared-account-admission-and-reconciliation)
from the same execution wheel:

```sh
alpha-execute account --config /absolute/accounts.json \
  --journal /absolute/accounts.sqlite3 --request /absolute/account-request.json
alpha-execute account --config /absolute/accounts.json \
  --journal /absolute/accounts.sqlite3
```

`AccountConfiguration` pins `account-runtime`, local `paper`/`shadow` mode,
opening currency funding, spot instrument mechanics and a `BudgetPolicy`.
`AccountExecutionRequest` selects exactly one action: `quote` records the
independent market observation; `admit` submits an attributable `AccountDecision`;
`event` processes normalized order/fill facts; `post` applies transfers, costs or
corrections; `reconcile` compares a complete independent `AccountObservation`;
`block` stops new account exposure; `inspect` returns current state. Contradictory
extra payloads are rejected before opening the journal. Configuration and request
files are bounded to one MiB. Use `DomainCodec` for exact financial wire values.

An opening account must reconcile before its first admission. Refresh market
observations separately from decisions. Reusing an admitted decision ID returns
its original result and checkpoint; replacing its bytes fails. Every result
reports `submission_attempted=false`. Normalized fill/account facts remain
modeled local input; no success is a physical venue observation. A contradiction
returns a nonzero CLI exit and retains the account block. The maintained
[shared-account consumer](../../../tests/integration/consumers/runtime/shared_account.py)
generates concrete configurations and requests and exercises the installed
command outside the checkout. Production authority remains absent.

The same command accepts the shared portfolio operations:

| Action | Required payload and result |
| --- | --- |
| `coordinate` | `batch: PortfolioBatch` retains strategy/revision metadata, all pre-net decisions, the explicit crossing policy and a stable batch identity. Gross risk admission and any internal crossing/physical order creation commit atomically. `portfolio` contains the original durable outcome. |
| `net_event` | `net_event: OrderEvent` names a physical parent. The journal applies its lifecycle and allocates its fill/cost effects to strategy children in one transaction. |
| `net_cost` | `net_cost: NetFeeCorrection` identifies a physical fill and its revised total fee. Append-only child corrections retain the original event and require account reconciliation before admission resumes. |
| `stop_instance` | `instance_id`, UTC `at`. Block the selected instance and request shared-parent cancellation while retaining unresolved reservations. This action does not flatten positions or claim an exchange cancellation. |
| `reissue_pending` | `account_id`, UTC `at`. After confirmed cancellation and complete reconciliation, route the unaffected strategy's reserved residuals through new physical parents. |
| `restart_instance` | `instance_id`, UTC `at`. Resume local decision admission only after the journal's recovery conditions hold; independent account blocks remain in force. |

Results expose both `orders` (attributed children) and `net_orders` (physical
parents), plus `stopped_instances`, retained `failed_net_events` and unroutable
`residuals` with their owner, quantity and physical-grid reason. Use the
parent identity when supplying normalized physical events;
strategy child identities remain accounting and risk lineage. Inspection and
all mutations report `submission_attempted=false`. Failed physical facts remain
durable and block new risk. See the [portfolio journal contract](../../execution/README.md#portfolio-coordination-and-recovery)
for compatibility, costs, residuals and the stop/reconciliation sequence.

The [portfolio consumer](../../../tests/integration/consumers/runtime/portfolio_account.py)
authors configured target and order-intent strategies, retains every request and
result, and exercises the installed CLI using both OKX/USDT and Bitfinex/USD
fixture labels. These are local spot accounting scenarios, not private account
observations or venue-rule qualification.

## Test-venue commands

`alpha-execute venue` uses `VenueExecutionConfiguration` (`venue-execution`),
an `AccountConfiguration` in explicit `venue_test` mode and the existing account
journal. The configuration includes the expected physical `venue_account_id`,
canonical/native instrument mapping, current reference history and credential
environment-variable references. `inspect`, `quote`, `admit` and `coordinate`
need no credentials. The modeled-event `account` command rejects this mode, preventing
its modeled event requests from masquerading as native venue facts.

```sh
alpha-execute venue --config /absolute/venue.json --journal /absolute/state/accounts.sqlite3 --action inspect
alpha-execute venue --config /absolute/venue.json --journal /absolute/state/accounts.sqlite3 --action reconcile
alpha-execute venue --config /absolute/venue.json --journal /absolute/state/accounts.sqlite3 --action quote --request /absolute/quote.json
alpha-execute venue --config /absolute/venue.json --journal /absolute/state/accounts.sqlite3 --action coordinate --request /absolute/batch.json
```

The local request uses the existing `AccountExecutionRequest` codec and its
matching action (`quote`, `admit` or `coordinate`). Independent account admission
returns `admission` or `portfolio`, including physical order identities. It does
not submit. Actual test submission requires a separate `VenueAuthorization`
document, pinned to the exact config digest, account/environment, instruments,
UTC validity interval and maximum order notional, with `submit_enabled=true`:

```sh
alpha-execute venue --config /absolute/venue.json --journal /absolute/state/accounts.sqlite3 --action submit --order PHYSICAL_ORDER_ID --authorization /protected/test-authority.json
alpha-execute venue --config /absolute/venue.json --journal /absolute/state/accounts.sqlite3 --action cancel --order PHYSICAL_ORDER_ID --authorization /protected/test-authority.json
alpha-execute venue --config /absolute/venue.json --journal /absolute/state/accounts.sqlite3 --action cancel-stranded --authorization /protected/test-authority.json
alpha-execute venue --config /absolute/venue.json --journal /absolute/state/accounts.sqlite3 --action stream --duration 30 --messages 100
```

These commands perform external authenticated requests and require separately
authorized test accounts. They were **not run against an exchange** during MR11
implementation. OKX uses demo trading and Bitfinex verifies the paper-account
flag; the returned native UID must match configuration. No production mode is
accepted. Protective cancellation keeps the envelope's account/config/instrument
scope even after its submission interval expires. Stops and cancellation do not
imply position reduction.

`gateway.stranded` lists resting sells whose remaining fee reserve cannot pay one
lot even at their limit (at the configured worst-case rate): they could only fill
by charging past their reserve. `--action cancel-stranded` requests cancellation of
all of them under one authorization; each keeps its reservation until the venue
reports it terminal. A venue fee above an order's reserve is still posted, because
the fill already happened: the reserve grows to the fee charged and the excess is
paid from free cash, and the account faults as `native_fee_overage_uncovered` only
when free cash cannot cover it.

Results contain `gateway`, optional local `admission`/`portfolio`, and
`quote_observed`. Check business status and `gateway.recovery_required` even on
a zero CLI exit. A request acknowledgement leaves recovery required until complete
physical reconciliation. `submission_attempted` describes this command, not the
history of an uncertain order. A failing transport returns a nonzero exit and
retains state for inspection/reconciliation. Never remove the journal or change
the client identity to retry an uncertain send.

The independent execution wheel now includes the same pinned WebSocket library
already selected for collection; it still excludes research/training dependencies.
The existing signed-release runner does not admit the new venue config/state
schema. Thus these remain installed development/test entrypoints; trusted venue
deployment and rollback are a separate integration and qualification gate, not
something to bypass by invoking an installed environment directly.

The [venue execution owner](../../execution/README.md#test-venue-execution) explains
history bounds, native fees, fencing and recovery. The
[installed consumer](../../../tests/integration/consumers/runtime/venue_execution.py)
authors runnable configs/authority and exercises both actual protocol adapters
with scripted HTTP, without credentials or exchange access. Its authored
specifications and account facts establish software conformance only.

## Local operational commands

The `account` command also accepts `control`, `backup` and `restore` requests.
Use a selected state directory, normally `state/accounts.sqlite3`. These
operations work in both paper and shadow mode and always suppress submission.

`control: AccountControl` selects `startup`, `stop`, `fault`, `restart` or
`cancel`, with a stable identity, account ID and UTC knowledge time. Stop/fault
retain a visible reason. Startup is the first local control transition after
fresh independent reconciliation and marks; it does not launch a process.
Restart names the exact `expected_control_identity` of the current stop/fault.
It requires a newer complete reconciliation, fresh quotes, resolved send/cancel
uncertainty and the existing funding/budget checks. Retry returns the original
control result; a reused identity with changed bytes fails. Results include
current account phases and the append-only `controls` history. Business refusal
is `control.status=rejected`; callers must check it even after a zero CLI exit.

Stop/fault block new exposure without cancelling orders. `cancel` records local
requests for outstanding physical orders and returns their IDs; no request or
acknowledgement releases a reservation. Selective instance stop remains the
separate MR09 operation. Managed paper reduction is a bounded reservation
documented in the managed requests section; physical venue reduction and venue
dispatch remain separate venue operations. No stop or cancel action claims
flattening.

A protective control can supply `alert_socket`, an absolute local Unix datagram
endpoint of at most 100 bytes. The control commits before delivery. The adjacent
`accounts.alerts.sqlite3` retains pending/delivered/failed attempts keyed to the
control digest. Delivered means local socket acceptance. An interrupted pending
attempt is visible and is not automatically resent. Alert-storage failure is
reported through `alert_error`; it cannot clear the account stop.

`backup` supplies `backup_root`, an absent absolute directory outside the selected
workspace. All accounts must be explicitly stopped or faulted; the check occurs
under the SQLite write locks. It preserves the entire journal directory,
including alert outcomes, through the existing workspace backup owner. The
returned `recovery.manifest_sha256` pins the snapshot. `restore` supplies that
`backup_root`, `manifest_sha256`, and an absent absolute `restore_root`. It
verifies config, state and bytes before publishing the new workspace. The result
names the restored `journal_path`; it does not select that workspace for an
installed service. Restored accounts stay stopped until missing facts are
replayed and fresh independent reconciliation permits an explicit restart.

The [operating runbook](../../../docs/governance/operations.md#local-paper-operations)
owns startup, incident, restoration and signed rollback procedures. The
[operational consumer](../../../tests/integration/consumers/runtime/account_operations.py)
retains concrete JSON requests for both spot fixture labels and uses these same
installed commands. It is quant-development software evidence, not a venue test.

## Managed paper activation requests

The signed target uses execution `paper`, `account-runtime` configuration
and `account-journal` state. `AccountExecutionRequest` and
`AccountExecutionResult` are execution-owned public wire APIs. The existing
`alpha-execute account` command accepts these additional actions:

| Action | Typed request fields | Result meaning |
| --- | --- | --- |
| `install_paper` | `deployment` | Disabled deployment and durable stop; no permission |
| `authorize_paper` | `authorization` | Explicit bounded grant; still stopped |
| `claim_paper` | `account_id`, `owner_id`, `control` (`restart`) | Fresh reconciliation and a new fenced `claimed_owner` |
| `revoke_paper` | `account_id`, `authorization_id`, `at` | New exposure/restart forbidden; protective actions retained |
| `paper_market` | `account_id`, `scenario`, `market`, `paper_owner` | Exact modeled events from finite eligible public liquidity |
| `reduce_paper` | `reduction`, optional `paper_owner` | Accepted reservation or rejection; never a liquidation claim |
| `inspect` | optional `account_id`, `query_instance`, `query_batch` | Deployment/grants, quarantine, traces, reductions, checkpoint or prior batch |

Existing `control/stop` and `control/cancel` remain distinct. Admission,
coordination, matching and economic mutation requests carry `paper_owner`.
Operator protection can omit an owner; a supplied replaced owner is rejected.
Independent quote/reconciliation requests do not grant authority. Installation
alone cannot admit orders, and managed restart must use `claim_paper`.

Use the governance launcher for all installed operations; its verified release
digest is injected internally and cannot be overridden in forwarded arguments.
Requests and recovery paths must be absolute. The raw command's release option
is an internal launcher interface, not proof that a caller verified a release.
See the [activation record](../../../docs/roadmap/paper-activation.md) for the
commands and evidence retained so far, artifact identities and remaining
operating limits; it does not claim operational qualification before drills.

### Shadow unsent-intent settlement

A managed shadow account never runs paper matching or posts modeled fills. A
supervised shadow policy can nevertheless leave a physical parent in local
`intent` or `cancel_requested` state with a reservation. To settle that
no-submission fact, explicitly stop the account, selectively stop every affected
instance, and inspect the parent and children. Through the current signed owner,
send an ordinary `AccountExecutionRequest(action="net_event", net_event=...,
paper_owner=...)` with an `OrderEvent(kind="rejected")` for each verified unsent
parent. The journal accepts this only for a managed shadow deployment whose
parent was never acknowledged or accepted and has zero fill and fee. It requires
the account to be stopped or faulted, a current owner token and a nonfuture event
clock. The transition releases the reservation while preserving ledger economics
and policy checkpoints. It records a local no-submission fact, not a venue event.

For example, save the exact current `PaperOwner` returned by the claim as
`/absolute/current-owner.json`; take the physical parent ID from a fresh
inspection. This writes one typed request for the signed launcher:

```sh
python - <<'PY'
from datetime import UTC, datetime
from pathlib import Path
from execution import AccountExecutionRequest, OrderEvent, PaperOwner
from serialization import DomainCodec

codec = DomainCodec()
owner = codec.decode_json(Path('/absolute/current-owner.json').read_bytes(), PaperOwner)
event = OrderEvent(
    identity='shadow-unsent-rejection-001',
    order_id='PHYSICAL_PARENT_ID_FROM_INSPECTION',
    at=datetime.now(UTC),
    kind='rejected',
)
request = AccountExecutionRequest(action='net_event', net_event=event, paper_owner=owner)
Path('/absolute/requests/shadow-unsent-rejection.json').write_bytes(codec.encode_json(request))
PY
alpha-governance-artifacts run --target /absolute/target --policy /protected/policy.json -- \
  account --request /absolute/requests/shadow-unsent-rejection.json
```

Keep the same event identity and bytes for an exact saved retry; a replaced
owner cannot apply a new event, although the current successor may reopen the
saved result after restart. New rejection while running, an acknowledged,
accepted, unknown or filled parent, other manual lifecycle events, and every
managed paper-mode `net_event` remain blocked. Verify zero new economics and an
empty physical-open-order set, then independently reconcile the complete account
with empty open orders before claiming a fresh owner and explicitly restarting
services and instances. The claim and every instance restart advance the account
control clock. Reconcile a fresh complete observation before each subsequent
instance restart; the supervisor's restart control can carry that observation.
Retain the original journal and checkpoints throughout.
The [MR14 record](../../../docs/roadmap/multi-instance-paper.md) owns the installed
qualification and its precise local operating limits.

## Bounded account-owner service

`serve_paper` is an `AccountExecutionRequest` with `service_socket` (absolute local
Unix socket), `service_seconds` (1–120) and the exact `paper_owner` returned by an
explicit claim. Run this request through the signed launcher:

```sh
alpha-governance-artifacts run --target /absolute/target --policy /protected/policy.json -- \
  account --request /absolute/requests/serve.json
```

The service keeps the installation fence, fixes configuration/journal/release, and
serializes the existing typed requests. `SocketPaperAccount` retains requests and
responses. Owner-generation checks remain inside economic transactions. Service
startup does not claim, renew or widen authority. Its heartbeat file beside the
socket exposes actual process PID, liveness and request progress separately.
The existing launcher bounds commands to 180 seconds; services are deliberately
limited to 120 seconds and require explicit recovery between invocations.

Account requests default to a complete response. Internal `PaperAccount` helpers
select a typed `projection` for their requested read or operation receipt, so a
checkpoint lookup does not transfer unrelated order and accounting history.
Explicit operator inspection remains complete. The service reuses its opened
journal handle after checking the exact configuration, path and owner; each
query and economic transaction still reads current SQLite state. Neither response
projection nor handle reuse changes admission checks. The store may reuse a fully
validated immutable decode only when freshly read configuration and payload bytes
match exactly. Changed payloads are decoded and validated before use; committed
writes never populate that cache from an unchecked in-memory value.

`shutdown_paper` requires the same owner and a separate `control` of kind `stop`.
It stops new exposure and ends the service; it does not cancel or liquidate.
Selective instance controls, cancellation, reduction and independent reconciliation
use their existing requests over the socket while it operates. Monitoring and
alert failures never cause an economic request to be retried.

The full installed research distribution also supplies `alpha-execute deployment`
and `deployment-control`, documented in the
[paper application guide](../paper/README.md#supervised-local-deployments).
The independently signed execution target remains free of research/source packages;
only the account service runs inside that target.

In that supervised paper composition, each `PaperServiceSource` declares
`market_interval_us` (default 3,000,000), a positive selected-book economic
cadence no greater than its `freshness_us` or capture idle time. The exact
`PaperServiceConfiguration.identity` and `ServiceBookInputs.identity` both pin
this value. Native records remain retained and validated
in order; the first eligible book and subsequent books at least one interval
after the last selected book cause `paper_market` matching and active strategy
evaluation. Intermediate eligible books update the monitoring mark without
matching orders, posting paper fills or advancing strategy checkpoints. Source
invalidation still faults immediately. Retained `SharedBookDelivery` records
record `market_effects` explicitly: `false` marks skipped economics for exact
replay, `true` means that book's market effects were applied. This models selected
paper opportunities and does not qualify feed throughput or MR15 capacity.

The supervisor consumes at most one durable frame per source per pass. When the
complete configured account sets of its sources are disjoint, a run-owned pool
observes those frames concurrently, with at most one in-flight job and frame per
source and at most four jobs. A pending source receives its next frame only after
completion, while other sources can progress across passes. Native validation,
full delivery retention and per-row fsync still precede each account's selected
effects. Worker and source health checks continue on every pass while jobs are
pending. With an active disjoint-source executor, owner identity, heartbeat and
process liveness have a twenty-millisecond deadline from each check's start;
the first subsequent supervisor pass performs the due check. The first check
is immediate. Account RPCs still validate current authority independently.
Every job joins before lifecycle fences, controls, phase sampling,
status or shutdown; failures are handled on the supervisor after removing owned
futures. Sources sharing any account retain
serial source-name and account-name order. The pool remains available through
the existing bounded shutdown drain and closes before launch fences release;
account and policy timeouts, selection cadence and authority are unchanged.
Waiting excludes busy source pipes and includes a run-owned completion socket,
so finishing a job wakes the supervisor even if the remaining source pipes are
idle. Nonblocking notifications coalesce and close after worker callbacks join.
The existing twenty-millisecond idle bound and the next owner-check deadline
bound waits; completed jobs never wait for another source frame.
