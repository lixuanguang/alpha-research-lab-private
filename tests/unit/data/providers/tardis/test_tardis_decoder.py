"""Test venue-independent Tardis line framing and provenance boundaries."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from typing import Literal, Self
from uuid import UUID

# third party library imports
import msgspec
import pytest

# project library imports
from market_data.adapters.providers.tardis import TardisDecoder
from market_data.contracts import DecodeContext, Disconnect, MarketEventError, MarketEventRecord
from reference_data.instruments import InstrumentId

_INSTRUMENT_ID = InstrumentId(UUID(int=7))


class TestTardisDecoderFraming:
    """Frame provider lines with capture ceilings, provenance and disconnects."""

    def test_provider_decoder_handles_capture_ceiling_provenance_and_disconnect(self) -> None:
        """Decode a native object and blank line through shared provider framing."""
        decoder = TardisDecoder(_SyntheticPayloadDecoder(), "synthetic.source")
        line = (
            "2024-06-01T00:00:00.0000001Z "
            '{"table":"synthetic","action":"insert","data":'
            '{"event_time":"2024-06-01T00:00:02Z","symbol":"alpha","value":3}}'
        )
        event = decoder.decode_line(
            line,
            source_sequence=4,
            local_received=datetime(2024, 6, 1, 0, 0, 3, tzinfo=UTC),
        )
        assert isinstance(event, _SyntheticEvent)
        assert event.symbol == "alpha"
        assert event.value == 3
        assert event.provenance.source_id == "synthetic.source"
        assert event.provenance.source_sequence == 4
        assert event.provenance.ts_knowledge == datetime(2024, 6, 1, 0, 0, 0, 1, tzinfo=UTC)
        assert event.provenance.ts_event == datetime(2024, 6, 1, 0, 0, 2, tzinfo=UTC)
        assert event.raw_line == line

        with pytest.raises(ValueError, match="synthetic value must be positive"):
            decoder.decode_line(
                line.replace('"value":3', '"value":0'),
                source_sequence=4,
                local_received=datetime(2024, 6, 1, 0, 0, 3, tzinfo=UTC),
            )

        disconnect = decoder.decode_line(
            "",
            source_sequence=5,
            local_received=datetime(2024, 6, 1, 0, 0, 3, tzinfo=UTC),
            local_ingested=datetime(2024, 6, 1, 0, 0, 5, tzinfo=UTC),
            disconnect_capture_time=datetime(2024, 6, 1, 0, 0, 4, tzinfo=UTC),
            disconnect_capture_reason="interval_end",
        )
        assert isinstance(disconnect, Disconnect)
        assert disconnect.capture_proxy_reason == "interval_end"
        assert disconnect.provenance.source_id == "synthetic.source"
        assert disconnect.provenance.ts_knowledge == datetime(2024, 6, 1, 0, 0, 4, tzinfo=UTC)
        assert disconnect.provenance.ts_event == disconnect.provenance.ts_knowledge
        assert disconnect.provenance.ts_source_received == disconnect.provenance.ts_knowledge
        assert disconnect.provenance.ts_received == datetime(2024, 6, 1, 0, 0, 3, tzinfo=UTC)
        assert disconnect.provenance.ts_ingested == datetime(2024, 6, 1, 0, 0, 5, tzinfo=UTC)
        assert disconnect.provenance.valid_to == disconnect.provenance.valid_from + timedelta(
            microseconds=1
        )
        assert disconnect.instrument_id is None and disconnect.symbol is None

    def test_provider_decoder_rejects_malformed_line_framing(self) -> None:
        """Reject a source line without a capture and payload separator."""
        decoder = TardisDecoder(_SyntheticPayloadDecoder(), "synthetic.source")
        with pytest.raises(MarketEventError, match="capture timestamp and JSON payload"):
            decoder.decode_line(
                "not-a-framed-source-line",
                source_sequence=0,
                local_received=datetime(2024, 6, 1, tzinfo=UTC),
            )


class _SyntheticData(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Decode one source-independent payload record."""

    event_time: datetime
    symbol: str
    value: int


class _SyntheticPayload(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Decode a source-native object without a generic stream field."""

    table: Literal["synthetic"]
    action: Literal["insert"]
    data: _SyntheticData


class _SyntheticEvent(MarketEventRecord, frozen=True, kw_only=True, tag="synthetic"):
    """Represent a test-only event with a generic payload invariant."""

    event_time_basis: Literal["source_event"] = "source_event"
    value: int

    def validate(self) -> Self:
        """Require positive synthetic values after shared event validation."""
        super().validate()
        if self.value <= 0:
            raise ValueError("synthetic value must be positive")
        return self


class _SyntheticPayloadDecoder:
    """Decode the native synthetic object supplied by the framing test."""

    _decoder: msgspec.json.Decoder[_SyntheticPayload] = msgspec.json.Decoder(
        _SyntheticPayload, strict=True
    )

    def decode_payload(self, payload: str, context: DecodeContext) -> _SyntheticEvent:
        """Decode a source payload and bind its event to neutral context."""
        try:
            decoded = self._decoder.decode(payload)
        except (msgspec.DecodeError, TypeError, ValueError) as error:
            raise MarketEventError("synthetic payload is invalid") from error
        return _SyntheticEvent(
            provenance=context.provenance(
                event_time=decoded.data.event_time,
                event_id_suffix=f"value:{decoded.data.value}",
            ),
            original_capture_time=context.capture_text,
            symbol=decoded.data.symbol,
            instrument_id=_INSTRUMENT_ID,
            source_stream=decoded.table,
            raw_line=context.raw_line,
            value=decoded.data.value,
        )
