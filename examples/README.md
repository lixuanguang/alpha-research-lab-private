# A quant researcher's guide to this project

Owner: repository founder. Updated 2026-09-16 for the MR 08 implementation candidate.
This is the living entry point for using the project as a researcher. The
[roadmap](../docs/roadmap/README.md) remains the authority for delivery and acceptance;
this guide explains what you can do, how to read the evidence and what remains open.

## Start with your research question

| What I want to understand | Open this notebook | What it gives me | What running it does |
| --- | --- | --- | --- |
| What historical trades do I have, and can I inspect the same inputs again? | [Historical trade-data exploration](research-foundations.ipynb) — start here | Original Binance rows, selected-hour observations, clock distinctions, exact amounts and visible data failures | Reuses the matching saved run; may download the configured day when the run is incomplete. Cache-only mode is available. |
| How could timing, units or damaged inputs change my conclusions? | [Data reliability lab](foundation-contract-checks.ipynb) — optional depth | Small synthetic examples of availability, arithmetic, wrong inputs, interruption and recovery | Offline; creates temporary test files and child processes. No provider access. |
| What can I observe about the order book, and what happens across gaps? | [Order-book observations](market-data-capture.ipynb) — separate activity | Bounded live observations, saved reconstruction, gap examples and an OKX historical prefix | Contacts sources, records new data and downloads an archive. Coinbase live access depends on local eligible credentials. |

Read the question and output interpretation in each section before inspecting its
code. Setup and implementation-heavy cells are collapsed in clients supporting
Jupyter cell visibility; expand them when needed. For execution, restart the
kernel and **Run All in order**: later cells depend on earlier ones. Each notebook
runs independently of the other notebooks.

For interpreter setup, actual commands, cached-data controls and error recovery,
use the [notebook operations guide](notebook-operations.md). Reading the saved
notebook outputs does not start a download or collector.

## What the historical workflow can do today

You can choose the supported source and interval, obtain its original file,
preserve that file, reopen it and inspect its rows with a trace back to their origin.
The current maintained example studies **BTCUSDT spot trades on 1 June 2024,
00:00–01:00 UTC**. Binance packages this source by day, so the notebook reads the
whole daily archive and then selects the research hour.

The [MR 08 verified run](../docs/roadmap/mr-08-implementation.md) read 638,484 rows
in that saved daily archive and selected 27,480 trades in the hour. These are
observations from that identified run, not a required future row count or proof
that every market trade was captured. Its source file, settings and original
acquisition records remain together in the local working copy.

| Completed work | What I get as a researcher | Research problem it addresses |
| --- | --- | --- |
| MR 03: identify saved input | An exact content fingerprint and a record of which request the file belongs to | I can detect changed input and identify what an experiment used. |
| MR 04: preserve originals | Complete saved files that repeated writes cannot silently replace | An interrupted save cannot expose half a file as ready for analysis. |
| MR 05: controlled download | Explicit access, response, integrity and timeout failures | Failed acquisition cannot quietly masquerade as usable input. The original Tardis path has synthetic evidence; the actual current workflow uses Binance. |
| MR 06: resume collection | A saved checklist of verified completed files | I can continue unfinished work without repeating completed downloads. The unfinished file may need downloading again. |
| MR 07: run and observe acquisition | A documented command, saved settings and progress/status | I can tell what was requested, what was saved and why a run stopped. |
| MR 08: inspect original rows | Exact row text, source order, row positions, file origins and research bounds | I can trace observations and see missing or malformed input without silent drops or invented observations. |

The fixed [P1 experiment specification](../docs/research/p1-baseline.md) retains the
sample, hypothesis and economic assumptions. These acquisition exercises do not
change it or report a strategy result.

## How to interpret the evidence

**An unchanged file** means its bytes match the saved fingerprint. It does not
establish that the provider observed every trade or that every value is correct.

**A missing file** means an expected input is unavailable. **An empty CSV** means
that particular file contains no rows. Neither establishes a quiet market.
The Binance reader reports recorder coverage as **unknown**, including for a
nonempty archive. Do not turn these outcomes into zero activity or padded prices.

**Trade time** describes when the source reports the trade occurred.
**Local receipt and save times** describe acquiring this archive now. They do not
establish when that observation became available to a historical strategy. The
archive lacks the recorder/knowledge evidence needed to answer that separately.

**Two rows with the same timestamp** keep their original order. That preserves
what the source supplied; it does not establish a more precise arrival time.
Likewise, avoiding repeated file downloads does not remove duplicate economic
trades inside or across those files.

**Reopening the same saved input** helps reproduce an analysis. A later provider
revision or different implementation/settings needs its own identity. Keep older
raw inputs and run records; a content fingerprint alone cannot recover a lost file.

## What I can investigate, and what is still ahead

| Research task | Current position |
| --- | --- |
| Inspect trade fields, timestamps, source order and a selected period | Available in the historical notebook; numerical/time previews remain exploratory. |
| Check exact price × quantity values for small examples | Available through the existing financial-unit APIs; this is not an executed strategy ledger. |
| Learn how timing, wrong instruments, corruption and interruption are handled | Available in the offline reliability lab. |
| Inspect visible order-book observations and reconstruction | Available for the bounded collector examples, with each source's gaps and access limits reported separately. L2 aggregates price levels; L3 retains visible individual orders. Neither establishes fills or queue priority. |
| Obtain consistently interpreted historical trade events | Next: MR 09, binding decoded observations to raw sources. |
| Treat duplicate trades and corrections consistently | MR 10. |
| Establish the historically eligible research universe | MR 11–12. Today's instrument catalog is not historical eligibility evidence. |
| Decide whether the data meets the experiment's quality requirements | MR 13. Unknown required coverage or eligibility cannot silently pass. |
| Save and reopen an accepted, versioned research dataset | MR 14–16. This adds dataset-level acceptance beyond saved source files. |
| Run the frozen strategy and interpret costed results | Later research/simulation work in the roadmap. The acquisition notebook supplies no empirical strategy conclusion. |

## A useful way to work through a notebook

1. State the question and identify the sample. Distinguish a real source observation
   from a deliberately constructed teaching example.
2. Inspect the outputs: selected instrument and interval, row counts, clocks,
   values and any rejection or unknown status.
3. Explain what those outputs establish. Keep unresolved coverage, availability,
   eligibility and execution assumptions visible beside the finding.
4. Preserve the inputs and the attempted run before changing an interpretation.
   Keep code, small reviewed outputs and guide changes in Git; retain bulk data
   and generated run snapshots in their designated ignored locations.
5. Write the next research question. Change exploratory scenarios deliberately;
   keep fixed reference examples and the frozen P1 specification unchanged.

The notebook runner saves successful and failed attempts, but these local snapshots
are not a backed-up research journal. An attempt that influences hypothesis or
parameter selection also needs the [research program's trial record](../docs/roadmap/research-program.md#small-records-and-artifacts).
Final holdouts are not exploratory notebook inputs.

## Small vocabulary for reading existing outputs

| Term in the code or output | Researcher's meaning |
| --- | --- |
| Raw object | The original saved source file, such as the ZIP archive. |
| Partition | One requested piece of source data; here, one instrument's UTC day. |
| Manifest | A saved record of the request, its inputs and completed files. |
| SHA-256 / digest | A fingerprint used to detect changed bytes; it is not a completeness score. |
| Provenance / origin | The trail from an observation back to its source file, row and acquisition record. |
| Immutable | Preserve the saved original; make a separately identified version for a change. |
| Canonical observation | A consistently interpreted event that later analysis can use; the historical archive path reaches this in MR 09. |
| Replay | Process saved observations in order. Reconstructing a book alone does not simulate whether your order would fill. |

## Keeping this guide useful as the project grows

Update this guide in the same change that alters a researcher's workflow or adds
a usable capability. Refresh the date and status, the notebook entry point, what
the outputs mean, remaining limitations and the next useful research action.
Link the actual acceptance record for measured examples; do not present planned
work or an old sample count as newly verified behavior. The roadmap continues to
own MR scope, dependencies and acceptance.

Use a consistent notebook pattern: **question → sample and assumptions → action →
observed output → interpretation and limits → next question**. Keep technical
checkpoint IDs for traceability inside supporting notes, rather than making them
the research narrative. Put execution/repair detail in the operations guide and
shared calculations in the package once they become maintained behavior.

The current notebook explanations and cell visibility were reorganized on
2026-09-16. Executable cells, their order and prior outputs were preserved; their
existing execution records identify the earlier runs. See the
[verification note](notebook-operations.md#researcher-guide-verification) for this
presentation change.
