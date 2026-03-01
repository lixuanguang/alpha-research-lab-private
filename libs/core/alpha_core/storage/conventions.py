"""Shared storage conventions for tiering, partitions, and table schemas."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]


class StorageTier(StrEnum):
    """Storage tiers used by the foundation data lake layout."""

    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"


PARTITION_SCHEME: dict[str, list[str]] = {
    "silver_trades": ["venue", "date"],
    "silver_books": ["venue", "date", "hour"],
    "silver_ohlcv": ["venue", "resolution", "date"],
    "silver_book_deltas": ["venue", "date", "hour"],
    "instrument_master": ["venue"],
}

_DECIMAL_TYPE = pa.decimal128(20, 10)

TRADE_DATASET_NAME = "trades"
BOOK_DATASET_NAME = "books"
OHLCV_DATASET_NAME = "ohlcv"
BOOK_DELTA_DATASET_NAME = "book_deltas"

TRADE_PARQUET_SCHEMA = pa.schema(
    [
        pa.field("event_id", pa.string(), nullable=False),
        pa.field("instrument_id", pa.string(), nullable=False),
        pa.field("venue_id", pa.string(), nullable=False),
        pa.field("event_type", pa.string(), nullable=False),
        pa.field("ts_event", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("ts_record", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("schema_version", pa.int32(), nullable=False),
        pa.field("sequence_id", pa.string(), nullable=True),
        pa.field("ts_exchange", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("ts_receive", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("source_latency_ms", pa.float64(), nullable=True),
        pa.field("sequence_id_capable", pa.bool_(), nullable=True),
        pa.field("latency_metadata_capable", pa.bool_(), nullable=True),
        pa.field("price", _DECIMAL_TYPE, nullable=False),
        pa.field("size", _DECIMAL_TYPE, nullable=False),
        pa.field("side", pa.string(), nullable=False),
        pa.field("trade_id", pa.string(), nullable=False),
        pa.field("venue", pa.string(), nullable=False),
        pa.field("date", pa.string(), nullable=False),
    ]
)

BOOK_PARQUET_SCHEMA = pa.schema(
    [
        pa.field("event_id", pa.string(), nullable=False),
        pa.field("instrument_id", pa.string(), nullable=False),
        pa.field("venue_id", pa.string(), nullable=False),
        pa.field("event_type", pa.string(), nullable=False),
        pa.field("ts_event", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("ts_record", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("schema_version", pa.int32(), nullable=False),
        pa.field("sequence_id", pa.string(), nullable=True),
        pa.field("ts_exchange", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("ts_receive", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("source_latency_ms", pa.float64(), nullable=True),
        pa.field("sequence_id_capable", pa.bool_(), nullable=True),
        pa.field("latency_metadata_capable", pa.bool_(), nullable=True),
        pa.field("bids_json", pa.string(), nullable=False),
        pa.field("asks_json", pa.string(), nullable=False),
        pa.field("venue", pa.string(), nullable=False),
        pa.field("date", pa.string(), nullable=False),
        pa.field("hour", pa.string(), nullable=False),
    ]
)

OHLCV_PARQUET_SCHEMA = pa.schema(
    [
        pa.field("event_id", pa.string(), nullable=False),
        pa.field("instrument_id", pa.string(), nullable=False),
        pa.field("venue_id", pa.string(), nullable=False),
        pa.field("event_type", pa.string(), nullable=False),
        pa.field("ts_event", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("ts_record", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("schema_version", pa.int32(), nullable=False),
        pa.field("sequence_id", pa.string(), nullable=True),
        pa.field("ts_exchange", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("ts_receive", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("source_latency_ms", pa.float64(), nullable=True),
        pa.field("sequence_id_capable", pa.bool_(), nullable=True),
        pa.field("latency_metadata_capable", pa.bool_(), nullable=True),
        pa.field("open", _DECIMAL_TYPE, nullable=False),
        pa.field("high", _DECIMAL_TYPE, nullable=False),
        pa.field("low", _DECIMAL_TYPE, nullable=False),
        pa.field("close", _DECIMAL_TYPE, nullable=False),
        pa.field("volume", _DECIMAL_TYPE, nullable=False),
        pa.field("resolution", pa.string(), nullable=False),
        pa.field("venue", pa.string(), nullable=False),
        pa.field("date", pa.string(), nullable=False),
    ]
)

# Schema for incremental order-book delta events (F6 extension).
# `is_reconstructed` marks deltas synthesised from a snapshot rather than
# received natively from a venue delta feed.
BOOK_DELTA_PARQUET_SCHEMA = pa.schema(
    [
        pa.field("event_id", pa.string(), nullable=False),
        pa.field("instrument_id", pa.string(), nullable=False),
        pa.field("venue_id", pa.string(), nullable=False),
        pa.field("event_type", pa.string(), nullable=False),
        pa.field("ts_event", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("ts_record", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("schema_version", pa.int32(), nullable=False),
        pa.field("ts_exchange", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("ts_receive", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("source_latency_ms", pa.float64(), nullable=True),
        pa.field("sequence_id_capable", pa.bool_(), nullable=True),
        pa.field("latency_metadata_capable", pa.bool_(), nullable=True),
        pa.field("side", pa.string(), nullable=False),
        pa.field("price", _DECIMAL_TYPE, nullable=False),
        pa.field("delta_size", _DECIMAL_TYPE, nullable=False),
        pa.field("reason", pa.string(), nullable=False),
        pa.field("sequence_id", pa.string(), nullable=True),
        pa.field("is_reconstructed", pa.bool_(), nullable=False),
        pa.field("venue", pa.string(), nullable=False),
        pa.field("date", pa.string(), nullable=False),
        pa.field("hour", pa.string(), nullable=False),
    ]
)


def resolve_partition_columns(dataset_key: str) -> list[str]:
    """Return partition columns for a storage dataset key."""
    if dataset_key not in PARTITION_SCHEME:
        raise KeyError(f"Unknown storage dataset key: {dataset_key}")
    return PARTITION_SCHEME[dataset_key]


def dataset_root(storage_root: Path, tier: StorageTier, dataset_name: str) -> Path:
    """Return canonical dataset root path for a tier and dataset name."""
    return storage_root / tier.value / dataset_name
