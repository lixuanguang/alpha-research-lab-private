# Notebook setup, execution and troubleshooting

Owner: repository founder. Current retention guidance updated 2026-09-22. This is
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
root or `examples/`. The two offline versions default to synthetic local fixtures, installed research/economic
APIs and installed subprocess consumers, including rule-only comparisons. No venue connection, archive download, account
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
notebook's separate ignored artifact directory; the supplied study is read. The default
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

## Historical order-book study

[Order-book research](orderbook-research.ipynb) is a real saved-data experiment
alongside the workflow tutorials. Its settings cell selects the exact OKX archive
directory and [L2 backtest configuration](../configs/backtests/okx-eth-usdt-book-v1.json).
The 2026-09-22 public index check found no September 21 archive and selected the
latest listed day, **2026-09-20**. The saved full-day archive is 97,973,786 bytes;
the existing reader replayed 10,000 messages from 00:00:00.001 through
00:06:00.252 UTC. This is a six-minute inspection, not full-day semantic validation.

The saved download is
`data/okx/history/f62e64b7-1b40-4869-8b05-2ca911fefcef/`. It is ignored by Git,
so another checkout needs the complete directory or a separate download. The
raw SHA-256 is `d5d530e6ce635d0e92ba4cd6d280b0aa2f64e918f09e2822018ed061846e1ea3`.
The directory retains the exact selected index, request and raw bytes; its
`availability-check/` also retains the original recent-day and September 21
index responses. A fresh download gets its own directory; update the notebook's
`ARCHIVE` setting explicitly rather than choosing a mutable latest directory.

```sh
uv run --frozen --no-editable alpha-acquire archive index --config configs/history/okx-eth-usdt.json
uv run --frozen --no-editable alpha-acquire archive fetch --config configs/history/okx-eth-usdt.json --output data/okx/history
```

These commands contact OKX's public service. Running the notebook only reads saved
files and creates a new local result directory:

```sh
uv run --frozen --no-sync --with 'nbclient==0.10.4' --with 'nbformat==5.10.4' \
  python examples/run_notebook.py examples/orderbook-research.ipynb --kernel-python .venv/bin/python
```

The kernel must contain the installed current package and `ipykernel`; use the
existing setup below. Install the current non-editable package before starting
that kernel:

```sh
uv run --frozen --no-editable python -c 'from applications.backtest import run_books'
```

The notebook calls `applications.backtest.run_books` to perform verified native
replay, exact EDA, a configured imbalance rule and a no-trade control, independent
risk, immediate-or-cancel depth execution and exact cash/position/P&L accounting.
The same workflow is available without a notebook:

```sh
uv run --frozen --no-editable alpha-backtest books \
  --config configs/backtests/okx-eth-usdt-book-v1.json \
  --archive data/okx/history/f62e64b7-1b40-4869-8b05-2ca911fefcef \
  --output logs/book-backtest/runs
```

The command prints a unique directory containing `report.html`, `report.json`,
`eda.json`, `configuration.json`, both complete checkpoints and the attempt record.
The notebook adds book/NAV charts. Use `--stop-at` and `--resume` as described in the
[acceptance and recovery guide](../docs/research/l2-book-backtest.md#interrupt-and-resume).
Failed attempts remain retained; a missing or corrupt archive never falls back
to a synthetic source.

The configuration declares the sample, spot grids, fees, limits, participation
cap and modeled feed/processing/order/response delays. Original receipt times and
source sequence IDs remain unknown. Decisions consume the delayed local book;
orders execute against the exchange book on arrival. Resting orders, queue
position, market impact and empirical latency calibration remain unsupported.
The frozen P1 trade-price experiment is unchanged.

The installed real-source run examined 10,000 messages and produced **62 orders,
78 level fills, 998.35849845 USDT terminal NAV and -1.64150155 USDT net P&L** for
the fixed imbalance rule. The no-trade control remained at **1,000 USDT**. The
[acceptance record](../docs/research/l2-book-backtest.md) retains full result and
verification context. This six-minute engineering demonstration makes no
profitability, full-day coverage or live-execution claim.

Preserve executed notebooks under ignored `examples/runs/` and generated reports
under ignored `logs/book-backtest/`. Clear maintained notebook outputs before
committing. The original EDA-only run remains retained at
`examples/runs/orderbook-research/424f9214-41bc-4d9c-8af5-7a42b4c08286-artifacts/`;
its earlier byte-parity observation does not describe the newly added economics.

To reverse this workflow, remove its book-specific configuration, notebook
consumer and implementation together while preserving saved inputs and attempts.

## Frozen source evidence

The [QR live notebook](research-foundations-live.ipynb) now defaults to
`ALPHA_QR_WORKFLOW=p1-evidence`. It reopens the explicitly pinned P1 Binance
archive and auxiliary native capture, without initiating a network call. Its
deliverable is a reproducible source-evidence handoff for the
[frozen acceptance requirements](../docs/research/p1-baseline.md#acceptance-and-research-discipline).
The separate Bitfinex workflow remains available with
`ALPHA_QR_WORKFLOW=book-capture`.

The default paths name the retained acquisition
`data/binance-archives/runs/acb948277201cc169d32c2bb874fb40ce9e9c33c893e56a992faa47853147f80/manifest.json`,
its `data/binance-archives/raw/` store, and
`logs/frozen-baseline/2026-09-22/source-evidence/archive-capture.json`.
These ignored inputs are local; a clean checkout does not contain them. Supply
explicit paths using `ALPHA_P1_MANIFEST`, `ALPHA_P1_RAW` and `ALPHA_P1_CAPTURE`
when reopening retained inputs elsewhere. A nonempty missing selector fails.
Set `ALPHA_P1_CAPTURE=''` deliberately for an archive-only investigation.
The notebook verifies the frozen archive/configuration digests, source, instrument,
interval and capture binding. It never selects a latest run or substitutes a fixture.

Each execution creates an exclusive `data/notebooks/p1-evidence/<uuid>/` study
containing the verified archive, acquisition, both unchanged economic configurations,
supplied capture/eligibility, source summary, actual strict publication report,
document review, semantic hash inventory and `handoff.json`/`handoff.md`.
Restart from setup to repeat cells that retain immutable outputs. The existing
notebook runner archives successful and failed executions separately.

To add evidence, copy the generated `review-template.json` to a separate working
file. Keep its exact `scope`, and add objects to `documents` with:

- `requirement`: `historical_eligibility`, `coverage` or `revisions`;
- `path`: an absolute path to a retained provider record;
- `source_reference`: provider provenance or reference;
- `claim`: the precise fact and interval the record supports;
- `limitations`: what remains unproven.

Set `ALPHA_P1_DOCUMENTS` to that working file and rerun. At most 20 documents,
each at most 8 MiB, are copied and hashed. They remain candidate evidence requiring
review; no attachment or authored status upgrades quality. If actual historical
eligibility evidence is available, provide its existing typed
`EligibilityAssertions` JSON through `ALPHA_P1_ELIGIBILITY`. Otherwise the notebook
passes an empty history, preserving unknown eligibility.

Run with the same pinned tooling command shown below. To verify reproduction,
restart through the runner with `ALPHA_P1_REOPEN` set to the exact earlier study.
It verifies the earlier retained bytes and compares deterministic input, code,
configuration and quality digests. Changing inputs or notebook source is a new
investigation and fails this reproduction comparison. UUIDs and execution clocks
are excluded from semantic comparison.

Strict publication currently refuses the source: historical eligibility and
positive coverage/complete revision evidence remain unresolved, and the platform
has no strict contract accepting the latter evidence yet. Expected source refusal
completes the evidence handoff with **MR 8 OPEN**, without running economics.
A completed notebook is not empirical acceptance. Unexpected input/runtime errors
fail the run. The handoff assigns the remaining source investigation, concrete
platform admission work, and subsequent actual-source economic/report/recovery
proof. It does not change the frozen sample, acceptance standard or roadmap status.

## Live versions

[QR live](research-foundations-live.ipynb) with `ALPHA_QR_WORKFLOW=book-capture` and
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
The book-capture routes ignore these offline input selectors and create a new recording.

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

The QR evidence route reads saved real inputs; the explicit book routes contact
the public source and retain new local recordings:

```sh
uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/research-foundations-live.ipynb
ALPHA_QR_WORKFLOW=book-capture uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/research-foundations-live.ipynb
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

## Retained research and economic studies

Offline notebooks now create an exclusive directory under
`examples/runs/<notebook-name>/<attempt-id>-artifacts/`. Rerunning setup in the same
runner attempt refuses to overwrite it. Inputs, configs, attempt roots, model bytes,
economic results/checkpoints and diagnostic child logs remain available after kernel
shutdown, including failed attempts. The runner's separate executed `.ipynb` records
source/runtime identities and failure/success. Neither location is a backed-up journal;
copy the whole relevant directory before using it as durable research evidence.

For the QR-to-QD handoff, copy the exact `price-study` path printed by the researcher
notebook and select it explicitly before running the developer notebook:

```sh
export ALPHA_RESEARCH_STUDY_DIRECTORY='/absolute/path/to/printed/price-study'
uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/infrastructure-diagnostics.ipynb
```

The developer reads the complete retained study without writing to it. It verifies
selected raw/snapshot bytes, pinned model manifests and feature results, reproduces
exact validation without fitting, and compares whole/resumed economics to saved
results. Missing or incompatible inputs fail without fallback. With the variable
unset, this user-artifact section reports `SKIPPED`; the installed synthetic
feature/model and economic consumers still execute.

The QR notebook first inspects the original synthetic mixed input or your explicitly
selected saved study. Its subsequent six-minute trade tutorial always creates a
**separate synthetic study**, with authored availability and the same saved snapshot
feeding features, models and fixed-rule economics. It never silently runs the synthetic
result against your supplied data or repairs missing real availability. Live book
notebooks retain their source behavior and direct readers to this boundary; a book
selection cannot feed the current trade-only feature/backtest APIs.

Model fitting and validation are disjoint by complete information interval, not just
decision timestamp. The model comparison uses a fixed software threshold, and the
backtest uses MR 5's supported no-trade/momentum policies; no model-to-order adapter
is invented. The synthetic momentum loss is an expected reconciled result.

### Optional actual ClearML publication

Default offline QR execution injects a specifically named unavailable-publication
exception at `ClearMLPublication.publish` after the real application retains its
model/economic outcome. It inspects terminal status and preserves the recoverable
outbox. This is explicit software failure evidence, **not** successful SDK publication.
The developer notebook similarly clears `ALPHA_CLEARML_LOCAL_ENV` from its consumer
subprocesses so shell test credentials cannot silently turn diagnostics into service calls.

For deliberate real QR publication, configure the SDK externally and set
`ALPHA_NOTEBOOK_TRACKING_CONFIG` to a non-secret `ClearMLDestination` JSON, for example:

```json
{"project":"notebook-research","api_uri":"http://127.0.0.1:18008","files_uri":"http://127.0.0.1:18081"}
```

Use the [local tracking guide](../configs/development/clearml/README.md) for credentials
and service setup; the notebook never starts a server. A supplied invalid config or
publication failure propagates without offline fallback. Retry an interrupted outbox
with `applications.explore.publish_experiments(attempts)` using the saved complete
attempt root, rather than refitting or rerunning the economy. Do not put SDK secrets
in configuration cells, maintained outputs or manifests.

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

A replay cursor binds source identity and progress. The separate economic consumer
retains observations, pending intent/reservation, schedules, applied fills and ledger
in `EconomicCheckpoint`; its fresh-process result must equal uninterrupted execution.
The feature/model consumer verifies exact state reload and an intact attempt-store
backup. Collector recovery still preserves unknown gaps and requires fresh source
synchronization. Synthetic economics does not qualify external source coverage,
executable liquidity, production account recovery or deployed incident response.

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

The historical optional columnar experiment uses `duckdb==1.5.5`, now also
pinned by the bounded research analysis consumer. That dependency admission does
not qualify the experimental storage backend or update its historical measurement. Copy `query_columnar_candidate.py` outside the checkout. Its
`convert`, `scan`, `verify` and `io` operations take the same input directory.
`convert` refuses an existing output; preserve each failed candidate in a separate
experiment directory before retrying. `verify` compares every complete revision
payload with canonical source bytes and checks exact codec round trips. `io` saves
DuckDB profiles separately from timings. The Parquet scan is a bounded experiment,
not a supported backend: it does not implement cutoff, controls, membership or
verified loading, and its metrics must not be presented as end-to-end query parity.
Retain commands, candidate identities, failures and the admission decision beside
each new benchmark attempt.
