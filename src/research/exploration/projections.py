"""Project admitted saved trade/book/reference inputs into named decision observations."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction

# third party library imports
from msgspec.structs import replace

# project library imports
from financial_units import ExactRatio
from market_data.contracts import BookObservation, Order, TradeBoundary
from market_data.datasets import PublicTradeObservation
from market_data.query import BookMarketRow, PublicTradeResult
from reference_data.instruments import InstrumentId
from research.exploration.selection import (
    BookResearchInput,
    BookSelection,
    PublicTradeResearchInput,
    PublicTradeSelection,
    ReferenceResearchInput,
    ReferenceSelection,
    ResearchReader,
    ResearchSelection,
)
from research.observations import (
    DecisionInputs,
    InputRequirement,
    NamedObservation,
    ObservationHistory,
)
from serialization import DomainCodec


class SavedDecisionSource:
    """Reuse MR01 pinned readers per decision, never querying once at a future cutoff.

    Supported projections are public trade price, quantity and signed quantity of
    the latest trade, signed trade flow over ``(at - age, at]``, native L2/L3
    imbalance, and bitemporal minimum quantity. Trade fields and the flow window
    match ``LiveTradeDecisionSource``. Source families retain their own query rules.
    Non-book numeric datasets can use NumericHistorySource or a fresh DecisionSource.
    """

    def __init__(
        self,
        reader: ResearchReader,
        selection: ResearchSelection,
        requirements: tuple[InputRequirement, ...],
    ) -> None:
        """Bind a pinned selection and validate projection names/families before I/O."""
        selection.__post_init__()
        bindings = {item.name: item for item in selection.inputs}
        for requirement in requirements:
            requirement.__post_init__()
            item = bindings.get(requirement.name)
            supported = (
                (
                    isinstance(item, PublicTradeSelection)
                    and requirement.family == "trade"
                    and requirement.clock == "event"
                    and requirement.field.name
                    in ("price", "quantity", "signed_quantity", "signed_flow")
                )
                or (
                    isinstance(item, BookSelection)
                    and requirement.family == "book"
                    and requirement.clock in ("event", "receipt")
                    and requirement.field.name == "imbalance"
                )
                or (
                    isinstance(item, ReferenceSelection)
                    and requirement.family == "reference"
                    and requirement.clock == "valid"
                    and requirement.field.name == "minimum_quantity"
                )
            )
            if not supported:
                raise ValueError("unsupported saved decision projection")
            if isinstance(item, BookSelection) and item.query.columns not in (
                ("bids", "asks"),
                ("orders",),
            ):
                raise ValueError("book imbalance requires bid/ask or native-order projection")
        self._reader, self._selection, self._requirements = reader, selection, requirements

    @property
    def identity(self) -> str:
        """Pin source snapshots, query envelope and projection; paths are excluded."""
        return hashlib.sha256(
            DomainCodec().encode_json((self._selection.identity, self.requirements))
        ).hexdigest()

    @property
    def requirements(self) -> tuple[InputRequirement, ...]:
        """Expose the explicitly selected ordered fields and freshness policies."""
        return self._requirements

    def read(self, entity: str, at: datetime) -> DecisionInputs:
        """Read each saved input at this cutoff and preserve controls/unknown availability."""
        instrument = InstrumentId.from_canonical_text(entity)
        selections: list[PublicTradeSelection | BookSelection | ReferenceSelection] = []
        for selection in self._selection.inputs:
            if not isinstance(selection, (PublicTradeSelection, BookSelection, ReferenceSelection)):
                raise ValueError("trade selections use the window feature path, not projections")
            if at > selection.query.known_at:
                raise ValueError("decision exceeds pinned source observation cutoff")
            selections.append(replace(selection, query=replace(selection.query, known_at=at)))
        dataset = self._reader.read(ResearchSelection(inputs=tuple(selections)))
        rows: list[NamedObservation] = []
        for requirement in self.requirements:
            for item in dataset.inputs:
                if item.name != requirement.name:
                    continue
                if isinstance(item, PublicTradeResearchInput):
                    candidates = tuple(
                        row
                        for row in item.result.rows
                        if row.instrument.instrument_id == instrument and row.ts_event <= at
                    )
                    if self._captured_refusal(item.result, at) is not None:
                        continue
                    if requirement.field.name == "signed_flow":
                        rows.extend(self._flow(item, requirement, entity, at, candidates))
                        continue
                    for trade in (
                        () if not candidates else (max(candidates, key=self._trade_order),)
                    ):
                        definition = trade.instrument
                        units = (
                            f"{definition.quote_currency}/{definition.base_currency}"
                            if requirement.field.name == "price"
                            else definition.base_currency
                        )
                        self._units(requirement, units)
                        amount = (
                            Fraction(trade.trade.price)
                            if requirement.field.name == "price"
                            else Fraction(trade.trade.quantity)
                            if requirement.field.name == "quantity"
                            else self._signed(trade)
                        )
                        rows.append(
                            NamedObservation(
                                input=requirement,
                                entity=entity,
                                event_at=trade.ts_event,
                                available_at=trade.ts_knowledge,
                                value=ExactRatio.from_fraction(amount),
                                reason="observed_public_trade;complete_tape_unproven",
                                lineage=f"{item.result.query.identity}:{trade.source_sha256}:{trade.ordinal}:{trade.position}",
                            )
                        )
                elif isinstance(item, ReferenceResearchInput):
                    spec = item.history.resolve(instrument, valid_at=at, known_at=at)
                    if spec is not None:
                        self._units(requirement, spec.instrument.base_currency)
                        rows.append(
                            NamedObservation(
                                input=requirement,
                                entity=entity,
                                event_at=spec.valid_from,
                                available_at=spec.ts_knowledge,
                                value=None
                                if spec.minimum_quantity is None
                                else ExactRatio.from_fraction(Fraction(spec.minimum_quantity)),
                                reason="unknown_minimum"
                                if spec.minimum_quantity is None
                                else "versioned_reference_assertion",
                                lineage=spec.identity,
                            )
                        )
                elif isinstance(item, BookResearchInput):
                    rows.extend(self._book(item, requirement, entity))
        return ObservationHistory(tuple(rows)).select(entity, at, self.requirements)

    @classmethod
    def _flow(
        cls,
        item: PublicTradeResearchInput,
        requirement: InputRequirement,
        entity: str,
        at: datetime,
        candidates: tuple[PublicTradeObservation, ...],
    ) -> tuple[NamedObservation, ...]:
        """Sum aggressor-signed quantity of known trades with event time in the window."""
        start = at - timedelta(microseconds=requirement.max_age_us)
        if item.result.query.start > start:
            return ()
        definition = next(
            (row for row in item.result.instruments if str(row.instrument_id) == entity), None
        )
        if definition is None:
            return ()
        cls._units(requirement, definition.base_currency)
        boundary = cls._boundary(item.result, at)
        if boundary is not None and (
            boundary.covered_from is None or boundary.covered_from > start
        ):
            return ()
        window = tuple(row for row in candidates if row.ts_event > start)
        return (
            NamedObservation(
                input=requirement,
                entity=entity,
                event_at=at,
                available_at=at,
                value=ExactRatio.from_fraction(
                    sum((cls._signed(row) for row in window), Fraction())
                ),
                reason="observed_public_trades;complete_tape_unproven",
                lineage=hashlib.sha256(
                    DomainCodec().encode_json(
                        tuple(
                            f"{item.result.query.identity}:{row.source_sha256}:{row.ordinal}:{row.position}"
                            for row in window
                        )
                    )
                ).hexdigest(),
            ),
        )

    @staticmethod
    def _boundary(result: PublicTradeResult, at: datetime) -> TradeBoundary | None:
        """Return a captured source's latest boundary known by the cutoff, if captured."""
        return next((item for item in reversed(result.boundaries) if item.received_at <= at), None)

    @classmethod
    def _captured_refusal(cls, result: PublicTradeResult, at: datetime) -> str | None:
        """Apply the live trade source's stream rules to a captured source; REST has none."""
        if result.idle_seconds is None:
            return None
        boundary = cls._boundary(result, at)
        if boundary is None:
            return "no_live_input"
        if boundary.covered_from is None:
            return "trade_stream_unsynchronized"
        if at - boundary.received_at > timedelta(seconds=result.idle_seconds):
            return "stale_trade_stream"
        return None

    @staticmethod
    def _signed(row: PublicTradeObservation) -> Fraction:
        """Sign a trade's quantity by its aggressor side."""
        quantity = Fraction(row.trade.quantity)
        return quantity if row.trade.side == "buy" else -quantity

    @staticmethod
    def _trade_order(row: PublicTradeObservation) -> tuple[datetime, datetime, int, int]:
        """Select latest event, then local knowledge and retained response/position for ties."""
        return row.ts_event, row.ts_knowledge, row.ordinal, row.position

    @staticmethod
    def _units(requirement: InputRequirement, units: str) -> None:
        """Refuse unit relabeling at the source projection boundary."""
        if requirement.field.units != units:
            raise ValueError("saved projection units differ from source")

    @classmethod
    def _book(
        cls, item: BookResearchInput, requirement: InputRequirement, entity: str
    ) -> tuple[NamedObservation, ...]:
        """Respect native message order and invalidation controls; receipt rounds upward."""
        cls._units(requirement, "dimensionless")
        if str(item.batches[0].evidence.request.config.instrument_id) != entity:
            return ()
        rows = tuple(row for batch in item.batches for row in batch.rows)
        if not rows:
            return ()
        row = rows[-1]
        if row.received_ns is None:
            return ()
        received = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(
            microseconds=(row.received_ns + 999) // 1000
        )
        event = received
        has_source_clock = row.source_time is not None and row.source_time.isdigit()
        if (
            requirement.clock == "event"
            and row.source_time is not None
            and row.source_time.isdigit()
        ):
            event = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=int(row.source_time))
        value = None
        reason = "invalid_book_control"
        if isinstance(row, BookMarketRow):
            if item.batches[0].columns == ("orders",):
                orders = tuple(order for order in row.values[0] if isinstance(order, Order))
                bids = tuple((order.price, order.size) for order in orders if order.side == "buy")
                asks = tuple((order.price, order.size) for order in orders if order.side == "sell")
            else:
                bids = tuple(
                    (price, level.size)
                    for level_row in row.values[0]
                    if type(level_row) is tuple
                    for price, level in (level_row,)
                )
                asks = tuple(
                    (price, level.size)
                    for level_row in row.values[1]
                    if type(level_row) is tuple
                    for price, level in (level_row,)
                )
            if bids and asks and max(p for p, _ in bids) < min(p for p, _ in asks):
                bid = sum((Fraction(size) for _, size in bids), Fraction())
                ask = sum((Fraction(size) for _, size in asks), Fraction())
                if bid + ask > Fraction(Decimal(0)):
                    value = ExactRatio.from_fraction((bid - ask) / (bid + ask))
                    reason = "visible_depth_only"
            if requirement.clock == "event" and not has_source_clock:
                value, reason = None, "unknown_source_event_time"
        elif not isinstance(row, BookObservation):
            raise ValueError("unsupported book record")
        return (
            NamedObservation(
                input=requirement,
                entity=entity,
                event_at=event,
                available_at=received,
                value=value,
                reason=reason,
                lineage=f"{item.batches[0].identity}:{row.position}",
            ),
        )
