# From a clean machine to a paper candidate

This is the supported path for a quantitative researcher (QR). It goes from a fresh
checkout to an extension package of your own, a retained study, a packaged candidate,
a served feature and a supervised paper run. Each step uses installed commands and the
supported API only: the names each package lists in its `__init__.py` `__all__`. The
[QR guide](README.md) explains what to research. This page covers how to run it.

Formal QR research still starts only after MR17/G5 acceptance. Until then this path
is for onboarding and engineering trials.

## 1. Provision the environments

On macOS arm64 with Docker Desktop running, from the repository root:

```sh
uv python install
uv sync --frozen --no-editable
make local-services-up
make local-services-status
```

`--no-editable` installs the platform the way a release does. Plain `uv sync`
leaves an editable install, so a run could read source files that no release
contains. The [development environment](../docs/README.md#development-environment)
covers the details, and the
[research-session prerequisites](README.md#before-every-research-session) cover the
local services.

Keep installed runs out of the checkout's environment. Give each one its own
environment, built from the same lock:

```sh
UV_PROJECT_ENVIRONMENT=/private/tmp/qr-research uv sync --frozen --no-editable
```

Feature serving uses the separately locked Feast worker; set it up once as its
[worker guide](../configs/development/research-worker/README.md#setup-and-lock-audit)
describes.

## 2. Lay out an extension package

Your components live in your own project, outside this repository. Start from the
maintained template, [`extensions/engineering-candidates`](../extensions/engineering-candidates/):

```text
qr-signals/
  pyproject.toml          # name, version, dependencies, one entry point
  src/qr_signals/
    __init__.py           # exports your component classes
    components.py         # features, policies, metrics, charts, a ComponentProvider
  tests/
```

- **Project.** Give it a distinct name that does not start with `alpha-research-`.
  Declare only dependencies that the paper-services lock already contains. A new
  third-party dependency needs a reviewed lock change in this repository first.
- **Registration.** Declare exactly one provider class in `pyproject.toml`, and no
  scripts:

  ```toml
  [project.entry-points."alpha_research.candidate_components"]
  qr-signals = "qr_signals:ComponentProvider"
  ```

- **Provider.** `ComponentProvider.factories()` returns `runtime.ExtensionFactories`:
  your feature, policy, transform, estimator, metric and chart constructors by
  registered key, as the template shows.
- **Feature inputs.** Book and trade inputs reach live paper directly. Reference and
  other non-book inputs reach paper only through the feature store (step 6).
- **Report code.** A metric or chart must construct without the research reporting
  stack. Import study records inside `evaluate`, as `FoldNetMetric` does.

Install your project into the research environment without changing its locked
packages:

```sh
uv pip install --python /private/tmp/qr-research/bin/python --no-deps /path/to/qr-signals
```

## 3. Audit your imports

From the checkout:

```sh
uv run --frozen --no-editable alpha-governance-engineering-standards import-audit /path/to/qr-signals
```

The audit reports every private name, deep module or unexported name that your code
imports from a platform package, and any `sys.path` change. It reads the installed
packages' `__all__` without importing them. A release build of your extension runs
the same audit and refuses any finding.

## 4. Write and run a study

### Capture and publish data

Collect public books and trades for a fixed UTC window with `alpha-collect
capture-run`, one run per feed, as the
[collector guide](../docs/data/l3-collectors.md#finite-public-collection-with-segment-rollover)
describes. Start from the maintained feed configurations under `configs/live/`; a
trades feed is the same configuration with `channel` `trades` and `depth` 0. Pass
`--universes` so research may read what you collect:

```sh
alpha-collect capture-run --config /absolute/okx-btc-usdt-books.json \
  --universes /absolute/universes.json --window /absolute/window.json \
  --run-directory /absolute/runs/okx-btc-usdt-books
alpha-collect capture-run-replay --run-directory /absolute/runs/okx-btc-usdt-books \
  --max-seconds 7200
```

**Instrument identity.** Every listing has one canonical `InstrumentId`, a UUID
authored once and kept forever. Reuse the identity a maintained configuration
already gives a listing. For a listing no configuration names yet, author a new
random UUID once, record it in your own configuration and universes, and never
derive it from a symbol.

Publish the completed runs. Pass every segment of a book run, and the last segment
of a trades run (it carries its whole chain):

```sh
alpha-dataset capture-publish --captures /absolute/runs/okx-btc-usdt-books/segments/<id> \
  /absolute/runs/okx-btc-usdt-trades/segments/<last-id> \
  --store /absolute/data/raw --snapshots /absolute/data/snapshots \
  --max-records 1000000 --max-bytes 1000000000
alpha-dataset discover --snapshots /absolute/data/snapshots \
  --max-entries 100 --max-bytes 64000000
```

The command prints the book snapshot identity and one trades snapshot identity per
trades run. Captured trades keep each message's coverage, so research applies the
same synchronization, staleness and flow-window rules the live trade source does
([captured public trades](../src/market_data/README.md#captured-public-trades)).

To version the published data, create a repository and publish `raw/` and
`snapshots/` with `market_data.storage.LakeFSStorage` (`create`, then `publish`,
which returns the verified `DatasetVersion`). Retain that version; `materialize`
reopens it later. Add `features/` in a later version once you have derived
features ([lakeFS guide](../configs/development/lakefs/README.md)).

### Run the example study

The maintained [study example](qr_study.py) composes every component role from the
[`engineering-candidates` template](../extensions/engineering-candidates/) over the
published snapshots. Copy it into your project and change what you need:

```sh
python examples/qr_study.py rule --snapshots /absolute/data/snapshots \
  --raw /absolute/data/raw --attempts /absolute/attempts \
  --book-snapshot <books> --instrument <instrument id> --trades-snapshot <trades> \
  --start 2026-10-04T10:00:00+00:00 --end 2026-10-04T10:30:00+00:00 \
  --train 300 --test 180 --folds 3 --holdout 300 --cadence 15 --horizon 60
python examples/qr_study.py learned ...                       # same arguments
python examples/qr_study.py learned --partition holdout ...   # once, last
```

The example selects the instrument's book from the book snapshot, which can hold
several. It shows the rules every study follows:
- **Every role comes from your extension.** The feature is the extension's
  registered `projection`; the transform, estimator and policies are its classes.
  `ForwardMidReturn` is a label: it is study code, not a registered component.
- **Inputs are complete before the first decision.** A fit refuses a training row
  with a missing feature, so the first window starts after the longest input
  window (`--warmup`, 30 seconds of trade flow here).
- **Labels stay inside their fold.** Training and validation decisions leave one
  label horizon before their window ends, so no label reads the holdout.
- **The holdout runs once**, after the validation folds, and its use is recorded.
- **Depth is bounded explicitly.** `CapturedStudyMarket` keeps the best
  `--max-levels` per side; the bound is part of the market identity.

To make the study packageable it retains the installed extension's identity:

```python
from runtime import InstalledExtensions

record = InstalledExtensions().artifact("qr-signals")
# components.artifacts includes record; study.extensions includes record.fingerprint
```

The artifact is your extension's installed `RECORD`. Its fingerprint is the identity
the packaged candidate will name, so the study pins exactly the code you will
deploy. Use `PublicationPolicy(mode="local")` for a first run, or deferred
publication to ClearML once the local services are up, then
`applications.explore.publish_experiments`. The study, its fold results, report
and fitted state stay in the attempt store; `research.studies.StudyResult` and
`StudyReportReader` reopen them. The
[study guide](../src/research/studies/README.md#generalized-decision-studies) covers
search (`compare_studies`) and every configuration rule.

**A policy must decide at every decision.** There is no "no intent" result. A target
policy can go flat; the example's quote policy refuses a missing touch instead of
inventing a price, so give it a book requirement fresh enough for your cadence.

## 5. Package a candidate

```python
from runtime import CandidatePackager, ComponentSelection

manifest = CandidatePackager().publish(
    root / "candidates" / "qr-imbalance",
    store=store,
    attempt_id=history.start.attempt_id,
    extension="qr-signals",
    selections=(
        ComponentSelection(role="feature", factory_key="...", parameters=b"{}"),
        ComponentSelection(role="policy", factory_key="...", parameters=policy_json),
        ComponentSelection(role="metric", factory_key="...", parameters=b"{}"),
        ComponentSelection(role="chart", factory_key="...", parameters=b"{}"),
    ),
    name="qr-imbalance",
    version="1",
    venue="okx",
    cadence_us=3_000_000,
    state=state_contract,
    metrics=metric_contracts,
    limitations=("...",),
)
```

Give one selection per component the study used: its registered key and the JSON
parameters that rebuild it. The packager builds each one through your installed
extension and refuses any whose identity differs from what the study recorded. It
also refuses a study that did not retain the extension (step 4). Requirements are
derived from the study's inputs and output. The bundle is verified on read and named
by its definition identity.

Every metric and chart the study used needs a selection and a matching
`CandidateMetricContract`. The [example's test](../tests/integration/test_qr_study_example.py)
packages the learned example study this way.

## 6. Serve a stored feature (optional)

To have paper read your feature from the feature store instead of computing it in
the candidate, serve it:
1. **Build the definition.** `CandidatePackager().feature_store(store, attempt_id,
   name=...)` builds the `FeatureStoreDefinition` from your study: its schema and,
   for a fitted study, the last fold's transform identity and output fields.
2. **Materialize history.** `research.features.FeatureMaterializer().materialize(...)`
   computes each vector, applies the study's `FittedTransform` with its retained
   `TransformVersion` (never refitting), publishes and verifies the Feast
   generation, then appends the snapshot. Calling it again with the same version
   and later decisions extends the version's stream.
3. **Package and select.** Pass the definition to
   `CandidatePackager.publish(feature_store=...)`, which refuses a definition that
   differs from the study's, and select the version with
   `PackagedCandidate.feature_version`.

In paper, the operator's feature publisher extends the same version from the live
book and trades feeds
([paper services](../src/applications/paper/README.md#supervised-local-deployments)).
The
[feature store guide](../src/research/features/README.md#versioned-feature-store-and-local-feast-serving)
covers point-in-time rules, faults and rollback.

## 7. Take the candidate to paper

An operator builds a signed paper-services release that contains your candidate
bundles (`--candidates`) and your extension project (`--extensions`). The release
records your extension's source, wheel and admitted dependencies. The operator then
checks every configured candidate with `deployment-check`, signs each account's
deployment from those identities, activates it, and runs the supervisor under its
grants. The [operations runbook](../docs/governance/operations.md#take-a-packaged-candidate-to-signed-paper)
lists the exact steps.

Your custom metric reaches paper dashboards through the candidate's metric
contracts: declare `applies_to` including `runtime`. During a supervised run the
diagnostics process evaluates your packaged metric component over each instance's
attributed paper fills, exactly as a study evaluates a fold, and writes it to the
account's telemetry beside the decision delay and, for a learned candidate, its
predictions (`runtime.CandidateMonitoringExporter`). A declared `warning_below` or
`warning_above` becomes an alert rule on the account's dashboard, delivered to the
configuration's `alert_socket`.
