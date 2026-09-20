"""Calculate exact observed-price returns from independently admitted cutoff windows."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Literal, NamedTuple

# project library imports
from financial_units import ExactRatio
from market_data.contracts import ArchiveTrade, Occurrence, Trade
from market_data.query import InputBinding, QueryBatch, QueryEvidence, QueryMarketRow
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
    window, including retained boundary controls; this diagnostic claims no recovery.
    Observed values never establish complete empirical coverage.
    """

    lookback_us: int
    min_trades: int
    max_staleness_us: int
    clock: Literal["query-business"] = "query-business"

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
        if covered < end:
            missing = "warm-up: window extends outside saved request coverage"
        elif controls:
            missing = "scoped disconnect: recovery is unproven"
        elif len(points) < self.min_trades:
            missing = "insufficient available trades"
        elif end - points[-1].business_at > timedelta(microseconds=self.max_staleness_us):
            missing = "stale final trade"
        elif any(point.price <= 0 for point in points):
            missing = "nonpositive price is unsupported for returns"
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
        )

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

    schema_version: Literal["trailing-return-v1"] = "trailing-return-v1"
    units: Literal["dimensionless"] = "dimensionless"
    policy: WindowPolicy
    cadence_us: int
    processing_delay_us: int

    def __post_init__(self) -> None:
        """Require supported formula/units and explicit cadence and processing delay."""
        if self.schema_version != "trailing-return-v1" or self.units != "dimensionless":
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
