"""Live-system CLI — strategy runtime startup, cycling, and status commands."""

from __future__ import annotations

from pathlib import Path

import click

import alpha_core.config.profiles as config_profiles
import alpha_core.research.manifest as manifest_mod
import alpha_core.research.run_summary as run_summary_mod
import apps.live_system.runtime as live_runtime


@click.group()
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Output format: human-readable text or machine-readable JSON.",
)
@click.option(
    "--profile",
    type=click.Choice(["dev", "research", "ci", "paper", "live"]),
    default=None,
    help="Runtime profile (dev/research/ci/paper/live). Overrides log level and safety flags.",
)
@click.pass_context
def main(ctx: click.Context, output_format: str, profile: str | None) -> None:
    """Live system — run strategy cycles against live venue adapters.

    \b
    Commands:
      run     Start one or more live strategy cycles (or plan them).
      status  Show recent materialized live runs.
    """
    ctx.ensure_object(dict)
    ctx.obj["format"] = output_format
    ctx.obj["profile"] = profile


@main.command("run")
@click.option(
    "--instrument",
    "instruments",
    multiple=True,
    help="Canonical instrument ids to include in the cycle (repeat flag).",
)
@click.option(
    "--cycles",
    type=int,
    default=1,
    show_default=True,
    help="Number of strategy cycles to run.",
)
@click.option(
    "--strategy-id",
    default="default",
    show_default=True,
    help="Strategy identifier label recorded in the run manifest.",
)
@click.option(
    "--storage-root",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=Path("data"),
    show_default=True,
    help="Root directory for run artifacts.",
)
@click.option(
    "--execute/--plan-only",
    default=False,
    show_default=True,
    help="Materialize run artifacts (--execute) or emit a validated plan (--plan-only).",
)
@click.option(
    "--real-money/--paper-money",
    default=False,
    show_default=True,
    help="Require the live profile before enabling real-money routing.",
)
@click.pass_context
def run_command(
    ctx: click.Context,
    instruments: tuple[str, ...],
    cycles: int,
    strategy_id: str,
    storage_root: Path,
    execute: bool,
    real_money: bool,
) -> None:
    """Start the live runtime for one or more strategy cycles.

    \b
    Examples:
      # Dry run — emit plan but write nothing
      python -m apps.live_system.main run --instrument p:abc:yes --plan-only

      # Execute two cycles and persist artifacts
      python -m apps.live_system.main run --instrument p:abc:yes --cycles 2 --execute
    """
    profile_name = (ctx.obj or {}).get("profile")
    active_profile = config_profiles.get_profile(profile_name) if profile_name is not None else None
    resolved_storage_root = (
        active_profile.storage_root
        if active_profile is not None and storage_root == Path("data")
        else storage_root
    )

    if execute:
        try:
            config_profiles.guard_execution(active_profile, context="live order submission")
            if real_money:
                if active_profile is None:
                    raise PermissionError("Real-money routing requires '--profile live'.")
                config_profiles.guard_real_money(
                    active_profile,
                    context="live real-money routing",
                )
        except PermissionError as exc:
            raise click.ClickException(str(exc)) from exc

    try:
        outcome = live_runtime.run_live_scaffold(
            live_runtime.LiveRunRequest(
                instruments=list(instruments),
                cycles=cycles,
                strategy_id=strategy_id,
                storage_root=resolved_storage_root,
                execute=execute,
            )
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    artifact_keys = []
    if outcome.manifest_path is not None:
        manifest = manifest_mod.read_run_manifest(outcome.manifest_path)
        artifact_keys = list(manifest.artifacts)
    summary = run_summary_mod.RunSummary(
        run_id=outcome.run_id,
        run_type="live",
        status=outcome.status,
        config_hash=outcome.config_hash,
        artifact_keys=artifact_keys,
        extra={
            "strategy_id": strategy_id,
            "cycles": outcome.cycles,
            "orders_emitted": outcome.orders_emitted,
            "real_money": real_money,
        },
    )

    fmt = (ctx.obj or {}).get("format", "text")
    if fmt == "json":
        click.echo(summary.as_json_str())
    else:
        click.echo(summary.as_text())
        if outcome.manifest_path is not None:
            click.echo(f"manifest={outcome.manifest_path}")


@main.command("status")
@click.option(
    "--storage-root",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=Path("data"),
    show_default=True,
    help="Root directory for run artifacts.",
)
@click.option(
    "--limit",
    type=int,
    default=5,
    show_default=True,
    help="Maximum number of recent live runs to display.",
)
def status_command(storage_root: Path, limit: int) -> None:
    """Show recent materialized live runs."""
    try:
        outcomes = live_runtime.list_recent_live_runs(storage_root, limit=limit)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    if not outcomes:
        click.echo("No live runs found.")
        return
    for outcome in outcomes:
        click.echo(
            f"run_id={outcome.run_id} status={outcome.status} "
            f"cycles={outcome.cycles} orders={outcome.orders_emitted} "
            f"manifest={outcome.manifest_path}"
        )


if __name__ == "__main__":
    main()
