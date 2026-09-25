# MR07A common BBO and incremental L3 aggregates

[Roadmap and delivery dependencies](../README.md#delivery-order-and-dependencies).

Status: **complete for the declared per-book scope**, 2026-09-25. Owner: quant development. This extends
`market_data` book contracts and their existing research/paper consumers.
MR03 already projects complete L3 observations to aggregate depth, and MR07
derives touch prices/quantities for paper matching. This milestone makes those
semantics reusable and maintains L3 aggregates as orders change.

- Define a typed per-book BBO result with venue/instrument identity, exact
  bid/ask prices and quantities, original source/receipt/availability clocks,
  sequence/epoch and quality. Missing sides and unavailable or invalid state
  remain explicit; only complete accepted message boundaries are observable.
- Update aggregate quantity and order count by side/price on L3 add, amend,
  partial fill and delete. Preserve native order IDs and L2 absolute-size
  semantics. Snapshot replacement, gaps and recovery reset or invalidate the
  derived quote consistently; no queue priority is inferred.
- Integrate shared quote/depth behavior into existing research projections and
  live paper delivery. Keep historical native/canonical evidence readable and
  retain exact arithmetic, causal availability and independent package ownership.

Acceptance: compare incremental levels and BBO with independently recomputed
expected state across multiple orders at one price, side/price amendments,
partial fills, deletion of the best/last level, missing sides and snapshot/gap
recovery. Exercise the affected installed research/paper consumer boundaries and
saved-input replay parity. Reuse unaffected venue-protocol evidence; record any
schema/state migration with the delivered implementation. Container choice remains
an implementation decision; MR15 qualifies throughput, latency and memory.

Delivered behavior and compatibility:

- `VisibleBook` owns incremental exact quantity/count changes alongside native
  order IDs. L3 set/remove operations move contributions between side/price
  levels and delete the last level. OKX absolute-size L2 semantics are unchanged.
- `BookQuote` / `BookQuoteSide` are frozen typed per-book values.
  `BookProjection.quote` uses the incremental native cache; `BookDepth` supplies
  the same projection for old canonical observations. Source, receipt and
  explicitly supplied delivery clocks remain distinct. Unavailable, empty,
  one-sided, locked and crossed states are explicit.
- `CapturedStudyMarket`, live imbalance and `PaperCaptureObserver` consume shared
  depth/quote behavior. Live quote availability is the original market delivery
  time; controls cannot refresh it or bypass existing causal/freshness admission.
- Existing L3 canonical records remain order-only, and native fingerprints,
  capture schemas, request identities and paper journal envelopes are unchanged.
  The cache rebuilds from retained frames, so no stored-state migration is needed.
  Collector packaging retains its existing independent ownership; the portable
  execution package has no new market-data or research dependency.

The [market-data guide](../../../src/market_data/README.md#shared-book-quotes) owns
API semantics and limitations; the [observation guide](../../../src/research/observations/README.md)
and [paper guide](../../../src/applications/paper/README.md) own consumers.
Evidence is retained under ignored `logs/mr07a/`:

| Boundary | Evidence and observed outcome |
| --- | --- |
| Exact lifecycle and failures | `tests/unit/data/test_book_quotes.py` compares every native L3 boundary with independent full aggregation, including low Decimal precision, same-price orders, side/price changes, best/last deletion, invalid partial snapshots, gaps and replacement epochs. Coinbase fixtures add exact partial/full fills; quote round-trip and malformed clock/side cases preserve explicit unknowns |
| Installed saved native replay | `saved-replay/result.json`: retained MR07 OKX and Bitfinex captures expose 73 and 247 accepted quote boundaries, with original final book/trace identities unchanged. Published 32-record prefixes retain query/replay parity, every completed checkpoint, and fresh-process restart |
| Installed costed research | `captured-study-final.log`: both retained MR02 sources complete two decisions/two fills. Expected fees remain 0.01681253 USDT for OKX and 0.02 USD for Bitfinex. The `receipt-as-matching-v1` assumption and source limitations remain explicit |
| Installed actual public paper input | `live-okx/summary.json`: 56 frames, one snapshot, 54 updates and seven decided timers. `live-bitfinex/summary.json`: 145 frames, one snapshot, 140 updates and five decided timers. Both eight-second captures have no observed gaps and raw replay parity |
| Saved delivery and paper recovery | Both live output trees retain exact paper step/order/ledger replay, equal shadow intents with zero fills, original delivery clocks and fresh-recording restart without duplicate effects. These engineering passive orders produced no live-input fills |
| Source correspondence | `installed-source-parity.json`: all 274 installed runtime/source/resource files match the source used for saved and live acceptance; source identity `c573acb45410efc863ceefc6efcd8c2dc470dc0f294a3fd019757039a6cab5df` |
| Independent collector installation | `collector-boundary/README.md`: admitted 14-wheel/16-edge closure, isolated offline install and pip check, all 156 local wheel members equal source and installed files, no research/simulation/execution packages. Installed quote and CLI replay preserve both venues' original book/trace identities. Final collector SHA-256 `a4a2daeffafbd8bc8820d9441fde957f968df4f1e5f3a00d3fa76bd8c4b450f0`; unchanged contracts wheel `1e661e802fb2c4f6f86d6e0ed589de6a74f69c7ac0d3b8fd9505e6ee244c6194` |

Two complete source/test lanes passed 1,507 tests each, but the final installed
wheel's outer book-workflow watchdog timed out at 60 seconds. The original logs
remain `make-check-before-wheel-timeout.log` and
`make-check-before-watchdog-fix.log`; the first wheel and produced reports remain
under `wheel-timeout/`. The same installed workflow passed independently in 3.064
seconds (`wheel-diagnosis.json`). An instrumented full layout
(`wheel-layout-trace.log`) showed the parent waiting for its nested CLI before a
successful completion. The outer and nested watchdogs both allowed 60 seconds,
leaving no startup/verification/shutdown allowance. The outer watchdog now uses
the existing installed-backtest integration's 120-second bound; the nested CLI's
60-second limit and all assertions remain unchanged. The corrected isolated
boundary passed (`wheel-layout-final.log`). These observations do not establish
a runtime latency budget; MR15 still owns that qualification.

The final complete gate passed: `make-check.log` records **1,507 passed, three
performance tests deselected, zero skips**, with the real pinned Feast worker,
strict typing/stubtest, governance/security/audit checks and isolated installed-wheel
smoke. `final-wheel/` retains the identical research wheel
(`668549d8a2d7b7fda155bbce23a2c2510c95ef0392b2b81e2167e871a5bad27f`),
requirements, smoke inputs/results and exact source/installed-member correspondence.
`final-candidates-source/` and `final-candidates-feast/` retain the final installed
candidate consumer outputs. The full command was:

```sh
UV_PROJECT_ENVIRONMENT=/private/tmp/ar07a-gate TMPDIR=/private/tmp \
  ALPHA_FEAST_WORKER_PYTHON=/private/tmp/ar07a-feast/bin/python \
  PYTEST_ADDOPTS=--basetemp=/private/tmp/ar07a-check-gate \
  make check > logs/mr07a/make-check.log 2>&1
```

The final roadmap status/evidence edit is editorial; its links were checked again
without rebuilding unchanged package bytes. `consumer-commands.json` retains
exact saved/live invocations, and `consumers/` retains the copied scripts.
Task-specific temporary environments are removed after retaining their evidence.

The source protocol and endpoint implementations are unchanged. Earlier venue
qualification is reused; these new public-input runs renew the changed
quote-to-paper boundary, not private execution fidelity. Coinbase remains
fixture-qualified and its external access limitation is unchanged. No source
availability or empirical strategy claim is inferred from simulated matching.

Commands used the installed research interpreter with `-I` and copied existing
consumers under `/private/tmp/ar07a-consumers`, running outside the checkout:

```sh
/absolute/core/bin/python -I /private/tmp/ar07a-consumers/parity_consumer.py \
  /absolute/repository/logs/mr07a/saved-replay \
  /absolute/retained-okx-capture /absolute/retained-bitfinex-capture
/absolute/core/bin/python -I /private/tmp/ar07a-consumers/live_paper.py \
  --config /absolute/repository/logs/mr07a/live-configs/okx.json \
  --output /absolute/repository/logs/mr07a/live-okx
```

Use `bitfinex` in the live config/output names for that venue. The initial saved
study check in `captured-study/` preceded the stale-observation compatibility
adjustment and is retained separately; `captured-study-final/` renews that proof.
No whole prerequisite milestone was closed: this slice uses completed MR01–MR07
contracts. MR07B consolidation, MR15 measured capacity, MR08+ operating outcomes
and MR17/G5 remain open. Reversal selects the prior compatible code and existing
retained raw/canonical/journal bytes; do not rewrite historical hashes or clocks.
Production deployment and live trading remain separately authorized work.
