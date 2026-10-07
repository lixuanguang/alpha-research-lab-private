# QR API map

The supported names a quant researcher imports, grouped by the task that needs them.
Import each from the package shown, never from a submodule; the
[import audit](quickstart.md#3-audit-your-imports) refuses anything else. Each
name's docstring is its contract; this page says where it fits.

## Exact units and records

| Name | Import from | Use |
| --- | --- | --- |
| `Dimension` | `financial_units` | Binds a quantity kind (`QuantityKind.BASE_UNIT`) to an instrument identity. |
| `Quantity` | `financial_units` | A signed amount in one instrument's dimension. |
| `Money` | `financial_units` | A signed currency amount, such as a study's initial cash. |
| `DecimalGrid` | `financial_units` | Exact conversion and rounding onto the bounded decimal grid, for example a fraction into a `Decimal` limit. |
| `WireRecord` | `serialization` | Base class for your component parameters and policy state: frozen, strictly UTC, exact JSON. |
| `Fingerprint` | `research.experiments` | Names immutable bytes by SHA-256; your metric and chart components expose one as their `identity`. |

## Components in your extension

| Name | Import from | Use |
| --- | --- | --- |
| `NumericField` | `research.observations` | A named field with explicit units, for feature outputs and inputs. |
| `InputRequirement` | `research.observations` | One named source field with its clock and maximum age; a feature schema lists its inputs as these. |
| `DecisionSource` | `research.observations` | The causal source protocol a feature or label reads through. |
| `FeatureTransition` | `research.features` | What a feature kernel returns: values and immutable successor state. |
| `DecisionContext` | `strategies` | What a policy receives: the then-available features and optional prediction. |
| `DecisionTransition` | `strategies` | What a policy returns: an intent, or `None` to abstain, plus its successor state. |
| `TargetIntent` | `strategies` | An absolute position in instrument units. |
| `OrderIntent` | `strategies` | One limit order: side, `Quantity`, limit price and time in force. |
| `QuoteIntent` | `strategies` | A two-sided quote of two `OrderIntent`s. |
| `ReportContext` | `research.reports` | What your metric or chart component receives: the study's folds and their economics. |
| `FoldSummary` | `research.reports` | One fold's ledger, terminal mark and curve; your metric reads these from its `ReportContext`. `terminal_mark` is `None` for a fold left holding without a fresh terminal bid, with `terminal_missing_reason`; report such a fold as missing, never as zero. |
| `ReportObservation` | `research.reports` | One exact series value, or an explicit missing value, at its UTC clock. |
| `MetricValue` | `research.reports` | What your metric returns: its exact value, units and per-fold evidence. |
| `ChartSpec` | `research.reports` | What your chart returns: exact named series for a line, bar or table view. |

Your extension also runs inside the signed paper services, which ship
`research.reports` but not `research.studies`. Import report contracts from
`research.reports`; a paper-services build refuses an extension that imports any
platform module the release does not ship, including inside a function.

Each paper or research decision replaces the instance's working orders, so a policy
that cannot price should return `DecisionTransition(intent=None, state=...)` rather
than invent a price.

## Studies

| Name | Import from | Use |
| --- | --- | --- |
| `BookQuery` | `market_data.query` | Selects one published book partition, instrument and receipt interval for a study input. |
| `IntentSimulationSpec` | `simulation` | The study's spot account: instance, entity, sample window, initial cash, instrument limits and the execution and cost model identities. |
| `LimitExecutionConfig` | `simulation` | The simulator's entry and cancel delays, order lifetime, maximum book age, take fraction and queue-ahead fraction. |
| `EstimatorLifecycle` | `research.models` | Wraps your estimator so fitting stays causal and inference reloads exactly. |

The [study guide](../packages/research-studies.md#generalized-decision-studies)
covers how these combine in a `DecisionStudy`, and the
[example study](../../examples/qr_study.py) uses each.

## Packaging and replay

| Name | Import from | Use |
| --- | --- | --- |
| `CandidateStateContract` | `research.experiments` | Declares a candidate's warm-up, gap and restart behaviour when packaging. |
| `AttemptHistory` | `research.experiments` | A retained attempt's start, outcome and consumed holdouts; a bundle names the one it came from. |
| `CandidateBundle` | `research.experiments` | Reopens a packaged candidate directory and verifies its bytes. |
| `CandidateDeployment` | `configuration` | Places a candidate: instance, entity, mode, input mode and capability selections. |
| `CapabilityProfile` | `configuration` | One implementation's supported envelope. |
| `CapabilityRegistry` | `configuration` | The profiles a deployment's selections resolve against. |
| `CapabilitySelection` | `configuration` | Binds one of the candidate's requirements to one profile. |
| `LocalCandidateExecutor` | `runtime` | Runs a loaded candidate's steps in the calling process. |

To replay a bundle against the study it came from:
1. Open `CandidateBundle(path)`, then decode `bundle.artifact(manifest.attempt)` as an
   `AttemptHistory` to reopen the study's `StudyResult`.
2. Build the replay source from the same published captures as the study.
3. Declare one replay `CapabilityProfile` per requirement in
   `manifest.definition.requirements`: `modes=("replay",)` and the requirement's own
   kind, product, venue, calendar, channel, clock, fields, operations and order
   types. Wrap them in a `CapabilityRegistry`.
4. Select each requirement with `CapabilitySelection(name=..., profile=...)` in a
   `CandidateDeployment(mode="replay", input_mode="source", ...)` whose
   `source_identity` is the replay source's identity.
5. Load it with `CandidateLoader(InstalledExtensions().components("<extension>"),
   registry).load(bundle, deployment)`.
6. Step `LocalCandidateExecutor(loaded)` through the study fold's decision instants,
   carrying each step's checkpoint into the next. Each step's
   `decision.intent` must equal the study's.

## Feature store

| Name | Import from | Use |
| --- | --- | --- |
| `FeastOfflineWorker` | `research.features` | Runs the separately locked Feast worker; give it the worker interpreter's command and a timeout. |

The [feature store guide](../packages/research-features.md#versioned-feature-store-and-local-feast-serving)
covers materialization, serving and the worker environment.
