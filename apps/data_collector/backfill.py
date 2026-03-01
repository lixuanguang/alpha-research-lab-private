"""Historical data backfill orchestration."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TypeVar

from pydantic import BaseModel, ConfigDict

import alpha_core.adapters.base as adapters_base
import alpha_core.events.models as event_models
import alpha_core.events.quality as event_quality
import alpha_core.quality.gap_detector as quality_gap_detector
import alpha_core.storage.bronze_writer as storage_bronze
import alpha_core.storage.lineage as storage_lineage
import alpha_core.storage.parquet_writer as storage_parquet
import alpha_core.utils.time as time_utils
import apps.data_collector.connectors.raw_payloads as connector_raw_payloads

# Maximum candles fetched per OHLCV backfill call (capped to avoid unreasonably large requests)
_MAX_OHLCV_LIMIT = 10_000

# Resolution label → seconds per candle
_RESOLUTION_SECONDS: dict[str, float] = {
    "1m": 60.0,
    "5m": 300.0,
    "1h": 3600.0,
    "1d": 86400.0,
}
_FETCH_RETRY_ATTEMPTS = 3
_FETCH_RETRY_BACKOFF_BASE_SECONDS = 0.25
_FETCH_RETRY_BACKOFF_MAX_SECONDS = 2.0
_ResultT = TypeVar("_ResultT")


@dataclass(slots=True)
class _TradePaginationState:
    """Mutable pagination state for one outcome trade backfill."""

    cursor: datetime | None
    stalled_iterations: int = 0
    seen_trade_keys: set[tuple[str, str]] = field(default_factory=set)


class BackfillResult(BaseModel):
    """Result of one backfill operation."""

    model_config = ConfigDict(extra="forbid")

    venue: str
    event_type: str
    outcome_ids: list[str]
    window_start: datetime
    window_end: datetime
    events_fetched: int
    events_stored: int
    events_rejected: int
    duration_seconds: float
    run_id: str


class BackfillManager:
    """Orchestrates historical data backfills for specific time windows."""

    def __init__(
        self,
        adapter: adapters_base.VenueAdapter,
        bronze_writer: storage_bronze.BronzeWriter,
        silver_writer: storage_parquet.ParquetEventWriter,
        quality_checker: event_quality.EventQualityChecker,
        lineage_store: storage_lineage.LineageStore,
        fetch_retry_attempts: int = _FETCH_RETRY_ATTEMPTS,
        fetch_retry_backoff_base_seconds: float = _FETCH_RETRY_BACKOFF_BASE_SECONDS,
        fetch_retry_backoff_max_seconds: float = _FETCH_RETRY_BACKOFF_MAX_SECONDS,
    ) -> None:
        if fetch_retry_attempts <= 0:
            raise ValueError("`fetch_retry_attempts` must be > 0")
        if fetch_retry_backoff_base_seconds <= 0:
            raise ValueError("`fetch_retry_backoff_base_seconds` must be > 0")
        if fetch_retry_backoff_max_seconds < fetch_retry_backoff_base_seconds:
            raise ValueError(
                "`fetch_retry_backoff_max_seconds` must be >= `fetch_retry_backoff_base_seconds`"
            )
        self._venue = adapter.venue_name()
        self._adapter = adapter
        self._bronze_writer = bronze_writer
        self._silver_writer = silver_writer
        self._quality_checker = quality_checker
        self._lineage_store = lineage_store
        self._fetch_retry_attempts = fetch_retry_attempts
        self._fetch_retry_backoff_base_seconds = fetch_retry_backoff_base_seconds
        self._fetch_retry_backoff_max_seconds = fetch_retry_backoff_max_seconds

    async def backfill_trades(
        self,
        outcome_ids: list[str],
        *,
        start: datetime,
        end: datetime,
        batch_size: int = 500,
    ) -> BackfillResult:
        """Fetch historical trades in batches, store bronze + silver."""
        if batch_size <= 0:
            raise ValueError("`batch_size` must be > 0")
        if not outcome_ids:
            raise ValueError("`outcome_ids` must be non-empty")

        start_utc = time_utils.ensure_utc(start)
        end_utc = time_utils.ensure_utc(end)
        _validate_window(start_utc, end_utc)

        run = self._lineage_store.start_run(
            venue=self._venue,
            connector_type="polling",
            event_types=["trades"],
            config_snapshot={
                "window_start": start_utc.isoformat(),
                "window_end": end_utc.isoformat(),
                "batch_size": batch_size,
            },
        )
        monotonic_start = time.monotonic()
        errors: list[str] = []
        fetched_total = 0
        stored_total = 0
        rejected_total = 0

        try:
            for outcome_id in outcome_ids:
                try:
                    trades, raw = await _fetch_trades_windowed(
                        self._adapter,
                        outcome_id,
                        start=start_utc,
                        end=end_utc,
                        batch_size=batch_size,
                        fetch_retry_attempts=self._fetch_retry_attempts,
                        fetch_retry_backoff_base_seconds=self._fetch_retry_backoff_base_seconds,
                        fetch_retry_backoff_max_seconds=self._fetch_retry_backoff_max_seconds,
                    )
                except Exception as exc:
                    errors.append(f"outcome={outcome_id}: {exc}")
                    continue

                trades.sort(key=lambda trade: (trade.instrument_id, trade.ts_event, trade.trade_id))
                valid_trades, rejected = _filter_quality_trades(self._quality_checker, trades)

                fetched_total += len(trades)
                stored_total += len(valid_trades)
                rejected_total += rejected

                if raw:
                    self._bronze_writer.write_raw_events(
                        raw,
                        venue=self._venue,
                        event_type="trades",
                        run_id=run.run_id,
                    )
                if valid_trades:
                    self._silver_writer.write_trades(valid_trades)

            self._lineage_store.complete_run(
                run.run_id,
                counts={
                    "events_raw": fetched_total,
                    "events_silver": stored_total,
                    "rejected": rejected_total,
                },
                errors=errors,
            )
        except Exception as exc:
            self._lineage_store.fail_run(run.run_id, str(exc))
            raise

        return BackfillResult(
            venue=self._venue,
            event_type="trades",
            outcome_ids=list(outcome_ids),
            window_start=start_utc,
            window_end=end_utc,
            events_fetched=fetched_total,
            events_stored=stored_total,
            events_rejected=rejected_total,
            duration_seconds=time.monotonic() - monotonic_start,
            run_id=run.run_id,
        )

    async def backfill_ohlcv(
        self,
        outcome_ids: list[str],
        *,
        resolution: str = "1h",
        start: datetime,
        end: datetime,
    ) -> BackfillResult:
        """Fetch historical OHLCV candles, store bronze + silver."""
        if not outcome_ids:
            raise ValueError("`outcome_ids` must be non-empty")
        if resolution not in _RESOLUTION_SECONDS:
            raise ValueError(
                f"Unknown resolution '{resolution}'. "
                f"Expected one of {list(_RESOLUTION_SECONDS)}"
            )

        start_utc = time_utils.ensure_utc(start)
        end_utc = time_utils.ensure_utc(end)
        _validate_window(start_utc, end_utc)

        candle_seconds = _RESOLUTION_SECONDS[resolution]
        window_seconds = (end_utc - start_utc).total_seconds()
        limit = min(math.ceil(window_seconds / candle_seconds) + 5, _MAX_OHLCV_LIMIT)

        run = self._lineage_store.start_run(
            venue=self._venue,
            connector_type="polling",
            event_types=["ohlcv"],
            config_snapshot={
                "window_start": start_utc.isoformat(),
                "window_end": end_utc.isoformat(),
                "resolution": resolution,
            },
        )
        monotonic_start = time.monotonic()
        errors: list[str] = []
        fetched_total = 0
        stored_total = 0
        rejected_total = 0

        try:
            for outcome_id in outcome_ids:
                try:
                    candles, raw = await _call_with_retries(
                        lambda: self._adapter.fetch_ohlcv_with_raw(
                            outcome_id,
                            resolution=resolution,
                            limit=limit,
                        ),
                        operation="fetch_ohlcv_with_raw",
                        outcome_id=outcome_id,
                        max_attempts=self._fetch_retry_attempts,
                        backoff_base_seconds=self._fetch_retry_backoff_base_seconds,
                        backoff_max_seconds=self._fetch_retry_backoff_max_seconds,
                    )
                    normalized_raw = connector_raw_payloads.normalize_raw_payloads(
                        raw, outcome_id=outcome_id
                    )
                    in_window_candles, in_window_raw = _filter_ohlcv_window_with_raw(
                        candles,
                        normalized_raw,
                        start=start_utc,
                        end=end_utc,
                    )
                except Exception as exc:
                    errors.append(f"outcome={outcome_id}: {exc}")
                    continue

                in_window_candles.sort(
                    key=lambda candle: (candle.instrument_id, candle.ts_event, candle.resolution)
                )
                valid_candles, rejected = _filter_quality_candles(
                    self._quality_checker,
                    in_window_candles,
                )
                fetched_total += len(in_window_candles)
                stored_total += len(valid_candles)
                rejected_total += rejected

                if in_window_raw:
                    self._bronze_writer.write_raw_events(
                        in_window_raw,
                        venue=self._venue,
                        event_type="ohlcv",
                        run_id=run.run_id,
                    )
                if valid_candles:
                    self._silver_writer.write_ohlcv(valid_candles)

            self._lineage_store.complete_run(
                run.run_id,
                counts={
                    "events_raw": fetched_total,
                    "events_silver": stored_total,
                    "rejected": rejected_total,
                },
                errors=errors,
            )
        except Exception as exc:
            self._lineage_store.fail_run(run.run_id, str(exc))
            raise

        return BackfillResult(
            venue=self._venue,
            event_type="ohlcv",
            outcome_ids=list(outcome_ids),
            window_start=start_utc,
            window_end=end_utc,
            events_fetched=fetched_total,
            events_stored=stored_total,
            events_rejected=rejected_total,
            duration_seconds=time.monotonic() - monotonic_start,
            run_id=run.run_id,
        )

    async def fill_gaps(self, gaps: list[quality_gap_detector.TimeGap]) -> list[BackfillResult]:
        """Automatically backfill detected gaps, routing by event_type."""
        results: list[BackfillResult] = []
        for gap in gaps:
            if gap.event_type == "trade":
                result = await self.backfill_trades(
                    [gap.outcome_id],
                    start=gap.gap_start,
                    end=gap.gap_end,
                )
            else:
                result = await self.backfill_ohlcv(
                    [gap.outcome_id],
                    start=gap.gap_start,
                    end=gap.gap_end,
                )
            results.append(result)
        return results


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _fetch_trades_windowed(
    adapter: adapters_base.VenueAdapter,
    outcome_id: str,
    *,
    start: datetime,
    end: datetime,
    batch_size: int,
    fetch_retry_attempts: int,
    fetch_retry_backoff_base_seconds: float,
    fetch_retry_backoff_max_seconds: float,
) -> tuple[list[event_models.CanonicalTrade], list[dict[str, object]]]:
    """Paginate fetch_trades_with_raw to collect all trades in [start, end]."""
    all_trades: list[event_models.CanonicalTrade] = []
    all_raw: list[dict[str, object]] = []
    state = _TradePaginationState(cursor=start)

    while True:
        trades, normalized_raw = await _fetch_trade_page(
            adapter,
            outcome_id=outcome_id,
            cursor=state.cursor,
            batch_size=batch_size,
            fetch_retry_attempts=fetch_retry_attempts,
            fetch_retry_backoff_base_seconds=fetch_retry_backoff_base_seconds,
            fetch_retry_backoff_max_seconds=fetch_retry_backoff_max_seconds,
        )
        if not trades:
            break

        new_rows = _append_windowed_unique_trades(
            trades=trades,
            normalized_raw=normalized_raw,
            start=start,
            end=end,
            state=state,
            all_trades=all_trades,
            all_raw=all_raw,
        )
        max_ts = max(t.ts_event for t in trades)
        if _should_stop_trade_pagination(
            max_ts=max_ts,
            end=end,
            page_size=len(trades),
            batch_size=batch_size,
        ):
            break
        _update_trade_pagination_state(state, max_ts=max_ts, new_rows=new_rows)

    return all_trades, all_raw


async def _fetch_trade_page(
    adapter: adapters_base.VenueAdapter,
    *,
    outcome_id: str,
    cursor: datetime | None,
    batch_size: int,
    fetch_retry_attempts: int,
    fetch_retry_backoff_base_seconds: float,
    fetch_retry_backoff_max_seconds: float,
) -> tuple[list[event_models.CanonicalTrade], list[dict[str, object]]]:
    raw_result: list[object]
    trades, raw_result = await _call_with_retries(
        lambda: adapter.fetch_trades_with_raw(
            outcome_id,
            since=cursor,
            limit=batch_size,
        ),
        operation="fetch_trades_with_raw",
        outcome_id=outcome_id,
        max_attempts=fetch_retry_attempts,
        backoff_base_seconds=fetch_retry_backoff_base_seconds,
        backoff_max_seconds=fetch_retry_backoff_max_seconds,
    )
    normalized_raw = connector_raw_payloads.normalize_raw_payloads(
        raw_result,
        outcome_id=outcome_id,
    )
    return trades, normalized_raw


async def _call_with_retries(
    fn: Callable[[], Awaitable[_ResultT]],
    *,
    operation: str,
    outcome_id: str,
    max_attempts: int,
    backoff_base_seconds: float,
    backoff_max_seconds: float,
) -> _ResultT:
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return await fn()
        except Exception as exc:
            last_error = exc
            if attempt + 1 >= max_attempts:
                break
            delay_seconds = min(backoff_max_seconds, backoff_base_seconds * (2**attempt))
            await asyncio.sleep(delay_seconds)
    raise RuntimeError(
        f"{operation} failed after {max_attempts} attempt(s) "
        f"for outcome `{outcome_id}`: {last_error}"
    ) from last_error


def _append_windowed_unique_trades(
    *,
    trades: list[event_models.CanonicalTrade],
    normalized_raw: list[dict[str, object]],
    start: datetime,
    end: datetime,
    state: _TradePaginationState,
    all_trades: list[event_models.CanonicalTrade],
    all_raw: list[dict[str, object]],
) -> int:
    new_rows = 0
    for trade, raw_payload in _pair_trades_with_raw_payloads(trades, normalized_raw):
        if not (start <= trade.ts_event <= end):
            continue
        trade_key = (trade.instrument_id, trade.trade_id)
        if trade_key in state.seen_trade_keys:
            continue

        state.seen_trade_keys.add(trade_key)
        all_trades.append(trade)
        if raw_payload is not None:
            all_raw.append(raw_payload)
        new_rows += 1
    return new_rows


def _pair_trades_with_raw_payloads(
    trades: list[event_models.CanonicalTrade],
    normalized_raw: list[dict[str, object]],
) -> Iterable[tuple[event_models.CanonicalTrade, dict[str, object] | None]]:
    if len(normalized_raw) == len(trades):
        return zip(trades, normalized_raw, strict=True)
    return ((trade, None) for trade in trades)


def _should_stop_trade_pagination(
    *,
    max_ts: datetime,
    end: datetime,
    page_size: int,
    batch_size: int,
) -> bool:
    if max_ts > end:
        return True
    return page_size < batch_size


def _update_trade_pagination_state(
    state: _TradePaginationState,
    *,
    max_ts: datetime,
    new_rows: int,
) -> None:
    cursor = state.cursor
    if cursor is not None and max_ts < cursor:
        raise RuntimeError(
            "Trade pagination regressed cursor timestamp; aborting to avoid silent data loss."
        )
    if cursor is not None and max_ts == cursor and new_rows == 0:
        state.stalled_iterations += 1
        if state.stalled_iterations >= 2:
            raise RuntimeError(
                "Trade pagination stalled at a single timestamp; venue pagination is ambiguous."
            )
    else:
        state.stalled_iterations = 0
    state.cursor = max_ts


def _filter_quality_trades(
    checker: event_quality.EventQualityChecker,
    trades: list[event_models.CanonicalTrade],
) -> tuple[list[event_models.CanonicalTrade], int]:
    """Return (valid_trades, rejected_count)."""
    valid: list[event_models.CanonicalTrade] = []
    rejected = 0
    for trade in trades:
        if checker.check(trade).is_valid:
            valid.append(trade)
        else:
            rejected += 1
    return valid, rejected


def _filter_quality_candles(
    checker: event_quality.EventQualityChecker,
    candles: list[event_models.CanonicalOHLCV],
) -> tuple[list[event_models.CanonicalOHLCV], int]:
    """Return (valid_candles, rejected_count)."""
    valid: list[event_models.CanonicalOHLCV] = []
    rejected = 0
    for candle in candles:
        if checker.check(candle).is_valid:
            valid.append(candle)
        else:
            rejected += 1
    return valid, rejected


def _filter_ohlcv_window_with_raw(
    candles: list[event_models.CanonicalOHLCV],
    raw_payloads: list[dict[str, object]],
    *,
    start: datetime,
    end: datetime,
) -> tuple[list[event_models.CanonicalOHLCV], list[dict[str, object]]]:
    """Filter candles to [start, end] and preserve raw-payload alignment when available."""
    in_window_candles: list[event_models.CanonicalOHLCV] = []
    in_window_raw_payloads: list[dict[str, object]] = []

    if len(raw_payloads) == len(candles):
        for candle, raw_payload in zip(candles, raw_payloads, strict=True):
            if not (start <= candle.ts_event <= end):
                continue
            in_window_candles.append(candle)
            in_window_raw_payloads.append(raw_payload)
        return in_window_candles, in_window_raw_payloads

    for candle in candles:
        if start <= candle.ts_event <= end:
            in_window_candles.append(candle)
    return in_window_candles, in_window_raw_payloads


def _validate_window(start: datetime, end: datetime) -> None:
    if end <= start:
        raise ValueError(f"`end` must be after `start`: start={start}, end={end}")


__all__ = ["BackfillManager", "BackfillResult"]
