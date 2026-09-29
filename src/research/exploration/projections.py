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
from market_data.contracts import BookObservation, Order
from market_data.datasets import PublicTradeObservation
from market_data.query import BookMarketRow
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

    Supported projections are public trade price/quantity, native L2/L3 imbalance,
    and bitemporal minimum quantity. Source families retain their own query rules.
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
                    and requirement.field.name in ("price", "quantity")
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
                        if row.receipt.request.instrument.instrument_id == instrument
                        and row.ts_event <= at
                    )
                    for trade in (
                        () if not candidates else (max(candidates, key=self._trade_order),)
                    ):
                        definition = trade.receipt.request.instrument
                        units = (
                            f"{definition.quote_currency}/{definition.base_currency}"
                            if requirement.field.name == "price"
                            else definition.base_currency
                        )
                        self._units(requirement, units)
                        amount = (
                            trade.trade.price
                            if requirement.field.name == "price"
                            else trade.trade.quantity
                        )
                        rows.append(
                            NamedObservation(
                                input=requirement,
                                entity=entity,
                                event_at=trade.ts_event,
                                available_at=trade.ts_knowledge,
                                value=ExactRatio.from_fraction(Fraction(amount)),
                                reason="observed_public_trade;complete_tape_unproven",
                                lineage=f"{item.result.query.identity}:{trade.receipt.raw.sha256}:{trade.position}",
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

    @staticmethod
    def _trade_order(row: PublicTradeObservation) -> tuple[datetime, datetime, int, int]:
        """Select latest event, then local knowledge and retained response/position for ties."""
        return row.ts_event, row.ts_knowledge, row.receipt.request.ordinal, row.position

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
