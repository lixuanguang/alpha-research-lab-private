"""Share exact aggregate depth and BBO projection across native and saved consumers."""

from __future__ import annotations

# standard library imports
from decimal import Decimal
from fractions import Fraction

# third party library imports
import msgspec
from msgspec.structs import replace

# project library imports
from financial_units import DecimalGrid
from market_data.books.protocol import NativeBook
from market_data.contracts import BookObservation, BookQuote, BookQuoteSide, Level
from reference_data.instruments import InstrumentId


class BookDepth(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Hold sorted exact visible levels; counts never imply native queue priority."""

    bids: tuple[tuple[Decimal, Level], ...]
    asks: tuple[tuple[Decimal, Level], ...]

    def __post_init__(self) -> None:
        """Reject malformed levels, duplicate prices and ambiguous ordering."""
        for side in (self.bids, self.asks):
            if type(side) is not tuple:
                raise ValueError("book depth requires immutable levels")
            previous: Decimal | None = None
            for price, level in side:
                if (
                    type(price) is not Decimal
                    or not price.is_finite()
                    or price <= 0
                    or (previous is not None and price <= previous)
                    or type(level) is not Level
                ):
                    raise ValueError("book depth requires sorted unique positive prices")
                level.__post_init__()
                previous = price

    @classmethod
    def from_observation(cls, row: BookObservation) -> BookDepth:
        """Aggregate native L3 orders or retain absolute L2 sizes without changing clocks.

        Args:
            row: Complete canonical observation, including control and invalid states.

        Returns:
            Sorted retained aggregate depth. Quote consumers separately gate its quality.
        """
        BookObservation.__post_init__(row)
        if not row.orders:
            return cls(tuple(sorted(row.bids)), tuple(sorted(row.asks)))
        totals: dict[tuple[str, Decimal], Fraction] = {}
        counts: dict[tuple[str, Decimal], int] = {}
        for order in row.orders:
            key = order.side, order.price
            totals[key] = totals.get(key, Fraction()) + Fraction(order.size)
            counts[key] = counts.get(key, 0) + 1
        levels = tuple(
            (side, price, Level(DecimalGrid.exact_decimal(total), counts[(side, price)]))
            for (side, price), total in sorted(totals.items())
        )
        return cls(
            tuple((price, level) for side, price, level in levels if side == "buy"),
            tuple((price, level) for side, price, level in levels if side == "sell"),
        )

    @classmethod
    def from_native(cls, book: NativeBook) -> BookDepth:
        """Read cached L2/L3 levels after successful apply; callers also gate replay quality.

        Args:
            book: Native reconstruction at a whole-message boundary, never during apply.

        Returns:
            An immutable copy of incremental levels, empty until synchronized.
        """
        return (
            cls(tuple(sorted(book.bids.items())), tuple(sorted(book.asks.items())))
            if book.ready
            else cls((), ())
        )

    @classmethod
    def project(cls, row: BookObservation) -> BookObservation:
        """Project L3 orders into L2 levels while retaining native metadata and quality.

        Args:
            row: Original canonical boundary; its bytes and identity remain authoritative.

        Returns:
            Aggregate observation for existing research depth consumers.
        """
        depth = cls.from_observation(row)
        return replace(row, orders=(), bids=depth.bids, asks=depth.asks)

    def quote(
        self,
        row: BookObservation,
        *,
        venue: str,
        instrument_id: InstrumentId,
        source_id: str,
        channel: str,
        available_ns: int | None,
    ) -> BookQuote:
        """Bind this boundary's depth to explicit source identity and delivery knowledge.

        Args:
            row: Metadata for the same complete message boundary as this depth.
            venue: Native venue owning this book.
            instrument_id: Canonical instrument, with no cross-venue equivalence implied.
            source_id: Explicit request or retained source identity.
            channel: Native stream representation.
            available_ns: Original delivery availability, or None when unknown.

        Returns:
            Common exact BBO; invalid/control boundaries expose no executable prices.
        """
        BookObservation.__post_init__(row)
        keep = row.status == "degraded" and row.outcome in ("snapshot", "update")
        bid = self.bids[-1] if self.bids and keep else None
        ask = self.asks[0] if self.asks and keep else None
        return BookQuote(
            venue=venue,
            instrument_id=instrument_id,
            source_id=source_id,
            channel=channel,
            position=row.position,
            epoch=row.epoch,
            sequence=row.sequence,
            source_time=row.source_time,
            received_ns=row.received_ns,
            available_ns=available_ns,
            outcome=row.outcome,
            status=row.status,
            reason=row.reason,
            state_identity=row.state_identity,
            bid=None if bid is None else BookQuoteSide(bid[0], bid[1].size, bid[1].order_count),
            ask=None if ask is None else BookQuoteSide(ask[0], ask[1].size, ask[1].order_count),
        )

    @staticmethod
    def touch_quote(
        row: BookObservation,
        *,
        venue: str,
        instrument_id: InstrumentId,
        source_id: str,
        channel: str,
        available_ns: int | None,
    ) -> BookQuote:
        """Project only displayed touch liquidity from one validated complete boundary.

        Full depth is needed for research imbalance, but paper matching and quote
        admission consume only the best price on each side. Native L3 orders at
        that price retain their exact aggregate size and original order count.
        """
        BookObservation.__post_init__(row)
        return BookDepth._touch_quote_validated(
            row,
            venue=venue,
            instrument_id=instrument_id,
            source_id=source_id,
            channel=channel,
            available_ns=available_ns,
        )

    @staticmethod
    def _touch_quote_validated(
        row: BookObservation,
        *,
        venue: str,
        instrument_id: InstrumentId,
        source_id: str,
        channel: str,
        available_ns: int | None,
    ) -> BookQuote:
        """Project the touch after a containing LiveBookDelivery validated the book."""
        bid: BookQuoteSide | None = None
        ask: BookQuoteSide | None = None
        if row.status == "degraded" and row.outcome in ("snapshot", "update"):
            if row.orders:
                bid_price = max(
                    (order.price for order in row.orders if order.side == "buy"), default=None
                )
                ask_price = min(
                    (order.price for order in row.orders if order.side == "sell"), default=None
                )
                for side, price in (("buy", bid_price), ("sell", ask_price)):
                    if price is None:
                        continue
                    best_orders = tuple(
                        order for order in row.orders if order.side == side and order.price == price
                    )
                    touch = BookQuoteSide(
                        price,
                        DecimalGrid.exact_decimal(
                            sum((Fraction(order.size) for order in best_orders), Fraction())
                        ),
                        len(best_orders),
                    )
                    if side == "buy":
                        bid = touch
                    else:
                        ask = touch
            else:
                # Validated sides have unique prices, so tuple comparison never
                # reaches Level. Construct only the two selected touch values.
                best_bid = max(row.bids, default=None)
                best_ask = min(row.asks, default=None)
                if best_bid is not None:
                    price, level = best_bid
                    bid = BookQuoteSide(price, level.size, level.order_count)
                if best_ask is not None:
                    price, level = best_ask
                    ask = BookQuoteSide(price, level.size, level.order_count)
        return BookQuote(
            venue=venue,
            instrument_id=instrument_id,
            source_id=source_id,
            channel=channel,
            position=row.position,
            epoch=row.epoch,
            sequence=row.sequence,
            source_time=row.source_time,
            received_ns=row.received_ns,
            available_ns=available_ns,
            outcome=row.outcome,
            status=row.status,
            reason=row.reason,
            state_identity=row.state_identity,
            bid=bid,
            ask=ask,
        )
