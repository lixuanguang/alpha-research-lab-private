"""Runtime orchestration for data-collector polling pipelines."""

from __future__ import annotations

import asyncio
import dataclasses
import functools
import time
from collections.abc import Callable
from typing import Protocol

import alpha_core.adapters.base as adapters_base
import alpha_core.config.models as config_models
import alpha_core.events.models as event_models
import alpha_core.events.quality as event_quality
import alpha_core.instruments.master as instrument_master
import alpha_core.instruments.models as instrument_models
import alpha_core.storage.bronze_writer as storage_bronze
import alpha_core.storage.lineage as storage_lineage
import alpha_core.storage.parquet_writer as storage_parquet
import apps.data_collector.connectors._polling as connector_polling
import apps.data_collector.connectors.book_poller as connector_book_poller
import apps.data_collector.connectors.market_refresh as connector_market_refresh
import apps.data_collector.connectors.ohlcv_poller as connector_ohlcv_poller
import apps.data_collector.connectors.rate_limiter as connector_rate_limiter
import apps.data_collector.connectors.scheduler as connector_scheduler
import apps.data_collector.connectors.trade_poller as connector_trade_poller
import apps.data_collector.pipeline as collector_pipeline

EmitMessage = Callable[[str, bool], None]


class AdapterFactory(Protocol):
    """Factory for venue adapter instances."""

    def __call__(
        self,
        exchange_name: str,
        config: config_models.VenueConfig,
    ) -> adapters_base.VenueAdapter:
        """Return a configured adapter instance for one venue."""


@dataclasses.dataclass(slots=True)
class PipelineContext:
    """Runtime state for one polling pipeline execution loop."""

    pipeline: collector_pipeline.PollingPipeline
    rate_limiter: connector_rate_limiter.TokenBucketRateLimiter


async def execute_pipeline_connector(
    context_by_connector_id: dict[str, PipelineContext],
    connector: connector_polling.PollingConnector,
) -> list[event_models.CanonicalMarketEvent]:
    """Execute one pipeline for scheduler callback wiring."""
    context = context_by_connector_id[connector.connector_id]
    run = await context.pipeline.execute()
    if run.status != "completed":
        error_text = run.errors[-1] if run.errors else "unknown error"
        raise RuntimeError(error_text)
    return []


def emit_pipeline_error(
    emit: EmitMessage,
    connector: connector_polling.PollingConnector,
    error: BaseException,
) -> None:
    """Emit scheduler execution errors with connector context."""
    emit(f"Pipeline failed ({connector.connector_id}): {error}", True)


async def run_polling_pipelines(
    settings: config_models.Settings,
    *,
    once: bool,
    max_outcomes_per_venue: int,
    request_timeout_seconds: float = 10.0,
    adapter_factory: AdapterFactory,
    emit: EmitMessage,
) -> int:
    """Build and execute polling pipelines once or continuously."""
    if max_outcomes_per_venue <= 0:
        raise ValueError("`max_outcomes_per_venue` must be > 0.")
    if request_timeout_seconds <= 0:
        raise ValueError("`request_timeout_seconds` must be > 0.")
    contexts = await build_pipeline_contexts(
        settings,
        max_outcomes_per_venue=max_outcomes_per_venue,
        request_timeout_seconds=request_timeout_seconds,
        adapter_factory=adapter_factory,
        emit=emit,
    )
    if not contexts:
        raise ValueError("No polling pipelines were created from enabled venue settings.")

    scheduler = build_polling_scheduler(contexts, emit=emit)
    if once:
        return len(await scheduler.run_once())

    while True:
        await scheduler.run_due_once()
        await asyncio.sleep(scheduler.seconds_until_next_due(time.monotonic()))


async def build_pipeline_contexts(
    settings: config_models.Settings,
    *,
    max_outcomes_per_venue: int,
    request_timeout_seconds: float = 10.0,
    adapter_factory: AdapterFactory,
    emit: EmitMessage,
) -> list[PipelineContext]:
    """Create polling pipelines for all enabled venues."""
    storage_root = settings.storage.base_path
    bronze_writer = storage_bronze.BronzeWriter(storage_root)
    silver_writer = storage_parquet.ParquetEventWriter(storage_root)
    lineage_store = storage_lineage.LineageStore(storage_root)
    market_master = instrument_master.MarketMaster()

    contexts: list[PipelineContext] = []
    for venue in settings.venues:
        if not venue.enabled:
            continue

        try:
            adapter = adapter_factory(venue.name, venue)
            markets, _ = await asyncio.wait_for(
                adapter.fetch_markets_with_raw(),
                timeout=request_timeout_seconds,
            )
        except Exception as exc:
            emit(f"Skipping venue `{venue.name}` due to setup failure: {exc}", True)
            continue

        outcome_ids = collect_outcome_ids(markets, max_outcomes_per_venue=max_outcomes_per_venue)
        rate_limiter = connector_rate_limiter.TokenBucketRateLimiter(rpm=venue.rate_limit_rpm)

        connectors: list[connector_polling.PollingConnector] = [
            connector_market_refresh.MarketRefreshPoller(
                adapter,
                market_master,
                request_timeout_seconds=request_timeout_seconds,
            )
        ]
        if outcome_ids:
            connectors.extend(
                [
                    connector_trade_poller.TradePoller(
                        adapter,
                        outcome_ids=outcome_ids,
                        request_timeout_seconds=request_timeout_seconds,
                    ),
                    connector_book_poller.BookSnapshotPoller(
                        adapter,
                        outcome_ids=outcome_ids,
                        request_timeout_seconds=request_timeout_seconds,
                    ),
                    connector_ohlcv_poller.OHLCVPoller(
                        adapter,
                        outcome_ids=outcome_ids,
                        request_timeout_seconds=request_timeout_seconds,
                    ),
                ]
            )

        for connector in connectors:
            pipeline = collector_pipeline.PollingPipeline(
                connector=connector,
                bronze_writer=bronze_writer,
                silver_writer=silver_writer,
                quality_checker=event_quality.EventQualityChecker(),
                lineage_store=lineage_store,
            )
            contexts.append(
                PipelineContext(
                    pipeline=pipeline,
                    rate_limiter=rate_limiter,
                )
            )

    return contexts


def build_polling_scheduler(
    contexts: list[PipelineContext],
    *,
    emit: EmitMessage,
) -> connector_scheduler.PollingScheduler:
    """Create a scheduler that executes full polling pipelines per connector."""
    context_by_connector_id = {
        context.pipeline.connector.connector_id: context for context in contexts
    }
    connectors = [context.pipeline.connector for context in contexts]
    rate_limiters: dict[str, connector_rate_limiter.TokenBucketRateLimiter] = {
        context.pipeline.connector.venue: context.rate_limiter for context in contexts
    }

    return connector_scheduler.PollingScheduler(
        connectors=connectors,
        rate_limiters=rate_limiters,
        execute_connector=functools.partial(
            execute_pipeline_connector,
            context_by_connector_id,
        ),
        on_error=functools.partial(emit_pipeline_error, emit),
    )


def collect_outcome_ids(
    markets: list[instrument_models.MarketSpec],
    *,
    max_outcomes_per_venue: int,
) -> list[str]:
    """Collect unique outcome ids up to a configured maximum."""
    if max_outcomes_per_venue <= 0:
        raise ValueError("`max_outcomes_per_venue` must be > 0.")
    seen: set[str] = set()
    outcome_ids: list[str] = []
    for market in markets:
        for outcome in market.outcomes:
            if outcome.canonical_id in seen:
                continue
            seen.add(outcome.canonical_id)
            outcome_ids.append(outcome.canonical_id)
            if len(outcome_ids) >= max_outcomes_per_venue:
                return outcome_ids
    return outcome_ids


__all__ = [
    "PipelineContext",
    "build_pipeline_contexts",
    "build_polling_scheduler",
    "collect_outcome_ids",
    "emit_pipeline_error",
    "execute_pipeline_connector",
    "run_polling_pipelines",
]
