"""Canonical market data models for prediction-market event normalization."""

from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

import alpha_core.events.schema_version as schema_version
import alpha_core.utils.ids as ids_utils
import alpha_core.utils.time as time_utils


class EventType(StrEnum):
    """Canonical event categories supported by the platform."""

    TRADE = "trade"
    BOOK_SNAPSHOT = "book_snapshot"
    BOOK_DELTA = "book_delta"
    OHLCV = "ohlcv"
    METADATA_UPDATE = "metadata_update"


class TradeSide(StrEnum):
    """Canonical trade side representation."""

    BUY = "buy"
    SELL = "sell"


_AUTO_EVENT_ID_SENTINEL = "__alpha_auto_event_id__"

# Fields that annotate an event with extra metadata but do not affect its
# canonical identity.  Excluded from the event_id hash so that enriching a
# payload (e.g. adding ts_exchange after the fact) does not silently break ID
# checks.
_EVENT_ID_EXCLUDE_FIELDS: frozenset[str] = frozenset(
    {"event_id", "ts_exchange", "ts_receive", "source_latency_ms"}
)
_EVENT_ID_EXCLUDE_EVENT_TYPES_FOR_SEQUENCE_ID: frozenset[EventType] = frozenset(
    {
        EventType.TRADE,
        EventType.BOOK_SNAPSHOT,
        EventType.OHLCV,
        EventType.METADATA_UPDATE,
    }
)


def event_id_exclude_fields(event_type: EventType) -> set[str]:
    """Return fields excluded from event-id hashing for a specific event type."""
    excluded = set(_EVENT_ID_EXCLUDE_FIELDS)
    if event_type in _EVENT_ID_EXCLUDE_EVENT_TYPES_FOR_SEQUENCE_ID:
        excluded.add("sequence_id")
    return excluded


class PriceLevel(BaseModel):
    """Order book price level for a single side of the book."""

    model_config = ConfigDict(extra="forbid")

    price: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    size: Decimal = Field(ge=Decimal("0"))


class CanonicalMarketEvent(BaseModel):
    """Base for all canonical market data events."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1)
    instrument_id: str = Field(min_length=1)
    venue_id: str = Field(min_length=1)
    event_type: EventType
    ts_event: datetime
    ts_record: datetime
    schema_version: int = Field(default=schema_version.CANONICAL_EVENT_SCHEMA_VERSION, ge=1)

    # Optional microstructure metadata (F3 extension)
    sequence_id: str | None = None
    ts_exchange: datetime | None = None
    ts_receive: datetime | None = None
    source_latency_ms: float | None = None

    @model_validator(mode="before")
    @classmethod
    def _fill_missing_event_id(cls, data: object) -> object:
        if isinstance(data, dict) and "event_id" not in data:
            payload = dict(data)
            payload["event_id"] = _AUTO_EVENT_ID_SENTINEL
            return payload
        return data

    @field_validator("event_id", "instrument_id", "venue_id")
    @classmethod
    def _strip_and_require_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value cannot be empty")
        return cleaned

    @field_validator("venue_id")
    @classmethod
    def _normalize_venue_id(cls, value: str) -> str:
        return value.lower()

    @field_validator("ts_event", "ts_record")
    @classmethod
    def _normalize_utc(cls, value: datetime) -> datetime:
        return time_utils.ensure_utc(value)

    @field_validator("ts_exchange", "ts_receive")
    @classmethod
    def _normalize_optional_utc(cls, value: datetime | None) -> datetime | None:
        return time_utils.ensure_utc(value) if value is not None else None

    @field_validator("source_latency_ms")
    @classmethod
    def _validate_optional_latency_ms(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if not math.isfinite(value):
            raise ValueError("`source_latency_ms` must be finite when provided")
        if value < 0:
            raise ValueError("`source_latency_ms` must be >= 0 when provided")
        return value

    @model_validator(mode="after")
    def _validate_bitemporal_order(self) -> CanonicalMarketEvent:
        if self.ts_event > self.ts_record:
            raise ValueError("`ts_event` must be less than or equal to `ts_record`")
        return self

    @model_validator(mode="after")
    def _validate_event_id(self) -> CanonicalMarketEvent:
        exclude_fields = event_id_exclude_fields(self.event_type)
        expected = ids_utils.generate_event_id(
            self.model_dump(exclude=exclude_fields, exclude_none=True)
        )
        if self.event_id == _AUTO_EVENT_ID_SENTINEL:
            self.event_id = expected
            return self
        if self.event_id != expected:
            raise ValueError("`event_id` must match canonical payload hash")
        return self


class CanonicalTrade(CanonicalMarketEvent):
    """Canonical trade event for prediction markets."""

    event_type: Literal[EventType.TRADE] = EventType.TRADE
    price: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    size: Decimal = Field(gt=Decimal("0"))
    side: TradeSide
    trade_id: str = Field(min_length=1)


class CanonicalBookSnapshot(CanonicalMarketEvent):
    """Canonical L2 order book snapshot event."""

    event_type: Literal[EventType.BOOK_SNAPSHOT] = EventType.BOOK_SNAPSHOT
    bids: list[PriceLevel] = Field(default_factory=list)
    asks: list[PriceLevel] = Field(default_factory=list)


class CanonicalOHLCV(CanonicalMarketEvent):
    """Canonical OHLCV bar event."""

    event_type: Literal[EventType.OHLCV] = EventType.OHLCV
    open: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    high: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    low: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    close: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    volume: Decimal = Field(ge=Decimal("0"))
    resolution: Literal["1m", "5m", "1h", "1d"]

    @model_validator(mode="after")
    def _validate_ohlc_consistency(self) -> CanonicalOHLCV:
        if self.low > self.high:
            raise ValueError("`low` cannot exceed `high`")
        if self.open < self.low or self.open > self.high:
            raise ValueError("`open` must be within [low, high]")
        if self.close < self.low or self.close > self.high:
            raise ValueError("`close` must be within [low, high]")
        return self


class CanonicalBookDelta(CanonicalMarketEvent):
    """Canonical order book delta (incremental update) event.

    Represents a single-level change to one side of the book, as emitted by
    venues that support delta-feed semantics.  ``reason`` identifies whether
    the change resulted from a new resting order ('add'), a cancellation
    ('cancel'), or a trade execution ('trade').
    """

    event_type: Literal[EventType.BOOK_DELTA] = EventType.BOOK_DELTA
    side: Literal["bid", "ask"]
    price: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    delta_size: Decimal
    reason: Literal["add", "cancel", "trade"]
    sequence_id: str | None = None  # venue-level sequence number for ordering


class CanonicalMetadataUpdate(CanonicalMarketEvent):
    """Canonical metadata update event for instrument or market-level changes."""

    event_type: Literal[EventType.METADATA_UPDATE] = EventType.METADATA_UPDATE
    fields_changed: dict[str, Any] = Field(default_factory=dict)
