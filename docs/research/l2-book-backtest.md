# Saved L2 order-book backtesting

Owner: repository founder. Status: implemented for bounded offline spot research.
This guide owns the current saved-book command, outputs, financial assumptions
and recovery behavior. Original receipt times, sequence continuity, interval
coverage, historical eligibility and correction history remain unqualified.
A reproducible simulation does not establish an empirical alpha or live execution.

## Run the complete workflow

Before starting or resuming this research workflow, run `make local-services-up`
from the repository root and complete the
[research-session prerequisites](guide.md#before-every-research-session).

From the repository root, with the pinned uv environment and the existing saved
archive present:

```sh
uv run --frozen --no-editable alpha-backtest books \
  --config configs/backtests/okx-eth-usdt-book.json \
  --archive data/okx/history/f62e64b7-1b40-4869-8b05-2ca911fefcef \
  --output logs/book-backtest/runs
```

The command reads saved files only and prints its unique result directory. Open
`report.html` there. `report.json` identifies the exact results, `eda.json` contains
10,000 descriptive observations, `configuration.json` contains the resolved
selection, and `checkpoint-0.json` / `checkpoint-1.json` contain the independent
rule/control accounts. Each checkpoint includes decisions, orders, per-level
fills, valuations, original source coordinates, both book information sets,
pending deliveries/responses and consumed liquidity. `attempt.json` identifies
that execution. The existing `AttemptStore` retains completed, failed and
intentionally interrupted attempts under the output root's `attempts/` directory.

New runs serialize each named artifact once. The configuration, EDA, checkpoints
and report exports are read-only hard links to their retained artifact in the
same output filesystem. `report.json` uses `l2-book-report`: metadata and
SHA-256 references to the adjacent configuration, EDA and ordered checkpoints,
without embedding those payloads again. `BookReport.read(path)` verifies every
digest and reconstructs the complete report; any other report schema is refused.
To move a report, copy its directory with all companion files. To share the rendered summary alone, use
`report.html`. Existing resumption identity checks still apply.

`AttemptStore` shares byte-identical content across attempts in
that store using content digests while retaining each attempt's named artifact
paths. Copy an export to a separate working file before editing it. Deleting an
export does not delete the retained artifact. Historical report bytes are unchanged.

```python
from pathlib import Path
from research.studies import BookReport

report = BookReport.read(Path("logs/book-backtest/runs/<attempt-id>/report.json"))
```

Use the [research guide](guide.md) to design an economic study
around the supported interfaces and their limitations.

## Source, configuration and implemented owners

The saved full-day archive is 97,973,786 bytes with SHA-256
`d5d530e6ce635d0e92ba4cd6d280b0aa2f64e918f09e2822018ed061846e1ea3`.
The selected first 10,000 messages span **2026-09-20 00:00:00.001 through
00:06:00.252 UTC**. Complete compression/tar integrity and original raw hashes are
verified; only the selected prefix is semantically reconstructed. The
[configuration](../../configs/backtests/okx-eth-usdt-book.json) sets a terminal
of 00:06:00.500 UTC. Another checkout needs the saved archive directory; it is
not committed or downloaded implicitly.

`SourceAdapters.books` and the existing OKX native reconstruction retain the
original `received_ns=None` and `sequence=None`. The scenario never feeds
fabricated receipt clocks into `BookReplay` admission. Unknown continuity,
historical availability, eligibility and full-day coverage remain unproven.
Acquisition timestamps identify the download; they are not historical receipt.

| Owner | Reused or added responsibility |
| --- | --- |
| `market_data` | Existing verified raw store, archive reader and native book replay |
| `configuration` | `BookRun`, `BookInstance`, `BookTiming`: resolved versioned selections and exact units |
| `research.observations` | `BookFeatures`: exact spread, depth and imbalance over original observations |
| `strategies` | Stateless imbalance and no-trade rules, selected through `BookRules` |
| `simulation` | Separate exchange/delivered books, IOC execution, consumption and complete checkpoints |
| `risk` / `accounting` | Existing `SpotLimits`, fee calculation and `Ledger` exact postings/reconciliation |
| `research.experiments` | Attempts, fingerprints and retained artifacts |
| `research.studies` | Result publication, QuantStats projection and L2 report reading/rendering |
| `applications.backtest` | Shared configured composition and the existing `alpha-backtest` command |

The original trade-price simulator, source-admission rules, vectorbt comparison
and trade-price configurations remain unchanged. L2 results never enter
the trade-price vectorbt path. Rules must be stateless in this first book API;
a new stateful strategy needs an explicit versioned checkpoint contract.

## Financial and timing assumptions

The fixed rule targets 0.01 ETH when the normalized top-five bid-minus-ask size
imbalance exceeds 0.2, otherwise zero. It decides once per second from the latest
**delivered** book. Initial cash is 1,000 USDT per instance. The independent
maximum holding/order delta is 0.01 ETH, lot is 0.0001 ETH, and tick is 0.01 USDT.
These are declared research grids and limits, not a downloaded historical venue
instrument-rule snapshot.

The versioned scenario declares feed **100 ms**, processing **10 ms**, order-entry
**20 ms** and response **100 ms**. Source messages update the exchange book at
source time and the local book at source time plus feed delay. A decision freezes
its feature, sends after processing delay, and reaches the exchange after order
entry delay. The pending slot remains reserved through the response, preventing
reuse of cash/exposure or visibility of unacknowledged holdings. Original receipt
fields remain unknown. These constants are sensitivity assumptions, not measured
latencies or proof of historical tradability.

Equal-time phases are **source → feed → arrival → response → decision → mark**.
All source messages at a tie apply in original position order before arrivals.
Orders arriving at terminal can fill; new decisions at terminal are suppressed.
Unarrived orders are canceled at terminal. Fills whose response falls after the
terminal remain economically posted with their pending response in the checkpoint.

Buys walk asks upwards and sells walk bids downwards. Each level offers at most
`max(0, take_fraction × displayed size − consumed size)`, rounded down to whole
lots; the example uses `take_fraction=0.01`. Actual cash, fees and position limits
are checked per fill, reducing to the largest affordable whole-lot amount.
Remainders are canceled immediately. Fees are **10 bps taker**, rounded once per
price-level fill to 0.00000001 USDT using half-even. There are no maker fees,
resting orders, queue positions, hidden liquidity, shorts, leverage or derivatives.

Consumption survives same-price snapshots and size/order-count changes. Removing
a price level clears its consumption; subsequent reappearance supplies new
capacity. Larger displayed size can increase available capacity without erasing
prior consumption. This conservative no-market-impact model can double-count
historical depletion and does not model a counterfactual exchange response.
The position and participation caps define its supported engineering envelope;
they do not establish execution capacity.

Missing, crossed, stale, off-tick or invalid books prevent decisions and fills
with retained reasons. Source age may not exceed two seconds. A flat account can
be valued without a book; an open terminal position without a valid fresh mark
fails the attempt. Marks use exchange best bid, with no terminal liquidation,
liquidation fee or full-position depth guarantee. Depth slippage is attributed
relative to the arrival touch; the ledger also reconciles effective-price
realized plus unrealized P&L minus fees exactly to NAV change. Analytical returns
and drawdown are sampled float projections; no annualized or capacity claim is made.

## Interrupt and resume

Add `--stop-at '2026-09-20T00:00:08.010000+00:00'` to the command to retain both
accounts while the first strategy order is pending. The command prints a unique
checkpoint directory and records the attempt as intentionally abandoned. Resume
by adding `--resume /absolute/path/to/that/directory` to the original command,
omitting `--stop-at`. Resume verifies source, complete state digest, configuration,
installed implementation and environment identities before advancing the state.
It reconstructs the original prefix to validate its cursor. Incompatible schemas
and changed inputs are rejected. This is offline recovery, not broker recovery
from unknown sends or a paper-runtime journal.

Reversal: remove the book-specific configuration, consumer and implementations
together. Preserve saved inputs and retained attempts. The existing trade-price
path remains usable; an older wheel must reject the new checkpoint schema.
