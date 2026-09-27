# Paper and shadow application

`run_paper` composes an admitted candidate, independent exact spot limits,
`PaperOrderJournal` and `PaperCandidateRuntime` over a finite iterable of
`PaperMarket`, `PaperTimer` and normalized `OrderEvent` records. Callers supply
registered component factories, capability registry, configuration, source or
feature feed, journal path, opening time and owner. The result contains the
durable checkpoint, ledger, orders and `submission_attempted=False`. Completing
an event prefix releases ownership without canceling orders. A later invocation
restores that same journal and its unresolved reservations.

## Shared account paper workflow

`run_shared_paper` composes selected `SharedStrategyBinding` values,
`SharedStrategyInput` records and an `AccountConfiguration` through one
`AccountJournal` and `SharedDecisionRuntime`. Import the application entry point
and records from `applications.paper`; policy bindings and inputs are public
runtime records. Each binding selects an instance/account/entity, an existing
`DecisionPolicy`, complete `PortfolioContext`, and maximum fee. Each input
supplies that instance's causal `DecisionContext` together with an `AccountQuote`
that the journal has already observed independently.

The finite event stream contains observed quotes, complete local
`AccountObservation` reconciliation facts, `SharedPaperDecision` batches, and
normalized `OrderEvent` facts for physical net orders. A batch has a stable
identity, a coordination time later than every policy decision, and an explicit
crossing policy (`reject` by default or `internal_at_quote`). The account must
reconcile before admission, and a policy input cannot substitute for the
journal's market quote. Both target/exposure and order/quote intents enter the
same instance/account/firm budget checks.

The journal first admits attributable child orders, then groups compatible
same-side children into physical net orders. Grouping requires a shared account,
observed quote, portfolio/venue/settlement/risk/authority context, side, limit and
time-in-force. With `internal_at_quote`, compatible opposite interests may cross
at their common observed quote when their limits permit it. An otherwise
crossable post-only child rejects the internal-crossing batch. The remaining
physical child quantities and reserved fee ceilings remain attributed to their
source instances. Physical partial fills are split using monotone cumulative
pro-rata quantity allocation on the exact financial grid; fees use remaining
child fee capacity and stable child-order identity for residual atoms. Each
normalized parent event and its child postings commit together, and conflicting
retries or attribution breaks are rejected and retained by the account journal.

Reopening with the same journal and bindings restores the account and each
instance's `shared-decision-v1` policy continuation. The continuation digest is
an optimistic precondition on the account transaction, so a stale concurrent
writer cannot replace a newer instance checkpoint. Selective instance stop and
restart remain account-journal operations; unresolved shared parents retain
their reservations until a terminal outcome and reconciliation. The result
returns current account views, tagged child orders, physical net orders and
batch outcomes with `submission_attempted=False`.

`run_shared_paper` preserves the explicit normalized-fact workflow. For automatic
native-book matching use `run_live_shared_paper` below. Shadow mode refuses fill
events. `run_paper` and `run_live_paper` retain the dedicated candidate paths;
broader multiple-instance deployment remains MR14 and authenticated execution is KIV.

## Automatic public-input accounts

`run_live_shared_paper` composes the existing native `CaptureRunner`,
`LiveBookDecisionSource`, `BookRegistry`, `SharedDecisionRuntime` and
`AccountJournal`. It supports one selected OKX or Bitfinex spot instrument/account
per invocation, with one dedicated instance or several sharing the account.
Supply `AccountConfiguration`, selected `SharedStrategyBinding` values, a
`PaperExecutionScenario`, one native `InputRequirement`/`CaptureRequest`, an
input adapter implementing `SharedBookInputs`, the account journal path and an
absent output directory. The input adapter supplies pure feature/prediction
contexts for the existing decision SDK; policy state remains in the journal.
It must preserve native input identity, actual cutoff and the independently
observed ask-valued account quote. Frozen candidate loading remains owned by
`CandidateLoader`; this bounded composition does not add promotion or activation.

Before decisions, supply a complete independently derived `AccountObservation`
when the journal requires opening or recovery reconciliation. The workflow never
constructs a successful reconciliation from its own output. For each eligible
book it first matches earlier orders and then coordinates new decisions, so the
decision's input cannot also fill that new order. Matching uses the declared
entry/cancel delays, fee, adverse price and take fraction. All physical net fills
and child allocations commit with finite touch liquidity in one account transaction.
Two distinct active reference policies exercise the public extension points;
their formulas are engineering workloads, not profitability evidence.

Output retains `manifest.json`, native `capture/`, fsynced `deliveries.jsonl`,
`paper-result.json`, `execution-traces.json` and `cost-report.json`. The manifest
pins configuration, source/implementation, book registry, policies, execution
assumptions and `last_eligible_bid_v1` mark policy. Reports require fresh marks
for all open holdings and retain exact account/strategy P&L, fees and slippage.
Slippage already paid through effective fill prices is disclosed without a second
deduction. Gas is explicitly inapplicable for the off-chain spot profile, with
a retained reason; applicable gas requires a future activity/accounting contract.

Replay retained `SharedBookDelivery` envelopes through a fresh
`SharedPaperCaptureObserver` over the same source/registry configuration. Native
state rebuilds from the beginning of the recording; exact old account/decision
retries preserve newer state. A new capture uses a new recording and waits for
fresh synchronization. Known invalid input blocks admission without releasing
unresolved exposure. Completion neither cancels orders nor liquidates holdings.
This is a bounded local invocation; service fencing/activation, deployment-wide
scheduling, dashboards and capacity qualification stay in MR13/MR14/MR12/MR15.

The [installed acceptance consumer](../../../tests/integration/consumers/runtime/public_paper.py)
adds independently calculated balances and order cumulatives, reconciliation,
replay, losing/no-trade and adverse-cost controls. The
[test guide](../../../tests/README.md#automatic-public-paper-acceptance) owns commands;
the [delivery record](../../../docs/roadmap/paper-integration.md) owns actual evidence.

`run_live_paper` is an asynchronous bounded public-book workflow. It accepts the
same candidate/configuration plus a `CaptureRequest`, capture output and journal
path. It injects native adapters and transport into `market_data.collection.CaptureRunner`
and runs the collector beside the UTC candidate scheduler. Either task's failure
cancels its peer; persisted capture and OMS records survive. The capture's existing
queue, byte, message, retry and duration bounds remain active. A fresh process
uses a fresh recording and waits for synchronized market input before resuming
decisions. It does not reuse a stale book from a previous connection.

`PaperCaptureObserver` requires the explicit `books` registry and admits the
selected venue through `BookRegistry.lookup` and `LiveBookDecisionSource.current_quote`, using
the shared [book quote contract](../../market_data/README.md#shared-book-quotes).
Displayed quantity at the best native price includes every visible order at that
price. The existing source cutoff, missing-side, crossed-book and freshness gates
remain active before paper matching. Receipt and actual post-persistence delivery
stay separate in the unchanged journal envelope; replay retains both clocks.
`run_live_paper` constructs the default per-source registry from native reference
and capability data. Callers may supply a broader `books` registry with explicit
equivalence mappings; only the candidate's selected venue supplies modeled fills.
The result includes `book_registry` configuration and its content identity for
retention. Original delivery replay rebuilds registry state and checks identical
paper effects. Consolidated BBO inspection does not authorize cross-venue routing.

Use the maintained installed reference consumers in the
[test guide](../../../tests/README.md#paper-and-live-input-acceptance). They build
real candidate bundles through completed engineering studies, supply extension
factories through existing public APIs and retain original source/availability
clocks. Their synthetic historical study, paper economics and current native
feed observations are separately labeled. They are infrastructure acceptance
workloads and supply no empirical strategy evidence.

The independent [`alpha-execute paper`](../execute/README.md) command operates the
portable OMS without loading research, training, notebook or serving dependencies.
It accepts explicit durable step, event, matching, cancel, replace and inspection
requests. Candidate/model supervision belongs to this full research application;
the execution wheel owns only the portable order/account boundary.

All modes are local and non-executable. Native input supports declared OKX/Bitfinex
spot books; other named sources use `run_paper` and must satisfy the candidate's
admitted signatures. Shared-account coordination accepts normalized facts or
automatically matched public books. Authenticated venue conformance, full MR14
multi-instance deployment and production activation remain separate outcomes.
