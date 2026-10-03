# Notebook setup and retained results

Start with the [research guide](README.md) and [study protocol](study-protocol.md).
Updated 2026-09-24. This page owns execution of the new research worksheets.
The [market-data guide](../src/market_data/README.md) owns source acquisition and
selection; the [saved L2 workflow](../docs/research/l2-book-backtest.md) owns the
existing simulation command.

Before any research notebook session, run `make local-services-up` from the
repository root and complete the [research-session prerequisites](README.md#before-every-research-session).
Confirm lakeFS and ClearML are accessible before executing the worksheet or
starting or resuming a study.

## Research workbooks

The four research notebooks are designs plus analysis worksheets. Their result
lists start empty and report `AWAITING EVIDENCE`; they do not fetch data, run
strategies, fit models or trade. Supply measured summaries from a retained
study only after fixing its sample, comparisons and evaluation boundaries.
The cells document units and row meanings. Preserve the underlying event/order
trace; an aggregated table cannot establish source quality or execution fidelity.

Use the pinned environment from the [development guide](../docs/README.md#development-environment).
The new worksheets use pandas and the standard library. The kernel (`ipykernel`)
and the runner's `nbclient`, `nbformat` and `jupyter-client` are pinned in the
locked `notebooks` dependency group, which is installed by default with the
development environment and never ships in a runtime or partial distribution.

From the repository root:

```sh
uv run --frozen --no-editable python examples/run_notebook.py examples/opportunity-map.ipynb
```

The kernel defaults to the interpreter running the command; pass
`--kernel-python <path>` to select another environment that has `ipykernel`.

Replace the notebook argument with `examples/liquidity-taking.ipynb`,
`examples/liquidity-shocks.ipynb` or `examples/liquidity-provision.ipynb`.
With no notebook argument, the runner opens the opportunity map. It starts a
fresh kernel, runs all cells, retains a uniquely named executed attempt under
`examples/runs/<stem>/`, and updates the local notebook on success. Failures
retain their attempted outputs as well. No-data success confirms only that the
worksheet runs; it is not empirical acceptance.

An interactive kernel can run the new worksheets from any directory because
they do not resolve local data paths. Source acquisition and simulation use the
installed commands in their owning package guides.

## Retain the research, clear the maintained notebook

Keep source notebooks, Markdown and reviewed small evidence in Git. Keep raw
market data, account records, full outputs, fitted state and trial history in
the study's appropriate retained storage. `examples/runs/` is an ignored local
convenience, not a backup or the authoritative research journal.

Populate worksheets from retrievable study outputs. Keep formal attempts,
including failures and abandoned variants, in the [research record](../docs/roadmap/research-program.md#small-records-and-artifacts).
Retain the code/config, dataset, split, fee/feed regime and execution assumptions
with each result. Do not select parameters using a final holdout in a worksheet.

Before committing, review result rows, outputs and metadata for sensitive data
and stale claims. Clear code-cell outputs and execution counts in maintained
notebooks; retain executed copies separately. Keep the input lists empty in the
maintained research templates. No source or result is fabricated when input is
missing.
