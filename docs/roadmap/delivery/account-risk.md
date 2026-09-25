# MR08 delivery and acceptance

[Roadmap and delivery dependencies](../README.md#delivery-order-and-dependencies).

Status: **partial — local account/risk increment implemented; physical venue
reconciliation remains unqualified**, 2026-09-25. Owner: quant development.
This is the current infrastructure MR08, not a historical research milestone.

Delivered behavior:

- `risk.BudgetPolicy` and `BudgetEngine` enforce instrument authority, exact
  instance/account/firm exposure ceilings, order notional, price deviation and
  quote/account freshness. Complete marked and reserved exposure is required;
  sell commitments do not prematurely offset held inventory.
- `execution.AccountJournal` commits shared-budget admission, candidate
  continuation, tagged child orders, lifecycle events and account postings in
  one SQLite transaction. It accepts the existing target/exposure/order/quote
  intents through the same spot lifecycle owner as the dedicated paper runtime.
  Independent observed quotes cannot be overwritten by candidate requests.
- `accounting.AccountLedger` retains exact multi-instrument and multi-currency
  postings, separate fees/rebates/transfers, stable source identities and
  append-only corrections. Physical and per-instance inventory cannot become
  short; physical cash cannot borrow. Corrections preserve original ownership.
- Complete account reconciliation compares cash, positions, cumulative costs,
  transfers, fill/posting identities and open-order economics. Unknown outcomes,
  stale/regressed state, unmatched facts and underfunded reservations block new
  risk. Cancel acknowledgement alone cannot release exposure. Independent
  operator blocks survive successful reconciliation and restart.
- `alpha-execute account` and its typed application compose these owners from
  configuration and requests in the independent execution distribution.
  Quant development supplies executable shared-budget and accounting consumers.

The [execution guide](../../../src/execution/README.md#shared-account-admission-and-reconciliation),
[accounting guide](../../../src/accounting/README.md), [risk guide](../../../src/risk/README.md)
and [command guide](../../../src/applications/execute/README.md#shared-account-command)
own APIs, commands, units, recovery and limits.

Acceptance evidence is retained under ignored `logs/mr08/`:

| Boundary | Evidence and outcome |
| --- | --- |
| Complete local gate | `make-check.log`: `make check` exited 0; 1,540 tests passed, three performance tests deselected, no skips, real Feast enabled. Strict mypy/stubtest, formatting/lint, ownership/documentation, dependency admission, vulnerability audit, secret scan and isolated wheel smoke all pass. |
| Shared admission and recovery | `tests/unit/execution/test_account_journal.py` in the final gate: seven cases cover concurrent 8,000 + 8,000 / 10,000 admission, restart, unknown/cancel acknowledgement, exact postings/corrections, stale state, independent marks, underfunded pending buys, regressed terminal events and public result codec round-trip. |
| Risk and ledger contracts | `tests/unit/risk/test_budgets.py` and `tests/unit/accounting/test_accounts.py` in the final gate: nested ceilings and complete owner snapshots; exact multi-currency/multi-instrument postings, correction lineage, retry and negative cases. Existing dedicated-paper tests continue to pass with the extracted lifecycle owner. |
| Installed independent execution | `execution/consumer.log`, `execution/consumer/` and `execution/shared_account.py`: outside-checkout `-I` consumer and actual CLI inspect/mutation retry pass. Partial cash is 19,799.80 with two units; after modeled fills, withdrawal, rebate and correction, cash is 11,900.50, holdings 80, fees 1, rebates 1.50 and cumulative transfers 19,900. No submission is attempted. |
| Operating source and closure | `execution/closure.json` and `execution/source-parity.json`: eight admitted wheels, nine dependency edges, clean offline install and 67 packaged source/resource files equal the working tree. This is local installation evidence, not a signed production release. |
| Shared-contract collector compatibility | `collector/`: unchanged accepted collector bytes plus the new contracts wheel admit as 14 wheels/16 edges, with 162 source/resource files matching. Fresh offline installation and CLI succeed; both retained OKX/Bitfinex native-capture replay summaries exactly match the prior accepted outputs. |
| Final research artifact | `final-wheel/` retains the built research wheel, requirements, smoke inputs/results and a 298-file source-parity manifest. `root-account-consumer/` retains the installed full-distribution account consumer from the complete gate. |

`validation-summary.json` records the base commit, uncommitted state, exact
command and exit status. The complete command was:

```sh
UV_PROJECT_ENVIRONMENT=/private/tmp/mr08-gate TMPDIR=/private/tmp \
  ALPHA_FEAST_WORKER_PYTHON=/private/tmp/mr08-feast/bin/python \
  PYTEST_ADDOPTS=--basetemp=/private/tmp/mr08-check \
  make check > logs/mr08/make-check.log 2>&1
```

The independent workload command used the admitted execution installation:

```sh
/private/tmp/mr08-execution/bin/python -I \
  /private/tmp/mr08-consumer/shared_account.py \
  --output /absolute/repository/logs/mr08/execution/consumer
```

Focused development exposed and corrected underfunded-reservation reconciliation,
knowledge-clock regression, request-supplied mark replacement and the public
Boolean result codec. The retained first typing/ownership diagnostics and
collector CLI argument error precede their successful corrections. These are
software tests and fixtures, not measured operating reliability or empirical
strategy results. New capture observations were unnecessary: no feed protocol,
clock or capture behavior changed, and the installed saved-source compatibility
proof renews the affected shared-contract boundary. Final evidence-only prose and
component links were checked separately after the complete source gate.

Scope and dependency ownership remain explicit. Initial qualification is local
cash-funded spot with authored grids, common explicit valuation currency,
quote-currency order fee reserves and normalized paper facts. Other currency
cash postings are supported, but FX aggregation, base-asset fee conversion and
other product mechanics require their declared adapters. The same contracts
permit OKX/Bitfinex instrument identities; neither venue's physical account or
execution behavior is qualified by these fixtures.

MR09 owns the delivered prerequisite slice of tagged instance ownership and
conservative crossing-order rejection. Its [portfolio increment](portfolio-coordination.md#mr09-delivery-and-acceptance)
extends these contracts with allocation, compatible netting, shared costs/residuals
and selective strategy control. MR10
owns the exercised local failure/restart slice; broader operational drills stay
open. MR12 owns future dashboards/alert routing; durable reasons and independent
blocks do not close it. MR11 must supply authenticated order, fill, balance,
fee/rebate and transfer observations, private-stream recovery and authorized
per-venue conformance for both OKX and Bitfinex. No private test credentials or
authorized private-account environment were supplied in this task; no physical
observations are inferred. The precise next external action is to qualify each
MR11 adapter in its separately authorized test environment and feed its normalized
facts into these account contracts. MR08 is not marked complete before that proof.

MR15 capacity, production deployment and MR17/G5 remain open. The complete
research graph retains its existing QuantLib release restriction. Reversal is
review/revert of the uncommitted patch or selection of compatible retained
artifacts with their exact configuration and journal; do not rewrite postings
or erase external effects to force older code to accept state.
