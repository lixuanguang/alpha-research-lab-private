"""Project admitted saved trade/book/reference inputs into named decision observations."""

from __future__ import annotations

# standard library imports
import hashlib
from bisect import bisect_left, bisect_right
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from types import MappingProxyType
from typing import ClassVar

# third party library imports
from msgspec.structs import replace

# project library imports
from financial_units import ExactRatio
from market_data.contracts import BookObservation, Order, TradeBoundary
from market_data.datasets import PublicTradeObservation
from market_data.query import BookMarketRow, BookQuery, BookQueryReader, PublicTradeResult
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
    """Project pinned saved inputs at any decision cutoff from one verified read.

    Supported projections are public trade price, quantity and signed quantity of
    the latest trade, signed trade flow over ``(at - age, at]``, native L2/L3
    imbalance and touch (``ask``, ``bid``, ``ask_size``, ``bid_size``, with the live
    book source's units), and bitemporal minimum quantity. Trade fields and the flow window
    match ``LiveTradeDecisionSource``. Source families retain their own query rules.
    Non-book numeric datasets can use NumericHistorySource or a fresh DecisionSource.

    The selection is read once, at its own cutoff, on the first decision. Every
    later decision is answered from indexes over what was read: the last book row
    known by the cutoff, each trade's effective version at the cutoff (all observed
    versions are kept), captured trade boundaries and reference history. Results
    equal a fresh read at each decision's cutoff, including lineage, while cost no
    longer grows with decisions times records.
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
                    and _BookIndex.UNITS.get(requirement.field.name) == requirement.field.units
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
        self._indexes: dict[str, _BookIndex | _TradeIndex | ReferenceResearchInput] | None = None

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
        """Project each saved input at this cutoff and preserve controls/unknown availability."""
        instrument = InstrumentId.from_canonical_text(entity)
        for selection in self._selection.inputs:
            if at > selection.query.known_at:
                raise ValueError("decision exceeds pinned source observation cutoff")
        indexes = self._index()
        rows: list[NamedObservation] = []
        for requirement in self.requirements:
            index = indexes[requirement.name]
            if isinstance(index, _TradeIndex):
                rows.extend(index.project(requirement, entity, instrument, at))
            elif isinstance(index, _BookIndex):
                rows.extend(index.project(requirement, entity, at))
            else:
                spec = index.history.resolve(instrument, valid_at=at, known_at=at)
                if spec is not None:
                    _Projection.units(requirement, spec.instrument.base_currency)
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
        return ObservationHistory(tuple(rows)).select(entity, at, self.requirements)

    def _index(self) -> dict[str, _BookIndex | _TradeIndex | ReferenceResearchInput]:
        """Read and verify the whole selection once, at its own cutoff, and index it."""
        if self._indexes is not None:
            return self._indexes
        for selection in self._selection.inputs:
            if not isinstance(selection, (PublicTradeSelection, BookSelection, ReferenceSelection)):
                raise ValueError("trade selections use the window feature path, not projections")
        dataset = self._reader.read(self._selection)
        indexes: dict[str, _BookIndex | _TradeIndex | ReferenceResearchInput] = {}
        for item, selection in zip(dataset.inputs, self._selection.inputs, strict=True):
            if isinstance(item, PublicTradeResearchInput) and isinstance(
                selection, PublicTradeSelection
            ):
                indexes[item.name] = _TradeIndex(
                    item.result, self._reader.public_trade_versions(selection)
                )
            elif isinstance(item, BookResearchInput) and isinstance(selection, BookSelection):
                indexes[item.name] = _BookIndex(item, selection.query)
            elif isinstance(item, ReferenceResearchInput):
                indexes[item.name] = item
            else:
                raise ValueError("saved decision input differs from its selection")
        self._indexes = indexes
        return indexes


# A bound just before any query start, so the latest-trade range includes the start.
_EARLIER = timedelta(microseconds=1)


class _Projection:
    """Share unit checks and signed quantities across saved projections."""

    @staticmethod
    def units(requirement: InputRequirement, units: str) -> None:
        """Refuse unit relabeling at the source projection boundary."""
        if requirement.field.units != units:
            raise ValueError("saved projection units differ from source")

    @staticmethod
    def signed(row: PublicTradeObservation) -> Fraction:
        """Sign a trade's quantity by its aggressor side."""
        quantity = Fraction(row.trade.quantity)
        return quantity if row.trade.side == "buy" else -quantity


class _TradeIndex:
    """Resolve every selected trade's effective version at any cutoff.

    A read at cutoff ``at`` keeps, per trade, the latest *changed* version known by
    ``at``; an equal repeat keeps the earlier one. The index therefore keeps each
    trade's change points in knowledge order, and an event-ordered list of every
    change point for window and latest-trade lookups.
    """

    def __init__(self, result: PublicTradeResult, versions: tuple[PublicTradeObservation, ...]):
        """Index the result read at the selection's cutoff and all its known versions."""
        self._result = result
        self._query = result.query
        changes: dict[tuple[InstrumentId, str], list[PublicTradeObservation]] = {}
        for row in versions:
            key = row.instrument.instrument_id, row.trade.trade_id
            points = changes.setdefault(key, [])
            if not points or points[-1].trade != row.trade:
                points.append(row)
        self._changes = changes
        self._known = {key: [row.ts_knowledge for row in rows] for key, rows in changes.items()}
        listed: dict[InstrumentId, list[PublicTradeObservation]] = {}
        for rows in changes.values():
            for row in rows:
                listed.setdefault(row.instrument.instrument_id, []).append(row)
        self._points: dict[InstrumentId, list[PublicTradeObservation]] = {
            key: sorted(rows, key=self._event_order) for key, rows in listed.items()
        }
        self._events: dict[InstrumentId, list[datetime]] = {
            key: [row.ts_event for row in rows] for key, rows in self._points.items()
        }
        self._received = [item.received_at for item in result.boundaries]

    def project(
        self,
        requirement: InputRequirement,
        entity: str,
        instrument: InstrumentId,
        at: datetime,
    ) -> tuple[NamedObservation, ...]:
        """Project one trade field at the cutoff, applying captured stream rules first."""
        if self._refusal(at) is not None:
            return ()
        identity = replace(self._query, known_at=at).identity
        if requirement.field.name == "signed_flow":
            return self._flow(requirement, entity, instrument, at, identity)
        trade = self._latest(instrument, at)
        if trade is None:
            return ()
        definition = trade.instrument
        _Projection.units(
            requirement,
            f"{definition.quote_currency}/{definition.base_currency}"
            if requirement.field.name == "price"
            else definition.base_currency,
        )
        amount = (
            Fraction(trade.trade.price)
            if requirement.field.name == "price"
            else Fraction(trade.trade.quantity)
            if requirement.field.name == "quantity"
            else _Projection.signed(trade)
        )
        return (
            NamedObservation(
                input=requirement,
                entity=entity,
                event_at=trade.ts_event,
                available_at=trade.ts_knowledge,
                value=ExactRatio.from_fraction(amount),
                reason="observed_public_trade;complete_tape_unproven",
                lineage=self._lineage(identity, trade),
            ),
        )

    def _effective(self, row: PublicTradeObservation, at: datetime) -> bool:
        """Return whether this change point is its trade's version at the cutoff."""
        key = row.instrument.instrument_id, row.trade.trade_id
        position = bisect_right(self._known[key], at) - 1
        return position >= 0 and self._changes[key][position] is row

    def _range(self, instrument: InstrumentId, after: datetime, at: datetime) -> range:
        """Return positions of one instrument's change points with event in ``(after, at]``.

        The query's event interval ``[start, end)`` bounds the range as a read does.
        """
        events = self._events[instrument] if instrument in self._events else []
        low = max(bisect_right(events, after), bisect_left(events, self._query.start))
        high = min(bisect_right(events, at), bisect_left(events, self._query.end))
        return range(low, max(low, high))

    def _latest(self, instrument: InstrumentId, at: datetime) -> PublicTradeObservation | None:
        """Return the effective trade with the latest event, knowledge and position.

        Change points are scanned from the latest event down; the first effective one
        fixes the event, and only its ties are compared.
        """
        points = self._points[instrument] if instrument in self._points else []
        best: PublicTradeObservation | None = None
        for position in reversed(self._range(instrument, self._query.start - _EARLIER, at)):
            row = points[position]
            if best is not None and row.ts_event < best.ts_event:
                break
            if self._effective(row, at) and (
                best is None or self._trade_order(row) > self._trade_order(best)
            ):
                best = row
        return best

    def _flow(
        self,
        requirement: InputRequirement,
        entity: str,
        instrument: InstrumentId,
        at: datetime,
        identity: str,
    ) -> tuple[NamedObservation, ...]:
        """Sum aggressor-signed quantity of effective trades with event time in the window."""
        start = at - timedelta(microseconds=requirement.max_age_us)
        if self._query.start > start:
            return ()
        definition = next(
            (row for row in self._result.instruments if str(row.instrument_id) == entity), None
        )
        if definition is None:
            return ()
        _Projection.units(requirement, definition.base_currency)
        boundary = self._boundary(at)
        if boundary is not None and (
            boundary.covered_from is None or boundary.covered_from > start
        ):
            return ()
        points = self._points[instrument] if instrument in self._points else []
        window = sorted(
            (
                points[position]
                for position in self._range(instrument, start, at)
                if self._effective(points[position], at)
            ),
            key=self._read_order,
        )
        return (
            NamedObservation(
                input=requirement,
                entity=entity,
                event_at=at,
                available_at=at,
                value=ExactRatio.from_fraction(
                    sum((_Projection.signed(row) for row in window), Fraction())
                ),
                reason="observed_public_trades;complete_tape_unproven",
                lineage=hashlib.sha256(
                    DomainCodec().encode_json(tuple(self._lineage(identity, row) for row in window))
                ).hexdigest(),
            ),
        )

    def _boundary(self, at: datetime) -> TradeBoundary | None:
        """Return a captured source's latest boundary known by the cutoff, if captured."""
        position = bisect_right(self._received, at) - 1
        return self._result.boundaries[position] if position >= 0 else None

    def _refusal(self, at: datetime) -> str | None:
        """Apply the live trade source's stream rules to a captured source; REST has none."""
        if self._result.idle_seconds is None:
            return None
        boundary = self._boundary(at)
        if boundary is None:
            return "no_live_input"
        if boundary.covered_from is None:
            return "trade_stream_unsynchronized"
        if at - boundary.received_at > timedelta(seconds=self._result.idle_seconds):
            return "stale_trade_stream"
        return None

    @staticmethod
    def _lineage(identity: str, row: PublicTradeObservation) -> str:
        """Name one trade version within the query at the cutoff."""
        return f"{identity}:{row.source_sha256}:{row.ordinal}:{row.position}"

    @staticmethod
    def _event_order(row: PublicTradeObservation) -> tuple[datetime, datetime, int, int]:
        """Order change points by event, then knowledge and source position."""
        return row.ts_event, row.ts_knowledge, row.ordinal, row.position

    @staticmethod
    def _trade_order(row: PublicTradeObservation) -> tuple[datetime, datetime, int, int]:
        """Select latest event, then local knowledge and retained response/position for ties."""
        return row.ts_event, row.ts_knowledge, row.ordinal, row.position

    @staticmethod
    def _read_order(row: PublicTradeObservation) -> tuple[datetime, str, int, int]:
        """Order a window as a cutoff read returns rows: knowledge, listing, position."""
        return row.ts_knowledge, str(row.instrument.instrument_id), row.ordinal, row.position


class _BookIndex:
    """Return the last book row known by any cutoff from one read at the selection's cutoff.

    Fields and units equal ``LiveBookDecisionSource``'s: visible-depth imbalance and
    the touch prices and sizes, with native L3 orders aggregated by price.
    """

    UNITS: ClassVar[Mapping[str, str]] = MappingProxyType(
        {
            "imbalance": "dimensionless",
            "ask": "quote/base",
            "bid": "quote/base",
            "ask_size": "base",
            "bid_size": "base",
        }
    )

    def __init__(self, item: BookResearchInput, query: BookQuery) -> None:
        """Index rows in source order by exact receipt nanoseconds."""
        self._item, self._query = item, query
        # A capture clock changes no book, so a cutoff after one reads the row before it,
        # as the live source carries its market across a clock.
        self._rows = tuple(
            row
            for batch in item.batches
            for row in batch.rows
            if not (isinstance(row, BookObservation) and row.outcome == "clock")
        )
        self._received = [-1 if row.received_ns is None else row.received_ns for row in self._rows]

    def _fields(self, row: BookMarketRow) -> dict[str, ExactRatio] | None:
        """Aggregate visible depth by price and project imbalance and the touch."""
        bids: dict[Decimal, Fraction] = {}
        asks: dict[Decimal, Fraction] = {}
        if self._item.batches[0].columns == ("orders",):
            for order in row.values[0]:
                if isinstance(order, Order):
                    side = bids if order.side == "buy" else asks
                    side[order.price] = side.get(order.price, Fraction()) + Fraction(order.size)
        else:
            for side, levels in ((bids, row.values[0]), (asks, row.values[1])):
                for level_row in levels:
                    if type(level_row) is tuple:
                        price, level = level_row
                        side[price] = side.get(price, Fraction()) + Fraction(level.size)
        if not bids or not asks:
            return None
        bid_price, ask_price = max(bids), min(asks)
        bid_size, ask_size = sum(bids.values(), Fraction()), sum(asks.values(), Fraction())
        if bid_price >= ask_price or bid_size + ask_size <= 0:
            return None
        return {
            "imbalance": ExactRatio.from_fraction((bid_size - ask_size) / (bid_size + ask_size)),
            "ask": ExactRatio.from_fraction(Fraction(ask_price)),
            "bid": ExactRatio.from_fraction(Fraction(bid_price)),
            "ask_size": ExactRatio.from_fraction(asks[ask_price]),
            "bid_size": ExactRatio.from_fraction(bids[bid_price]),
        }

    def project(
        self, requirement: InputRequirement, entity: str, at: datetime
    ) -> tuple[NamedObservation, ...]:
        """Project one book field of the last row known at the cutoff."""
        _Projection.units(requirement, self.UNITS[requirement.field.name])
        if str(self._item.batches[0].evidence.request.config.instrument_id) != entity:
            return ()
        elapsed = at - datetime(1970, 1, 1, tzinfo=UTC)
        cutoff = (elapsed.days * 86_400 + elapsed.seconds) * 1_000_000_000 + (
            elapsed.microseconds * 1000
        )
        position = bisect_right(self._received, cutoff) - 1
        if position < 0:
            return ()
        row = self._rows[position]
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
            fields = self._fields(row)
            if fields is not None:
                value = fields[requirement.field.name]
                reason = "visible_depth_only"
            if requirement.clock == "event" and not has_source_clock:
                value, reason = None, "unknown_source_event_time"
        elif not isinstance(row, BookObservation):
            raise ValueError("unsupported book record")
        identity = BookQueryReader.identity(replace(self._query, known_at=at))
        return (
            NamedObservation(
                input=requirement,
                entity=entity,
                event_at=event,
                available_at=received,
                value=value,
                reason=reason,
                lineage=f"{identity}:{row.position}",
            ),
        )
