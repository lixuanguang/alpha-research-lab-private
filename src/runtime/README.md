# Runtime services and candidate binding

MR06's [trusted local installer](../../docs/governance/operations.md#trusted-local-installation)
is an administrative artifact consumer. It installs the independent collector
and execution-admission packages, fences installed invocations, and preserves
compatible current state during rollback. It does not convert these local
job/candidate services into deployed services. The full research distribution
retains this guide's APIs; the collector's smaller runtime surface contains
identity and supervision only. Optional research exports fail when their owning
distribution is absent rather than importing research into the collector closure.

Status: implemented local MR04 service. Owner: `runtime`. These services schedule
offline application work and preserve selected local stores. The application owns
the study, dataset or feature operation and supplies its handler; `runtime` owns
the durable queue, worker bounds and backup publication. The broader deployment
and online serving gates remain in the [roadmap](../../docs/roadmap/README.md).

`JobQueue(root)` provisions a local SQLite WAL queue and immutable result tree.
`submit(JobSpec)` binds a stable job ID to exact request bytes and four SHA-256
pins: installed implementation, resolved configuration, retrievable inputs and
worker environment. An identical submission reopens its state; changing any pin
under the same ID fails. The application should use
`ImplementationIdentity.sha256()` for the installed package and derive the other
digests from its resolved, versioned inputs. `secret_refs` accepts only
`secret://...` names. Keep credential values out of the request and all retained
artifacts; the selected handler resolves references privately.

`JobWorkerPool(queue, handlers, max_workers=..., implementation_sha256=...,
environment_sha256=...)` admits only matching installed and environment pins.
`run_until_idle()` executes currently due jobs; `serve(stop_event)` waits for
future due work and drains active handlers before exit. One pool owns a POSIX
worker lock, and at most `max_workers` handlers execute concurrently. Both run
methods acquire and release the pool fence themselves; callers do not wrap them
in a second pool context. Due times are persisted as UTC microseconds and the
service rechecks them after each bounded relative wait. A handler
implements `execute(spec, run) -> bytes`. `run.idempotency_key` is the stable job
ID, `run.attempt_index` identifies a retained retry, and `run.work_directory`
isolates local output files. `run.report_progress(completed, total)` persists
monotonic units. `JobQueue.read()` exposes status, attempt count, progress, next
due time, safe failure class and verified result bytes. `JobQueue.health()`
reports status counts, the earliest due job and whether a pool owns the worker
lock.

On success the pool verifies regular output files, writes a result receipt and
atomically publishes `results/<job_id>` before marking the job complete. After a
process loss, the next pool adopts a verified published result without invoking
the handler again. Unpublished attempts remain under `work/<job_id>/<attempt>`
for diagnosis. Retry uses a bounded attempt count and exponential delay. This
local transaction does not make arbitrary external effects exactly once: a
handler that calls another store or service must use the stable key for its own
idempotent commit or reconcile an uncertain outcome before retry. The
`applications.explore` study handler uses the retained attempt contract for
that boundary. Independent worker environments can be selected by application
handlers; the queue itself does not install packages or move credentials.

`cancel(job_id)` cancels queued work immediately. For running work it persists a
request that the handler can check with `run.cancel_requested()`. The pool checks
again before publishing a result. Cancellation cannot unwind an already
committed external effect or interrupt a handler in the middle of a bounded
operation. A late request may find the job already complete.

`WorkspaceBackup.create(source_root, backup_root, components=(...))` copies only
named component directories. Include the local `attempts`, `datasets`,
`features`, `artifacts` and `jobs` roots needed to reopen a study. The caller
must stop other dataset, feature and artifact producers before backup. The
backup refuses active nested attempt writers and job workers, fences job
submissions and cancellation, and holds SQLite write locks across selected
`*.sqlite3` stores while capturing them through SQLite's backup API. Immutable
receipt-bound Feast `*.db` generations are copied byte for byte so their saved
hashes remain valid. The backup compares source inventories before and after
copying. It records byte digests
and modes in a manifest, verifies the staged tree, then publishes the backup by
directory rename. `WorkspaceBackup.verify()` checks every saved file.

`WorkspaceBackup.restore(backup_root, destination_root)` verifies every source
byte, stages a copy next to an **absent** destination and publishes it by
directory rename. Reopen the restored attempt, dataset, feature and job stores
through their owners before switching any application reference. A backup covers
only the selected local directories; remote lakeFS, Feast or ClearML server
state needs its own quiesced volume/snapshot included in the selection or a
separate verified service backup. Do not restore over an active workspace.

## Candidate loading and intent evaluation

Owner: `runtime`; local candidate binding is implemented for MR05. Candidate
publication belongs to [`research.experiments`](../research/experiments/README.md#candidate-bundles).
`configuration.CandidateDeployment` selects a candidate digest, instance, entity,
start/cadence binding, input version, explicit capability selections and four
independent universes. Its `replay` and `runtime` modes emit intents only. This
placement record neither deploys a service nor grants trading authority.

`CapabilityRegistry` resolves separately typed market-data, reference-data,
calendar, valuation, account and execution requirements against environment-owned
`CapabilityProfile` declarations. It checks product, venue, calendar, mode,
channel/representation/depth, clocks, field units, freshness, operations, order
types and lifecycle. Named requirements permit several sources; selections can
differ between replay and runtime. Qualification is explicit (`fixture`,
`read_only`, `external`), and an external declaration requires an evidence
reference. Declarations are not conformance proofs. Existing `DataCapability`
transport admission remains with source adapters; it cannot infer projected
field units, decision clocks or execution support.

`CandidateComponents` accepts explicit registered `FeatureFactory`, `PolicyFactory`,
`TransformFactory`, `EstimatorFactory`, `MetricFactory` and `ChartFactory` mappings.
Each factory binds implementation bytes and decodes its own parameter schema.
`CandidateLoader(components, registry).load(bundle, deployment)` checks bundle,
installed code/environment, capability, feature/model signature and availability
before source or feature-service reads. It recreates the selected implementations
without a built-in fallback. Metrics and charts use the existing study interfaces;
their local rendering/alert routing uses the [monitoring interfaces](../telemetry/README.md).
External operating qualification remains MR12 work.

`applications.explore.run_candidate` accepts that bundle/deployment, factories,
registry, a `DecisionSource`, and an explicit UTC decision tuple. It returns a
`CandidateRunResult` with candidate, deployment and resolved-binding identities,
feature/prediction/intent traces and a combined checkpoint. A different source
adapter can supply runtime inputs with the same named signature; it retains its
own identity and true availability semantics. The installed reference workload
uses authored observations and establishes software parity, not live-input or
venue qualification.

`CandidateSession` stages the existing feature and policy state machines together.
Invalid outputs, undeclared order types and inference failures cannot partially
advance feature state. Checkpoints bind both states, their cutoff, warm-up count,
candidate, deployment and resolved profiles. Another instance, source version or
candidate cannot reuse them. Warm-up advances state while withholding intents.
A missing cadence pauses until the omitted input is supplied, or resets both
machines if the candidate explicitly selects reset. Restart restoration requires
the exact checkpoint schema; explicit reset starts a new session. The application
owns durable retention. `PaperCandidateRuntime` below connects these same sessions
to the MR07 durable order journal.

`ServedFeatures(store, bridge=..., serving_root=...).serve(candidate, at)` reads a
feature-served candidate's deployment-pinned stream (the deployment's
`source_identity` is the store's `stream_identity` for its packaged
`FeatureStoreDefinition` and `feature_version`). Offline serving needs a snapshot
exactly at the cutoff and matches the authoritative PIT value; online serving reads
the active version's latest snapshot by the cutoff within the candidate's declared
age and verifies that snapshot's isolated Feast generation. It returns a
`ServedFeature` (vector, stream, version, snapshot cutoff and identity) or the pause
reason: `future`, `stale`, `expired`, `missing`, `feature-version-changed` or
`feature-service-unavailable`. `verify` reopens a retained served feature's exact
snapshot and refuses a different value. `CandidateFeatureFeed` applies it to a
dedicated session. Fitted store vectors are never transformed twice; a pause leaves
state unchanged; a version change needs an explicit new binding; no fallback
recomputes a different definition.

The complete input schedule, fitted availability, current field signatures and
unsupported product/channel/order combinations fail before data work. Actual
intent values are checked again at each transition. Current accepted candidates
originate in bounded spot studies; generalized named inputs and registry axes
remain available, but other product economics are rejected until their owning
study/runtime adapters are implemented. OKX and Bitfinex read-only source evidence
remains MR01; private account/execution conformance remains MR11. Exact environment
matching currently precedes loading; independent deployable environments and
trusted compatibility admission are provided by MR06 for its independent operating
closures; the broader research release restriction remains open.

## Research extensions

A research extension is a project in `extensions/<name>/` with its own
`pyproject.toml` and `src/` package. It declares only external dependencies and
registers exactly one provider class under the `alpha_research.candidate_components`
entry-point group. The provider's `factories()` returns `ExtensionFactories`: feature,
policy, transform, estimator, metric and chart constructors by registered key.
`InstalledExtensions` finds the named installed distribution, verifies every file
against its `RECORD`, and uses the `RECORD` digest as the implementation identity of
every component it provides. A candidate definition therefore pins exact extension
code, and a changed install is refused. Components must construct without the
research reporting stack: a metric or chart imports study records inside `evaluate`.
The maintained [engineering extension](../../extensions/engineering-candidates/)
is the reference workload and template.

`InstalledExtensions.artifact(name)` returns the extension's installed `RECORD` as a
`StudyArtifact`, whose fingerprint is the extension identity; a study that retains
it pins the exact code a candidate will name. `CandidatePackager.publish` packages a
completed study: one `ComponentSelection` (registered key and JSON parameters) per
component the study used, each rebuilt through the installed extension and refused
if its identity differs from the study's. It also refuses a study that did not
retain the extension, derives requirements with `CandidateRequirements` (the rule
`AuthoredCandidates` uses), copies provenance from the attempt store, and reads the
published bundle back before returning its manifest.

`PaperCapabilities` declares what the supervised paper environment offers one native
book source: the five book fields, its freshness and receipt clock, reference data,
calendar, valuation, account and every paper intent family and order type. When the
source records public trades it adds a `trade` channel profile with the four trade
fields in the feed's own currencies and the feed's idle time as freshness. Packaged
candidates resolve their requirements against it rather than against their own
declarations.

## Shared decision runtime

Owner: `runtime`; account admission, tagged orders and portfolio coordination
belong to [`execution`](../execution/README.md). Application composition belongs
to [`applications.paper`](../applications/paper/README.md). Shared accounts run
the same candidate engine as dedicated paper and replay: every selected instance
binds a `LoadedCandidate`, and each step runs its feature, fitted transform,
estimator and policy together in one `CandidateSession`. Nothing here grants
execution authority.

`SharedStrategyBinding` pins an instance, account, entity, loaded candidate,
`PortfolioContext` and maximum fee. The candidate's runtime placement must name
the same instance and entity. Construction checks that the configured instance
owns the account and entity and that the fee uses the account's valuation
currency. `SharedStrategyInput` supplies that instance's causal `DecisionInputs`
and an `AccountQuote`; the quote must be no later than the inputs' cutoff, and
the journal independently verifies it was observed for risk use. The application
supplies an explicit batch identity, a UTC coordination time later than each
decision, and a crossing policy.

`SharedDecisionRuntime.evaluate()` orders inputs by instance ID and runs each
candidate step through its executor: `LocalCandidateExecutor` in process, or a
`ProcessCandidateExecutor` supplied by the application. A decided step reaches
the same independent account admission for targets, exposures, orders and quotes.
A warming step commits its continuation as an `OrderDecision` without an intent,
which reserves nothing and reports `no_intent`. A paused step commits nothing,
and a cohort that only pauses returns no batch. The continuation is the
`shared-candidate-decision` record: the full `CandidateCheckpoint` (feature
state, warm-up count, policy state), the step's feature vector, prediction and
decision, and the retry identities. The journal stores it as opaque bytes, so the
independently installed execution distribution never decodes research types.
Each request carries the digest of the previously saved continuation; the account
transaction checks that precondition before committing, so a stale concurrent
decision cannot overwrite newer state. Exact batch retries reopen their saved
result, while changed input bytes or a continuation of another binding fail
closed. A candidate whose restart rule is `reset` starts fresh at its first step
in each new runtime; `restore` resumes the journal's continuation.

The shared runtime stages decisions only. It does not observe markets, reconcile
accounts or synthesize order events; those facts remain explicit inputs to the
account journal. A business rejection has no partial account reservations; it
does retain the evaluated policy continuations and rejected outcome, so retry
cannot evaluate a different decision from the same state. Identity, policy and
stale-checkpoint preflight failures leave continuation unchanged. Retrying an
older accepted or rejected batch cannot rewind a newer checkpoint. The account
journal owns selective instance stop/restart
and retains reservations on shared physical orders until their terminal outcome
is established. The supervised service composition below uses this same boundary;
the [MR14 record](../../docs/roadmap/multi-instance-paper.md) owns its qualification.

## Paper candidate supervision

`SharedPaperCaptureObserver` connects the shared decision runtime above to native
public books through `LiveBookDecisionSource` and `BookRegistry`. The source
projects every book field the bound candidates read (`imbalance`, `ask`, `bid`,
`ask_size`, `bid_size`) from one canonical book under one name, clock and
freshness. Each candidate decides at its own UTC grid instants,
`starts_at + k * cadence`, as research studies and dedicated paper do. When the
first eligible book after an instant arrives, the due candidates decide at that
instant from the latest eligible market at or before it, whose quote the journal
observes. The batch coordinates at the instant plus one microsecond, so the
account's knowledge stays before the crossing book, and that book then matches
orders. New orders therefore first meet the next book. Books between instants
update monitoring only. An instant without a fresh market or complete inputs is
skipped, and the candidate's gap rule (`pause`, `reset` or `continue`) governs it.
`SharedBookDelivery` (`shared-candidate-delivery`) is persisted before effects
with each decided instant's inputs, quote and coordination clock, and whether the
book matched. Replay recomputes the grid and refuses a retained delivery whose
matching or decided inputs differ. Native invalidation blocks new independent
admission while preserving pending exposure.

Shared accounts also run feature-served candidates. `SharedStrategyInput` carries
either source `inputs` or a `served` feature, and both executors accept either. The
observer serves such a candidate at each instant through `ServedFeatures`; a pause
reason skips the instant like missing inputs and is kept in `feature_pauses`. The
delivery log retains the served vector and snapshot, and a replay reopens that
snapshot and refuses a different value. `AuthoredCandidates.load(served=...,
feature_version=...)` builds such a candidate; `PaperCapabilities(features=...)`
resolves its inputs against profiles derived from the registered store definition.

`PaperInputs` maps each declared input to a feed the source provisions: book fields
to the book, trade fields to the source's public trades feed when it records one.
Reference and non-book inputs reach paper candidates only through the feature
store, so a source-fed candidate declaring one is refused before any process
starts. With a trades feed the observer also holds a `LiveTradeDecisionSource`;
`observe_trades` retains each trade boundary with its delivery time in a sibling
`.trades.jsonl` log before applying it, and each decided instant reads both sources.
A replay delivers both logs into fresh sources in delivery-time order, trades first
at equal times, through `deliver_trades` and `deliver`. Mixed grids on one observer
read the sources in ascending instants, because a live source freezes its cutoffs. See the
[automatic paper application](../applications/paper/README.md#automatic-public-input-accounts)
for retention, last-bid cost reports and explicit recovery boundaries.

The supervised source pipe decodes a private book schema whose strict typed
decoder validates each native `Level` and `Order` once. It then checks all book
coordinates, quality, representation and uniqueness constraints before the
observer consumes it. Public delivery, observation, depth, dataset and simulation
entries explicitly invoke recursive `BookObservation` validation, including for
a decoded row later modified through an unsafe mutation. The retained wire
fields and native state are unchanged.

The decision source keeps each historical native book as complete encoded bytes
inside its existing bounded history. Current-state inspection uses the latest
decoded book; historical decisions decode the selected row and retain the first
frozen decision at an equal cutoff. Controls carry the same market payload with
its original age. This avoids cyclic-GC scans over every historical level and
decimal without discarding native fields, revisions or causal boundaries.

Every native record is retained, reconstructed and validated in source order. A
valid book that is momentarily one-sided or crossed between per-order messages,
and the heartbeats or controls that follow it, has no eligible market. It faults
the account only if no eligible market arrives within the smaller of source
freshness and capture idle time, measured on retained delivery clocks. This is a
grid-selected paper model, not a measured feed or throughput capacity claim.

`ReferenceCandidates` packages the installed `fixed_clip`, `liquidity_clip` and
`target_clip` formulas over the native touch (ask, bid, ask size) as complete
candidate definitions without research provenance; they carry state across
missed instants. `AuthoredCandidates` does the same for any supplied feature
kernel and policy, for authored workloads and tests. Admitting a
provenance-free candidate is the calling application's decision.

`PaperConfiguration.execution` selects a required versioned scenario. The dedicated
journal pins its bytes and atomically commits each quote, modeled events and
same-touch liquidity debt. Entry and cancel delays use later eligible received
quotes; effective prices include adverse movement within the order limit, with
half-even quote fees. This top-of-book model has no exchange response clock or
queue position.

Owner: `runtime`; application composition belongs to
[`applications.paper`](../applications/paper/README.md), order state and modeled
fills to [`execution`](../execution/README.md). `PaperConfiguration` pins the mode,
dedicated account, initial currency cash, instrument, exact spot grids, maximum
position, maximum fee per order, modeled fee rate and quote freshness. This local
paper/shadow configuration does not carry executable authority.

`PaperCandidateRuntime` admits a `LoadedCandidate`, configuration, journal and
either its source or `CandidateFeatureFeed`. `open(owner=..., at=...)` obtains
the journal's process fence, restores the combined checkpoint, and delivers
pending order/account callbacks before a start/recovery event. `release()` leaves
unresolved orders and reservations intact. Candidates require `on_restart=restore`;
a changed candidate, deployment, source binding, configuration or state schema
cannot silently adopt another continuation.

Quotes claim their exact identity/bytes before any matching effect. On reopening,
the runtime finishes interrupted claimed quotes before advancing its clock to the
recovery event, preserving already posted fills and delivering their callbacks
once. Reusing a quote identity with changed bytes fails even when its final
candidate callback had not committed.

Policies may implement `strategies.DecisionLifecycle.on_event(event, state)` for
start, recovery, market, timer, order, account, fault and stop callbacks. These
callbacks are pure state transitions, validated and checkpointed like decisions.
Order callbacks retain a durable cursor and the account balance at each event,
so replay cannot expose a later fill balance to an earlier callback. A callback
failure leaves its cursor unadvanced. Independent block/stop state persists
before its callback, even if the policy fails.

`market(PaperMarket)` admits a received quote, runs the paper matcher, drains
order/account events and checkpoints the market callback. Shadow mode records
orders without matching. `timer(identity=..., at=...)` evaluates at an admitted
UTC cadence; its checkpoint, observed input/result bytes and all resulting child
orders commit together. An identical timer reopens its saved result. Missing
input, stale quote, feature expiry/service loss, changed serving version, an
uncertain order or account break pauses new decisions. A paused cutoff may be
retried under a fresh timer identity; a successful cutoff cannot run twice.

`order`, `cancel`, `reconcile`, `block` and `stop` are separate operations.
Reconciliation compares independently supplied paper cash, position and open
orders; it cannot certify a physical venue. A block suppresses decisions without
claiming cancellation or liquidation. Market/account clocks cannot regress;
late order facts retain their original event clock and are delivered no earlier
than the current runtime clock.
Successful account reconciliation clears only an account-break block. It cannot
clear an operator stop or independent fault block.

`PaperCaptureObserver` receives native books only after the collector durably
appends and reconstructs them. `LiveBookDelivery` retains raw receipt and separately
observed local delivery time. The observer journals that complete envelope,
updates `LiveBookDecisionSource`, and admits eligible best quotes for paper
matching. Its asynchronous scheduler emits real UTC cadence ticks. Delayed ticks
stay gaps governed by the candidate policy; receipt time is never rewritten to
hide download, persistence or scheduling delay. Replaying saved deliveries and
timer identities uses the same source, feature, policy, matcher and OMS classes.

The initial native binding covers OKX `books` L2 and Bitfinex `R0` L3 spot input.
The generic candidate source/feature interfaces retain named multi-source inputs.
The live convenience application currently binds one book source and one
dedicated account/instance. `run_live_shared_paper` additionally connects the
existing shared decision/account runtime to the native adapters and automatic
paper matching for one selected account/instrument. Its default per-book decision
cohort remains available; supervised services use the explicit selected-book
cadence above. Authenticated private adapters
retain scripted software evidence and KIV qualification; production deployment,
alert routing and capacity remain separately owned. Paper matching is an explicit
model, not observed venue fills.

MR10 adds `PaperCandidateRuntime.fault` and explicit `resume`. Live capture and
scheduler failures persist a block before releasing the owner fence, including
unhealthy completed capture summaries. Fault evidence retains observed UTC time;
its policy callback uses the current continuation clock so an interrupted claimed
market remains replayable. Each live invocation has a distinct fault identity.
Resume compares an exact `PaperCheckpoint`, requires a strictly newer independent
account reconciliation, and rejects unknown sends and pending cancellations,
including cancel/fill races. Reopening alone never clears a stop. If persistence
itself fails, the original failure stays visible and the run ends; the failed
write is not claimed as a durable block.

`ProcessSupervisor.run(..., protect=...)` optionally calls a parent-owned hard
control after terminating the child and before attempting alert delivery. It
retains whether protection succeeded or which exception class prevented it.
The callback must not depend on a strategy or telemetry. This is the existing
bounded local watchdog, not a deployed account service or venue owner.

## Account workspace recovery

`AccountWorkspace(config, component="state", journal_name="accounts.sqlite3")`
uses `WorkspaceBackup` to snapshot the entire selected account directory. Backup
checks explicitly stopped/faulted account phases after acquiring the selected
SQLite write locks. It retains unresolved orders, fills, checkpoints, controls
and the adjacent alert journal. Snapshot inspection uses the account owner's
immutable SQLite mode, preserving hashes and excluding WAL sidecars.

`restore(backup, destination, expected_manifest_sha256=...)` verifies the selected
digest, complete inventory, exact configuration and state schema, then validates
the staged account before publishing an absent workspace. Running accounts,
corrupt bytes, incompatible config and existing destinations fail closed.
Restoration does not replace the current installation or rewind its journal.
Keep compatible signed artifacts/trust separately and reconcile missing facts
before any explicit selection and restart. An older stopped snapshot can be
restored for recovery inspection; managed paper quarantines a restored journal
before publication, so it cannot resume, claim, reduce or match from that copy.
This local operation provides no external venue-generation or anti-rewind
attestation.

The independent execution wheel includes only these workspace, identity and
supervision services plus bounded local telemetry. Candidate/research services
still require their owning research distribution. The
[operating runbook](../../docs/governance/operations.md#local-paper-operations)
and [execution command guide](../applications/execute/README.md#local-operational-commands)
own concrete procedures and selected commands.

Managed paper public-input runtimes consume the execution-owned `PaperAccount`
protocol, implemented by a local journal or `InstalledPaperAccount`'s signed
command adapter. The protocol does not replace accounting or independent risk.
A managed finite capture stops at completion and records recoverable faults on
source failure. Fresh public data, independent reconciliation and a new owner
claim are required before a replacement worker creates exposure. Expiry or
revocation blocks new exposure and restart, while the original current owner may
drain existing obligations on fresh eligible data. Accepted standing orders keep
their reservations until terminal outcomes are established. A replacement grant
requires a stopped account and settled physical order outcomes before a new owner
claim. The activation record retains the signed local drills and does not
claim deployed-service recovery qualification.

`AccountWorkspace.restore` now quarantines the staged restored journal before
atomic publication. A managed snapshot remains inspectable but cannot resume
execution because it cannot establish whether a newer journal has committed
additional economics. Local restart and compatible signed code rollback use the
latest retained journal; restoring a historical copy over an active state is
unsupported. The [activation record](../../docs/roadmap/paper-activation.md)
separates this local boundary from future deployed-service disaster recovery.

## Supervised candidate processes

`ProcessCandidateExecutor` runs each candidate step (feature, transform,
estimator and policy) in a spawned process. The parent retains the
`SharedDecisionRuntime` cohort and the continuation transaction. The child
receives only causal inputs and the committed checkpoint; it has no account
client or ability to transfer another instance's ownership. A two-second response
budget bounds a stalled candidate, which raises `CandidateProcessFailure`, and the
parent fences it before selective controls. Process heartbeat remains distinct
from step completion.

The [paper service application](../applications/paper/README.md#supervised-local-deployments)
owns source and instance selection, process lifetime and operator controls. It
reuses `ProcessSupervisor.heartbeat`, `HealthMetrics`, `HealthPolicy`, native book
adapters and the existing book registry. Each source delivers persisted native
records in order. Independent account sets can progress concurrently with one
observation in flight per source; shared-account sources retain serial order.
All observations join before lifecycle or status changes. The
[execution service](../applications/execute/README.md#bounded-account-owner-service)
owns completion wakeups, health deadlines and bounded shutdown. Native retention,
fsync and account/policy timeouts remain unchanged. Separate source processes do
not share a global mutable active instrument. A replacement source starts
unsynchronized.

`SocketPaperAccount` implements the same `PaperAccount` contract through the signed
account-owner service. It does not retry an uncertain response. A local scheduler
fence is scoped to each account socket, in addition to the signed installation
fence and durable journal generation. Every supervisor relaunch requires a fresh
reconciled owner generation, even when a different output root is supplied.
These services remain bounded local processes; the
[MR14 record](../../docs/roadmap/multi-instance-paper.md) owns qualification and limits.
