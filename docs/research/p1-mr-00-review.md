# MR 00 review record

Owner: repository founder. Status: checkpoint prepared for merge, 2026-09-13.
MRs 01–28 have not started. The sections below retain the original MR 00 and
notebook validation history. The [checkpoint follow-up](#checkpoint-follow-up-2026-09-13)
records the broader current scope and supersedes earlier scope and merge-order
statements; earlier runtime hashes and notebook runs identify their original
candidate only.

## Problem / change

The P1 roadmap proposed a source and baseline without selecting them. The founder
has now selected the bounded Tardis/Binance BTCUSDT one-minute return case while
explicitly leaving access and evidence unresolved. The
[owning experiment](p1-baseline.md) freezes timing, quantity, costs, rejection,
coverage and terminal valuation before comparison, with an independent hand ledger.
Synthetic notebook findings are retained in focused foundation tests.

## Affected scope

Implementation branch: `codex/p1-00-baseline-spec`, based directly on unmerged
roadmap commit `d39fd881fe9b54e2cd0ae8d94942bf1135b739c6` on `p1-roadmap`.
`git fetch origin` succeeded; latest `main` / `origin/main` remained
`f9cee2819eaa6c2a3e8ab47220922f566bff16f5`. The diff from the roadmap's inspected
main is empty, so no new main changes alter this slice. Review MR 00 relative
to `d39fd88`; the eventual diff into main also carries the unmerged roadmap.
Merge that dependency first, then update the implementation branch before merge.

Changed production code: **0 added + 0 deleted = 0 lines**, both relative to
the dependency and main. No runtime source, tracked executable tooling,
dependency metadata/lock or hosted merge gate changed. The 2026-09-13 follow-up
adds one `/examples/` ignore rule. The original MR scope is
two research documents, a roadmap status update and four owning test files.
The engineering guide is the current single standard; the documentation skill's
older `docs/coding_standards/documentation.md` path is absent. Its applicable
rules were read from [the guide](../coding_standards/README.md#documentation)
and [development workflow](../governance/workflow.md). No nonempty applicable
`AGENTS.md` was found. Only the primary agent performed this work.

## Validation result

The notebook imported the candidate installed by `uv run --frozen --no-editable`
on standard GIL CPython 3.14.7, macOS 26.6.2 arm64. Runtime imports resolved under
the project's `.venv/lib/python3.14/site-packages/alpha_research`, not the source
tree. All 30 runtime `.py`, `.json` and `.typed` files matched the checkout bytes.
The base above plus the unchanged runtime tree identifies the exercised code.

| Identity | SHA-256 |
| --- | --- |
| Project `uv.lock` | `1159199bc83be7a75b0ccd2df3a401f3239eda11e37892f5e32d3a88ecf5fc6d` |
| Runtime source content | `fb40bf12cf6398888c75021e7c0c661696f4e34c0721bde8647ac6452ce7ede3` |

The runtime digest concatenates sorted relative file paths, NUL, file bytes,
NUL for those 30 files beneath `src/alpha_research`. The test-only candidate
is the retained MR diff; no notebook-owned runtime logic was extracted because
the existing APIs supplied the entire foundation exercise.

Notebook creation and execution commands (temporary script and notebook removed
after execution):

```sh
uv run --frozen --no-editable python /Users/lxg/.codex/skills/jupyter-notebook/scripts/new_notebook.py --kind experiment --title 'MR 00: clocks, exact units, catalog boundaries' --out /private/tmp/alpha-p1-mr-00/p1-mr-00.ipynb
uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python /private/tmp/alpha-p1-mr-00/exercise.py
```

uv supplied a separate temporary tooling environment using the pinned interpreter
and the frozen installed runtime; no `sys.path` edits or project Jupyter
dependencies were added. Tooling versions were nbclient 0.10.4, ipykernel 7.2.0,
nbformat 5.10.4 and jupyter_client 8.10.0. The final exercise passed all four code
cells in each of two fresh kernels, with explicit kernel shutdown. The initial
run also passed but exposed a scaffold missing-cell-ID warning and a missing
explicit kernel shutdown in the disposable harness; the normalized notebook and
corrected harness reran cleanly. This was a tooling issue, not a product failure.

Retained findings: exact event/capture/local clocks and one-microsecond point
validity; interval-end disconnect provenance; catalog rejection one microsecond
beyond coverage; exact `98.60841460 USDT` trade notional; cash `798.80`, open NAV
`1008.80`, final cash `1017.58`, and net `17.58` in the separate hand oracle.
The test uses independently hand-rounded oracle fees and does not pretend to
exercise a future fee engine. C03's supported half-even policy is used by the
selected baseline; the roadmap's separate half-up oracle remains unchanged.

Final focused commands, all run from the repository root:

```sh
uv run --frozen --no-editable pytest -q tests/unit/data/providers/tardis/test_tardis_binance.py tests/unit/data/providers/tardis/test_tardis_decoder.py tests/unit/test_reference_data.py tests/unit/financial_units/test_p1_hand_ledger.py
uv run --frozen --no-editable ruff check tests/unit/data/providers/tardis/test_tardis_binance.py tests/unit/data/providers/tardis/test_tardis_decoder.py tests/unit/test_reference_data.py tests/unit/financial_units/test_p1_hand_ledger.py
uv run --frozen --no-editable ruff format --check tests/unit/data/providers/tardis/test_tardis_binance.py tests/unit/data/providers/tardis/test_tardis_decoder.py tests/unit/test_reference_data.py tests/unit/financial_units/test_p1_hand_ledger.py
uv run --frozen --no-editable mypy --strict tests/unit/data/providers/tardis/test_tardis_binance.py tests/unit/data/providers/tardis/test_tardis_decoder.py tests/unit/test_reference_data.py tests/unit/financial_units/test_p1_hand_ledger.py
uv run --frozen --no-editable alpha-governance-engineering-standards
uv run --frozen --no-editable alpha-governance-architecture
git diff --check
```

Results: **14 tests passed in 0.58s**, zero skips/deselections; Ruff lint and
format checks passed for four files; configured strict mypy passed for four
files; the engineering checker passed its entire protected scope; local links
passed for all 24 discovered documents, including all three changed documents.
`git diff --check` passed. The first format check requested one line-wrap change
in the new arithmetic test; `ruff format` fixed it before the final checks.
No behavior test failed. Only prose and the validation record changed afterward;
their link/whitespace checks were renewed without repeating unaffected tests.

At the original 2026-09-11 handoff, both final notebook kernels were shut down, and the entire
`/private/tmp/alpha-p1-mr-00` directory (notebook, script, connections and any
checkpoints/exports) was deleted. No other notebook copies existed at that handoff.
Tracked and untracked notebook queries, the staged diff and branch history were
checked for notebook additions; none remain. The changed files are staged for
local review without creating an implementation commit.

On 2026-09-13, the founder replaced the temporary-path/deletion convention with
locally retained executable examples in repository-root `examples/`, ignored by
Git. The MR 00 example was reconstructed as `examples/p1-mr-00.ipynb` with
`examples/run_notebook.py` and local usage instructions. It is a new local copy,
not a claim that the original deleted notebook was retained. Execute from the
repository root:

```sh
uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py
```

All four code cells passed in two fresh kernels; both kernels were shut down and
their temporary files removed. The notebook retains its outputs locally. The
first population attempt was blocked by sandbox access to the uv cache; an
escalated retry succeeded. An earlier scaffold-only run is not counted as example
validation. Git ignore and documentation link/whitespace checks passed afterward.
Production behavior and retained tests did not change, so their prior evidence
is reused. No source access, commit, push, merge or next MR was performed.

The founder subsequently refined the 2026-09-13 notebook preference: maintain
long-lived data-fetching, EDA, quant strategy research and strategy monitoring
notebooks, with the package owning productionized infrastructure and versioned
strategies. The roadmap, research program and ignored examples instructions now
reflect that lifecycle. At that prose-only checkpoint the notebook and runner
were unchanged;
activity notebooks will be split out when there is working content to separate.
This prose-only update changes no runtime code, retained tests or dependencies.
Local links and whitespace checks passed; prior runtime/notebook evidence remains
applicable. One-MR-at-a-time review and existing source/release boundaries remain.

The founder then authorized the notebook rework on 2026-09-13. The working file
is now `examples/research-foundations.ipynb`; the previous local copy is preserved
at `examples/archive/p1-mr-00.ipynb`. Its nine code cells provide a question and
hypothesis, four editable synthetic scenarios, computed comparison/clock/boundary
tables, independent fixed reference examples, and findings with a next question
and promotion decision. Activity notebooks will emerge as working content grows.
The runner accepts an explicit notebook path, defaults to one fresh kernel, and
saves distinct completed or failed attempts under ignored `examples/runs/`.
Snapshots include the executed source hash, attempt ID, times, status and outputs.
They are local convenience records, not the future packaged trial journal.

The final notebook source SHA-256 is
`72d7fd968371243b22fca5a54f5d110bf24430586b27cab4d5065b9c157abeb8`.
It hashes the JSON array of cell-type/source pairs with UTF-8, unescaped Unicode
and compact separators, excluding outputs and execution metadata. The notebook
also verifies all 30 installed runtime files against source and records the
candidate, lockfile, catalog and experiment-input identities. The runtime and
lockfile digests above remain unchanged.

The default single execution and an explicit
`python examples/run_notebook.py examples/research-foundations.ipynb --repeat 2`
(using the same frozen `uv` tooling prefix above) passed all nine cells in each
fresh kernel. A disposable copied scenario changed quantity to `0.00120000`:
its notional became `81.04801200 USDT`, while the fixed `98.60841460` notional and
`17.58` hand-ledger result still passed. The copied notebook's actual path,
source hash and attempt ID agreed with its snapshot. A deliberate error produced
one failed snapshot, a nonzero exit and no second repetition or working-file
overwrite. Invalid repeat counts, non-notebook paths and paths outside
`examples/` were rejected before execution. An initial diagnostic expected a
particular display scale; it was corrected to assert exact Decimal values rather
than trailing-zero formatting. No package behavior failed or changed.

Ruff lint/format checks passed for the notebook and runner. Documentation links,
including the ignored examples README, and diff whitespace checks passed.
Disposable diagnostic scripts/notebooks/snapshots and temporary kernel files
were removed; the working notebook, historical copy and actual execution
snapshots remain ignored and untracked. Production-code delta remains **0 lines**;
the prior 14 retained tests and static checks remain applicable. Hosted gates are
unchanged. No source access, commit, push, merge or next MR was performed.

## Risks / reversal

Source access, permitted use/retention, historical eligibility and source revision
availability remain unresolved. No source probe or research result was produced.
The frozen tick, lot, fee and full-fill assumptions do not prove venue fidelity,
capacity or trading readiness. Hosted source validation, macOS wheel smoke and
the authoritative merged-result lane remain required before merge; no hosted
run was triggered. Runtime source and package metadata are unchanged, so the
focused installed-package notebook/tests suffice for this local slice; no new
full local suite or wheel rebuild was needed.

Revert only this MR's specification/status/test changes before dependent
consumers merge, preserving `d39fd88`. If the selected experiment later changes,
version its specification and retain influencing attempts under the research
program rather than retroactively replacing the frozen case.

## Checkpoint follow-up — 2026-09-13

The founder requested one commit/push/merge checkpoint containing the current
work. This combines the unmerged roadmap commit `d39fd88`, the MR 00 specification
and tests, local notebook workflow, decoder API cleanup, and implementation
guideline. The earlier instruction to merge the roadmap separately is superseded
by this combined checkpoint. Further cleanup and MRs 01–28 remain outstanding.

`BinanceTardisDecoder` is now the public reusable decoding API. The standalone
`decode_tardis_line` wrapper and its exports are removed; retained callers use
an instance's `decode_line` method. The wheel smoke verifies the public class
import. The engineering guide now confines workflow wrappers to orchestrator
pipelines and requires other implementation modules to remain libraries.

Current focused validation from the repository root:

```sh
uv run --frozen --no-editable pytest -q tests/unit/data tests/unit/test_reference_data.py tests/unit/financial_units/test_p1_hand_ledger.py tests/engineering/test_package_definition.py
```

All **36 tests passed**, with no skips or deselections. Focused Ruff lint,
formatting and strict mypy checks, engineering standards, documentation links,
and the isolated installed-wheel smoke also passed during decoder cleanup.
The six retained local notebooks and execution snapshots are ignored under
`examples/`; no notebook or example is tracked or present in the branch history.
Historical notebook snapshots were not rerun against the changed decoder API.
Hosted source validation, macOS wheel smoke, and the authoritative merged-result
lane must pass for the published checkpoint before merge.

Removing the wrapper is an intentional import/API break; external callers must
construct and reuse the decoder. Reversal restores the checkpoint's API and
caller changes together while preserving later dependent work. This checkpoint
does not claim source access, a completed pipeline, or empirical acceptance.
