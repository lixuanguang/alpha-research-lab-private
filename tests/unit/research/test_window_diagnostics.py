"""Prove window diagnostics with independent CDF, exact error and availability examples."""

from __future__ import annotations

# standard library imports
import hashlib
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from applications.explore import compare_windows
from financial_units import ExactRatio
from reference_data.instruments import InstrumentId
from research.experiments import (
    AttemptStore,
    ClearMLDestination,
    ClearMLPublication,
    DiagnosticSource,
    EvaluationRecord,
    FeatureLabelPayload,
    SampleInterval,
    TemporalSplit,
    TimeWindow,
    WindowDiagnosticReport,
    WindowDiagnostics,
    WindowDiagnosticStudy,
)
from research.features import FeatureValue, PriceWindow, TrailingReturn, WindowPolicy
from research.labels import ForwardReturn, LabelValue
from serialization import DomainCodec

_START = datetime(2024, 1, 1, tzinfo=UTC)
_CODEC = DomainCodec()


class TestWindowDiagnostics:
    """Use disjoint shifted supports, an identical control and unit squared errors."""

    @staticmethod
    def _ratio(value: int) -> ExactRatio:
        """Encode the hand-authored integer example without floating point."""
        return ExactRatio(numerator=str(value), denominator="1")

    @staticmethod
    def _window(start: int, end: int) -> TimeWindow:
        """Create explicit half-open UTC windows in minutes from the fixture epoch."""
        return TimeWindow(
            start=_START + timedelta(minutes=start), end=_START + timedelta(minutes=end)
        )

    @classmethod
    def _fixture(cls) -> tuple[WindowDiagnosticStudy, FeatureLabelPayload, EvaluationRecord]:
        """Build retained records with 10 observations per instrument and per window."""
        policy = WindowPolicy(lookback_us=60_000_000, min_trades=2, max_staleness_us=60_000_000)
        feature_definition = TrailingReturn(
            policy=policy, cadence_us=60_000_000, processing_delay_us=0
        )
        label_definition = ForwardReturn(
            policy=policy, horizon_us=60_000_000, availability_delay_us=60_000_000
        )
        features: list[tuple[str, FeatureValue]] = []
        labels: list[tuple[str, LabelValue]] = []
        samples: list[SampleInterval] = []
        predictions: list[tuple[str, str, ExactRatio, ExactRatio, datetime]] = []
        excluded: list[tuple[str, str]] = []
        for current in (False, True):
            for index in range(10):
                decision = _START + timedelta(minutes=1 + index + (20 if current else 0))
                for entity in (1, 2):
                    row_id = f"{current}-{index}-{entity}"
                    instrument = InstrumentId.from_canonical_text(
                        f"{entity}" * 8
                        + f"-{entity}"
                        + f"{entity}" * 3
                        + f"-4{entity}{entity}{entity}-8{entity}{entity}{entity}-"
                        + f"{entity}" * 12
                    )
                    value = cls._ratio(index + (100 if current and entity == 1 else 0))
                    window = PriceWindow(
                        query_identity="b" * 64,
                        binding=("synthetic", "trade", instrument),
                        start=decision - timedelta(minutes=1),
                        end=decision,
                        known_at=decision,
                        points=(),
                        missing=None,
                        evidence=(),
                        controls=(),
                    )
                    feature = FeatureValue(
                        feature_definition.identity, decision, decision, window, value
                    )
                    missing = index == 4 and entity == 2
                    available = None if missing else decision + timedelta(minutes=2)
                    outcome = None if missing else cls._ratio(int(value.numerator) - 1)
                    label = LabelValue(
                        label_definition.identity,
                        decision,
                        decision + timedelta(minutes=1),
                        window.start,
                        decision + timedelta(minutes=1),
                        available,
                        None,
                        "missing source outcome" if missing else None,
                        outcome,
                    )
                    features.append((row_id, feature))
                    labels.append((row_id, label))
                    samples.append(
                        SampleInterval(
                            row_id=row_id,
                            input_sha256=hashlib.sha256(
                                _CODEC.encode_json((feature, label))
                            ).hexdigest(),
                            decision_at=decision,
                            information_start=label.information_start,
                            information_end=label.information_end,
                            features_available_at=decision,
                            label_available_at=available,
                        )
                    )
                    if outcome is not None and available is not None:
                        predictions.append((row_id, "f" * 64, value, outcome, available))
                    else:
                        excluded.append((row_id, "missing retained outcome"))
        split = TemporalSplit(
            training=None,
            validation=cls._window(0, 40),
            holdout=cls._window(60, 80),
            samples=(),
            fit_mode="none",
            fit_cutoff=None,
            embargo_us=0,
            rationale="Fixed diagnostic, disjoint untouched holdout",
        )
        payload = FeatureLabelPayload(
            schema_version="feature-study-result-v1",
            selection_identity="a" * 64,
            feature_definition=feature_definition,
            label_definition=label_definition,
            features=tuple(features),
            labels=tuple(labels),
            samples=tuple(samples),
            split_identity=split.identity,
            fitting="not applicable: configured fixture",
            scope="exploratory_degraded",
        )
        evaluation = EvaluationRecord(
            dataset_sha256="d" * 64,
            split_identity=split.identity,
            window=split.validation,
            partition="validation",
            evaluated_as_of=_START + timedelta(minutes=40),
            predictions=tuple(predictions),
            excluded=tuple(excluded),
            mean_squared_error=cls._ratio(1),
            selection="accepted",
            reason="Known unit error",
        )
        study = WindowDiagnosticStudy(
            family="window-diagnostics",
            features=(
                DiagnosticSource(
                    attempt_id="a" * 32,
                    sha256=hashlib.sha256(_CODEC.encode_json(payload)).hexdigest(),
                ),
            ),
            predictions=(
                DiagnosticSource(
                    attempt_id="b" * 32,
                    sha256=hashlib.sha256(_CODEC.encode_json(evaluation)).hexdigest(),
                ),
            ),
            split=split,
            reference=cls._window(0, 11),
            current=cls._window(20, 31),
            evaluated_as_of=_START + timedelta(minutes=31),
            min_observations=5,
            ks_statistic_threshold=0.5,
            ks_pvalue_threshold=0.01,
            predictive_metric="mse",
            predictive_reason="Same retained dimensionless target",
            max_mse=cls._ratio(1),
            threshold_reason="Frozen hand-example software policy",
        )
        return study, payload, evaluation

    def test_known_shift_and_identical_control(self) -> None:
        """Check D=1 and p=2/binomial(20,10), versus exactly D=0 and p=1."""
        study, payload, evaluation = self._fixture()
        report = WindowDiagnostics().evaluate(study, (payload,), (evaluation,))
        shifted, control = [row for row in report.distributions if row.field == "feature"]
        assert shifted.statistic == 1.0 and shifted.drift is True
        assert shifted.pvalue == pytest.approx(2 / math.comb(20, 10), abs=1e-15)
        assert control.statistic == 0.0 and control.pvalue == 1.0 and control.drift is False
        assert dict(report.versions)["scipy"] == "1.18.1"
        assert b"Repository report computed with SciPy" in report.html_bytes()
        assert report == _CODEC.decode_json(_CODEC.encode_json(report), WindowDiagnosticReport)
        assert _CODEC.encode_json(report) == _CODEC.encode_json(
            WindowDiagnostics().evaluate(study, (payload,), (evaluation,))
        )

    def test_missing_and_later_labels_leave_feature_drift_unchanged(self) -> None:
        """Admit the last delayed labels at equality while preserving permanent missingness."""
        study, payload, evaluation = self._fixture()
        earlier = WindowDiagnostics().evaluate(study, (payload,), (evaluation,))
        later = WindowDiagnostics().evaluate(
            replace(study, evaluated_as_of=_START + timedelta(minutes=32)),
            (payload,),
            (evaluation,),
        )
        assert earlier.distributions == later.distributions
        assert sum(row.count for row in later.predictive) == 38
        assert sum(row.count for row in earlier.predictive) == 36
        assert sum(row.label_reason is not None for row in later.observations) == 2
        assert all(row.mean_squared_error == self._ratio(1) for row in later.predictive)
        assert all(row.threshold_exceeded is False for row in later.predictive)
        assert earlier.study.split == later.study.split

    def test_predictive_inapplicability_does_not_disable_feature_diagnostics(self) -> None:
        """Retain a rule-only reason without inventing model state or zero error."""
        study, payload, _ = self._fixture()
        study = replace(
            study,
            predictions=(),
            predictive_metric="inapplicable",
            max_mse=None,
            predictive_reason="Rule-only study has no predictive target",
        )
        report = WindowDiagnostics().evaluate(study, (payload,), ())
        assert report.distributions[0].drift is True
        assert all(
            row.mean_squared_error is None and row.inapplicable_reason == study.predictive_reason
            for row in report.predictive
        )

    def test_no_available_labels_and_excluded_window_rows_are_explicit(self) -> None:
        """Withhold all error metrics at an early cutoff while retaining excluded observations."""
        study, payload, evaluation = self._fixture()
        study = replace(
            study,
            reference=self._window(0, 2),
            current=self._window(2, 3),
            evaluated_as_of=_START + timedelta(minutes=3),
            min_observations=2,
        )
        report = WindowDiagnostics().evaluate(study, (payload,), (evaluation,))
        assert sum(row.window == "excluded" for row in report.observations) == 36
        assert all(row.inapplicable_reason is not None for row in report.distributions)
        assert all(
            row.mean_squared_error is None for row in report.predictive if row.window == "current"
        )

    def test_reject_changed_splits_duplicate_rows_and_mismatched_outcomes(self) -> None:
        """Refuse temporal leakage, duplicate sources and falsely attributed predictions."""
        study, payload, evaluation = self._fixture()
        with pytest.raises(ValueError, match="holdout"):
            replace(study, evaluated_as_of=study.split.holdout.start)
        with pytest.raises(ValueError, match="unique feature"):
            WindowDiagnostics().evaluate(
                replace(
                    study,
                    features=(study.features[0], replace(study.features[0], attempt_id="c" * 32)),
                ),
                (payload, payload),
                (evaluation,),
            )
        first = evaluation.predictions[0]
        changed: tuple[str, str, ExactRatio, ExactRatio, datetime] = (
            first[0],
            first[1],
            self._ratio(2),
            self._ratio(1),
            first[4],
        )
        changed_predictions = (changed, *evaluation.predictions[1:])
        wrong = replace(evaluation, predictions=changed_predictions)
        with pytest.raises(ValueError, match="outcome differs"):
            WindowDiagnostics().evaluate(study, (payload,), (wrong,))

    def test_retained_failure_retry_and_source_tampering(self, tmp_path: Path) -> None:
        """Preserve failed inputs and reject tampered saved bytes without holdout reads."""
        study, payload, _ = self._fixture()
        destination = ClearMLDestination(
            project="diagnostic-fixture",
            api_uri="http://127.0.0.1:18008",
            files_uri="http://127.0.0.1:18081",
        )
        with AttemptStore(tmp_path) as store:
            source = store.start(
                study.specification(implementation="a" * 64, environment="b" * 64),
                at=_START,
                invocation="synthetic fixture",
                request=b"synthetic",
            )
            store.finish(
                source.attempt_id,
                status="completed",
                at=_START,
                reason="Synthetic retained numeric inputs",
                result=_CODEC.encode_json(payload),
            )
        study = replace(
            study,
            features=(replace(study.features[0], attempt_id=source.attempt_id),),
            predictions=(),
            predictive_metric="inapplicable",
            max_mse=None,
        )
        with patch.object(
            WindowDiagnostics, "evaluate", side_effect=ArithmeticError("injected computation")
        ):
            with pytest.raises(ArithmeticError, match="injected"):
                compare_windows(study, attempts=tmp_path, tracking=destination)
        with AttemptStore(tmp_path) as store:
            failed = next(history for history in store.histories() if history.status == "failed")
            assert store.artifact(
                failed.start.attempt_id, "feature-source-0"
            ) == _CODEC.encode_json(payload)
        with patch.object(
            ClearMLPublication, "_publish", side_effect=ConnectionError("offline transport")
        ):
            with pytest.raises(ConnectionError):
                compare_windows(study, attempts=tmp_path, tracking=destination)
        with AttemptStore(tmp_path) as store:
            assert store.read(failed.start.attempt_id) == failed
            completed = [
                h
                for h in store.histories()
                if h.status == "completed" and h.start.attempt_id != source.attempt_id
            ]
            assert len(completed) == 1
            assert "window-report-html" in store.artifacts(completed[0].start.attempt_id)
            assert any(
                name.startswith("clearml-failure-")
                for name in store.artifacts(completed[0].start.attempt_id)
            )
        bad = replace(study, features=(replace(study.features[0], sha256="0" * 64),))
        with pytest.raises(ValueError, match="digest mismatch"):
            compare_windows(bad, attempts=tmp_path, tracking=destination)
        assert all(
            not any(e.status == "holdout_consumed" for e in h.events)
            for h in AttemptStore(tmp_path).histories()
        )
