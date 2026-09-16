# Research notebooks and examples

## Native L3 capture and replay

Start the new live-data workflow with [market-data-capture.ipynb](market-data-capture.ipynb).
It records bounded Bitfinex R0 and, when local Exchange credentials are filled,
Coinbase Level 3. It explains receipt clocks, exact decoding, durable inputs,
visible-order replay and gaps. See the [collector guide](../docs/data/l3-collectors.md)
for commands and `secrets/coinbase.secrets` setup.

```sh
uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/market-data-capture.ipynb
```

The historical Binance workflow below and both existing notebooks retain their
original historical and foundation-check roles.


Maintained `.ipynb`, `.py` and `.md` files in this folder are versioned in Git.
Generated run snapshots, checkpoints and kernel files remain ignored. This is the
long-lived test bed for research questions and package-boundary experiments.

There are two maintained notebook routes:

| Route | Purpose |
| --- | --- |
| [research-foundations.ipynb](research-foundations.ipynb) | Primary route for the real historical workflow. It resolves the configured job and catalog, downloads or reads the saved Binance archive, verifies it, inspects selected real rows and applies the C03 financial-unit checks. |
| [foundation-contract-checks.ipynb](foundation-contract-checks.ipynb) | Offline companion for detailed synthetic MR 00–07 boundary experiments, retained assertions, hand-ledger explanations and restart/failure fixtures. |

The primary notebook is the default research starting point. Its eight sections
follow one connected route: check the installed environment, resolve the actual
configuration and catalog, acquire or reopen the saved run, connect storage to
source clocks, inspect selected real rows, apply C03 financial units, verify
repeatability and rejection, and record a summary. It reads an existing cached
archive when configured for cache-only operation, or downloads the archive when
acquisition is enabled. No later-MR implementation is implied by this notebook.

The companion is a standalone copy of the first 44 cells of the maintained
foundation flow, through `mr07-checkpoint-3`. It keeps the synthetic MR 00–07
assertions, hand-ledger explanations and actual fixture code. It performs no
source access and is useful when the detailed contract boundaries need to be
examined without the real-data route. Its fixed reference examples remain
independent of the editable synthetic scenarios. The notebook's normal fallback
`notebook_path` points to the companion; the runner command below selects each
route explicitly.

| Activity | Notebook contents |
| --- | --- |
| Data fetching | Explore permitted source APIs and inspect requests, payloads, timestamps and acquisition quality. |
| EDA | Inspect saved data, gaps, distributions, relationships and candidate features. |
| Quant strategy research | Prototype hypotheses, signals/models, scenarios and costed comparisons. |
| Strategy monitoring | Inspect saved reports and, when available, runtime P&L, exposure, freshness and drift. |

Experimental logic can stay in notebooks while an idea is being evaluated. Reuse
the existing foundations, then promote mature shared behavior and selected
strategies into the package with decisive retained tests. After promotion, import
the package implementation for formal evaluation rather than maintaining a second
copy in notebook cells. Record influencing research attempts and their identities
outside mutable notebook outputs.

The package is the maintained home for productionized infrastructure and
versioned strategies. Notebook monitoring views will consume its outputs;
persistent collection, alerts and operating controls belong in maintained code.
Source-access and release/activation requirements still apply. Historical
knowledge, eligibility and dataset acceptance remain separate from the real-data
inspection route. No monitoring service is implied by this directory structure.

The primary notebook's real route uses the founder-selected Binance public archive
and the revised [P1 source contract](../docs/research/p1-baseline.md), preserving
the selected hour and economic rules. It uses the installed acquisition command
and keeps the configured job, catalog and manifest identities together with the
saved archive. The `data/binance-archives/` directory is ignored: shared
`raw/<sha256>` objects and `runs/<resolved-run-identity>/` inputs, manifest,
use/retention record and separate attempt logs. A code or input change gets a new
manifest identity; raw content can still be shared. Keep manifests and bytes
together for reproduction. This local working copy has no automatic expiry and is
not a backed-up long-term archive. The archive files and generated run state live
under this ignored directory. Notebook run snapshots, checkpoints and kernel
files are also ignored; maintained examples and configuration remain tracked. No
Tardis entitlement is needed for this source.

Set `ALPHA_BINANCE_DOWNLOAD=0` when the primary route should read the existing
cached real data. It fails clearly when the required cached object is absent; it
does not skip real inspection. With acquisition enabled, the selected run may
perform real network access when no completed object is available. The socket
timeout is 10 seconds, with two retries and separate 64 MiB compressed/expanded
caps. Interrupt and rerun the download stage to resume. Correct validation
failures; never delete a manifest just to hide changed raw bytes. The notebook
CSV inspection is feasibility evidence, not a canonical reader, coverage
guarantee or causal backtest.

The companion's synthetic sections retain the following bounded checks and their
linked implementation records. Section 11 completes **NB 03** with the installed
`RawObject` API: inspect the compressed-byte digest, request partition, retrieval
reference and original clocks; round-trip the descriptor; reject mutation,
truncation and another request; then verify recovery with the original bytes. The
sample files are temporary and synthetic. See the [MR 03 acceptance record](../docs/roadmap/mr-03-implementation.md)
for commands and results.

Section 12 completes **NB 04** with `RawStore`: two child processes exit before and
after the atomic link; inspect staging versus published bytes, retry, confirm inode
reuse and reject a corrupt existing object. The retained
[interruption fixture](../tests/fixtures/mr04/interrupt_publish.py) is shared with
the storage tests. See the [MR 04 acceptance record](../docs/roadmap/mr-04-implementation.md).

Section 13 completes the synthetic **NB 05** checkpoint: fetch a fake HTTP
partition, verify and reopen its exact gzip bytes, decode the saved trade, inspect
original clocks, and reject malformed or truncated gzip, authentication and
timeout failures. See the [MR 05 record](../docs/roadmap/mr-05-implementation.md)
for the unperformed source probe and historical-evidence limits.

Section 14 completes **NB 06**: four abrupt process exits around raw/checkpoint
publication, exact resumed/uninterrupted manifest comparison with fixed clocks,
repeated-run skips, missing or mutated completed-byte rejection, terminal
authentication/schema failures and exhausted transient backoff. It shares the
[synthetic process fixture](../tests/fixtures/mr06/acquire.py) with retained
regressions and runs child consumers outside the checkout. See the [MR 06
record](../docs/roadmap/mr-06-implementation.md).

Section 15 completes the synthetic **NB 07** checkpoint through the installed
`alpha-acquire` command: saved config/command identities, flushed progress,
abrupt and keyboard interruption, retry exhaustion, resume/repeat parity and
missing or mutated object rejection. It uses copied inputs and the same synthetic
fixture from outside the checkout. The next package work is **MR 08 — Read saved
raw frames with explicit gaps**; it is not implemented here.

Future notebooks can use names such as `data-fetching.ipynb`, `eda.ipynb`,
`strategy-research.ipynb` and `strategy-monitoring.ipynb`; these files have not
been created yet. Each MR records which notebook sections it exercised while
retaining its own bounded code scope.

## Running the two routes

From the repository root, use the pinned project interpreter and separate notebook
tooling. The no-argument runner default remains the primary real historical
workflow; the explicit paths make the selected route reviewable.

Primary real historical workflow:

```sh
uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/research-foundations.ipynb
```

Offline detailed boundary companion:

```sh
uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/foundation-contract-checks.ipynb
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

For the offline companion, replace the notebook path in that command with
`examples/foundation-contract-checks.ipynb`. `--no-sync` preserves the editor's
installed kernel/tooling while the command adds the runner tools in uv's separate
environment. The notebook checks the runtime package's installed bytes against
the checkout before interpreting any result.

No new project runtime dependencies or `sys.path` changes are needed.

## Interactive kernel and import repair

The kernel requires `ipykernel` and the installed runtime package.
`nbclient`/`nbformat` are runner tooling, so their absence from an interactive
kernel is permitted and recorded accurately in the notebook table.

On 2026-09-14, interactive imports failed because all 33 expected installed
package files were missing and only renamed duplicates remained under
`site-packages`. The existing verified M0 wheel was reinstalled with
`--no-deps --link-mode copy`; all 33 files then matched it exactly. The cause of
the file renaming was not established. Restart a previously opened kernel after
repairing its installation, since it may retain the failed namespace import in
memory. The saved interactive failure is retained under
`examples/runs/research-foundations/`.

On 2026-09-15, the MR 04 editor run used an older `.venv` installation missing
`data/raw_store.py`; the separate clean verification environment already had it.
The same candidate wheel was installed into `.venv` with `--no-deps --reinstall
--link-mode copy`. Twenty stale renamed runtime duplicates were quarantined, and
all 34 expected runtime files then matched the source and wheel exactly. All 13
cells passed using `--kernel-python .venv/bin/python`, preserving the editor's
ipykernel 7.3.0. The [MR 04 repair record](../docs/roadmap/mr-04-implementation.md#editor-environment-repair-before-merge)
contains the commands and retained attempt identity.

After switching to source that adds or changes a module, refresh the installed
candidate in the interpreter selected by the editor, then restart that kernel and
run all cells. `--no-sync` only preserves an existing installation; it does not
install new source. The package version remains `0.1.0` across these MRs, so check
installed file identity instead of treating the version string as proof that the
current candidate is installed.

During MR 05 verification, four byte-identical ` 2` copies in the checkout and
35 such files in the installed runtime package were quarantined outside the
checkout. The verified MR 05 wheel contains no duplicate names; reinstalling it
restored exact agreement for all 37 package files. The cause of the copies was not
established. The [MR 05 cleanup record](../docs/roadmap/mr-05-implementation.md#duplicate-file-cleanup)
identifies the reversible quarantine and installation command.
