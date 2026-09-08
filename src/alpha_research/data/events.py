"""Define shared immutable market-event records and validation primitives."""

from __future__ import annotations

# standard library imports
from decimal import Decimal
from typing import Literal, Self

# third party library imports
import msgspec

# project library imports
from alpha_research.core import EventProvenance
from alpha_research.instrument_identity import InstrumentId

type Symbol = str
type EventTimeBasis = Literal["source_event", "capture_proxy"]
type PriceLevel = tuple[Decimal, Decimal]


class MarketEventError(ValueError):
    """Report malformed or unsupported source market data."""


def _require_text(value: object, *, field_name: str, allow_empty: bool = False) -> str:
    """Require one string field at the Python construction boundary."""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not allow_empty and not value:
        raise ValueError(f"{field_name} must be nonempty")
    return value


def _require_int(value: object, *, field_name: str, nonnegative: bool = True) -> int:
    """Require a strict integer field, rejecting booleans."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if nonnegative and value < 0:
        raise ValueError(f"{field_name} must be nonnegative")
    return value


def _validate_decimal(value: object, *, field_name: str, allow_zero: bool = True) -> Decimal:
    """Require a finite nonnegative Decimal price or quantity."""
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    if value < 0 or (not allow_zero and value == 0):
        qualifier = "positive" if not allow_zero else "nonnegative"
        raise ValueError(f"{field_name} must be {qualifier}")
    return value


def _validate_levels(value: object, *, field_name: str) -> tuple[PriceLevel, ...]:
    """Validate immutable price-level pairs and reject duplicate prices."""
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    seen_prices: set[Decimal] = set()
    for level in value:
        if not isinstance(level, tuple) or len(level) != 2:
            raise TypeError(f"{field_name} must contain two-item tuples")
        price, quantity = level
        _validate_decimal(price, field_name=f"{field_name}.price", allow_zero=False)
        _validate_decimal(quantity, field_name=f"{field_name}.quantity")
        if price in seen_prices:
            raise ValueError(f"{field_name} contains duplicate prices")
        seen_prices.add(price)
    return value


class TaggedEvent(
    msgspec.Struct,
    frozen=True,
    kw_only=True,
    forbid_unknown_fields=True,
    tag_field="event_type",
):
    """Share the frozen closed-schema policy for tagged event records."""

    @property
    def event_type(self) -> str:
        """Return the stable tagged-union discriminator for this event.

        Returns:
            The concrete event tag used by the closed wire union.
        """
        tag = type(self).__struct_config__.tag
        return tag if isinstance(tag, str) else str(tag)


def _validate_market_fields(event: MarketEventRecord) -> None:
    """Validate fields shared by all canonical market events."""
    if not isinstance(event.provenance, EventProvenance):
        raise TypeError("provenance must be an EventProvenance")
    event.provenance.validate()
    _require_text(event.original_capture_time, field_name="original_capture_time")
    if event.original_capture_time != event.original_capture_time.strip():
        raise ValueError("source text must not have surrounding whitespace")
    if not isinstance(event.event_time_basis, str):
        raise TypeError("event_time_basis must be a string")
    if event.event_time_basis not in {"source_event", "capture_proxy"}:
        raise ValueError("event_time_basis is unsupported")
    _require_text(event.symbol, field_name="symbol")
    if not isinstance(event.instrument_id, InstrumentId):
        raise TypeError("instrument_id must be an InstrumentId")
    _require_text(event.source_stream, field_name="source_stream")
    _require_text(event.raw_line, field_name="raw_line")
    if event.raw_line != event.raw_line.strip():
        raise ValueError("source text must not have surrounding whitespace")


class MarketEventRecord(TaggedEvent, frozen=True, kw_only=True):
    """Hold fields common to immutable normalized market events."""

    provenance: EventProvenance
    original_capture_time: str
    event_time_basis: EventTimeBasis
    symbol: Symbol
    instrument_id: InstrumentId
    source_stream: str
    raw_line: str

    def __post_init__(self) -> None:
        """Validate through dynamic subclass dispatch after msgspec construction."""
        self.validate()

    def validate(self) -> Self:
        """Recheck shared event fields after a trusted boundary operation.

        Returns:
            This validated event.

        Raises:
            TypeError: A field has the wrong Python type.
            ValueError: A field or cross-field invariant is invalid.
        """
        _validate_market_fields(self)
        return self


class Disconnect(TaggedEvent, frozen=True, kw_only=True, tag="disconnect"):
    """Represent an explicit blank source line and its conservative capture proxy."""

    provenance: EventProvenance
    original_capture_time: str = ""
    event_time_basis: Literal["capture_proxy"] = "capture_proxy"
    symbol: None = None
    instrument_id: None = None
    source_stream: Literal["global"] = "global"
    raw_line: Literal[""] = ""
    capture_proxy_reason: Literal["next_source_capture", "interval_end"]

    def __post_init__(self) -> None:
        """Validate the blank-line disconnect and its capture-proxy metadata.

        Raises:
            TypeError: A field has the wrong Python type.
            ValueError: The provenance or proxy reason is invalid.
        """
        if not isinstance(self.provenance, EventProvenance):
            raise TypeError("provenance must be an EventProvenance")
        self.provenance.validate()
        _require_text(
            self.original_capture_time, field_name="original_capture_time", allow_empty=True
        )
        if not isinstance(self.event_time_basis, str):
            raise TypeError("event_time_basis must be a string")
        if self.event_time_basis != "capture_proxy":
            raise ValueError("disconnect event_time_basis must be capture_proxy")
        if not isinstance(self.source_stream, str):
            raise TypeError("source_stream must be a string")
        if not isinstance(self.raw_line, str):
            raise TypeError("raw_line must be a string")
        if not isinstance(self.capture_proxy_reason, str):
            raise TypeError("capture_proxy_reason must be a string")
        if self.original_capture_time != "":
            raise ValueError("disconnect original_capture_time must be empty")
        if self.symbol is not None or self.instrument_id is not None:
            raise TypeError("disconnect symbol and instrument_id must be None")
        if self.source_stream != "global" or self.raw_line != "":
            raise ValueError("disconnect source identity is invalid")
        if self.capture_proxy_reason not in {"next_source_capture", "interval_end"}:
            raise ValueError("capture_proxy_reason is unsupported")

    def validate(self) -> Self:
        """Recheck this disconnect before a trusted consumer uses it.

        Returns:
            This validated disconnect.

        Raises:
            TypeError: An unsafe mutation inserted a value with the wrong type.
            ValueError: An unsafe mutation violates a disconnect invariant.
        """
        self.__post_init__()
        return self


__all__ = [
    "Disconnect",
    "EventTimeBasis",
    "MarketEventError",
    "MarketEventRecord",
    "PriceLevel",
    "Symbol",
    "TaggedEvent",
]
