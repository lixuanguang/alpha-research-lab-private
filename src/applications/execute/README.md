# Installed execution admission and paper accounts

Owner: quant development. The original `inspect` and `admit` commands accept
exact spot limit intents through the existing capability, reference and
independent risk contracts. Their output is either a rejection or a suppressed
admissible intent. The separate `paper` command owns a durable local order
journal and account state. Neither command has a venue submission client,
credential resolver, live order command or capital authority.

`ExecutionConfiguration` (`execution-admission-v1`) binds the environment,
research/paper/shadow mode, mode-scoped credential reference, execution capability
profile, reference history, maximum quantity and quote currency. Credential
values never appear in the configuration. A production mode, executable profile,
foreign environment or mismatched credential mode fails before reading an intent.
The legacy admission state schema is `none-v1`; its requests do not mutate the
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
`PaperConfiguration` (`paper-runtime-v1`) with a dedicated flat initial account,
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
training, reporting and QuantLib packages. The complete research environment
also includes the application for development. Source public APIs preserve
optional research imports through Python's module-attribute loading protocol;
this narrow hook selects/imports explicitly named owned implementations, while
ordinary behavior remains class-owned. The static checker verifies the typed
imports, complete name map and unknown-name rejection used by those hooks.

The [trusted installation runbook](../../../docs/governance/operations.md#trusted-local-installation)
owns build/sign/install/rollback. [MR06's acceptance record](../../../docs/roadmap/README.md#mr06-delivery-and-acceptance)
tracks installed proof. MR07 owns supervised runtime and durable OMS; MR08 owns
atomic account reservations/reconciliation; MR11 owns OKX and Bitfinex private
execution conformance; MR13 owns separate activation and operational recovery.

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

`AccountConfiguration` pins `account-runtime-v1`, local `paper`/`shadow` mode,
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
separate MR09 operation. Position reduction and venue dispatch are MR13/MR11
work; no stop or cancel action claims flattening.

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
