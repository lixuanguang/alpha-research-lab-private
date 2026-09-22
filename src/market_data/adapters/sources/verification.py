"""Re-decode retained occurrences through their installed source boundaries."""

from __future__ import annotations

# standard library imports
from datetime import datetime, timedelta

# project library imports
from market_data.adapters.providers.binance import ArchiveRow, BinanceArchiveTrades
from market_data.adapters.providers.tardis import TardisDecoder
from market_data.adapters.venues.binance import BinancePayloadDecoder
from market_data.contracts import (
    ArchiveCapture,
    ArchiveTrade,
    DepthSnapshot,
    DepthUpdate,
    Disconnect,
    Occurrence,
    OccurrenceVerifier,
    SourceRequest,
    Trade,
)


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
            original = BinanceArchiveTrades.from_row(
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

    def captures(self, evidence: ArchiveCapture) -> tuple[Trade, ...]:
        """Verify complete native Tardis slices for the exact archive interval.

        Args:
            evidence: Contiguous original uncompressed response slices and acquisition clocks.

        Returns:
            Native trades including boundary rows; matching economic versions is separate.

        Raises:
            ValueError: Binding, framing, capture coverage, ordering or source messages fail.
        """
        evidence.__post_init__()
        request = self._request
        start, end = request.manifest.job.start, request.manifest.job.end
        if (
            request.manifest.job.provider != "binance-archive"
            or request.manifest.job.venue != "binance"
            or evidence.request_identity != request.identity
            or evidence.slices[0].start > start
            or evidence.slices[-1].start + timedelta(minutes=evidence.slices[-1].minutes) < end
        ):
            raise ValueError("capture evidence differs from archive selection or coverage")
        decoder = TardisDecoder(
            BinancePayloadDecoder(request.manifest.instruments), "tardis.binance.witness"
        )
        identity = evidence.identity
        retained: list[Trade] = []
        previous: datetime | None = None
        for piece in evidence.slices:
            for index, line in enumerate(piece.payload.decode().splitlines()):
                if not line:
                    raise ValueError("capture coverage contains a disconnect marker")
                event = decoder.decode_line(
                    line,
                    source_sequence=index,
                    local_received=piece.received_at,
                    local_ingested=piece.received_at,
                    source_digest=identity,
                )
                if (
                    not isinstance(event, Trade)
                    or event.instrument_id != request.instrument.instrument_id
                ):
                    raise ValueError("capture evidence requires native individual trades")
                instant = event.provenance.ts_knowledge
                if not piece.start <= instant < piece.start + timedelta(minutes=piece.minutes):
                    raise ValueError("native capture falls outside its response interval")
                if previous is not None and instant < previous:
                    raise ValueError("native capture order regressed")
                previous = instant
                retained.append(event)
        return tuple(retained)
