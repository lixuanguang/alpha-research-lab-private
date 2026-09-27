"""Verify the launch capacity and exact upper bounds for retained study inputs."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from financial_units import ExactRatio
from market_data.query import InputBinding
from reference_data.instruments import InstrumentId
from research.experiments import SampleInterval, TemporalSplit, TimeWindow
from research.exploration import EdaQuery, FeatureStudy, ResearchSelection, TradeSelection
from research.features import FeatureValue, PriceWindow, TrailingReturn, WindowPolicy
from research.results import FeatureStudyResult
from research.studies.decision_studies import StudyFold
from research.studies.reports import BenchmarkPeriod, ReportPolicy


class TestResearchCapacityBounds:
    """Keep requested launch sizes valid while retaining explicit per-object ceilings."""

    start = datetime(2026, 9, 27, tzinfo=UTC)

    @classmethod
    def _split(cls, *, schedule_size: int, training_size: int = 0) -> TemporalSplit:
        """Create a no-fit or feature-fit split that contains the requested schedules."""
        if training_size:
            training_end = cls.start + timedelta(minutes=training_size)
            validation_start = training_end
            training = TimeWindow(start=cls.start, end=training_end)
            fit_cutoff = training_end
            fit_mode: Literal["features", "none"] = "features"
        else:
            validation_start = cls.start
            training = None
            fit_cutoff = None
            fit_mode = "none"
        validation_end = validation_start + timedelta(minutes=schedule_size + 1)
        return TemporalSplit(
            training=training,
            fit_cutoff=fit_cutoff,
            fit_mode=fit_mode,
            samples=(),
            embargo_us=0,
            rationale="Capacity fixture has no external or fitted inputs",
            validation=TimeWindow(start=validation_start, end=validation_end),
            holdout=TimeWindow(
                start=validation_end + timedelta(minutes=1),
                end=validation_end + timedelta(days=1),
            ),
        )

    @classmethod
    def _fold(cls, *, decision_count: int, training_count: int = 0) -> StudyFold:
        """Build one valid fold with independently sized training and evaluation schedules."""
        split = cls._split(schedule_size=decision_count, training_size=training_count)
        decision_start = split.validation.start
        decisions = tuple(
            decision_start + timedelta(minutes=index) for index in range(decision_count)
        )
        training_decisions = tuple(
            cls.start + timedelta(minutes=index) for index in range(training_count)
        )
        return StudyFold(
            name="capacity",
            split=split,
            training_decisions=training_decisions,
            decisions=decisions,
            evaluated_as_of=decisions[-1],
        )

    @classmethod
    def _report_policy(cls, *, period_count: int) -> ReportPolicy:
        """Build consecutive exact one-minute benchmark periods."""
        zero = ExactRatio(numerator="0", denominator="1")
        benchmark = tuple(
            BenchmarkPeriod(
                end=cls.start + timedelta(minutes=index),
                value=zero,
            )
            for index in range(period_count)
        )
        return ReportPolicy(
            benchmark_name="capacity",
            benchmark=benchmark,
            cadence_seconds=60,
            periods_per_year=525_600,
            annual_risk_free=zero,
        )

    @classmethod
    def _feature_definition(cls) -> TrailingReturn:
        """Declare one-minute decisions over a one-minute observed-price lookback."""
        return TrailingReturn(
            policy=WindowPolicy(
                lookback_us=60_000_000,
                min_trades=2,
                max_staleness_us=60_000_000,
            ),
            cadence_us=60_000_000,
            processing_delay_us=0,
        )

    @classmethod
    def _feature_study(cls, *, decision_count: int) -> FeatureStudy:
        """Build a valid feature grid over two independently bound instruments."""
        instrument_a = InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111")
        instrument_b = InstrumentId.from_canonical_text("22222222-2222-4222-8222-222222222222")
        bindings = (
            ("venue", "stream", instrument_a),
            ("venue", "stream", instrument_b),
        )
        decision_start = cls.start + timedelta(minutes=1)
        decision_end = decision_start + timedelta(minutes=decision_count)
        query = EdaQuery(
            snapshot_id="e" * 64,
            precedence=bindings,
            instruments=(instrument_a, instrument_b),
            start=cls.start,
            end=decision_end,
            known_at=decision_end,
            columns=("revision",),
            mode="cutoff",
            batch_size=1,
            max_bytes=262_144,
        )
        return FeatureStudy(
            family="capacity",
            question="Retain every minute for each configured instrument",
            selection=ResearchSelection(inputs=(TradeSelection(name="prices", query=query),)),
            split=TemporalSplit(
                training=None,
                fit_cutoff=None,
                fit_mode="none",
                samples=(),
                embargo_us=0,
                rationale="The diagnostic has no fitted state",
                validation=TimeWindow(start=cls.start, end=decision_end),
                holdout=TimeWindow(
                    start=decision_end + timedelta(minutes=1),
                    end=decision_end + timedelta(days=1),
                ),
            ),
            partition="validation",
            decisions=TimeWindow(start=decision_start, end=decision_end),
            feature=cls._feature_definition(),
            label=None,
        )

    @classmethod
    def _feature_result(cls, *, row_count: int) -> FeatureStudyResult:
        """Construct aligned feature and sample tuples without optional labels."""
        definition = cls._feature_definition()
        definition_identity = definition.identity
        binding: InputBinding = (
            "venue",
            "stream",
            InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
        )
        window = PriceWindow(
            "c" * 64,
            binding,
            cls.start,
            cls.start + timedelta(minutes=1),
            cls.start + timedelta(minutes=1),
            (),
            None,
            (),
            (),
        )
        features = tuple(
            (
                str(index),
                FeatureValue(
                    definition_identity,
                    at := cls.start + timedelta(minutes=index),
                    at,
                    window,
                    None,
                ),
            )
            for index in range(row_count)
        )
        samples = tuple(
            SampleInterval(
                row_id=str(index),
                input_sha256="d" * 64,
                decision_at=(at := cls.start + timedelta(minutes=index)),
                information_start=at - timedelta(minutes=1),
                information_end=at,
                features_available_at=at,
                label_available_at=None,
            )
            for index in range(row_count)
        )
        return FeatureStudyResult(
            schema_version="feature-study-result-v1",
            selection_identity="a" * 64,
            feature_definition=definition,
            label_definition=None,
            features=features,
            labels=(),
            samples=samples,
            split_identity="b" * 64,
            fitting="not applicable: fixed diagnostic has no fitted state",
            scope="exploratory_degraded",
        )

    def test_study_fold_schedules_accept_launch_size_and_stop_at_8192(self) -> None:
        """Apply the per-schedule bound independently to training and decisions."""
        launch = self._fold(decision_count=4320)
        assert len(launch.decisions) == 4320
        assert len(self._fold(decision_count=8192).decisions) == 8192
        assert len(self._fold(decision_count=1, training_count=8192).training_decisions) == 8192
        with pytest.raises(ValueError, match="8192"):
            self._fold(decision_count=8193)
        with pytest.raises(ValueError, match="8192"):
            self._fold(decision_count=1, training_count=8193)

        with pytest.raises(ValueError, match="immutable tuple"):
            replace(launch, decisions=cast(tuple[datetime, ...], list(launch.decisions)))
        with pytest.raises(TypeError, match="timezone-aware datetime"):
            replace(launch, decisions=cast(tuple[datetime, ...], (True,)))

    def test_report_benchmark_accepts_launch_size_and_stops_at_8192(self) -> None:
        """Retain 4,320 scheduled report periods while keeping exact tuple and integer checks."""
        launch = self._report_policy(period_count=4320)
        assert len(launch.benchmark) == 4320
        assert len(self._report_policy(period_count=8192).benchmark) == 8192
        with pytest.raises(ValueError, match="8192"):
            self._report_policy(period_count=8193)
        with pytest.raises(ValueError, match="immutable tuple"):
            replace(
                launch,
                benchmark=cast(tuple[BenchmarkPeriod, ...], list(launch.benchmark)),
            )
        with pytest.raises(ValueError, match="unsupported report policy"):
            replace(launch, periods_per_year=True)

    def test_feature_study_accepts_8640_launch_rows_and_stops_above_16384(self) -> None:
        """Bound the combined decision/instrument grid at 16,384 rows."""
        launch = self._feature_study(decision_count=4320)
        assert launch.decisions.end - launch.decisions.start == timedelta(hours=72)
        selected_input = launch.selection.inputs[0]
        assert isinstance(selected_input, TradeSelection)
        assert isinstance(selected_input.query, EdaQuery)
        assert len(selected_input.query.instruments) == 2
        assert (
            (launch.decisions.end - launch.decisions.start - timedelta(microseconds=1))
            // timedelta(minutes=1)
            + 1
        ) * len(selected_input.query.instruments) == 8640
        with pytest.raises(ValueError, match="research selection requires"):
            replace(
                launch,
                selection=replace(
                    launch.selection,
                    inputs=cast(
                        tuple[TradeSelection, ...],
                        list(launch.selection.inputs),
                    ),
                ),
            )
        maximum = self._feature_study(decision_count=8192)
        assert maximum.feature.cadence_us == 60_000_000
        maximum_input = maximum.selection.inputs[0]
        assert isinstance(maximum_input, TradeSelection)
        assert isinstance(maximum_input.query, EdaQuery)
        assert (
            (maximum.decisions.end - maximum.decisions.start - timedelta(microseconds=1))
            // timedelta(minutes=1)
            + 1
        ) * len(maximum_input.query.instruments) == 16_384
        with pytest.raises(ValueError, match="16384"):
            self._feature_study(decision_count=8193)
        with pytest.raises(ValueError, match="invalid cadence"):
            replace(launch, feature=replace(launch.feature, cadence_us=True))

    def test_feature_result_accepts_8640_rows_and_stops_at_16384(self) -> None:
        """Retain the launch result size and reject the first row count above the cap."""
        launch = self._feature_result(row_count=8640)
        assert len(launch.features) == len(launch.samples) == 8640
        assert len(self._feature_result(row_count=16_384).features) == 16_384
        with pytest.raises(ValueError, match="16384"):
            self._feature_result(row_count=16_385)
        with pytest.raises(TypeError, match="features must be an immutable tuple"):
            replace(
                launch,
                features=cast(
                    tuple[tuple[str, FeatureValue], ...],
                    list(launch.features),
                ),
            )
