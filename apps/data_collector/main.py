"""Data collector CLI commands for runtime control and validation."""

from __future__ import annotations

import asyncio
import collections
from datetime import UTC, datetime, timedelta
from pathlib import Path

import click

import alpha_core.adapters.pmxt_adapter as adapters_pmxt
import alpha_core.config.loader as config_loader
import alpha_core.config.models as config_models
import alpha_core.config.secrets as config_secrets
import alpha_core.events.quality as event_quality
import alpha_core.quality.gap_detector as gap_detector_mod
import alpha_core.storage.bronze_writer as storage_bronze
import alpha_core.storage.lineage as storage_lineage
import alpha_core.storage.parquet_reader as parquet_reader_mod
import alpha_core.storage.parquet_writer as storage_parquet
import apps.data_collector.backfill as collector_backfill
import apps.data_collector.runtime as collector_runtime


@click.group()
def main() -> None:
    """Run data-collector operational commands."""


@main.command("run")
@click.option(
    "--venues",
    multiple=True,
    help="Optional venue subset (repeat flag); defaults to all enabled venues.",
)
@click.option(
    "--mode",
    type=click.Choice(["poll", "stream", "both"]),
    default="poll",
    show_default=True,
    help="Collection mode to execute.",
)
@click.option(
    "--environment",
    type=str,
    default=None,
    help="Optional environment overlay (e.g. local).",
)
@click.option(
    "--apply-user-settings/--ignore-user-settings",
    default=True,
    show_default=True,
    help="Apply venue toggles from config/user_settings.yaml.",
)
@click.option(
    "--validate-secrets/--skip-secret-validation",
    default=False,
    show_default=True,
    help="Fail fast when enabled venues are missing required credentials.",
)
@click.option(
    "--execute/--plan-only",
    default=False,
    show_default=True,
    help="Execute polling pipelines instead of only validating runtime configuration.",
)
@click.option(
    "--once/--continuous",
    default=True,
    show_default=True,
    help="Run one ingestion cycle or continue polling indefinitely.",
)
@click.option(
    "--max-outcomes-per-venue",
    type=int,
    default=50,
    show_default=True,
    help="Upper bound of outcomes to poll per venue when execution is enabled.",
)
@click.option(
    "--request-timeout-seconds",
    type=float,
    default=10.0,
    show_default=True,
    help="Per-request timeout applied to venue polling calls.",
)
def run_command(
    venues: tuple[str, ...],
    mode: str,
    environment: str | None,
    apply_user_settings: bool,
    validate_secrets: bool,
    execute: bool,
    once: bool,
    max_outcomes_per_venue: int,
    request_timeout_seconds: float,
) -> None:
    """Validate runtime configuration and optionally execute polling pipelines."""
    if max_outcomes_per_venue <= 0:
        raise click.ClickException("`--max-outcomes-per-venue` must be > 0.")
    if request_timeout_seconds <= 0:
        raise click.ClickException("`--request-timeout-seconds` must be > 0.")

    settings = config_loader.load_settings(
        environment=environment,
        apply_user_settings=apply_user_settings,
        validate_secrets=validate_secrets,
    )
    selected_venues = _resolve_target_venues(settings, requested_venues=venues)
    if not selected_venues:
        raise click.ClickException("No enabled venues found for run command.")

    click.echo(
        "Run configuration ready "
        f"(environment={environment or 'default'}, mode={mode}, venues={','.join(selected_venues)})"
    )
    if not execute:
        click.echo("Execution mode: plan-only (pass --execute to start pipelines).")
        return

    try:
        if mode == "poll":
            completed_runs = asyncio.run(
                collector_runtime.run_polling_pipelines(
                    settings,
                    once=once,
                    max_outcomes_per_venue=max_outcomes_per_venue,
                    request_timeout_seconds=request_timeout_seconds,
                    adapter_factory=adapters_pmxt.PmxtAdapter,
                    emit=lambda message, is_error: click.echo(message, err=is_error),
                    venue_names=set(selected_venues),
                )
            )
        elif mode == "stream":
            completed_runs = asyncio.run(
                collector_runtime.run_streaming_pipelines(
                    settings,
                    once=once,
                    max_outcomes_per_venue=max_outcomes_per_venue,
                    request_timeout_seconds=request_timeout_seconds,
                    adapter_factory=adapters_pmxt.PmxtAdapter,
                    emit=lambda message, is_error: click.echo(message, err=is_error),
                    venue_names=set(selected_venues),
                )
            )
        else:
            completed_runs = asyncio.run(
                collector_runtime.run_polling_and_streaming(
                    settings,
                    once=once,
                    max_outcomes_per_venue=max_outcomes_per_venue,
                    request_timeout_seconds=request_timeout_seconds,
                    adapter_factory=adapters_pmxt.PmxtAdapter,
                    emit=lambda message, is_error: click.echo(message, err=is_error),
                    venue_names=set(selected_venues),
                )
            )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(
        "Execution complete "
        f"(collection_mode={mode}, run_mode={'once' if once else 'continuous'}, "
        f"successful_runs={completed_runs})"
    )


@main.command("validate")
@click.option(
    "--environment",
    type=str,
    default=None,
    help="Optional environment overlay (e.g. ci).",
)
@click.option(
    "--apply-user-settings/--ignore-user-settings",
    default=False,
    show_default=True,
    help="Apply venue toggles from config/user_settings.yaml.",
)
def validate_command(environment: str | None, apply_user_settings: bool) -> None:
    """Validate config schema and report missing secrets for enabled venues."""
    settings = config_loader.load_settings(
        environment=environment,
        apply_user_settings=apply_user_settings,
        validate_secrets=False,
    )
    missing = config_secrets.missing_required_secrets(settings)
    enabled_venues = sorted(venue.name for venue in settings.venues if venue.enabled)

    click.echo(
        "Configuration valid "
        f"(environment={environment or 'default'}, enabled_venues={len(enabled_venues)})"
    )
    if missing:
        missing_joined = ", ".join(missing)
        raise click.ClickException(f"Missing required secrets: {missing_joined}")
    click.echo("All required secrets resolved for enabled venues.")


@main.command("status")
@click.option(
    "--apply-user-settings/--ignore-user-settings",
    default=True,
    show_default=True,
    help="Apply venue toggles from config/user_settings.yaml.",
)
def status_command(apply_user_settings: bool) -> None:
    """Show configured venues and recent runtime connector metrics."""
    settings = config_loader.load_settings(
        environment=None,
        apply_user_settings=apply_user_settings,
        validate_secrets=False,
    )
    enabled = sorted(venue.name for venue in settings.venues if venue.enabled)
    disabled = sorted(venue.name for venue in settings.venues if not venue.enabled)

    click.echo(f"Enabled venues ({len(enabled)}): {', '.join(enabled) if enabled else 'none'}")
    click.echo(f"Disabled venues ({len(disabled)}): {', '.join(disabled) if disabled else 'none'}")
    _echo_recent_runtime_metrics(settings.storage.base_path)


@main.command("backfill")
@click.option("--venue", required=True, help="Target venue (e.g. polymarket).")
@click.option(
    "--outcomes",
    multiple=True,
    required=True,
    help="Canonical outcome ids to backfill (repeat flag for multiple).",
)
@click.option("--start", required=True, help="Inclusive UTC start timestamp (ISO 8601).")
@click.option("--end", required=True, help="Inclusive UTC end timestamp (ISO 8601).")
@click.option(
    "--event-type",
    type=click.Choice(["trades", "ohlcv"]),
    default="trades",
    show_default=True,
    help="Data type to backfill.",
)
@click.option(
    "--resolution",
    default="1h",
    show_default=True,
    help="OHLCV resolution (ignored for trades). One of: 1m, 5m, 1h, 1d.",
)
@click.option(
    "--batch-size",
    type=int,
    default=500,
    show_default=True,
    help="Number of trades fetched per pagination call.",
)
@click.option(
    "--environment",
    type=str,
    default=None,
    help="Optional environment overlay (e.g. local).",
)
def backfill_command(
    venue: str,
    outcomes: tuple[str, ...],
    start: str,
    end: str,
    event_type: str,
    resolution: str,
    batch_size: int,
    environment: str | None,
) -> None:
    """Backfill historical data for a time window."""
    try:
        start_dt = _parse_utc_datetime(start)
        end_dt = _parse_utc_datetime(end)
    except ValueError as exc:
        raise click.ClickException(f"Invalid datetime: {exc}") from exc

    if batch_size <= 0:
        raise click.ClickException("`--batch-size` must be > 0.")

    settings = config_loader.load_settings(
        environment=environment,
        apply_user_settings=False,
        validate_secrets=False,
    )
    venue_config = _require_venue(settings, venue)
    storage_root = settings.storage.base_path

    try:
        adapter = adapters_pmxt.PmxtAdapter(venue, venue_config)
    except Exception as exc:
        raise click.ClickException(f"Failed to initialise adapter for '{venue}': {exc}") from exc

    manager = collector_backfill.BackfillManager(
        adapter=adapter,
        bronze_writer=storage_bronze.BronzeWriter(storage_root),
        silver_writer=storage_parquet.ParquetEventWriter(storage_root),
        quality_checker=event_quality.EventQualityChecker(),
        lineage_store=storage_lineage.LineageStore(storage_root),
    )
    outcome_ids = list(outcomes)

    try:
        if event_type == "trades":
            result = asyncio.run(
                manager.backfill_trades(
                    outcome_ids, start=start_dt, end=end_dt, batch_size=batch_size
                )
            )
        else:
            result = asyncio.run(
                manager.backfill_ohlcv(
                    outcome_ids, resolution=resolution, start=start_dt, end=end_dt
                )
            )
    except Exception as exc:
        raise click.ClickException(f"Backfill failed: {exc}") from exc

    click.echo(
        f"Backfill complete: venue={result.venue}, event_type={result.event_type}, "
        f"fetched={result.events_fetched}, stored={result.events_stored}, "
        f"rejected={result.events_rejected}, duration={result.duration_seconds:.2f}s"
    )


@main.command("detect-gaps")
@click.option("--venue", required=True, help="Target venue.")
@click.option(
    "--outcomes",
    multiple=True,
    help="Canonical outcome ids to check (repeat flag). Defaults to all found in silver data.",
)
@click.option(
    "--event-type",
    type=click.Choice(["trades", "ohlcv"]),
    default="trades",
    show_default=True,
    help="Data type to scan for gaps.",
)
@click.option("--start", required=True, help="Window start (ISO 8601 UTC).")
@click.option("--end", required=True, help="Window end (ISO 8601 UTC).")
@click.option(
    "--max-gap-hours",
    type=float,
    default=1.0,
    show_default=True,
    help="Minimum gap duration in hours to report.",
)
@click.option(
    "--resolution",
    default="1h",
    show_default=True,
    help="OHLCV resolution (ignored for trades). One of: 1m, 5m, 1h, 1d.",
)
@click.option(
    "--environment",
    type=str,
    default=None,
    help="Optional environment overlay (e.g. local).",
)
def detect_gaps_command(
    venue: str,
    outcomes: tuple[str, ...],
    event_type: str,
    start: str,
    end: str,
    max_gap_hours: float,
    resolution: str,
    environment: str | None,
) -> None:
    """Detect gaps in collected data for a time window."""
    try:
        start_dt = _parse_utc_datetime(start)
        end_dt = _parse_utc_datetime(end)
    except ValueError as exc:
        raise click.ClickException(f"Invalid datetime: {exc}") from exc
    if max_gap_hours <= 0:
        raise click.ClickException("`--max-gap-hours` must be > 0.")

    settings = config_loader.load_settings(
        environment=environment,
        apply_user_settings=False,
        validate_secrets=False,
    )
    storage_root = settings.storage.base_path
    reader = parquet_reader_mod.ParquetEventReader(storage_root)
    detector = gap_detector_mod.GapDetector(reader)

    # Resolve outcome ids: use provided or scan silver data
    outcome_ids: list[str] = list(outcomes)
    if not outcome_ids:
        outcome_ids = _scan_instrument_ids(
            reader,
            venue=venue,
            start=start_dt,
            end=end_dt,
            event_type=event_type,
            resolution=resolution if event_type == "ohlcv" else None,
        )
        if not outcome_ids:
            click.echo(f"No data found for venue='{venue}' in the given window.")
            return

    all_gaps: list[gap_detector_mod.TimeGap] = []
    max_gap_seconds = max_gap_hours * 3600.0
    for outcome_id in outcome_ids:
        if event_type == "trades":
            gaps = detector.detect_trade_gaps(
                venue, outcome_id, start=start_dt, end=end_dt, max_gap_seconds=max_gap_seconds
            )
        else:
            gaps = detector.detect_ohlcv_gaps(
                venue, outcome_id, resolution=resolution, start=start_dt, end=end_dt
            )
        all_gaps.extend(gaps)

    if not all_gaps:
        click.echo(
            f"No gaps detected for venue={venue}, event_type={event_type}, "
            f"outcomes={len(outcome_ids)}, window=[{start_dt.date()}, {end_dt.date()}]."
        )
        return

    click.echo(
        f"Detected {len(all_gaps)} gap(s) for venue={venue}, event_type={event_type}:"
    )
    for gap in all_gaps:
        click.echo(
            f"  outcome={gap.outcome_id}, "
            f"start={gap.gap_start.isoformat()}, "
            f"end={gap.gap_end.isoformat()}, "
            f"duration={gap.duration_seconds / 3600:.2f}h"
        )


def _echo_recent_runtime_metrics(storage_root: Path) -> None:
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
        counts = run.counts
        click.echo(
            "Recent run: "
            f"venue={venue}, "
            f"status={run.status}, "
            f"run_id={run.run_id}, "
            f"events_raw={counts.get('events_raw', 0)}, "
            f"events_silver={counts.get('events_silver', 0)}, "
            f"rejected={counts.get('rejected', 0)}, "
            f"errors={len(run.errors)}"
        )


def _parse_utc_datetime(value: str) -> datetime:
    """Parse an ISO 8601 string and return a UTC-aware datetime."""
    cleaned = value.strip().rstrip("Z")
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError(f"Cannot parse '{value}' as ISO 8601 datetime.") from exc
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _require_venue(
    settings: config_models.Settings, venue: str
) -> config_models.VenueConfig:
    """Return the VenueConfig for *venue* or raise ClickException."""
    venue_config = next((v for v in settings.venues if v.name == venue), None)
    if venue_config is None:
        available = sorted(v.name for v in settings.venues)
        raise click.ClickException(
            f"Venue '{venue}' not found in config. Available: {available}"
        )
    return venue_config


def _scan_instrument_ids(
    reader: parquet_reader_mod.ParquetEventReader,
    *,
    venue: str,
    start: datetime,
    end: datetime,
    event_type: str,
    resolution: str | None = None,
) -> list[str]:
    """Return distinct instrument_ids present in silver data for the window/event type."""
    if event_type == "trades":
        table = reader.read_trades(venue=venue, start=start, end=end)
    elif event_type == "ohlcv":
        table = reader.read_ohlcv(venue=venue, resolution=resolution, start=start, end=end)
    else:
        raise ValueError(f"Unsupported event_type for instrument scan: {event_type}")
    if table.num_rows == 0 or "instrument_id" not in table.schema.names:
        return []
    return sorted(set(table.column("instrument_id").to_pylist()))


def _resolve_target_venues(
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

    unknown = sorted(name for name in requested if name not in {v.name for v in settings.venues})
    if unknown:
        raise click.ClickException(f"Unknown venue(s) requested: {unknown}")

    disabled_requested = sorted(name for name in requested if name not in enabled_venues)
    if disabled_requested:
        raise click.ClickException(f"Requested venue(s) are disabled: {disabled_requested}")

    return requested


if __name__ == "__main__":
    main()
