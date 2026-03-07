"""Live-system CLI — strategy runtime startup, cycling, and status commands."""

from __future__ import annotations

import json
from pathlib import Path

import click

import apps.live_system.runtime as live_runtime
from alpha_core.research.run_summary import RunSummary


@click.group()
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Output format: human-readable text or machine-readable JSON.",
)
@click.pass_context
def main(ctx: click.Context, output_format: str) -> None:
    """Live system — run strategy cycles against live venue adapters.

    \b
    Commands:
      run     Start one or more live strategy cycles (or plan them).
      status  Show recent materialized live runs.
    """
    ctx.ensure_object(dict)
    ctx.obj["format"] = output_format


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
@click.pass_context
def run_command(
    ctx: click.Context,
    instruments: tuple[str, ...],
    cycles: int,
    strategy_id: str,
    storage_root: Path,
    execute: bool,
) -> None:
    """Start the live runtime for one or more strategy cycles.

    \b
    Examples:
      # Dry run — emit plan but write nothing
      python -m apps.live_system.main run --instrument p:abc:yes --plan-only

      # Execute two cycles and persist artifacts
      python -m apps.live_system.main run --instrument p:abc:yes --cycles 2 --execute
    """
    try:
        outcome = live_runtime.run_live_scaffold(
            live_runtime.LiveRunRequest(
                instruments=list(instruments),
                cycles=cycles,
                storage_root=storage_root,
                execute=execute,
            )
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    artifact_keys = (
        sorted(["config", "live_summary", "manifest"])
        if outcome.manifest_path is not None
        else []
    )
    summary = RunSummary(
        run_id=outcome.run_id,
        run_type="live",
        status=outcome.status,
        config_hash=outcome.config_hash,
        artifact_keys=artifact_keys,
        extra={
            "strategy_id": strategy_id,
            "cycles": outcome.cycles,
            "orders_emitted": outcome.orders_emitted,
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
