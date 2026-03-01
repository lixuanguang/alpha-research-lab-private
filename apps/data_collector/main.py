"""Data collector CLI commands for runtime control and validation."""

from __future__ import annotations

import asyncio
import collections
from datetime import UTC, datetime, timedelta
from pathlib import Path

import click

import alpha_core.adapters.pmxt_adapter as adapters_pmxt
import alpha_core.config.loader as config_loader
import alpha_core.config.secrets as config_secrets
import alpha_core.storage.lineage as storage_lineage
import apps.data_collector.runtime as collector_runtime


@click.group()
def main() -> None:
    """Run data-collector operational commands."""


@main.command("run")
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
    enabled_venues = sorted(venue.name for venue in settings.venues if venue.enabled)
    if not enabled_venues:
        raise click.ClickException("No enabled venues found for run command.")

    click.echo(
        "Run configuration ready "
        f"(environment={environment or 'default'}, venues={','.join(enabled_venues)})"
    )
    if not execute:
        click.echo("Execution mode: plan-only (pass --execute to start pipelines).")
        return

    try:
        completed_runs = asyncio.run(
            collector_runtime.run_polling_pipelines(
                settings,
                once=once,
                max_outcomes_per_venue=max_outcomes_per_venue,
                request_timeout_seconds=request_timeout_seconds,
                adapter_factory=adapters_pmxt.PmxtAdapter,
                emit=lambda message, is_error: click.echo(message, err=is_error),
            )
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(
        "Execution complete "
        f"(mode={'once' if once else 'continuous'}, successful_runs={completed_runs})"
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
@click.option("--instrument-id", required=True, help="Canonical instrument id to replay.")
@click.option("--start", required=True, help="Inclusive UTC start timestamp.")
@click.option("--end", required=True, help="Inclusive UTC end timestamp.")
def backfill_command(venue: str, instrument_id: str, start: str, end: str) -> None:
    """Backfill command shell (fully implemented in step D6)."""
    raise click.ClickException(
        "Command `backfill` is not implemented yet (pending D6). "
        f"Received inputs: venue={venue}, instrument_id={instrument_id}, start={start}, end={end}"
    )


@main.command("detect-gaps")
@click.option("--venue", default=None, help="Optional venue filter.")
@click.option("--start", default=None, help="Optional UTC start timestamp.")
@click.option("--end", default=None, help="Optional UTC end timestamp.")
def detect_gaps_command(venue: str | None, start: str | None, end: str | None) -> None:
    """Gap-detection command shell (fully implemented in step D6)."""
    raise click.ClickException(
        "Command `detect-gaps` is not implemented yet (pending D6). "
        f"Received inputs: venue={venue or 'all'}, start={start or 'none'}, end={end or 'none'}"
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


if __name__ == "__main__":
    main()
