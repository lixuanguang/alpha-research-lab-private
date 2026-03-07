"""Historical data backfill orchestration."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from functools import partial

from pydantic import BaseModel, ConfigDict

import alpha_core.adapters.base as adapters_base
import alpha_core.events.quality as event_quality
import alpha_core.quality.gap_detector as quality_gap_detector
import alpha_core.storage.bronze_writer as storage_bronze
import alpha_core.storage.lineage as storage_lineage
import alpha_core.storage.parquet_writer as storage_parquet
import alpha_core.utils.time as time_utils
import apps.data_collector.backfill_support as backfill_support
import apps.data_collector.connectors.raw_payloads as connector_raw_payloads


@dataclass(slots=True)
class BackfillDependencies:
    """Storage and validation dependencies required by BackfillManager."""

    bronze_writer: storage_bronze.BronzeWriter
    silver_writer: storage_parquet.ParquetEventWriter
    quality_checker: event_quality.EventQualityChecker
    lineage_store: storage_lineage.LineageStore


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
        dependencies: BackfillDependencies,
        *,
        retry_policy: backfill_support.FetchRetryPolicy | None = None,
    ) -> None:
        self._venue = adapter.venue_name()
        self._adapter = adapter
        self._bronze_writer = dependencies.bronze_writer
        self._silver_writer = dependencies.silver_writer
        self._quality_checker = dependencies.quality_checker
        self._lineage_store = dependencies.lineage_store
        self._retry_policy = retry_policy or backfill_support.FetchRetryPolicy()

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
        backfill_support.validate_window(start_utc, end_utc)
        window = backfill_support.TimeWindow(start=start_utc, end=end_utc)
        return await self._run_outcome_backfill(
            event_type="trades",
            outcome_ids=outcome_ids,
            window=window,
            config_snapshot={
                "window_start": start_utc.isoformat(),
                "window_end": end_utc.isoformat(),
                "batch_size": batch_size,
            },
            process_outcome=partial(
                self._backfill_trades_for_outcome,
                window=window,
                batch_size=batch_size,
            ),
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

        start_utc = time_utils.ensure_utc(start)
        end_utc = time_utils.ensure_utc(end)
        backfill_support.validate_window(start_utc, end_utc)
        limit = backfill_support.compute_ohlcv_limit(
            resolution=resolution,
            start=start_utc,
            end=end_utc,
        )
        window = backfill_support.TimeWindow(start=start_utc, end=end_utc)
        return await self._run_outcome_backfill(
            event_type="ohlcv",
            outcome_ids=outcome_ids,
            window=window,
            config_snapshot={
                "window_start": start_utc.isoformat(),
                "window_end": end_utc.isoformat(),
                "resolution": resolution,
            },
            process_outcome=partial(
                self._backfill_ohlcv_for_outcome,
                window=window,
                resolution=resolution,
                limit=limit,
            ),
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

    async def _run_outcome_backfill(
        self,
        *,
        event_type: str,
        outcome_ids: list[str],
        window: backfill_support.TimeWindow,
        config_snapshot: dict[str, object],
        process_outcome: Callable[[str, str], Awaitable[backfill_support.OutcomeBackfillTotals]],
    ) -> BackfillResult:
        run = self._lineage_store.start_run(
            venue=self._venue,
            connector_type="polling",
            options=storage_lineage.StartRunOptions(
                event_types=[event_type],
                config_snapshot=config_snapshot,
            ),
        )
        monotonic_start = time.monotonic()
        errors: list[str] = []
        totals = backfill_support.BackfillAccumulator()

        try:
            for outcome_id in outcome_ids:
                try:
                    outcome_totals = await process_outcome(outcome_id, run.run_id)
                except Exception as exc:
                    errors.append(f"outcome={outcome_id}: {exc}")
                    continue
                totals.add(outcome_totals)

            self._lineage_store.complete_run(run.run_id, counts=totals.as_counts(), errors=errors)
        except Exception as exc:
            self._lineage_store.fail_run(run.run_id, str(exc))
            raise

        return BackfillResult(
            venue=self._venue,
            event_type=event_type,
            outcome_ids=list(outcome_ids),
            window_start=window.start,
            window_end=window.end,
            events_fetched=totals.fetched,
            events_stored=totals.stored,
            events_rejected=totals.rejected,
            duration_seconds=time.monotonic() - monotonic_start,
            run_id=run.run_id,
        )

    async def _backfill_trades_for_outcome(
        self,
        outcome_id: str,
        run_id: str,
        *,
        window: backfill_support.TimeWindow,
        batch_size: int,
    ) -> backfill_support.OutcomeBackfillTotals:
        trades, raw_payloads = await backfill_support.fetch_trades_windowed(
            self._adapter,
            outcome_id,
            window=window,
            batch_size=batch_size,
            retry_policy=self._retry_policy,
        )
        trades.sort(key=lambda trade: (trade.instrument_id, trade.ts_event, trade.trade_id))
        valid_trades, rejected = backfill_support.filter_quality_events(
            self._quality_checker,
            trades,
        )

        if raw_payloads:
            self._bronze_writer.write_raw_events(
                raw_payloads,
                venue=self._venue,
                event_type="trades",
                run_id=run_id,
            )
        if valid_trades:
            self._silver_writer.write_trades(valid_trades)

        return backfill_support.OutcomeBackfillTotals(
            fetched=len(trades),
            stored=len(valid_trades),
            rejected=rejected,
        )

    async def _backfill_ohlcv_for_outcome(
        self,
        outcome_id: str,
        run_id: str,
        *,
        window: backfill_support.TimeWindow,
        resolution: str,
        limit: int,
    ) -> backfill_support.OutcomeBackfillTotals:
        candles, raw_payloads = await backfill_support.call_with_retries(
            partial(
                self._adapter.fetch_ohlcv_with_raw,
                outcome_id,
                resolution=resolution,
                limit=limit,
            ),
            context=f"fetch_ohlcv_with_raw[{outcome_id}]",
            retry_policy=self._retry_policy,
        )
        normalized_raw = connector_raw_payloads.normalize_raw_payloads(
            raw_payloads,
            outcome_id=outcome_id,
        )
        in_window_candles, in_window_raw = backfill_support.filter_ohlcv_window_with_raw(
            candles,
            normalized_raw,
            start=window.start,
            end=window.end,
        )
        in_window_candles.sort(
            key=lambda candle: (candle.instrument_id, candle.ts_event, candle.resolution)
        )
        valid_candles, rejected = backfill_support.filter_quality_events(
            self._quality_checker,
            in_window_candles,
        )

        if in_window_raw:
            self._bronze_writer.write_raw_events(
                in_window_raw,
                venue=self._venue,
                event_type="ohlcv",
                run_id=run_id,
            )
        if valid_candles:
            self._silver_writer.write_ohlcv(valid_candles)

        return backfill_support.OutcomeBackfillTotals(
            fetched=len(in_window_candles),
            stored=len(valid_candles),
            rejected=rejected,
        )


__all__ = ["BackfillDependencies", "BackfillManager", "BackfillResult"]
