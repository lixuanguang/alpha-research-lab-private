"""Exercise fresh components through installed temporal studies and exact economics."""

from __future__ import annotations

# standard library imports
import hashlib
import subprocess
import sys
from dataclasses import replace as dataclass_replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Literal

# third party library imports
import msgspec
from msgspec.structs import replace

# project library imports
from applications.explore import (
    StudyComponents,
    StudyJobHandler,
    compare_studies,
    evaluate_study,
    schedule_study,
)
from financial_units import Currency, Dimension, ExactRatio, Money, Price, Quantity, QuantityKind
from market_data.contracts import BookObservation, Level
from reference_data.instruments import InstrumentId
from research.experiments import AttemptStore, Fingerprint, TemporalSplit, TimeWindow
from research.features import FeatureSchema, FeatureTransition, FeatureVector, FittedTransform
from research.labels import Outcome
from research.models import EstimatorLifecycle
from research.observations import (
    DecisionInputs,
    InputRequirement,
    NamedObservation,
    NumericField,
    NumericHistorySource,
)
from research.studies import (
    ChartSpec,
    ClearMLDestination,
    DecisionComparison,
    DecisionStudy,
    MetricValue,
    PublicationPolicy,
    ReportContext,
    ReportObservation,
    StudyArtifact,
    StudyFold,
    StudyReportReader,
    StudyResult,
)
from risk import SpotLimits
from runtime import (
    ImplementationIdentity,
    JobQueue,
    JobRun,
    JobSpec,
    JobWorkerPool,
    WorkspaceBackup,
)
from serialization import DomainCodec
from simulation import (
    IntentMarket,
    IntentSimulationSpec,
    IntentTrade,
    LimitExecutionConfig,
    LimitOrderExecution,
    SpotCosts,
    SpotFeeModel,
)
from strategies import DecisionContext, DecisionTransition, OrderIntent, TargetIntent


class _Feature:
    """Produce a fresh two-field batch feature from an authored numeric observation."""

    def __init__(self, requirement: InputRequirement) -> None:
        """Bind the exact input and output signatures."""
        self._schema = FeatureSchema(
            implementation="installed-square-signal-v1",
            inputs=(requirement,),
            outputs=(
                NumericField(name="signal", units="dimensionless"),
                NumericField(name="signal-square", units="dimensionless"),
            ),
            parameters=(),
            mode="batch",
            ttl_us=0,
        )

    @property
    def schema(self) -> FeatureSchema:
        """Expose the selected two-field definition."""
        return self._schema

    def initial_state(self) -> bytes:
        """Start one stateless batch transition."""
        return b"batch"

    def validate_state(self, state: bytes) -> None:
        """Reject state that did not originate from this feature."""
        if state != b"batch":
            raise ValueError("foreign custom feature state")

    def step(self, inputs: DecisionInputs, state: bytes) -> FeatureTransition:
        """Square only the then-known numeric value."""
        self.validate_state(state)
        signal = inputs.observations[0].value
        if signal is None:
            return FeatureTransition(
                values=(None, None), reasons=("missing", "missing"), state=state
            )
        value = Fraction(int(signal.numerator), int(signal.denominator))
        return FeatureTransition(
            values=(signal, ExactRatio.from_fraction(value * value)),
            reasons=("observed", "observed"),
            state=state,
        )


class _Labels:
    """Supply delayed exact outcomes independently of decision-time features."""

    @property
    def identity(self) -> str:
        """Pin this synthetic one-second outcome definition."""
        return "installed-next-value-label-v1"

    def read(self, row: FeatureVector, *, as_of: datetime) -> Outcome:
        """Retain a separately available label without presenting it to the policy."""
        available = row.decision_at + timedelta(seconds=1)
        signal = row.values[0]
        if signal is None:
            raise ValueError("synthetic training signal is missing")
        return Outcome(
            feature_identity=row.identity,
            definition=self.identity,
            field=NumericField(name="next-value", units="dimensionless"),
            information_start=row.event_at,
            information_end=available,
            available_at=available if available <= as_of else None,
            value=signal if available <= as_of else None,
            reason="observed" if available <= as_of else "pending",
            lineage=(f"label:{row.identity}",),
        )


class _Estimator:
    """Prove the lifecycle passes only admitted training rows to a fresh estimator."""

    @property
    def identity(self) -> str:
        """Identify the installed external estimator contract."""
        return "installed-training-only-estimator-v1"

    def fit(self, rows: tuple[FeatureVector, ...], outcomes: tuple[ExactRatio, ...]) -> bytes:
        """Reject validation or holdout values in the fit call."""
        values = tuple(int(row.values[0].numerator) for row in rows if row.values[0] is not None)
        if values not in ((1, 2), (3, 4)) or len(outcomes) != 2:
            raise ValueError(f"estimator received non-training rows: {values}")
        return ",".join(str(value) for value in values).encode()

    def predict(self, state: bytes, row: FeatureVector) -> ExactRatio:
        """Reload fitted bytes and return the selected decision-time signal."""
        if state not in (b"1,2", b"3,4") or row.values[0] is None:
            raise ValueError("invalid custom estimator state or inference row")
        return row.values[0]


class _ShiftTransform:
    """Fit a first-column center using only the current fold's training values."""

    @property
    def identity(self) -> str:
        """Pin the external exact-shift implementation."""
        return "installed-train-only-shift-v1"

    def fit(self, rows: tuple[FeatureVector, ...]) -> bytes:
        """Reject validation and holdout rows before persisting an exact mean."""
        values = tuple(int(row.values[0].numerator) for row in rows if row.values[0] is not None)
        if values not in ((1, 2), (3, 4)) or len(rows) != 2:
            raise ValueError(f"transform received non-training rows: {values}")
        return str(Fraction(sum(values), len(values))).encode()

    def output_fields(
        self, state: bytes, fields: tuple[NumericField, ...]
    ) -> tuple[NumericField, ...]:
        """Preserve the two custom output names after checking fitted state."""
        if state not in (b"3/2", b"7/2") or tuple(field.name for field in fields) != (
            "signal",
            "signal-square",
        ):
            raise ValueError("unexpected fitted transform state or fields")
        return fields

    def apply(self, state: bytes, row: FeatureVector) -> tuple[ExactRatio | None, ...]:
        """Subtract the retained train mean and preserve the independent square."""
        self.output_fields(state, row.fields)
        signal, square = row.values
        if signal is None or square is None:
            raise ValueError("missing shifted study input")
        shifted = Fraction(int(signal.numerator), int(signal.denominator)) - Fraction(
            state.decode()
        )
        return ExactRatio.from_fraction(shifted), square


class _ShiftedEstimator:
    """Prove the estimator receives train-only transformed values, then reloads state."""

    @property
    def identity(self) -> str:
        """Pin a separate transformed estimator implementation."""
        return "installed-shifted-estimator-v1"

    def fit(self, rows: tuple[FeatureVector, ...], outcomes: tuple[ExactRatio, ...]) -> bytes:
        """Check the exact centered training values and aligned outcomes."""
        shifted = tuple(row.values[0] for row in rows)
        squares = tuple(row.values[1] for row in rows)
        if (
            shifted
            != (
                ExactRatio(numerator="-1", denominator="2"),
                ExactRatio(numerator="1", denominator="2"),
            )
            or squares
            not in (
                (
                    ExactRatio(numerator="1", denominator="1"),
                    ExactRatio(numerator="4", denominator="1"),
                ),
                (
                    ExactRatio(numerator="9", denominator="1"),
                    ExactRatio(numerator="16", denominator="1"),
                ),
            )
            or outcomes
            not in (
                (
                    ExactRatio(numerator="1", denominator="1"),
                    ExactRatio(numerator="2", denominator="1"),
                ),
                (
                    ExactRatio(numerator="3", denominator="1"),
                    ExactRatio(numerator="4", denominator="1"),
                ),
            )
        ):
            raise ValueError("estimator did not receive aligned shifted training rows")
        return b"shifted-training-only"

    def predict(self, state: bytes, row: FeatureVector) -> ExactRatio:
        """Predict only from a reloaded transformed inference vector."""
        if state != b"shifted-training-only" or row.values[0] is None:
            raise ValueError("invalid shifted model state or inference row")
        return row.values[0]


class _TargetPolicy:
    """Select target holdings from a feature or injected prediction with portable state."""

    def __init__(self, dimension: Dimension, *, threshold: int, fail: bool = False) -> None:
        """Bind one exact threshold and isolated instrument dimension."""
        self._dimension, self._threshold, self._fail = dimension, threshold, fail

    @property
    def identity(self) -> str:
        """Pin behavior and authored parameter choice."""
        return f"installed-target-{self._threshold}-{'fail' if self._fail else 'run'}-v1"

    @property
    def output(self) -> Literal["target"]:
        """Declare an absolute spot holding request."""
        return "target"

    def admit(self, fields: tuple[NumericField, ...], prediction: NumericField | None) -> None:
        """Require both custom feature fields and compatible optional model output."""
        if tuple(field.name for field in fields) != ("signal", "signal-square") or (
            prediction is not None and prediction.units != "dimensionless"
        ):
            raise ValueError("custom target signature mismatch")

    def initial_state(self) -> bytes:
        """Begin with no emitted decisions."""
        return b"0"

    def validate_state(self, state: bytes) -> None:
        """Reject foreign or corrupt counter bytes."""
        if not state.isdigit():
            raise ValueError("invalid custom policy state")

    def decide(self, context: DecisionContext, state: bytes) -> DecisionTransition:
        """Return an exact target or a deliberate failed-trial witness."""
        self.validate_state(state)
        if self._fail:
            raise ValueError("injected policy trial failure")
        signal = (
            context.prediction.value
            if context.prediction is not None
            else context.features.values[0]
        )
        if signal is None:
            raise ValueError("decision signal is missing")
        value = Fraction(int(signal.numerator), int(signal.denominator))
        target = "1" if value >= self._threshold else "0"
        return DecisionTransition(
            intent=TargetIntent(
                quantity=Quantity(value=Decimal(target), dimension=self._dimension)
            ),
            state=str(int(state) + 1).encode(),
        )


class _OrderPolicy:
    """Emit a fresh resting bid from the custom two-field signal."""

    def __init__(self, scenario: _Scenario) -> None:
        """Bind the exact spot units and authored limit."""
        self._scenario = scenario

    @property
    def identity(self) -> str:
        """Pin the selected passive order rule."""
        return "installed-passive-bid-99-v1"

    @property
    def output(self) -> Literal["order"]:
        """Declare order intent before any source reads."""
        return "order"

    def admit(self, fields: tuple[NumericField, ...], prediction: NumericField | None) -> None:
        """Reject an unexpected feature or model signature."""
        if tuple(field.name for field in fields) != ("signal", "signal-square") or prediction:
            raise ValueError("custom order signature mismatch")

    def initial_state(self) -> bytes:
        """Start one isolated pure order decision."""
        return b"0"

    def validate_state(self, state: bytes) -> None:
        """Check portable state before deriving an order."""
        if not state.isdigit():
            raise ValueError("invalid order policy state")

    def decide(self, context: DecisionContext, state: bytes) -> DecisionTransition:
        """Rest one bid without any venue submission or hidden portfolio mutation."""
        self.validate_state(state)
        if context.features.values[0] is None:
            raise ValueError("missing passive order signal")
        return DecisionTransition(
            intent=OrderIntent(
                side="buy",
                quantity=self._scenario.quantity("1"),
                limit=self._scenario.price("99"),
                time_in_force="post-only",
            ),
            state=str(int(state) + 1).encode(),
        )


class _Market:
    """Return pinned synthetic L2 books for the requested evaluation window only."""

    def __init__(
        self, scenario: _Scenario, *, fail_holdout: bool = False, passive: bool = False
    ) -> None:
        """Keep an optional read failure after the application records holdout access."""
        self._scenario, self._fail_holdout, self._passive = scenario, fail_holdout, passive

    @property
    def identity(self) -> str:
        """Identify the authored source and clock interpretation."""
        return "installed-synthetic-l2-passive-v1" if self._passive else "installed-synthetic-l2-v1"

    def read(self, window: TimeWindow) -> tuple[IntentMarket, ...]:
        """Supply pre-window touch and terminal valuation without inventing fills."""
        if self._fail_holdout and window.start == self._scenario.at(39):
            raise OSError("injected holdout market read failure")
        if window.end == self._scenario.at(39) - timedelta(microseconds=1):
            return self._book(window.start), self._book(self._scenario.at(38))
        if (window.end - window.start) != timedelta(seconds=6):
            raise ValueError("unsupported synthetic market window")
        if self._passive:
            return (
                self._book(window.start),
                self._trade(window.start + timedelta(seconds=4), quantity="1"),
                self._trade(window.start + timedelta(seconds=5), quantity="2"),
                self._book(window.end),
            )
        return (self._book(window.start), self._book(window.end))

    def _trade(self, at: datetime, *, quantity: str) -> IntentMarket:
        """Supply an explicitly timed sell trade at the resting bid price."""
        return IntentMarket(
            identity=f"sell-trade:{at.isoformat()}:{quantity}",
            source_identity=self.identity,
            instrument=self._scenario.entity,
            channel="l2",
            source_at=at,
            known_at=at,
            book=None,
            trades=(
                IntentTrade(
                    price=self._scenario.price("99"),
                    quantity=self._scenario.quantity(quantity),
                    aggressor="sell",
                ),
            ),
        )

    def _book(self, at: datetime) -> IntentMarket:
        """Carry canonical aggregate L2 levels and explicit source/knowledge clocks."""
        source_ms = str(int(at.timestamp()) * 1000)
        book = BookObservation(
            position=int((at - self._scenario.at(0)).total_seconds()),
            epoch=None,
            received_ns=None,
            source_time=source_ms,
            sequence=None,
            outcome="snapshot",
            status="degraded",
            reason="synthetic L2 research fixture",
            state_identity=hashlib.sha256(f"book:{source_ms}".encode()).hexdigest(),
            bids=((Decimal("99"), Level(Decimal("2"), 1)),),
            asks=((Decimal("101"), Level(Decimal("2"), 1)),),
        )
        return IntentMarket(
            identity=f"book:{source_ms}",
            source_identity=self.identity,
            instrument=self._scenario.entity,
            channel="l2",
            source_at=at,
            known_at=at,
            book=book,
        )


class _ShiftedDecisionSource:
    """Misreport the decision cutoff while preserving selected source admission metadata."""

    def __init__(self, source: NumericHistorySource) -> None:
        """Wrap the retained history without changing its declared identity or inputs."""
        self._source = source

    @property
    def identity(self) -> str:
        """Expose the already selected source identity."""
        return self._source.identity

    @property
    def requirements(self) -> tuple[InputRequirement, ...]:
        """Expose the selected named input signature."""
        return self._source.requirements

    def read(self, entity: str, at: datetime) -> DecisionInputs:
        """Return valid inputs one microsecond later than the requested cutoff."""
        return self._source.read(entity, at + timedelta(microseconds=1))


class _FillCountMetric:
    """Count exact posted fills across independent folds."""

    @property
    def identity(self) -> Fingerprint:
        """Identify this custom report computation."""
        return Fingerprint(
            name="installed-fill-count",
            sha256=hashlib.sha256(b"installed-fill-count-v1").hexdigest(),
        )

    def evaluate(self, context: ReportContext) -> MetricValue:
        """Derive the count only from retained authoritative ledger postings."""
        observations = tuple(
            ReportObservation(
                fold_id=fold.fold_id,
                name="posted-fills",
                at=fold.window.end,
                units="fills",
                value=ExactRatio.from_fraction(Fraction(len(fold.ledger.fills))),
            )
            for fold in context.folds
        )
        return MetricValue(
            definition=self.identity,
            name="Posted fills",
            version="1",
            units="fills",
            value=ExactRatio.from_fraction(
                Fraction(sum(len(fold.ledger.fills) for fold in context.folds))
            ),
            observations=observations,
        )


class _ProfitChart:
    """Expose exact fold net profit to the generic chart renderer."""

    @property
    def identity(self) -> Fingerprint:
        """Identify this custom selected chart."""
        return Fingerprint(
            name="installed-fold-profit",
            sha256=hashlib.sha256(b"installed-fold-profit-v1").hexdigest(),
        )

    def evaluate(self, context: ReportContext) -> ChartSpec:
        """Build a typed bar series from exact terminal ledger marks."""
        observations = tuple(
            ReportObservation(
                fold_id=fold.fold_id,
                name="net-profit",
                at=fold.window.end,
                units=fold.terminal_mark.net.currency.code,
                value=ExactRatio.from_fraction(Fraction(fold.terminal_mark.net.value)),
            )
            for fold in context.folds
        )
        return ChartSpec(
            definition=self.identity,
            title="Custom fold net profit",
            kind="bar",
            data_references=("net-profit",),
            observations=observations,
        )


class _MarketClocks(msgspec.Struct, frozen=True):
    """Decode only source and knowledge clocks from a retained market artifact."""

    source_at: datetime
    known_at: datetime


class _DecisionInputClock(msgspec.Struct, frozen=True):
    """Decode the retained cutoff from an otherwise complete decision input record."""

    entity: str
    decision_at: datetime


class _Scenario:
    """Construct complete independent study inputs outside shared orchestration."""

    entity = "4476df8e-6342-4417-839e-e41b88f41446"

    def __init__(self) -> None:
        """Bind exact units, source, model and execution collaborators."""
        source_bytes = Path(__file__).read_bytes()
        self.artifact = StudyArtifact(
            fingerprint=Fingerprint(
                name="installed-consumer-module",
                sha256=hashlib.sha256(source_bytes).hexdigest(),
            ),
            payload=source_bytes,
        )
        self.dimension = Dimension(
            instrument_id=InstrumentId.from_canonical_text(self.entity),
            kind=QuantityKind.BASE_UNIT,
        )
        self.currency = Currency(code="USDT", minor_unit=Decimal("0.01"))
        self.requirement = InputRequirement(
            name="authored-signal",
            family="non-book",
            clock="authored",
            field=NumericField(name="level", units="dimensionless"),
            max_age_us=0,
        )
        rows = tuple(
            NamedObservation(
                input=self.requirement,
                entity=self.entity,
                event_at=self.at(second),
                available_at=self.at(second),
                value=ExactRatio(numerator=str(value), denominator="1"),
                reason="synthetic",
                lineage=f"signal:{second}:{value}",
            )
            for second, value in ((1, 1), (2, 2), (10, 7), (20, 3), (21, 4), (30, 8), (40, 9))
        )
        self.source = NumericHistorySource(rows, (self.requirement,))
        self.feature = _Feature(self.requirement)
        self.model = EstimatorLifecycle(_Estimator())
        self.transform = FittedTransform(_ShiftTransform())
        self.shifted_model = EstimatorLifecycle(_ShiftedEstimator())
        self.labels = _Labels()
        self.execution = LimitOrderExecution(
            LimitExecutionConfig(
                entry_delay_us=1_000_000,
                cancel_delay_us=0,
                lifetime_us=6_000_000,
                max_book_age_us=20_000_000,
                take_fraction=Decimal("1"),
                queue_ahead_fraction=Decimal("1"),
            )
        )
        self.optimistic_execution = LimitOrderExecution(
            replace(self.execution.config, queue_ahead_fraction=Decimal("0"))
        )
        costs = SpotCosts(adverse=self.price("0"), fee_rate=Decimal("0.002"), rounding="half_even")
        self.costs = SpotFeeModel(maker=costs, taker=costs)
        self.metric, self.chart = _FillCountMetric(), _ProfitChart()
        self.limits = SpotLimits(
            maximum=self.quantity("10"),
            lot=self.quantity("1"),
            tick=self.price("0.01"),
            product="spot",
            specification_identity="a" * 64,
            minimum_order=self.quantity("1"),
        )

    @staticmethod
    def at(second: int) -> datetime:
        """Return one exact authored UTC second."""
        return datetime(2026, 9, 23, tzinfo=UTC) + timedelta(seconds=second)

    def quantity(self, value: str) -> Quantity:
        """Bind exact base units."""
        return Quantity(value=Decimal(value), dimension=self.dimension)

    def price(self, value: str) -> Price:
        """Bind exact quote per base unit."""
        return Price(value=Decimal(value), currency=self.currency, per=self.dimension)

    def _split(
        self, training: tuple[int, int], validation: tuple[int, int], *, fit: bool
    ) -> TemporalSplit:
        """Reserve one final holdout while keeping each fitting fold earlier-only."""
        return TemporalSplit(
            training=TimeWindow(start=self.at(training[0]), end=self.at(training[1]))
            if fit
            else None,
            validation=TimeWindow(start=self.at(validation[0]), end=self.at(validation[1])),
            holdout=TimeWindow(start=self.at(39), end=self.at(45)),
            samples=(),
            fit_mode="labels" if fit else "none",
            fit_cutoff=self.at(training[1] + 1) if fit else None,
            embargo_us=0,
            rationale="disjoint synthetic training, validation and untouched final holdout",
        )

    def folds(self, *, fitted: bool, holdout: bool = False) -> tuple[StudyFold, ...]:
        """Declare two walk-forward validations or one frozen final evaluation."""
        first = StudyFold(
            name="early-validation",
            split=self._split((0, 4), (9, 15), fit=fitted),
            training_decisions=(self.at(1), self.at(2)) if fitted else (),
            decisions=(self.at(10),),
            evaluated_as_of=self.at(14),
        )
        second = StudyFold(
            name="late-validation",
            split=self._split((19, 23), (29, 35), fit=fitted),
            training_decisions=(self.at(20), self.at(21)) if fitted else (),
            decisions=(self.at(30),),
            evaluated_as_of=self.at(34),
        )
        if holdout:
            return (
                StudyFold(
                    name="final-holdout",
                    split=second.split,
                    training_decisions=second.training_decisions,
                    decisions=(self.at(40),),
                    evaluated_as_of=self.at(44),
                ),
            )
        return (first, second) if fitted else (first,)

    def components(
        self,
        policy: _TargetPolicy | _OrderPolicy,
        *,
        fitted: bool,
        transformed: bool = False,
        passive: bool = False,
        optimistic: bool = False,
        fail_holdout_market: bool = False,
    ) -> StudyComponents:
        """Supply implementations explicitly without a built-in registry or fallback."""
        return StudyComponents(
            source=self.source,
            market=_Market(self, fail_holdout=fail_holdout_market, passive=passive),
            feature=self.feature,
            policy=policy,
            execution=self.optimistic_execution if optimistic else self.execution,
            costs=self.costs,
            capabilities=(
                "product:spot",
                "calendar:continuous-utc",
                f"intent:{policy.output}",
                "feature:batch",
                "input:non-book",
            ),
            metrics=(self.metric,),
            charts=(self.chart,),
            artifacts=(self.artifact,),
            model=(self.shifted_model if transformed else self.model) if fitted else None,
            transform=self.transform if transformed else None,
            labels=self.labels if fitted else None,
        )

    def study(
        self,
        policy: _TargetPolicy | _OrderPolicy,
        *,
        fitted: bool,
        transformed: bool = False,
        passive: bool = False,
        optimistic: bool = False,
        partition: Literal["validation", "holdout"] = "validation",
        family: str = "installed-decision-study",
    ) -> DecisionStudy:
        """Freeze every selected component and economic assumption in one typed config."""
        return DecisionStudy(
            family=family,
            source_identity=self.source.identity,
            feature_identity=self.feature.schema.identity,
            policy_identity=policy.identity,
            model_identity=(self.shifted_model if transformed else self.model).identity
            if fitted
            else None,
            transform_identity=self.transform.identity if transformed else None,
            label_identity=self.labels.identity if fitted else None,
            output=policy.output,
            calendar="continuous-utc",
            required_capabilities=(),
            folds=self.folds(fitted=fitted, holdout=partition == "holdout"),
            partition=partition,
            economics=IntentSimulationSpec(
                instance="installed-study-instance",
                entity=self.entity,
                source_identity=_Market(self, passive=passive).identity,
                start=self.at(9),
                end=self.at(45),
                initial_cash=Money(value=Decimal("1000"), currency=self.currency),
                limits=self.limits,
                execution_identity=(
                    self.optimistic_execution if optimistic else self.execution
                ).identity,
                cost_identity=self.costs.identity,
            ),
            metrics=(self.metric.identity,),
            charts=(self.chart.identity,),
            extensions=(self.artifact.fingerprint,),
        )


class _LostStudyAcknowledgement:
    """Lose one response after a real completed study to exercise retry reconciliation."""

    def __init__(self, handler: StudyJobHandler) -> None:
        """Bind the actual installed workflow and one bounded transport failure."""
        self._handler = handler
        self._lost = False

    def execute(self, spec: JobSpec, run: JobRun) -> bytes:
        """Retain the real completed effect before the first artificial response loss."""
        result = self._handler.execute(spec, run)
        if not self._lost:
            self._lost = True
            raise OSError("injected completed-study acknowledgement loss")
        return result


class _Run:
    """Assert the installed API's retained behavior with independent hand economics."""

    @staticmethod
    def read(root: Path) -> None:
        """Reopen typed results and custom reports in a fresh isolated process."""
        ids = msgspec.json.decode((root / "attempt-ids.json").read_bytes(), type=tuple[str, ...])
        store = AttemptStore(root / "attempts")
        for attempt in ids:
            result = StudyResult.read(store, attempt)
            report = StudyReportReader.read(store, attempt)
            assert len(result.folds) == 2
            assert tuple(f.economics.mark.net.value for f in result.folds) == (
                Decimal("-2.20"),
                Decimal("-2.20"),
            )
            assert report.metrics[0].definition.name == "installed-fill-count"
            assert report.metrics[0].value == ExactRatio(numerator="2", denominator="1")
            assert report.charts[0].title == "Custom fold net profit"
            assert b"Custom fold net profit" in store.artifact(attempt, "report-html")

    @staticmethod
    def jobs(
        root: Path, scenario: _Scenario, components: StudyComponents, study: DecisionStudy
    ) -> None:
        """Recover completed study effects and reopen queue/results after a clean restore."""
        workspace = root / "workspace"
        queue = JobQueue(workspace / "jobs")
        handler = StudyJobHandler({study.identity: components}, workspace / "studies")
        spec = schedule_study(
            queue,
            study,
            job_id="retained-study",
            run_at=scenario.at(0),
            publication=PublicationPolicy(mode="local"),
            retry_delay_seconds=0,
        )
        pool = JobWorkerPool(
            queue,
            {"decision-study": _LostStudyAcknowledgement(handler)},
            max_workers=2,
            implementation_sha256=ImplementationIdentity.sha256(),
            environment_sha256=StudyJobHandler.environment_sha256(),
        )
        pool.run_until_idle()
        state = queue.read(spec.job_id)
        assert state.status == "completed" and state.attempts == 2
        family = hashlib.sha256(study.family.encode()).hexdigest()
        store = AttemptStore(workspace / "studies" / family)
        histories = store.histories()
        assert len(histories) == 1 and histories[0].status == "completed"
        assert len(StudyResult.read(store, histories[0].start.attempt_id).folds) == 2
        queue.submit(spec)
        assert queue.read(spec.job_id) == state
        WorkspaceBackup.create(workspace, root / "workspace-backup", components=("jobs", "studies"))
        restored = root / "workspace-restored"
        WorkspaceBackup.restore(root / "workspace-backup", restored)
        assert JobQueue(restored / "jobs").read(spec.job_id) == state
        reopened = AttemptStore(restored / "studies" / family)
        assert reopened.histories() == histories
        assert StudyResult.read(reopened, histories[0].start.attempt_id) == StudyResult.read(
            store, histories[0].start.attempt_id
        )

    @staticmethod
    def execute(root: Path) -> None:
        """Run typed, serialized, search, local/deferred and holdout paths."""
        root.mkdir(exist_ok=True)
        codec, scenario = DomainCodec(), _Scenario()
        buy = _TargetPolicy(scenario.dimension, threshold=5)
        flat = _TargetPolicy(scenario.dimension, threshold=100)
        failing = _TargetPolicy(scenario.dimension, threshold=5, fail=True)
        study = scenario.study(buy, fitted=True)
        components = scenario.components(buy, fitted=True)
        _Run.jobs(root, scenario, components, study)
        changed_payload = scenario.artifact.payload + b"\n# changed extension bytes\n"
        changed_artifact = StudyArtifact(
            fingerprint=Fingerprint(
                name=scenario.artifact.fingerprint.name,
                sha256=hashlib.sha256(changed_payload).hexdigest(),
            ),
            payload=changed_payload,
        )
        changed_study = replace(study, extensions=(changed_artifact.fingerprint,))
        assert changed_study.identity != study.identity
        attempts = root / "attempts"
        local = PublicationPolicy(mode="local")
        first = evaluate_study(study, components=components, attempts=attempts, publication=local)
        assert first.status == "completed"
        assert (
            Fingerprint(
                name=f"extension:{scenario.artifact.fingerprint.name}",
                sha256=scenario.artifact.fingerprint.sha256,
            )
            in first.start.spec.components
        )
        config = root / "study.json"
        config.write_bytes(codec.encode_json(study))
        changed_config = root / "changed-study.json"
        changed_config.write_bytes(codec.encode_json(changed_study))
        assert DecisionStudy.read(config).identity == study.identity
        assert DecisionStudy.read(changed_config).identity == changed_study.identity
        assert DecisionStudy.read(changed_config).identity != DecisionStudy.read(config).identity
        destination = ClearMLDestination(
            project="installed-studies",
            api_uri="http://127.0.0.1:18008",
            files_uri="http://127.0.0.1:18081",
        )
        second = evaluate_study(
            config,
            components=components,
            attempts=attempts,
            publication=PublicationPolicy(mode="deferred", destination=destination),
        )
        assert second.status == "completed"
        store = AttemptStore(attempts)
        assert "clearml-destination" not in store.artifacts(first.start.attempt_id)
        assert "clearml-destination" in store.artifacts(second.start.attempt_id)
        assert "clearml-receipt" not in store.artifacts(second.start.attempt_id)
        for history in (first, second):
            assert (
                store.artifact(history.start.attempt_id, "extension-0000")
                == Path(__file__).read_bytes()
            )
            result = StudyResult.read(store, history.start.attempt_id)
            assert len(result.folds) == 2
            for fold, trained in zip(result.folds, ((1, 2), (3, 4)), strict=True):
                assert fold.model is not None
                assert len(fold.model.fit_rows) == 2
                assert (
                    tuple(int(value) for value in fold.model.state.decode().split(",")) == trained
                )
                assert fold.economics.mark.net.value == Decimal("-2.20")
                assert fold.economics.ledger.fills[0].effective.value == Decimal("101")
                assert fold.economics.ledger.fills[0].fee.value == Decimal("0.20")
                assert not any(item.status == "holdout_consumed" for item in history.events)
        (root / "attempt-ids.json").write_bytes(
            codec.encode_json((first.start.attempt_id, second.start.attempt_id))
        )
        subprocess.run([sys.executable, "-I", __file__, str(root), "read"], check=True, timeout=90)
        rule = scenario.study(flat, fitted=False, family="installed-rule-only-control")
        rule_result = evaluate_study(
            rule,
            components=scenario.components(flat, fitted=False),
            attempts=attempts,
            publication=local,
        )
        assert rule_result.status == "completed"
        assert (
            StudyResult.read(store, rule_result.start.attempt_id).folds[0].economics.mark.net.value
            == 0
        )
        shifted_policy = _TargetPolicy(scenario.dimension, threshold=0)
        shifted = scenario.study(
            shifted_policy, fitted=True, transformed=True, family="installed-shifted-study"
        )
        shifted_history = evaluate_study(
            shifted,
            components=scenario.components(shifted_policy, fitted=True, transformed=True),
            attempts=attempts,
            publication=local,
        )
        assert shifted_history.status == "completed"
        shifted_result = StudyResult.read(store, shifted_history.start.attempt_id)
        for fold, center, prediction in zip(
            shifted_result.folds,
            (b"3/2", b"7/2"),
            (
                ExactRatio(numerator="11", denominator="2"),
                ExactRatio(numerator="9", denominator="2"),
            ),
            strict=True,
        ):
            assert fold.transform is not None and fold.transform.state == center
            assert fold.model is not None and fold.model.state == b"shifted-training-only"
            assert fold.transform.fit_rows == fold.model.fit_rows
            assert len(fold.transform.fit_rows) == 2
            assert tuple(item.value for item in fold.predictions) == (prediction,)
            assert fold.economics.mark.net.value == Decimal("-2.20")
        order_policy = _OrderPolicy(scenario)
        for optimistic, filled_at, ahead in (
            (False, scenario.at(14), scenario.quantity("2")),
            (True, scenario.at(13), scenario.quantity("0")),
        ):
            order_study = scenario.study(
                order_policy,
                fitted=False,
                passive=True,
                optimistic=optimistic,
                family=f"installed-passive-order-{optimistic}",
            )
            order_history = evaluate_study(
                order_study,
                components=scenario.components(
                    order_policy, fitted=False, passive=True, optimistic=optimistic
                ),
                attempts=attempts,
                publication=local,
            )
            assert order_history.status == "completed"
            order_result = StudyResult.read(store, order_history.start.attempt_id).folds[0]
            assert order_result.decisions[0].intent == OrderIntent(
                side="buy",
                quantity=scenario.quantity("1"),
                limit=scenario.price("99"),
                time_in_force="post-only",
            )
            assert len(order_result.economics.orders) == 1
            order = order_result.economics.orders[0]
            assert order.status == "filled" and order.queue_ahead == ahead
            assert len(order.fills) == 1 and order.fills[0].filled_at == filled_at
            assert order.fills[0].effective.value == Decimal("99")
            assert order.fills[0].fee.value == Decimal("0.20")
            assert order_result.economics.mark.net.value == Decimal("-0.20")
            order_report = StudyReportReader.read(store, order_history.start.attempt_id)
            assert order_report.metrics[0].value == ExactRatio(numerator="1", denominator="1")
            assert order_report.charts[0].observations[0].value == ExactRatio(
                numerator="-1", denominator="5"
            )
            assert b"Custom fold net profit" in store.artifact(
                order_history.start.attempt_id, "report-html"
            )
        boundary = scenario.study(flat, fitted=False, family="installed-contiguous-validation")
        boundary_fold = boundary.folds[0]
        boundary = replace(
            boundary,
            folds=(
                replace(
                    boundary_fold,
                    split=replace(
                        boundary_fold.split,
                        validation=TimeWindow(
                            start=boundary_fold.split.validation.start,
                            end=boundary_fold.split.holdout.start,
                        ),
                    ),
                ),
            ),
        )
        boundary_history = evaluate_study(
            boundary,
            components=scenario.components(flat, fitted=False),
            attempts=attempts,
            publication=local,
        )
        assert boundary_history.status == "completed"
        retained_market = msgspec.json.decode(
            store.artifact(boundary_history.start.attempt_id, "market-0000"),
            type=tuple[_MarketClocks, ...],
        )
        assert retained_market
        assert max(row.source_at for row in retained_market) < boundary_fold.split.holdout.start
        assert (
            max(max(row.source_at, row.known_at) for row in retained_market)
            < boundary_fold.split.holdout.start
        )
        shifted_source_study = scenario.study(
            flat, fitted=False, family="installed-shifted-source-rejected"
        )
        try:
            evaluate_study(
                shifted_source_study,
                components=dataclass_replace(
                    scenario.components(flat, fitted=False),
                    source=_ShiftedDecisionSource(scenario.source),
                ),
                attempts=attempts,
                publication=local,
            )
        except ValueError as error:
            assert "source input differs" in str(error)
        else:
            raise AssertionError("source silently advanced the declared decision cutoff")
        shifted_source_attempts = tuple(
            history
            for history in store.histories()
            if history.start.spec.family == shifted_source_study.family
        )
        assert len(shifted_source_attempts) == 1
        failed_source = shifted_source_attempts[0]
        assert (
            failed_source.status == "failed"
            and failed_source.start.request == codec.encode_json(shifted_source_study)
        )
        failed_artifacts = store.artifacts(failed_source.start.attempt_id)
        assert "inputs-0000" in failed_artifacts
        captured_inputs = msgspec.json.decode(
            store.artifact(failed_source.start.attempt_id, "inputs-0000"),
            type=tuple[_DecisionInputClock, ...],
        )
        assert len(captured_inputs) == 1
        assert captured_inputs[0].entity == scenario.entity
        assert captured_inputs[0].decision_at == scenario.at(10) + timedelta(microseconds=1)
        assert not {
            "features-0000",
            "market-0000",
            "fold-0000",
            "study-result",
            "study-report",
            "report-html",
        } & set(failed_artifacts)
        variants = (
            study,
            scenario.study(flat, fitted=True),
            scenario.study(failing, fitted=True),
        )
        search = DecisionComparison(
            name="installed-decision-search",
            variants=variants,
            budget=3,
            seed=17,
            minimum_return=ExactRatio(numerator="-1", denominator="1"),
        )
        bindings = {
            run.identity: scenario.components(policy, fitted=True)
            for run, policy in zip(variants, (buy, flat, failing), strict=True)
        }
        journal = root / "search.log"
        early = compare_studies(
            search,
            bindings=bindings,
            attempts=attempts,
            journal=journal,
            publication=local,
            max_trials=1,
        )
        assert len(early) == 1
        original_history = store.read(early[0])
        assert "clearml-destination" not in store.artifacts(early[0])
        deferred = PublicationPolicy(mode="deferred", destination=destination)
        searched = compare_studies(
            search, bindings=bindings, attempts=attempts, journal=journal, publication=deferred
        )
        assert len(searched) == 3
        assert store.read(early[0]) == original_history
        searched_histories = {item: store.read(item) for item in searched}
        for item, history in searched_histories.items():
            assert codec.decode_json(history.start.request, DecisionStudy).identity in bindings
            assert (
                codec.decode_json(store.artifact(item, "clearml-destination"), ClearMLDestination)
                == destination
            )
            assert "clearml-receipt" not in store.artifacts(item)
        assert (
            compare_studies(
                search, bindings=bindings, attempts=attempts, journal=journal, publication=deferred
            )
            == searched
        )
        assert {item: store.read(item) for item in searched} == searched_histories
        assert all("clearml-receipt" not in store.artifacts(item) for item in searched)
        assert {store.read(item).status for item in searched} == {"completed", "failed"}
        assert not any(
            event.status == "holdout_consumed"
            for item in searched
            for event in store.read(item).events
        )
        holdout = scenario.study(buy, fitted=True, partition="holdout")
        try:
            evaluate_study(
                holdout,
                components=scenario.components(buy, fitted=True, fail_holdout_market=True),
                attempts=attempts,
                publication=local,
            )
        except OSError as error:
            assert "holdout market" in str(error)
        else:
            raise AssertionError("holdout read failure was not propagated")
        consumed = tuple(
            history
            for history in store.histories()
            if history.start.spec.family == holdout.family
            and any(event.status == "holdout_consumed" for event in history.events)
        )
        assert len(consumed) == 1 and consumed[0].status == "failed"
        try:
            evaluate_study(
                scenario.study(flat, fitted=True, partition="holdout"),
                components=scenario.components(flat, fitted=True),
                attempts=attempts,
                publication=local,
            )
        except ValueError as error:
            assert "already consumed" in str(error)
        else:
            raise AssertionError("changed run reused the family holdout")
        print(
            codec.encode_json(
                {
                    "typed_and_json": True,
                    "fresh_model_feature_policy_metric_chart": True,
                    "fitted_transform_train_only": True,
                    "passive_order_queue_sensitive": True,
                    "contiguous_validation_precedes_holdout": True,
                    "shifted_source_rejected": True,
                    "walk_forward_folds": 2,
                    "deferred_retained": True,
                    "search_attempts": len(searched),
                    "failed_holdout_recorded": True,
                    "job_retry_single_study_and_workspace_restore": True,
                }
            ).decode()
        )


if __name__ == "__main__":
    _Run.read(Path(sys.argv[1])) if len(sys.argv) == 3 else _Run.execute(Path(sys.argv[1]))
