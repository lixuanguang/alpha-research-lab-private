"""Buffered streaming write helper for canonical event Parquet output."""

from __future__ import annotations

import atexit
import functools
import logging
import threading
import time
import weakref
from collections.abc import Callable
from pathlib import Path
from typing import cast

import alpha_core.events.models as event_models
import alpha_core.storage.parquet_writer as parquet_writer

_SUPPORTED_EVENT_TYPES: tuple[type[event_models.CanonicalMarketEvent], ...] = (
    event_models.CanonicalTrade,
    event_models.CanonicalBookSnapshot,
    event_models.CanonicalOHLCV,
)
_LOGGER = logging.getLogger(__name__)


def _flush_writer_at_exit(writer_ref: weakref.ReferenceType[StreamingParquetWriter]) -> None:
    writer = writer_ref()
    if writer is None:
        return
    try:
        writer.close()
    except Exception:
        _LOGGER.exception("Exit-time streaming flush failed")


class StreamingParquetWriter:
    """Buffers events and periodically rotates to new Parquet files."""

    def __init__(
        self,
        writer: parquet_writer.ParquetEventWriter,
        *,
        max_buffer_size: int = 10_000,
        max_buffer_age_seconds: float = 60.0,
    ) -> None:
        if max_buffer_size <= 0:
            raise ValueError("`max_buffer_size` must be > 0")
        if max_buffer_age_seconds <= 0:
            raise ValueError("`max_buffer_age_seconds` must be > 0")

        self._writer = writer
        self._max_buffer_size = max_buffer_size
        self._max_buffer_age_seconds = max_buffer_age_seconds
        self._buffer: list[event_models.CanonicalMarketEvent] = []
        self._buffer_started_at: float | None = None
        self._lock = threading.Lock()
        self._flush_timer: threading.Timer | None = None
        self._background_flush_error: Exception | None = None
        self._closed = False
        self._atexit_callback: Callable[[], None] | None = None
        self._register_atexit_hook()

    def append(self, event: event_models.CanonicalMarketEvent) -> None:
        if not isinstance(event, _SUPPORTED_EVENT_TYPES):
            raise TypeError(
                "Unsupported event type for streaming parquet writer: "
                f"{type(event).__name__}"
            )
        self._raise_if_background_flush_failed()
        with self._lock:
            if self._closed:
                raise RuntimeError("Cannot append after streaming writer is closed")
            if not self._buffer:
                self._buffer_started_at = time.monotonic()
                self._schedule_flush_timer_locked()
            self._buffer.append(event)
            should_flush = self._should_flush_locked()
        if should_flush:
            self.flush()

    def flush(self, *, raise_background_error: bool = True) -> dict[str, Path]:
        """Flush current buffer and return written dataset roots by event type key."""
        if raise_background_error:
            self._raise_if_background_flush_failed()
        with self._lock:
            if not self._buffer:
                return {}

            buffered = list(self._buffer)
            outputs = self._write_buffered_events(buffered)
            self._buffer.clear()
            self._buffer_started_at = None
            self._cancel_flush_timer_locked()
            return outputs

    def close(self) -> dict[str, Path]:
        """Flush remaining buffered events and return written dataset roots."""
        with self._lock:
            if self._closed:
                return {}
            self._closed = True

        try:
            return self.flush(raise_background_error=False)
        finally:
            with self._lock:
                self._cancel_flush_timer_locked()
            self._unregister_atexit_hook()

    def _write_buffered_events(
        self,
        buffered: list[event_models.CanonicalMarketEvent],
    ) -> dict[str, Path]:
        trades: list[event_models.CanonicalTrade] = []
        books: list[event_models.CanonicalBookSnapshot] = []
        candles: list[event_models.CanonicalOHLCV] = []

        for event in buffered:
            if isinstance(event, event_models.CanonicalTrade):
                trades.append(event)
            elif isinstance(event, event_models.CanonicalBookSnapshot):
                books.append(event)
            elif isinstance(event, event_models.CanonicalOHLCV):
                candles.append(event)

        outputs: dict[str, Path] = {}
        if trades:
            outputs["trades"] = self._writer.write_trades(trades)
        if books:
            outputs["books"] = self._writer.write_books(books)
        if candles:
            outputs["ohlcv"] = self._writer.write_ohlcv(candles)

        return outputs

    def _should_flush_locked(self) -> bool:
        if len(self._buffer) >= self._max_buffer_size:
            return True
        if self._buffer_started_at is None:
            return False
        return (time.monotonic() - self._buffer_started_at) >= self._max_buffer_age_seconds

    def _schedule_flush_timer_locked(self) -> None:
        self._cancel_flush_timer_locked()
        timer = threading.Timer(self._max_buffer_age_seconds, self._flush_from_timer)
        timer.daemon = True
        self._flush_timer = timer
        timer.start()

    def _cancel_flush_timer_locked(self) -> None:
        timer = self._flush_timer
        self._flush_timer = None
        if timer is not None:
            timer.cancel()

    def _flush_from_timer(self) -> None:
        try:
            self.flush(raise_background_error=False)
        except Exception as exc:
            with self._lock:
                self._background_flush_error = exc
                if not self._closed and self._buffer:
                    self._schedule_flush_timer_locked()
            _LOGGER.exception("Background streaming flush failed; buffered events retained")
        else:
            with self._lock:
                self._background_flush_error = None

    def _raise_if_background_flush_failed(self) -> None:
        with self._lock:
            error = self._background_flush_error
            self._background_flush_error = None
        if error is None:
            return
        raise RuntimeError("Background flush failed; buffered events were retained") from error

    def _register_atexit_hook(self) -> None:
        if self._atexit_callback is not None:
            return
        callback = cast(
            Callable[[], None],
            functools.partial(_flush_writer_at_exit, weakref.ref(self)),
        )
        self._atexit_callback = callback
        atexit.register(callback)

    def _unregister_atexit_hook(self) -> None:
        callback = self._atexit_callback
        if callback is None:
            return
        atexit.unregister(callback)
        self._atexit_callback = None


__all__ = ["StreamingParquetWriter"]
