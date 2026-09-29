# Exact predictive model studies

Owner: repository founder. Updated 2026-09-20. **Bounded research implementation.**
`research.models` owns model input admission, construction, serialization and
prediction. `research.experiments` owns attempts, evaluation records and ClearML
publication. The existing `applications.explore` composes both through
`evaluate_model` and `publish_experiments`; no new runner or command is added.

The first question is whether a centered, one-feature least-squares model can
predict the separate forward-return diagnostic from the versioned trailing
return. This is an engineering example, not an accepted empirical model or a
strategy. A configured intercept/slope supplies the analytical no-fit comparator.
Models emit dimensionless predictions, never orders, positions or economic P&L.

`EstimatorRegistry` now selects compatible implementations through typed factories
over `LinearDefinition`. `ModelStudy.estimator_implementation` defaults to
`linear-return`; an explicitly supplied registry can construct a compatible
`LinearModel` subclass. The implementation ID enters the retained study identity.
The existing construction, evaluation, fitting boundaries and `ModelVersion`
contract remain authoritative. Unregistered/duplicate IDs fail explicitly.
This seam does not imply support for arbitrary model schemas, SHAP explanations
or prediction-to-order binding; those require their own working consumers.

## Generalized estimator lifecycle

Owner: quant development. Implemented 2026-09-24 alongside the retained linear
study API. `EstimatorAdapter` accepts arbitrary ordered `FeatureVector` schemas
and immutable state bytes; it does not subclass `LinearModel` or receive
`LinearDefinition`. `EstimatorLifecycle` passes only admitted rows/labels to the
selected adapter. It verifies each `Outcome.sample(vector)` against the existing
`TemporalSplit`, including actual input digests, label availability, purge and
embargo. Optional preprocessing must bind the same admitted rows and split.
Held-out or future values cannot enter either fit. Inference receives no labels.

`EstimatorVersion` retains the input feature/fitted-transform signature, label
schema and units, split/fit rows, fit-input digest, cutoff, authored availability,
actual immutable state bytes and digest. `predict` is reload-only and checks
implementation, schema/order/units, availability and missing values. The retained
`research.results.Prediction` binds the exact model/vector/entity/clock and units.
A [decision policy](../../strategies/README.md) turns it into an intent; the model
owns no portfolio, risk or order execution.

`NearestExample` is a nonlinear multi-feature reference: exact squared distance
with equal input units, and first admitted row winning an exact tie. Its state
contains portable points/outcomes, with no executable pickle. The installed
[fresh consumer](../../../tests/integration/consumers/research/decision_extensions.py)
uses a different external estimator and custom label/feature/quote policy;
shared orchestration does not substitute a built-in implementation.

These APIs provide MR02 research/decision contracts. The older `evaluate_model`
workflow below still owns its original linear report schema. Generalized formal
study evaluation, search, reports and candidate/runtime promotion remain MR03/MR05.
No external learned-model deployment or empirical success is established.

## Inputs and construction

`ModelStudy` is strict versioned JSON. It pins completed
[feature study](../features/README.md) results by attempt ID and result SHA-256 in
the same retained root. The consumer reopens actual result bytes, verifies their
digests, checks row alignment and definition identities, and reconstructs the
sample information intervals. It does not implicitly download data. Keep the
original raw/snapshot stores alongside retained feature attempts for reproduction.
An earlier exploratory inspection is not made untouched by calling it a model input.
Use the complete family history; do not rename families or move stores to evade
previous final-holdout access.

`ModelFrame` applies Pandera 0.33.1 to the selected dataframe boundary. The exact
column order is `row_id`, `decision_at`, `features_available_at`,
`label_available_at`, `units`, `trailing_return`, `forward_return`. Object dtype is
intentional: values remain UTC Python datetimes with microsecond precision and
canonical `ExactRatio` records, including arbitrarily large integer components.
The schema rejects undeclared/missing/reordered columns, duplicate IDs, naive
clocks, wrong units and approximate numerical values. It never coerces or mutates
the caller frame. Nullable outcomes/features remain explicitly missing; required
identity and feature clocks cannot be null. Pandera validates dataframe structure;
the domain records and temporal split still own causal and numerical validity.

The input is bounded to 1,024 rows. One signature pins the ordered feature name,
feature and label definitions, dimensionless units and exact-rational convention.
The split's sample records must equal the verified dataset records, including
digests and availability clocks. Calibration admits only
`TemporalSplit.fitting_rows()` and checks the same row IDs immediately before
construction. Missing admitted values and a zero-variance design fail explicitly.
No unrelated dataframe columns or future/held-out values enter centering or fitting.

Least squares retains training mean `center`, mean target `intercept`, and
`slope = sum((x-center)*(y-intercept))/sum((x-center)**2)`. Prediction is
`intercept + slope*(x-center)`. All calculations use exact `Fraction` arithmetic
and canonical integer-string serialization; reload agreement has **zero tolerance**.
Centering is intrinsic fitted model state, not a second feature-definition system.
Configured models retain exact authored intercept/slope and a zero center, with
no training window, fitting cutoff or fitted rows. Neither mode uses randomness;
the semantic seed map is explicitly empty.

## State and evaluation

A `ModelVersion` contains actual state bytes and their SHA-256, definition and
assumptions, input signature, construction attempt, actual creation time, fit
window/cutoff/rows and admitted fit-input digest. Its historical `available_at`
is an explicitly authored simulation assumption and cannot precede the fit cutoff.
It is not measured deployment latency. A new construction always creates a new
version even if its numerical coefficients match an earlier attempt.

The application retains usable state **before** evaluation. Failed calibration
retains diagnostics and no invented state. A rejected evaluation retains its usable
model and exact evaluation artifact. `models` references select reload-only
inference; they cannot also specify a new definition or availability time.
Inference validates actual state bytes and signature and never fits implicitly.

Evaluation chooses the latest supplied version available by each decision. Tied
availability times are ambiguous and rejected. A future/full-history model cannot
serve an earlier decision. The feature must also be available then. Evaluation
uses only labels available by the separately declared outcome cutoff, retains
missing/late exclusions, and refuses an empty scored sample. Validation outcomes
cannot reach the frozen holdout. Final-holdout access is durably recorded before
input results are exposed, and remains consumed if reading or evaluation fails.

`EvaluationRecord` retains dataset and split identities, partition/window,
prediction-to-version mappings, outcome availability, exact mean squared error
in dimensionless-squared units, and the frozen threshold's acceptance/rejection
reason. Reload validates the MSE against those exact prediction/outcome pairs.
Mutable model byte buffers are rejected. Residuals are recoverable exactly from the recorded prediction/outcome
pairs. These are predictive diagnostics, separate from calibration and later
strategy economics. Native residual diagnostics answer the selected question;
there is no selected SHAP explanation question, so SHAP remains conditional.

## Supported invocation and recovery

A model configuration is prepared from the actual completed feature result and
its `ModelDataset.rows` sample intervals. The installed
[acceptance consumer](../../../tests/integration/consumers/research/feature_study.py)
shows the complete saved-input construction and reload journey. With a retained
configuration and the SDK endpoint/credentials configured outside the manifest:

```python
from pathlib import Path
from applications.explore import evaluate_model, publish_experiments
from research.studies import ClearMLDestination

root = Path("/absolute/path/to/retained/research")
history = evaluate_model(
    root / "model.json",
    attempts=root / "attempts",
    tracking=ClearMLDestination(
        project="research",
        api_uri="http://127.0.0.1:18008",
        files_uri="http://127.0.0.1:18081",
    ),
)
# After publication interruption, retry only the outbox, never the evaluation:
receipts = publish_experiments(root / "attempts")
```

Malformed/oversized configuration, unavailable retention and writer contention
fail before a supported attempt begins. Resolved invocations retain completed,
failed, rejected or abandoned outcomes. Hard process termination leaves an
incomplete attempt and publication intent; explicitly finish it as abandoned
with `AttemptStore.finish` before publishing it. New executions create new attempts.

Backup the whole attempt root, including family files, original requests,
terminal events, state/evaluation artifacts and publication records. Backup and
reopen checks verify real state bytes and exact predictions in a fresh installed
process. Keep the matching wheel and locked environment. Reversal means using the
previous wheel for its supported workflows while retaining these versioned bytes;
the previous wheel cannot interpret the new model schema. No deployed runtime or
trading authority is introduced.
