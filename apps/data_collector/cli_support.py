"""Operational helpers for the data-collector CLI."""

from __future__ import annotations

import asyncio
import collections
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import click

import alpha_core.adapters.pmxt_adapter as adapters_pmxt
import alpha_core.config.loader as config_loader
import alpha_core.config.models as config_models
import alpha_core.events.quality as event_quality
import alpha_core.quality.base as quality_base
import alpha_core.quality.gap_detector as gap_detector_mod
import alpha_core.quality.partition_validator as quality_partition_validator
import alpha_core.storage.bronze_writer as storage_bronze
import alpha_core.storage.lineage as storage_lineage
import alpha_core.storage.parquet_reader as parquet_reader_mod
import alpha_core.storage.parquet_writer as storage_parquet
import apps.data_collector.backfill as collector_backfill
import apps.data_collector.runtime as collector_runtime


@dataclass(slots=True, frozen=True)
class CollectionModeRequest:
    mode: str
    settings: config_models.Settings
    runtime_options: collector_runtime.RuntimeOptions


@dataclass(slots=True, frozen=True)
class BackfillRequest:
    venue: str
    outcomes: list[str]
    start_dt: datetime
    end_dt: datetime
    event_type: str
    resolution: str
    batch_size: int
    environment: str | None


@dataclass(slots=True, frozen=True)
class GapScanScope:
    venue: str
    event_type: str
    start_dt: datetime
    end_dt: datetime
    resolution: str | None = None


@dataclass(slots=True, frozen=True)
class OutcomeGapScanScope:
    venue: str
    outcome_id: str
    event_type: str
    start_dt: datetime
    end_dt: datetime
    max_gap_seconds: float
    resolution: str


@dataclass(slots=True, frozen=True)
class GapDetectionRequest:
    venue: str
    requested_outcomes: list[str]
    event_type: str
    start_dt: datetime
    end_dt: datetime
    max_gap_hours: float
    resolution: str
    environment: str | None


def prepare_run_settings(
    *,
    environment: str | None,
    apply_user_settings: bool,
    validate_secrets: bool,
    requested_venues: tuple[str, ...],
) -> tuple[config_models.Settings, list[str]]:
    settings = config_loader.load_settings(
        environment=environment,
        apply_user_settings=apply_user_settings,
        validate_secrets=validate_secrets,
    )
    selected_venues = resolve_target_venues(settings, requested_venues=requested_venues)
    return settings, selected_venues


def run_collection_mode(
    request: CollectionModeRequest,
    *,
    emit: Callable[[str, bool], None],
) -> int:
    run_collectors: dict[str, Callable[..., Coroutine[object, object, int]]] = {
        "poll": collector_runtime.run_polling_pipelines,
        "stream": collector_runtime.run_streaming_pipelines,
        "both": collector_runtime.run_polling_and_streaming,
    }
    run_collector = run_collectors.get(request.mode)
    if run_collector is None:
        raise click.ClickException(f"Unsupported mode: {request.mode}")
    try:
        return asyncio.run(
            run_collector(
                request.settings,
                options=request.runtime_options,
                adapter_factory=adapters_pmxt.PmxtAdapter,
                emit=emit,
            )
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


def parse_window_datetimes(start: str, end: str) -> tuple[datetime, datetime]:
    try:
        return parse_utc_datetime(start), parse_utc_datetime(end)
    except ValueError as exc:
        raise click.ClickException(f"Invalid datetime: {exc}") from exc


def build_backfill_manager(
    *,
    venue: str,
    environment: str | None,
) -> collector_backfill.BackfillManager:
    settings = config_loader.load_settings(
        environment=environment,
        apply_user_settings=False,
        validate_secrets=False,
    )
    venue_config = require_venue(settings, venue)
    storage_root = settings.storage.base_path
    try:
        adapter = adapters_pmxt.PmxtAdapter(venue, venue_config)
    except Exception as exc:
        raise click.ClickException(f"Failed to initialise adapter for '{venue}': {exc}") from exc

    return collector_backfill.BackfillManager(
        adapter=adapter,
        dependencies=collector_backfill.BackfillDependencies(
            bronze_writer=storage_bronze.BronzeWriter(storage_root),
            silver_writer=storage_parquet.ParquetEventWriter(storage_root),
            quality_checker=event_quality.EventQualityChecker(),
            lineage_store=storage_lineage.LineageStore(storage_root),
        ),
    )


def run_backfill(request: BackfillRequest) -> collector_backfill.BackfillResult:
    manager = build_backfill_manager(venue=request.venue, environment=request.environment)
    try:
        if request.event_type == "trades":
            return asyncio.run(
                manager.backfill_trades(
                    request.outcomes,
                    start=request.start_dt,
                    end=request.end_dt,
                    batch_size=request.batch_size,
                )
            )
        return asyncio.run(
            manager.backfill_ohlcv(
                request.outcomes,
                resolution=request.resolution,
                start=request.start_dt,
                end=request.end_dt,
            )
        )
    except Exception as exc:
        raise click.ClickException(f"Backfill failed: {exc}") from exc


def detect_gaps(
    request: GapDetectionRequest,
) -> tuple[list[str] | None, list[gap_detector_mod.TimeGap]]:
    settings = config_loader.load_settings(
        environment=request.environment,
        apply_user_settings=False,
        validate_secrets=False,
    )
    reader = parquet_reader_mod.ParquetEventReader(settings.storage.base_path)
    detector = gap_detector_mod.GapDetector(reader)
    scope = GapScanScope(
        venue=request.venue,
        event_type=request.event_type,
        start_dt=request.start_dt,
        end_dt=request.end_dt,
        resolution=request.resolution if request.event_type == "ohlcv" else None,
    )
    outcome_ids = request.requested_outcomes or scan_instrument_ids(reader, scope=scope)
    if not outcome_ids:
        return None, []

    max_gap_seconds = request.max_gap_hours * 3600.0
    all_gaps: list[gap_detector_mod.TimeGap] = []
    for outcome_id in outcome_ids:
        all_gaps.extend(
            detect_outcome_gaps(
                detector,
                scope=OutcomeGapScanScope(
                    venue=request.venue,
                    outcome_id=outcome_id,
                    event_type=request.event_type,
                    start_dt=request.start_dt,
                    end_dt=request.end_dt,
                    max_gap_seconds=max_gap_seconds,
                    resolution=request.resolution,
                ),
            )
        )
    return outcome_ids, all_gaps


def echo_recent_runtime_metrics(storage_root: Path) -> None:
    lineage_store = storage_lineage.LineageStore(storage_root)
    since = datetime.now(tz=UTC) - timedelta(hours=24)
    recent_runs = lineage_store.list_runs(since=since)
    if not recent_runs:
        click.echo("Runtime metrics (24h): no ingestion runs recorded.")
        return

    status_counts = collections.Counter(run.status for run in recent_runs)
    click.echo(
        "Runtime metrics (24h): "
        f"total_runs={len(recent_runs)}, "
        f"completed={status_counts.get('completed', 0)}, "
        f"failed={status_counts.get('failed', 0)}, "
        f"running={status_counts.get('running', 0)}"
    )

    latest_by_venue: dict[str, storage_lineage.IngestionRun] = {}
    for run in recent_runs:
        latest_by_venue.setdefault(run.venue, run)

    for venue in sorted(latest_by_venue):
        run = latest_by_venue[venue]
        click.echo(
            "Recent run: "
            f"venue={venue}, "
            f"status={run.status}, "
            f"run_id={run.run_id}, "
            f"events_raw={run.counts.get('events_raw', 0)}, "
            f"events_silver={run.counts.get('events_silver', 0)}, "
            f"rejected={run.counts.get('rejected', 0)}, "
            f"errors={len(run.errors)}"
        )


def run_quality_validation(
    *,
    settings: config_models.Settings,
    venue: str | None,
    since: datetime | None,
) -> list[quality_base.SuiteReport]:
    window_start = since if since is not None else datetime.now(tz=UTC) - timedelta(days=1)
    reader = parquet_reader_mod.ParquetEventReader(settings.storage.base_path)
    validator = quality_partition_validator.PartitionValidator.from_defaults(
        reader=reader,
        include_microstructure=True,
    )
    return validator.validate_since(since=window_start, venue=venue)


def parse_utc_datetime(value: str) -> datetime:
    cleaned = value.strip().rstrip("Z")
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError(f"Cannot parse '{value}' as ISO 8601 datetime.") from exc
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def require_venue(settings: config_models.Settings, venue: str) -> config_models.VenueConfig:
    venue_config = next(
        (candidate for candidate in settings.venues if candidate.name == venue),
        None,
    )
    if venue_config is None:
        available = sorted(candidate.name for candidate in settings.venues)
        raise click.ClickException(f"Venue '{venue}' not found in config. Available: {available}")
    return venue_config


def scan_instrument_ids(
    reader: parquet_reader_mod.ParquetEventReader,
    *,
    scope: GapScanScope,
) -> list[str]:
    if scope.event_type == "trades":
        table = reader.read_trades(venue=scope.venue, start=scope.start_dt, end=scope.end_dt)
    elif scope.event_type == "ohlcv":
        table = reader.read_ohlcv(
            venue=scope.venue,
            resolution=scope.resolution,
            start=scope.start_dt,
            end=scope.end_dt,
        )
    else:
        raise ValueError(f"Unsupported event_type for instrument scan: {scope.event_type}")
    if table.num_rows == 0 or "instrument_id" not in table.schema.names:
        return []
    outcome_ids = {
        value.strip()
        for value in table.column("instrument_id").to_pylist()
        if isinstance(value, str) and value.strip()
    }
    return sorted(outcome_ids)


def detect_outcome_gaps(
    detector: gap_detector_mod.GapDetector,
    *,
    scope: OutcomeGapScanScope,
) -> list[gap_detector_mod.TimeGap]:
    if scope.event_type == "trades":
        return detector.detect_trade_gaps(
            scope.venue,
            scope.outcome_id,
            start=scope.start_dt,
            end=scope.end_dt,
            max_gap_seconds=scope.max_gap_seconds,
        )
    return detector.detect_ohlcv_gaps(
        scope.venue,
        scope.outcome_id,
        resolution=scope.resolution,
        start=scope.start_dt,
        end=scope.end_dt,
    )


def resolve_target_venues(
    settings: config_models.Settings,
    *,
    requested_venues: tuple[str, ...],
) -> list[str]:
    enabled_venues = sorted(venue.name for venue in settings.venues if venue.enabled)
    if not requested_venues:
        return enabled_venues

    requested = sorted({name.strip().lower() for name in requested_venues if name.strip()})
    if not requested:
        return enabled_venues

    known_venues = {venue.name for venue in settings.venues}
    unknown = sorted(name for name in requested if name not in known_venues)
    if unknown:
        raise click.ClickException(f"Unknown venue(s) requested: {unknown}")

    disabled_requested = sorted(name for name in requested if name not in enabled_venues)
    if disabled_requested:
        raise click.ClickException(f"Requested venue(s) are disabled: {disabled_requested}")

    return requested


__all__ = [
    "BackfillRequest",
    "CollectionModeRequest",
    "GapDetectionRequest",
    "GapScanScope",
    "build_backfill_manager",
    "detect_gaps",
    "detect_outcome_gaps",
    "echo_recent_runtime_metrics",
    "parse_utc_datetime",
    "parse_window_datetimes",
    "prepare_run_settings",
    "require_venue",
    "resolve_target_venues",
    "run_backfill",
    "run_collection_mode",
    "run_quality_validation",
    "scan_instrument_ids",
]
