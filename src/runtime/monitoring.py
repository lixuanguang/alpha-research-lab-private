"""Export a packaged candidate's runtime metrics, decision delays and predictions to telemetry."""

from __future__ import annotations

# standard library imports
import hashlib
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
from typing import Literal

# project library imports
from accounting import Fill, Ledger, LedgerState
from financial_units import Dimension, ExactRatio, Money, Price, QuantityKind
from reference_data.instruments import InstrumentId
from research.experiments import CandidateMetricContract, TimeWindow
from research.features import FeatureVector
from research.labels import Outcome
from research.reports import FoldSummary, LedgerPoint, MetricDefinition, ReportContext
from research.results import Prediction
from runtime.candidates import CandidateStep, LoadedCandidate
from serialization import DomainCodec
from telemetry import MetricThreshold, MonitoringEvent, MonitoringIdentity


@dataclass(frozen=True, slots=True)
class CandidateEvidence:
    """Carry one instance's attributed paper economics at an account observation.

    ``fills`` are the fills attributed to the instance, ``initial_cash`` its capital
    (its budget limit), and ``mark`` the latest eligible bid, needed only while the
    instance holds a position. ``start`` opens the fold and ``cutoff`` closes it.
    """

    fills: tuple[Fill, ...]
    initial_cash: Money
    mark: Price | None
    start: datetime
    cutoff: datetime


class CandidateMonitoringExporter:
    """Turn one deployed candidate's committed evidence into monitoring facts.

    Runtime metrics are the bundle's own metric components, evaluated over one
    paper fold built as research builds a study fold: the attributed fills, the
    opening and terminal marks. Decision delays, predictions and caller-computed
    outcomes are emitted per committed step. The exporter has no control path
    back to the candidate, journal or account; callers supply receipt clocks.
    """

    prediction_name = "research.prediction"
    outcome_name = "research.outcome"
    decision_delay_name = "runtime.decision-delay"
    version = "1"

    def __init__(
        self,
        loaded: LoadedCandidate,
        *,
        scope: str,
        account: str,
        mode: Literal["paper", "shadow"],
        clock_quality: Literal["observed", "modeled", "unknown"],
        study: str,
        release: str | None = None,
    ) -> None:
        """Bind the admitted candidate, its account scope and research provenance.

        Raises:
            ValueError: The mode, clock quality or study is invalid, or a runtime
                metric contract names no packaged metric component.
        """
        loaded.definition.__post_init__()
        loaded.deployment.__post_init__()
        MonitoringIdentity(scope=scope, mode=mode, account=account)
        if (
            mode not in ("paper", "shadow")
            or clock_quality not in ("observed", "modeled", "unknown")
            or type(study) is not str
            or not study
        ):
            raise ValueError("candidate monitoring requires a paper mode and its study")
        keys = tuple(
            component.factory_key
            for component in loaded.definition.components
            if component.role == "metric"
        )
        components = dict(zip(keys, loaded.metrics, strict=True))
        selected: list[tuple[CandidateMetricContract, MetricDefinition]] = []
        for contract in loaded.definition.metrics:
            if contract.kind != "metric" or "runtime" not in contract.applies_to:
                continue
            component = components.get(contract.component_key)
            if component is None:
                raise ValueError("runtime metric contract names no packaged metric")
            selected.append((contract, component))
        self.metrics = tuple(selected)
        self.loaded, self.scope, self.account, self.mode = loaded, scope, account, mode
        self.clock_quality, self.study, self.release = clock_quality, study, release
        self._codec = DomainCodec()

    @property
    def thresholds(self) -> tuple[MetricThreshold, ...]:
        """Return each runtime metric's declared warning band edges."""
        edges: list[MetricThreshold] = []
        for contract, _ in self.metrics:
            if contract.warning_below is not None:
                edges.append(
                    MetricThreshold(
                        name=contract.name, operator="<", threshold=contract.warning_below
                    )
                )
            if contract.warning_above is not None:
                edges.append(
                    MetricThreshold(
                        name=contract.name, operator=">", threshold=contract.warning_above
                    )
                )
        return tuple(edges)

    def runtime_metrics(
        self, evidence: CandidateEvidence, *, recorded_at: datetime
    ) -> tuple[MonitoringEvent, ...]:
        """Evaluate every runtime metric over the instance's paper fold at its cutoff."""
        MonitoringEvent._require_utc(recorded_at, field_name="candidate metric receipt")
        if recorded_at < evidence.cutoff or not evidence.start < evidence.cutoff:
            raise ValueError("candidate metric receipt precedes its evidence")
        context = ReportContext(
            study_identity=self.loaded.definition.identity, folds=(self._fold(evidence),)
        )
        events: list[MonitoringEvent] = []
        for contract, component in self.metrics:
            value = component.evaluate(context)
            exact = value.value if value.units == contract.units else None
            events.append(
                MonitoringEvent(
                    context=self._context(None),
                    name=contract.name,
                    version=contract.version,
                    sample=hashlib.sha256(
                        self._codec.encode_json((contract.name, evidence.cutoff))
                    ).hexdigest(),
                    at=evidence.cutoff,
                    available_at=evidence.cutoff,
                    recorded_at=recorded_at,
                    units=contract.units,
                    value=exact,
                    missing_reason=None
                    if exact is not None
                    else value.missing_reason or "metric units differ from its contract",
                    clock_quality=self.clock_quality,
                )
            )
        return tuple(events)

    def decision_delay(
        self, at: datetime, coordinated_at: datetime, *, recorded_at: datetime
    ) -> MonitoringEvent:
        """Emit the seconds between a decided instant and its coordination."""
        MonitoringEvent._require_utc(recorded_at, field_name="decision delay receipt")
        if not at < coordinated_at <= recorded_at:
            raise ValueError("decision delay requires a coordination after its instant")
        delay = coordinated_at - at
        seconds = Fraction(delay.days * 86_400 + delay.seconds) + Fraction(
            delay.microseconds, 1_000_000
        )
        return MonitoringEvent(
            context=self._context(None),
            name=self.decision_delay_name,
            version=self.version,
            sample=hashlib.sha256(self._codec.encode_json(("delay", at))).hexdigest(),
            at=at,
            available_at=coordinated_at,
            recorded_at=recorded_at,
            units="seconds",
            value=ExactRatio.from_fraction(seconds),
            clock_quality=self.clock_quality,
        )

    def prediction(self, step: CandidateStep, *, recorded_at: datetime) -> MonitoringEvent:
        """Emit the committed inference with its caller-supplied receipt clock."""
        feature, prediction = self._admit_step(step)
        MonitoringEvent._require_utc(recorded_at, field_name="candidate monitoring receipt")
        if recorded_at < step.at:
            raise ValueError("candidate monitoring receipt precedes committed inference")
        return MonitoringEvent(
            context=self._context(prediction),
            name=self.prediction_name,
            version=self.version,
            sample=feature.identity,
            at=prediction.decision_at,
            available_at=step.at,
            recorded_at=recorded_at,
            units=prediction.field.units,
            value=prediction.value,
            clock_quality=self.clock_quality,
        )

    def outcome(
        self,
        step: CandidateStep,
        outcome: Outcome,
        *,
        recorded_at: datetime,
        revision: int = 0,
    ) -> MonitoringEvent:
        """Emit a pending, observed or corrected label at its genuine knowledge clock."""
        feature, prediction = self._admit_step(step)
        outcome.sample(feature)
        version = self.loaded.estimator_version
        if (
            version is None
            or outcome.definition != version.label_definition
            or outcome.field != prediction.field
        ):
            raise ValueError("candidate outcome differs from admitted fitted label")
        MonitoringEvent._require_utc(recorded_at, field_name="candidate label receipt")
        available_at = outcome.available_at or recorded_at
        if recorded_at < max(step.at, available_at):
            raise ValueError("candidate label receipt precedes inference or knowledge")
        return MonitoringEvent(
            context=self._context(prediction),
            name=self.outcome_name,
            version=self.version,
            sample=feature.identity,
            at=prediction.decision_at,
            available_at=available_at,
            recorded_at=recorded_at,
            units=outcome.field.units,
            value=outcome.value,
            missing_reason=outcome.reason if outcome.value is None else None,
            revision=revision,
            clock_quality=self.clock_quality if outcome.available_at is not None else "unknown",
        )

    def _fold(self, evidence: CandidateEvidence) -> FoldSummary:
        """Build the instance's paper fold as research builds a study fold."""
        dimension = Dimension(
            instrument_id=InstrumentId.from_canonical_text(self.loaded.deployment.entity),
            kind=QuantityKind.BASE_UNIT,
        )
        opening = Ledger(LedgerState(initial_cash=evidence.initial_cash, dimension=dimension))
        ledger = Ledger(
            LedgerState(
                initial_cash=evidence.initial_cash,
                dimension=dimension,
                fills=tuple(sorted(evidence.fills, key=self._fill_order)),
            )
        )
        terminal = ledger.mark(evidence.mark if ledger.balance.holding.value else None)
        return FoldSummary(
            fold_id=self.loaded.deployment.instance,
            window=TimeWindow(start=evidence.start, end=evidence.cutoff),
            ledger=ledger.state,
            terminal_mark=terminal,
            curve=(
                LedgerPoint(at=evidence.start, mark=opening.mark(None)),
                LedgerPoint(at=evidence.cutoff, mark=terminal),
            ),
        )

    @staticmethod
    def _fill_order(fill: Fill) -> tuple[datetime, str]:
        """Apply fills in time order, ties by identity."""
        return fill.filled_at, fill.identity

    def _admit_step(self, step: CandidateStep) -> tuple[FeatureVector, Prediction]:
        """Reject an undecided or foreign step before emitting account telemetry."""
        step.__post_init__()
        if (
            step.status != "decided"
            or step.feature is None
            or step.prediction is None
            or step.checkpoint.binding_identity != self.loaded.identity
        ):
            raise ValueError("candidate monitoring requires a committed learned step")
        version = self.loaded.estimator_version
        if (
            version is None
            or step.prediction.model_identity != version.identity
            or step.prediction.field != version.output
        ):
            raise ValueError("candidate monitoring prediction differs from fitted model")
        return step.feature, step.prediction

    def _context(self, prediction: Prediction | None) -> MonitoringIdentity:
        """Pin the account scope, installed code, study, source, model and instrument."""
        policy = next(
            item.identity for item in self.loaded.definition.components if item.role == "policy"
        )
        model = self.loaded.estimator_version
        return MonitoringIdentity(
            scope=self.scope,
            mode=self.mode,
            release=self.release or self.loaded.definition.code_sha256,
            strategy=policy,
            model=prediction.model_identity
            if prediction is not None
            else None
            if model is None
            else model.identity,
            source=self.loaded.deployment.source_identity,
            study=self.study,
            account=self.account,
            instrument=self.loaded.deployment.entity,
        )
