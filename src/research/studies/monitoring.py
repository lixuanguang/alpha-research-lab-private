"""Bridge retained study evidence to causal monitoring metrics and events."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime
from typing import Literal

# project library imports
from research.experiments import Fingerprint
from research.studies.extensions import ChartSpec, MetricValue, ReportContext, ReportObservation
from research.studies.study_results import StudyFoldResult, StudyResult
from serialization import DomainCodec
from telemetry import (
    MetricRegistry,
    MetricResult,
    MonitoringEvent,
    MonitoringIdentity,
    MonitoringMetric,
    MonitoringQuery,
)


class ReportMonitoringBridge:
    """Evaluate one selected monitoring definition against retained report diagnostics.

    Report observations have event clocks but no source knowledge or receipt clocks.
    Their first defensible monitoring availability is the explicit import receipt.
    """

    def __init__(self, metric: MonitoringMetric, *, scope: str, recorded_at: datetime) -> None:
        """Bind reviewed metric code, a research scope and actual import receipt."""
        metric.spec.__post_init__()
        MonitoringIdentity(scope=scope, mode="research")
        MonitoringEvent._require_utc(recorded_at, field_name="report import receipt")
        if "research" not in metric.spec.modes:
            raise ValueError("report metric must apply to research")
        self.metric = metric
        self.scope = scope
        self.recorded_at = recorded_at
        self.registry = MetricRegistry((metric,))

    @property
    def metric_identity(self) -> Fingerprint:
        """Bind the complete metric definition, including implementation digest."""
        return Fingerprint(name=self.metric.spec.name, sha256=self.metric.spec.identity)

    def evaluate(self, context: ReportContext) -> tuple[MetricResult, dict[str, str]]:
        """Select exact named diagnostics and retain their fold correlation."""
        events, folds = self._select(context)
        start = min(
            (event.at for event in events), default=min(fold.window.start for fold in context.folds)
        )
        if start >= self.recorded_at or len(events) > 100_000:
            raise ValueError(
                "report import must follow selected observations within query capacity"
            )
        query = MonitoringQuery(
            scope=self.scope,
            mode="research",
            start=start,
            end=self.recorded_at,
            as_of=self.recorded_at,
            limit=max(1, len(events)),
        )
        return self.registry.evaluate(self.metric.spec.identity, query, events), folds

    def events(self, context: ReportContext) -> tuple[MonitoringEvent, ...]:
        """Expose diagnostic facts for retained telemetry and dashboard queries."""
        events, _ = self._select(context)
        return events

    def _select(self, context: ReportContext) -> tuple[tuple[MonitoringEvent, ...], dict[str, str]]:
        """Convert selected diagnostics without assigning fictional historical clocks."""
        context.__post_init__()
        inputs = {item.name: item for item in self.metric.spec.inputs}
        identity = MonitoringIdentity(
            scope=self.scope, mode="research", study=context.study_identity
        )
        events: list[MonitoringEvent] = []
        folds: dict[str, str] = {}
        keys: set[tuple[str, str]] = set()
        for fold in context.folds:
            for observation in fold.diagnostics:
                selected = inputs.get(observation.name)
                if selected is None:
                    continue
                if observation.units != selected.units:
                    raise ValueError("report diagnostic units differ from monitoring definition")
                sample = hashlib.sha256(
                    DomainCodec().encode_json(
                        (context.study_identity, fold.fold_id, observation.at)
                    )
                ).hexdigest()
                key = observation.name, sample
                if key in keys:
                    raise ValueError("report diagnostic has duplicate name and fold clock")
                keys.add(key)
                folds[sample] = fold.fold_id
                events.append(
                    MonitoringEvent(
                        context=identity,
                        name=selected.name,
                        version=selected.version,
                        sample=sample,
                        at=observation.at,
                        available_at=self.recorded_at,
                        recorded_at=self.recorded_at,
                        units=observation.units,
                        value=observation.value,
                        missing_reason=observation.missing_reason,
                        clock_quality="unknown",
                    )
                )
        ordered = tuple(sorted(events, key=self._event_order))
        return ordered, folds

    @staticmethod
    def _event_order(event: MonitoringEvent) -> tuple[datetime, str, str]:
        """Keep diagnostics deterministic at shared observation clocks."""
        return event.at, event.name, event.sample

    @staticmethod
    def observations(result: MetricResult, folds: dict[str, str]) -> tuple[ReportObservation, ...]:
        """Carry selected metric points into report units and fold identities."""
        observations: list[ReportObservation] = []
        for point in result.points:
            fold_id = folds.get(point.sample)
            if fold_id is None:
                raise ValueError("monitoring metric point lacks a selected report sample")
            observations.append(
                ReportObservation(
                    fold_id=fold_id,
                    name=result.spec.name,
                    at=point.at,
                    units=result.spec.units,
                    value=point.value,
                    missing_reason=point.missing_reason,
                )
            )
        return tuple(observations)


class ReportMetricAdapter:
    """Expose the same injected monitoring computation as an MR03 report metric."""

    def __init__(self, bridge: ReportMonitoringBridge) -> None:
        """Bind the checked research-to-monitoring evaluation boundary."""
        self.bridge = bridge

    @property
    def identity(self) -> Fingerprint:
        """Expose the full selected monitoring definition to the report builder."""
        return self.bridge.metric_identity

    def evaluate(self, context: ReportContext) -> MetricValue:
        """Preserve the exact output, status reason, units and selected point series."""
        result, folds = self.bridge.evaluate(context)
        observations = self.bridge.observations(result, folds)
        return MetricValue(
            definition=self.identity,
            name=result.spec.name,
            version=result.spec.version,
            units=result.spec.units,
            value=result.value,
            missing_reason=result.reason,
            observations=observations,
        )


class ReportChartAdapter:
    """Expose a monitoring metric's exact point series to the existing chart renderer."""

    def __init__(
        self,
        bridge: ReportMonitoringBridge,
        *,
        title: str,
        kind: Literal["line", "bar", "table"] = "line",
    ) -> None:
        """Bind explicit chart presentation to the metric's complete definition."""
        if not title.strip() or kind not in ("line", "bar", "table"):
            raise ValueError("monitoring report chart requires title and supported kind")
        self.bridge = bridge
        self.title = title
        self.kind = kind

    @property
    def identity(self) -> Fingerprint:
        """Pin both implementation/metric contract and chart presentation selection."""
        digest = hashlib.sha256(
            DomainCodec().encode_json((self.bridge.metric.spec, self.title, self.kind))
        ).hexdigest()
        return Fingerprint(name=f"{self.bridge.metric.spec.name}-chart", sha256=digest)

    def evaluate(self, context: ReportContext) -> ChartSpec:
        """Pass exact metric points and explicit gaps through the existing renderer."""
        result, folds = self.bridge.evaluate(context)
        if not result.points:
            raise ValueError("monitoring metric returned no chart points")
        observations = self.bridge.observations(result, folds)
        return ChartSpec(
            definition=self.identity,
            title=self.title,
            kind=self.kind,
            data_references=(result.spec.name,),
            observations=observations,
        )


class StudyMonitoringExporter:
    """Export actual retained learned samples without reconstructing receipt clocks."""

    prediction_name = "research.prediction"
    outcome_name = "research.outcome"
    version = "1"

    def export(
        self,
        result: StudyResult,
        *,
        scope: str,
        recorded_at: datetime,
    ) -> tuple[MonitoringEvent, ...]:
        """Preserve per-fold model/source identities and one causal sample per feature."""
        result.__post_init__()
        MonitoringIdentity(scope=scope, mode="research")
        events: list[MonitoringEvent] = []
        for fold in result.folds:
            context = MonitoringIdentity(
                scope=f"{scope}/{fold.name}",
                mode="research",
                strategy=result.config.policy_identity,
                model=fold.model.identity if fold.model is not None else None,
                source=result.config.source_identity,
                study=result.config.identity,
            )
            events.extend(
                self.export_fold(
                    fold,
                    context=context,
                    recorded_at=recorded_at,
                )
            )
        return tuple(events)

    def export_fold(
        self,
        fold: StudyFoldResult,
        *,
        context: MonitoringIdentity,
        recorded_at: datetime,
    ) -> tuple[MonitoringEvent, ...]:
        """Retain the initial prediction and outcome facts for one fold."""
        predictions = self._predictions(fold, context=context, recorded_at=recorded_at)
        outcomes = self.export_outcomes(fold, context=context, recorded_at=recorded_at)
        return predictions + outcomes

    def export_outcomes(
        self,
        fold: StudyFoldResult,
        *,
        context: MonitoringIdentity,
        recorded_at: datetime,
        revision: int = 0,
    ) -> tuple[MonitoringEvent, ...]:
        """Emit a later label revision without changing retained prediction bytes."""
        self._validate_fold(fold, context=context, recorded_at=recorded_at)
        rows = {row.identity: row for row in fold.features}
        if len(rows) != len(fold.features):
            raise ValueError("retained fold has duplicate feature identities")
        events: list[MonitoringEvent] = []
        for outcome in fold.outcomes:
            row = rows.get(outcome.feature_identity)
            if row is None:
                raise ValueError("retained outcome lacks feature sample")
            outcome.sample(row)
            if fold.model is not None and (
                outcome.definition != fold.model.label_definition
                or outcome.field != fold.model.output
            ):
                raise ValueError("retained outcome differs from fitted label definition")
            available_at = outcome.available_at or recorded_at
            if recorded_at < available_at:
                raise ValueError("study import predates outcome knowledge")
            events.append(
                MonitoringEvent(
                    context=context,
                    name=self.outcome_name,
                    version=self.version,
                    sample=outcome.feature_identity,
                    at=row.decision_at,
                    available_at=available_at,
                    recorded_at=recorded_at,
                    units=outcome.field.units,
                    value=outcome.value,
                    missing_reason=outcome.reason if outcome.value is None else None,
                    revision=revision,
                    clock_quality="observed" if outcome.available_at is not None else "unknown",
                )
            )
        return tuple(events)

    def _predictions(
        self, fold: StudyFoldResult, *, context: MonitoringIdentity, recorded_at: datetime
    ) -> tuple[MonitoringEvent, ...]:
        """Import historical predictions at receipt time when their knowledge clock is absent."""
        self._validate_fold(fold, context=context, recorded_at=recorded_at)
        rows = {(row.entity, row.decision_at): row for row in fold.features}
        if len(rows) != len(fold.features):
            raise ValueError("retained fold has ambiguous entity and decision clocks")
        decisions = {(decision.feature_identity, decision.at) for decision in fold.decisions}
        events: list[MonitoringEvent] = []
        for prediction in fold.predictions:
            row = rows.get((prediction.entity, prediction.decision_at))
            if (
                row is None
                or (prediction.feature_identity, prediction.decision_at) not in decisions
                or (prediction.feature_identity != row.identity and fold.transform is None)
                or (fold.model is not None and prediction.field != fold.model.output)
            ):
                raise ValueError("retained prediction differs from feature sample")
            if recorded_at < prediction.decision_at:
                raise ValueError("study import predates prediction")
            events.append(
                MonitoringEvent(
                    context=context,
                    name=self.prediction_name,
                    version=self.version,
                    sample=row.identity,
                    at=prediction.decision_at,
                    available_at=recorded_at,
                    recorded_at=recorded_at,
                    units=prediction.field.units,
                    value=prediction.value,
                    clock_quality="unknown",
                )
            )
        return tuple(events)

    @staticmethod
    def _validate_fold(
        fold: StudyFoldResult, *, context: MonitoringIdentity, recorded_at: datetime
    ) -> None:
        """Require the selected research/model scope and a real UTC import receipt."""
        fold.__post_init__()
        context.__post_init__()
        MonitoringEvent._require_utc(recorded_at, field_name="study import receipt")
        expected_model = fold.model.identity if fold.model is not None else None
        if context.mode != "research" or context.model != expected_model:
            raise ValueError("study monitoring context differs from retained fitted model")
