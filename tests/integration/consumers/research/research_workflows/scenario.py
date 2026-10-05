"""Define authored components and market inputs for installed decision workflows."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Literal

# third party library imports
import msgspec
from msgspec.structs import replace

# project library imports
from applications.explore import StudyComponents
from financial_units import Currency, Dimension, ExactRatio, Money, Price, Quantity, QuantityKind
from market_data.contracts import BookObservation, Level
from reference_data.instruments import InstrumentId
from research.experiments import Fingerprint, TemporalSplit, TimeWindow
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
from research.reports import ChartSpec, MetricValue, ReportContext, ReportObservation
from research.studies import DecisionStudy, StudyArtifact, StudyFold
from risk import SpotLimits
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
            implementation="installed-square-signal",
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
        return "installed-next-value-label"

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
        return "installed-training-only-estimator"

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
        return "installed-train-only-shift"

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
        return "installed-shifted-estimator"

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
        return f"installed-target-{self._threshold}-{'fail' if self._fail else 'run'}"

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
        return "installed-passive-bid-99"

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
        return "installed-synthetic-l2-passive" if self._passive else "installed-synthetic-l2"

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
            sha256=hashlib.sha256(b"installed-fill-count").hexdigest(),
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
            sha256=hashlib.sha256(b"installed-fold-profit").hexdigest(),
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
