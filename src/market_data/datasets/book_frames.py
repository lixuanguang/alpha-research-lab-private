"""Encode canonical book rows as exact deltas from the previous row in the same frame."""

from __future__ import annotations

# standard library imports
from bisect import bisect_left, insort
from decimal import Decimal
from itertools import pairwise

# third party library imports
import msgspec
from msgspec.structs import replace

# project library imports
from market_data.contracts import BookObservation, Level, Order

type _Pair = tuple[Decimal, Level]


class StoredBookRow(msgspec.Struct, frozen=True, forbid_unknown_fields=True, omit_defaults=True):
    """Hold one row's coordinates and either its whole visible state or its change.

    A whole row's ``orders``, ``bids`` and ``asks`` are its complete state. A delta
    row's are the entries set since the previous row, and its ``removed_*`` fields
    the entries removed. Removals apply before sets.
    """

    position: int
    epoch: int | None
    received_ns: int | None
    source_time: str | None
    sequence: int | None
    outcome: str
    status: str
    reason: str
    state_identity: str
    transition_ns: int | None = None
    last_durable_ns: int | None = None
    whole: bool = False
    orders: tuple[Order, ...] = ()
    bids: tuple[_Pair, ...] = ()
    asks: tuple[_Pair, ...] = ()
    removed_orders: tuple[str, ...] = ()
    removed_bids: tuple[Decimal, ...] = ()
    removed_asks: tuple[Decimal, ...] = ()


class _States:
    """Classify and compare book states exactly."""

    @staticmethod
    def representation(orders: object, bids: object, asks: object) -> int:
        """Classify a state as L3 (2), L2 (1) or absent (0)."""
        return 2 if orders else 1 if bids or asks else 0

    @staticmethod
    def base(orders: tuple[Order, ...], bids: tuple[_Pair, ...], asks: tuple[_Pair, ...]) -> int:
        """Classify a state that a delta may follow: L3 (2), L2 (1), or none (0).

        A delta rebuilds ascending order, so a state out of that order cannot be a base.
        """
        ascending = all(
            left[0] < right[0] for side in (bids, asks) for left, right in pairwise(side)
        ) and all(left.order_id < right.order_id for left, right in pairwise(orders))
        return _States.representation(orders, bids, asks) if ascending else 0

    @staticmethod
    def same_decimal(left: Decimal, right: Decimal) -> bool:
        """Compare exact decimal text, not only value: ``1.0`` and ``1`` differ."""
        return left is right or left.as_tuple() == right.as_tuple()

    @staticmethod
    def same_level(left: Level, right: Level) -> bool:
        """Compare a level's exact size and order count."""
        return left is right or (
            left.order_count == right.order_count and _States.same_decimal(left.size, right.size)
        )

    @staticmethod
    def same_order(left: Order, right: Order) -> bool:
        """Compare an order's identity, side and exact price and size."""
        return left is right or (
            left.order_id == right.order_id
            and left.side == right.side
            and _States.same_decimal(left.price, right.price)
            and _States.same_decimal(left.size, right.size)
        )


class BookFrameEncoder:
    """Turn canonical rows into stored rows; a frame's first row is always whole.

    A delta rebuilds its state in ascending order, so a row is stored as a delta
    only when it and the row before it are both in that order. Published rows are,
    because both book producers sort; any other row is stored whole.
    """

    def __init__(self) -> None:
        """Start with no previous row."""
        self._representation = 0
        self._bids: dict[Decimal, _Pair] = {}
        self._asks: dict[Decimal, _Pair] = {}
        self._orders: dict[str, Order] = {}

    def encode(self, row: BookObservation, *, frame_start: bool) -> StoredBookRow:
        """Store a row whole, or as its exact change from the previous row.

        Args:
            row: Validated canonical row, with sorted sides and orders.
            frame_start: Whether this row opens a frame, so it cannot be a delta.

        Returns:
            The stored row to encode.
        """
        representation = _States.base(row.orders, row.bids, row.asks)
        whole = frame_start or representation == 0 or representation != self._representation
        base = StoredBookRow(
            row.position,
            row.epoch,
            row.received_ns,
            row.source_time,
            row.sequence,
            row.outcome,
            row.status,
            row.reason,
            row.state_identity,
            transition_ns=row.transition_ns,
            last_durable_ns=row.last_durable_ns,
        )
        self._representation = representation
        if whole:
            self._bids = {pair[0]: pair for pair in row.bids}
            self._asks = {pair[0]: pair for pair in row.asks}
            self._orders = {order.order_id: order for order in row.orders}
            return replace(base, whole=True, orders=row.orders, bids=row.bids, asks=row.asks)
        if representation == 2:
            orders, removed_orders = self._diff_orders(row.orders)
            return replace(base, orders=orders, removed_orders=removed_orders)
        bids, removed_bids, self._bids = self._diff_side(self._bids, row.bids)
        asks, removed_asks, self._asks = self._diff_side(self._asks, row.asks)
        return replace(
            base, bids=bids, asks=asks, removed_bids=removed_bids, removed_asks=removed_asks
        )

    @staticmethod
    def _diff_side(
        previous: dict[Decimal, _Pair], current: tuple[_Pair, ...]
    ) -> tuple[tuple[_Pair, ...], tuple[Decimal, ...], dict[Decimal, _Pair]]:
        """Return the levels set, the prices removed and the side's new map.

        A price whose exact text changed is removed and set again, so the rebuilt
        key carries the new text.
        """
        mapped = {pair[0]: pair for pair in current}
        removed = [price for price in previous if price not in mapped]
        changed: list[_Pair] = []
        for pair in current:
            old = previous.get(pair[0])
            if old is None:
                changed.append(pair)
            elif not _States.same_decimal(old[0], pair[0]):
                removed.append(old[0])
                changed.append(pair)
            elif not _States.same_level(old[1], pair[1]):
                changed.append(pair)
        return tuple(changed), tuple(removed), mapped

    def _diff_orders(self, current: tuple[Order, ...]) -> tuple[tuple[Order, ...], tuple[str, ...]]:
        """Return the orders upserted and the identities removed."""
        mapped = {order.order_id: order for order in current}
        removed = tuple(order_id for order_id in self._orders if order_id not in mapped)
        changed = tuple(
            order
            for order in current
            if (old := self._orders.get(order.order_id)) is None
            or not _States.same_order(old, order)
        )
        self._orders = mapped
        return changed, removed


class BookFrameDecoder:
    """Rebuild canonical rows from stored rows, refusing a delta without its base."""

    def __init__(self) -> None:
        """Start with no previous row."""
        self._representation = 0
        self._bids = _SortedState[Decimal, Level]()
        self._asks = _SortedState[Decimal, Level]()
        self._orders = _SortedState[str, Order]()

    def decode(self, stored: StoredBookRow, *, frame_start: bool) -> BookObservation:
        """Apply one stored row and return the exact canonical row.

        Args:
            stored: Decoded stored row.
            frame_start: Whether the row opens a frame.

        Returns:
            The canonical row, with sorted sides and orders.

        Raises:
            ValueError: A delta opens a frame, follows an absent state, mixes L2 and L3
                changes, or empties its state.
        """
        if frame_start:
            self._representation = 0
        try:
            orders, bids, asks = self._state(stored)
        except KeyError as error:
            raise ValueError("a book delta removes an absent entry") from error
        return BookObservation(
            stored.position,
            stored.epoch,
            stored.received_ns,
            stored.source_time,
            stored.sequence,
            stored.outcome,
            stored.status,
            stored.reason,
            stored.state_identity,
            orders=orders,
            bids=bids,
            asks=asks,
            transition_ns=stored.transition_ns,
            last_durable_ns=stored.last_durable_ns,
        )

    def _state(
        self, stored: StoredBookRow
    ) -> tuple[tuple[Order, ...], tuple[_Pair, ...], tuple[_Pair, ...]]:
        """Apply a stored row to the previous state and return the visible state."""
        if stored.whole:
            if stored.removed_orders or stored.removed_bids or stored.removed_asks:
                raise ValueError("a whole book row cannot remove entries")
            self._representation = _States.base(stored.orders, stored.bids, stored.asks)
            self._bids.reset(stored.bids)
            self._asks.reset(stored.asks)
            self._orders.reset(tuple((order.order_id, order) for order in stored.orders))
            return stored.orders, stored.bids, stored.asks
        if self._representation == 2:
            if stored.bids or stored.asks or stored.removed_bids or stored.removed_asks:
                raise ValueError("an L3 book delta cannot change levels")
            self._orders.apply(
                stored.removed_orders, tuple((order.order_id, order) for order in stored.orders)
            )
            if not self._orders:
                raise ValueError("a book delta cannot empty its state")
            return self._orders.values(), (), ()
        if self._representation == 1:
            if stored.orders or stored.removed_orders:
                raise ValueError("an L2 book delta cannot change orders")
            self._bids.apply(stored.removed_bids, stored.bids)
            self._asks.apply(stored.removed_asks, stored.asks)
            if not self._bids and not self._asks:
                raise ValueError("a book delta cannot empty its state")
            return (), self._bids.items(), self._asks.items()
        raise ValueError("a book delta requires a previous state in its frame")


class _SortedState[Key: (Decimal, str), Value: (Level, Order)]:
    """Keep entries with their keys in ascending order, updated in place.

    Setting an existing key keeps its stored key object, as a dict does, so a
    rebuilt price keeps the text of the row that first set it.
    """

    def __init__(self) -> None:
        """Start empty."""
        self._keys: list[Key] = []
        self._values: dict[Key, Value] = {}

    def __bool__(self) -> bool:
        """Return whether any entry is present."""
        return bool(self._keys)

    def reset(self, entries: tuple[tuple[Key, Value], ...]) -> None:
        """Replace every entry with ``entries``, already in ascending key order."""
        self._keys = [key for key, _ in entries]
        self._values = dict(entries)

    def apply(self, removed: tuple[Key, ...], changed: tuple[tuple[Key, Value], ...]) -> None:
        """Remove, then set, entries; removing an absent key raises ``KeyError``."""
        for key in removed:
            del self._values[key]
            del self._keys[bisect_left(self._keys, key)]
        for key, value in changed:
            if key not in self._values:
                insort(self._keys, key)
            self._values[key] = value

    def items(self) -> tuple[tuple[Key, Value], ...]:
        """Return every entry in ascending key order."""
        values = self._values
        return tuple((key, values[key]) for key in self._keys)

    def values(self) -> tuple[Value, ...]:
        """Return every value in ascending key order."""
        values = self._values
        return tuple(values[key] for key in self._keys)
