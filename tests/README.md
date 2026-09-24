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
directory outside the checkout. They must not import repository test helpers or
add the checkout to `sys.path`. Deliberate `os._exit` support programs run only in
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

Wheel smoke installs the hash-locked runtime without governance, checks every
shipped API/resource and installed identity, reopens the historical snapshot,
and runs the existing book consumer with `--smoke`. This mode verifies one small
synthetic OKX archive through the installed CLI and exact account report. The
default book-consumer mode retains the complete recovery/failure scenario.
Wheel smoke does not repeat all domain workflows or contact services.

The smoke prints and retains its temporary wheel/environment directory. Keep
needed evidence before explicitly cleaning it up. Do not synchronize or reinstall
an environment while tests, notebooks or workers use it. The historical snapshot's
original bytes and identity stay in `fixtures/datasets/historical_snapshot/`.
Existing Binance/Tardis-shaped synthetic fixtures remain compatibility tests;
new data-dependent work follows the [OKX/Bitfinex policy](../docs/roadmap/README.md#current-platform).

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
implicitly download provider data. The [notebook guide](../examples/notebook-operations.md)
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
