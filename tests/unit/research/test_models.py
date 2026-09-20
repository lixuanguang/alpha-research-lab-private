"""Prove model arithmetic and temporal boundaries with independent hand-calculated examples."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

# third party library imports
import pandas as pd
import pytest
from msgspec.structs import force_setattr, replace
from pandera.errors import SchemaError, SchemaErrors

# project library imports
from applications.explore import evaluate_model, publish_experiments
from financial_units import ExactRatio
from research.experiments import (
    AttemptStore,
    ClearMLDestination,
    ClearMLPublication,
    SampleInterval,
    TemporalSplit,
    TimeWindow,
)
from research.models import (
    LinearDefinition,
    LinearModel,
    ModelDataset,
    ModelFrame,
    ModelRow,
    ModelSignature,
    ModelStudy,
    ModelVersion,
    RetainedResult,
)
from serialization import DomainCodec

_START = datetime(2024, 6, 1, tzinfo=UTC)
_CODEC = DomainCodec()


class TestModels:
    """Use y = 2x + 1 with nonzero fitted centering and a deliberately imperfect outcome."""

    @staticmethod
    def _ratio(value: int) -> ExactRatio:
        """Encode independent integer examples exactly."""
        return ExactRatio.from_fraction(Fraction(value))

    @classmethod
    def _row(cls, name: str, hour: int, x: int, y: int) -> ModelRow:
        """Bind one feature and delayed outcome to an independently authored interval."""
        return ModelRow(
            sample=SampleInterval(
                row_id=name,
                input_sha256=hashlib.sha256(name.encode()).hexdigest(),
                decision_at=_START + timedelta(hours=hour),
                information_start=_START + timedelta(hours=hour),
                information_end=_START + timedelta(hours=hour, minutes=30),
                features_available_at=_START + timedelta(hours=hour),
                label_available_at=_START + timedelta(hours=hour + 1),
            ),
            feature=cls._ratio(x),
            label=cls._ratio(y),
        )

    @classmethod
    def _dataset(cls) -> ModelDataset:
        """Declare three training points and separate validation/holdout/future values."""
        return ModelDataset(
            signature=ModelSignature(feature_identity="a" * 64, label_identity="b" * 64),
            sources=("c" * 64,),
            rows=(
                cls._row("train-a", 1, 1, 3),
                cls._row("train-b", 3, 2, 5),
                cls._row("train-c", 5, 3, 7),
                cls._row("validation", 12, 4, 10),
                cls._row("holdout", 21, 1000, -500),
                cls._row("future", 30, 9999, -9999),
            ),
        )

    @staticmethod
    def _split(dataset: ModelDataset) -> TemporalSplit:
        """Use a fold with a material gap, independent of model implementation."""
        return TemporalSplit(
            training=TimeWindow(start=_START, end=_START + timedelta(hours=8)),
            validation=TimeWindow(
                start=_START + timedelta(hours=10), end=_START + timedelta(hours=15)
            ),
            holdout=TimeWindow(
                start=_START + timedelta(hours=20), end=_START + timedelta(hours=25)
            ),
            samples=tuple(row.sample for row in dataset.rows),
            fit_mode="labels",
            fit_cutoff=_START + timedelta(hours=9),
            embargo_us=0,
            rationale="Disjoint synthetic information windows with an explicit gap.",
        )

    @classmethod
    def _fit(cls, dataset: ModelDataset) -> ModelVersion:
        """Exercise public construction with one exact permitted training fold."""
        return LinearModel.construct(
            LinearDefinition(mode="least-squares", assumptions="One-feature predictive example"),
            dataset,
            cls._split(dataset),
            attempt_id="d" * 32,
            created_at=_START + timedelta(days=100),
            available_at=_START + timedelta(hours=10),
        )

    def test_hand_calculated_fit_reload_and_error(self) -> None:
        """Recover y=2x+1 exactly after JSON reload; the validation squared error is one."""
        dataset = self._dataset()
        model = self._fit(dataset)
        reloaded = _CODEC.decode_json(_CODEC.encode_json(model), ModelVersion)
        assert reloaded.fit_rows == ("train-a", "train-b", "train-c")
        assert reloaded.predict(dataset.rows[3], dataset.signature) == self._ratio(9)
        report = LinearModel.evaluate(
            (reloaded,),
            dataset,
            self._split(dataset),
            partition="validation",
            known_at=_START + timedelta(hours=15),
            max_mse=self._ratio(0),
            reason="Require zero synthetic error",
        )
        assert report.mean_squared_error == self._ratio(1)
        assert report.selection == "rejected"
        assert report.predictions[0][1] == model.identity
        with pytest.raises(ValueError, match="differs from retained"):
            replace(report, mean_squared_error=self._ratio(0))
        with pytest.raises(ValueError, match="unique"):
            replace(report, predictions=report.predictions * 2)

    def test_future_and_held_out_values_cannot_change_fitted_state(self) -> None:
        """Perturb every nontraining value while preserving the permitted training rows."""
        original = self._dataset()
        changed = replace(
            original,
            rows=original.rows[:3]
            + tuple(
                replace(row, feature=self._ratio(-99999), label=self._ratio(88888))
                for row in original.rows[3:]
            ),
        )
        before, after = self._fit(original), self._fit(changed)
        assert before.state_bytes == after.state_bytes
        assert before.fit_input_sha256 == after.fit_input_sha256
        assert before.identity == after.identity

    def test_late_label_cannot_change_center_or_slope(self) -> None:
        """Exclude a corrupted training label that becomes available after cutoff."""
        dataset = self._dataset()
        row: ModelRow = replace(
            dataset.rows[2],
            label=self._ratio(99999),
            sample=replace(dataset.rows[2].sample, label_available_at=_START + timedelta(hours=10)),
        )
        changed_rows: tuple[ModelRow, ...] = (*dataset.rows[:2], row, *dataset.rows[3:])
        changed = replace(dataset, rows=changed_rows)
        model = self._fit(changed)
        assert model.fit_rows == ("train-a", "train-b")
        assert model.predict(changed.rows[3], changed.signature) == self._ratio(9)

    def test_missing_and_singular_training_fail_without_model_state(self) -> None:
        """Refuse imputation and an underidentified statistical construction."""
        dataset = self._dataset()
        missing: ModelRow = replace(dataset.rows[0], feature=None)
        with pytest.raises(ValueError, match="no imputation"):
            missing_rows: tuple[ModelRow, ...] = (missing, *dataset.rows[1:])
            self._fit(replace(dataset, rows=missing_rows))
        constant_rows = tuple(self._constant_feature(row) for row in dataset.rows)
        with pytest.raises(ValueError, match="zero variance"):
            self._fit(replace(dataset, rows=constant_rows))

    @classmethod
    def _constant_feature(cls, row: ModelRow) -> ModelRow:
        """Construct a typed singular-design example."""
        return replace(row, feature=cls._ratio(1))

    def test_configured_model_has_no_invented_fit(self) -> None:
        """Run an explicitly configured analytical model without training clocks."""
        dataset = self._dataset()
        split = replace(self._split(dataset), fit_mode="none", training=None, fit_cutoff=None)
        model = LinearModel.construct(
            LinearDefinition(
                mode="configured",
                assumptions="fixed y=1+2x",
                intercept=self._ratio(1),
                slope=self._ratio(2),
            ),
            dataset,
            split,
            attempt_id="e" * 32,
            created_at=_START,
            available_at=_START,
        )
        assert model.fit_rows == () and model.fit_cutoff is None and model.training is None
        assert model.predict(dataset.rows[3], dataset.signature) == self._ratio(9)

    def test_incompatible_and_tampered_state_fail_closed(self) -> None:
        """Reject wrong definitions, order, units, unavailable state and mutated bytes."""
        dataset = self._dataset()
        model = self._fit(dataset)
        with pytest.raises(ValueError, match="incompatible"):
            model.predict(dataset.rows[3], replace(dataset.signature, feature_identity="f" * 64))
        with pytest.raises(ValueError, match="unavailable"):
            model.predict(dataset.rows[0], dataset.signature)
        with pytest.raises(ValueError, match="order, units"):
            replace(dataset.signature, feature_order=("other", "trailing_return"))
        signature = replace(dataset.signature)
        force_setattr(signature, "units", "USD")
        with pytest.raises(ValueError, match="units"):
            signature.__post_init__()
        force_setattr(model, "state_bytes", bytearray(model.state_bytes))
        with pytest.raises(TypeError, match="immutable"):
            model.predict(dataset.rows[3], dataset.signature)
        force_setattr(model, "state_bytes", b"{}")
        with pytest.raises(ValueError, match="digest"):
            model.predict(dataset.rows[3], dataset.signature)

    def test_walk_forward_never_uses_final_full_history_state(self) -> None:
        """A future refit cannot replace the earlier available model at validation decisions."""
        dataset = self._dataset()
        earlier = self._fit(dataset)
        later = replace(
            earlier, available_at=_START + timedelta(hours=30), creation_attempt="f" * 32
        )
        report = LinearModel.evaluate(
            (later, earlier),
            dataset,
            self._split(dataset),
            partition="validation",
            known_at=_START + timedelta(hours=15),
            max_mse=self._ratio(1),
            reason="fixed threshold",
        )
        assert report.predictions[0][1] == earlier.identity
        with pytest.raises(ValueError, match="no model was available"):
            LinearModel.evaluate(
                (later,),
                dataset,
                self._split(dataset),
                partition="validation",
                known_at=_START + timedelta(hours=15),
                max_mse=self._ratio(1),
                reason="fixed threshold",
            )

    def test_evaluation_excludes_unknown_and_late_outcomes(self) -> None:
        """Do not score an outcome before the declared availability cutoff."""
        dataset = self._dataset()
        with pytest.raises(ValueError, match="no available complete outcomes"):
            LinearModel.evaluate(
                (self._fit(dataset),),
                dataset,
                self._split(dataset),
                partition="validation",
                known_at=_START + timedelta(hours=12),
                max_mse=self._ratio(1),
                reason="fixed threshold",
            )

    def test_pandera_rejects_malformed_without_coercion(self) -> None:
        """Keep exact large ratios and reject missing identity, naive clocks, floats and order."""
        boundary = ModelFrame()
        boundary.from_rows(self._dataset().rows)
        columns = [
            "row_id",
            "decision_at",
            "features_available_at",
            "label_available_at",
            "units",
            "trailing_return",
            "forward_return",
        ]
        values: list[object] = [
            "row",
            _START,
            _START,
            None,
            "dimensionless",
            self._ratio(10**100),
            None,
        ]
        boundary.validate(pd.DataFrame([values], columns=columns, dtype=object))
        for index, invalid in (
            (0, None),
            (1, datetime(2024, 1, 1)),
            (4, "USD"),
            (5, 0.1),
            (5, float("nan")),
            (3, pd.NaT),
        ):
            malformed = values.copy()
            malformed[index] = invalid
            with pytest.raises((SchemaError, SchemaErrors)):
                boundary.validate(pd.DataFrame([malformed], columns=columns, dtype=object))
        with pytest.raises((SchemaError, SchemaErrors)):
            boundary.validate(pd.DataFrame([values], columns=list(reversed(columns)), dtype=object))
        with pytest.raises((SchemaError, SchemaErrors)):
            boundary.validate(pd.DataFrame([values[:-1]], columns=columns[:-1], dtype=object))
        with pytest.raises((SchemaError, SchemaErrors)):
            boundary.validate(
                pd.DataFrame([[*values, None]], columns=[*columns, "forward_return"], dtype=object)
            )

    def test_failed_holdout_read_and_publication_retry_preserve_consumption(
        self, tmp_path: Path
    ) -> None:
        """Retain failed holdout access and reject a changed semantic rerun."""
        dataset = self._dataset()
        study = ModelStudy(
            family="holdout-consumption",
            question="No source can be read",
            sources=(RetainedResult(attempt_id="a" * 32, sha256="b" * 64),),
            split=replace(self._split(dataset), training=None, fit_cutoff=None, fit_mode="none"),
            partition="holdout",
            known_at=_START + timedelta(hours=26),
            max_mse=self._ratio(1),
            selection_reason="Authored final access",
            available_at=_START,
            definition=LinearDefinition(
                mode="configured",
                assumptions="Fixed no-fit comparator",
                intercept=self._ratio(0),
                slope=self._ratio(0),
            ),
        )
        config, root = tmp_path / "study.json", tmp_path / "attempts"
        config.write_bytes(_CODEC.encode_json(study))
        destination = ClearMLDestination(
            project="unit", api_uri="http://127.0.0.1:18008", files_uri="http://127.0.0.1:18081"
        )
        with patch.object(ClearMLPublication, "publish", side_effect=ConnectionError("offline")):
            with pytest.raises(ConnectionError, match="offline"):
                evaluate_model(config, attempts=root, tracking=destination)
            store = AttemptStore(root)
            before = store.histories()
            assert len(before) == 1 and before[0].status == "failed"
            assert before[0].events[0].status == "holdout_consumed"
            with pytest.raises(ConnectionError, match="offline"):
                publish_experiments(root)
            assert store.histories() == before
            config.write_bytes(
                _CODEC.encode_json(replace(study, question="Changed semantic choice"))
            )
            with patch.object(ModelStudy, "dataset", side_effect=AssertionError("forbidden read")):
                with pytest.raises(ConnectionError, match="offline"):
                    evaluate_model(config, attempts=root, tracking=destination)
            rejected = tuple(h for h in store.histories() if h.status == "rejected")
            assert len(rejected) == 1
            assert "holdout already consumed" in rejected[0].events[-1].reason
            assert store.read(before[0].start.attempt_id) == before[0]
