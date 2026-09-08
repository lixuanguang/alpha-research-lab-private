"""Decode captured Tardis source lines through an injected payload boundary."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from typing import Literal

# project library imports
from alpha_research.data.decoders import DecodeContext, PayloadDecoder
from alpha_research.data.events import Disconnect, MarketEventError


def parse_capture_time(capture_text: str) -> datetime:
    """Parse source capture text and round upward to microsecond precision.

    Args:
        capture_text: ISO UTC source capture text ending in ``Z``.

    Returns:
        A timezone-aware UTC instant rounded upward to microsecond precision.

    Raises:
        TypeError: ``capture_text`` is not a string.
        MarketEventError: The text is not a valid ISO UTC capture timestamp.
    """
    if not isinstance(capture_text, str):
        raise TypeError("capture timestamp must be a string")
    if not capture_text.endswith("Z"):
        raise MarketEventError("capture timestamp must be an ISO UTC timestamp")
    timestamp_text = capture_text[:-1]
    if "." in timestamp_text:
        date_text, fraction = timestamp_text.split(".", 1)
    else:
        date_text, fraction = timestamp_text, ""
    if len(date_text) != 19 or (fraction and not fraction.isdigit()):
        raise MarketEventError("capture timestamp must be an ISO UTC timestamp")
    try:
        base = datetime.fromisoformat(f"{date_text}+00:00")
    except ValueError as error:
        raise MarketEventError("capture timestamp is not a valid instant") from error
    microseconds = int((fraction + "000000")[:6])
    rounded = base.replace(microsecond=microseconds)
    if len(fraction) > 6 and any(character != "0" for character in fraction[6:]):
        rounded += timedelta(microseconds=1)
    return rounded


class TardisDecoder[T]:
    """Decode Tardis capture lines with shared framing and provenance semantics."""

    __slots__ = ("_payload_decoder", "_source_id")

    def __init__(self, payload_decoder: PayloadDecoder[T], source_id: str) -> None:
        """Bind a payload decoder and stable source identity.

        Args:
            payload_decoder: Decoder for one complete nonblank source payload.
            source_id: Nonempty source identifier for generated provenance.

        Raises:
            TypeError: ``payload_decoder`` or ``source_id`` has the wrong type.
            ValueError: ``source_id`` is empty.
        """
        if not isinstance(payload_decoder, PayloadDecoder):
            raise TypeError("payload_decoder must implement PayloadDecoder")
        if not isinstance(source_id, str):
            raise TypeError("source_id must be a string")
        if not source_id:
            raise ValueError("source_id must be nonempty")
        self._payload_decoder = payload_decoder
        self._source_id = source_id

    def decode_line(
        self,
        line: str,
        *,
        source_sequence: int,
        local_received: datetime,
        local_ingested: datetime | None = None,
        disconnect_capture_time: datetime | None = None,
        disconnect_capture_reason: Literal[
            "next_source_capture", "interval_end"
        ] = "next_source_capture",
        source_digest: str | None = None,
    ) -> T | Disconnect:
        """Decode one source line through capture and provenance handling.

        Args:
            line: Original UTF-8 line, including no trailing newline.
            source_sequence: Zero-based source line sequence, retaining tie order.
            local_received: Local receipt/ingestion time for the raw object.
            local_ingested: Optional local durable-ingestion timestamp.
            disconnect_capture_time: Conservative capture proxy for a blank line.
            disconnect_capture_reason: Reason for the blank-line capture proxy.
            source_digest: Optional raw-object digest.

        Returns:
            One decoded payload or an explicit blank-line disconnect.

        Raises:
            MarketEventError: The source line or capture framing is malformed.
            TypeError: A supplied boundary value has the wrong Python type.
            ValueError: A supplied timestamp is naive.
        """
        if isinstance(source_sequence, bool) or not isinstance(source_sequence, int):
            raise TypeError("source_sequence must be an integer")
        if source_sequence < 0:
            raise ValueError("source_sequence must be nonnegative")
        if not isinstance(line, str):
            raise TypeError("line must be a string")
        if not isinstance(local_received, datetime):
            raise TypeError("local_received must be a datetime")
        if local_received.tzinfo is None or local_received.utcoffset() is None:
            raise ValueError("local_received must be timezone-aware")
        normalized_received = local_received.astimezone(UTC)
        if line == "":
            if disconnect_capture_time is None:
                raise MarketEventError("blank disconnect requires a capture proxy")
            if not isinstance(disconnect_capture_time, datetime):
                raise TypeError("disconnect_capture_time must be a datetime")
            if (
                disconnect_capture_time.tzinfo is None
                or disconnect_capture_time.utcoffset() is None
            ):
                raise ValueError("disconnect_capture_time must be timezone-aware")
            proxy = disconnect_capture_time.astimezone(UTC)
            context = DecodeContext(
                capture_text="",
                capture_time=proxy,
                raw_line="",
                source_sequence=source_sequence,
                local_received=normalized_received,
                local_ingested=local_ingested,
                source_digest=source_digest,
                source_id=self._source_id,
            )
            if disconnect_capture_reason not in {"next_source_capture", "interval_end"}:
                raise ValueError("disconnect_capture_reason is unsupported")
            return Disconnect(
                provenance=context.provenance(event_time=proxy, event_id_suffix="disconnect"),
                capture_proxy_reason=disconnect_capture_reason,
            )

        if " " not in line:
            raise MarketEventError("source line must contain capture timestamp and JSON payload")
        capture_text, payload_text = line.split(" ", 1)
        capture = parse_capture_time(capture_text)
        context = DecodeContext(
            capture_text=capture_text,
            capture_time=capture,
            raw_line=line,
            source_sequence=source_sequence,
            local_received=normalized_received,
            local_ingested=local_ingested,
            source_digest=source_digest,
            source_id=self._source_id,
        )
        return self._payload_decoder.decode_payload(payload_text, context)


__all__ = ["TardisDecoder", "parse_capture_time"]
