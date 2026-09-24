"""Prove named research contracts with independent exact, temporal and failure examples."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from applications.explore import (
    DecisionCheckpoint,
    DecisionResult,
    inspect_decisions,
    run_decisions,
)
from configuration import DecisionRun
from financial_units import Dimension, ExactRatio, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from research.experiments import AttemptStore, TemporalSplit, TimeWindow
from research.features import (
    CenterColumns,
    FeatureCheckpoint,
    FeatureSchema,
    FeatureSession,
    FeatureVector,
    FittedTransform,
    ProjectionFeature,
    RunningMeanFeature,
    TransformVersion,
)
from research.labels import NumericDifference, Outcome
from research.models import EstimatorLifecycle, EstimatorVersion, NearestExample
from research.observations import (
    InputRequirement,
    NamedObservation,
    NumericField,
    NumericHistorySource,
)
from serialization import DomainCodec
from strategies import ConfirmedSignal, DecisionContext, DecisionSession, TargetIntent

_START = datetime(2026, 9, 23, tzinfo=UTC)
_ENTITY = "4476df8e-6342-4417-839e-e41b88f41446"
_OTHER = "c87d983f-e7ec-4e64-8d54-9f2be67a64b8"
_CAPABILITIES = (
    "product:spot",
    "calendar:24/7",
    "input:non-book",
    "feature:batch",
    "feature:incremental",
    "intent:target",
)


class _Scenario:
    """Author independent numeric inputs without borrowing production expected results."""

    @staticmethod
    def at(seconds: int) -> datetime:
        """Offset a UTC decision from the fixture epoch."""
        return _START + timedelta(seconds=seconds)

    @staticmethod
    def ratio(value: int) -> ExactRatio:
        """Author canonical integer rational goldens."""
        return ExactRatio(numerator=str(value), denominator="1")

    @classmethod
    def source(cls, *, future: int = 5, entity: str = _ENTITY) -> NumericHistorySource:
        """Retain two numeric non-book indicators and explicit source revisions."""
        fields = tuple(
            InputRequirement(
                name=name,
                family="non-book",
                clock="authored",
                field=NumericField(name="level", units="score"),
                max_age_us=5_000_000,
            )
            for name in ("activity", "inventory")
        )
        rows = tuple(
            NamedObservation(
                input=field,
                entity=entity,
                event_at=cls.at(at),
                available_at=cls.at(at),
                value=cls.ratio(value),
                reason="synthetic",
                lineage=f"fixture:{entity}:{at}:{index}:{value}",
            )
            for at, values in ((10, (1, 10)), (20, (3, 14)), (40, (future, 18)))
            for index, (field, value) in enumerate(zip(fields, values, strict=True))
        )
        return NumericHistorySource(rows, fields)

    @staticmethod
    def schema(source: NumericHistorySource, *, incremental: bool = False) -> FeatureSchema:
        """Define two explicitly ordered output columns and exact lifecycle semantics."""
        return FeatureSchema(
            implementation="running-mean-v1" if incremental else "named-projection-v1",
            inputs=source.requirements,
            outputs=(
                NumericField(name="activity", units="score"),
                NumericField(name="inventory", units="score"),
            ),
            parameters=(),
            mode="incremental" if incremental else "batch",
            ttl_us=1_000_000,
        )

    @staticmethod
    def policy(entity: str = _ENTITY, confirmations: int = 1) -> ConfirmedSignal:
        """Configure a dimensioned long target, independently of source selection."""
        return ConfirmedSignal(
            field=NumericField(name="activity", units="score"),
            quantity=Quantity(
                value=Decimal("2"),
                dimension=Dimension(
                    instrument_id=InstrumentId.from_canonical_text(entity),
                    kind=QuantityKind.BASE_UNIT,
                ),
            ),
            confirmations=confirmations,
        )

    @classmethod
    def config(
        cls,
        source: NumericHistorySource,
        schema: FeatureSchema,
        policy: ConfirmedSignal,
        *,
        entity: str = _ENTITY,
    ) -> DecisionRun:
        """Select supported components without any authorized account or submission path."""
        return DecisionRun(
            instance="reference",
            entity=entity,
            product="spot",
            calendar="24/7",
            source_identity=source.identity,
            feature_identity=schema.identity,
            policy_identity=policy.identity,
            model_identity=None,
            transform_identity=None,
            output="target",
            decisions=tuple(cls.at(s) for s in (10, 20, 40)),
            required_capabilities=(),
        )

    @classmethod
    def training(cls) -> tuple[tuple[FeatureVector, ...], tuple[Outcome, ...], TemporalSplit]:
        """Bind two training rows and one future validation row to independent outcomes."""
        source = cls.source()
        session = FeatureSession(
            ProjectionFeature(cls.schema(source)), instance="training", entity=_ENTITY
        )
        rows = tuple(session.evaluate(source.read(_ENTITY, cls.at(at))) for at in (10, 20, 40))
        outcomes = tuple(
            Outcome(
                feature_identity=row.identity,
                definition="reference-outcome-v1",
                field=NumericField(name="change", units="score"),
                information_start=row.decision_at,
                information_end=row.decision_at + timedelta(seconds=1),
                available_at=row.decision_at + timedelta(seconds=1),
                value=cls.ratio(value),
                reason="synthetic",
                lineage=(f"independent-outcome:{index}",),
            )
            for index, (row, value) in enumerate(zip(rows, (2, 6, 1000), strict=True))
        )
        split = TemporalSplit(
            training=TimeWindow(start=cls.at(0), end=cls.at(25)),
            validation=TimeWindow(start=cls.at(40), end=cls.at(50)),
            holdout=TimeWindow(start=cls.at(60), end=cls.at(70)),
            samples=tuple(o.sample(r) for r, o in zip(rows, outcomes, strict=True)),
            fit_mode="labels",
            fit_cutoff=cls.at(30),
            embargo_us=0,
            rationale="disjoint independent engineering observations",
        )
        return rows, outcomes, split


class _NormalizeFirst:
    """Exercise a fresh fitted transform that changes width, name and units."""

    @property
    def identity(self) -> str:
        """Pin first-column selection and exact train-mean normalization."""
        return "normalize-first-column-v1"

    def fit(self, rows: tuple[FeatureVector, ...]) -> bytes:
        """Fit the first column mean without seeing any validation values."""
        values = tuple(row.values[0] for row in rows)
        assert all(value is not None for value in values)
        mean = sum(
            (
                Fraction(int(value.numerator), int(value.denominator))
                for value in values
                if value is not None
            ),
            Fraction(),
        ) / len(rows)
        return DomainCodec().encode_json(ExactRatio.from_fraction(mean))

    def output_fields(
        self, state: bytes, fields: tuple[NumericField, ...]
    ) -> tuple[NumericField, ...]:
        """Declare a single dimensionless field and reject an unusable fitted scale."""
        mean = DomainCodec().decode_json(state, ExactRatio)
        if mean.numerator == "0" or not fields:
            raise ValueError("normalization needs a nonzero mean and input signature")
        return (NumericField(name="normalized_level", units="dimensionless"),)

    def apply(self, state: bytes, row: FeatureVector) -> tuple[ExactRatio | None, ...]:
        """Select and normalize one column using saved exact state only."""
        mean = DomainCodec().decode_json(state, ExactRatio)
        value = row.values[0]
        return (
            None
            if value is None
            else ExactRatio.from_fraction(
                Fraction(int(value.numerator), int(value.denominator))
                / Fraction(int(mean.numerator), int(mean.denominator))
            ),
        )


class TestDecisionContracts:
    """Exercise causal input admission, portable state and executable generic composition."""

    def test_served_feature_preserves_origin_and_uses_consuming_clock(self) -> None:
        """Accept exact TTL boundary and reject future/expired values without state advance."""
        source = _Scenario.source()
        features = FeatureSession(
            ProjectionFeature(_Scenario.schema(source)), instance="served", entity=_ENTITY
        )
        vector = features.evaluate(source.read(_ENTITY, _Scenario.at(10)))
        session = DecisionSession(
            _Scenario.policy(), run_identity="served-run", instance="served", entity=_ENTITY
        )
        decision = session.evaluate(
            DecisionContext(features=vector, prediction=None, evaluated_at=_Scenario.at(11))
        )
        assert decision.at == _Scenario.at(11)
        assert decision.feature_identity == vector.identity
        assert vector.decision_at == _Scenario.at(10)
        checkpoint = session.checkpoint()
        for second in (9, 12):
            with pytest.raises(ValueError, match="unavailable or expired"):
                session.evaluate(
                    DecisionContext(
                        features=vector, prediction=None, evaluated_at=_Scenario.at(second)
                    )
                )
        assert session.checkpoint() == checkpoint

    def test_train_only_transform_non_linear_fit_and_reload(self) -> None:
        """Independent means (2,12) and nearest target 6 survive state serialization."""
        rows, outcomes, split = _Scenario.training()
        transform = FittedTransform(CenterColumns())
        fitted = transform.fit(rows, split, available_at=_Scenario.at(30))
        assert transform.training_apply(fitted, rows[0]).values == (
            _Scenario.ratio(-1),
            _Scenario.ratio(-2),
        )
        assert transform.training_apply(fitted, rows[1]).values == (
            _Scenario.ratio(1),
            _Scenario.ratio(2),
        )
        with pytest.raises(ValueError, match="availability"):
            transform.apply(fitted, rows[0])
        model = EstimatorLifecycle(NearestExample())
        version = model.fit(
            rows,
            outcomes,
            split,
            available_at=_Scenario.at(30),
            transform=transform,
            transform_version=fitted,
        )
        codec = DomainCodec()
        restored = codec.decode_json(codec.encode_json(version), EstimatorVersion)
        restored_transform = codec.decode_json(codec.encode_json(fitted), TransformVersion)
        prediction = model.predict(restored, transform.apply(restored_transform, rows[2]))
        assert prediction.value == _Scenario.ratio(6)
        assert version.fit_rows == tuple(r.identity for r in rows[:2])
        changed: tuple[Outcome, ...] = (
            *outcomes[:2],
            replace(outcomes[2], value=_Scenario.ratio(-999999)),
        )
        samples = tuple(o.sample(r) for r, o in zip(rows, changed, strict=True))
        changed_split = replace(split, samples=samples)
        changed_fit = transform.fit(rows, changed_split, available_at=_Scenario.at(30))
        assert changed_fit.state == fitted.state
        assert (
            model.fit(
                rows,
                changed,
                changed_split,
                available_at=_Scenario.at(30),
                transform=transform,
                transform_version=changed_fit,
            ).state
            == version.state
        )
        with pytest.raises(ValueError, match="actual feature/label bytes"):
            model.fit(rows, changed, split, available_at=_Scenario.at(30))
        with pytest.raises(ValueError, match="digest"):
            replace(version, state=version.state + b" ")
        reversed_fields = tuple(reversed(rows[2].fields))
        with pytest.raises(ValueError, match="signature"):
            model.predict(
                restored,
                replace(transform.apply(fitted, rows[2]), fields=reversed_fields),
            )

    def test_fitted_output_schema_can_change_width_and_units(self) -> None:
        """A fresh selector/normalizer produces one dimensionless column with exact value 5/2."""
        rows, outcomes, split = _Scenario.training()
        transform = FittedTransform(_NormalizeFirst())
        fitted = transform.fit(rows, split, available_at=_Scenario.at(30))
        transformed = transform.apply(fitted, rows[2])
        assert transformed.fields == (NumericField(name="normalized_level", units="dimensionless"),)
        assert transformed.values == (ExactRatio(numerator="5", denominator="2"),)
        model = EstimatorLifecycle(NearestExample())
        version = model.fit(
            rows,
            outcomes,
            split,
            available_at=_Scenario.at(30),
            transform=transform,
            transform_version=fitted,
        )
        assert version.signature.fields == fitted.output_fields
        assert model.predict(version, transformed).value == _Scenario.ratio(6)
        changed_fields = (NumericField(name="incorrect", units="score"),)
        wrong = replace(fitted, output_fields=changed_fields)
        with pytest.raises(ValueError, match="output signature"):
            transform.apply(wrong, rows[2])

    def test_learned_predictions_reach_selected_target_policy(self) -> None:
        """The application carries fitted preprocessing and predictions into exact targets."""
        rows, outcomes, split = _Scenario.training()
        source = _Scenario.source()
        schema, policy = _Scenario.schema(source), _Scenario.policy()
        transform, model = FittedTransform(CenterColumns()), EstimatorLifecycle(NearestExample())
        fitted = transform.fit(rows, split, available_at=_Scenario.at(30))
        version = model.fit(
            rows,
            outcomes,
            split,
            available_at=_Scenario.at(30),
            transform=transform,
            transform_version=fitted,
        )
        config = replace(
            _Scenario.config(source, schema, policy),
            decisions=(_Scenario.at(40),),
            model_identity=version.identity,
            transform_identity=fitted.identity,
        )
        result = run_decisions(
            config,
            source=source,
            feature=ProjectionFeature(schema),
            policy=policy,
            capabilities=_CAPABILITIES,
            model=model,
            model_version=version,
            transform=transform,
            transform_version=fitted,
        )
        assert result.predictions[0].value == _Scenario.ratio(6)
        assert isinstance(result.decisions[0].intent, TargetIntent)
        assert result.decisions[0].intent.quantity.value == Decimal("2")
        assert result.decisions[0].model_identity == version.identity

    def test_future_perturbation_restart_and_independent_instances(self) -> None:
        """Means 1,2,3 and target warm-up 0,2,2 survive reload and later input changes."""
        source = _Scenario.source()
        schema = _Scenario.schema(source, incremental=True)
        policy = _Scenario.policy(confirmations=2)
        config = _Scenario.config(source, schema, policy)
        whole = run_decisions(
            config,
            source=source,
            feature=RunningMeanFeature(schema),
            policy=policy,
            capabilities=_CAPABILITIES,
        )
        assert tuple(r.values[0] for r in whole.features) == tuple(
            _Scenario.ratio(v) for v in (1, 2, 3)
        )
        assert tuple(
            r.intent.quantity.value for r in whole.decisions if isinstance(r.intent, TargetIntent)
        ) == (Decimal(0), Decimal(2), Decimal(2))
        assert whole.features[-1].information_start == _Scenario.at(10)
        prefix = run_decisions(
            config,
            source=source,
            feature=RunningMeanFeature(schema),
            policy=policy,
            capabilities=_CAPABILITIES,
            stop_after=1,
        )
        state = DomainCodec().decode_json(
            DomainCodec().encode_json(prefix.checkpoint), DecisionCheckpoint
        )
        resumed = run_decisions(
            config,
            source=source,
            feature=RunningMeanFeature(schema),
            policy=_Scenario.policy(confirmations=2),
            capabilities=_CAPABILITIES,
            checkpoint=state,
        )
        assert prefix.features + resumed.features == whole.features
        assert prefix.decisions + resumed.decisions == whole.decisions
        assert resumed.checkpoint == whole.checkpoint
        changed_source = _Scenario.source(future=-500)
        changed_config = replace(config, source_identity=changed_source.identity)
        changed = run_decisions(
            changed_config,
            source=changed_source,
            feature=RunningMeanFeature(schema),
            policy=policy,
            capabilities=_CAPABILITIES,
        )
        assert changed.features[:2] == whole.features[:2]
        assert changed.decisions[:2] == whole.decisions[:2]
        with pytest.raises(ValueError, match="checkpoint run"):
            run_decisions(
                replace(config, instance="other"),
                source=source,
                feature=RunningMeanFeature(schema),
                policy=policy,
                capabilities=_CAPABILITIES,
                checkpoint=state,
            )
        other = _Scenario.source(entity=_OTHER)
        other_policy = _Scenario.policy(_OTHER, confirmations=2)
        second = run_decisions(
            _Scenario.config(other, schema, other_policy, entity=_OTHER),
            source=other,
            feature=RunningMeanFeature(schema),
            policy=other_policy,
            capabilities=_CAPABILITIES,
        )
        assert isinstance(second.decisions[0].intent, TargetIntent)
        assert second.decisions[0].intent.quantity.value == 0

    def test_unknown_stale_late_revision_and_conflict_semantics(self) -> None:
        """Unknown values remain missing and late revisions change only later cutoffs."""
        source = _Scenario.source()
        requirement = source.requirements[0]
        original = NamedObservation(
            input=requirement,
            entity=_ENTITY,
            event_at=_Scenario.at(10),
            available_at=_Scenario.at(10),
            value=_Scenario.ratio(1),
            reason="observed",
            lineage="original",
        )
        correction = replace(
            original, value=_Scenario.ratio(9), available_at=_Scenario.at(12), lineage="correction"
        )
        history = NumericHistorySource((original, correction), (requirement,))
        assert history.read(_ENTITY, _Scenario.at(11)).observations[0].value == _Scenario.ratio(1)
        assert history.read(_ENTITY, _Scenario.at(12)).observations[0].value == _Scenario.ratio(9)
        assert history.read(_ENTITY, _Scenario.at(15)).observations[0].value == _Scenario.ratio(9)
        assert history.read(_ENTITY, _Scenario.at(16)).observations[0].reason == "stale"
        assert history.read(_OTHER, _Scenario.at(12)).observations[0].value is None
        with pytest.raises(ValueError, match="ambiguous"):
            NumericHistorySource(
                (original, replace(original, value=_Scenario.ratio(5))), (requirement,)
            ).read(_ENTITY, _Scenario.at(10))
        with pytest.raises(ValueError, match="known availability"):
            replace(original, available_at=None)

    def test_feature_failure_leaves_committed_state_and_expiry_explicit(self) -> None:
        """Wrong signatures, corrupt state and repeated clocks cannot advance a session."""
        source = _Scenario.source()
        schema = _Scenario.schema(source, incremental=True)
        session = FeatureSession(RunningMeanFeature(schema), instance="state", entity=_ENTITY)
        row = session.evaluate(source.read(_ENTITY, _Scenario.at(10)))
        checkpoint = session.checkpoint()
        with pytest.raises(ValueError, match="strictly advance"):
            session.evaluate(source.read(_ENTITY, _Scenario.at(10)))
        assert session.checkpoint() == checkpoint
        with pytest.raises(ValueError, match="digest"):
            replace(checkpoint, state=b"{}")
        restored = DomainCodec().decode_json(
            DomainCodec().encode_json(checkpoint), FeatureCheckpoint
        )
        with pytest.raises(ValueError, match="binding"):
            FeatureSession(
                RunningMeanFeature(schema), instance="other", entity=_ENTITY, checkpoint=restored
            )
        row.require_available(_Scenario.at(11))
        with pytest.raises(ValueError, match="expired"):
            row.require_available(_Scenario.at(12))

    def test_generic_labels_remain_separate_and_pending(self) -> None:
        """A non-return label uses a frozen base and becomes knowable only at its own cutoff."""
        source = _Scenario.source()
        base = source.read(_ENTITY, _Scenario.at(10))
        row = FeatureSession(
            ProjectionFeature(_Scenario.schema(source)), instance="label", entity=_ENTITY
        ).evaluate(base)
        future = source.read(_ENTITY, _Scenario.at(20)).observations[0]
        label = NumericDifference()
        pending = label.evaluate(row, base.observations[0], future, observed_at=_Scenario.at(19))
        assert pending.value is None and pending.available_at is None
        known = label.evaluate(row, base.observations[0], future, observed_at=_Scenario.at(20))
        assert known.value == _Scenario.ratio(2)
        assert known.sample(row).information_end == _Scenario.at(20)
        assert row.values[0] == _Scenario.ratio(1)
        later = replace(future, event_at=_Scenario.at(21), available_at=_Scenario.at(21))
        other_horizon = label.evaluate(
            row, base.observations[0], later, observed_at=_Scenario.at(21)
        )
        assert other_horizon.definition != known.definition

    def test_no_trade_control_and_unsupported_calendar(self) -> None:
        """An all-zero input stays flat and an unqualified calendar fails admission."""
        original = _Scenario.source()
        rows = tuple(
            NamedObservation(
                input=requirement,
                entity=_ENTITY,
                event_at=_Scenario.at(at),
                available_at=_Scenario.at(at),
                value=_Scenario.ratio(0),
                reason="no_trade_control",
                lineage=f"zero:{index}:{at}",
            )
            for at in (10, 20, 40)
            for index, requirement in enumerate(original.requirements)
        )
        source = NumericHistorySource(rows, original.requirements)
        schema, policy = _Scenario.schema(source), _Scenario.policy()
        config = _Scenario.config(source, schema, policy)
        result = run_decisions(
            config,
            source=source,
            feature=ProjectionFeature(schema),
            policy=policy,
            capabilities=_CAPABILITIES,
        )
        assert all(
            isinstance(r.intent, TargetIntent) and r.intent.quantity.value == 0
            for r in result.decisions
        )
        with pytest.raises(ValueError, match="calendar:XNYS"):
            run_decisions(
                replace(config, calendar="XNYS"),
                source=source,
                feature=ProjectionFeature(schema),
                policy=policy,
                capabilities=_CAPABILITIES,
            )

    def test_late_training_label_never_reaches_estimator(self) -> None:
        """Exclude a late training label while preserving the earlier admitted sample."""
        rows, outcomes, split = _Scenario.training()
        late = replace(outcomes[1], information_end=_Scenario.at(31), available_at=_Scenario.at(31))
        labels = (outcomes[0], late, outcomes[2])
        samples = tuple(o.sample(r) for r, o in zip(rows, labels, strict=True))
        selected = replace(split, samples=samples)
        model = EstimatorLifecycle(NearestExample())
        version = model.fit(rows, labels, selected, available_at=_Scenario.at(30))
        assert version.fit_rows == (rows[0].identity,)
        assert model.predict(version, rows[2]).value == _Scenario.ratio(2)

    def test_retained_attempts_and_capability_refusal(self, tmp_path: Path) -> None:
        """Reopen typed results and retain a failed unsupported-product attempt."""
        source = _Scenario.source()
        schema, policy = _Scenario.schema(source), _Scenario.policy()
        config = _Scenario.config(source, schema, policy)
        history = inspect_decisions(
            config,
            source=source,
            feature=ProjectionFeature(schema),
            policy=policy,
            capabilities=_CAPABILITIES,
            attempts=tmp_path,
            family="decision-reference",
        )
        assert history.status == "completed"
        result = history.events[-1].result
        assert result is not None
        reopened = DomainCodec().decode_json(result, DecisionResult)
        assert len(reopened.decisions) == 3
        with pytest.raises(ValueError, match="product:future"):
            inspect_decisions(
                replace(config, product="future"),
                source=source,
                feature=ProjectionFeature(schema),
                policy=policy,
                capabilities=_CAPABILITIES,
                attempts=tmp_path,
                family="decision-reference",
            )
        assert sorted(h.status for h in AttemptStore(tmp_path).histories()) == [
            "completed",
            "failed",
        ]
