# Research decision contracts

Owner: quant development. Implemented research SDK, 2026-09-24.
Existing `TargetRule`, `RuleRegistry`, `BookRule` and saved spot simulations retain
their behavior. The generalized interface is `DecisionPolicy`: explicit identity,
output family, signature admission, initial/validated state, and a pure
`decide(context, state)` transition. A policy cannot submit orders or approve risk.
A transition's intent may be `None`: the policy abstains, wanting no working orders
at that decision, while its state still advances. Research and paper treat every
decision as replacing the instance's working orders, so an abstention withdraws any
resting quote; a policy that cannot price should abstain rather than invent a price.

For MR07 supervision, a policy may also implement `DecisionLifecycle.on_event`.
`StrategyEvent` carries explicit start/recovery, timer, market, order, account,
fault or stop identity and UTC availability, with paired order and cash/holding
fields where applicable. The callback returns validated policy state bytes; it
does not submit an intent, read a venue or change independent account protection.
The [paper runtime](../runtime/README.md#paper-candidate-supervision) persists the
state and callback cursor together. Policies without lifecycle callbacks retain
their existing pure decision behavior.

`DecisionContext` contains a then-available multi-feature vector and an optional
prediction bound to that exact vector, entity and decision. Labels are absent.
`TargetIntent` requests an absolute dimensioned position; `ExposureIntent` requests
currency exposure; `OrderIntent` carries a positive limit order with IOC, GTC or
post-only semantics; `QuoteIntent` carries two compatible noncrossing resting
limits. These are intent contracts, not claims that every downstream venue or
simulator supports those operations. MR03 owns generalized economic consumption;
MR05/MR07–MR11 own runtime, portfolio/risk/OMS and execution integration.

`ConfirmedSignal` is the reference rule/prediction binding. It requests the selected
long quantity after the configured number of consecutive positive signals;
missing/nonpositive inputs reset confirmation and request flat. Formula, named
field, units, quantity and confirmation count enter its identity. No profitability
claim follows from this engineering reference.

`DecisionSession` validates the declared signature/output and instrument units
before committing state. State is supplied and returned as immutable bytes; the
adapter must validate its own schema and must not keep hidden mutable decision
state. Failure leaves the committed checkpoint unchanged. The checkpoint binds
run identity and cutoff; different instances and instruments cannot share it.
Digests detect accidental corruption, not hostile code or forgery.

`configuration.DecisionRun` pins the entity, instance, product/calendar,
source/feature/policy/fitted identities, required capabilities and explicit UTC
schedule. Available capabilities are supplied by the composing environment.
Unsupported requirements, signatures or fitted-state availability fail before
source access. Packaged study candidates use the typed capability registry and
[`CandidateLoader`](../runtime/README.md#candidate-loading-and-intent-evaluation)
for resolved replay/runtime admission. A declared capability is not venue
qualification or trading authority.

`applications.explore.run_decisions` composes the selected source, feature,
optional transform/model and policy. It accepts typed configuration, which can be
serialized with `DomainCodec`, and returns `DecisionResult` plus a combined
feature/policy checkpoint. `stop_after` produces a prefix checkpoint; reloading
the same configuration processes only its remaining schedule. Both feature and
policy state bind the same cutoff and installed implementation identity.
`inspect_decisions` retains complete/failed engineering attempts and fitted bytes
using the existing `AttemptStore`. It deliberately uses engineering-sample identity;
it cannot reinterpret a formal holdout family or claim empirical acceptance.

The [fresh installed consumer](../../tests/integration/consumers/research/decision_extensions.py)
authors a feature, label, non-built-in estimator and quote policy outside shared
orchestration. Its training/prediction/quote goldens and fresh-process continuation
prove these extension points. The
[domain tests](../../tests/unit/research/test_decision_contracts.py) exercise rule-only,
learned, stateful and separate-instrument instances. Shared accounts, supervised
order handling and service state migration remain separate milestones. Candidate
loading now reconstructs the selected policy and rejects changed state or outputs.
