"""Compose the Tardis line decoder with Binance payload decoding."""

from __future__ import annotations

# standard library imports
from datetime import datetime
from typing import Literal

# project library imports
from alpha_research.data.providers.tardis.decoder import TardisDecoder
from alpha_research.data.venues.binance.codecs import MarketEvent
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


def decode_tardis_line(
    line: str,
    *,
    instruments: tuple[SpotInstrument, ...],
    source_sequence: int,
    local_received: datetime,
    local_ingested: datetime | None = None,
    disconnect_capture_time: datetime | None = None,
    disconnect_capture_reason: Literal[
        "next_source_capture", "interval_end"
    ] = "next_source_capture",
    source_digest: str | None = None,
) -> MarketEvent:
    """Decode one Tardis line at an explicit one-off trust boundary.

    Args:
        line: Original UTF-8 line, including no trailing newline.
        instruments: Configured spot mappings used to resolve source stream symbols.
        source_sequence: Zero-based source line sequence, retaining tie order.
        local_received: Local receipt/ingestion time for the raw object.
        local_ingested: Optional local durable-ingestion timestamp.
        disconnect_capture_time: Conservative capture proxy for a blank line.
        disconnect_capture_reason: Reason for the blank-line capture proxy.
        source_digest: Optional raw-object digest.

    Returns:
        One immutable canonical event or an explicit blank-line disconnect.

    Raises:
        MarketEventError: The stream, payload, timestamp, or field values are
            unsupported or malformed.
        TypeError: A supplied boundary value has the wrong Python type.
        ValueError: A supplied timestamp is naive.
    """
    return BinanceTardisDecoder(instruments).decode_line(
        line,
        source_sequence=source_sequence,
        local_received=local_received,
        local_ingested=local_ingested,
        disconnect_capture_time=disconnect_capture_time,
        disconnect_capture_reason=disconnect_capture_reason,
        source_digest=source_digest,
    )


__all__ = ["BinanceTardisDecoder", "decode_tardis_line"]
