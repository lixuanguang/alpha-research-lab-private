"""Decode individual archive trades without inventing historical capture clocks."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal

# project library imports
from alpha_research.data.events import MarketEventRecord, TaggedEvent
from alpha_research.data.providers.binance.rows import ArchiveRow, BinanceArchiveRows
from alpha_research.data.requests import SourceRequest
from alpha_research.data.venues.binance.events import BinanceMarketEvent
from alpha_research.instrument_identity import InstrumentId


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

    @classmethod
    def from_row(cls, row: ArchiveRow, request: SourceRequest) -> ArchiveTrade:
        """Decode one verified seven-column individual-trade row for its explicit binding.

        Args:
            row: Original CSV bytes and origin supplied by the saved archive reader.
            request: Selected instrument/day; timestamp units follow the publisher's date rule.

        Returns:
            Exact trade values, including rows outside the narrower research selection.

        Raises:
            ValueError: Binding, source fields, units or the UTC partition is invalid.
        """
        row.__post_init__()
        BinanceArchiveRows(request=request, descriptor=row.origin)
        if (row.selection_start, row.selection_end) != (
            request.manifest.job.start,
            request.manifest.job.end,
        ):
            raise ValueError("archive row selection differs from request")
        fields = row.columns()
        try:
            if any(not fields[i].isascii() or not fields[i].isdecimal() for i in (0, 4)):
                raise ValueError("trade ID and timestamp must be unsigned ASCII integers")
            if any(fields[i] not in ("true", "false", "True", "False") for i in (5, 6)):
                raise ValueError("trade flags must be true/false or True/False")
            event = cls(
                instrument_id=request.instrument.instrument_id,
                symbol=request.instrument.symbol,
                trade_id=int(fields[0]),
                price=Decimal(fields[1]),
                quantity=Decimal(fields[2]),
                quote_quantity=Decimal(fields[3]),
                timestamp=int(fields[4]),
                timestamp_unit="us" if request.start.year >= 2025 else "ms",
                is_buyer_maker=fields[5].lower() == "true",
                is_best_match=fields[6].lower() == "true",
            )
            if not request.start <= event.ts_event < request.end:
                raise ValueError("trade timestamp outside requested UTC day")
            return event
        except (ValueError, InvalidOperation) as error:
            raise ValueError(f"invalid Binance trade at row {row.position}: {error}") from error
