# Notebook setup, execution and troubleshooting

Owner: repository founder. Updated 2026-09-16. This is the supporting operations
guide. Start with the [researcher's guide](README.md) to choose a question and
understand the data. The [roadmap](../docs/roadmap/README.md#local-notebook-workflow)
owns notebook retention and acceptance; this page explains the existing tools.

## Before executing

Use the pinned project interpreter and installed candidate. Run commands from the
repository root. Historical exploration uses an existing verified cache when
`ALPHA_BINANCE_DOWNLOAD=0`; its default permits acquisition when a matching run
is incomplete. The offline foundations lab makes no source requests. The market
data notebook contacts live sources and downloads the configured OKX historical
archive; it is a separate, deliberate collection activity.

A source or configuration change can change the resolved run identity, even if
the requested date is unchanged. A missing cache for the new identity is expected;
use its acquisition path or reopen the compatible older environment. Never edit a
manifest to disguise a mismatch or delete old inputs to make a check pass.

Keep local raw files with their requests, settings and completion records. The
historical notebook uses ignored `data/binance-archives/`, with shared
`raw/<sha256>` objects and `runs/<resolved-run-identity>/` records. This working copy
has no automatic expiry and is not backed up by Git. Live and OKX input locations
are described in the [collector guide](../docs/data/l3-collectors.md) and
[OKX guide](../docs/data/okx-market-data.md).

## Running a notebook

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

Live order-book and OKX historical observations (network access and new recording):

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
| Equal-time rows, empty content and missing archives | Historical notebook, sections 5 and 7 | [MR 08](../docs/roadmap/mr-08-implementation.md) |

The numbered checkpoints and fixed synthetic examples remain intact. New activity
notebooks should grow from working research needs; do not create empty fetching,
EDA, strategy or monitoring notebooks to represent planned capabilities.

## Researcher guide verification

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
