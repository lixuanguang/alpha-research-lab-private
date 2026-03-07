"""Data collector CLI commands for runtime control and validation."""

from __future__ import annotations

import click

import alpha_core.config.loader as config_loader
import alpha_core.config.secrets as config_secrets
import apps.data_collector.cli_support as cli_support
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

    settings, selected_venues = cli_support.prepare_run_settings(
        environment=environment,
        apply_user_settings=apply_user_settings,
        validate_secrets=validate_secrets,
        requested_venues=venues,
    )
    if not selected_venues:
        raise click.ClickException("No enabled venues found for run command.")

    click.echo(
        "Run configuration ready "
        f"(environment={environment or 'default'}, mode={mode}, "
        f"venues={','.join(selected_venues)})"
    )
    if not execute:
        click.echo("Execution mode: plan-only (pass --execute to start pipelines).")
        return

    completed_runs = cli_support.run_collection_mode(
        cli_support.CollectionModeRequest(
            mode=mode,
            settings=settings,
            runtime_options=collector_runtime.RuntimeOptions(
                once=once,
                max_outcomes_per_venue=max_outcomes_per_venue,
                request_timeout_seconds=request_timeout_seconds,
                venue_names=set(selected_venues),
            ),
        ),
        emit=_cli_emit,
    )

    click.echo(
        "Execution complete "
        f"(collection_mode={mode}, "
        f"run_mode={'once' if once else 'continuous'}, "
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
@click.option(
    "--venue",
    type=str,
    default=None,
    help="Optional venue filter for data-quality validation.",
)
@click.option(
    "--since",
    type=str,
    default=None,
    help="Optional ISO8601 lower-bound for data-quality validation.",
)
def validate_command(
    environment: str | None,
    apply_user_settings: bool,
    venue: str | None,
    since: str | None,
) -> None:
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

    since_dt = cli_support.parse_utc_datetime(since) if since is not None else None
    if venue is not None or since_dt is not None:
        if venue is not None:
            cli_support.require_venue(settings, venue.strip().lower())
        reports = cli_support.run_quality_validation(
            settings=settings,
            venue=venue.strip().lower() if venue is not None else None,
            since=since_dt,
        )
        if not reports:
            click.echo("Data quality validation: no matching silver data in the requested window.")
            return
        failed_reports = sum(1 for report in reports if not report.passed)
        degraded_reports = sum(1 for report in reports if report.degraded)
        click.echo(
            "Data quality validation complete: "
            f"reports={len(reports)}, failed={failed_reports}, degraded={degraded_reports}"
        )
        for report in reports:
            click.echo(
                f"  suite={report.suite_name}, passed={report.passed}, "
                f"degraded={report.degraded}, rows={report.row_count}"
            )
        if failed_reports > 0:
            raise click.ClickException(
                "Data quality validation failed one or more fail-severity suites."
            )


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
    cli_support.echo_recent_runtime_metrics(settings.storage.base_path)


@main.command("backfill")
@click.option("--venue", required=True, help="Target venue (e.g. polymarket).")
@click.option(
    "--outcomes",
    multiple=True,
    required=True,
    help="Canonical outcome ids to backfill (repeat flag for multiple).",
)
@click.option(
    "--start",
    required=False,
    default=None,
    help="Inclusive UTC start timestamp (ISO 8601). Required unless --resume is set.",
)
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
@click.option(
    "--resume/--no-resume",
    default=False,
    show_default=True,
    help=(
        "When set, reads the cursor watermark from the most recent completed "
        "run for this venue and uses it as the start of the backfill window.  "
        "Overrides --start when a valid cursor is found."
    ),
)
def backfill_command(
    venue: str,
    outcomes: tuple[str, ...],
    start: str | None,
    end: str,
    event_type: str,
    resolution: str,
    batch_size: int,
    environment: str | None,
    resume: bool,
) -> None:
    """Backfill historical data for a time window.

    Use ``--resume`` to continue from the watermark of the last completed run
    instead of providing an explicit ``--start`` timestamp:

    \\b
        data-collector backfill \\
            --venue polymarket \\
            --outcomes p:mkt1:yes \\
            --end 2026-02-01T00:00:00Z \\
            --resume
    """
    if start is None and not resume:
        raise click.ClickException(
            "--start is required unless --resume is set.  "
            "Pass --resume to start from the last cursor watermark."
        )

    end_dt = cli_support.parse_utc_datetime(end)
    if batch_size <= 0:
        raise click.ClickException("`--batch-size` must be > 0.")

    # Resolve start datetime — either explicit or from last cursor.
    if resume:
        last_run = cli_support.get_last_cursor(
            venue=venue,
            event_type=event_type,
            environment=environment,
        )
        if last_run is not None and last_run.cursor_watermark_utc is not None:
            start_dt = last_run.cursor_watermark_utc
            if not last_run.resume_safe:
                click.echo(
                    f"Warning: last cursor for venue={venue} is marked resume_safe=False. "
                    "The previous run may have been interrupted; consider adding window overlap.",
                    err=True,
                )
            click.echo(
                f"Resume mode: using cursor watermark {start_dt.isoformat()} "
                f"from run {last_run.run_id} as window start."
            )
        elif start is not None:
            click.echo(
                f"Resume mode: no cursor found for venue={venue}, "
                "falling back to explicit --start value."
            )
            start_dt = cli_support.parse_utc_datetime(start)
        else:
            raise click.ClickException(
                f"--resume was set but no cursor found for venue='{venue}' "
                f"event_type='{event_type}' and no --start fallback was provided."
            )
    else:
        start_dt = cli_support.parse_utc_datetime(start)  # type: ignore[arg-type]

    result = cli_support.run_backfill(
        cli_support.BackfillRequest(
            venue=venue,
            outcomes=list(outcomes),
            start_dt=start_dt,
            end_dt=end_dt,
            event_type=event_type,
            resolution=resolution,
            batch_size=batch_size,
            environment=environment,
        )
    )

    cursor_info = (
        f", cursor_watermark={result.cursor_watermark_utc.isoformat()}"
        if result.cursor_watermark_utc is not None
        else ""
    )
    replay_info = (
        f", replay_package_id={result.replay_package_id}"
        if result.replay_package_id is not None
        else ""
    )
    click.echo(
        f"Backfill complete: venue={result.venue}, event_type={result.event_type}, "
        f"fetched={result.events_fetched}, stored={result.events_stored}, "
        f"rejected={result.events_rejected}, duration={result.duration_seconds:.2f}s"
        f"{cursor_info}{replay_info}"
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
    start_dt, end_dt = cli_support.parse_window_datetimes(start, end)
    if max_gap_hours <= 0:
        raise click.ClickException("`--max-gap-hours` must be > 0.")

    request = cli_support.GapDetectionRequest(
        venue=venue,
        requested_outcomes=list(outcomes),
        event_type=event_type,
        start_dt=start_dt,
        end_dt=end_dt,
        max_gap_hours=max_gap_hours,
        resolution=resolution,
        environment=environment,
    )
    outcome_ids, all_gaps = cli_support.detect_gaps(request)
    if outcome_ids is None:
        click.echo(f"No data found for venue='{venue}' in the given window.")
        return
    if not all_gaps:
        click.echo(
            f"No gaps detected for venue={venue}, event_type={event_type}, "
            f"outcomes={len(outcome_ids)}, window=[{start_dt.date()}, {end_dt.date()}]."
        )
        return

    click.echo(f"Detected {len(all_gaps)} gap(s) for venue={venue}, event_type={event_type}:")
    for gap in all_gaps:
        click.echo(
            f"  outcome={gap.outcome_id}, "
            f"start={gap.gap_start.isoformat()}, "
            f"end={gap.gap_end.isoformat()}, "
            f"duration={gap.duration_seconds / 3600:.2f}h"
        )


@main.command("list-packages")
@click.option("--venue", default=None, help="Filter by venue name.")
@click.option(
    "--since",
    default=None,
    help="Only show packages whose window_end is on or after this ISO 8601 timestamp.",
)
@click.option(
    "--environment",
    type=str,
    default=None,
    help="Optional environment overlay.",
)
def list_packages_command(
    venue: str | None,
    since: str | None,
    environment: str | None,
) -> None:
    """List replay packages available in the store."""
    since_dt = cli_support.parse_utc_datetime(since) if since is not None else None
    packages = cli_support.list_replay_packages(
        venue=venue,
        since=since_dt,
        environment=environment,
    )
    if not packages:
        click.echo("No replay packages found.")
        return

    click.echo(f"Replay packages ({len(packages)}):")
    for pkg in packages:
        cursor_info = (
            f", cursor_watermark={pkg.cursor_watermark_utc.isoformat()}"
            if pkg.cursor_watermark_utc is not None
            else ""
        )
        click.echo(
            f"  package_id={pkg.package_id}, venue={pkg.venue}, "
            f"window=[{pkg.window_start.date()}, {pkg.window_end.date()}], "
            f"event_types={','.join(pkg.event_types)}, "
            f"total_events={pkg.total_event_count}, "
            f"partitions={len(pkg.partitions)}"
            f"{cursor_info}"
        )


def _cli_emit(message: str, is_error: bool) -> None:
    click.echo(message, err=is_error)


if __name__ == "__main__":
    main()
