# Notebook setup, execution and troubleshooting

Owner: repository founder. Current retention guidance updated 2026-09-19. This is
the supporting operations guide. Start with the [researcher's guide](README.md) to choose a question and
understand the data. This page owns notebook setup, execution and source/output retention. The
[roadmap](../docs/roadmap/README.md#execution-and-maintenance) owns implementation
acceptance; the [research program](../docs/roadmap/research-program.md#notebook-research-and-package-promotion)
owns research methodology and promotion.

## Maintained source and output retention

Use long-lived activity notebooks under repository-root `examples/`: fetching,
EDA, strategy research and monitoring as working content appears. The founder's
2026-09-13 activity organization and 2026-09-14 source-retention decision remain
in force. Maintained `.ipynb`, `.py` and `.md` examples and the consumed, reviewed measurement
JSON under `examples/evidence/` are versioned; generated
run snapshots, checkpoints and temporary kernels remain ignored. Do not create
an empty notebook per future capability or a notebook per MR.

| Activity | Notebook responsibility | Maintained package boundary |
| --- | --- | --- |
| Data fetching | Explore permitted requests, responses, clocks and quality | Shared adapters, validation, immutable storage and acquisition |
| EDA | Inspect coverage, missingness, alignment and candidate features | Reusable selection/quality/feature operations when consumed |
| Strategy research | Prototype and compare features, models, rules and economic assumptions | Versioned components and shared fit/backtest/report workflows |
| Monitoring | Inspect attributed results and runtime observations | Persistent metrics, alerts and controls when implemented |

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

Use the pinned project interpreter and installed candidate. Run commands from the
repository root. The primary notebook now reads saved OKX historical and Bitfinex
live book inputs without network access. With no saved inputs, run the capture
notebook first. It records Bitfinex and OKX public feeds sequentially for bounded
20-second samples, then downloads the configured OKX historical archive. No API
keys, exchange account or secret file is used. The offline foundations lab also
makes no source requests; its retained Binance/Tardis fixtures are synthetic.

A changed configuration needs a matching saved request. A missing match is
expected; acquire the intended sample or restore the compatible configuration.
Never edit a manifest to disguise a mismatch or delete old inputs to make a check pass.

Keep local raw files with their requests, settings and completion records. New
inputs go under ignored `data/bitfinex/<recording-id>/`,
`data/okx/live/<recording-id>/` and `data/okx/history/<archive-id>/`. Each completed
directory retains its request, manifest and original bytes. There is no automatic
expiry or Git backup. A failed acquisition is preserved separately; it cannot
stand in for a completed input. See the [collector guide](../docs/data/l3-collectors.md)
and [OKX guide](../docs/data/okx-market-data.md) for budgets and failure behavior.

Without path overrides, the primary notebook selects the latest completed input
whose request matches the maintained config, using manifest `ts_ingested` (path
as tie-breaker). It prints the selection before verifying and replaying it. This
exploratory default can change after acquisition; it is not a dataset version.
Corrupt selected inputs fail, with no fallback. To pin a study, set both paths to
the actual directories printed by a successful acquisition:

```sh
export ALPHA_OKX_ARCHIVE_DIRECTORY='/absolute/path/from/archive_directory'
export ALPHA_BITFINEX_CAPTURE_DIRECTORY='/absolute/path/from/bitfinex/capture_directory'
```

The primary notebook requires those requests to match the maintained configs.
The capture notebook honors only the OKX override: it verifies and reuses that
archive while still making **new live captures**. Unset the OKX override to test a
new historical download. There is no Bitfinex historical-download adapter here.

Old `data/binance-archives/` files and the frozen P1 specification are retained.
`ALPHA_BINANCE_DOWNLOAD` and `ALPHA_BINANCE_DIRECTORY` no longer control the active
notebooks; earlier run snapshots keep their original meaning.

## Running a notebook

From the repository root, use the pinned project interpreter and separate notebook
tooling. The no-argument runner defaults to saved order-book inspection;
the explicit paths make the selected route reviewable.

Primary saved-input workflow (no network):

```sh
uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' --with 'matplotlib==3.10.8' python examples/run_notebook.py examples/research-foundations.ipynb
```

Offline detailed boundary companion:

```sh
uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/foundation-contract-checks.ipynb
```

Acquire public books (network access, two new recordings, new archive unless overridden):

```sh
uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/market-data-capture.ipynb
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

For the offline lab, replace the notebook path in that command with
`examples/foundation-contract-checks.ipynb`. `--no-sync` preserves the editor's
installed kernel/tooling while the command adds the runner tools in uv's separate
environment. The notebook checks the runtime package's installed bytes against
the checkout before interpreting any result.

No new project runtime dependencies or `sys.path` changes are needed.

## Interactive kernel and import repair

The kernel requires `ipykernel` and the installed runtime package. The primary
notebook also requires `matplotlib==3.10.8` for its synthetic EDA plot.
`nbclient`/`nbformat` are runner tooling, so their absence from an interactive
kernel is permitted and recorded accurately in the notebook table.

After switching to source that adds or changes a module, refresh the installed
candidate in the interpreter selected by the editor, then restart that kernel and
run all cells. `--no-sync` only preserves an existing installation; it does not
install new source. The package version remains `0.1.0` across source changes, so check
installed file identity instead of treating the version string as proof that the
current candidate is installed.

The primary notebook compares the complete installed runtime inventory and bytes,
and selects the dataset command beside the kernel interpreter rather than from
`PATH`. If that check fails, install a clean wheel environment and restart; a
matching package version or matching subset of files is insufficient.

## Where the detailed checks live

Use the [QR walkthrough](README.md#follow-the-connected-dataset-walkthrough) for
the primary notebook's sections and interpretation. The offline lab covers units,
clocks, corrupted input, interrupted writes and acquisition recovery. The
[test guide](../tests/README.md) identifies focused and isolated installed consumers.

A replay cursor binds source identity and progress. A stateful consumer must also
retain its own state, pending schedules and applied event identities. Do not infer
economic restart parity from the source-cursor example. Collector recovery preserves
unknown gaps and requires fresh source synchronization; publication retains the
source's declared quality scope.

## Query workload evidence

Section 9 of `research-foundations.ipynb` recomputes the backend decision from the
small retained measurement record. It checks installed runtime, lock and benchmark
driver fingerprints; it does not silently rerun the expensive representative
benchmark. Sections 7–8 still execute the synthetic correction, scoped-control,
cancellation, invalid-clock, byte-limit and mutable-ID examples in the fresh kernel.

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
