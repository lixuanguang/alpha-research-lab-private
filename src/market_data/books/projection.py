"""Project exact native states into source-independent observation records."""

# project library imports
from market_data.books.reconstruction import CaptureReplay
from market_data.contracts import BookObservation, CaptureRecord, Order


class BookProjection:
    """Capture a complete visible state and quality transition after each message."""

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
            bids=tuple(sorted(book.bids.items())) if keep else (),
            asks=tuple(sorted(book.asks.items())) if keep else (),
            transition_ns=replay.quality.transition_ns,
            last_durable_ns=replay.quality.last_durable_ns,
        )

    @staticmethod
    def _order_key(order: Order) -> str:
        """Order a complete L3 state deterministically without inventing queue priority."""
        return order.order_id
