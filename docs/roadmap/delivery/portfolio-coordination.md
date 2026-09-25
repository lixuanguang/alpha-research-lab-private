# MR09 delivery and acceptance

[Roadmap and delivery dependencies](../README.md#delivery-order-and-dependencies).

Status: **complete for local shared-account portfolio infrastructure**, 2026-09-25.
Owner: quant development. This is the current infrastructure MR09, not the
historical MR09A saved-book research baseline.

The bounded delivery extends the existing `AccountJournal`, independent
instance/account/firm risk and exact account postings with compatible shared
spot coordination. `portfolio` owns scope metadata and the deterministic
reference allocation policy. The installed `alpha-execute account` application
exposes coordination, physical order events and strategy stop/restart; the
research-side `run_shared_paper` application composes existing decision policies
with the same journal. Two distinct executable target and order-intent reference
policies share an instrument/account, retain their own state and reconcile
independently and in aggregate. No empirical profitability requirement is used
to establish this infrastructure outcome.

Every batch retains original strategy/model/configuration/time/account/portfolio/
instrument/horizon/reason lineage. Gross instance/account/firm budgets and funding
are enforced before compatible netting or an explicitly selected internal cross.
Compatibility includes account, currency, venue, instrument, settlement, risk
bucket and authority; a different label cannot grant account or instrument access.
Physical parents and tagged children remain separate. Exact fill/fee allocation,
append-only fee revisions, residual ownership and policy continuation survive
retry/restart in the existing SQLite account transaction. Selective stop fences
one strategy; shared cancellation retains the other strategy's reservation until
terminal confirmation, reconciliation and fresh risk checks permit reissue.

The [execution guide](../../../src/execution/README.md#portfolio-coordination-and-recovery),
[allocation guide](../../../src/portfolio/README.md),
[command guide](../../../src/applications/execute/README.md#shared-account-command)
and [runtime guide](../../../src/runtime/README.md) own the interfaces and recovery
procedure. Acceptance evidence is retained under ignored `logs/mr09/`:

| Boundary | Evidence and outcome |
| --- | --- |
| Complete local gate | `make-check.log`: `make check` exited 0; 1,565 tests passed, three performance tests deselected, no skips, real Feast worker enabled. Formatting/lint, strict mypy/stubtest, engineering/architecture/dependency checks, security/vulnerability/secret checks and isolated wheel smoke pass. |
| Executable strategy consumers | `tests/unit/runtime/test_shared_decisions.py` runs through the installed full distribution in the final gate. A target policy and a stateful order policy share the paper application, restore independently, retain business-rejected continuation and retry an older batch without rewinding newer state. Generated journals are retained in `root-shared-runtime/`. |
| Exact allocation and safety | Thirteen allocator and eight account coordination cases pass. Independent quantities/cash, uneven fills, changing price quanta, low Decimal precision, price improvement, fee correction/void/restore, retained fee capacity, stale marks, checkpoint races and child-event bypass rejection are covered. `residual-probe.log` additionally proves an installed application exposes an unroutable 0.5-unit beta residual after cancellation/reconciliation and restart. |
| Independent execution consumers | `execution/consumer-okx-final/`, `execution/consumer-bitfinex-final/` and their final logs retain outside-checkout `-I` consumers and actual CLI requests/results. Authored OKX/USDT and Bitfinex/USD workloads both reject gross 8,000 + 8,000 under 10,000, net 2 + 2 into a physical order of 4, allocate a partial fill of 2 as 1 + 1, and preserve beta's remaining order when alpha stops. |
| Independent account goldens | Each fixture begins with 50,000 cash. After partial fill, cash is 49,799.98. After selective recovery, holdings are 3, fees 0.03 and cash 49,699.97. Internal crossing leaves physical totals unchanged. A physical fee revision gives aggregate fees 0.05 and cash 49,699.95, with alpha/beta fees 0.02/0.03. Incompatible crossing, changed retry bytes and malformed commands fail. |
| Operating artifact boundary | `execution/closure.json` and `source-parity.json` retain an admitted eight-wheel closure with nine edges and 72 packaged source/resource files equal to the final tree. Fresh offline installation, dependency compatibility and absence of unrelated research/simulation dependencies pass. No submission is attempted. |
| Collector compatibility | `collector/` retains the rebuilt collector and contracts, admitted 14-wheel/16-edge closure, 162-file source parity, clean offline installation and runtime identity/import checks. Replaying the retained native OKX and Bitfinex captures produces summaries identical to MR08. This renews compatibility, not live-source or private-account qualification. |
| Final research artifact | `final-wheel/` retains the full research wheel, smoke requirements/inputs/results and a 305-file exact source-parity manifest. The existing development-only QuantLib release restriction remains in force. |

`validation-summary.json` binds commands and results to the base commit and
uncommitted file identities. The complete local command was:

```sh
UV_PROJECT_ENVIRONMENT=/private/tmp/mr09-gate TMPDIR=/private/tmp \
  ALPHA_FEAST_WORKER_PYTHON=/private/tmp/mr09-feast/bin/python \
  PYTEST_ADDOPTS=--basetemp=/private/tmp/mr09-check \
  make check > logs/mr09/make-check.log 2>&1
```

The maintained `tests/integration/consumers/runtime/portfolio_account.py` accepts
`--output /absolute/output --venue okx` or `--venue bitfinex`; copy it and its sibling
`portfolio_account_facts.py` outside the checkout and invoke it with the admitted
execution installation's `python -I`.
The full gate also discovers `tests/integration/test_portfolio_workflow.py`.
Retained application typing/development diagnostics precede the successful
installed results. Some early core failure traces were not retained;
`development-diagnostics.json` records that gap and the later fee-tail fixture
precision correction. These runs establish correctness, not measured operating
reliability or empirical strategy evidence.
Final evidence prose and component links were checked after the complete gate.

Initial qualification is cash-funded spot with explicit lot/tick grids, common
account valuation currency and quote-currency fee reserves. Quantity residuals
that cannot form a physical lot remain visible and reserved, and completed
children retain fee capacity while their physical parent remains unresolved.
Other product economics, FX aggregation and base-asset fee conversion still
require their owning adapters. The generalized identities and scope checks are
retained; fixture venue labels do not establish venue rules or observed liquidity.

Dependency ownership remains bounded. MR08 supplies the local gross-budget and
normalized account boundary; its authenticated physical reconciliation remains
MR11 work. MR10 owns the exercised shared failure/recovery slice, with broader
operational drills still open. MR14 owns broader multi-instance deployments;
the required two-strategy shared-account workload belongs to MR09. MR12
dashboards/alert routing, MR13 activation, MR15 capacity and MR17/G5 remain open.
No private venue environment, production deployment, live orders or capital
activation is claimed by authored local spot facts.
The next external qualification is MR11: implement and exercise each authenticated
OKX/Bitfinex spot adapter in its separately authorized test environment, feeding
real normalized observations into the same contracts. MR08 physical acceptance
and G4 remain open until that proof and their other binding outcomes exist.
Formal QR work remains gated on the complete infrastructure and MR17/G5.
Review or revert the uncommitted patch for reversal; retain exact configuration,
journal and compatible artifact together instead of editing accounting history
to force compatibility with an older artifact.
