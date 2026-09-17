# A quant researcher's guide to this project

Owner: repository founder. Updated 2026-09-17 for MR 14 dataset manifest identity.
This is the living entry point for using the project as a researcher. The
[roadmap](../docs/roadmap/README.md) remains the authority for delivery and acceptance;
this guide explains what you can do, how to read the evidence and what remains open.

## Start with your research question

| What I want to understand | Open this notebook | What it gives me | What running it does |
| --- | --- | --- | --- |
| What liquidity did my saved inputs show, and can I inspect them again? | [Saved order-book exploration](research-foundations.ipynb) — start here after acquisition | An OKX historical reconstruction summary, Bitfinex visible orders and spread, clock distinctions and visible data failures | Reads verified saved inputs only; no network or credentials. |
| How could timing, units or damaged inputs change my conclusions? | [Data reliability lab](foundation-contract-checks.ipynb) — optional depth | Small synthetic examples of availability, arithmetic, wrong inputs, interruption and recovery | Offline; creates temporary test files and child processes. No provider access. |
| How do I obtain a new sample without exchange account credentials? | [Acquire OKX and Bitfinex books](market-data-capture.ipynb) — run first if you have no saved inputs | Bounded public live observations, saved reconstruction, gap examples and an OKX historical prefix | Records two new live samples and downloads an archive; an explicit saved-archive override avoids the download. |

Read the question and output interpretation in each section before inspecting its
code. Setup and implementation-heavy cells are collapsed in clients supporting
Jupyter cell visibility; expand them when needed. For execution, restart the
kernel and **Run All in order**: later cells depend on earlier ones. Each notebook
runs independently of the other notebooks.

For interpreter setup, actual commands, cached-data controls and error recovery,
use the [notebook operations guide](notebook-operations.md). Reading the saved
notebook outputs does not start a download or collector.

## What data am I actually researching?

The maintained research examples now use **order books**, following the available
OKX and Bitfinex implementations. They require no Binance access. A book describes
displayed buying and selling interest; a trade records an executed transaction.
These are different observations and support different research questions.

| Sample | What I can inspect | What it does not tell me |
| --- | --- | --- |
| OKX BTC-USDT historical L2, 8 September 2026 | A verified daily archive and reconstruction summary for its first 10,000 records; reported depth is 400 price levels per side | Individual order IDs, source sequences, historical receipt times or proven continuity; this is a prefix, not the entire day. The current archive API does not return a price/feature table. |
| Bitfinex BTC/USD recorded R0 | A bounded live sample, visible individual orders, exact prices/sizes and the spread at its final reconstructed state; configured depth is 25 | Earlier Bitfinex history, exchange timestamps in R0 messages, hidden orders, queue priority or executable fills. |
| OKX BTC-USDT public live `books` | A bounded L2 sample with source timestamps, local receipt records and continuity checks | Individual orders or the full exchange book beyond the feed's depth. |

The capture notebook uses the public [Bitfinex raw-book feed](https://docs.bitfinex.com/reference/ws-public-raw-books)
and [OKX market-data APIs](https://www.okx.com/docs-v5/en/) without API keys
(documentation checked 2026-09-16). Source availability can still depend on the
endpoint and location; a denied request fails explicitly. There is no credential
prompt or automatic switch to another venue.

The samples differ in date, receipt interval, depth and quote currency: **USD is
not USDT**, and sequential live captures are not simultaneous. Do not subtract
their prices and label the result an arbitrage opportunity.

The main notebook selects the latest completed saved input matching each maintained
configuration, prints its identity and then verifies its bytes. For repeatability,
pin the printed directories using the [operations guide](notebook-operations.md).
A new capture is a new sample; it does not silently extend the previous recording.

## What the raw-input stage provides

The historical acquisition MRs provide the following foundations. Their original
acceptance uses Tardis/Binance contracts; the existing native
[Bitfinex collector](../docs/data/l3-collectors.md) and
[OKX readers](../docs/data/okx-market-data.md) have their own capture/archive
contracts and reuse shared storage. In particular, the resumable MR 06 checklist
does not make an interrupted OKX download or live recording resumable.

| Completed work | What I get as a researcher | Research problem it addresses |
| --- | --- | --- |
| MR 03: identify saved input | An exact content fingerprint and a record of which request the file belongs to | I can detect changed input and identify what an experiment used. |
| MR 04: preserve originals | Complete saved files that repeated writes cannot silently replace | An interrupted save cannot expose half a file as ready for analysis. |
| MR 05: controlled download | Explicit access, response, integrity and timeout failures | Failed acquisition cannot quietly masquerade as usable input. The original Tardis path has synthetic evidence; MR 07 added the historical Binance path. |
| MR 06: resume collection | A saved checklist of verified completed files | I can continue unfinished work without repeating completed downloads. The unfinished file may need downloading again. |
| MR 07: run and observe acquisition | A documented command, saved settings and progress/status | I can tell what was requested, what was saved and why a run stopped. |
| MR 08: inspect original rows | Exact row text, source order, row positions, file origins and research bounds | I can trace observations and see missing or malformed input without silent drops or invented observations. |
| MR 09: decode and trace occurrences | Exact archive trades, raw origins and stable identities across rebuilds, including separate input scopes | Repeated sequence numbers cannot confuse two files or make a disconnect apply to unrelated input. |
| MR 10: admit duplicates and corrections | One economic trade with all duplicate origins and explicitly evidenced predecessor versions | Inserted rows cannot create new trades, and a late correction cannot erase an earlier version. |
| MR 11: read eligibility assertions | Retained membership, evidence identities and independent valid/knowledge clocks tied to the selected catalog | A 2026-authored assumption cannot be backdated to the historical sample; excluded members remain visible. |

The fixed [P1 experiment specification](../docs/research/p1-baseline.md) retains the
Binance trade sample, hypothesis and economic assumptions. This notebook migration
does not replace that sample with book data or report a strategy result. Its source
access remains a separate unresolved research dependency for the frozen study.
The [MR 08 record](../docs/roadmap/mr-08-implementation.md) retains the earlier
verified Binance run (638,484 daily rows; 27,480 selected-hour trades). Its synthetic
row-order and missing-input checks now live in section 16 of the offline lab,
where they run without provider access.

Section 9 of [research-foundations.ipynb](research-foundations.ipynb) adds NB 09:
small **synthetic Binance trades** and Tardis controls, without Binance access.
It displays equal-time row order, colliding sequence numbers across files and
independent bindings, absent capture/knowledge clocks and explicit wrong-binding
rejections. This exercise is separate from the real OKX/Bitfinex book observations.
The [MR 09 record](../docs/roadmap/mr-09-implementation.md) identifies its tested state.

Section 10 adds NB 10: shifted-row duplicates, an explicitly evidenced late correction,
and reconstruction before/at its availability boundary. The evidence is **synthetic**;
it does not fill in missing historical archive knowledge. Invalid evidence and
unevidenced conflicts fail. The [MR 10 record](../docs/roadmap/mr-10-implementation.md)
identifies the installed candidate and required failures.

Section 11 adds NB 11: read the synthetic eligibility file and compare a
2026-authored assumption with synthetic evidence modeling availability in the 2024
sample. The table retains a hypothetical delisting, its reason and evidence identity.
Missing evidence, backdated knowledge/assumption availability, contradictory overlap
and changed catalog units are visibly rejected. The
[MR 11 record](../docs/roadmap/mr-11-implementation.md) records the fresh installed run.
These are supplied evidence attestations, not authenticated Binance documents;
the frozen P1 historical eligibility gap remains open.

Section 12 adds NB 12: select membership with independent validity and knowledge
cutoffs. The synthetic late listing correction leaves the earlier BTC+ETH universe
unchanged, then excludes BTC when the correction becomes known. Tables show before,
at and after both clocks' boundaries, the half-open endpoint, unknown and unsupported
outcomes, and four controlled failures. Only explicit inclusion enters the universe.
The [MR 12 record](../docs/roadmap/mr-12-implementation.md) identifies the installed
candidate. Selection alone does not produce an accepted dataset.

Section 13 adds NB 13: declare exploratory or causal use, inspect duplicate/gap
counts and compare the resulting publication gates. The synthetic archive can
produce deterministic **exploratory degraded** bytes with retained histories;
its unknown recorder coverage and historical availability prevent causal admission.
Seven examples refuse publication for required coverage, a foreign instrument,
an unevidenced conflict, a rewritten capture clock, NaN/zero prices and zero trade
quantity. Raw failures retain reasons and originals; there is no silent row drop
or filled gap. See the [MR 13 record](../docs/roadmap/mr-13-implementation.md).
Section 14 adds NB 14: rebuild a synthetic dataset twice, change its gap policy,
and compare manifest/canonical hashes. The reader verifies raw and canonical files,
retained quality scope and resolved references. Tables show matching repeat hashes,
a changed-policy identity and failures for unknown versions, causal scope, changed
identity and missing bytes. Relocating and restoring the same files preserves identity.
See the [MR 14 record](../docs/roadmap/mr-14-implementation.md). These working files
have no atomic snapshot visibility; that is the next research question in MR 15.

## How to interpret the evidence

**An unchanged file** means its bytes match the saved fingerprint. It does not
establish that the provider observed every trade or that every value is correct.

**A missing file** means an expected input is unavailable. **An empty input** does
not establish a quiet market. In the OKX historical summary, `gaps=None` means
continuity is unknown because source sequences are absent. A reconstructed book
can be available while coverage remains unproven.

**Source time** describes the exchange's timestamp where supplied.
**Local receipt and save times** describe the collector's observation or archive
acquisition. Downloading an old OKX archive now does not establish historical
knowledge time. Bitfinex R0 supplies receipt order and sequences, but no exchange
timestamp in these messages. Do not substitute one clock for another.

**A live gap** makes the reconstructed book unavailable until synchronization is
restored. A matching offline replay proves that the same saved messages produced
the same states; it does not prove complete observation of the exchange.

**Reopening the same saved input** helps reproduce an analysis. A later provider
revision or different implementation/settings needs its own identity. Keep older
raw inputs and run records; a content fingerprint alone cannot recover a lost file.

## What I can investigate, and what is still ahead

| Research task | Current position |
| --- | --- |
| Inspect historical book coverage and a bounded live book | Available in the main notebook: OKX prefix summary and Bitfinex visible prices/sizes/spread. |
| Check exact price × quantity values for small examples | Available through financial-unit APIs in the offline lab; this is not an executed strategy ledger. |
| Learn how timing, wrong instruments, corruption and interruption are handled | Available in the offline reliability lab. |
| Inspect visible order-book observations and reconstruction | Available for the bounded collector examples, with each source's gaps and access limits reported separately. L2 aggregates price levels; L3 retains visible individual orders. Neither establishes fills or queue priority. |
| Obtain consistently interpreted historical trade events | MR 09 supplies a saved Binance archive iterator with exact values and raw-origin identities. Historical availability and accepted dataset publication remain open. |
| Treat duplicate trades and corrections consistently | MR 10 supplies bounded in-memory admission, complete duplicate lineage and linear evidenced correction histories. Original archive knowledge remains unknown; accepted dataset publication is still ahead. |
| Inspect historical membership assertions | MR 11 reads evidence-labeled histories without dropping excluded members. Today's catalog is still an authored assumption. |
| Establish the historically eligible research universe | MR 12 selects by independent validity and knowledge, preserving corrections and explicit unknown/unsupported outcomes. Actual historical evidence is still required for empirical P1 acceptance. |
| Decide whether the data meets the experiment's quality requirements | MR 13. Unknown required coverage or eligibility cannot silently pass. |
| Identify admitted partitions and verify their saved files | MR 14 supplies deterministic manifest identity and verified reading, retaining exploratory degraded scope. |
| Publish and reopen an accepted, versioned research snapshot | MRs 15–16 add atomic publication and the dataset command. |
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
| Raw object | The original saved source file, such as the OKX archive or recorded message journal. |
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

The [migration verification](notebook-operations.md#okx-and-bitfinex-migration-verification)
records fresh executions and limitations for these examples. The earlier
[presentation verification](notebook-operations.md#researcher-guide-verification)
is retained as historical evidence.
