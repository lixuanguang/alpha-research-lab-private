# MR07B book registry and consolidated BBO

[Roadmap and delivery dependencies](../README.md#delivery-order-and-dependencies).

Status: **complete for the declared read-only book registry and consolidated BBO scope**, 2026-09-25. Owner: quant development. Depends on MR07A;
the initial integration remains read-only market data and paper/replay consumption.

- Maintain independent book state under `(venue, instrument)` keys, preserving
  source/channel provenance and selecting one admitted source per book. Expose
  per-venue BBO lookup and consolidated BBO lookup through the same public owner.
- Require an explicit reference mapping for economically comparable instruments,
  quote currencies and quantity units. BTC-USD and BTC-USDT remain distinct;
  implicit FX conversion is unsupported. Name the crypto result consolidated BBO.
- Begin with a scan of cached venue quotes. At each query cutoff, use only then
  available observations and apply declared freshness/quality eligibility.
  Expiry and disconnect invalidate eligibility even without a new price update;
  saved replay must never expose a later cached quote at an earlier cutoff.
- Return the highest eligible bid and lowest eligible ask, summed size and
  contributing venues at each tied best price, original quote clocks and
  excluded/missing venue reasons. Mark partial coverage, absent sides and
  consolidated locked/crossed states explicitly. Reference paper/replay consumers
  demonstrate the query contract while fills remain tied to the selected venue.

Acceptance: independent multi-venue cases cover key isolation, tied prices,
empty sides, stale/disconnected venues, resynchronization, currency/unit mismatch,
cutoff ordering and replay/restart parity. Reuse retained OKX/Bitfinex recordings
for their native input paths; synthetic comparable-quote cases establish
consolidation correctness without relabeling USD/USDT captures as one market.
Record selected versus eligible coverage. Execution routing, shared-account
allocation and FX conversion remain outside this milestone; MR15 measures the
registry and quote workload before requiring a more complex index.

Delivered behavior:

- `BookRegistryConfiguration` binds exact source/channel selection to reference
  definitions, adapter capability, quantity units, freshness and degraded-quality
  admission. Explicit equivalent-market references carry knowledge and validity
  cutoffs; mismatched currencies, assets, products or units are rejected.
- `BookRegistry` owns independent native reconstruction and bounded cached quote
  histories. Per-venue and consolidated queries preserve causal cutoffs, original
  quote clocks, exact tie sizes, selected/eligible coverage and exclusion reasons.
  Expiry requires no new price message. Controls cannot refresh market age;
  disconnect/recovery invalidates the affected book without erasing earlier history.
- `run_live_paper` and `PaperCaptureObserver` use the selected venue's registry
  lookup before modeled matching. Callers may inspect explicit multi-venue groups;
  a better consolidated price never changes the venue used for a paper fill.
- The installed registry consumer reuses retained OKX/Bitfinex native journals in
  separate USD/USDT groups and authors comparable fixtures for consolidation.
  Historical queries and reconstruction exercise the same public registry.

The [market-data guide](../../../src/market_data/README.md#book-registry-and-consolidated-bbo)
owns configuration/API contracts; the [paper guide](../../../src/applications/paper/README.md)
and [test guide](../../../tests/README.md#registry-and-consolidated-quote-acceptance)
own application and installed acceptance commands. No native/canonical/dataset or
paper journal schema migration is needed: rebuild registry state from retained
records and delivery clocks. Reversal uses the prior implementation with those
unchanged original bytes.

Evidence is retained under ignored `logs/mr07b/`:

| Boundary | Evidence and observed outcome |
| --- | --- |
| Exact queries and admission | `focused-final.log`: 25 focused cases passed across registry, native quotes, live observations and paper application; `runtime-binding-final.log`: the later product/symbol admission regression passed (13 unrelated cases deselected). Registry cases include exact low-precision ties, same-venue instrument isolation, nanosecond source cutoffs, missing sides, expiry, disconnect/resynchronization and currency/unit mismatches |
| Installed native inputs and replay | `installed-registry/result.json`: 77 OKX and 253 Bitfinex records; 73 and 247 accepted market boundaries; native final book/trace identities preserved. The 660 selected singleton-coverage queries contain 320 eligible and 340 partial results. Native USD/USDT groups remain separate and explicitly use receipt-clock availability because original delivery is unknown |
| Historical and fresh-process replay | `installed-registry-restart/result.json` and `fresh-process-parity.json`: independent installed processes produce identical result and reverse-cutoff hashes. Fresh registries rebuild from original raw bytes; old cutoffs never see later cached boundaries |
| Synthetic comparable market and venue-bound paper | Installed consumer: consolidated ask 100 from Bitfinex; selected OKX paper IOC fills exactly 2 at 101, fee 1.01 USD and final cash 796.99 USD. Reopening and rematching adds no effects. This is authored software/accounting evidence, not a real comparable-venue quote or venue fill |
| Actual installed public paper input | `live-okx/summary.json`: 66 frames, one snapshot, 64 updates, seven decided timers. `live-bitfinex/summary.json`: 147 frames, one snapshot, 142 updates, seven decided timers. Both eight-second captures have no observed gaps and raw replay parity |
| Actual delivery and paper restart | Both live trees retain original receipt and actual delivery clocks, exact saved paper steps/orders/ledger, equal shadow intents with zero fills, and a fresh-recording restart without duplicate effects. These passive engineering orders produced zero fills; the synthetic IOC separately proves fill accounting |
| Research wheel source correspondence | `installed-source-parity.json`: all 290 installed source/resource members match checkout and wheel bytes; wheel SHA-256 `2b198bf22f8c75a36de2f915600fd5b6f6a0c97192e63a466a45a11326df5a7f` |
| Independent collector boundary | `collector-boundary/README.md`: current contracts/collector wheels pass the admitted 14-wheel/16-edge closure, offline installation, exact source/installed-byte checks and pip check. Installed native registry and CLI replay preserve both source identities; no research/simulation/execution packages are present |

`consumer-commands.json` records exact invocations; `consumers/` retains the copied
scripts. Native public-paper commands used the verified installed interpreter
with `-I` from `/private/tmp`, selecting the bounded files under `live-configs/`.
The owning test guide records the reusable registry command.

The first full gate stopped on a new runtime `assert`; it was replaced by an
explicit `ValueError` and the security check passed. The original log remains
`make-check-before-assert-fix.log`. A complete intermediate gate passed 1,518
cases (`make-check-before-binding-guard.log`); the later reference-admission guard
and regression required a renewed full gate. Its first focused attempt collided
with a concurrent reinstall of the shared development environment, producing a
missing installed module during collection (`runtime-binding-environment-race.log`).
The same regression passed in the separate task environment before renewing the
full gate. These are development corrections, not source- or venue-reliability
claims.

The final complete `make check` passed **1,519 tests, three performance cases
deselected, zero skips**, with the real pinned Feast worker, strict typing and
stubtest, governance/security/dependency audit and isolated wheel smoke. The
final wheel is byte-identical to the wheel used for installed registry and public
paper acceptance; `final-wheel/` retains the wheel, runtime requirements, smoke
inputs/results and source/installed-member hashes. The final command was:

```sh
UV_PROJECT_ENVIRONMENT=/private/tmp/ar07b-gate TMPDIR=/private/tmp \
  ALPHA_FEAST_WORKER_PYTHON=/private/tmp/ar07b-feast/bin/python \
  PYTEST_ADDOPTS=--basetemp=/private/tmp/ar07b-check \
  make check > logs/mr07b/make-check.log 2>&1
```

The retained MR06 execution consumer also accepts the new contracts wheel in an
isolated admitted eight-wheel/nine-edge environment; CLI import and dependency
checks pass without market-data or research packages. This is compatibility with
that retained consumer, not renewed execution-source or signed-release evidence.
The final roadmap status/evidence update is editorial; its links and changed
component/test-guide links were checked explicitly after the gate. Task-specific
temporary environments are removed after retaining evidence; no unrelated state
or historical inputs are cleaned.

Software query and modeled-account correctness remain distinct from original
source continuity, private venue execution, strategy evidence and deployment
readiness. Existing native endpoint qualification is reused because protocols and
endpoints are unchanged; actual public input renews the changed paper boundary.
No later-MR prerequisite slice was required or marked complete. MR15 measured
capacity, MR08+ operating outcomes and MR17/G5 remain open; live activation is
separate. The full research graph retains its existing QuantLib release restriction;
these local development checks do not grant a production release.
