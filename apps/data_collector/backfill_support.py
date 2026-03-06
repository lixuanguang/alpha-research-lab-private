"""Support logic for historical data backfill orchestration."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TypeVar

import alpha_core.adapters.base as adapters_base
import alpha_core.events.models as event_models
import alpha_core.events.quality as event_quality
import apps.data_collector.connectors.raw_payloads as connector_raw_payloads

_MAX_OHLCV_LIMIT = 10_000
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
class TradePaginationState:
    """Mutable pagination state for one outcome trade backfill."""

    cursor: datetime | None
    stalled_iterations: int = 0
    seen_trade_keys: set[tuple[str, str]] = field(default_factory=set)


@dataclass(slots=True, frozen=True)
class FetchRetryPolicy:
    """Retry/backoff policy for adapter fetch calls."""

    max_attempts: int = _FETCH_RETRY_ATTEMPTS
    backoff_base_seconds: float = _FETCH_RETRY_BACKOFF_BASE_SECONDS
    backoff_max_seconds: float = _FETCH_RETRY_BACKOFF_MAX_SECONDS

    def __post_init__(self) -> None:
        if self.max_attempts <= 0:
            raise ValueError("`max_attempts` must be > 0")
        if self.backoff_base_seconds <= 0:
            raise ValueError("`backoff_base_seconds` must be > 0")
        if self.backoff_max_seconds < self.backoff_base_seconds:
            raise ValueError("`backoff_max_seconds` must be >= `backoff_base_seconds`")


@dataclass(slots=True, frozen=True)
class TimeWindow:
    start: datetime
    end: datetime


@dataclass(slots=True)
class TradeBackfillSink:
    trades: list[event_models.CanonicalTrade] = field(default_factory=list)
    raw_payloads: list[dict[str, object]] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class OutcomeBackfillTotals:
    fetched: int
    stored: int
    rejected: int


@dataclass(slots=True)
class BackfillAccumulator:
    fetched: int = 0
    stored: int = 0
    rejected: int = 0

    def add(self, totals: OutcomeBackfillTotals) -> None:
        self.fetched += totals.fetched
        self.stored += totals.stored
        self.rejected += totals.rejected

    def as_counts(self) -> dict[str, int]:
        return {
            "events_raw": self.fetched,
            "events_silver": self.stored,
            "rejected": self.rejected,
        }


def compute_ohlcv_limit(*, resolution: str, start: datetime, end: datetime) -> int:
    if resolution not in _RESOLUTION_SECONDS:
        raise ValueError(
            f"Unknown resolution '{resolution}'. Expected one of {list(_RESOLUTION_SECONDS)}"
        )

    candle_seconds = _RESOLUTION_SECONDS[resolution]
    window_seconds = (end - start).total_seconds()
    return min(math.ceil(window_seconds / candle_seconds) + 5, _MAX_OHLCV_LIMIT)


async def fetch_trades_windowed(
    adapter: adapters_base.VenueAdapter,
    outcome_id: str,
    *,
    window: TimeWindow,
    batch_size: int,
    retry_policy: FetchRetryPolicy,
) -> tuple[list[event_models.CanonicalTrade], list[dict[str, object]]]:
    """Paginate fetch_trades_with_raw to collect all trades in [start, end]."""
    sink = TradeBackfillSink()
    state = TradePaginationState(cursor=window.start)

    while True:
        trades, normalized_raw = await _fetch_trade_page(
            adapter,
            outcome_id=outcome_id,
            cursor=state.cursor,
            batch_size=batch_size,
            retry_policy=retry_policy,
        )
        if not trades:
            break

        new_rows = _append_windowed_unique_trades(
            trades=trades,
            normalized_raw=normalized_raw,
            window=window,
            state=state,
            sink=sink,
        )
        max_ts = max(trade.ts_event for trade in trades)
        if _should_stop_trade_pagination(
            max_ts=max_ts,
            end=window.end,
            page_size=len(trades),
            batch_size=batch_size,
        ):
            break
        _update_trade_pagination_state(state, max_ts=max_ts, new_rows=new_rows)

    return sink.trades, sink.raw_payloads


async def call_with_retries(
    fn: Callable[[], Awaitable[_ResultT]],
    *,
    context: str,
    retry_policy: FetchRetryPolicy,
) -> _ResultT:
    last_error: Exception | None = None
    for attempt in range(retry_policy.max_attempts):
        try:
            return await fn()
        except Exception as exc:
            last_error = exc
            if attempt + 1 >= retry_policy.max_attempts:
                break
            delay_seconds = min(
                retry_policy.backoff_max_seconds,
                retry_policy.backoff_base_seconds * (2**attempt),
            )
            await asyncio.sleep(delay_seconds)
    raise RuntimeError(
        f"{context} failed after {retry_policy.max_attempts} attempt(s): {last_error}"
    ) from last_error


def filter_quality_trades(
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


def filter_quality_candles(
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


def filter_ohlcv_window_with_raw(
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

    in_window_candles.extend(candle for candle in candles if start <= candle.ts_event <= end)
    return in_window_candles, in_window_raw_payloads


def validate_window(start: datetime, end: datetime) -> None:
    if end <= start:
        raise ValueError(f"`end` must be after `start`: start={start}, end={end}")


async def _fetch_trade_page(
    adapter: adapters_base.VenueAdapter,
    *,
    outcome_id: str,
    cursor: datetime | None,
    batch_size: int,
    retry_policy: FetchRetryPolicy,
) -> tuple[list[event_models.CanonicalTrade], list[dict[str, object]]]:
    raw_result: list[object]
    trades, raw_result = await call_with_retries(
        lambda: adapter.fetch_trades_with_raw(
            outcome_id,
            since=cursor,
            limit=batch_size,
        ),
        context=f"fetch_trades_with_raw[{outcome_id}]",
        retry_policy=retry_policy,
    )
    normalized_raw = connector_raw_payloads.normalize_raw_payloads(
        raw_result,
        outcome_id=outcome_id,
    )
    return trades, normalized_raw


def _append_windowed_unique_trades(
    *,
    trades: list[event_models.CanonicalTrade],
    normalized_raw: list[dict[str, object]],
    window: TimeWindow,
    state: TradePaginationState,
    sink: TradeBackfillSink,
) -> int:
    new_rows = 0
    for trade, raw_payload in _pair_trades_with_raw_payloads(trades, normalized_raw):
        if not (window.start <= trade.ts_event <= window.end):
            continue
        trade_key = (trade.instrument_id, trade.trade_id)
        if trade_key in state.seen_trade_keys:
            continue

        state.seen_trade_keys.add(trade_key)
        sink.trades.append(trade)
        if raw_payload is not None:
            sink.raw_payloads.append(raw_payload)
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
    state: TradePaginationState,
    *,
    max_ts: datetime,
    new_rows: int,
) -> None:
    if state.cursor is not None and max_ts < state.cursor:
        raise RuntimeError(
            "Trade pagination regressed cursor timestamp; aborting to avoid silent data loss."
        )
    if state.cursor is not None and max_ts == state.cursor and new_rows == 0:
        state.stalled_iterations += 1
        if state.stalled_iterations >= 2:
            raise RuntimeError(
                "Trade pagination stalled at a single timestamp; venue pagination is ambiguous."
            )
    else:
        state.stalled_iterations = 0
    state.cursor = max_ts
