"""Parquet writers for canonical market events."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

import alpha_core.events.models as event_models
import alpha_core.storage.conventions as storage_conventions
import alpha_core.utils.time as time_utils

_FILE_STEM_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ParquetEventWriter:
    """Write canonical events to partitioned Parquet datasets."""

    def __init__(self, storage_root: Path, compression: str = "zstd") -> None:
        self._storage_root = storage_root
        self._compression = compression

    def write_trades(
        self,
        trades: list[event_models.CanonicalTrade],
        tier: storage_conventions.StorageTier = storage_conventions.StorageTier.SILVER,
        *,
        file_stem_token: str | None = None,
    ) -> Path:
        """Write canonical trades to the configured storage tier."""
        dataset_root = storage_conventions.dataset_root(
            self._storage_root,
            tier,
            storage_conventions.TRADE_DATASET_NAME,
        )
        dataset_root.mkdir(parents=True, exist_ok=True)
        if not trades:
            return dataset_root

        rows = [self._trade_to_row(trade) for trade in trades]
        self._write_partitioned_table(
            rows=rows,
            schema=storage_conventions.TRADE_PARQUET_SCHEMA,
            dataset_root=dataset_root,
            partition_cols=storage_conventions.resolve_partition_columns("silver_trades"),
            file_stem_token=file_stem_token,
        )
        return dataset_root

    def write_books(
        self,
        books: list[event_models.CanonicalBookSnapshot],
        tier: storage_conventions.StorageTier = storage_conventions.StorageTier.SILVER,
    ) -> Path:
        """Write canonical order book snapshots to the configured storage tier."""
        dataset_root = storage_conventions.dataset_root(
            self._storage_root,
            tier,
            storage_conventions.BOOK_DATASET_NAME,
        )
        dataset_root.mkdir(parents=True, exist_ok=True)
        if not books:
            return dataset_root

        rows = [self._book_to_row(book) for book in books]
        self._write_partitioned_table(
            rows=rows,
            schema=storage_conventions.BOOK_PARQUET_SCHEMA,
            dataset_root=dataset_root,
            partition_cols=storage_conventions.resolve_partition_columns("silver_books"),
        )
        return dataset_root

    def write_ohlcv(
        self,
        candles: list[event_models.CanonicalOHLCV],
        tier: storage_conventions.StorageTier = storage_conventions.StorageTier.SILVER,
        *,
        file_stem_token: str | None = None,
    ) -> Path:
        """Write canonical OHLCV bars to the configured storage tier."""
        dataset_root = storage_conventions.dataset_root(
            self._storage_root,
            tier,
            storage_conventions.OHLCV_DATASET_NAME,
        )
        dataset_root.mkdir(parents=True, exist_ok=True)
        if not candles:
            return dataset_root

        rows = [self._ohlcv_to_row(candle) for candle in candles]
        self._write_partitioned_table(
            rows=rows,
            schema=storage_conventions.OHLCV_PARQUET_SCHEMA,
            dataset_root=dataset_root,
            partition_cols=storage_conventions.resolve_partition_columns("silver_ohlcv"),
            file_stem_token=file_stem_token,
        )
        return dataset_root

    def write_book_deltas(
        self,
        deltas: list[event_models.CanonicalBookDelta],
        tier: storage_conventions.StorageTier = storage_conventions.StorageTier.SILVER,
        *,
        is_reconstructed: bool = False,
    ) -> Path:
        """Write canonical book delta events to the configured storage tier.

        Args:
            deltas: Canonical book delta events to persist.
            tier: Storage tier to write into (default: SILVER).
            is_reconstructed: Batch-level override — when ``True`` every row in
                this call is marked as reconstructed regardless of the per-event
                flag.  Per-event ``delta.is_reconstructed`` is always ORed with
                this value, so individually-tagged deltas are preserved even
                when the batch flag is ``False``.
        """
        dataset_root = storage_conventions.dataset_root(
            self._storage_root,
            tier,
            storage_conventions.BOOK_DELTA_DATASET_NAME,
        )
        dataset_root.mkdir(parents=True, exist_ok=True)
        if not deltas:
            return dataset_root

        rows = [
            self._book_delta_to_row(delta, is_reconstructed=is_reconstructed) for delta in deltas
        ]
        self._write_partitioned_table(
            rows=rows,
            schema=storage_conventions.BOOK_DELTA_PARQUET_SCHEMA,
            dataset_root=dataset_root,
            partition_cols=storage_conventions.resolve_partition_columns("silver_book_deltas"),
        )
        return dataset_root

    def _write_partitioned_table(
        self,
        rows: list[dict[str, object]],
        schema: pa.Schema,
        dataset_root: Path,
        partition_cols: list[str],
        file_stem_token: str | None = None,
    ) -> None:
        table = pa.Table.from_pylist(rows, schema=schema)
        basename_template = None
        if file_stem_token is not None:
            normalized_token = _normalize_file_stem_token(file_stem_token)
            basename_template = f"run_{normalized_token}_{uuid.uuid4().hex}-{{i}}.parquet"
        pq.write_to_dataset(
            table,
            root_path=str(dataset_root),
            partition_cols=partition_cols,
            compression=self._compression,
            basename_template=basename_template,
        )

    @staticmethod
    def _trade_to_row(trade: event_models.CanonicalTrade) -> dict[str, object]:
        ts_event = time_utils.ensure_utc(trade.ts_event)
        return {
            "event_id": trade.event_id,
            "instrument_id": trade.instrument_id,
            "venue_id": trade.venue_id,
            "event_type": trade.event_type.value,
            "ts_event": ts_event,
            "ts_record": time_utils.ensure_utc(trade.ts_record),
            "schema_version": trade.schema_version,
            "sequence_id": trade.sequence_id,
            "ts_exchange": time_utils.ensure_utc(trade.ts_exchange)
            if trade.ts_exchange is not None
            else None,
            "ts_receive": time_utils.ensure_utc(trade.ts_receive)
            if trade.ts_receive is not None
            else None,
            "source_latency_ms": trade.source_latency_ms,
            "sequence_id_capable": trade.sequence_id_capable,
            "latency_metadata_capable": trade.latency_metadata_capable,
            "price": trade.price,
            "size": trade.size,
            "side": trade.side.value,
            "trade_id": trade.trade_id,
            "venue": trade.venue_id,
            "date": ts_event.date().isoformat(),
        }

    @staticmethod
    def _book_to_row(book: event_models.CanonicalBookSnapshot) -> dict[str, object]:
        ts_event = time_utils.ensure_utc(book.ts_event)
        return {
            "event_id": book.event_id,
            "instrument_id": book.instrument_id,
            "venue_id": book.venue_id,
            "event_type": book.event_type.value,
            "ts_event": ts_event,
            "ts_record": time_utils.ensure_utc(book.ts_record),
            "schema_version": book.schema_version,
            "sequence_id": book.sequence_id,
            "ts_exchange": time_utils.ensure_utc(book.ts_exchange)
            if book.ts_exchange is not None
            else None,
            "ts_receive": time_utils.ensure_utc(book.ts_receive)
            if book.ts_receive is not None
            else None,
            "source_latency_ms": book.source_latency_ms,
            "sequence_id_capable": book.sequence_id_capable,
            "latency_metadata_capable": book.latency_metadata_capable,
            "bids_json": _encode_price_levels(book.bids),
            "asks_json": _encode_price_levels(book.asks),
            "venue": book.venue_id,
            "date": ts_event.date().isoformat(),
            "hour": ts_event.strftime("%H"),
        }

    @staticmethod
    def _ohlcv_to_row(candle: event_models.CanonicalOHLCV) -> dict[str, object]:
        ts_event = time_utils.ensure_utc(candle.ts_event)
        return {
            "event_id": candle.event_id,
            "instrument_id": candle.instrument_id,
            "venue_id": candle.venue_id,
            "event_type": candle.event_type.value,
            "ts_event": ts_event,
            "ts_record": time_utils.ensure_utc(candle.ts_record),
            "schema_version": candle.schema_version,
            "sequence_id": candle.sequence_id,
            "ts_exchange": time_utils.ensure_utc(candle.ts_exchange)
            if candle.ts_exchange is not None
            else None,
            "ts_receive": time_utils.ensure_utc(candle.ts_receive)
            if candle.ts_receive is not None
            else None,
            "source_latency_ms": candle.source_latency_ms,
            "sequence_id_capable": candle.sequence_id_capable,
            "latency_metadata_capable": candle.latency_metadata_capable,
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
            "resolution": candle.resolution,
            "venue": candle.venue_id,
            "date": ts_event.date().isoformat(),
        }

    @staticmethod
    def _book_delta_to_row(
        delta: event_models.CanonicalBookDelta,
        *,
        is_reconstructed: bool,
    ) -> dict[str, object]:
        ts_event = time_utils.ensure_utc(delta.ts_event)
        return {
            "event_id": delta.event_id,
            "instrument_id": delta.instrument_id,
            "venue_id": delta.venue_id,
            "event_type": delta.event_type.value,
            "ts_event": ts_event,
            "ts_record": time_utils.ensure_utc(delta.ts_record),
            "schema_version": delta.schema_version,
            "ts_exchange": time_utils.ensure_utc(delta.ts_exchange)
            if delta.ts_exchange is not None
            else None,
            "ts_receive": time_utils.ensure_utc(delta.ts_receive)
            if delta.ts_receive is not None
            else None,
            "source_latency_ms": delta.source_latency_ms,
            "sequence_id_capable": delta.sequence_id_capable,
            "latency_metadata_capable": delta.latency_metadata_capable,
            "side": delta.side,
            "price": delta.price,
            "delta_size": delta.delta_size,
            "reason": delta.reason,
            "sequence_id": delta.sequence_id,
            "is_reconstructed": is_reconstructed or delta.is_reconstructed,
            "venue": delta.venue_id,
            "date": ts_event.date().isoformat(),
            "hour": ts_event.strftime("%H"),
        }


def _encode_price_levels(levels: list[event_models.PriceLevel]) -> str:
    payload = [{"price": str(level.price), "size": str(level.size)} for level in levels]
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _normalize_file_stem_token(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("`file_stem_token` must be non-empty")
    if _FILE_STEM_TOKEN_RE.fullmatch(cleaned) is None:
        raise ValueError("`file_stem_token` contains unsupported characters; use [A-Za-z0-9._-]")
    return cleaned


__all__ = ["ParquetEventWriter"]
