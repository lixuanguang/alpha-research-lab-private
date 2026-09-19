# Notebook setup, execution and troubleshooting

Owner: repository founder. Current retention guidance updated 2026-09-20. This is
the supporting operations guide. Start with the [researcher's guide](README.md) to choose a question and
understand the data. This page owns notebook setup, execution and source/output retention. The
[roadmap](../docs/roadmap/README.md#execution-and-maintenance) owns implementation
acceptance; the [research program](../docs/roadmap/research-program.md#notebook-research-and-package-promotion)
owns research methodology and promotion.

## Maintained source and output retention

Maintain two reader journeys under repository-root `examples/`:
[QR research](research-foundations.ipynb) and
[engineering diagnostics](infrastructure-diagnostics.ipynb), each with an explicit
[live version](#live-versions) alongside its offline entry point. The 2026-09-19 cleanup
consolidates the old reliability/capture notebooks and removes infrastructure
milestone sections from the QR path. The earlier activity-based and source-retention
decisions still apply: extend working content by activity, not by MR, and create
another notebook only when a distinct implemented reader journey warrants it.

Maintained `.ipynb`, `.py`, `.md` and the reviewed measurement JSON under
`examples/evidence/` remain versioned. Generated runs, checkpoints and temporary
kernels remain ignored. Former notebook source/outputs remain retrievable from Git
history; their removal from the current catalog does not delete saved data or runs.
The existing runner remains the only notebook execution wrapper.

1. Import the installed candidate from the pinned interpreter. Keep notebook
   tooling in an explicitly identified development environment/kernel; do not
   silently change `uv.lock`, add runtime Jupyter dependencies or patch `sys.path`.
   Confirm interpreter, package location and identity; refresh the install/kernel
   after source changes.
2. Begin with a tiny synthetic or permitted saved sample and inspect meaningful
   clocks, identities, units and outputs. Exploratory calculations can remain
   local while investigated; formal promoted results call the versioned package.
3. For changed executable examples, exercise the applicable boundary case, restart
   the kernel and run all cells. Retain commands, identities, conclusions and
   limitations in the change or research record; promote decisive regression cases into
   focused tests. Unchanged code/output evidence need not be rerun for prose.
4. Before **each commit, push and merge to main**, review maintained notebook,
   runner and guide sources. Keep credentials, restricted/raw data and bulk
   exports outside Git. Reviewed small synthetic outputs may remain. Close
   finished kernels and preserve successful/failed snapshots under ignored
   `examples/runs/`; these are not a backed-up research journal.
5. Stage explicit maintained files. Check `git ls-files -- examples/` for intended
   source/reviewed outputs and use `git check-ignore` on generated paths. Do not
   force-add generated artifacts. Review notebook code, outputs and metadata for
   secrets, unintended data and stale execution claims.

Do not inspect the final holdout through an exploratory notebook. Retain every
real-data attempt influencing hypothesis or parameter selection, including failures
and abandoned comparisons, under the research program's
[trial record contract](../docs/roadmap/research-program.md#small-records-and-artifacts).
Until the shared journal is implemented, use an append-only text record beside
protected research outputs. Keep retrievable permitted raw/output references.

## Before executing

Use the pinned project interpreter and installed candidate, from the repository
root or `examples/`. The two offline versions default to synthetic local fixtures and
installed subprocess consumers. No venue connection, archive download, account
or credential is needed. The engineer's health exercise uses a temporary local
syslog socket and intentionally stops its own synthetic child collectors.

The QR notebook optionally opens `ALPHA_RESEARCH_DATASET_DIRECTORY`, which must
contain `raw/`, `snapshots/` and an authored `selection.json` of type
`ResearchSelection`. The public [selection reference](../src/market_data/README.md#discover-and-reopen-research-selections)
shows how to author the JSON after publication. Every referenced snapshot and raw
object must be retained; identities alone cannot restore deleted files.

```sh
export ALPHA_RESEARCH_DATASET_DIRECTORY='/absolute/path/to/retained-study'
```

Unset that variable for the default synthetic lesson. A supplied missing, invalid
or corrupt selection fails without fallback. Reports are written only to the
notebook's separate temporary workspace; the supplied study is read. The default
small entry/byte bounds must be reviewed for a larger intended study. Batch size
limits delivered rows, not total memory.

### Acquire and reopen permitted inputs

Acquisition is a deliberate source operation in the live versions or the installed commands.
It is outside the offline notebook runs.
Use the existing [trade acquisition/publication commands](../src/market_data/README.md#installed-acquisition-command),
[Bitfinex collector guide](../docs/data/l3-collectors.md#start-here) and
[OKX guide](../docs/data/okx-market-data.md#installed-commands). Check the selected configuration,
source access and retention before invoking them. For example, the maintained public
book routes are:

```sh
uv run --frozen --no-editable alpha-collect capture --config configs/live/bitfinex-btc-usd.json --output data/bitfinex
uv run --frozen --no-editable alpha-collect capture --config configs/live/okx-btc-usdt.json --output data/okx/live
uv run --frozen --no-editable alpha-acquire archive fetch --config configs/history/okx-btc-usdt.json --output data/okx/history
```

These commands contact the public sources and retain new bounded live recordings
or the selected historical archive. The configured historical archive is about
104 MiB plus working bytes; it is not downloaded by any maintained notebook. Command
budgets, completion and failure semantics belong to the linked source guides.
Do not treat a failed acquisition as a completed input or edit its manifest to
conceal a configuration mismatch.

Use `SavedCapture.read` for native saved recordings, `OKXArchiveStore.replay` for
the archive summary, and `DatasetPublication.publish_books` to publish bounded
native prefixes with retained raw bytes, then author a pinned book selection.
The [book publication reference](../src/market_data/README.md) owns parameters and
quality restrictions. A historical archive's missing receipt clock stays unknown.
The engineer notebook optionally reads a saved Bitfinex recording selected by
`ALPHA_BITFINEX_CAPTURE_DIRECTORY`. With no value, that section reports `SKIPPED`.
It requires a completed manifest by default; set the cell's `completed` value to
`False` only for a deliberate interrupted-prefix investigation. It never infers
that mode merely because a manifest is missing. No capture is initiated.

Existing `data/bitfinex/`, `data/okx/`, `data/binance-archives/` and ignored
`examples/runs/` are retained. Old `ALPHA_OKX_ARCHIVE_DIRECTORY`,
`ALPHA_BITFINEX_CAPTURE_DIRECTORY`, `ALPHA_BINANCE_DOWNLOAD` and
`ALPHA_BINANCE_DIRECTORY` no longer select the QR notebook's input. Historical
run snapshots retain their original environment-variable meaning. No latest-input
search or automatic source switch occurs in the current QR path.

## Live versions

[QR live](research-foundations-live.ipynb) and
[engineer live](infrastructure-diagnostics-live.ipynb) each initiate one new public
Bitfinex R0 capture when run. The selected [configuration](../configs/live/bitfinex-btc-usd.json)
allows 20 seconds of receipt, 10,000 messages, a 32 MB journal, 8 MB frames, queue
capacity 1,024, 100,000 visible orders, a 15-second idle bound and two retries.
The cells reject a different venue/channel or a receive interval above 20 seconds.
They retain and display the resolved config before the source call. Connection,
finalization and fsync can extend elapsed time; an 80-second outer child deadline
kills and waits for the process on timeout. No credentials or account endpoint is used.
Source meanings, use limits and recovery remain owned by the
[collector guide](../docs/data/l3-collectors.md#verified-source-contract).

Each execution creates an exclusive UUID study under ignored
`data/notebooks/research-live/` or `data/notebooks/infrastructure-live/`.
It retains attempt identity/question, copied config, exact command, stdout/stderr,
exit code when available, original capture, raw objects, bounded snapshots and a
pinned `selection.json`. The capture cell exclusively claims its attempt before connecting;
rerunning that cell without rerunning setup fails instead of overwriting its logs.
Only the first 32 raw positions are published, including controls. The whole finite native recording remains available. This is bounded
foreground development; no deployment, continuous service or trading is started.

A network, quality, publication or timeout failure stops the notebook, retains its
attempt and never switches to offline/synthetic input. Inspect its logs and the
explicit recording path. A missing completed manifest requires deliberately selecting
interrupted mode in the offline engineer notebook; do not infer success from files.
The existing notebook runner also archives the failed execution. Retain all real-data
attempts that influence research under the research program's trial contract.
Local ignored storage is not a backed-up journal.

Both live versions print paths for offline reopening:

```sh
export ALPHA_RESEARCH_DATASET_DIRECTORY='/absolute/path/to/printed-study'
export ALPHA_BITFINEX_CAPTURE_DIRECTORY='/absolute/path/to/printed-recording'
```

Run the respective offline version below. No capture is repeated and no mutable latest
alias is selected. The offline QR path reads a saved selection and inspects its values,
controls and earlier cutoff; its synthetic prototype remains restricted to the teaching
sample. The live QR version retains its explicitly declared R0 prototype in the study.
Both live versions ignore these offline input selectors and always create a new recording.

Live QR analysis uses exact rational arithmetic over native base quantities and retains
market-derived ratios locally in `prototype.json`. Maintained outputs show only reviewed
identities, counts and quality, not raw frames or market values. Before committing a live
notebook, strip market-derived outputs or retain only reviewed non-sensitive summaries.
The live engineer verifies full native replay and the selected canonical prefix. It uses
the foreground collector; independent watchdog/alert fault scenarios remain in the offline
version because the current supervised capture command refuses snapshot flags.

## Running a notebook

From the repository root, use separate pinned notebook tooling. The no-argument
runner defaults to the offline QR workflow. These commands execute offline synthetic
examples when their saved-input selectors are unset:

```sh
uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/research-foundations.ipynb
uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/infrastructure-diagnostics.ipynb
```

The live counterparts explicitly contact the public source and retain new local data:

```sh
uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/research-foundations-live.ipynb
uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/infrastructure-diagnostics-live.ipynb
```

The runner executes once by default. Append `--repeat 2` only when two
fresh-kernel runs are intended. Every attempted execution saves a distinct
notebook under `examples/runs/<notebook-name>/<attempt-id>.ipynb`, with source
hash, start/end times, execution status and available outputs. An execution error
is archived and returns a nonzero exit; remaining repetitions stop. Successful
execution also refreshes the selected working notebook's outputs. Kernels are shut
down and temporary kernel files are cleaned up. The working notebooks and runner
are maintained alongside the package.

For interactive exploration, select this repository's `.venv/bin/python` kernel,
restart and run all before interpreting a result. Interactive edits are not
automatically archived: use the route-specific runner command before replacing an
experiment's conclusions. These ignored local snapshots are a convenience, not a
backed-up trial journal or the future packaged research runner. Preserve
influencing real-data attempts with the research program's trial fields and
protected input/output references.

To verify the same editor interpreter using separate runner tooling, use the
route-specific notebook path with:

```sh
uv run --frozen --no-sync --with 'nbclient==0.10.4' --with 'nbformat==5.10.4' \
  python examples/run_notebook.py examples/research-foundations.ipynb --kernel-python .venv/bin/python
```

For engineering diagnostics, replace the notebook path in that command with
`examples/infrastructure-diagnostics.ipynb`. `--no-sync` preserves the editor's
installed kernel/tooling while the command adds the runner tools in uv's separate
environment. The notebook checks the runtime package's installed bytes against
the checkout before interpreting any result.

No new project runtime dependencies or `sys.path` changes are needed.

## Interactive kernel and import repair

The kernel requires `ipykernel` and the installed runtime package. The notebooks
use the already-locked pandas dependency for small tables.
`nbclient`/`nbformat` are runner tooling, so their absence from an interactive
kernel is permitted and recorded accurately in the notebook table.

After switching to source that adds or changes a module, refresh the installed
candidate in the interpreter selected by the editor, then restart that kernel and
run all cells. `--no-sync` only preserves an existing installation; it does not
install new source. The package version remains `0.1.0` across source changes, so check
installed file identity instead of treating the version string as proof that the
current candidate is installed.

The notebooks compare the complete installed runtime inventory and bytes.
Their installed subprocess consumers select commands beside the kernel interpreter
rather than trusting a different environment on `PATH`. If that check fails,
install a clean wheel environment and restart; a
matching package version or matching subset of files is insufficient.

## Where the detailed checks live

Use the [QR walkthrough](README.md#follow-the-connected-dataset-walkthrough) for
the research stages. The engineer notebook diagnoses installed runtime identity,
configuration/temporal contracts, acquisition and publication interruptions, native
session recovery and independent health supervision using the existing consumers.
Its final interpretation maps failures to functional owners and focused commands;
it is not a replacement for the hosted validation lane.

A replay cursor binds source identity and progress. Stateful consumers must also
retain their own state and pending schedules. Collector recovery preserves unknown
gaps and requires fresh source synchronization. None of those checks qualifies
strategy accounting, external source coverage or deployed incident response.

## Query workload evidence

The engineer notebook inspects the retained workload record, with its original
revision and fingerprint. It does not time current code or silently rerun the
representative benchmark. The former QR backend section has moved out of the
research journey. The historical conclusion remains scoped to its recorded
workload and code; a newer lock/runtime requires new measurement before claiming
current performance.

The standalone [driver](query_workload.py) requires macOS (its process high-water RSS is in bytes),
an installed candidate, and a directory containing the retained `raw/` and
`snapshots/` stores. It reads existing inputs only; it does not fetch data, rewrite
availability, publish snapshots or introduce a backend. Use the recorded snapshot,
not a latest alias. Missing bytes fail explicitly.

To repeat against an isolated candidate, build/install with the frozen wheel-smoke
procedure in the [architecture guide](../docs/architecture/README.md#build-setup-and-ci-contract), copy `query_workload.py` outside the checkout, and run
from that directory. Keep other tests/notebooks idle during timing:

```sh
cd /absolute/path/to/isolated-query-workload
./reuse-installed/venv/bin/python -I query_workload.py permitted timing > reuse-timing-1.jsonl
./reuse-installed/venv/bin/python -I query_workload.py permitted timing > reuse-timing-2.jsonl
./reuse-installed/venv/bin/python -I query_workload.py permitted timing > reuse-timing-3.jsonl
./reuse-installed/venv/bin/python -I query_workload.py permitted io > reuse-reads.jsonl
```

Each timing process fully verifies and loads once, then measures ten serial cycles
of three queries. The separate I/O process counts returned binary bytes including
raw verification and ZIP access; its instrumented times are excluded from acceptance.
Retain every attempt. Compute nearest-rank percentiles across all thirty observations
per query and compare all three loads and process RSS peaks with the fixed budgets.
Do not relabel the OS file cache as cold or infer device traffic from application
read counts. The full-hour history query returns 27,480 revisions; its cutoff returns
zero eligible trades with degraded evidence. Neither result proves historical
availability or membership.

Local bulk inputs and generated run snapshots remain outside Git. Maintained
Python, Markdown and notebook sources stay tracked; the small
[measurement summary](evidence/query-workload-measurements.json) contains identities, counts
and timings, not raw market rows. It remains a historical result, not a new benchmark.

The optional columnar experiment requires `duckdb==1.5.5` only in an isolated
`uv run --with` environment; the normal notebook and installed reference reader do
not require it. Copy `query_columnar_candidate.py` outside the checkout. Its
`convert`, `scan`, `verify` and `io` operations take the same input directory.
`convert` refuses an existing output; preserve each failed candidate in a separate
experiment directory before retrying. `verify` compares every complete revision
payload with canonical source bytes and checks exact codec round trips. `io` saves
DuckDB profiles separately from timings. The Parquet scan is a bounded experiment,
not a supported backend: it does not implement cutoff, controls, membership or
verified loading, and its metrics must not be presented as end-to-end query parity.
Retain commands, candidate identities, failures and the admission decision beside
each new benchmark attempt.
