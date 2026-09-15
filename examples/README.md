# Research notebooks and examples

Maintained `.ipynb`, `.py` and `.md` files in this folder are versioned in Git.
Generated run snapshots, checkpoints and kernel files remain ignored. This is the
long-lived test bed for ideas, organized by activity rather than implementation MR. Let the
existing foundation notebook evolve and split it as actual working content grows.

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
Source-access and release/activation requirements still apply. The founder-authorized Binance public archive is now acquired in section 16;
historical knowledge, eligibility and dataset acceptance remain separate. No
monitoring service is implied by this directory structure.

The current [research-foundations.ipynb](research-foundations.ipynb) is the working
starting point. Edit the question, hypothesis and named scenarios in section 2;
inspect the comparison and boundary tables; then update the interpretation, next
question and promotion decision in section 8. Section 7 holds independent fixed
reference examples, so changing an exploratory quantity does not change a golden
result. The notebook records interpreter, installed-package/source agreement,
Git, catalog, lockfile, notebook source and experiment-input identities.

Section 11 completes **NB 03** with the installed `RawObject` API: inspect the
compressed-byte digest, request partition, retrieval reference and original clocks;
round-trip the descriptor; reject mutation, truncation and another request; then
verify recovery with the original bytes. The sample files are temporary and
synthetic. See the [MR 03 acceptance record](../docs/roadmap/mr-03-implementation.md)
for commands and results. Section 12 completes **NB 04** with `RawStore`: two
child processes exit before/after the atomic link; inspect staging versus published
bytes, retry, confirm inode reuse and reject a corrupt existing object. The retained
[interruption fixture](../tests/fixtures/mr04/interrupt_publish.py) is shared with
the storage tests. See the [MR 04 acceptance record](../docs/roadmap/mr-04-implementation.md).
Section 13 completes the synthetic **NB 05** checkpoint: fetch a fake HTTP
partition, verify/reopen its exact gzip bytes, decode the saved trade, inspect
original clocks, and reject malformed/truncated gzip, authentication and timeout
failures. See the [MR 05 record](../docs/roadmap/mr-05-implementation.md) for the
unperformed source probe and historical-evidence limits. Section 14 completes
**NB 06**: four abrupt process exits around raw/checkpoint publication, exact
resumed/uninterrupted manifest comparison with fixed clocks, repeated-run skips,
missing/mutated completed-byte rejection, terminal auth/schema failures and
exhausted transient backoff. It shares the [synthetic process fixture](../tests/fixtures/mr06/acquire.py)
with retained regressions and runs child consumers outside the checkout. See the
[MR 06 record](../docs/roadmap/mr-06-implementation.md). Section 15 completes the
synthetic **NB 07** checkpoint through the installed `alpha-acquire` command:
saved config/command identities, flushed progress, abrupt and keyboard interruption,
retry exhaustion, resume/repeat parity and missing/mutated object rejection. It
uses copied inputs and the same synthetic fixture from outside the checkout.
Section 16 runs **actual Binance public daily trade acquisition** through that
same installed command, with no key or transport patch. Run All downloads the June 1,
2024 BTCUSDT ZIP on first use; repeats verify its saved checksum and skip fetching.
It displays exact raw identity, archive/selected-hour row counts, event timestamps
and three real trades. The notebook resolves the revised
[P1 source contract](../docs/research/p1-baseline.md), preserving the selected hour
and economic rules. See the [MR 07 source follow-up](../docs/roadmap/mr-07-implementation.md#binance-source-follow-up).
MR 08 is next and is not started here.

The user-selected `data/binance-archives/` is ignored: shared `raw/<sha256>` objects
and `runs/<resolved-run-identity>/` inputs, manifest, use/retention record and
separate attempt logs. A code/input change gets a new manifest identity; raw
content can still be shared. Keep manifests and bytes together for reproduction.
This local working copy has no automatic expiry and is not a backed-up long-term
archive. Only that generated data directory is newly ignored; maintained examples
and configuration remain tracked. No Tardis entitlement is needed for this source.

Set `ALPHA_BINANCE_DOWNLOAD=0` to execute only offline foundations, or set
`RUN_REAL_BINANCE=False` in section 16. Otherwise Run All performs real network
access if the selected run has no completed object. The socket timeout is 10 seconds,
with two retries and separate 64 MiB compressed/expanded caps. Interrupt/rerun the
download cell to resume. Correct validation failures; never delete a manifest just
to hide changed raw bytes. The notebook-only CSV inspection is feasibility evidence,
not a canonical reader, coverage guarantee or causal backtest.

Future notebooks can
use names such as `data-fetching.ipynb`, `eda.ipynb`, `strategy-research.ipynb` and
`strategy-monitoring.ipynb`; these files have not been created yet. Each MR records
which notebook sections it exercised while retaining its own bounded code scope.

From the repository root, execute the foundation notebook with the pinned
project interpreter and installed package, plus separate notebook tooling:

```sh
uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py
```

The runner defaults to one execution. Supply a notebook path under `examples/`
to execute another notebook; append `--repeat 2` only when two fresh-kernel runs
are intended. For example, keep the same `uv` prefix above and replace its final
command with:

```sh
python examples/run_notebook.py examples/research-foundations.ipynb --repeat 2
```

Every attempted execution saves a distinct notebook under
`examples/runs/<notebook-name>/<attempt-id>.ipynb`, with source hash, start/end
times, execution status and available outputs. An execution error is archived
and returns a nonzero exit; remaining repetitions stop. Successful execution also
refreshes the working notebook's outputs. Kernels are shut down and temporary
kernel files are cleaned up. The working notebook and runner are maintained alongside the package.

For interactive exploration, restart and run all before interpreting a result.
Interactive edits are not automatically archived: use the runner before replacing
an experiment's conclusions. These ignored local snapshots are a convenience,
not a backed-up trial journal or the future packaged research runner. Preserve
influencing real-data attempts with the research program's trial fields and
protected input/output references.

Sections 1–15 use synthetic trades. Section 16 uses the actual archive and a
separate authored source binding; local download clocks are not historical knowledge.
No new project runtime dependencies or `sys.path` changes are needed.

## Interactive kernel and import repair

In the notebook editor, select this repository's `.venv/bin/python`, then restart
the kernel and run all cells. The kernel requires `ipykernel` and the installed
runtime package. `nbclient`/`nbformat` are runner tooling, so their absence from an
interactive kernel is permitted and recorded accurately in the notebook table.

To verify that same editor interpreter using separate runner tooling, use:

```sh
uv run --frozen --no-sync --with 'nbclient==0.10.4' --with 'nbformat==5.10.4' \
  python examples/run_notebook.py --kernel-python .venv/bin/python
```

`--no-sync` preserves the editor's installed kernel/tooling while the command adds
the runner tools in uv's separate environment. The notebook checks the runtime
package's installed bytes against the checkout before interpreting any result.
The default runner command above remains the pinned isolated checkpoint.

On 2026-09-14, interactive imports failed because all 33 expected installed package
files were missing and only renamed duplicates remained under `site-packages`.
The existing verified M0 wheel was reinstalled with `--no-deps --link-mode copy`;
all 33 files then matched it exactly. The cause of the file renaming was not
established. Restart a previously opened kernel after repairing its installation,
since it may retain the failed namespace import in memory. The saved interactive
failure is retained under `examples/runs/research-foundations/`.


On 2026-09-15, the MR 04 editor run used an older `.venv` installation missing
`data/raw_store.py`; the separate clean verification environment already had it.
The same candidate wheel was installed into `.venv` with `--no-deps --reinstall
--link-mode copy`. Twenty stale renamed runtime duplicates were quarantined, and
all 34 expected runtime files then matched the source and wheel exactly. All 13
cells passed using `--kernel-python .venv/bin/python`, preserving the editor's
ipykernel 7.3.0. The [MR 04 repair record](../docs/roadmap/mr-04-implementation.md#editor-environment-repair-before-merge)
contains the commands and retained attempt identity.

After switching to source that adds or changes a module, refresh the installed
candidate in the interpreter selected by the editor, then restart that kernel
and run all cells. `--no-sync` only preserves an existing installation; it does
not install new source. The package version remains `0.1.0` across these MRs, so
check installed file identity instead of treating the version string as proof
that the current candidate is installed.

During MR 05 verification, four byte-identical ` 2` copies in the checkout and
35 such files in the installed runtime package were quarantined outside the
checkout. The verified MR 05 wheel contains no duplicate names; reinstalling it
restored exact agreement for all 37 package files. The cause of the copies was
not established. The [MR 05 cleanup record](../docs/roadmap/mr-05-implementation.md#duplicate-file-cleanup)
identifies the reversible quarantine and installation command.
