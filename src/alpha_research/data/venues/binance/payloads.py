"""Decode Binance source payloads into canonical market events."""

from __future__ import annotations

# standard library imports
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

# third party library imports
import msgspec

# project library imports
from alpha_research.data.decoders import DecodeContext
from alpha_research.data.events import MarketEventError, PriceLevel, _require_int, _validate_decimal
from alpha_research.data.venues.binance.codecs import (
    _DEPTH_DECODER,
    _SNAPSHOT_DECODER,
    _TRADE_DECODER,
    BinanceEnvelope,
    _decode_binance_payload,
    _DepthPayload,
    _SnapshotPayload,
    _TradePayload,
)
from alpha_research.data.venues.binance.events import DepthSnapshot, DepthUpdate, Trade
from alpha_research.instrument_identity import InstrumentId
from alpha_research.reference_data import SpotInstrument

_BINANCE_ENVELOPE_DECODER: msgspec.json.Decoder[BinanceEnvelope] = msgspec.json.Decoder(
    BinanceEnvelope, strict=True
)


def _event_time(milliseconds: object, *, field_name: str) -> datetime:
    """Convert a millisecond Unix timestamp to a UTC datetime."""
    timestamp = _require_int(milliseconds, field_name=field_name)
    seconds, remaining_milliseconds = divmod(timestamp, 1000)
    try:
        return datetime.fromtimestamp(seconds, tz=UTC).replace(
            microsecond=remaining_milliseconds * 1000
        )
    except (OverflowError, OSError, ValueError) as error:
        raise MarketEventError(f"{field_name} is outside datetime range") from error


def _decimal_text(value: object, *, field_name: str, allow_zero: bool = True) -> Decimal:
    """Parse source decimal text while rejecting float and nonfinite values."""
    if not isinstance(value, str) or not value:
        raise MarketEventError(f"{field_name} must be decimal text")
    try:
        decimal_value = Decimal(value)
    except InvalidOperation as error:
        raise MarketEventError(f"{field_name} is not a valid decimal") from error
    try:
        return _validate_decimal(decimal_value, field_name=field_name, allow_zero=allow_zero)
    except (TypeError, ValueError) as error:
        raise MarketEventError(str(error)) from error


def _levels(value: Sequence[tuple[str, str]], *, field_name: str) -> tuple[PriceLevel, ...]:
    """Parse typed source decimal text pairs into immutable exact levels."""
    parsed: list[PriceLevel] = []
    for price_text, quantity_text in value:
        parsed.append(
            (
                _decimal_text(price_text, field_name=f"{field_name}.price", allow_zero=False),
                _decimal_text(quantity_text, field_name=f"{field_name}.quantity"),
            )
        )
    return tuple(parsed)


def _instrument_by_symbol(
    instruments: tuple[SpotInstrument, ...],
) -> dict[str, SpotInstrument]:
    """Validate and index one configured adapter instrument selection."""
    if not isinstance(instruments, tuple) or not instruments:
        raise ValueError("instruments must be a nonempty tuple")
    by_symbol: dict[str, SpotInstrument] = {}
    ids: set[InstrumentId] = set()
    for instrument in instruments:
        if not isinstance(instrument, SpotInstrument):
            raise TypeError("instruments must contain SpotInstrument records")
        instrument.validate()
        if instrument.symbol in by_symbol:
            raise ValueError("instruments contain duplicate symbols")
        if instrument.instrument_id in ids:
            raise ValueError("instruments contain duplicate instrument IDs")
        by_symbol[instrument.symbol] = instrument
        ids.add(instrument.instrument_id)
    return by_symbol


class BinancePayloadDecoder:
    """Decode Binance JSON payloads with one validated instrument selection."""

    __slots__ = ("_by_symbol",)

    def __init__(self, instruments: tuple[SpotInstrument, ...]) -> None:
        """Bind one immutable source symbol to instrument mapping.

        Args:
            instruments: Configured spot mappings used for all decoded payloads.

        Raises:
            TypeError: The selection contains a non-SpotInstrument value.
            ValueError: The selection is empty, duplicated, or invalid.
        """
        self._by_symbol = _instrument_by_symbol(instruments)

    def decode_payload(
        self, payload: str, context: DecodeContext
    ) -> DepthSnapshot | DepthUpdate | Trade:
        """Decode one Binance source object using neutral capture context.

        Args:
            payload: Complete Binance JSON envelope without a source timestamp.
            context: Immutable source capture and provenance metadata.

        Returns:
            One validated immutable Binance market event.

        Raises:
            MarketEventError: The envelope or Binance payload fields are malformed.
            TypeError: A supplied boundary value has the wrong Python type.
            ValueError: A supplied context value violates its invariant.
        """
        try:
            envelope = _BINANCE_ENVELOPE_DECODER.decode(payload)
        except (msgspec.DecodeError, TypeError, ValueError) as error:
            raise MarketEventError("source payload is not a valid Binance envelope") from error
        stream = envelope.stream
        stream_prefix, separator, stream_suffix = stream.partition("@")
        if (
            not separator
            or not stream_prefix
            or stream_suffix not in {"trade", "depth@100ms", "depthSnapshot"}
        ):
            raise MarketEventError(f"unsupported stream {stream}")
        symbol = stream_prefix.upper()
        instrument = self._by_symbol.get(symbol)
        if instrument is None:
            raise MarketEventError(f"unsupported stream symbol {symbol}")
        if stream_prefix != instrument.symbol.lower():
            raise MarketEventError("stream symbol must use lowercase venue syntax")
        if stream.endswith("@depthSnapshot"):
            snapshot_payload = _decode_binance_payload(envelope.data, _SNAPSHOT_DECODER)
            if not isinstance(snapshot_payload, _SnapshotPayload):
                raise MarketEventError("snapshot payload is invalid")
            if (
                snapshot_payload.event_marker is not msgspec.UNSET
                or snapshot_payload.event_time_marker is not msgspec.UNSET
            ):
                raise MarketEventError("depth snapshot must not invent an exchange timestamp")
            snapshot_update_id = _require_int(
                snapshot_payload.last_update_id, field_name="lastUpdateId"
            )
            return DepthSnapshot(
                provenance=context.provenance(
                    event_time=context.capture_time,
                    event_id_suffix=f"snapshot:{snapshot_update_id}",
                ),
                original_capture_time=context.capture_text,
                symbol=symbol,
                instrument_id=instrument.instrument_id,
                source_stream=stream,
                raw_line=context.raw_line,
                last_update_id=snapshot_update_id,
                bids=_levels(snapshot_payload.bids, field_name="bids"),
                asks=_levels(snapshot_payload.asks, field_name="asks"),
            )

        if stream_suffix == "depth@100ms":
            depth_payload = _decode_binance_payload(envelope.data, _DEPTH_DECODER)
            if not isinstance(depth_payload, _DepthPayload):
                raise MarketEventError("depth payload is invalid")
            if depth_payload.source_symbol != symbol:
                raise MarketEventError("stream symbol does not match payload symbol")
            first_update_id = _require_int(depth_payload.first_update_id, field_name="U")
            last_update_id = _require_int(depth_payload.last_update_id, field_name="u")
            return DepthUpdate(
                provenance=context.provenance(
                    event_time=_event_time(depth_payload.event_time, field_name="E"),
                    event_id_suffix=f"depth:{first_update_id}:{last_update_id}",
                ),
                original_capture_time=context.capture_text,
                symbol=symbol,
                instrument_id=instrument.instrument_id,
                source_stream=stream,
                raw_line=context.raw_line,
                first_update_id=first_update_id,
                last_update_id=last_update_id,
                bids=_levels(depth_payload.bids, field_name="bids"),
                asks=_levels(depth_payload.asks, field_name="asks"),
            )

        if stream_suffix == "trade":
            trade_payload = _decode_binance_payload(envelope.data, _TRADE_DECODER)
            if not isinstance(trade_payload, _TradePayload):
                raise MarketEventError("trade payload is invalid")
            if trade_payload.source_symbol != symbol:
                raise MarketEventError("stream symbol does not match payload symbol")
            trade_id = _require_int(trade_payload.trade_id, field_name="trade_id")
            return Trade(
                provenance=context.provenance(
                    event_time=_event_time(trade_payload.event_time, field_name="T"),
                    event_id_suffix=f"trade:{trade_id}",
                ),
                original_capture_time=context.capture_text,
                symbol=symbol,
                instrument_id=instrument.instrument_id,
                source_stream=stream,
                raw_line=context.raw_line,
                price=_decimal_text(trade_payload.price, field_name="price", allow_zero=False),
                quantity=_decimal_text(trade_payload.quantity, field_name="quantity"),
                trade_id=trade_id,
                is_buyer_maker=trade_payload.is_buyer_maker,
            )
        raise MarketEventError(f"stream {stream} has unsupported event type")


__all__ = ["BinancePayloadDecoder"]
