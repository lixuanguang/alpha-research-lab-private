# Runtime services and candidate binding

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
owns durable retention; this is not the MR07 order journal or supervised OMS.

`run_candidate_feature(session, store, at=..., bridge=..., serving_root=...)`
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
trusted compatibility admission remain MR06.
