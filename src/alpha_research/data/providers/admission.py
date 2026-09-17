"""Re-decode retained occurrences through their installed source boundaries."""

from __future__ import annotations

# standard library imports
from datetime import datetime

# project library imports
from alpha_research.data.events import Disconnect
from alpha_research.data.inputs import OccurrenceVerifier
from alpha_research.data.normalization import Occurrence
from alpha_research.data.providers.binance.rows import ArchiveRow
from alpha_research.data.providers.binance.trades import ArchiveTrade
from alpha_research.data.providers.tardis.decoder import TardisDecoder
from alpha_research.data.requests import SourceRequest
from alpha_research.data.venues.binance.events import DepthSnapshot, DepthUpdate, Trade
from alpha_research.data.venues.binance.payloads import BinancePayloadDecoder


class SourceOccurrenceVerifier(OccurrenceVerifier):
    """Verify retained archive or captured occurrence bytes for one source request."""

    __slots__ = ("_decoder", "_request")

    def __init__(self, request: SourceRequest) -> None:
        """Bind one request and initialize any provider decoder it needs.

        Args:
            request: Validated source request whose bytes will be re-decoded.

        Raises:
            TypeError: The supplied value is not a source request.
            ValueError: The request or its provider is unsupported.
        """
        if type(request) is not SourceRequest:
            raise TypeError("occurrence verifier requires a SourceRequest")
        request.__post_init__()
        self._request = request
        self._decoder: TardisDecoder[Trade | DepthSnapshot | DepthUpdate] | None = (
            TardisDecoder(
                BinancePayloadDecoder(request.manifest.instruments), request.instrument.source
            )
            if request.manifest.job.provider == "tardis"
            else None
        )
        if request.manifest.job.provider not in {"tardis", "binance-archive"}:
            raise ValueError(f"unsupported occurrence source: {request.manifest.job.provider}")

    def check(self, item: Occurrence) -> tuple[datetime, datetime | None]:
        """Re-decode original bytes and return source observation clocks.

        Args:
            item: Occurrence bound to this verifier's source request.

        Returns:
            Archive event time with unknown knowledge, or captured source capture
            time with the event's retained original knowledge timestamp.

        Raises:
            ValueError: Source bytes differ from the retained canonical event or
                the captured event lacks a source capture timestamp.
        """
        event = item.event
        if isinstance(event, ArchiveTrade):
            original = ArchiveTrade.from_row(
                ArchiveRow(
                    origin=item.origin,
                    position=item.position,
                    payload=item.raw,
                    selection_start=self._request.manifest.job.start,
                    selection_end=self._request.manifest.job.end,
                ),
                self._request,
            )
            if original != event:
                raise ValueError("canonical archive event differs from original bytes")
            return event.ts_event, None

        if self._decoder is None:
            raise ValueError("captured event requires its source decoder")
        original_capture = self._decoder.decode_line(
            item.raw.decode().removesuffix("\n").removesuffix("\r"),
            source_sequence=item.position,
            local_received=item.origin.ts_received,
            local_ingested=item.origin.ts_ingested,
            source_digest=item.origin.sha256,
            disconnect_capture_time=event.provenance.ts_source_received,
            disconnect_capture_reason=(
                event.capture_proxy_reason
                if isinstance(event, Disconnect)
                else "next_source_capture"
            ),
        )
        if original_capture != event:
            raise ValueError("canonical capture differs from original bytes/clocks")
        capture = event.provenance.ts_source_received
        if capture is None:
            raise ValueError("captured occurrence has no source capture")
        return capture, event.provenance.ts_knowledge


__all__ = ["SourceOccurrenceVerifier"]
