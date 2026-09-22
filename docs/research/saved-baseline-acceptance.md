# Saved-data baseline acceptance

Owner: repository founder. Specification fixed 2026-09-23 before new executions.
Base: current `main`, `bcd68e23bda70ce9c27d09faa2b4b1cf2e424f99`, after PR #77.
Status: **MR8 complete within the explicitly revised simulation scope**, accepted
2026-09-23 Asia/Singapore (executions on 2026-09-22 UTC). P1 remains deferred and
unaccepted; historical causal qualification is not established.

## Scope decision

The founder explicitly authorized replacing MR8's Binance/Tardis acceptance target
with a bounded baseline using preferred freely accessible data. MR8 now accepts
**reproducible offline simulation on real saved data**, under declared assumptions.
It does not accept historical causal data qualification, strategy selection,
profitability, paper operation or live readiness. This decision replaces the MR8
milestone criterion; it does not revise the frozen P1 experiment's own criteria.

[P1](p1-baseline.md), its economic configurations, attempts and results remain
frozen, deferred and unaccepted. Do not obtain further Binance/Tardis records,
purchase services or contact providers for this work. Existing strict admission
checks remain unchanged. Passing the scenario cannot promote its input into a
strict causal dataset or grant deployment/trading authority.

## Fixed replacement specification

Reuse the implemented [MR9A workflow and evidence](l2-book-backtest.md), the saved
OKX ETH-USDT spot archive at
`data/okx/history/f62e64b7-1b40-4869-8b05-2ca911fefcef/`, and the unchanged
[versioned configuration](../../configs/backtests/okx-eth-usdt-book-v1.json).
The saved archive was obtained through OKX's public unauthenticated endpoint;
this acceptance reads retained bytes only and makes no new source-access or
redistribution-entitlement claim. Preserve the archive and its request/index/manifest
locally; neither hashes nor a current download are a replacement for those bytes.

The raw SHA-256 is
`d5d530e6ce635d0e92ba4cd6d280b0aa2f64e918f09e2822018ed061846e1ea3`.
Replay exactly the first 10,000 messages on 2026-09-20: source timestamps
00:00:00.001–00:06:00.252 UTC, with terminal valuation at 00:06:00.500 UTC.
Complete compressed/archive integrity is checked; semantic reconstruction covers
only this prefix. No full-day completeness claim follows.

The fixed top-five imbalance rule targets 0.01 ETH when imbalance exceeds 0.2,
otherwise zero; the separate control never trades. Each account starts with
1,000 USDT. Decisions occur once per second. Keep the declared 0.01 ETH maximum,
0.0001 ETH lot, 0.01 USDT price tick and 1% displayed per-level participation cap.
No fitting, tuning, split, holdout or profitability threshold is introduced. The
already observed negative result is known before this scope revision; this is
engineering acceptance, not an out-of-sample strategy test.

Fees are assumed 10 bps taker per price-level fill, rounded half-even to
0.00000001 USDT. Feed/processing/entry/response delays are assumed
100/10/20/100 ms, with two-second stale-book refusal. They are not historical
measurements or an account-specific venue fee schedule. IOC orders walk the
arrival book with persistent consumed size; unfilled quantity is canceled.
Terminal inventory is marked at fresh exchange best bid without liquidation.
The [owning timing/fill contract](l2-book-backtest.md#financial-and-timing-assumptions)
defines tie ordering, reservations, depletion and unsupported mechanics.

Original receipt times and source sequences remain `None`. Sequence continuity,
positive interval coverage, historical eligibility/reference availability and
exhaustive original/correction history remain unknown or unproven. Download
timestamps are provenance only. Model-delivery clocks are separate scenario
clocks and cannot supply missing historical facts. Preserve source failures and
strict refusal behavior; never fill a gap with assumed evidence.

## Criteria and sufficient evidence

All rows are required for the revised MR8; historical qualification is explicitly
outside its acceptance, not a criterion recorded as passed.

| ID | Observable criterion | Evidence plan and reuse boundary |
| --- | --- | --- |
| S1 | Fixed real saved input, source/config/code/environment identities and explicit quality limits | Reuse retained acquisition; verify exact archive through the installed reader, 10,000 EDA rows and preserved unknown clocks/sequences. |
| S2 | EDA → simple strategy and isolated no-trade control → orders/fills → cash/positions/P&L through shared owners | Reuse `run_books`, CLI, configuration, replay, risk, ledger and reports; inspect current code before adding any missing implementation. |
| S3 | Exact financial agreement without tolerance | Independently sum saved signed fills, effective notionals, per-fill rounded fees and positions; reconcile every recorded valuation and both P&L attributions; control has zero orders/fills/costs and unchanged capital. |
| S4 | Fresh-process repeat and interrupted/resumed equivalence across complete outputs | Current installed package: uninterrupted notebook, independent CLI repeat, CLI checkpoint with a pending order, then fresh CLI resume. Compare configuration, EDA, both full checkpoints, JSON and HTML reports byte for byte. Attempt IDs/clocks legitimately differ. |
| S5 | Supported mechanics, causal scenario ordering, failures, units and isolation | Reuse MR9A hand/causal/stale/invalid/partial-fill/recovery/second-spot fixtures where owning runtime bytes are unchanged; rerun relevant configured tests only when impact requires it. Retain failures and do not weaken admission. |
| S6 | Runnable maintained command and notebook calling installed shared code | Execute all cells of `examples/orderbook-research.ipynb`; expose exact accounting and limitations, retain executed copy separately, clear maintained outputs. |
| S7 | Criterion-by-criterion result, reproducible retained artifacts and scope-correct roadmap/usage | Record actual results and hashes here, link from current usage and roadmap, preserve original MR9A and P1 evidence identities. |

No new simulation abstraction, source adapter, configuration format or alternative
runner is planned: each necessary consumer already exists. Notebook presentation
may expose more existing ledger fields; domain calculations remain in shared
owners. Renew actual-source process evidence because PR #77 changed installed
identity since MR9A. Earlier runtime mechanics evidence remains attributable to its
tested bytes; it is not silently relabeled as a new run.

Reversal: restore the previous MR8 milestone wording and remove the replacement
acceptance links/presentation changes together. Preserve frozen P1, saved archives,
all old and new attempts and tested packages. No checkpoint schema, runtime API,
strict admission policy or economic parameter changes are required.

## Acceptance record

The specification was retained before new execution as
`logs/saved-baseline/2026-09-23/specification-before-execution.md`, SHA-256
`c73033044a03a086145d399a29284069214280001e0a7e4861f2378bb794f8f6`.
The fixed economic configuration was not changed. Its authored-file SHA-256 is
`9a710c74812117f0ce66ad3d7916a96283774ab723647e47e5237c8dc8560658`;
resolved configuration identity is
`3fdf83b4d7aa9b107ac6503cbd335d7b51ef017e04b0576b43886b3e98c531a0`.

| Criterion | Result | Actual evidence and limits |
| --- | --- | --- |
| S1 — saved source and EDA | **Pass** | Installed archive verification and 10,000 EDA rows; all labeled `visible_depth_only`, spread 0.01–0.41 USDT/ETH. Zero known original receipt times or source sequence IDs. This quality label means visible depth is inspectable, not complete historical data. |
| S2 — shared complete economic path | **Pass** | Both accounts ran through the existing installed `run_books` and `alpha-backtest books`; each retained 360 decisions and 361 valuations. No missing shared implementation was found; runtime, configs and dependencies are unchanged. |
| S3 — exact accounting | **Pass** | Independent signed-fill sums checked cash, holdings, fees, turnover and depth slippage at every one of 722 valuations; best-bid NAV, effective-price attribution and reference gross-to-net identities all matched exactly. All 78 rounded fees matched independently; the control had no orders/fills/costs. |
| S4 — fresh-process repeat/restart | **Pass** | Notebook, independent CLI repeat and fresh CLI resume have identical configuration, EDA, both entire checkpoint files, JSON report and HTML report. Checkpoints cover all decisions/orders/fills/valuations, both book information sets, pending state and consumed size. Interruption at 00:00:08.010 UTC retained pending order `imbalance:0`, ten feed deliveries and zero fills. Attempt IDs/clocks differ as intended. |
| S5 — mechanics, ordering and refusal | **Pass** | Existing current installed tests: **19 passed, zero skips/deselections**. They cover hand-calculated partial fills/fees, affordability/depletion, future perturbation, delayed information, stale/invalid inputs, seven restart boundaries, unsupported mechanics, second spot configuration, three isolated accounts and retained corrupt-source failure. MR9A's unchanged owning mechanics evidence is reused. |
| S6 — maintained notebook/command | **Pass** | All **12 cells, six code cells** executed in a fresh installed-package kernel. The notebook calls shared `run_books` and reconstructs terminal balances with `Ledger`; exact attribution is displayed without converting money to floats. Chart inspected; executed copy retained and maintained outputs cleared. |
| S7 — record, usage and roadmap | **Pass** | This report owns the replacement specification, identities, actual results and boundaries; roadmap and usage link here. P1 and MR9A history retain their original evidence and scope. |

| Instance | Decisions | Orders | Level fills | Terminal cash/NAV (USDT) | ETH position | Fees (USDT) | Net P&L (USDT) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Imbalance | 360 | 62 | 78 | 998.35849845 | 0 | 1.62998455 | -1.64150155 |
| No-trade | 360 | 0 | 0 | 1000 | 0 | 0 | 0 |

For the imbalance account, effective-price realized P&L before fees is
**-0.011517 USDT** and unrealized P&L is zero. Reference-price gross P&L is
**-0.0021 USDT**, depth slippage is **0.009417 USDT**, and turnover is
**1629.984541 USDT**. Exact reconciliations are:

```text
-0.011517 + 0 - 1.62998455 = -1.64150155 USDT
-0.0021 - 0.009417 - 1.62998455 = -1.64150155 USDT
1000 - 1.64150155 = 998.35849845 USDT
```

The negative result reproduces MR9A without tuning. No real-window order needed
partial cancellation; fixtures, not this window, establish partial-fill behavior.

## Run and reproduce

From the repository root with the retained archive present:

```sh
uv run --frozen --no-editable alpha-backtest books \
  --config configs/backtests/okx-eth-usdt-book-v1.json \
  --archive data/okx/history/f62e64b7-1b40-4869-8b05-2ca911fefcef \
  --output logs/book-backtest/runs
```

Open `report.html` in the printed result directory. The command creates a fresh
attempt and reads saved data only. For the maintained notebook:

```sh
uv run --frozen --no-editable python -c 'from applications.backtest import run_books'
uv run --frozen --no-sync --with 'nbclient==0.10.4' --with 'nbformat==5.10.4' \
  python examples/run_notebook.py examples/orderbook-research.ipynb --kernel-python .venv/bin/python
```

Use the [notebook environment instructions](../../examples/notebook-operations.md#historical-order-book-study)
for the existing kernel dependencies. Do not synchronize/install into that kernel
while it is running. The notebook and command share the same configuration and
runtime. The [recovery instructions](l2-book-backtest.md#interrupt-and-resume)
explain `--stop-at '2026-09-20T00:00:08.010000+00:00'` and then
`--resume /absolute/path/to/the/printed/checkpoint-directory` on a fresh invocation
without `--stop-at`. Complete runs compare the six files listed in S4, not just
summary metrics. Do not compare attempt IDs or wall-clock execution timestamps.

## Retained current evidence

Local ignored record root: `logs/saved-baseline/2026-09-23/`. The matching wheel
is retained in `package/alpha_research_lab-0.1.0-py3-none-any.whl`. On CPython
3.14.7 / macOS arm64, **all 205 owned runtime files** match checkout, installed
package and retained wheel exactly. `identity.json` records:

- Wheel SHA-256: `7bf7dc562696a33d0576554721238945240e905ac2352f4e5bed8aa2ed29cfbd`.
- Installed implementation: `5f65a1e886f18107957d1fe586c9725bd7fc59abacc38e8aa762d52defafec40`.
- Environment: `98584a361d334c54fa9e0e83370a061dfe2d397da76d39ab1cbec368fd59b1e8`.
- Run identity: `e9ae810554539127c113382eb77716eca6c82e1dae8fc9244b055c105def3255`.
- JSON report: `b115d43333ee38bafd56d463139d4489e50ce0e72166e06c69fd2661b2a04a54`.
- HTML report: `9d3642bcc8b11ad836302f501be6351cb9b0b228a3d49f871685ce2521890f8e`.

| Artifact | Retained location relative to repository root |
| --- | --- |
| Executed notebook | `examples/runs/orderbook-research/b2bd0144-d777-495b-8e42-e7a2e235d2e5.ipynb` |
| Uninterrupted result and chart | `logs/book-backtest/notebook/60e467aac74a4d618920a0ca3b9d1879/` |
| Independent CLI repeat | `logs/saved-baseline/2026-09-23/repeat/3edb1e0c2d464dc2967b173ca18d8500/` |
| Pending-order checkpoint | `logs/saved-baseline/2026-09-23/interrupted/b323bef28d374da08a2e5527047faba7/` |
| Fresh-process resume | `logs/saved-baseline/2026-09-23/resumed/0af8c864b6e342d69c5e424506bea7dc/` |

Each invocation retains its own attempt history. CLI executions used the installed
`.venv/bin/alpha-backtest` from `/private/tmp` with absolute paths. The small retained
`verify_saved_results.py` checks these saved outputs independently, without rerunning
the simulation or changing runtime; `verification.json` records its exact financial
checks, full-output hashes, original unknowns, EDA counts and explicit paths. To
recheck the retained evidence:

```sh
baseline_record="$PWD/logs/saved-baseline/2026-09-23"
.venv/bin/python -I "$baseline_record/verify_saved_results.py" \
  "$PWD/logs/book-backtest/notebook/60e467aac74a4d618920a0ca3b9d1879" \
  "$baseline_record/repeat/3edb1e0c2d464dc2967b173ca18d8500" \
  "$baseline_record/interrupted/b323bef28d374da08a2e5527047faba7" \
  "$baseline_record/resumed/0af8c864b6e342d69c5e424506bea7dc" \
  "$baseline_record/verification-recheck.json"
```

Verification also passed native notebook Ruff lint, formatting of changed code
cells, the complete engineering-rule checker and local-link checking of **39
documents plus all notebook Markdown cells**. Maintained notebook SHA-256 is
`e7761d5ecd7fe2f97b02986de0f431572640c407be2310073927bf7b027afc4e`;
every cell's source/type matches the retained execution. The configured
19-test invocation is:

```sh
uv run --frozen --no-editable pytest -q -m 'not performance' \
  tests/unit/simulation/test_book_economics.py tests/integration/test_book_backtest.py
```

The final secret scan passed for **480 tracked paths plus the new acceptance
document**; diff whitespace checks passed. Runtime, all economic configurations,
test implementations and dependency inputs are byte-unchanged from the main base.

The execution used the already installed interpreter (`.venv/bin/python -I -m
pytest`) to avoid environment mutation during notebook execution. Initial sandbox
access refusals, the incorrect nonexistent test-path selection and an inappropriate
per-cell lint invocation are recorded in `validation-notes.md`; corrected checks
passed. No economic attempt failed or was discarded; the deliberate checkpoint is
retained as abandoned and its resume as a new completed attempt.

No new tests or shared implementation were needed. The unchanged full source
lane from [PR #77's evidence](source-qualification.md#verification-and-results)
and original MR9A mechanics evidence are reused only for their tested scope.
Current wheel/API/real-data/recovery proof was renewed above because the installed
identity differs from MR9A. The subsequent pre-merge check below renews the full
local lane; no artifact release or activation is claimed.

## Pre-merge verification

On the founder's request to merge, commit `57497623459cfdda55e4acaa7529c336e55cb74c`
passed the complete local lane on 2026-09-23:

```sh
TMPDIR=/private/tmp MPLCONFIGDIR=/private/tmp/alpha-saved-baseline-merge-fonts make check
```

The command exited **0**. Source tests passed **1,244 cases**, with **three
performance cases deselected and zero skips**; strict mypy checked 353 files and
native stubtest checked 1,562 modules. All configured formatting, lint, engineering,
dependency admission/audit, links, Bandit and secret checks passed. The isolated
installed-wheel API, command, recovery and historical-snapshot consumers passed.
The rebuilt wheel is byte-identical to the accepted wheel above. The complete log
is retained in `logs/saved-baseline/2026-09-23/make-check.log`; isolated smoke inputs,
environment and outputs remain in `/private/tmp/alpha-research-wheel-smoke-bjw1mzso/`.
Final changes after this check update this evidence text and the roadmap only.

[PR #78](https://github.com/lixuanguang/alpha-research-lab-private/pull/78) owns the
final merge status. Its initial
[hosted run](https://github.com/lixuanguang/alpha-research-lab-private/actions/runs/35761908542)
could not start source validation because GitHub reported failed account payments
or an insufficient spending limit. The authoritative job failed and macOS was
skipped; these are not passing hosted checks. GitHub showed the normal merge action
available with no conflicts. No check, branch protection, billing or security
configuration was changed. The observed failure is retained separately in
`logs/saved-baseline/2026-09-23/hosted-premerge.json`.

## Remaining boundaries

**No remaining gap in the revised S1–S7 simulation acceptance.** Historical data
qualification remains unestablished: original receipt/availability, source sequence
continuity, positive coverage, historical eligibility and complete correction history.
The raw archive and local artifacts must remain available to reproduce this result;
they are ignored, not distributed or backed up by Git. Portability to a different
environment requires renewed identity/equivalence evidence.

P1's original acceptance remains deferred and unaccepted. Neither the negative
strategy result nor perfect reconciliation supports profitability, historical causal
qualification, executable liquidity/capacity, candidate promotion or live readiness.
The baseline supports only the declared long-only, cash-funded spot IOC scenario;
no broker, paper-runtime or live-recovery claim is made.
