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

## 4. Run and retain a study

Compose `applications.explore.StudyComponents` with your component instances and run
`evaluate_study` on a `DecisionStudy`, as the
[study guide](../src/research/studies/README.md#generalized-decision-studies)
describes. To make the study packageable, retain your installed extension's
identity:

```python
from runtime import InstalledExtensions

record = InstalledExtensions().artifact("qr-signals")
# components.artifacts includes record; study.extensions includes record.fingerprint
```

The artifact is your extension's installed `RECORD`. Its fingerprint is the identity
the packaged candidate will name, so the study pins exactly the code you will
deploy. Use `PublicationPolicy(mode="local")` for a first run, or deferred
publication to ClearML once the local services are up. The study, its fold results,
report and fitted state stay in the attempt store.

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

The [packaging consumer](../tests/integration/consumers/research/candidate_packaging.py)
runs this whole step against the template extension.

## 6. Serve a stored feature (optional)

For an input that no live feed provides, store the feature and serve it. Register a
`FeatureStoreDefinition` for your feature schema. Publish snapshots of one version
with `applications.explore.materialize_features`, which prepares each snapshot,
publishes and verifies its Feast generation, then appends it. Calling it again with
the same version and later decisions extends the version's stream. Pass the
definition to `CandidatePackager.publish(feature_store=...)`, and select the version
with `PackagedCandidate.feature_version`. The
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

Your custom metric and chart reach paper dashboards through the candidate's metric
contracts, with `applies_to` including `runtime`, and
`runtime.CandidateMonitoringExporter`.
