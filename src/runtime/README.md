# Runtime job and workspace services

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
