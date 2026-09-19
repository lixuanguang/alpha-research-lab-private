"""Cache strict Binance event and source-payload codecs."""

from __future__ import annotations

# third party library imports
import msgspec

# project library imports
from market_data.contracts import DepthSnapshot, DepthUpdate, Disconnect, MarketEventError, Trade
from serialization import DomainCodec

type MarketEvent = DepthSnapshot | DepthUpdate | Trade | Disconnect
"""Discriminated immutable normalized Binance event union."""


class MarketEventCodec:
    """Own strict canonical event validation and reusable deterministic JSON codecs."""

    __slots__ = ("_decoder", "_encoder")

    def __init__(self) -> None:
        """Compile the closed event union once for repeated encoding and decoding."""
        self._encoder = msgspec.json.Encoder(enc_hook=DomainCodec.encode_domain, order="sorted")
        self._decoder: msgspec.json.Decoder[MarketEvent] = msgspec.json.Decoder(
            MarketEvent, strict=True, dec_hook=DomainCodec.decode_domain
        )

    @staticmethod
    def validate(event: MarketEvent) -> MarketEvent:
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

    def encode(self, event: MarketEvent) -> bytes:
        """Encode one validated canonical event as deterministic sorted-key JSON.

        Args:
            event: Canonical market event to encode.

        Returns:
            UTF-8 JSON bytes with exact decimals and canonical UUID text.

        Raises:
            TypeError: The event is unsupported or has an invalid field type.
            ValueError: The event violates a domain invariant.
        """
        return self._encoder.encode(self.validate(event))

    def decode(self, data: bytes | str) -> MarketEvent:
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
            event = self._decoder.decode(data)
        except (msgspec.DecodeError, TypeError, ValueError) as error:
            raise MarketEventError("canonical market event JSON is invalid") from error
        return event
