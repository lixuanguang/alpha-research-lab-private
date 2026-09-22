"""Inspect native L2 states without assigning historical receipt or knowledge times."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction

# project library imports
from financial_units import DecimalGrid, ExactRatio
from market_data.contracts import BookObservation
from serialization import WireRecord


class BookFeature(WireRecord, frozen=True):
    """Retain exact native best prices and selected-depth imbalance with unknown clocks."""

    position: int
    source_at: datetime
    received_ns: int | None
    sequence: int | None
    bid: Decimal | None
    ask: Decimal | None
    spread: Decimal | None
    bid_size: Decimal
    ask_size: Decimal
    imbalance: ExactRatio | None
    reason: str

    def __post_init__(self) -> None:
        """Require exact feature values, original optional clocks and consistent missingness."""
        self._require_utc(self.source_at, field_name="feature source")
        if type(self.position) is not int or self.position < 0 or not self.reason:
            raise ValueError("invalid book feature position or quality")
        for clock in (self.received_ns, self.sequence):
            if clock is not None and (type(clock) is not int or clock < 0):
                raise ValueError("invalid original book clock")
        for value in (self.bid, self.ask, self.spread, self.bid_size, self.ask_size):
            if value is not None:
                DecimalGrid.require_decimal(value)
        if (
            self.bid_size < 0
            or self.ask_size < 0
            or (self.bid is not None and self.bid <= 0)
            or (self.ask is not None and self.ask <= 0)
        ):
            raise ValueError("invalid book feature prices or sizes")
        if self.imbalance is not None:
            self.imbalance.__post_init__()
            if (
                self.reason != "visible_depth_only"
                or self.bid is None
                or self.ask is None
                or self.bid >= self.ask
                or not -1
                <= Fraction(int(self.imbalance.numerator), int(self.imbalance.denominator))
                <= 1
            ):
                raise ValueError("invalid book imbalance or quality")


class BookFeatures:
    """Own source clock interpretation, book validity and exact descriptive features."""

    @staticmethod
    def source_at(row: BookObservation) -> datetime:
        """Interpret the supported native Unix-millisecond clock without floating point.

        Args:
            row: Native L2 observation; original receipt and sequence remain untouched.

        Returns:
            UTC exchange event time.

        Raises:
            ValueError: Missing or noninteger source milliseconds cannot drive this scenario.
        """
        if row.source_time is None or not row.source_time.isdigit():
            raise ValueError("L2 research scenario requires native source milliseconds")
        return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=int(row.source_time))

    @staticmethod
    def reason(row: BookObservation | None, at: datetime, stale_us: int) -> str | None:
        """Refuse missing, crossed, invalid or source-aged states without filling gaps.

        Args:
            row: Exchange or delivered local state, never substituted for the other.
            at: UTC evaluation clock.
            stale_us: Maximum source age in microseconds, inclusive.

        Returns:
            Stable refusal reason, or None for a supported visible state.
        """
        if row is None:
            return "missing_book"
        if row.orders or row.status != "degraded" or row.outcome not in ("snapshot", "update"):
            return "invalid_book"
        if not row.bids or not row.asks:
            return "missing_side"
        if max(price for price, _ in row.bids) >= min(price for price, _ in row.asks):
            return "crossed_book"
        source = BookFeatures.source_at(row)
        if at < source or at - source > timedelta(microseconds=stale_us):
            return "stale_book"
        return None

    @staticmethod
    def inspect(row: BookObservation, depth: int) -> BookFeature:
        """Compute a bounded exact EDA row from the same native state the engine receives.

        Args:
            row: Complete retained native observation.
            depth: Positive number of best levels per side for the descriptive imbalance.

        Returns:
            Exact observation with explicit missing/invalid status and original clocks.

        Raises:
            ValueError: The requested depth is outside supported archive depth.
        """
        if type(depth) is not int or not 1 <= depth <= 400:
            raise ValueError("book feature depth must be within 1..400")
        at = BookFeatures.source_at(row)
        reason = BookFeatures.reason(row, at, 1)
        bids = sorted(row.bids, reverse=True)[:depth]
        asks = sorted(row.asks)[:depth]
        bid_size = sum((Fraction(level.size) for _, level in bids), Fraction())
        ask_size = sum((Fraction(level.size) for _, level in asks), Fraction())
        bid = bids[0][0] if bids else None
        ask = asks[0][0] if asks else None
        return BookFeature(
            position=row.position,
            source_at=at,
            received_ns=row.received_ns,
            sequence=row.sequence,
            bid=bid,
            ask=ask,
            spread=None
            if bid is None or ask is None
            else DecimalGrid.exact_decimal(Fraction(ask) - Fraction(bid)),
            bid_size=DecimalGrid.exact_decimal(bid_size),
            ask_size=DecimalGrid.exact_decimal(ask_size),
            imbalance=None
            if reason is not None
            else ExactRatio.from_fraction((bid_size - ask_size) / (bid_size + ask_size)),
            reason=reason or "visible_depth_only",
        )
