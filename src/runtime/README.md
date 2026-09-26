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
their runtime rendering/alert routing remains MR12.

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

`CandidateFeatureFeed(store, bridge=..., serving_root=...).evaluate(session, at)`
consumes the packaged `FeatureStoreDefinition` and a deployment-pinned immutable
materialization. Offline reads match the authoritative PIT value at that cutoff;
online reads also verify the actual isolated Feast generation and active version.
Fitted store vectors are never transformed twice. Missing, stale, expired or lost
serving values pause with unchanged state. A version change pauses and requires
an explicit new binding. No fallback recomputes a different definition.

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

## Shared decision runtime

Owner: `runtime`; account admission, tagged orders and portfolio coordination
belong to [`execution`](../execution/README.md). Application composition belongs
to [`applications.paper`](../applications/paper/README.md). This local
paper/shadow increment reuses the public `strategies.DecisionPolicy` and
`DecisionSession` contracts for a selected set of account instances. It does not
load candidates or grant execution authority.

`SharedStrategyBinding` pins an instance, account, entity, policy,
`PortfolioContext` and maximum fee. Construction checks that the configured
instance owns the account and entity and that the fee uses the account's
valuation currency. `SharedStrategyInput` supplies that instance's causal
`DecisionContext` and an `AccountQuote`; the quote must be no later than the
decision, and the journal independently verifies it was observed for risk use.
The application supplies an explicit batch identity, a UTC coordination time
later than each decision, and a crossing policy.

`SharedDecisionRuntime.evaluate()` orders inputs by instance ID and evaluates
each policy in its own `DecisionSession`. Session identity binds the selected
account configuration, instance, entity, policy, portfolio context and fee
reserve. Target/exposure and order/quote decisions both pass through the same
independent account admission. Policy continuations use the
`shared-decision-v1` checkpoint and are committed with their portfolio batch.
Each request carries the digest of the previously saved instance checkpoint;
the account transaction checks that precondition before committing, so a stale
concurrent decision cannot overwrite a newer policy state. Exact batch retries
reopen their saved result, while changed input bytes or an incompatible restored
binding fail closed.

The shared runtime stages decisions only. It does not observe markets, reconcile
accounts or synthesize order events; those facts remain explicit inputs to the
account journal. A business rejection has no partial account reservations; it
does retain the evaluated policy continuations and rejected outcome, so retry
cannot evaluate a different decision from the same state. Identity, policy and
stale-checkpoint preflight failures leave continuation unchanged. Retrying an
older accepted or rejected batch cannot rewind a newer checkpoint. The account
journal owns selective instance stop/restart
and retains reservations on shared physical orders until their terminal outcome
is established. The broader installed multi-instance deployment remains MR14.

## Paper candidate supervision

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
dedicated account/instance. `SharedDecisionRuntime` supplies a separate local
multi-instance decision path over a shared account journal; it consumes explicit
normalized account and order events and does not add a venue adapter or automatic
matching. Private execution/account adapters, production deployment, alert
routing and capacity qualification remain later work; paper matching is an
explicit model, not venue fill evidence.

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
restored for recovery inspection; this local operation provides no external
venue-generation or anti-rewind attestation.

The independent execution wheel includes only these workspace, identity and
supervision services plus bounded local telemetry. Candidate/research services
still require their owning research distribution. The
[operating runbook](../../docs/governance/operations.md#local-paper-operations)
and [execution command guide](../applications/execute/README.md#local-operational-commands)
own concrete procedures and selected commands.
