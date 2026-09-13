"""Compose the Tardis line decoder with Binance payload decoding."""

from __future__ import annotations

# project library imports
from alpha_research.data.providers.tardis.decoder import TardisDecoder
from alpha_research.data.venues.binance.events import DepthSnapshot, DepthUpdate, Trade
from alpha_research.data.venues.binance.payloads import BinancePayloadDecoder
from alpha_research.reference_data import SpotInstrument


class BinanceTardisDecoder(TardisDecoder[DepthSnapshot | DepthUpdate | Trade]):
    """Decode Tardis Binance lines with one validated instrument selection."""

    def __init__(self, instruments: tuple[SpotInstrument, ...]) -> None:
        """Bind one immutable source symbol to instrument mapping.

        Args:
            instruments: Configured spot mappings used for all decoded lines.

        Raises:
            TypeError: The selection contains a non-SpotInstrument value.
            ValueError: The selection is empty, duplicated, or invalid.
        """
        super().__init__(
            payload_decoder=BinancePayloadDecoder(instruments),
            source_id="tardis.binance.spot",
        )


__all__ = ["BinanceTardisDecoder"]
