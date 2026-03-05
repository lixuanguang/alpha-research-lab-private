"""Live-system CLI commands for scaffold runtime control."""

from __future__ import annotations

from pathlib import Path

import click

import apps.live_system.runtime as live_runtime


@click.group()
def main() -> None:
    """Run live-system scaffolding commands."""


@main.command("run")
@click.option(
    "--instrument",
    "instruments",
    multiple=True,
    help="Canonical instrument ids to include in the scaffold cycle (repeat flag).",
)
@click.option(
    "--cycles",
    type=int,
    default=1,
    show_default=True,
    help="Number of strategy cycles to simulate.",
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
    help="Materialize run artifacts or only emit a validated execution plan.",
)
def run_command(
    instruments: tuple[str, ...],
    cycles: int,
    storage_root: Path,
    execute: bool,
) -> None:
    """Plan or materialize a live runtime scaffold cycle."""
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

    click.echo(
        f"status={outcome.status} run_id={outcome.run_id} "
        f"orders={outcome.orders_emitted} cycles={outcome.cycles}"
    )
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
            f"orders={outcome.orders_emitted} manifest={outcome.manifest_path}"
        )


if __name__ == "__main__":
    main()
