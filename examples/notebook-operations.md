# Notebook setup, execution and troubleshooting

Owner: repository founder. Updated 2026-09-18 for MR 21. This is the supporting operations
guide. Start with the [researcher's guide](README.md) to choose a question and
understand the data. The [roadmap](../docs/roadmap/README.md#local-notebook-workflow)
owns notebook retention and acceptance; this page explains the existing tools.

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
notebook also requires `matplotlib==3.10.8` for its MR 21 synthetic EDA plot.
`nbclient`/`nbformat` are runner tooling, so their absence from an interactive
kernel is permitted and recorded accurately in the notebook table.

After switching to source that adds or changes a module, refresh the installed
candidate in the interpreter selected by the editor, then restart that kernel and
run all cells. `--no-sync` only preserves an existing installation; it does not
install new source. The package version remains `0.1.0` across these MRs, so check
installed file identity instead of treating the version string as proof that the
current candidate is installed.

Historical environment failures and repairs are retained in the
[M0 import record](../docs/roadmap/m0-implementation.md#interactive-notebook-import-repair),
[MR 04 record](../docs/roadmap/mr-04-implementation.md#editor-environment-repair-before-merge)
and [MR 05 record](../docs/roadmap/mr-05-implementation.md#duplicate-file-cleanup).
MR 21 found extra duplicate runtime files in the existing development environment;
its final acceptance uses a clean external wheel installation. The primary notebook
now compares the complete installed runtime file set as well as file bytes, and
selects the dataset command beside the kernel interpreter rather than from `PATH`.
If that inventory check fails, use a clean wheel environment and restart; do not
interpret a matching package version or matching subset of files as acceptance.

## Where the detailed checks live

These references explain implementation and retain historical test evidence;
they do not change what a source proves about the market.

| Research concern | Notebook location | Engineering record |
| --- | --- | --- |
| Time, instrument identity and exact amounts | Offline lab, sections 4–7 | [Frozen case](../docs/research/p1-baseline.md) |
| Selecting the intended saved observations | Offline lab, section 10 | [M0](../docs/roadmap/m0-implementation.md) |
| Changed or truncated files | Offline lab, section 11 | [MR 03](../docs/roadmap/mr-03-implementation.md) |
| Interrupted writes | Offline lab, section 12 | [MR 04](../docs/roadmap/mr-04-implementation.md) |
| Download failures | Offline lab, section 13 | [MR 05](../docs/roadmap/mr-05-implementation.md) |
| Resuming collection | Offline lab, sections 14–15 | [MR 06](../docs/roadmap/mr-06-implementation.md), [MR 07](../docs/roadmap/mr-07-implementation.md) |
| Equal-time rows, empty content and missing archives | Offline lab, section 16 | [MR 08](../docs/roadmap/mr-08-implementation.md) |
| Separate dataset inputs, duplicates and quality scope | Primary notebook, sections 5–6; [dataset tests](../tests/unit/data/test_datasets.py) | [MR 09](../docs/roadmap/mr-09-implementation.md), [MR 13](../docs/roadmap/mr-13-implementation.md), [MR 14](../docs/roadmap/mr-14-implementation.md) |
| Atomic publication and installed commands | Primary notebook, section 6; [snapshot tests](../tests/unit/data/test_snapshots.py) | [MR 15](../docs/roadmap/mr-15-implementation.md), [MR 16](../docs/roadmap/mr-16-implementation.md) |
| Corrections, membership and cutoff selection | Primary notebook, section 7; [as-of tests](../tests/unit/data/test_asof.py) | [MR 10](../docs/roadmap/mr-10-implementation.md), [MR 12](../docs/roadmap/mr-12-implementation.md), [MR 17](../docs/roadmap/mr-17-implementation.md) |

Historical checkpoint records below describe the notebook at each tested revision.
The current primary notebook combines NB 09–17 into sections 5–7; fixed fixtures and
engineering tests retain the detailed cases. New activity notebooks should grow
from working research needs; do not create empty fetching,
EDA, strategy or monitoring notebooks to represent planned capabilities.

## Researcher guide verification

This section records the earlier presentation-only change. The subsequent source
migration is recorded below; its executable cells and evidence supersede that
presentation snapshot for current use.

The 2026-09-16 presentation change is based on MR 08 commit `1a25b48`. It rewrites
the researcher entry guide and notebook explanations, collapses implementation
source cells with standard Jupyter metadata, and moves setup/repair guidance to
this page. Revert the documentation/notebook presentation commit to restore the
previous reading order and wording; no runtime or saved-data migration is involved.

Validation compares every code cell's ID, source, relative execution order,
execution count and outputs with that commit, and preserves each notebook's
`research_execution` record. All three notebooks pass nbformat schema validation.
Local Markdown links are checked for this guide, the researcher's README, the
roadmap and the narrative cells of all three notebooks. Executable code and
original outputs are unchanged, so existing behavioral evidence is reused;
no notebook execution, new live capture or archive download is claimed here.

Commands used for this presentation check:

```sh
uv run --frozen --no-sync --with 'nbformat==5.10.4' \
  python /private/tmp/researcher-guide-validation/check.py
uv run --frozen --no-sync alpha-governance-architecture
git diff --check
```

The first command used a local, temporary inspection script, not a new project
command. It called `nbformat.validate`, compared code/evidence fields against
`git show 1a25b48:examples/<notebook>.ipynb`, and used the existing
`ArchitectureGovernanceService.validate_local_links` on both guides, the roadmap
and extracted notebook Markdown. Results: three valid notebook schemas, all
**41 code cells** and their outputs/order unchanged, all selected local links valid.
The architecture command also passed for all 41 documents under `docs/`.

| Notebook | Retained successful attempt | What the retained evidence covers |
| --- | --- | --- |
| Historical trade data | `ee11fc43-8a05-4515-bcf9-32519f84675e` (2026-09-16) | The MR 08 candidate's installed reader, selected-hour inspection and controlled failures. |
| Offline reliability lab | `aa3cd64a-f768-4be5-adf2-973afcb9c5e9` (2026-09-15) | Its earlier installed implementation and synthetic foundation/acquisition checks; not a fresh run of the MR 08 candidate. |
| Order-book observations | `e332e7de-a068-4a69-9e32-afe51a7e3c05` (2026-09-16) | The recorded collector implementation, bounded source attempts and historical prefix; not a new capture or current access check. |

The execution records' source digests identify their original notebooks before
this prose edit. Rerunning through the normal runner will create a new source
identity and attempt. Review the network behavior before rerunning the capture
notebook. Maintained example files remain tracked; run snapshots, raw data,
checkpoints and temporary kernel files retain their existing ignore policy.

## OKX and Bitfinex migration verification

The 2026-09-16 source migration is based on commit `df2831e`. It replaces the
primary Binance trade walkthrough with saved OKX/Bitfinex book exploration,
removes the Coinbase credential route from the capture notebook and moves NB 08
to the offline lab. It reuses existing package APIs and configurations. Runtime,
dependencies, runner, ignore policy and the frozen P1 file are unchanged: **zero
production code-bearing changed lines** under the roadmap's counting rule.
Notebook code/output changes are cohesive teaching and execution evidence.
Revert this migration's commit to restore the prior example route; no stored-data
migration or deletion is needed.

All three notebooks ran every cell in a fresh CPython 3.14.7 kernel against the
installed candidate. The primary notebook passed both latest-matching selection
and explicit saved directories. The capture notebook passed a new public download
and a saved-archive run, with new live recordings on both executions.

| Notebook / mode | Successful attempt | Executed code cells |
| --- | --- | --- |
| Saved books, latest matching inputs | `822d546a-d706-46bb-9463-94c244bb67f2` | 9 |
| Saved books, explicit directories (maintained outputs) | `4549b993-5206-4cdf-84b0-9c29b2b73d92` | 9 |
| Public capture and new OKX archive | `487d8f73-62af-4320-8621-5c248ef17841` | 9 |
| Public capture and reused OKX archive (maintained outputs) | `ba7527ab-1309-4525-b44a-24f47130e4e2` | 9 |
| Offline lab with NB 08 (maintained outputs) | `bfac2d07-4ac3-47c1-8878-4422cc191f05` | 21 |

The first new acquisition recorded **376 Bitfinex messages / 50 final visible
orders** and **154 OKX messages / 800 final price levels**. Both had no detected
gaps and matched independent saved replay. The OKX archive contained **109,423,187
compressed bytes**; the reader reconstructed **10,000 records / 800 final levels**
from source time `2026-09-08T00:00:00.004Z` through `00:03:44.624Z`. Continuity
remains unknown, and `entire_archive_replayed=False`. Counts belong to these
identified inputs; they are not future acceptance thresholds.

The primary notebook pins these first-acquisition directories:

- `data/bitfinex/a5116c5a-b7d6-4e2b-9ee6-c79839c80f43/`
- `data/okx/history/802967bb-05eb-4b7b-9c90-2c964f22e41f/`

Their raw SHA-256 values are respectively
`a57ddabc5b1283c702ee2c7fd104a2b9cd943e2b41661cfc1d66619b35930163` and
`fef59b343d1972c32f67583edc538c5d2f7350e6f3a0059e6f87896d7e8bf676`.
The first OKX live sample is in
`data/okx/live/26d6c532-9948-47f1-b94c-29856630368c/`. Each attempt retains its
own printed paths and identities; the second capture observes a different interval.

Commands used, from the repository root unless stated otherwise:

```sh
uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/research-foundations.ipynb
uv run --frozen --no-sync --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/market-data-capture.ipynb
ALPHA_OKX_ARCHIVE_DIRECTORY=data/okx/history/802967bb-05eb-4b7b-9c90-2c964f22e41f uv run --frozen --no-sync --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/market-data-capture.ipynb
ALPHA_OKX_ARCHIVE_DIRECTORY=data/okx/history/802967bb-05eb-4b7b-9c90-2c964f22e41f ALPHA_BITFINEX_CAPTURE_DIRECTORY=data/bitfinex/a5116c5a-b7d6-4e2b-9ee6-c79839c80f43 uv run --frozen --no-sync --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/research-foundations.ipynb
uv run --frozen --no-sync --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/foundation-contract-checks.ipynb
uv run --frozen --no-sync pytest -q tests/unit/data/live tests/unit/data/venues/okx tests/unit/data/providers/binance/test_rows.py
uv run --frozen --no-sync ruff check examples/research-foundations.ipynb examples/market-data-capture.ipynb
uv run --frozen --no-sync ruff format --check examples/research-foundations.ipynb examples/market-data-capture.ipynb
uv run --frozen --no-sync --with 'nbformat==5.10.4' python /private/tmp/orderbook-notebook-migration/validate.py
uv run --frozen --no-sync alpha-governance-architecture
git diff --check
```

Focused tests: **64 passed**, no skips or deselections. The two migrated book
notebooks pass Ruff lint/format. The temporary validation script checks notebook
schemas, syntax, current source digests, all-cell execution and local Markdown
links. It confirms the offline lab's original 19 code cells are unchanged and
the moved/new cells introduce no lint findings. The full legacy lab retains
pre-existing lint findings; this migration does not claim a clean full-lab Ruff
check. The architecture check validates the repository's 41 documentation files.
The full CI lane and a new wheel build were not run for this notebook/docs change.

Installed-consumer verification ran from `/private/tmp/orderbook-notebook-migration`
with this checkout's absolute `.venv/bin/python` path and the temporary
`consumer.py` script, passing the absolute checkout as its argument. It verified
all **59 installed runtime files**, reopened the three first-acquisition inputs
above and matched their saved book and full trace identities without network
requests or editable imports. Its command on this workstation was:

```sh
cd /private/tmp/orderbook-notebook-migration
'/Users/lxg/Documents/GitHub/Alpha Research/alpha-research-lab-private/.venv/bin/python' /private/tmp/orderbook-notebook-migration/consumer.py '/Users/lxg/Documents/GitHub/Alpha Research/alpha-research-lab-private'
```

These temporary scripts are verification aids, not new supported commands.
The maintained notebooks retain the corresponding replay and identity checks.
P1 remains byte-identical, SHA-256
`7feb8039724001889060dfeb79138fb4bc78764dcca6683297bc64fb2bd0192d`.
This proves accessible bounded book acquisition and saved reconstruction, not
trade history, simultaneous cross-venue liquidity, complete coverage, fills or a
strategy result. MR 09 remains the next roadmap MR; no part of it is implemented here.

## MR 09 occurrence checkpoint

The later MR 09 change adds section 9 to `research-foundations.ipynb`; its synthetic
Binance trade and Tardis-control examples need no provider access. The earlier
saved OKX/Bitfinex exploration remains intact. Run the whole notebook with the
existing runner and pinned saved directories shown in the
[MR 09 evidence record](../docs/roadmap/mr-09-implementation.md#fresh-kernel-nb-09).
All 27 cells, including 12 code cells, passed in a fresh kernel against committed
runtime `0969f01`. The notebook verified all 61 installed runtime files first.
It displays distinct raw occurrences, exact source units, absent archive clocks,
binding-scoped controls and explicit incompatible-input failures. MR 10 is next;
no duplicate/correction or accepted-dataset workflow is implied.

## MR 10 correction checkpoint

Section 10 of `research-foundations.ipynb` now exercises economic duplicate admission
and explicitly evidenced corrections. Use the existing runner and pinned saved
OKX/Bitfinex directories; no source access or new acquisition is required. The
[MR 10 evidence record](../docs/roadmap/mr-10-implementation.md#fresh-kernel-nb-10)
retains the exact command and candidate identity. All **34 cells / 15 code cells**
passed in a fresh kernel at runtime commit `27d8a2f`, after matching all **62 installed
runtime files**. Successful attempt: `8e11de2d-a1ef-40a8-a286-3ac31b8d6e4f`.

The notebook shows two origins contributing one trade despite an inserted row,
unknown original archive knowledge, a separately evidenced corrected version, and
the earlier captured price before a late correction becomes available. It displays
unevidenced-conflict, missing-reference, invalid-clock and non-trade failures.
These assertions are synthetic and do not establish empirical revision history.
MR 11 is next; quality, snapshots and shared as-of queries remain future work.


## Connected dataset walkthrough verification

On 2026-09-17 the primary notebook was condensed from **69 cells / 29 code cells**
to **29 cells / 15 code cells** (1,647 to 604 code lines). It retains the saved book
exploration and combines NB 09–17 into per-input evidence, publication, verified
reading and cutoff selection. The other maintained notebooks and P1 are unchanged.

The existing runner passed every cell in a fresh CPython 3.14.7 kernel, with the
same explicit OKX and Bitfinex directories shown above. It verified all **72 installed
runtime files** against the working candidate based on `3deb34b966adf1f66e4eb79551375283c45300f0`.
No source access or new book acquisition occurred. Final attempt:
`06e4bde5-aa91-41a7-bb38-1d94aadfe4fb`; notebook source SHA-256:
`f6aee23f52ea2c243e340f6995aa86ef62f4db71486216bdf4f5d419d2a5d7bb`.
The working notebook and ignored run snapshot retain the execution and runtime
identities. Synthetic files are removed by the notebook's final cell.

The earlier condensation attempt `f4a9c0e7-532c-4115-ab48-74cd4b32be4e` failed when
the shortened disconnect example appended a record after capture end. The example
now reconstructs up to that boundary before injecting the gap; the failed run is
retained separately. Final checks passed notebook schema, syntax, sequential
execution, source digest, saved-run equality, 56 local links, Ruff lint/format and
the architecture link check. Detailed runtime regressions remain in the test suite;
this walkthrough does not add LOB publication or empirical historical evidence.

## MR 18 query workload

Section 9 of `research-foundations.ipynb` recomputes the backend decision from the
small retained measurement record. It checks installed runtime, lock and benchmark
driver fingerprints; it does not silently rerun the expensive representative
benchmark. Sections 7–8 still execute the synthetic correction, scoped-control,
cancellation, invalid-clock, byte-limit and mutable-ID examples in the fresh kernel.

The [MR 18 record](../docs/roadmap/mr-18-implementation.md) owns the preregistered
workload, accepted proposed budgets, observed results and limitations. The standalone
[driver](query_workload.py) requires macOS (its process high-water RSS is in bytes),
an installed candidate, and a directory containing the retained `raw/` and
`snapshots/` stores. It reads existing inputs only; it does not fetch data, rewrite
availability, publish snapshots or introduce a backend. Use the recorded snapshot,
not a latest alias. Missing bytes fail explicitly.

To repeat against an isolated candidate, build/install with the frozen wheel-smoke
procedure recorded in MR 18, copy `query_workload.py` outside the checkout, and run
from that directory. Keep other tests/notebooks idle during timing:

```sh
cd /private/tmp/mr18-validation
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
Python, Markdown and notebook sources stay tracked; the small measurement summary
under `docs/roadmap/` contains identities, counts and timings, not raw market rows.

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
The MR record retains the executed commands, failed attempts and admission decision.


## MR 20 shared stepping checkpoint

Section 10 of `research-foundations.ipynb` adds shared chronological trade/control
stepping to the existing saved-input walkthrough. It needs the same saved OKX and
Bitfinex directories, an installed candidate and the pinned separate notebook
tooling. Run the complete notebook with the command in the
[MR 20 acceptance record](../docs/roadmap/mr-20-implementation.md#fresh-kernel-nb-20).
No additional source acquisition, runtime dependency or kernel path patch is needed.

The final run passed **45 cells / 23 code cells**, including installed import/byte
verification, the new phase trace and cursor failures. It shows the original
capture at 0.004103 seconds, an explicit 1.5-second wakeup, gap at second 2 and
correction at second 10. Batch sizes 1/8 and restored consumer-prefix/suffix traces
agree. The first attempt confused a query cutoff with capture time; its separate
failed snapshot and the corrected successful attempt are identified in the record.

A cursor is valid only after every phase of its step completes. Save it with the
consumer state and earliest outstanding schedule. On callback failure, discard
the partial replay/consumer state and restore both from the last completed step.
Changing selected input, query bounds, consumer configuration or ordering policy
requires a fresh run; an incompatible cursor is refused. This is source replay,
not a strategy ledger, fill implementation or durable account checkpoint.

Section 9 continues to verify MR 18's measured files at their historical Git
revision and against the installed candidate. The added replay module was not
measured by MR 18. If a measured file changes, investigate and renew the relevant
measurement instead of replacing its recorded hash. Generated attempt snapshots
and transient kernel files remain ignored; maintained example sources stay tracked.


## MR 21 configured EDA and clean-kernel acceptance

Section 11 publishes six synthetic corrected observations across two instruments,
calls the installed `inspect_eda` entry, plots the bounded event interval and reads
standalone replay/extension evidence. The normal runner uses separate pinned
Matplotlib tooling; no runtime dependency or lockfile change is required.

For an external wheel kernel, install the locked runtime wheel as described in the
[MR 21 record](../docs/roadmap/mr-21-implementation.md), add explicitly pinned kernel
tooling to that temporary environment, and point the existing runner at it:

```sh
uv pip install --python /private/tmp/mr21-validation/installed/venv/bin/python --only-binary=:all: 'ipykernel==7.2.0' 'matplotlib==3.10.8'
ALPHA_OKX_ARCHIVE_DIRECTORY=data/okx/history/802967bb-05eb-4b7b-9c90-2c964f22e41f ALPHA_BITFINEX_CAPTURE_DIRECTORY=data/bitfinex/a5116c5a-b7d6-4e2b-9ee6-c79839c80f43 uv run --frozen --no-sync --with 'nbclient==0.10.4' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/research-foundations.ipynb --kernel-python /private/tmp/mr21-validation/installed/venv/bin/python
```

Those saved book paths are the actual acceptance inputs; select compatible retained
paths explicitly on another machine. The external wheel and generated synthetic
stores are local acceptance artifacts, not a release archive. The owning MR record
retains the successful/failed attempts, hashes, observations and environment limits.


## MR 22 saved source negotiation

Section 12 reads the same pinned Bitfinex capture as section 2, exposing protocol
version, configuration/subscription acknowledgement, original receipt nanoseconds
and server sequences. It opens no live connection. Six synthetic examples reject
unsupported negotiation and product/stream combinations using the installed APIs.

The [MR 22 acceptance record](../docs/roadmap/mr-22-implementation.md#fresh-kernel-nb-22)
contains the exact installed-wheel/kernel commands and the actual capture directory.
All 55 cells / 28 code cells passed with candidate imports and bytes verified.
Keep the saved capture or select another compatible retained recording explicitly;
the notebook never substitutes a later archive download for live receipt.

The first run detected changed live files in MR 18's historical whole-package
comparison. Section 9 now preserves that historical digest, requires every other
measured file to match, checks in a separate process that the two explicitly named
live modules are not query imports, and displays their changed paths. The query
measurements remain historical; no live/replay performance inference is made.
Both failed and successful attempts remain separately retained under the generated
runs policy. No runtime notebook dependency or ignore rule changed.
