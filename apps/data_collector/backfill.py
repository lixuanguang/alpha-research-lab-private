"""Historical data backfill orchestration."""

from __future__ import annotations

import math
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

import alpha_core.adapters.base as adapters_base
import alpha_core.events.models as event_models
import alpha_core.events.quality as event_quality
import alpha_core.storage.bronze_writer as storage_bronze
import alpha_core.storage.lineage as storage_lineage
import alpha_core.storage.parquet_writer as storage_parquet
import alpha_core.utils.time as time_utils
import apps.data_collector.connectors.raw_payloads as connector_raw_payloads

if TYPE_CHECKING:
    from alpha_core.quality.gap_detector import TimeGap

# Maximum candles fetched per OHLCV backfill call (capped to avoid unreasonably large requests)
_MAX_OHLCV_LIMIT = 10_000

# Resolution label → seconds per candle
_RESOLUTION_SECONDS: dict[str, float] = {
    "1m": 60.0,
    "5m": 300.0,
    "1h": 3600.0,
    "1d": 86400.0,
}


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
    ) -> None:
        self._venue = adapter.venue_name()
        self._adapter = adapter
        self._bronze_writer = bronze_writer
        self._silver_writer = silver_writer
        self._quality_checker = quality_checker
        self._lineage_store = lineage_store

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
        all_trades: list[event_models.CanonicalTrade] = []
        all_raw: list[dict[str, object]] = []
        errors: list[str] = []

        try:
            for outcome_id in outcome_ids:
                try:
                    trades, raw = await _fetch_trades_windowed(
                        self._adapter,
                        outcome_id,
                        start=start_utc,
                        end=end_utc,
                        batch_size=batch_size,
                    )
                    all_trades.extend(trades)
                    all_raw.extend(raw)
                except Exception as exc:
                    errors.append(f"outcome={outcome_id}: {exc}")

            valid_trades, rejected = _filter_quality_trades(self._quality_checker, all_trades)

            if all_raw:
                self._bronze_writer.write_raw_events(
                    all_raw, venue=self._venue, event_type="trades", run_id=run.run_id
                )
            if valid_trades:
                self._silver_writer.write_trades(valid_trades)

            self._lineage_store.complete_run(
                run.run_id,
                counts={
                    "events_raw": len(all_trades),
                    "events_silver": len(valid_trades),
                    "rejected": rejected,
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
            events_fetched=len(all_trades),
            events_stored=len(valid_trades),
            events_rejected=rejected,
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
        all_candles: list[event_models.CanonicalOHLCV] = []
        all_raw: list[dict[str, object]] = []
        errors: list[str] = []

        try:
            for outcome_id in outcome_ids:
                try:
                    candles, raw = await self._adapter.fetch_ohlcv_with_raw(
                        outcome_id, resolution=resolution, limit=limit
                    )
                    normalized_raw = connector_raw_payloads.normalize_raw_payloads(
                        raw, outcome_id=outcome_id
                    )
                    in_window = [c for c in candles if start_utc <= c.ts_event <= end_utc]
                    all_candles.extend(in_window)
                    # Include proportional raw payloads
                    all_raw.extend(normalized_raw[: len(in_window)])
                except Exception as exc:
                    errors.append(f"outcome={outcome_id}: {exc}")

            valid_candles, rejected = _filter_quality_candles(self._quality_checker, all_candles)

            if all_raw:
                self._bronze_writer.write_raw_events(
                    all_raw, venue=self._venue, event_type="ohlcv", run_id=run.run_id
                )
            if valid_candles:
                self._silver_writer.write_ohlcv(valid_candles)

            self._lineage_store.complete_run(
                run.run_id,
                counts={
                    "events_raw": len(all_candles),
                    "events_silver": len(valid_candles),
                    "rejected": rejected,
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
            events_fetched=len(all_candles),
            events_stored=len(valid_candles),
            events_rejected=rejected,
            duration_seconds=time.monotonic() - monotonic_start,
            run_id=run.run_id,
        )

    async def fill_gaps(self, gaps: list[TimeGap]) -> list[BackfillResult]:
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
) -> tuple[list[event_models.CanonicalTrade], list[dict[str, object]]]:
    """Paginate fetch_trades_with_raw to collect all trades in [start, end]."""
    all_trades: list[event_models.CanonicalTrade] = []
    all_raw: list[dict[str, object]] = []
    cursor: datetime | None = start

    while True:
        raw_result: list[object]
        trades, raw_result = await adapter.fetch_trades_with_raw(
            outcome_id, since=cursor, limit=batch_size
        )
        if not trades:
            break

        normalized_raw = connector_raw_payloads.normalize_raw_payloads(
            raw_result, outcome_id=outcome_id
        )

        in_window = [t for t in trades if start <= t.ts_event <= end]
        if not in_window:
            # All fetched trades are outside window (already past end)
            break

        all_trades.extend(in_window)
        all_raw.extend(normalized_raw[: len(in_window)])

        # Advance cursor past last seen ts_event
        max_ts = max(t.ts_event for t in trades)
        cursor = max_ts + timedelta(microseconds=1)

        # Stop when we've passed the end of the window or batch was partial
        if max_ts >= end or len(trades) < batch_size:
            break

    return all_trades, all_raw


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


def _validate_window(start: datetime, end: datetime) -> None:
    if end <= start:
        raise ValueError(f"`end` must be after `start`: start={start}, end={end}")


__all__ = ["BackfillManager", "BackfillResult"]
