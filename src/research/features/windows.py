"""Calculate exact observed-price returns from independently admitted cutoff windows."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Literal, NamedTuple, Protocol

# project library imports
from financial_units import ExactRatio
from market_data.contracts import ArchiveTrade, Disconnect, Occurrence, Trade
from market_data.query import (
    ContinuityResumed,
    InputBinding,
    QueryBatch,
    QueryEvidence,
    QueryMarketRow,
)
from market_data.validation import TradeRevision
from serialization import DomainCodec, WireRecord


class PricePoint(NamedTuple):
    """Retain revision identity, distinct business/event/knowledge clocks and native price."""

    identity: str
    business_at: datetime
    event_at: datetime | None
    available_at: datetime
    price: Decimal


class PriceWindow(NamedTuple):
    """Expose a bounded window including missingness and unprojectable quality evidence."""

    query_identity: str
    binding: InputBinding
    start: datetime
    end: datetime
    known_at: datetime
    points: tuple[PricePoint, ...]
    missing: str | None
    evidence: tuple[QueryEvidence, ...]
    controls: tuple[Occurrence, ...]
    # Disconnect recoveries the window relied on (only when its policy accepts them).
    recoveries: tuple[ContinuityResumed, ...] = ()


class FeatureValue(NamedTuple):
    """Keep a feature vector value independent of forward outcomes and their identities."""

    definition_identity: str
    decision_at: datetime
    available_at: datetime
    window: PriceWindow
    value: ExactRatio | None


class WindowPolicy(WireRecord, frozen=True, kw_only=True):
    """Require a complete declared window, enough trades and a fresh final event.

    Missing values stay missing. Scoped disconnects conservatively invalidate a
    window, including retained boundary controls, unless the policy opts in to the
    weaker first-binding-message recovery and every disconnect was answered before
    the window started. Observed values never establish complete empirical coverage.
    """

    lookback_us: int
    min_trades: int
    max_staleness_us: int
    clock: Literal["query-business"] = "query-business"
    # Opt in to the weaker recovery basis: the first same-binding trade after a
    # disconnect stands in for proof that the subscription resumed.
    accept_first_binding_message: bool = False

    def __post_init__(self) -> None:
        """Bound integer windows and reject invalid warm-up/freshness choices."""
        if (
            self.clock != "query-business"
            or type(self.lookback_us) is not int
            or not 0 < self.lookback_us <= 31_536_000_000_000
            or type(self.min_trades) is not int
            or not 1 <= self.min_trades <= 1_000_000
            or type(self.max_staleness_us) is not int
            or not 0 <= self.max_staleness_us <= self.lookback_us
            or type(self.accept_first_binding_message) is not bool
        ):
            raise ValueError("invalid window, warm-up count or staleness in microseconds")

    def collect(
        self,
        batches: tuple[QueryBatch, ...],
        *,
        binding: InputBinding,
        end: datetime,
        known_at: datetime,
    ) -> PriceWindow:
        """Reduce one binding from a trusted cutoff query, retaining its complete evidence.

        Args:
            batches: Complete admitted query with a revision column; batch size is immaterial.
            binding: One source/stream/instrument; prices never cross bindings or units.
            end: Exclusive UTC business end; start is end minus the configured lookback.
            known_at: Inclusive UTC revision/membership cutoff used by the query.

        Returns:
            Business-ordered prices, stable query identity and an explicit missing reason.
            Captured trades use valid_from; archives use ts_event, as in QueryReader.
            Equal business times retain query knowledge/precedence/raw-position order.

        Raises:
            ValueError: Batches mix queries, omit revisions or violate the cutoff contract.
            TypeError: A projected revision is malformed or is not a trade.
        """
        self.__post_init__()
        self._require_utc(end, field_name="end")
        self._require_utc(known_at, field_name="known_at")
        start = end - timedelta(microseconds=self.lookback_us)
        if not batches or any(
            batch.mode != "cutoff"
            or "revision" not in batch.columns
            or batch._replace(rows=()) != batches[0]._replace(rows=())
            for batch in batches
        ):
            raise ValueError("window requires one complete cutoff query with revisions")
        recoveries = batches[0].recoveries
        if recoveries is None and self.accept_first_binding_message:
            raise ValueError(
                "policy accepts first-binding-message recovery the query did not request"
            )
        evidence = tuple(
            item
            for item in batches[0].evidence
            if (
                item.request.instrument.source,
                item.request.manifest.job.stream,
                item.request.instrument.instrument_id,
            )
            == binding
        )
        if not evidence:
            raise ValueError("window binding has no admitted evidence")
        units = {
            (item.request.instrument.quote_currency.code, item.request.instrument.product)
            for item in evidence
        }
        if len(units) != 1:
            raise ValueError("window binding has conflicting units")
        points: list[PricePoint] = []
        controls: list[Occurrence] = []
        for batch in batches:
            for row in batch.rows:
                if isinstance(row, QueryMarketRow):
                    if row.binding != binding:
                        continue
                    version = row.values[batch.columns.index("revision")]
                    if not isinstance(version, TradeRevision):
                        raise TypeError("window requires trade revisions")
                    version.__post_init__()
                    event = version.occurrences[0].event
                    if not isinstance(event, (Trade, ArchiveTrade)):
                        raise TypeError("window requires trade events")
                    business_at = (
                        event.ts_event
                        if isinstance(event, ArchiveTrade)
                        else event.provenance.valid_from
                    )
                    available = version.ts_knowledge
                    if available is None or available > known_at or not start <= business_at < end:
                        raise ValueError("window input violates business or knowledge cutoff")
                    event_at = (
                        event.ts_event
                        if isinstance(event, ArchiveTrade)
                        else event.provenance.ts_event
                    )
                    points.append(
                        PricePoint(version.identity, business_at, event_at, available, event.price)
                    )
                elif (
                    row.request.instrument.source,
                    row.request.manifest.job.stream,
                    row.request.instrument.instrument_id,
                ) == binding:
                    controls.append(row)
        points.sort(key=self._event_time)
        covered = start
        for left, right in sorted(
            (
                max(item.request.start, item.request.manifest.job.start),
                min(item.request.end, item.request.manifest.job.end),
            )
            for item in evidence
        ):
            if left > covered:
                break
            covered = max(covered, right)
        missing: str | None = None
        used: tuple[ContinuityResumed, ...] = ()
        if covered < end:
            missing = "warm-up: window extends outside saved request coverage"
        elif controls:
            missing, used = self._recover(controls, recoveries or (), binding, start, known_at)
        if missing is None:
            missing = self._shortfall(points, end)
        return PriceWindow(
            batches[0].identity,
            binding,
            start,
            end,
            known_at,
            tuple(points),
            missing,
            evidence,
            tuple(controls),
            used if missing is None else (),
        )

    def _recover(
        self,
        controls: list[Occurrence],
        recoveries: tuple[ContinuityResumed, ...],
        binding: InputBinding,
        start: datetime,
        known_at: datetime,
    ) -> tuple[str | None, tuple[ContinuityResumed, ...]]:
        """Pair every scoped disconnect with a recovery before the window, if accepted.

        Returns:
            The missing reason, or None with the recoveries relied on.
        """
        if not self.accept_first_binding_message:
            return "scoped disconnect: recovery is unproven", ()
        # Each disconnect's answers, in order, by its identity; one pass, not one per control.
        answers: dict[str, list[ContinuityResumed]] = {}
        for item in recoveries:
            if item.binding == binding:
                answers.setdefault(item.disconnect_identity, []).append(item)
        used: list[ContinuityResumed] = []
        for control in controls:
            event = control.event
            if not isinstance(event, Disconnect):
                return "scoped control: recovery is unproven", ()
            if event.provenance.valid_from >= start:
                return "scoped disconnect inside window", ()
            answer = next(
                (item for item in answers.get(control.identity, ()) if item.known_at <= known_at),
                None,
            )
            if answer is None:
                return "scoped disconnect: recovery is unproven", ()
            if answer.resumed_at > start:
                return "scoped disconnect: recovery after window start", ()
            used.append(answer)
        return None, tuple(used)

    def _shortfall(self, points: list[PricePoint], end: datetime) -> str | None:
        """Explain why the collected trades cannot give a value, if they cannot."""
        if len(points) < self.min_trades:
            return "insufficient available trades"
        if end - points[-1].business_at > timedelta(microseconds=self.max_staleness_us):
            return "stale final trade"
        if any(point.price <= 0 for point in points):
            return "nonpositive price is unsupported for returns"
        return None

    @staticmethod
    def _event_time(point: PricePoint) -> datetime:
        """Keep admitted query order as the stable tie breaker for equal business times."""
        return point.business_at


class TrailingReturn(WireRecord, frozen=True, kw_only=True):
    """Version last/first minus one over a completed observed-price window.

    The decision schedule is anchored by the study's first decision. Processing
    delay shifts the exclusive window end and knowledge cutoff earlier than the
    decision. There is no fit, imputation, resampling or executable-price claim.
    """

    schema_version: Literal["trailing-return"] = "trailing-return"
    units: Literal["dimensionless"] = "dimensionless"
    policy: WindowPolicy
    cadence_us: int
    processing_delay_us: int

    def __post_init__(self) -> None:
        """Require supported formula/units and explicit cadence and processing delay."""
        if self.schema_version != "trailing-return" or self.units != "dimensionless":
            raise ValueError("unsupported trailing-return definition")
        if type(self.policy) is not WindowPolicy:
            raise TypeError("trailing return requires WindowPolicy")
        self.policy.__post_init__()
        if self.policy.min_trades < 2:
            raise ValueError("trailing return requires at least two trades")
        if (
            type(self.cadence_us) is not int
            or not 0 < self.cadence_us <= 31_536_000_000_000
            or type(self.processing_delay_us) is not int
            or not 0 <= self.processing_delay_us <= 31_536_000_000_000
        ):
            raise ValueError("invalid cadence or processing delay in microseconds")

    @property
    def identity(self) -> str:
        """Hash the formula version, units and all window/availability choices.

        Returns:
            SHA-256 of the immutable definition.
        """
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()

    def evaluate(
        self, batches: tuple[QueryBatch, ...], *, binding: InputBinding, decision_at: datetime
    ) -> FeatureValue:
        """Calculate the exact feature without accessing any forward outcome.

        Args:
            batches: Admitted cutoff window ending at decision minus processing delay.
            binding: Explicit source/stream/instrument with native price units.
            decision_at: UTC decision and declared feature availability time.

        Returns:
            Exact dimensionless return or explicit missingness with selected input identities.
        """
        self.__post_init__()
        end = self._require_utc(decision_at, field_name="decision_at") - timedelta(
            microseconds=self.processing_delay_us
        )
        window = self.policy.collect(batches, binding=binding, end=end, known_at=end)
        value = (
            None
            if window.missing
            else ExactRatio.from_fraction(
                Fraction(window.points[-1].price) / Fraction(window.points[0].price) - 1
            )
        )
        return FeatureValue(self.identity, decision_at, decision_at, window, value)


class FeatureDefinition(Protocol):
    """Describe the narrow causal contract shared by registered feature definitions."""

    @property
    def schema_version(self) -> str:
        """Identify the implementation/schema contract.

        Returns:
            Stable schema identity for the feature definition.
        """
        ...

    @property
    def units(self) -> str:
        """Identify the feature output units.

        Returns:
            Units of each emitted feature value.
        """
        ...

    @property
    def policy(self) -> WindowPolicy:
        """Expose the causal window policy.

        Returns:
            Immutable policy governing coverage, warm-up and freshness.
        """
        ...

    @property
    def cadence_us(self) -> int:
        """Expose the decision cadence in microseconds.

        Returns:
            Positive interval between scheduled feature decisions.
        """
        ...

    @property
    def processing_delay_us(self) -> int:
        """Expose the feature processing delay in microseconds.

        Returns:
            Delay between the decision and the latest admissible observation.
        """
        ...

    @property
    def identity(self) -> str:
        """Identify the immutable feature formula and its resolved parameters.

        Returns:
            Stable identity of the resolved definition and its parameters.
        """
        ...

    def __post_init__(self) -> None:
        """Validate the definition before a consumer uses it.

        Raises:
            ValueError: If the definition violates its schema or timing contract.
        """
        ...

    def evaluate(
        self, batches: tuple[QueryBatch, ...], *, binding: InputBinding, decision_at: datetime
    ) -> FeatureValue:
        """Evaluate one causal feature value from admitted cutoff batches.

        Args:
            batches: Admitted cutoff query batches containing the causal window.
            binding: Source/stream/instrument identity for the requested window.
            decision_at: UTC decision timestamp at which the value is available.

        Returns:
            Feature value retaining its definition, window and availability identity.
        """
        ...


class FeatureFactory(Protocol):
    """Construct a compatible evaluator for one registered implementation ID."""

    def __call__(self, definition: TrailingReturn) -> FeatureDefinition:
        """Construct one evaluator from the retained typed definition.

        Args:
            definition: Immutable definition supplied by the research study.

        Returns:
            Evaluator preserving the definition's causal contract.
        """
        ...


class FeatureRegistry:
    """Resolve compatible feature evaluators through explicit versioned factories."""

    def __init__(self) -> None:
        """Register the existing trailing-return implementation by default."""
        self._factories: dict[str, FeatureFactory] = {}
        self.register("trailing-return", self._validate_trailing_return)

    @property
    def identities(self) -> tuple[str, ...]:
        """Return registered feature implementation identities in insertion order.

        Returns:
            Stable implementation identities available to this registry.
        """
        return tuple(self._factories)

    def register(self, identity: str, factory: FeatureFactory) -> None:
        """Register one feature implementation under a unique engine identity.

        Args:
            identity: Stable implementation/engine identity.
            factory: Evaluator factory for typed definitions under that identity.

        Raises:
            ValueError: If the identity is invalid or already registered.
        """
        identity = self._validate_identity(identity)
        if identity in self._factories:
            raise ValueError(f"duplicate feature implementation identity: {identity}")
        self._factories[identity] = factory

    def resolve(self, identity: str, definition: TrailingReturn) -> FeatureDefinition:
        """Construct one evaluator and enforce the retained feature contract.

        Args:
            identity: Registered implementation/engine identity.
            definition: Immutable trailing-return definition selected by a study.

        Returns:
            Compatible feature evaluator for the study.

        Raises:
            ValueError: If no implementation is registered or the evaluator changes
                the definition's identity, units, window or timing contract.
        """
        identity = self._validate_identity(identity)
        factory = self._factories.get(identity)
        if factory is None:
            raise ValueError(f"unsupported installed feature: {identity}")
        evaluator = factory(definition)
        if (
            evaluator.schema_version != definition.schema_version
            or evaluator.identity != definition.identity
            or evaluator.units != definition.units
            or evaluator.policy != definition.policy
            or evaluator.cadence_us != definition.cadence_us
            or evaluator.processing_delay_us != definition.processing_delay_us
        ):
            raise ValueError("feature evaluator changes the selected definition contract")
        evaluator.__post_init__()
        return evaluator

    def supports(self, identity: str) -> bool:
        """Report whether one implementation identity is registered.

        Args:
            identity: Candidate feature implementation identity.

        Returns:
            Whether the identity is registered.
        """
        return type(identity) is str and bool(identity) and identity in self._factories

    @staticmethod
    def _validate_identity(identity: str) -> str:
        """Validate one nonempty, trimmed implementation identity."""
        if type(identity) is not str or not identity or identity != identity.strip():
            raise ValueError("feature implementation identity must be a nonempty trimmed string")
        return identity

    @staticmethod
    def _validate_trailing_return(definition: TrailingReturn) -> FeatureDefinition:
        """Construct the maintained trailing-return evaluator."""
        if not isinstance(definition, TrailingReturn):
            raise TypeError("trailing-return implementation requires TrailingReturn")
        definition.__post_init__()
        return definition
