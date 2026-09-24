# Installed execution admission

Owner: quant development; initial MR06 execution package consumer. This
application accepts exact spot limit intents through the existing capability,
reference and independent risk contracts. Its output is either a rejection or a
suppressed admissible intent. It has no venue submission client, credential
resolver, OMS, live order command or capital authority.

`ExecutionConfiguration` (`execution-admission-v1`) binds the environment,
research/paper/shadow mode, mode-scoped credential reference, execution capability
profile, reference history, maximum quantity and quote currency. Credential
values never appear in the configuration. A production mode, executable profile,
foreign environment or mismatched credential mode fails before reading an intent.
The initial state schema is `none-v1`; it does not represent an order journal.

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
```

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
