"""Data collector CLI commands for runtime control and validation."""

from __future__ import annotations

import click

import alpha_core.config.loader as config_loader
import alpha_core.config.models as config_models
import alpha_core.config.secrets as config_secrets


def _load_settings(
    *,
    environment: str | None,
    apply_user_settings: bool,
    validate_secrets: bool,
) -> config_models.Settings:
    return config_loader.load_settings(
        environment=environment,
        validate_secrets=validate_secrets,
        apply_user_settings=apply_user_settings,
    )


def _enabled_venue_names(settings: config_models.Settings) -> list[str]:
    return sorted(venue.name for venue in settings.venues if venue.enabled)


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
def run_command(
    environment: str | None,
    apply_user_settings: bool,
    validate_secrets: bool,
) -> None:
    """Validate runtime configuration and print the active collection scope."""
    settings = _load_settings(
        environment=environment,
        apply_user_settings=apply_user_settings,
        validate_secrets=validate_secrets,
    )
    enabled_venues = _enabled_venue_names(settings)
    if not enabled_venues:
        raise click.ClickException("No enabled venues found for run command.")

    click.echo(
        "Run configuration ready "
        f"(environment={environment or 'default'}, venues={','.join(enabled_venues)})"
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
    settings = _load_settings(
        environment=environment,
        apply_user_settings=apply_user_settings,
        validate_secrets=False,
    )
    missing = config_secrets.missing_required_secrets(settings)
    enabled_venues = _enabled_venue_names(settings)

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
    """Show enabled and disabled venues under current config selection."""
    settings = _load_settings(
        environment=None,
        apply_user_settings=apply_user_settings,
        validate_secrets=False,
    )
    enabled = sorted(venue.name for venue in settings.venues if venue.enabled)
    disabled = sorted(venue.name for venue in settings.venues if not venue.enabled)

    click.echo(f"Enabled venues ({len(enabled)}): {', '.join(enabled) if enabled else 'none'}")
    click.echo(f"Disabled venues ({len(disabled)}): {', '.join(disabled) if disabled else 'none'}")


@main.command("backfill")
@click.option("--venue", required=True, help="Target venue (e.g. polymarket).")
@click.option("--instrument-id", required=True, help="Canonical instrument id to replay.")
@click.option("--start", required=True, help="Inclusive UTC start timestamp.")
@click.option("--end", required=True, help="Inclusive UTC end timestamp.")
def backfill_command(venue: str, instrument_id: str, start: str, end: str) -> None:
    """Submit a backfill request payload (execution engine is staged after D1)."""
    click.echo(
        "Backfill request captured "
        f"(venue={venue}, instrument_id={instrument_id}, start={start}, end={end})"
    )


@main.command("detect-gaps")
@click.option("--venue", default=None, help="Optional venue filter.")
@click.option("--start", default=None, help="Optional UTC start timestamp.")
@click.option("--end", default=None, help="Optional UTC end timestamp.")
def detect_gaps_command(venue: str | None, start: str | None, end: str | None) -> None:
    """Run gap-detection command wiring (detector implementation follows in later steps)."""
    click.echo(
        "Gap detection inputs accepted "
        f"(venue={venue or 'all'}, start={start or 'none'}, end={end or 'none'})"
    )


if __name__ == "__main__":
    main()
