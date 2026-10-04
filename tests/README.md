# Tests and retained inputs

The [engineering guide](../docs/coding_standards/README.md#stable-names-and-test-support-layout)
owns naming and source requirements; the [development workflow](../docs/governance/workflow.md)
owns validation and merge requirements. Keep tests organized by behavior rather
than by the MR that originally demonstrated it.

## Layout and execution

| Location | Responsibility |
| --- | --- |
| `unit/` | Domain/component regressions, including integration-marked cases beside their owner |
| `engineering/` | Packaging, dependencies, source standards and governance |
| `unit/extensions/` | Maintained research extensions under `extensions/`, through their registered providers |
| `golden/`, `fixtures/` | Independent expected values and static input bytes; no executable Python |
| `support/subprocesses/` | Acquisition fakes and deliberate process-death/publication interruptions |
| `integration/test_*.py` | Discovered workflow tests |
| `integration/consumers/` | Standalone installed workflows still used by tests, notebooks or explicit service checks |

```sh
# Correctness tests, including integration; excludes performance cases.
make test

# Installed workflow regressions and component integration cases.
make integration-test

# One affected workflow during development.
uv run --frozen --no-editable pytest -q -m integration tests/integration/test_book_backtest.py

# Clean artifact installation and a bounded OKX CLI round trip.
make wheel-smoke
```

Plain pytest excludes `integration` and `performance` through its marker filter.
A script under `consumers/` is not discovered automatically. `make check` runs
source validation, including domain regressions, followed by wheel smoke. Hosted
source, macOS and merged-result gates remain unchanged. On macOS use
`TMPDIR=/private/tmp` to keep Unix-domain socket paths within OS limits.

## Installed boundaries and domain regressions

Consumers run as copied scripts with `python -I`, copied inputs and a working
directory outside the checkout. A consumer copied with sibling support modules
runs with `python -E -s` instead: the environment and user site are still ignored,
and Python puts the copied directory first on the path. Consumers must not import
repository test helpers or mutate `sys.path`. Deliberate `os._exit` support programs run only in
children. Real orchestration belongs to `src/applications/`.

| Maintained caller | Behavior retained |
| --- | --- |
| [Ingestion/feature tests](integration/test_ingestion_workflow.py) | Acquisition resume, publication, EDA, installed feature/label reproduction and model recovery |
| [Economic tests](integration/test_economic_workflow.py) | Exact trade-price economics, vectorbt/comparison reports, feature parity, publication failure and fresh-process resume |
| [Book tests](integration/test_book_backtest.py) | Saved OKX L2 CLI, independent accounts, second spot configuration, checkpoint restart and corrupt-source refusal |
| [Capture recovery tests](unit/data/live/test_recovery.py) | Pending snapshots, duplicates, stale responses, recovery and installed replay CLI/API equality |
| Component tests under `unit/data/` | Installed book, health and parity consumers alongside their domain regressions |
| [Public data tests](unit/data/test_public_data.py) | Both public source parsers, pending-response recovery, four scopes, PIT venue rules, source integrity and configuration-only onboarding |
| [Decision workflow](integration/test_decision_workflow.py) | Fresh feature/label/estimator/quote implementations, retained fit bytes and fresh-process restart through installed public APIs |
| [Public data consumer](integration/consumers/datasets/public_data.py) | Installed CLI publication/discovery/read, named public-trade/book/reference assembly and replay continuation; accepts completed actual captures |
| [Trusted installation consumer](integration/consumers/deployment/trusted_installation.py) | Real signed execution releases, isolated package inventory, signed configuration changes, production-request refusal and rollback with current mutable state |
| [Bounded runtime capacity](integration/consumers/runtime/capacity_trial.py) | Fresh signed four-owner fixture/recovery runs, sampled healthy intervals, native/economic parity and loaded faults; [read observers](integration/consumers/runtime/capacity_reads.py) retain every paced request and [results](integration/consumers/runtime/capacity_results.py) require complete steady latency cohorts and successful per-reader schedules. Acceptance and remaining gates live in the [runtime profile](../docs/roadmap/runtime-capacity.md). |

Wheel smoke installs the hash-locked runtime without governance, checks every
shipped API/resource and installed identity, and runs the existing book consumer
with `--smoke`. This mode verifies one small synthetic OKX archive through the installed CLI and exact account report. The
default book-consumer mode retains the complete recovery/failure scenario.
Wheel smoke does not repeat all domain workflows or contact services.

The smoke prints and retains its temporary wheel/environment directory. Keep
needed evidence before explicitly cleaning it up. Do not synchronize or reinstall
an environment while tests, notebooks or workers use it. Existing
Binance/Tardis-shaped synthetic fixtures remain regression tests; new
data-dependent work follows the [OKX/Bitfinex policy](../docs/roadmap/README.md#current-platform).

The trusted installation consumer requires two independently verified releases,
an out-of-band trust policy, an absent target, and authored admission requests.
Copy it outside the checkout and run with the installed governance interpreter:

```sh
python -I -B /absolute/trusted_installation.py \
  --policy /protected/target-policy.json \
  --initial /absolute/registry/INITIAL_SHA256 \
  --upgrade /absolute/registry/UPGRADE_SHA256 \
  --target /absolute/new-operating-target \
  --request /absolute/shadow-request.json \
  --upgrade-request /absolute/shadow-upgrade-request.json \
  --output /absolute/trusted-installation.json
```

Both releases must accept the base request with submission suppressed. Only the
upgrade accepts the second request; initial installation and rollback must reject
it. The consumer verifies the exact installed distribution graph and absence of
research, notebook, training and reporting modules. The
[installation runbook](../docs/governance/operations.md#trusted-local-installation)
owns release preparation and trust provisioning. Signature, dependency and
failure-transition regressions are ordinary engineering tests; this explicit
consumer additionally crosses the real builder/signature/offline-install boundary.

The old standalone row/occurrence, revision, quality, identity, publication,
eligibility, query and EDA acceptance demos have been retired. Their maintained
regressions are in `unit/data/`, `unit/pipelines/` and the ingestion workflow.
Snapshot and command process-death tests remain. The as-of and replay consumers
remain because the maintained notebooks execute them.
The standalone engineering-sample demonstration is also retired; qualification,
engineering scope, cost reconciliation and no-trade controls belong to their
data, experiment and simulation regressions.

## Explicit service and saved-source checks

The [authored capacity consumer](integration/consumers/research/capacity_workload.py)
measures multi-day feature grids, concurrent local study workers, exact costed
trials and backup/restore through a real isolated Feast worker. The
[native archive capacity consumer](integration/consumers/research/archive_capacity.py)
measures bounded original-book publication and independent reopening, preserving
unknown historical availability. Both are explicit installed diagnostics, not
discovered tests or representative launch acceptance. Their commands, pinned
inputs, measured limits and remaining gaps live in the
[capacity record](../docs/roadmap/research-capacity.md).

The installed feature consumer exercises the copied feature/label boundary and
fresh-process model recovery with an unavailable publication transport. Factor,
model-lifecycle and window-diagnostic assertions run as discovered domain tests
under `unit/research`; it still writes the frozen factor/window configuration
handoffs used by the manual comparison notebook. The output stores can be passed
to the single [ClearML verifier](integration/consumers/research/clearml_publication.py)
for actual publication, fresh-process receipt recovery and remote byte checks.
The verifier reads `ALPHA_CLEARML_LOCAL_ENV`; ordinary domain
runs make no server claim. The [ClearML runbook](../configs/development/clearml/README.md)
owns its invocation; no ordinary test starts Docker or an agent.

The [pipeline consumer](integration/consumers/backtest/pipeline_workflow.py)
requires an explicitly running local agent and matching installed wheel. The
[versioned-storage consumer](integration/consumers/datasets/versioned_storage.py)
requires the selected local lakeFS service. These remain manual service checks.

The [offline feature consumer](integration/consumers/research/offline_features.py)
uses the [separately locked Feast worker](../configs/development/research-worker/README.md).
After running `feature_study.py`, copy it outside the checkout and invoke:

```sh
/absolute/core/bin/python -I /absolute/consumers/offline_features.py \
  /absolute/feature-study-output /absolute/fresh-feast-output \
  --worker-python /absolute/checkout/configs/development/research-worker/.venv/bin/python
```

It checks real SDK retrieval, pinned registry/source bytes, delayed corrections,
missing entities and TTL expiry. ClearML publication uses the separate verifier.
It does not implicitly install Feast in the core CI environment.

The [saved-source consumer](integration/consumers/backtest/source_acceptance.py)
and [capture recovery probe](integration/consumers/capture/recovery_probe.py) need
explicit retained external inputs. Their source identity, clocks and quality must
satisfy the [market-data contracts](../src/market_data/README.md). They do not
implicitly download provider data.

The [Coinbase bridge conformance consumer](integration/consumers/capture/coinbase_bridge_conformance.py)
reads retained Coinbase `level3` capture journals given with `--capture` or found
under `--search` roots. For each REST snapshot it reports bridged updates whose
source `time` precedes the snapshot's, the adapter's refusal if any, and whether
sequence-only bridging would accept. Without a Coinbase capture it reports that no
pair is available, which is expected while Coinbase collection is deferred. The [notebook guide](../examples/notebook-operations.md)
owns execution of the research worksheets.

The [decision source consumer](integration/consumers/research/decision_sources.py)
reuses retained MR01 publications and originals without downloads. Copy it outside
the checkout and run with the installed interpreter:

```sh
python -I /absolute/decision_sources.py \
  --selection /absolute/data/selection.json \
  --snapshots /absolute/data/snapshots --raw /absolute/data/raw \
  --output /absolute/fresh-decision-source-output
```

It selects an observed book cutoff per instrument, carries public-trade size,
reference minimum quantity and visible book imbalance into generic features and
rule decisions, and retains the actual source/config/result identities in the
existing attempt store. It requires retained eligible book states for both supplied
venue listings. It establishes source reopening and decision composition, not
simulated fills, execution qualification or empirical research acceptance.

## Feature serving and scheduled workspace acceptance

The [feature workspace consumer](integration/consumers/research/feature_workspace.py)
requires the independently locked real Feast worker. Copy it outside the checkout
and select the worker's virtual-environment executable without resolving its
symlink to the base interpreter:

```sh
/absolute/core/bin/python -I /absolute/feature_workspace.py \
  /absolute/fresh-feature-workspace --worker-python /absolute/feast-venv/bin/python
```

It uses authored multi-entity inputs, exact incremental features, the real Feast
online store and the intent-only application consumer. It checks restart, retries,
PIT corrections, expiry/service-loss pauses, rollback and restored serving bytes.
The regular feature-store and runtime tests require no service. The explicit
Feast integration case is selected separately by the worker guide; the ordinary
full gate reports its skip when no worker is selected.

The existing [versioned-storage consumer](integration/consumers/datasets/versioned_storage.py)
accepts `FEATURE_WORKSPACE OUTPUT feature-workspace` to publish those retained
`raw`, `snapshots` and `features` bytes to the selected local lakeFS service.
`FEATURE_WORKSPACE OUTPUT feature-reopen` reopens the saved commit without another
publication, including after a service-volume restore. Use absolute
`ALPHA_LAKEFS_CREDENTIALS` and `ALPHA_CLEARML_LOCAL_ENV` paths because recovery
checks deliberately change working directories. The study consumer now also
checks scheduled jobs and workspace restore; its existing ClearML verifier
checks the selected deferred attempts against the actual local service.

## Registry and consolidated quote acceptance

`unit/data/test_book_registry.py` checks exact ties, independent listings on the
same venue, future and historical cutoffs, stale/delayed inputs, nanosecond source
clocks, controls, gaps, recovery, reference/unit mismatches and explicit coverage.
It uses synthetic comparable markets and real native decoder fixtures.

Copy the [registry consumer](integration/consumers/capture/book_registry.py) outside
the checkout and run it with a freshly installed research wheel:

```sh
/absolute/core/bin/python -I /absolute/copied/book_registry.py \
  /absolute/fresh-registry-output /absolute/retained-okx-capture \
  /absolute/retained-bitfinex-capture
```

The consumer reconstructs separate native books, compares every boundary with the
original decoder/projection, checks old cutoffs after later input and verifies a
fresh rebuild. It retains selected/eligible coverage and original source identities.
The native journals supply receipt only; the saved query workload explicitly uses
`receipt-clock-as-availability`. Original delivery is unknown in this workload.
USD/USDT recordings remain separate. Authored comparable quotes demonstrate tied
BBO and a paper fill at the selected venue even when another venue has a better
ask. Paper restart cannot duplicate those modeled effects. This explicit retained
source check is not a network dependency of the normal unit suite.

## Paper and live-input acceptance

The common book boundary is covered by `unit/data/test_book_quotes.py` and the
native venue tests: independent full aggregation checks exact incremental L3
levels, BBO sides, source/receipt/availability clocks, invalidation and recovery.
The existing installed `capture/parity_consumer.py` additionally checks every
native record in supplied completed recordings through `BookProjection.quote`
and preserves the original final book/trace identities. Its published prefix
continues to exercise chronological queries and fresh-process cursor recovery.
Run it against explicit retained OKX/Bitfinex capture directories:

```sh
python -I /absolute/copied/parity_consumer.py /absolute/fresh-replay-output \
  /absolute/okx-capture /absolute/bitfinex-capture
```

The paper consumer below exercises the same shared BBO through actual post-durable
delivery and saved envelope replay. Native protocol fixtures and modeled fills
remain separate from source qualification and private execution evidence. Private
venue qualification is KIV outside the bounded paper-acceptance gate; the
[reconsideration record](../docs/roadmap/README.md#live-trading-kiv-and-reconsideration)
owns that boundary.

`tests/unit/execution/` exercises the portable OMS and finite-liquidity matcher:
atomic quote admission, exact cash/inventory/fee reservations, fencing, restart,
duplicate events, uncertain outcomes, partial fills, cancellation acknowledgments,
confirmed replacement and contradictory terminal facts. Runtime tests add
checkpointed lifecycle callbacks, hard blocks, causal order/account callbacks,
stale-data pauses and unchanged intents across paper and shadow modes.

The installed [candidate consumer](integration/consumers/research/candidate_workflow.py)
now runs completed rule-order and learned-target candidates through
`applications.paper.run_paper`. It checks independently expected fills, fees and
cash, shadow suppression and restart. Its `feast` mode also runs the actual
isolated online store through the paper OMS, including service-loss and version-change
pauses. Select it with:

```sh
ALPHA_FEAST_WORKER_PYTHON=/absolute/pinned-feast-worker/bin/python \
  uv run --frozen --no-editable pytest -q -m integration \
  --basetemp=/private/tmp/mr07-candidates \
  tests/integration/test_candidate_workflow.py
```

For bounded actual public-input acceptance, copy
[`live_paper.py`](integration/consumers/runtime/live_paper.py),
[`candidate_workflow.py`](integration/consumers/research/candidate_workflow.py) and
[`decision_study.py`](integration/consumers/research/decision_study.py), and the
`research_workflows/` support
directory together outside the checkout, preserving that directory name. Use the
installed core interpreter and a bounded copy of
`configs/live/okx-btc-usdt.json` or `configs/live/bitfinex-btc-usd.json`:

```sh
/absolute/core/bin/python -E -s /absolute/consumer/live_paper.py \
  --config /absolute/okx-paper-capture.json --output /absolute/fresh-okx-paper
```

The maintained workload packages a synthetic historical engineering study before
binding current native feed observations. Source evidence retains both original
receipt and actual post-persistence delivery clocks. The paper price/grid/fee
assumptions are fixtures; live books do not qualify private venue execution or
validate the reference rule's profitability. The roadmap retains the actual
commands, output identities and limits under MR07. This public-network workload
is explicit acceptance work, not an unconditional test-suite network dependency.
It also replays the saved delivery envelopes and timer identities through the
same source/runtime classes, checks exact paper journal/account equality, compares
shadow intents with zero fills, and reopens the account with a fresh recording
identity without duplicating the last decision or its effects.

Run the final local gate with the same real worker and a short macOS socket path:

```sh
PYTEST_ADDOPTS=--basetemp=/private/tmp/mr07-check \
  ALPHA_FEAST_WORKER_PYTHON=/absolute/pinned-feast-worker/bin/python \
  make check > logs/mr07/make-check.log 2>&1
```


## Automatic public paper acceptance

The [public paper consumer](integration/consumers/runtime/public_paper.py) runs
`applications.paper.run_live_shared_paper` through the installed research wheel.
It selects the existing native OKX L2 or Bitfinex L3 adapter, two distinct active
order policies, independent budgets, automatic matching, exact child attribution,
source-event-derived reconciliation and last-eligible-bid net-P&L reports.
`--dedicated` selects one instance on the account. Source profiles and economic
assumptions are retained separately; fixed grids/costs remain authored scenarios.

Copy that single file and the selected `configs/live/okx-btc-usdt.json` or
`configs/live/bitfinex-btc-usd.json` outside the checkout. With an installed core
interpreter, run each venue into a separate absent output:

```sh
/absolute/core/bin/python -I /absolute/copied/public_paper.py \
  --config /absolute/copied/okx-btc-usdt.json --output /absolute/fixture-okx
/absolute/core/bin/python -I /absolute/copied/public_paper.py \
  --config /absolute/copied/bitfinex-btc-usd.json --output /absolute/fixture-bitfinex
```

By default, scripted native frames establish deterministic economic expectations.
Add `--no-trade` for zero economics, `--adverse 1.00` for the higher-cost case, or
`--dedicated` for one active instance. The discovered
[workflow tests](integration/test_public_paper_workflow.py) cover those distinct
cases on both venues, copy the consumer outside the checkout, and verify retained
results and exact replay in a second isolated process. Run them with:

```sh
uv run --frozen --no-editable pytest -q -m integration \
  --basetemp=/private/tmp/public-paper-tests tests/integration/test_public_paper_workflow.py
```

`--live --adverse 0.01` explicitly selects actual public network input, bounded
to 20 frames or ten seconds. It sends only public subscriptions. The output keeps
the account SQLite journal, original captures, manifests, delivery clocks,
matching traces, child orders/costs, independent reconciliation and reports.
It distinguishes observed public source from modeled execution; a finite capture
cannot qualify historical continuity, queue behavior, calibrated venue costs,
service availability or profitability. Actual source runs and artifact identities
belong to the [delivery record](../docs/roadmap/paper-integration.md).

To verify a retained run in a fresh process, repeat its original command with
`--replay` and the same output path, flags, copied consumer and installed artifact.
This mode makes no network request. It checks the retained configuration,
consumer and implementation identities, rebuilds native source state from saved
deliveries, and writes `replay-verification.json` with equal before/after hashes
for accounts, child orders, net orders and matching traces. Existing economic
reports and reconciliation files remain byte-identical. The run also retains
`monitoring-input.json` and the automatically returned `.monitoring` result, with
per-scope dashboard directories containing `snapshot.json`, `dashboard.html`
and `manifest.json`. `monitoring-reconciliation.json` records exact dashboard
to source-event arithmetic and the envelope hash, separately from the account
`reconciliation.json`.

In `--replay`, the consumer also calls
`applications.paper.render_paper_monitoring` with the saved envelope and the
same telemetry journal, using a new output directory. This recovery step
checks zero newly inserted events and equal dashboard names and snapshots; it
does not replay matching or account operations to rebuild the view. The overall
consumer still performs its separate retained-delivery execution replay before
that monitoring recovery check. The [MR12 monitoring record](../docs/roadmap/paper-monitoring.md)
owns observed commands, results and remaining limits.

On a normal run, the consumer supplies a temporary local AF_UNIX datagram
receiver path as `alert_socket`, records which alert sends the receiver reads,
and writes `alert-delivery.json`. Its `human_acknowledged` and `remote_service`
fields are `not_tested`: sender status, receiver receipt and human or remote
acknowledgement are distinct outcomes. The run retains source-clock copies, but
`data.source_clock_drift_seconds` and `data.receipt_to_durable_seconds` remain
`not_measured`; this consumer does not qualify source-clock accuracy.

The focused `test_paper_matching.py`, `test_account_paper_matching.py`,
`test_public_paper.py` and `test_paper_reports.py` cases cover timing, liquidity,
cancel/fill races, uncertainty, failure blocks, duplicate/restart behavior and
independent monetary reconciliation. Existing shared-budget, allocation and
operational tests remain evidence for their unchanged boundaries.

## Shared account admission and reconciliation

The [account consumer](integration/consumers/runtime/shared_account.py) runs
`AccountExecutionApplication` and the installed `alpha-execute account` command
with retained typed configuration, requests and results. It uses authored USDT
spot facts, two active instance decisions, the 8,000 + 8,000 / 10,000 admission
boundary, exact partial-fill/cost goldens, transfer/rebate/correction postings,
unknown/cancel reconciliation, restart and independent stops. Copy it outside
the checkout and run with the actual installed execution interpreter:

```sh
/absolute/execution/bin/python -I /absolute/consumer/shared_account.py \
  --output /absolute/new-account-evidence
```

`unit/execution/test_account_journal.py` adds simultaneous clients, regressed
knowledge clocks, independent quote binding and underfunded-reservation failures.
`unit/risk/test_budgets.py` tests every limit scope with independent amounts;
`unit/accounting/test_accounts.py` tests exact multi-currency replay and corrections.
This MR08 software proof does not qualify a venue, empirical strategy, live
capital, portfolio netting or capacity. The MR08 roadmap record owns its actual
commands and results. Private venue/account qualification remains KIV outside
paper acceptance under the
[live-trading reconsideration record](../docs/roadmap/README.md#live-trading-kiv-and-reconsideration).

## Shared portfolio workflow

The local MR09 increment composes per-instance decision state through
`runtime.SharedDecisionRuntime` and `applications.paper.run_shared_paper`; see
the [runtime](../src/runtime/README.md#shared-decision-runtime) and
[paper application](../src/applications/paper/README.md#shared-account-paper-workflow)
contracts. The installed execution workflow exercises the account journal with
two authored intents on one instrument/account: a target decision and an order
intent. It checks shared budget rejection, compatible physical netting, partial
fill and fee allocation, per-instance/aggregate balances, changed retry bytes,
selective stop and reissue after cancellation/reconciliation, explicit internal
crossing, and parity between the application and installed CLI.

The [installed consumer](integration/consumers/runtime/portfolio_account.py)
and [discovered regression](integration/test_portfolio_workflow.py) run the
same authored workload under OKX/USDT and Bitfinex/USD fixture labels. Those
labels and instrument identities are test inputs; the consumer records
`local-paper-fixture` qualification and `physical_venue_evidence=false`. The
standalone consumer needs
[`portfolio_account_facts.py`](integration/consumers/runtime/portfolio_account_facts.py)
beside it when copied outside the checkout. The
workflow test covers `AccountExecutionApplication` and the installed
`alpha-execute account` command. The [shared decision consumer](unit/runtime/test_shared_decisions.py)
also drives `run_shared_paper` with two distinct executable decision policies,
checks exact physical and attributed balances, restores policy continuation,
and retries an older batch without rewinding newer state. The direct
[allocation tests](unit/portfolio/test_allocation.py) and
[account coordination tests](unit/execution/test_portfolio_accounts.py) cover
exact quantity/fee splits, net fill retry, child ownership, stop/restart and
internal crossing. Actual commands, results and retained artifact identities
belong to the [MR09 acceptance record](../docs/roadmap/README.md#mr09-delivery-and-acceptance).

These are local software proofs over authored account and order facts. They do
not qualify physical OKX or Bitfinex private streams, order handling or account
state. That private venue qualification remains KIV outside paper acceptance
under the [live-trading reconsideration record](../docs/roadmap/README.md#live-trading-kiv-and-reconsideration).

## Local operational qualification

The [operational workflow](integration/test_operational_workflow.py) copies
[`account_operations.py`](integration/consumers/runtime/account_operations.py) and
[`portfolio_account_facts.py`](integration/consumers/runtime/portfolio_account_facts.py)
outside the checkout and exercises installed `alpha-execute account` requests.
For retained evidence, copy those files together and run:

```sh
/absolute/execution/bin/python -I /absolute/consumer/account_operations.py \
  --venue okx --output /absolute/new-operations-output
```

Run `--venue bitfinex` separately with another absent output. Both are authored
spot fixtures. Retained requests, control history, partial/cancel state, exact
fees/cash/positions, backup identity and local watchdog/alert outcomes describe
software behavior. Private venue qualification remains KIV outside paper
acceptance under the
[live-trading reconsideration record](../docs/roadmap/README.md#live-trading-kiv-and-reconsideration).
The watchdog drills use
actual process loss and a bounded SQLite page quota, not host-volume exhaustion.
The account unit tests cover stale recovery, unknown outcomes and snapshot
verification; dedicated candidate tests cover clock/protocol faults and repeat
failure after resume. Existing capture health/recovery and workspace tests cover
their unchanged component boundaries.

The [runbook](../docs/governance/operations.md#local-paper-operations) owns safe
reconciliation, snapshot selection and the remaining external evidence gates.
