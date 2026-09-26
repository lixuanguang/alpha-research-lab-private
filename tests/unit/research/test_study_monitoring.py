"""Check causal delayed-label revisions at the research telemetry boundary."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from financial_units import ExactRatio
from research.studies.monitoring import StudyMonitoringExporter
from telemetry import (
    DelayedLabelError,
    MetricInput,
    MetricRegistry,
    MetricSpec,
    MonitoringEvent,
    MonitoringIdentity,
    MonitoringQuery,
    TelemetryStore,
)


class TestStudyMonitoring:
    """Keep late labels and revisions invisible before their knowledge cutoffs."""

    start = datetime(2025, 1, 1, tzinfo=UTC)
    scope = MonitoringIdentity(
        scope="selected-study/fold-a",
        mode="research",
        model="fitted-state-a",
        dataset="source-a",
    )
    spec = MetricSpec(
        name="prediction-error",
        version="1",
        implementation_sha256=hashlib.sha256(b"delayed-label-error-v1").hexdigest(),
        inputs=(
            MetricInput(name=StudyMonitoringExporter.prediction_name, version="1", units="ratio"),
            MetricInput(name=StudyMonitoringExporter.outcome_name, version="1", units="ratio"),
        ),
        units="(ratio)^2",
        modes=("research",),
        aggregation="custom",
        missingness="pending labels remain gaps; mean uses observed pairs",
    )

    @classmethod
    def _query(cls, as_of: datetime) -> MonitoringQuery:
        """Keep the event window fixed while advancing only available knowledge."""
        return MonitoringQuery(
            scope=cls.scope.scope,
            mode="research",
            start=cls.start,
            end=cls.start + timedelta(microseconds=1),
            as_of=as_of,
        )

    def test_pending_missing_and_revised_outcomes_follow_cutoff(self, tmp_path: Path) -> None:
        """A future or revised label never changes an earlier dashboard result."""
        later = self.start + timedelta(seconds=1)
        missing_at = later + timedelta(seconds=1)
        revision_at = missing_at + timedelta(seconds=1)
        prediction = MonitoringEvent(
            context=self.scope,
            name=StudyMonitoringExporter.prediction_name,
            version="1",
            sample="feature-a",
            at=self.start,
            available_at=self.start,
            recorded_at=self.start,
            units="ratio",
            value=ExactRatio.from_fraction(Fraction(1, 3)),
        )
        pending = MonitoringEvent(
            context=self.scope,
            name=StudyMonitoringExporter.outcome_name,
            version="1",
            sample="feature-a",
            at=self.start,
            available_at=self.start,
            recorded_at=self.start,
            units="ratio",
            value=None,
            missing_reason="pending",
        )
        observed = replace(
            pending,
            revision=1,
            available_at=later,
            recorded_at=later,
            value=ExactRatio.from_fraction(Fraction(2, 3)),
            missing_reason=None,
        )
        missing = replace(
            pending,
            revision=2,
            available_at=missing_at,
            recorded_at=missing_at,
            missing_reason="source missing",
        )
        revised = replace(
            pending,
            revision=3,
            available_at=revision_at,
            recorded_at=revision_at,
            value=ExactRatio.from_fraction(Fraction(1, 2)),
            missing_reason=None,
        )
        store = TelemetryStore(tmp_path / "labels.sqlite")
        assert store.append((prediction, pending, observed, missing, revised)) == 5
        registry = MetricRegistry((DelayedLabelError(self.spec),))

        early = self._query(later - timedelta(microseconds=1))
        early_result = registry.evaluate(self.spec.identity, early, store.query(early))
        assert early_result.status == "missing"
        assert early_result.points[0].missing_reason == "pending"
        assert early_result.value is None

        known = self._query(later)
        known_result = registry.evaluate(self.spec.identity, known, store.query(known))
        assert known_result.value == ExactRatio.from_fraction(Fraction(1, 9))
        assert known_result.points[0].value == known_result.value

        absent = self._query(missing_at)
        absent_result = registry.evaluate(self.spec.identity, absent, store.query(absent))
        assert absent_result.status == "missing"
        assert absent_result.points[0].missing_reason == "source missing"

        corrected = self._query(revision_at)
        corrected_result = registry.evaluate(self.spec.identity, corrected, store.query(corrected))
        assert corrected_result.value == ExactRatio.from_fraction(Fraction(1, 36))
        assert registry.evaluate(self.spec.identity, early, store.query(early)) == early_result

        wrong_context = replace(
            observed,
            context=MonitoringIdentity(
                scope=self.scope.scope,
                mode="research",
                model="different-model",
            ),
        )
        with pytest.raises(ValueError, match="correlation"):
            registry.evaluate(self.spec.identity, known, (wrong_context, prediction))
