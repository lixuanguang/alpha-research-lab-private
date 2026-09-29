"""Verify optional comparison composition keeps the installed pipeline contract."""

from __future__ import annotations

# standard library imports
from datetime import timedelta
from fractions import Fraction

# third party library imports
import pytest
from economic_examples import ReplayInputs
from msgspec.structs import replace

# project library imports
from financial_units import ExactRatio
from research.experiments import TemporalSplit, TimeWindow
from research.studies import (
    BacktestRun,
    BenchmarkPeriod,
    ClearMLDestination,
    ComparisonStudy,
    PipelineRun,
    ReportPolicy,
)
from serialization import DomainCodec


class TestResearchPipeline:
    """Keep comparison config optional while binding it to the configured first variant."""

    @staticmethod
    def _runs() -> tuple[BacktestRun, ComparisonStudy]:
        """Build an actual bounded economic grid from the shared admitted replay fixture."""
        reader, economics = ReplayInputs._inputs(ReplayInputs.rows)
        zero = ExactRatio.from_fraction(Fraction(0))
        report = ReportPolicy(
            benchmark_name="explicit-flat-control",
            benchmark=tuple(
                BenchmarkPeriod(end=economics.start + timedelta(minutes=index), value=zero)
                for index in range(1, 5)
            ),
            cadence_seconds=60,
            periods_per_year=525_600,
            annual_risk_free=zero,
        )
        split = TemporalSplit(
            fit_mode="none",
            training=None,
            fit_cutoff=None,
            validation=TimeWindow(start=economics.start, end=economics.end),
            holdout=TimeWindow(
                start=economics.end + timedelta(days=1),
                end=economics.end + timedelta(days=2),
            ),
            samples=(),
            embargo_us=0,
            rationale="No fitted state; final holdout stays untouched",
        )
        first = BacktestRun(
            family="pipeline-comparison",
            snapshot_id=reader.identity,
            economics=economics,
            report=report,
            split=split,
        )
        second = replace(
            first,
            economics=replace(economics, instance="flat-control", rule="no-trade-v1"),
        )
        return first, ComparisonStudy(
            name="pipeline-comparison",
            variants=(first, second),
            budget=2,
            seed=17,
            minimum_return=ExactRatio.from_fraction(Fraction(-1)),
        )

    @staticmethod
    def _plan(configuration: BacktestRun, comparison: ComparisonStudy | None = None) -> PipelineRun:
        """Compose one plan with the exact installed-command boundary."""
        return PipelineRun(
            configuration=configuration,
            tracking=ClearMLDestination(
                project="unit",
                api_uri="http://127.0.0.1:18008",
                files_uri="http://127.0.0.1:18081",
            ),
            inputs_root="/tmp/pipeline-inputs",
            attempts="/tmp/pipeline-attempts",
            output_root="/tmp/pipeline-output",
            max_bytes=2_000_000,
            implementation_sha256="a" * 64,
            environment_sha256="b" * 64,
            artifact_sha256="c" * 64,
            python="/tmp/worker/bin/python",
            command="/tmp/worker/bin/alpha-backtest",
            queue="alpha-research-local",
            comparison=comparison,
        )

    def test_comparison_plan_roundtrip_and_first_variant_binding(self) -> None:
        """Retain the real comparison definition and reject a mismatched base configuration."""
        configuration, comparison = self._runs()
        plan = self._plan(configuration, comparison)
        codec = DomainCodec()

        restored = codec.decode_json(codec.encode_json(plan), PipelineRun)

        assert restored == plan
        assert restored.comparison == comparison
        mismatched = replace(
            configuration,
            economics=replace(configuration.economics, instance="different-base"),
        )
        with pytest.raises(ValueError, match="first"):
            self._plan(mismatched, comparison)
