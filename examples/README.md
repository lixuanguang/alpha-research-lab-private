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
Source-access and release/activation requirements still apply. Current source
access remains unresolved, and no fetching or monitoring service is implied by
this directory structure.

The current [research-foundations.ipynb](research-foundations.ipynb) is the working
starting point. Edit the question, hypothesis and named scenarios in section 2;
inspect the comparison and boundary tables; then update the interpretation, next
question and promotion decision in section 8. Section 7 holds independent fixed
reference examples, so changing an exploratory quantity does not change a golden
result. The notebook records interpreter, installed-package/source agreement,
Git, catalog, lockfile, notebook source and experiment-input identities.

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

The example uses synthetic trades and the authored catalog, with no market-data
access. No project runtime dependencies or `sys.path` changes are needed.

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
