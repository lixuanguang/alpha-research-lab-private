"""Runtime orchestration for data-collector pipelines."""

from __future__ import annotations

import asyncio
import dataclasses
import functools
import time
from collections.abc import Callable
from typing import Literal, Protocol

import alpha_core.adapters.base as adapters_base
import alpha_core.config.models as config_models
import alpha_core.events.models as event_models
import alpha_core.events.quality as event_quality
import alpha_core.instruments.models as instrument_models
import alpha_core.storage.bronze_writer as storage_bronze
import alpha_core.storage.lineage as storage_lineage
import alpha_core.storage.parquet_writer as storage_parquet
import alpha_core.storage.streaming_writer as storage_streaming
import apps.data_collector.connectors._polling as connector_polling
import apps.data_collector.connectors.factory as connector_factory
import apps.data_collector.connectors.rate_limiter as connector_rate_limiter
import apps.data_collector.connectors.scheduler as connector_scheduler
import apps.data_collector.pipeline as collector_pipeline
import apps.data_collector.streaming_pipeline as collector_streaming_pipeline

EmitMessage = Callable[[str, bool], None]
CollectionMode = Literal["poll", "stream", "both"]


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


@dataclasses.dataclass(slots=True)
class StreamingPipelineContext:
    """Runtime state for one streaming pipeline."""

    pipeline: collector_streaming_pipeline.StreamingPipeline


@dataclasses.dataclass(slots=True)
class VenueRuntimeSeed:
    """Prepared per-venue runtime setup shared by polling and streaming builders."""

    venue_config: config_models.VenueConfig
    adapter: adapters_base.VenueAdapter
    markets: list[instrument_models.MarketSpec]


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


async def run_polling_pipelines(
    settings: config_models.Settings,
    *,
    once: bool,
    max_outcomes_per_venue: int,
    request_timeout_seconds: float = 10.0,
    adapter_factory: AdapterFactory,
    emit: EmitMessage,
    venue_names: set[str] | None = None,
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
        venue_names=venue_names,
    )
    if not contexts:
        raise ValueError("No polling pipelines were created from enabled venue settings.")

    scheduler = build_polling_scheduler(contexts, emit=emit)
    if once:
        return len(await scheduler.run_once())

    while True:
        await scheduler.run_due_once()
        await asyncio.sleep(scheduler.seconds_until_next_due(time.monotonic()))


async def run_streaming_pipelines(
    settings: config_models.Settings,
    *,
    once: bool,
    max_outcomes_per_venue: int,
    request_timeout_seconds: float = 10.0,
    adapter_factory: AdapterFactory,
    emit: EmitMessage,
    venue_names: set[str] | None = None,
) -> int:
    """Build and execute streaming pipelines once or continuously."""
    if max_outcomes_per_venue <= 0:
        raise ValueError("`max_outcomes_per_venue` must be > 0.")
    if request_timeout_seconds <= 0:
        raise ValueError("`request_timeout_seconds` must be > 0.")

    contexts = await build_streaming_pipeline_contexts(
        settings,
        max_outcomes_per_venue=max_outcomes_per_venue,
        request_timeout_seconds=request_timeout_seconds,
        adapter_factory=adapter_factory,
        emit=emit,
        venue_names=venue_names,
        stop_after_events=1 if once else None,
    )
    if not contexts:
        raise ValueError("No streaming pipelines were created from enabled venue settings.")

    tasks = [
        asyncio.create_task(
            context.pipeline.run(),
            name=f"stream:{context.pipeline.connector_id}",
        )
        for context in contexts
    ]
    if once:
        timeout_seconds = max(5.0, request_timeout_seconds * 3.0)
        try:
            settled = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=timeout_seconds,
            )
        except TimeoutError as exc:
            await _stop_streaming_pipelines(contexts)
            raise ValueError("Streaming once-mode timed out waiting for first event.") from exc
        return _count_streaming_results(settled, emit)

    settled = await asyncio.gather(*tasks, return_exceptions=True)
    return _count_streaming_results(settled, emit)


async def run_polling_and_streaming(
    settings: config_models.Settings,
    *,
    once: bool,
    max_outcomes_per_venue: int,
    request_timeout_seconds: float = 10.0,
    adapter_factory: AdapterFactory,
    emit: EmitMessage,
    venue_names: set[str] | None = None,
) -> int:
    """Run polling and streaming pipelines for `mode=both`."""
    if once:
        polling_runs, streaming_runs = await asyncio.gather(
            run_polling_pipelines(
                settings,
                once=True,
                max_outcomes_per_venue=max_outcomes_per_venue,
                request_timeout_seconds=request_timeout_seconds,
                adapter_factory=adapter_factory,
                emit=emit,
                venue_names=venue_names,
            ),
            run_streaming_pipelines(
                settings,
                once=True,
                max_outcomes_per_venue=max_outcomes_per_venue,
                request_timeout_seconds=request_timeout_seconds,
                adapter_factory=adapter_factory,
                emit=emit,
                venue_names=venue_names,
            ),
        )
        return polling_runs + streaming_runs

    await asyncio.gather(
        run_polling_pipelines(
            settings,
            once=False,
            max_outcomes_per_venue=max_outcomes_per_venue,
            request_timeout_seconds=request_timeout_seconds,
            adapter_factory=adapter_factory,
            emit=emit,
            venue_names=venue_names,
        ),
        run_streaming_pipelines(
            settings,
            once=False,
            max_outcomes_per_venue=max_outcomes_per_venue,
            request_timeout_seconds=request_timeout_seconds,
            adapter_factory=adapter_factory,
            emit=emit,
            venue_names=venue_names,
        ),
    )
    return 0


async def build_pipeline_contexts(
    settings: config_models.Settings,
    *,
    max_outcomes_per_venue: int,
    request_timeout_seconds: float = 10.0,
    adapter_factory: AdapterFactory,
    emit: EmitMessage,
    venue_names: set[str] | None = None,
) -> list[PipelineContext]:
    """Create polling pipelines for all enabled venues."""
    storage_root = settings.storage.base_path
    bronze_writer = storage_bronze.BronzeWriter(storage_root)
    silver_writer = storage_parquet.ParquetEventWriter(storage_root)
    lineage_store = storage_lineage.LineageStore(storage_root)
    factory = connector_factory.VenueConnectorFactory(settings)
    seeds = await _build_venue_runtime_seeds(
        settings,
        adapter_factory=adapter_factory,
        request_timeout_seconds=request_timeout_seconds,
        emit=emit,
        venue_names=venue_names,
    )

    contexts: list[PipelineContext] = []
    for seed in seeds:
        outcome_ids = collect_outcome_ids(
            seed.markets,
            max_outcomes_per_venue=max_outcomes_per_venue,
        )
        rate_limiter = connector_rate_limiter.TokenBucketRateLimiter(
            rpm=seed.venue_config.rate_limit_rpm
        )
        connectors = factory.create_poll_connectors(
            seed.adapter,
            outcome_ids,
            request_timeout_seconds=request_timeout_seconds,
        )
        if not connectors:
            emit(
                f"Skipping venue `{seed.venue_config.name}`; no polling connectors configured.",
                True,
            )
            continue

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


async def build_streaming_pipeline_contexts(
    settings: config_models.Settings,
    *,
    max_outcomes_per_venue: int,
    request_timeout_seconds: float = 10.0,
    adapter_factory: AdapterFactory,
    emit: EmitMessage,
    venue_names: set[str] | None = None,
    stop_after_events: int | None = None,
) -> list[StreamingPipelineContext]:
    """Create streaming pipelines for all enabled venues."""
    if stop_after_events is not None and stop_after_events <= 0:
        raise ValueError("`stop_after_events` must be > 0 when configured")

    storage_root = settings.storage.base_path
    bronze_writer = storage_bronze.BronzeWriter(storage_root)
    lineage_store = storage_lineage.LineageStore(storage_root)
    factory = connector_factory.VenueConnectorFactory(settings)
    seeds = await _build_venue_runtime_seeds(
        settings,
        adapter_factory=adapter_factory,
        request_timeout_seconds=request_timeout_seconds,
        emit=emit,
        venue_names=venue_names,
    )

    contexts: list[StreamingPipelineContext] = []
    for seed in seeds:
        stream_outcome_cap = min(
            max_outcomes_per_venue,
            seed.venue_config.collection.stream_outcomes_max,
        )
        outcome_ids = collect_outcome_ids(seed.markets, max_outcomes_per_venue=stream_outcome_cap)
        connectors = factory.create_stream_connectors(seed.adapter, outcome_ids)
        if not connectors:
            emit(
                f"Skipping venue `{seed.venue_config.name}`; no streaming connectors configured.",
                True,
            )
            continue

        for connector in connectors:
            pipeline = collector_streaming_pipeline.StreamingPipeline(
                connector=connector,
                bronze_writer=bronze_writer,
                streaming_writer=storage_streaming.StreamingParquetWriter(
                    storage_parquet.ParquetEventWriter(storage_root)
                ),
                quality_checker=event_quality.EventQualityChecker(),
                lineage_store=lineage_store,
                max_events=stop_after_events,
            )
            contexts.append(StreamingPipelineContext(pipeline=pipeline))

    return contexts


async def _build_venue_runtime_seeds(
    settings: config_models.Settings,
    *,
    adapter_factory: AdapterFactory,
    request_timeout_seconds: float,
    emit: EmitMessage,
    venue_names: set[str] | None,
) -> list[VenueRuntimeSeed]:
    seeds: list[VenueRuntimeSeed] = []
    for venue in settings.venues:
        if not venue.enabled:
            continue
        if venue_names is not None and venue.name not in venue_names:
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
        seeds.append(
            VenueRuntimeSeed(
                venue_config=venue,
                adapter=adapter,
                markets=markets,
            )
        )
    return seeds


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
        on_error=lambda connector, error: emit(
            f"Pipeline failed ({connector.connector_id}): {error}",
            True,
        ),
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


async def _stop_streaming_pipelines(contexts: list[StreamingPipelineContext]) -> None:
    if not contexts:
        return
    await asyncio.gather(
        *(context.pipeline.stop() for context in contexts),
        return_exceptions=True,
    )


def _count_streaming_results(
    settled: list[storage_lineage.IngestionRun | BaseException],
    emit: EmitMessage,
) -> int:
    completed_runs = 0
    for result in settled:
        if isinstance(result, BaseException):
            emit(f"Streaming pipeline failed: {result}", True)
            continue
        if result.status != "completed":
            errors = ", ".join(result.errors[-3:]) if result.errors else "unknown error"
            emit(f"Streaming run failed ({result.run_id}): {errors}", True)
            continue
        completed_runs += 1
    return completed_runs


__all__ = [
    "CollectionMode",
    "PipelineContext",
    "StreamingPipelineContext",
    "build_pipeline_contexts",
    "build_polling_scheduler",
    "build_streaming_pipeline_contexts",
    "collect_outcome_ids",
    "execute_pipeline_connector",
    "run_polling_and_streaming",
    "run_polling_pipelines",
    "run_streaming_pipelines",
]
