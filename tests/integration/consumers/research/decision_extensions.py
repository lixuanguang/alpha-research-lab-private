"""Run fresh feature, label, estimator and quote implementations through installed contracts."""

from __future__ import annotations

# standard library imports
import hashlib
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Literal

# project library imports
from applications.explore import (
    DecisionCheckpoint,
    DecisionResult,
    inspect_decisions,
    run_decisions,
)
from configuration import DecisionRun
from financial_units import (
    Currency,
    DecimalGrid,
    Dimension,
    ExactRatio,
    Price,
    Quantity,
    QuantityKind,
)
from reference_data.instruments import InstrumentId
from research.experiments import TemporalSplit, TimeWindow
from research.features import (
    CenterColumns,
    FeatureSchema,
    FeatureSession,
    FeatureTransition,
    FeatureVector,
    FittedTransform,
    TransformVersion,
)
from research.labels import Outcome
from research.models import EstimatorLifecycle, EstimatorVersion
from research.observations import (
    DecisionInputs,
    InputRequirement,
    NamedObservation,
    NumericField,
    NumericHistorySource,
)
from serialization import DomainCodec, WireRecord
from strategies import DecisionContext, DecisionTransition, OrderIntent, QuoteIntent

_ENTITY = "c87d983f-e7ec-4e64-8d54-9f2be67a64b8"
_CAPABILITIES = (
    "product:spot",
    "calendar:24/7",
    "input:non-book",
    "feature:incremental",
    "intent:quote",
)


class _SignalFeature:
    """Implement a fresh two-column nonlinear feature without registering a built-in case."""

    def __init__(self, schema: FeatureSchema) -> None:
        """Bind the exact authored definition."""
        self._schema = schema

    @property
    def schema(self) -> FeatureSchema:
        """Expose the complete custom signature."""
        return self._schema

    def initial_state(self) -> bytes:
        """Start an independent sample count."""
        return b"0"

    def validate_state(self, state: bytes) -> None:
        """Reject malformed portable state."""
        if not state.isdigit():
            raise ValueError("invalid custom feature count")

    def step(self, inputs: DecisionInputs, state: bytes) -> FeatureTransition:
        """Compute x and x squared with explicit exact state progression."""
        self.validate_state(state)
        value = inputs.observations[0].value
        if value is None:
            raise ValueError("custom feature requires its numeric input")
        x = Fraction(int(value.numerator), int(value.denominator))
        return FeatureTransition(
            values=(value, ExactRatio.from_fraction(x * x)),
            reasons=("synthetic", "synthetic"),
            state=str(int(state) + 1).encode(),
        )


class _AffineState(WireRecord, frozen=True):
    """Serialize one fresh estimator's exact learned offset."""

    offset: ExactRatio

    def __post_init__(self) -> None:
        """Validate exact state through its owned rational contract."""
        self.offset.__post_init__()


class _OffsetEstimator:
    """Fit a mean outcome and infer its sum with the first transformed feature."""

    @property
    def identity(self) -> str:
        """Version the external implementation and all fixed formula choices."""
        return "example-offset-estimator-v1"

    def fit(self, rows: tuple[FeatureVector, ...], outcomes: tuple[ExactRatio, ...]) -> bytes:
        """Assert only two admitted rows reached this fresh estimator, then fit their mean."""
        assert len(rows) == len(outcomes) == 2
        assert rows[0].values[0] == ExactRatio(numerator="-1", denominator="1")
        offset = sum(
            (Fraction(int(v.numerator), int(v.denominator)) for v in outcomes), Fraction()
        ) / len(outcomes)
        return DomainCodec().encode_json(_AffineState(offset=ExactRatio.from_fraction(offset)))

    def predict(self, state: bytes, row: FeatureVector) -> ExactRatio:
        """Reload bytes with no implicit fitting or built-in model dependency."""
        saved = DomainCodec().decode_json(state, _AffineState)
        value = row.values[0]
        if value is None:
            raise ValueError("missing inference feature")
        return ExactRatio.from_fraction(
            Fraction(int(saved.offset.numerator), int(saved.offset.denominator))
            + Fraction(int(value.numerator), int(value.denominator))
        )


class _FutureLevel:
    """Supply a fresh label definition separate from the feature/model implementation."""

    def evaluate(
        self,
        row: FeatureVector,
        base: NamedObservation,
        future: NamedObservation,
        *,
        observed_at: datetime,
    ) -> Outcome:
        """Return a delayed scalar outcome without adding it to the decision vector."""
        if future.available_at is None or future.available_at > observed_at:
            raise ValueError("future label still pending")
        return Outcome(
            feature_identity=row.identity,
            definition="example-future-level-v1",
            field=NumericField(name="level", units="dimensionless"),
            information_start=base.event_at,
            information_end=future.event_at,
            available_at=future.available_at,
            value=future.value,
            reason="synthetic_reference",
            lineage=(base.lineage, future.lineage),
        )


class _QuotePolicy:
    """Bind a fresh prediction policy to exact two-sided quote intent and portable state."""

    @property
    def identity(self) -> str:
        """Version the reference price rule, spread and unit quantity."""
        return "example-forecast-quote-v1"

    @property
    def output(self) -> Literal["quote"]:
        """Declare two-sided quote support before work starts."""
        return "quote"

    def admit(self, fields: tuple[NumericField, ...], prediction: NumericField | None) -> None:
        """Require the custom signature and dimensionless model output."""
        if (
            tuple(f.name for f in fields) != ("level", "square")
            or prediction is None
            or prediction.units != "dimensionless"
        ):
            raise ValueError("custom quote signature mismatch")

    def initial_state(self) -> bytes:
        """Start a fresh per-instance quote counter."""
        return b"0"

    def validate_state(self, state: bytes) -> None:
        """Reject corrupt count bytes."""
        if not state.isdigit():
            raise ValueError("invalid quote count")

    def decide(self, context: DecisionContext, state: bytes) -> DecisionTransition:
        """Convert prediction to a quote without constructing any executable venue client."""
        self.validate_state(state)
        forecast = context.prediction
        if forecast is None:
            raise ValueError("custom quote requires a prediction")
        center = Fraction(100) + Fraction(
            int(forecast.value.numerator), int(forecast.value.denominator)
        )
        dimension = Dimension(
            instrument_id=InstrumentId.from_canonical_text(context.features.entity),
            kind=QuantityKind.BASE_UNIT,
        )
        quantity = Quantity(value=Decimal("1"), dimension=dimension)
        return DecisionTransition(
            intent=QuoteIntent(
                bid=OrderIntent(
                    side="buy",
                    quantity=quantity,
                    limit=Price(
                        value=DecimalGrid.exact_decimal(center - 1),
                        currency=Currency.from_code("USD"),
                        per=dimension,
                    ),
                    time_in_force="post-only",
                ),
                ask=OrderIntent(
                    side="sell",
                    quantity=quantity,
                    limit=Price(
                        value=DecimalGrid.exact_decimal(center + 1),
                        currency=Currency.from_code("USD"),
                        per=dimension,
                    ),
                    time_in_force="post-only",
                ),
            ),
            state=str(int(state) + 1).encode(),
        )


class _Inputs:
    """Author the same retained source independently in the two installed processes."""

    @staticmethod
    def at(seconds: int) -> datetime:
        """Use explicit synthetic UTC clocks."""
        return datetime(2026, 9, 23, tzinfo=UTC) + timedelta(seconds=seconds)

    @classmethod
    def source(cls) -> NumericHistorySource:
        """Create one non-book signal with two training and two inference observations."""
        requirement = InputRequirement(
            name="measurement",
            family="non-book",
            clock="authored",
            field=NumericField(name="level", units="dimensionless"),
            max_age_us=1_000_000,
        )
        rows = tuple(
            NamedObservation(
                input=requirement,
                entity=_ENTITY,
                event_at=cls.at(at),
                available_at=cls.at(at),
                value=ExactRatio(numerator=str(value), denominator="1"),
                reason="synthetic",
                lineage=f"non-book:{at}:{value}",
            )
            for at, value in ((10, 1), (20, 3), (40, 5), (50, 7))
        )
        return NumericHistorySource(rows, (requirement,))

    @staticmethod
    def feature(source: NumericHistorySource) -> _SignalFeature:
        """Select a custom implementation/schema independent of maintained feature defaults."""
        return _SignalFeature(
            FeatureSchema(
                implementation="example-square-feature-v1",
                inputs=source.requirements,
                outputs=(
                    NumericField(name="level", units="dimensionless"),
                    NumericField(name="square", units="dimensionless"),
                ),
                parameters=(),
                mode="incremental",
                ttl_us=0,
            )
        )


def main() -> None:
    """Fit, run, checkpoint and reload fresh extensions outside the repository checkout."""
    output = Path(sys.argv[1])
    output.mkdir(exist_ok=True)
    codec, source = DomainCodec(), _Inputs.source()
    feature, policy = _Inputs.feature(source), _QuotePolicy()
    transform, model = FittedTransform(CenterColumns()), EstimatorLifecycle(_OffsetEstimator())
    if len(sys.argv) == 3:
        config = codec.decode_json((output / "config.json").read_bytes(), DecisionRun)
        fitted = codec.decode_json((output / "transform.json").read_bytes(), TransformVersion)
        version = codec.decode_json((output / "model.json").read_bytes(), EstimatorVersion)
        checkpoint = codec.decode_json(
            (output / "checkpoint.json").read_bytes(), DecisionCheckpoint
        )
        resumed = run_decisions(
            config,
            source=source,
            feature=feature,
            policy=policy,
            capabilities=_CAPABILITIES,
            model=model,
            model_version=version,
            transform=transform,
            transform_version=fitted,
            checkpoint=checkpoint,
        )
        (output / "resumed.json").write_bytes(codec.encode_json(resumed))
        return
    session = FeatureSession(feature, instance="fit", entity=_ENTITY)
    rows = tuple(session.evaluate(source.read(_ENTITY, _Inputs.at(at))) for at in (10, 20))
    labels = _FutureLevel()
    outcomes: list[Outcome] = []
    for row, outcome in zip(rows, (2, 6), strict=True):
        base = source.read(_ENTITY, row.decision_at).observations[0]
        future = NamedObservation(
            input=base.input,
            entity=_ENTITY,
            event_at=row.decision_at + timedelta(seconds=1),
            available_at=row.decision_at + timedelta(seconds=1),
            value=ExactRatio(numerator=str(outcome), denominator="1"),
            reason="synthetic_label",
            lineage=f"label:{outcome}",
        )
        outcomes.append(labels.evaluate(row, base, future, observed_at=_Inputs.at(30)))
    split = TemporalSplit(
        training=TimeWindow(start=_Inputs.at(0), end=_Inputs.at(25)),
        validation=TimeWindow(start=_Inputs.at(40), end=_Inputs.at(55)),
        holdout=TimeWindow(start=_Inputs.at(70), end=_Inputs.at(80)),
        samples=tuple(o.sample(r) for r, o in zip(rows, outcomes, strict=True)),
        fit_mode="labels",
        fit_cutoff=_Inputs.at(30),
        embargo_us=0,
        rationale="separate engineering fit and inference intervals",
    )
    fitted = transform.fit(rows, split, available_at=_Inputs.at(30))
    version = model.fit(
        rows,
        tuple(outcomes),
        split,
        available_at=_Inputs.at(30),
        transform=transform,
        transform_version=fitted,
    )
    config = DecisionRun(
        instance="custom-quotes",
        entity=_ENTITY,
        product="spot",
        calendar="24/7",
        source_identity=source.identity,
        feature_identity=feature.schema.identity,
        policy_identity=policy.identity,
        model_identity=version.identity,
        transform_identity=fitted.identity,
        output="quote",
        decisions=(_Inputs.at(40), _Inputs.at(50)),
        required_capabilities=(),
    )
    history = inspect_decisions(
        config,
        source=source,
        feature=feature,
        policy=policy,
        capabilities=_CAPABILITIES,
        attempts=output / "attempts",
        family="custom-research-extensions",
        model=model,
        model_version=version,
        transform=transform,
        transform_version=fitted,
    )
    payload = history.events[-1].result
    assert payload is not None
    whole = codec.decode_json(payload, DecisionResult)
    assert tuple(p.value.numerator for p in whole.predictions) == ("7", "9")
    assert isinstance(whole.decisions[0].intent, QuoteIntent)
    assert whole.decisions[0].intent.bid.limit.value == Decimal("106")
    assert whole.decisions[0].intent.ask.limit.value == Decimal("108")
    prefix = run_decisions(
        config,
        source=source,
        feature=feature,
        policy=policy,
        capabilities=_CAPABILITIES,
        model=model,
        model_version=version,
        transform=transform,
        transform_version=fitted,
        stop_after=1,
    )
    for name, record in (
        ("config", config),
        ("transform", fitted),
        ("model", version),
        ("checkpoint", prefix.checkpoint),
        ("result", whole),
    ):
        (output / f"{name}.json").write_bytes(codec.encode_json(record))
    subprocess.run([sys.executable, "-I", __file__, str(output), "resume"], check=True, timeout=60)
    resumed = codec.decode_json((output / "resumed.json").read_bytes(), DecisionResult)
    assert prefix.features + resumed.features == whole.features
    assert prefix.decisions + resumed.decisions == whole.decisions
    assert resumed.checkpoint == whole.checkpoint
    print(
        codec.encode_json(
            {
                "result_sha256": hashlib.sha256(payload).hexdigest(),
                "decisions": len(whole.decisions),
                "fresh_feature_label_estimator_quote": True,
                "restart_equal": True,
            }
        ).decode()
    )


if __name__ == "__main__":
    main()
