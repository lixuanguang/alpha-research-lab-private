"""Define strict immutable Binance spot market-event records."""

from __future__ import annotations

# standard library imports
from decimal import Decimal
from typing import Literal, Self

# project library imports
from alpha_research.data.events import (
    MarketEventRecord,
    PriceLevel,
    _require_int,
    _require_text,
    _validate_decimal,
    _validate_levels,
)


def _validate_symbol(value: object, *, field_name: str = "symbol") -> str:
    """Require a nonempty uppercase ASCII alphanumeric Binance symbol."""
    symbol = _require_text(value, field_name=field_name)
    if not symbol.isascii() or not symbol.isalnum() or symbol != symbol.upper():
        raise ValueError(f"{field_name} must be uppercase ASCII alphanumeric text")
    return symbol


class BinanceMarketEvent(MarketEventRecord, frozen=True, kw_only=True):
    """Add Binance's uppercase ASCII symbol restriction to common event fields."""

    def validate(self) -> Self:
        """Recheck common fields and Binance symbol syntax.

        Returns:
            This validated Binance market event.

        Raises:
            TypeError: A field has the wrong Python type.
            ValueError: A field or Binance symbol invariant is invalid.
        """
        super().validate()
        _validate_symbol(self.symbol)
        return self


class DepthSnapshot(BinanceMarketEvent, frozen=True, kw_only=True, tag="depth_snapshot"):
    """Represent a source-generated full Binance order-book snapshot.

    Binance snapshots have no exchange event timestamp. ``event_time_basis`` is
    therefore ``capture_proxy`` and provenance ``ts_event`` is the rounded-up
    source capture time, explicitly preserving its proxy semantics.
    """

    event_time_basis: Literal["capture_proxy"] = "capture_proxy"
    last_update_id: int
    bids: tuple[PriceLevel, ...]
    asks: tuple[PriceLevel, ...]

    def validate(self) -> Self:
        """Recheck snapshot identity, sequence, and immutable levels.

        Returns:
            This validated snapshot.

        Raises:
            TypeError: An unsafe mutation inserted a value with the wrong Python type.
            ValueError: An unsafe mutation violates a snapshot invariant.
        """
        super().validate()
        if self.event_time_basis != "capture_proxy":
            raise ValueError("depth snapshot event_time_basis must be capture_proxy")
        _require_int(self.last_update_id, field_name="last_update_id")
        _validate_levels(self.bids, field_name="bids")
        _validate_levels(self.asks, field_name="asks")
        return self


class DepthUpdate(BinanceMarketEvent, frozen=True, kw_only=True, tag="depth_update"):
    """Represent one incremental Binance depth update."""

    event_time_basis: Literal["source_event"] = "source_event"
    first_update_id: int
    last_update_id: int
    bids: tuple[PriceLevel, ...]
    asks: tuple[PriceLevel, ...]

    def validate(self) -> Self:
        """Recheck update identity, interval, and immutable levels.

        Returns:
            This validated update.

        Raises:
            TypeError: An unsafe mutation inserted a value with the wrong Python type.
            ValueError: An unsafe mutation violates an update invariant.
        """
        super().validate()
        if self.event_time_basis != "source_event":
            raise ValueError("depth update event_time_basis must be source_event")
        _require_int(self.first_update_id, field_name="first_update_id")
        _require_int(self.last_update_id, field_name="last_update_id")
        if self.last_update_id < self.first_update_id:
            raise ValueError("last_update_id must be greater than or equal to first_update_id")
        _validate_levels(self.bids, field_name="bids")
        _validate_levels(self.asks, field_name="asks")
        return self


class Trade(BinanceMarketEvent, frozen=True, kw_only=True, tag="trade"):
    """Represent one Binance individual trade payload, without aggregation."""

    event_time_basis: Literal["source_event"] = "source_event"
    price: Decimal
    quantity: Decimal
    trade_id: int
    is_buyer_maker: bool

    def validate(self) -> Self:
        """Recheck trade identity, exact decimals, and maker flag.

        Returns:
            This validated trade.

        Raises:
            TypeError: An unsafe mutation inserted a value with the wrong Python type.
            ValueError: An unsafe mutation violates a trade invariant.
        """
        super().validate()
        if self.event_time_basis != "source_event":
            raise ValueError("trade event_time_basis must be source_event")
        _validate_decimal(self.price, field_name="price", allow_zero=False)
        _validate_decimal(self.quantity, field_name="quantity")
        _require_int(self.trade_id, field_name="trade_id")
        if not isinstance(self.is_buyer_maker, bool):
            raise TypeError("is_buyer_maker must be a boolean")
        return self


__all__ = ["BinanceMarketEvent", "DepthSnapshot", "DepthUpdate", "Trade"]
