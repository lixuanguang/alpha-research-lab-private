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
and records from `applications.paper`; candidate bindings and inputs are public
runtime records. Each binding selects an instance/account/entity, a
`LoadedCandidate`, complete `PortfolioContext`, and maximum fee. Each input
supplies that instance's causal `DecisionInputs` together with an `AccountQuote`
that the journal has already observed independently. A decision whose candidates
all pause or warm reserves nothing.

The finite event stream contains observed quotes, complete local
`AccountObservation` reconciliation facts, `SharedPaperDecision` batches, and
normalized `OrderEvent` facts for physical net orders. A batch has a stable
identity, a coordination time later than every candidate decision, and an explicit
crossing policy (`reject` by default or `internal_at_quote`). The account must
reconcile before admission, and a candidate input cannot substitute for the
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
instance's `shared-decision` policy continuation. The continuation digest is
an optimistic precondition on the account transaction, so a stale concurrent
writer cannot replace a newer instance checkpoint. Selective instance stop and
restart remain account-journal operations; unresolved shared parents retain
their reservations until a terminal outcome and reconciliation. The result
returns current account views, tagged child orders, physical net orders and
batch outcomes with `submission_attempted=False`.

`run_shared_paper` preserves the explicit normalized-fact workflow. For automatic
native-book matching use `run_live_shared_paper` below. Shadow mode refuses fill
events. `run_paper` and `run_live_paper` retain the dedicated candidate paths;
the [supervised local deployment](#supervised-local-deployments) composes multiple
instances, and authenticated execution is out of scope.

## Automatic public-input accounts

`run_live_shared_paper` composes the existing native `CaptureRunner`,
`LiveBookDecisionSource`, `BookRegistry`, `SharedDecisionRuntime` and
`AccountJournal`. It supports one selected OKX or Bitfinex spot instrument/account
per invocation, with one dedicated instance or several sharing the account.
Supply `AccountConfiguration`, selected `SharedStrategyBinding` values, a
`PaperExecutionScenario`, one native `CaptureRequest`, the account journal path
and an absent output directory. The native source projects every book field the
bound candidates read; each candidate decides on its own UTC grid and keeps its
full continuation in the journal. Candidate loading remains owned by
`CandidateLoader`; this bounded composition does not add promotion or activation.

Before decisions, supply a complete independently derived `AccountObservation`
when the journal requires opening or recovery reconciliation. The workflow never
constructs a successful reconciliation from its own output. At each candidate
grid instant the due candidates decide from the latest eligible market at or
before it, then the book that crossed the instant matches orders, so a decision's
input cannot also fill its own order. Each decision replaces its instance's
working orders: the account requests their cancellation at the decision time, and
an abstention replaces them with none. Matching uses the declared
entry/cancel delays, fee, adverse price and take fraction. The supervisor binds each
instance as its own portfolio, so candidates' physical orders are never netted. All physical net fills
and child allocations commit with finite touch liquidity in one account transaction.
Two distinct active candidates exercise the public extension points; their
formulas are engineering workloads, not profitability evidence.

Output retains `manifest.json`, native `capture/`, fsynced `deliveries.jsonl`,
`paper-result.json`, `execution-traces.json` and `cost-report.json`. The manifest
pins configuration, source/implementation, book registry, projected input
requirements, candidate and deployment identities, execution
assumptions and `last_eligible_bid` mark policy. Reports require fresh marks
for all open holdings and retain exact account/strategy P&L, fees and slippage.
Slippage already paid through effective fill prices is disclosed without a second
deduction. Gas is explicitly inapplicable for the off-chain spot profile, with
a retained reason; applicable gas requires a future activity/accounting contract.

### Retained public-paper monitoring

After the account result and report are retained, `run_live_shared_paper` projects
the committed account, strategy, trace and report facts into an immutable
`monitoring-input.json` envelope and renders a finite final view automatically.
The optional `alert_socket` argument selects an explicit local Unix datagram
route; it defaults to `None`. The returned `SharedPublicPaperResult.monitoring`
contains dashboard names, recorder counts and any projection, storage, render or
alert errors. Monitoring failures are returned after the paper operation and do
not undo it or enter account-failure handling.

Each event's `recorded_at` is the actual first monitoring receipt used to create
that envelope, including a retrospective import; event time and source
availability retain their own clocks. The envelope copies the delivered source
clock fields (`position`, optional native `source_time`, `received_ns` and
`available_at`) without normalizing them, and stores SHA-256 identities for the
retained manifest, account result, execution traces, cost report and deliveries
that exist. Reading the envelope verifies those referenced bytes. These copies
preserve the inputs; they do not qualify the source clock.

`runtime.processing_seconds` is the monotonic duration of the most recent actual
delivery callback that applies matching and decisions. It excludes feed transport
and persistence and is not the modeled `entry_delay_us` or `cancel_delay_us`.
Lifecycle facts produced from those paper assumptions carry modeled clock quality.
`data.source_clock_drift_seconds` and `data.receipt_to_durable_seconds` remain
explicitly `not_measured`; the workflow does not infer either from UTC clocks.

Default paper views use exact `last` values for current account/strategy state
and report economics. Account and strategy scopes, currencies, and instruments
remain separate series; the view does not sum them. Report-derived valuation is
keyed by the report digest and retains its cutoff, mark-age limit, gas
applicability, and currency results. Lifecycle events stay individually
attributable in telemetry for custom metric/chart consumers, while the default
snapshot views select cumulative state series.

The workflow writes `monitoring-input.json`, a telemetry journal, per-scope
configuration JSON, one directory per dashboard page, and `monitoring-status.json`.
Each dashboard directory contains `snapshot.json`, self-contained
`dashboard.html`, the selected events in `provenance.jsonl`, and `manifest.json`;
the names in the returned `dashboards`
field identify those directories. Open `monitoring/index.html` for the account
and strategy pages, report, original inputs and diagnostic status. This finite
invocation does not run a continuously refreshed dashboard service.

Monitoring can be regenerated from the retained envelope without reopening the
account journal, venue source, or execution workflow:

The recovery API is `render_paper_monitoring(input_path, *, journal_path,
output, alert_socket=None)`.

```python
from pathlib import Path

from applications.paper import render_paper_monitoring

result = render_paper_monitoring(
    Path("/absolute/run/monitoring-input.json"),
    journal_path=Path("/absolute/run/monitor.sqlite3"),
    output=Path("/absolute/run/monitoring-reopened"),
)
```

Use an absent output directory. Reusing the same telemetry journal makes event
ingestion idempotent; the renderer verifies the envelope's evidence identities,
then rebuilds only its telemetry views at the original receipt cutoff. Incomplete
ingestion refuses partial dashboards; replay the saved envelope after storage
or queue recovery. A fresh capture stamps new receipts only for its new lifecycle
facts, preserving prior envelopes. With an `alert_socket`, diagnostic rules
send local datagrams and retain pending/delivered/failed attempts in
`monitor.alerts.sqlite3`. `delivered` means the local socket accepted the send;
it does not show that a receiver processed it or that a person acknowledged it.
Alert and telemetry failures remain separate from account controls.
Default routes diagnose blocks, uncertainty, reconciliation/source/runtime
failures and negative net P&L by currency; missing/stale evidence triggers the
configured route. Preserve the same socket configuration and alert journal when
reopening if identical alert identities are required.

Replay retained `SharedBookDelivery` envelopes through a fresh
`SharedPaperCaptureObserver` over the same source/registry configuration. Native
state rebuilds from the beginning of the recording; exact old account/decision
retries preserve newer state. A new capture uses a new recording and waits for
fresh synchronization. Known invalid input blocks admission without releasing
unresolved exposure. Completion neither cancels orders nor liquidates holdings.
This is a bounded local invocation. Managed signed activation and local recovery
are documented below. The supervised service composition below supplies multi-instance
scheduling; runtime capacity and remote monitoring are separate outcomes.

The [installed acceptance consumer](../../tests/integration/consumers/runtime/public_paper.py)
adds independently calculated balances and order cumulatives, reconciliation,
replay, losing/no-trade and adverse-cost controls. The
[test guide](../development/testing.md#automatic-public-paper-acceptance) owns commands;
the [delivery record](../roadmap/overview.md#capabilities) owns actual evidence.

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
the shared [book quote contract](market-data.md#shared-book-quotes).
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
[test guide](../development/testing.md#paper-and-live-input-acceptance). They build
real candidate bundles through completed engineering studies, supply extension
factories through existing public APIs and retain original source/availability
clocks. Their synthetic historical study, paper economics and current native
feed observations are separately labeled. They are infrastructure acceptance
workloads and supply no empirical strategy evidence.

The independent [`alpha-execute paper`](execute-application.md) command operates the
portable OMS without loading research, training, notebook or serving dependencies.
It accepts explicit durable step, event, matching, cancel, replace and inspection
requests. Candidate/model supervision belongs to this full research application;
the execution wheel owns only the portable order/account boundary.

All modes are local and non-executable. Native input supports declared OKX/Bitfinex
spot books; other named sources use `run_paper` and must satisfy the candidate's
admitted signatures. Shared-account coordination accepts normalized facts or
automatically matched public books. Private venue qualification is out of scope. The bounded signed managed-paper
activation and local recovery interface, and the supervised multi-instance
composition, are described below.

## Signed account consumer

`InstalledPaperAccount` implements the execution-owned `PaperAccount` contract.
Pass it as `paper_account=` to `run_live_shared_paper` to route every account
operation through `alpha-governance-artifacts run --target ... --policy ... --
account --request ...`. The launcher fixes signed configuration, current release
and journal paths. The client retains exact request/result bytes and never
retries a failed or uncertain command automatically.

The deployment input digest is SHA-256 of
`DomainCodec().encode_json((capture_config, requirements))`, where `requirements`
are the projected book fields. The API checks that digest, the execution scenario,
each instance's candidate, policy, model and feature identities, paper authority
context, account configuration and claimed owner before starting the bounded feed.
Candidate components must include all parameters in their identities, as their
existing contracts require. Economic boundaries repeat
current authority and generation checks. Finite completion records an operational
stop; recovery needs new reconciliation and an explicit owner claim. Expiry or
revocation blocks new exposure and restart, while the original current owner may
drain existing obligations on fresh eligible data. Accepted standing orders keep
their reservations until terminal outcomes are established. A replacement grant
requires a stopped account and settled physical order outcomes before a new owner
claim.

The collector/input and policy producer is a client of the installed account
service. The execution target contains only its independently admitted execution
and contracts packages; it neither installs nor imports the research wheel. The
existing direct `journal_path` form remains a development/reference workflow and
is not an installed activation path. A developer environment or input producer
has no authority to override the signed target's risk, release or deployment.

The maintained [public-paper consumer](../../tests/integration/consumers/runtime/public_paper.py)
exercises this interface. A process timeout has an uncertain outcome: inspect
retained journal facts and exact request identity before recovery. Monitoring
failure is diagnostic and must never cause a committed matching/admission request
to be rerun.

## Supervised local deployments

`PaperServiceConfiguration` separates available source, instance and account
definitions from the `active` instance tuple. Each account definition points to an
explicitly activated signed account socket. Each source binds one native book
capture, optionally the same instrument's public `trades` capture, venue/instrument
identity, execution scenario and freshness budget; each instance selects its
source and a candidate: a `ReferenceCandidate` (an installed formula, its decision
cadence and UTC grid origin) or a `PackagedCandidate` (a signed bundle's
definition identity, the installed extension providing its code, and the grid
origin; the definition fixes the cadence). Packaged bundles are read only from the
release's signed `candidates/` directory, after their research provenance verifies,
with components from the named extension resolved against `PaperCapabilities`. All
candidates on one source must share its book requirement name, clock and freshness,
and likewise its trade requirement. A candidate's trade fields need the source's
trades capture, which runs in its own source process under the `<source>.trades`
key, shares the book's chain limits and observers, and is retained in each
account's `.trades.jsonl` log; reference and non-book inputs are refused here.
A `PackagedCandidate` with `feature_version` instead reads that version's
feature-store stream, which the bundle's packaged `FeatureStoreDefinition` names;
it then adds no source fields. Its serving needs the configuration's `features`
binding (`PaperFeatureServing`: absolute store path and Feast generation root, the
separately locked worker command and its timeout), and preflight refuses a
feature-served candidate without it. With `features.publisher`
(`PaperFeaturePublisher`, a maximum lag of 1 to 300 seconds), the separate
`alpha-execute feature-publisher --config ... --candidates ... --root ...` process
extends each served stream while the supervisor runs. It binds the supervisor's run
through a `status.json` written after it started, follows that run's book and trades
recordings read-only and replays each record on its receipt clock, as a saved
reconstruction does. At each grid instant, once every followed feed holds a durable
record after it, it materializes the pinned version's snapshot with the bundle's
kernel and fitted transform (`FeatureMaterializer`), Feast-verified before it is
appended. An instant it has not published within the lag is skipped; a failed
publication is retried until then. Its life ends when the recordings complete or at
the supervisor's own end. It serves batch definitions only, follows one recording per
feed, and writes only the feature store and the Feast generation root. Because the
publisher counts served candidates' fields, a source starts its trades capture when
a served stream reads trades. The cadence cannot exceed source freshness or
capture idle time. The supervisor loads every instance before starting and checks its candidate,
policy, model and feature identities against the signed deployment.
`alpha-execute deployment-check --config ... --candidates ...` loads every configured
candidate without starting anything and prints those identities, for authoring and
checking the signed deployments. The supported local envelope is at most four
accounts, eight source processes (a trades capture counts as one) and sixteen
candidate instances. Invocations
are bounded by each account configuration's signed service life (120 seconds unless
declared). These resource ceilings are not throughput qualification.
`fixed_clip`, `liquidity_clip` and `target_clip` are different engineering formulas,
not profitability recommendations. The two clip formulas price on the tick grid of the
instrument limits in the instance's installed account: the opening clip bids 200 bps
through the ask, rounded up to a tick, so it stays marketable against the scenario's
modeled adverse cost at any price level; later interests rest one tick below the best
bid, or at a bid of a single tick.

`target_clip` requests the same absolute target at every decision instant. The account
lowers an unmet target to one immediate-or-cancel buy at the ask, so the target is
reachable only in a scenario whose modeled adverse cost is zero. Once the target is
held, a checkpoint commits as `target_matched` without an order. A held position still
needs the account reconciled within its state-age budget.

All native books are retained and validated. Each candidate decides at its grid
instants from the latest eligible market at or before the instant, and the book
that crosses an instant matches orders; books between instants update monitoring
marks without fills or checkpoint changes. Source invalidation still protects
accounts immediately. Delivery records retain decided instants for exact replay.
This grid-selected paper model does not establish sustained native-feed capacity.

After installing, authorizing, reconciling and claiming each account separately,
start its signed owner service using the
[account command](execute-application.md#bounded-account-owner-service). Then use the
full installed research distribution for the source/policy supervisor:

```sh
alpha-execute deployment --config /absolute/services.json --owners /absolute/owners.json \
  --root /absolute/service-state --socket /private/tmp/paper-supervisor.sock
alpha-execute deployment-control --socket /private/tmp/paper-supervisor.sock \
  --request /absolute/operator-control.json
```

`owners.json` encodes `PaperServiceOwners(owners=...)`. Operator control files encode
`PaperServiceControl(action=..., identity=..., subject=...)`; actions are `inspect`,
`stop_instance`, `restart_instance`, `stop_source`, `restart_source` and `shutdown`.
The supervisor reserves the last fifth of its life, at most five seconds, for draining.
During that drain reserve it answers only `inspect` and `shutdown` and
refuses the rest; when it starts that drain itself, it keeps answering until a
`shutdown` arrives or its deadline is half a second away.
Instance/source actions name their configured subject. A repeated control identity
must retain identical content. Restarting a source provides fresh synchronization
and may settle accepted obligations; it does not clear the account stop or authorize
new decisions. Instance restart still checks journal reconciliation and independent
account protection. `shutdown` stops children and requests account service stops.

`restart_instance` may carry one complete typed `AccountObservation` in its optional
`observation` field for the named instance's account. The supervisor sends that
independent observation to the current signed owner and requires a successful
reconciliation immediately before the restart command, before scheduling another
source cohort. A mismatched or rejected observation starts no worker; omitting it
retains the journal's existing reconciliation requirement. A lost account response
is uncertain and is never retried automatically. A successfully applied control
retains the full observation, so changed reuse of its identity is rejected.

The root retains immutable configuration revisions, native captures, fsynced
delivery envelopes, socket requests/results, operational events and `status.json`.
`monitoring/<account>.json` contains the account and strategy cost/valuation report;
`monitoring/telemetry.sqlite3` uses the existing telemetry query/dashboard APIs. It
also holds each deployed candidate's runtime metrics (its packaged metric component
over the instance's attributed fills, opening and terminal marks), its decision
delays from the delivery logs and a learned candidate's predictions. Every 60 s the
diagnostics process renders each paper account's pages under
`monitoring/dashboards/<account>/`, with one alert rule per declared candidate
warning band. A breach is delivered to `alert_socket` through the `alerts.sqlite3`
journal and repeats once per rendering while it lasts.
Liveness, source quality and economic progress have separate observations. Failed
or stale monitoring does not establish healthy execution and does not retry it.

To add a provisioned inactive instance, stop the supervisor and services, change
only the active selection, increment `revision`, and set `previous_sha256` to the
previous configuration identity. Preserve the service root and account journals.
Reconcile and explicitly claim new owner generations, start their services and
launch the successor configuration. Existing account, source, policy and checkpoint
identities remain exact. An unknown instance, changed policy, instrument, budget or
account configuration is incompatible; this procedure never resets a journal or
silently migrates economic state. An unprovisioned signed definition requires its
own compatible installation procedure.

Each account target has one atomic journal budget. Multiple strategies/instruments
within that target share risk and compatible netting. Isolated targets and USD/USDT
have independent budgets; no atomic cross-journal firm limit or implicit FX is
claimed. Policy loss triggers selective stop; source loss conservatively faults
dependent accounts; owner loss terminates every dependent policy before recovery.
Unrelated accounts continue only within their own source and authority controls.
An error while committing or retaining a cohort is an uncertain account outcome,
even if a policy process also died. It faults the account and is never retried.
