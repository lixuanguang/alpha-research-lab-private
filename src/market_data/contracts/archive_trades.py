"""Define immutable Binance archive trade records without row parsing."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

# project library imports
from market_data.contracts.binance import BinanceMarketEvent
from market_data.contracts.events import MarketEventRecord, TaggedEvent
from reference_data.instruments import InstrumentId


class ArchiveTrade(TaggedEvent, frozen=True, kw_only=True, tag="archive_trade"):
    """Retain exact trade values and source precision with explicitly absent availability.

    Price is quote currency per base unit, quantity is base units, and quote_quantity
    is the publisher's quote amount, not a recomputed or rounded product. The binding
    supplies currency/instrument metadata. Acquisition clocks remain on the raw origin.
    Serialize through a reused DomainCodec; the existing captured Trade stays unchanged.
    """

    instrument_id: InstrumentId
    symbol: str
    trade_id: int
    price: Decimal
    quantity: Decimal
    quote_quantity: Decimal
    timestamp: int
    timestamp_unit: Literal["ms", "us"]
    is_buyer_maker: bool
    is_best_match: bool
    ts_source_received: None = None
    ts_knowledge: None = None

    def __post_init__(self) -> None:
        """Reject unsafe types, invalid amounts, timestamp units and fabricated clocks.

        Raises:
            ValueError: An event field or timestamp convention is invalid.
            TypeError: Exact domain fields have incompatible Python types.
        """
        if not isinstance(self.instrument_id, InstrumentId):
            raise TypeError("archive instrument_id must be an InstrumentId")
        BinanceMarketEvent._validate_symbol(self.symbol)
        for name, value in (("trade_id", self.trade_id), ("timestamp", self.timestamp)):
            MarketEventRecord._require_int(value, field_name=name)
        for name, amount in (
            ("price", self.price),
            ("quantity", self.quantity),
            ("quote_quantity", self.quote_quantity),
        ):
            MarketEventRecord._validate_decimal(amount, field_name=name, allow_zero=name != "price")
        if type(self.is_buyer_maker) is not bool or type(self.is_best_match) is not bool:
            raise TypeError("archive trade flags must be booleans")
        if self.ts_source_received is not None or self.ts_knowledge is not None:
            raise ValueError("archive capture and knowledge must remain absent")
        if self.timestamp_unit not in ("ms", "us"):
            raise ValueError("archive timestamp_unit must be ms or us")
        if (self.ts_event.year >= 2025) != (self.timestamp_unit == "us"):
            raise ValueError("archive timestamp unit differs from the source date convention")

    @property
    def ts_event(self) -> datetime:
        """Convert the retained Unix integer using exact microsecond arithmetic.

        Returns:
            UTC source event instant without rounding or a float intermediate.

        Raises:
            ValueError: The source timestamp exceeds the supported datetime range.
        """
        try:
            return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(
                microseconds=self.timestamp * (1000 if self.timestamp_unit == "ms" else 1)
            )
        except OverflowError as error:
            raise ValueError("archive timestamp outside datetime range") from error
