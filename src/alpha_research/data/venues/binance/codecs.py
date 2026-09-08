"""Cache strict Binance event and source-payload codecs."""

from __future__ import annotations

# standard library imports
from typing import Literal

# third party library imports
import msgspec

# project library imports
from alpha_research.data.events import Disconnect, MarketEventError
from alpha_research.data.venues.binance.events import DepthSnapshot, DepthUpdate, Trade
from alpha_research.serialization import decode_domain, encode_domain

type MarketEvent = DepthSnapshot | DepthUpdate | Trade | Disconnect
"""Discriminated immutable normalized Binance event union."""


class BinanceEnvelope(msgspec.Struct, frozen=True, kw_only=True):
    """Decode the Binance source envelope while retaining native payload bytes."""

    stream: str
    data: msgspec.Raw

    def __post_init__(self) -> None:
        """Validate required Binance envelope fields while allowing source extras.

        Raises:
            TypeError: ``stream`` or ``data`` has the wrong Python type.
            ValueError: ``stream`` is empty.
        """
        if not isinstance(self.stream, str):
            raise TypeError("stream must be a string")
        if not self.stream:
            raise ValueError("stream must be nonempty")
        if not isinstance(self.data, msgspec.Raw):
            raise TypeError("data must be msgspec.Raw")


_MARKET_EVENT_ENCODER = msgspec.json.Encoder(enc_hook=encode_domain, order="sorted")
_MARKET_EVENT_DECODER: msgspec.json.Decoder[MarketEvent] = msgspec.json.Decoder(
    MarketEvent,
    strict=True,
    dec_hook=decode_domain,
)


def validate_market_event(event: MarketEvent) -> MarketEvent:
    """Validate one canonical event at an explicit trusted boundary.

    Args:
        event: Canonical market event to validate.

    Returns:
        The same event instance after all field and domain invariants pass.

    Raises:
        TypeError: The value is not a supported event or contains a wrong field type.
        ValueError: A field or cross-field event invariant is invalid.
    """
    if not isinstance(event, (DepthSnapshot, DepthUpdate, Trade, Disconnect)):
        raise TypeError("event must be a supported MarketEvent")
    return event.validate()


def encode_market_event(event: MarketEvent) -> bytes:
    """Encode one validated canonical event as deterministic sorted-key JSON.

    Args:
        event: Canonical market event to encode.

    Returns:
        UTF-8 JSON bytes with exact decimals and canonical UUID text.

    Raises:
        TypeError: The event is unsupported or has an invalid field type.
        ValueError: The event violates a domain invariant.
    """
    return _MARKET_EVENT_ENCODER.encode(validate_market_event(event))


def decode_market_event(data: bytes | str) -> MarketEvent:
    """Decode strict typed JSON into one canonical market event.

    Args:
        data: Complete canonical event JSON bytes or text.

    Returns:
        A typed immutable market event with all custom invariants checked.

    Raises:
        MarketEventError: JSON syntax, unknown fields, field types, or domain values
            are invalid.
    """
    try:
        event = _MARKET_EVENT_DECODER.decode(data)
    except (msgspec.DecodeError, TypeError, ValueError) as error:
        raise MarketEventError("canonical market event JSON is invalid") from error
    return event


class _SnapshotPayload(msgspec.Struct, kw_only=True):
    """Decode required Binance snapshot fields and inspect forbidden markers."""

    last_update_id: int = msgspec.field(name="lastUpdateId")
    bids: list[tuple[str, str]]
    asks: list[tuple[str, str]]
    event_marker: msgspec.Raw | msgspec.UnsetType = msgspec.field(name="e", default=msgspec.UNSET)
    event_time_marker: msgspec.Raw | msgspec.UnsetType = msgspec.field(
        name="E", default=msgspec.UNSET
    )


class _DepthPayload(msgspec.Struct, kw_only=True):
    """Decode required Binance incremental-depth fields."""

    event_type: Literal["depthUpdate"] = msgspec.field(name="e")
    source_symbol: str = msgspec.field(name="s")
    event_time: int = msgspec.field(name="E")
    first_update_id: int = msgspec.field(name="U")
    last_update_id: int = msgspec.field(name="u")
    bids: list[tuple[str, str]] = msgspec.field(name="b")
    asks: list[tuple[str, str]] = msgspec.field(name="a")


class _TradePayload(msgspec.Struct, kw_only=True):
    """Decode required Binance trade fields."""

    event_type: Literal["trade"] = msgspec.field(name="e")
    source_symbol: str = msgspec.field(name="s")
    event_time: int = msgspec.field(name="T")
    price: str = msgspec.field(name="p")
    quantity: str = msgspec.field(name="q")
    trade_id: int = msgspec.field(name="t")
    is_buyer_maker: bool = msgspec.field(name="m")


_SNAPSHOT_DECODER: msgspec.json.Decoder[_SnapshotPayload] = msgspec.json.Decoder(
    _SnapshotPayload, strict=True
)
_DEPTH_DECODER: msgspec.json.Decoder[_DepthPayload] = msgspec.json.Decoder(
    _DepthPayload, strict=True
)
_TRADE_DECODER: msgspec.json.Decoder[_TradePayload] = msgspec.json.Decoder(
    _TradePayload, strict=True
)


def _decode_binance_payload[T](raw_data: msgspec.Raw, decoder: msgspec.json.Decoder[T]) -> T:
    """Decode one typed Binance payload while retaining extra exchange members."""
    try:
        return decoder.decode(raw_data)
    except (msgspec.DecodeError, TypeError, ValueError) as error:
        raise MarketEventError("source payload fields are invalid") from error


__all__ = [
    "BinanceEnvelope",
    "MarketEvent",
    "decode_market_event",
    "encode_market_event",
    "validate_market_event",
]
