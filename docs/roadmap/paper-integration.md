# Public-input paper integration

Owner: quant development. Status: bounded delivery complete, 2026-09-27.
Scope: MR08/MR11, starting at `7d4b65d` on
`codex/mr11-mr08-paper-integration`. The starting worktree was clean.

## Bounded delivery plan

Deliver an installed OKX and Bitfinex spot path from native public books through
selected decision policies, existing portfolio/risk admission, simulated matching,
attributed accounting, independent reconciliation and retained net-P&L reports.
Use the [engineering guide](../coding_standards/README.md) and existing functional
owners. No credentials, private submissions, live capital or research claims.

1. Extend the existing paper execution contracts with versioned, explicit entry
   and cancel delay, adverse price, fee, liquidity and gas applicability assumptions.
   Reuse exact financial arithmetic and existing simulation cost semantics. Keep
   supported GTC/IOC/post-only behavior explicit and reject unsupported mechanics.
2. Extend `AccountJournal` with transactional automatic matching for admitted
   direct and net orders. Reuse lifecycle, allocation, risk reservations and ledger
   owners. Retain exact market/profile identities and matching traces so retry,
   partial execution and restart preserve finite liquidity and unresolved exposure.
3. Compose native `CaptureRunner`/`BookRegistry` inputs with the existing shared
   decision runtime and automatic matcher. Keep collection/receipt/availability
   clocks, stale-input rejection and per-instance policy continuation intact.
   Existing dedicated candidate workflows consume the same execution assumptions.
4. Add exact accounting-owned report projections with explicit marks, costs and
   strategy attribution. Net P&L includes execution-price slippage exactly once.
   Retain inputs, configuration/profile identities, orders, fills, residuals,
   reconciliation facts and reports through installed acceptance consumers.
5. Qualify each venue separately. Use independently authored numerical fixtures
   and failure cases, followed by installed native-feed workflows where public
   access permits. Record any missing observed boundary without relabeling fixtures.
   Update component guides and roadmap status against actual evidence.

The new abstractions serve these consumers: execution assumptions serve both
paper journals; a pure match evaluator serves their existing transaction owners;
the public-book observer serves the shared runtime; report values project existing
ledger facts for retained results/MR12. Existing risk, portfolio, account ledgers,
native adapters, candidate SDK and deployment boundaries remain authoritative.

## Sufficient verification

Focused tests cover independent fill/cash/fee/P&L arithmetic, no-trade and losing
controls, adverse-cost sensitivity, causal entry/cancel timing, price/lot limits,
partial fills, shared-budget contention, duplicate/reordered inputs, cancellation
races, stale books and restart. Reuse unchanged risk, allocation, private-adapter
and operational evidence; renew affected installed artifact and source checks.
Run repository-required `make check`, retaining failures and diagnosed reruns.

Fixture source clocks establish software properties. Observed public feeds establish
only the native-input boundary; modeled liquidity, delay, fills and fees remain
assumptions. Queue fidelity, calibrated costs, private venue qualification, MR12
dashboards, MR13 activation, MR14 broader integration and MR15 capacity stay with
their owners. Applicable gas is unsupported and must reject; off-chain spot must
retain an explicit inapplicability reason.

Reversal: revert code, configuration consumers and docs together. Preserve all
retained journals/captures/reports; older artifacts must not resume incompatible
execution-assumption or journal identities. No push, merge or deployment is part
of this work.

## Results and retained evidence

All five steps are implemented. MR08 and MR11 acceptance is complete for the
cash-funded, off-chain spot paper scope described here. Native authenticated
venue qualification and the wider operating milestones remain open/KIV.

### Installed user journey

The [paper application guide](../../src/applications/paper/README.md#automatic-public-input-accounts)
owns `run_live_shared_paper`: select a native capture configuration, execution
scenario, existing policy/context bindings, account budgets and an independent
opening observation; run the finite capture; independently reconcile its retained
orders/fills and inspect exact account/strategy costs and net P&L. A single binding
is dedicated operation; multiple bindings share admission, netting and attribution.
The existing dedicated candidate loader/runtime also consumes the same scenario.
The [test guide](../../tests/README.md#automatic-public-paper-acceptance) gives
copy-and-run commands for the installed reference consumer, controls and replay.

Matching preserves causal entry/cancellation, tick/lot and limit constraints,
finite displayed touch liquidity and partial fills. Repeated same-price size does
not replenish already consumed liquidity. Scenario identity, market/result bytes
and ledger changes persist atomically. Exact old input retries preserve newer
state; unknown orders and pending cancellation keep exposure. Known invalid
public inputs durably block further admission. Reports use a fresh last eligible
bid and charge effective execution prices and fees once; adverse slippage is
separately attributed without another P&L deduction. Gas is explicitly
inapplicable with a retained reason; applicable gas rejects.

The two reference policies are different implementations: one requests a fixed
opening clip, the other caps its clip by visible liquidity. Both subsequently
place resting limits. Shared children, partial fills, fees, pending reservations
and any physical-lot residuals remain attributable. These engineering policies
do not establish research quality or profitable trading.

### Commands and checks

The required full lane passed with a separate installed environment:

```sh
UV_PROJECT_ENVIRONMENT=/private/tmp/public-paper-installed \
  PYTEST_ADDOPTS=--basetemp=/private/tmp/paper-integration-check TMPDIR=/private/tmp \
  make check
```

`logs/paper-integration/make-check.log` records **1,710 passed, 2 skipped,
3 deselected**; Ruff, strict mypy, stub checks, engineering standards, dependency
admission/audit, architecture links, secret scan, Bandit and clean installed-wheel
smoke passed. The two skips require the separately configured Feast worker;
performance tests are outside this correctness lane. The existing development-only
QuantLib source-to-wheel qualification restriction remains unchanged; this work
does not grant artifact release approval.

After extending the consumer with a second-process `--replay` check, the affected
installed suite was renewed:

```sh
/private/tmp/public-paper-observed/bin/python -m pytest -q -m integration \
  --basetemp=/private/tmp/paper-integration-qualified-fixtures \
  tests/integration/test_public_paper_workflow.py
```

`installed-fixtures-qualified.log` records **8 passed**. The earlier full lane remains
evidence for unchanged runtime code. Focused owner tests additionally cover
cancel/fill races, uncertain exposure, failed posting rollback, stale source/marks,
duplicate and older retries, grid/limit refusal, exact corrections and unsupported
gas. Existing shared-budget contention and operational recovery tests were reused
in the full lane. Final source/document checks are retained in `final-checks.log`.

### Independent economic results

Each fixture uses 100,000 opening quote units, ask 100, bid/mark 99, a 0.1% fee,
one-millisecond entry delay, two-millisecond cancellation delay and 50% take
fraction. Shared baseline has two children of one base unit filled against the
four-unit parent, leaving two units pending; dedicated baseline fills one two-unit
child. Repeated displayed size supplies no additional liquidity. Golden arithmetic
uses independent rational calculations and explicit currency rounding.

| Venue / quote | Baseline fee | Baseline net P&L | Adverse 1.00 fee | Adverse 1.00 net P&L | No-trade fee / P&L |
| --- | --- | --- | --- | --- | --- |
| OKX / USDT | 0.201 | -3.201 | 0.202 | -4.202 | 0 / 0 |
| Bitfinex / USD | 0.20 | -3.20 | 0.20 | -4.20 | 0 / 0 |

Baseline adverse price is 0.50. Its slippage attribution is 1.00 total; the higher
cost case attributes 2.00, already embedded in prices. Dedicated baseline has the
same total economics with one instance. Reconciliation independently checks order
cumulatives, source/child fills, positions, quote balances and fees. Installed
fixtures plus the accounting/portfolio tests check per-strategy allocations and
aggregate conservation. Every fixture passes replay in a new `python -I` process.

### Observed public boundary

Separate actual public runs used the copied installed consumer, each native
`configs/live` profile, `--live --adverse 0.01`, and `--dedicated` where indicated.
Each capture is bounded to 20 frames or ten seconds and sends public subscriptions
only. All four runs independently reconciled and passed a separate-process replay:

| Retained run under `logs/paper-integration/observed/` | Attributed fills | Quote fee | Net P&L |
| --- | --- | --- | --- |
| `okx-shared-final/` | 2 | 0.01680522 USDT | -0.01682722 USDT |
| `okx-dedicated-final/` | 1 | 0.00840261 USDT | -0.00841361 USDT |
| `bitfinex-shared-final/` | 2 | 0.01 USD | -0.0124035556 USD |
| `bitfinex-dedicated-final/` | 1 | 0.01 USD | -0.010601 USD |

The Bitfinex shared observation partially fills the physical order; its remaining
exposure stays reserved. These short, marked, simulated results are engineering
evidence only. Observed source timestamps, receipt/availability clocks, native raw
bytes, instrument/configuration identities and exact models remain in each run.

### Retention and remaining limits

Local evidence is retained under ignored `logs/paper-integration/`:

- `fixtures-qualified/`: all eight final installed cases, including original copied consumer
  and configuration, journals, raw captures, manifests, delivery logs, independent
  reconciliation, traces, reports and `replay-verification.json`.
- `observed/*-final/`: the four public runs with the same evidence. Each
  `reference-consumer.py` has SHA-256
  `c0dcc9836466e69df352fa14058391328d9ccb6c823cf3335a54b27798b7104f`.
- `artifact/`: the smoke-tested wheel and locked runtime requirements. Wheel
  SHA-256 is `b7d4e369d7da46e15f89a69e7265605b22f3249062e00143520e37661586a8c2`.
  Its Python files and the observed interpreter's installed Python files were
  byte-compared with the final source with no differences.
- `evidence-index.json`: run identities and SHA-256 inventory of retained evidence.
  `make-check.log`, `installed-fixtures-qualified.log`, public/replay logs and
  `final-checks.log` record commands and outcomes. Earlier failed attempts remain
  beside successful reruns; they exposed a fixture source timestamp omission,
  currency-rounding oracle error and sandbox/cache/network setup restrictions.
  Final consumer checks also corrected formatting/helper docstrings and supplied
  the scanner executable on `PATH`. `consumer-equivalence.json` verifies that the
  observed consumer and final consumer have identical Python syntax trees after
  excluding docstrings; retained observed copies remain replayable with their
  original identities. Earlier fixture outputs remain under `fixtures/`.

The committed consumers/tests reproduce numerical acceptance; ignored local logs
are not remotely published evidence. One invocation selects one venue, instrument
and account. Tick/lot values, fees, adverse prices, delay and take fraction remain
authored, uncalibrated assumptions. Displayed-touch matching has no queue position
or market impact and does not infer newly traded liquidity from unchanged size.
Supported behavior is GTC/IOC/post-only spot limits with configured quote fees;
borrow/short/derivative, third-asset fee conversion and applicable gas mechanics
reject or remain outside this path. Native base/quote-fee software evidence from
the prior venue-adapter work remains unchanged.

No authenticated orders, venue fill/latency qualification, continuous operation,
long outage/service recovery, deployed scheduling or capacity observation was
performed. Live trading remains KIV. MR12 receives versioned events/results;
dashboard expansion, MR13 activation, MR14 broader integration and MR15 capacity
remain open. No dependency/governance policy, private credentials or capital were
changed; no merge or push was performed.
