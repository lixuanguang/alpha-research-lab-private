# Saved L2 order-book backtesting

Owner: repository founder. Status: implemented for bounded offline spot research.
Acceptance date: 2026-09-22. Scope and original acceptance criteria:
[MR 9A](../roadmap/README.md#l2-order-book-backtesting). This is an engineering
example, not a selected alpha strategy or a live-execution qualification.

## Run the complete workflow

From the repository root, with the pinned uv environment and the existing saved
archive present:

```sh
uv run --frozen --no-editable alpha-backtest books \
  --config configs/backtests/okx-eth-usdt-book-v1.json \
  --archive data/okx/history/f62e64b7-1b40-4869-8b05-2ca911fefcef \
  --output logs/book-backtest/runs
```

The command reads saved files only and prints its unique result directory. Open
`report.html` there. `report.json` retains the exact results, `eda.json` contains
10,000 descriptive observations, `configuration.json` contains the resolved
selection, and `checkpoint-0.json` / `checkpoint-1.json` contain the independent
rule/control accounts. Each checkpoint includes decisions, orders, per-level
fills, valuations, original source coordinates, both book information sets,
pending deliveries/responses and consumed liquidity. `attempt.json` identifies
that execution. The existing `AttemptStore` retains completed, failed and
intentionally interrupted attempts under the output root's `attempts/` directory.

The [order-book notebook](../../examples/orderbook-research.ipynb) calls
`applications.backtest.run_books`, the same shared orchestrator as the command,
and plots the retained EDA and NAV. It contains no copied replay, strategy,
execution or accounting implementation. For fresh-kernel execution:

```sh
uv run --frozen --no-editable python -c 'from applications.backtest import run_books'
uv run --frozen --no-sync --with 'nbclient==0.10.4' --with 'nbformat==5.10.4' \
  python examples/run_notebook.py examples/orderbook-research.ipynb --kernel-python .venv/bin/python
```

The kernel requires the notebook dependencies described in the
[operations guide](../../examples/notebook-operations.md#historical-order-book-study).
Keep executed notebook copies and generated market-derived results outside Git.
The maintained notebook has cleared outputs.

## Source, configuration and implemented owners

The saved full-day archive is 97,973,786 bytes with SHA-256
`d5d530e6ce635d0e92ba4cd6d280b0aa2f64e918f09e2822018ed061846e1ea3`.
The selected first 10,000 messages span **2026-09-20 00:00:00.001 through
00:06:00.252 UTC**. Complete compression/tar integrity and original raw hashes are
verified; only the selected prefix is semantically reconstructed. The
[configuration](../../configs/backtests/okx-eth-usdt-book-v1.json) sets a terminal
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
| `research.experiments` | Existing attempts, fingerprints, atomic result publication and QuantStats projection; L2 report |
| `applications.backtest` | Shared configured composition and the existing `alpha-backtest` command |

The original trade-price simulator, source-admission rules, vectorbt comparison
and frozen P1 configuration/experiment remain unchanged. L2 results never enter
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

## Observed result and acceptance evidence

The real saved-data installed-package run produced:

| Instance | Orders | Level fills | Terminal cash / NAV (USDT) | Position (ETH) | Fees (USDT) | Net P&L (USDT) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Imbalance | 62 | 78 | 998.35849845 | 0 | 1.62998455 | -1.64150155 |
| No-trade | 0 | 0 | 1000 | 0 | 0 | 0 |

No order in this particular real window required partial cancellation. Independent
fixtures establish partial fills and consumption; the real run establishes the
saved-source integration. The negative result is retained without tuning the
rule or modifying the frozen P1 experiment.

Verification commands and scope:

- Focused book/trade/accounting/replay regression invocation: **79 passed,
  1 deselected**. It includes all `tests/unit/simulation`, ledger tests, P1 hand
  ledger, book replay/input/dataset tests and OKX archive tests.
- `pytest -q -m integration tests/integration/test_book_backtest.py`: **1 passed**.
  The installed CLI runs from outside the checkout over native ETH-USDT and
  BTC-USDT fixtures, verifies three isolated accounts and byte-identical complete
  versus resumed reports/checkpoints, and retains a corrupt-source failure.
- Hand calculations cover level walking, exact fee/cash postings, proportional
  basis, partial sales, cash/participation caps, source depletion and a hostile
  Decimal context. Causal tests change future books, delay deliveries, tie source
  updates to arrival, hide pending responses, reject invalid/stale books and check
  seven restart boundaries including pending orders and consumed liquidity.
- Full strict mypy, Ruff lint/format and engineering-rule checks passed. Final
  acceptance artifact paths and additional checks are recorded below.

The first integration harness attempt failed while deliberately trying to corrupt
an immutable raw file. The fixture now explicitly makes its own temporary file
writable before corruption; runtime raw-file protection remains unchanged. That
harness failure is separate from the deliberately retained source-rejection proof.
Hosted source/macOS/merged-result CI remains the pre-merge gate and is not claimed
by local validation.

## Retained local acceptance artifacts

Tested from `main` base `98d0724` plus this implementation's working-tree changes.
The final installed-code SHA-256 is
`c8fcc0d9ee99b0c96fa761ef6370f5b6c60fa1bc3ef2d406623f643dd56c121f`;
environment SHA-256 is
`98584a361d334c54fa9e0e83370a061dfe2d397da76d39ab1cbec368fd59b1e8`.
The resolved run identity is
`16ed529078a3fff5ff1ddaeddef9061cd4cdbbf1de489de411b2fcdfbb3eae1b`.
The report also retains the complete configuration, native request and raw identity.

- Final executed notebook: `examples/runs/orderbook-research/7ee6e315-2e05-4108-a743-f2db8575e3de.ipynb`.
  All 12 cells, including six code cells, passed in a fresh installed-package
  kernel. The saved-source workflow cell took approximately 71 seconds on this
  local run; this is an observation, not a performance guarantee.
- Final report directory: `logs/book-backtest/notebook/1196a3b0c74b42c7b88e47e6501a1857/`.
  HTML SHA-256: `92de1003c98c255d2ac6567533950f8bf7f981b867f9c955d121ac1549dcd5bd`.
  Exact report JSON SHA-256: `9caced57c59e59ca546193ee0adf1c07718367e4f20aeed7d60f1a0fd1f148d2`.
- Actual pending-order interruption: `logs/book-backtest/acceptance/5dac56f9b71a41dc82770c34f52fb705/`.
  At 00:00:08.010 UTC it retained one pending order, ten pending feed deliveries
  and zero fills. The command ran outside the checkout using the installed executable.
- Actual resumed run: `logs/book-backtest/acceptance/d016299aee40486b837c3f410c0f54a0/`.
  Its EDA, both complete checkpoints, JSON report and HTML report matched the
  uninterrupted `logs/book-backtest/notebook/5b7128beae544e75805d40a86591a659/`
  run **byte for byte**.

Those real restart runs used installed implementation
`b94c32d45c541535eb57e475b3cd938401870505e6d5254ca0c3ef7a5180ecd5`.
The final change replaced two redundant assertions with explicit validation for
Bandit. The final notebook renewed the real-source proof; its EDA bytes and both
complete account states matched those earlier runs exactly. Complete checkpoint
identity fields intentionally change when installed code changes. Final installed
fixture execution renewed all 18 mechanics cases and the outside-checkout
multi-account restart case: **19 passed**, no skips or deselections.

Additional final checks: strict mypy **351 files**; native stubtest **1,562 modules**;
Ruff lint and format **358 files**; engineering/source ownership checks;
Bandit; secret scanning **462 tracked paths plus 13 new files** in separate
scanner invocations; and local links **37 documents**,
including the changed example/component guides. The separate source-layout plus
book-mechanics selection passed **47 tests**. The direct secret-scan attempt first
lacked its subprocess executable on PATH; rerunning through the pinned uv
environment passed. Dependency pins, admission scope and native stubs were not
changed. Full hosted CI is still required before merge; no release or deployment
acceptance is implied.

These paths are local ignored artifacts, not a backup or distribution of market
data. Preserve the complete archive directory and result directories when moving
this study; hashes alone cannot recover missing files. The maintained notebook
has its outputs and execution metadata cleared.

### Full local pre-merge validation

On 2026-09-22, implementation commit `ab93884` passed the complete local lane:
`TMPDIR=/private/tmp MPLCONFIGDIR=/private/tmp/alpha-l2-merge-fonts make check`.
The suite passed **1,226 tests**, with **three performance cases deselected and
zero skips**, followed by successful installed-wheel API, command, recovery and
historical-snapshot consumers. All configured static, governance, dependency audit,
security and secret checks passed. The complete log is retained at
`logs/book-backtest/merge-validation/make-check.log`. This extends the focused
acceptance above without changing the runtime or frozen experiment. Hosted checks
and merge outcome are recorded on [PR #76](https://github.com/lixuanguang/alpha-research-lab-private/pull/76).

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
