"""Project exact native states into source-independent observation records."""

# project library imports
from market_data.books.depth import BookDepth
from market_data.books.reconstruction import CaptureReplay
from market_data.contracts import BookObservation, BookQuote, CaptureRecord, Order


class BookProjection:
    """Capture a complete visible state and quality transition after each message."""

    @classmethod
    def quote(
        cls,
        position: int,
        record: CaptureRecord,
        outcome: str,
        replay: CaptureReplay,
        *,
        source_id: str,
        available_ns: int | None,
    ) -> BookQuote:
        """Expose cached native L2/L3 touch only after a complete accepted boundary.

        Args:
            position: Original raw position of the just-applied record.
            record: Exact persisted native message or quality transition.
            outcome: Classification returned by this replay's apply operation.
            replay: Current reconstruction and quality for the same record.
            source_id: Explicit recording/request identity, retained in the result.
            available_ns: Actual delivery clock or explicit unknown; never invented from receipt.

        Returns:
            Common quote with independent sides and unchanged native clocks and quality.
        """
        row = cls.capture(position, record, outcome, replay)
        return BookDepth.from_native(replay.book).quote(
            row,
            venue=replay.config.venue,
            instrument_id=replay.config.instrument_id,
            source_id=source_id,
            channel=replay.config.channel,
            available_ns=available_ns,
        )

    @classmethod
    def capture(
        cls, position: int, record: CaptureRecord, outcome: str, replay: CaptureReplay
    ) -> BookObservation:
        """Normalize one durable live or saved message through the identical native boundary.

        Args:
            position: Zero-based original raw position.
            record: Exact persisted frame or session transition.
            outcome: Classification returned by this replay's apply operation.
            replay: Reconstruction and quality immediately after that whole message.

        Returns:
            Exact visible state, quality transition and original receipt/session coordinates.
        """
        book = replay.book
        keep = outcome in ("snapshot", "update") and book.ready and not replay.invalid
        return BookObservation(
            position,
            record.epoch,
            record.received_ns,
            book.source_time,
            book.sequence,
            outcome,
            replay.quality.status,
            replay.quality.reason,
            book.identity,
            orders=tuple(sorted(book.orders.values(), key=cls._order_key)) if keep else (),
            bids=tuple(sorted(book.bids.items())) if keep and not book.orders else (),
            asks=tuple(sorted(book.asks.items())) if keep and not book.orders else (),
            transition_ns=replay.quality.transition_ns,
            last_durable_ns=replay.quality.last_durable_ns,
        )

    @staticmethod
    def _order_key(order: Order) -> str:
        """Order a complete L3 state deterministically without inventing queue priority."""
        return order.order_id
