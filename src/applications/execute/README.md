# Installed execution admission and dedicated paper OMS

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
command outside the checkout. Production authority and netting remain absent.
