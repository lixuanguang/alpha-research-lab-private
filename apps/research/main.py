"""Research CLI commands aligned with the R1-R6 stage contract."""

from __future__ import annotations

import json
from pathlib import Path

import click

import apps.research.commands.backtest as backtest_cmd
import apps.research.commands.build_dataset as build_dataset_cmd
import apps.research.commands.build_features as build_features_cmd
import apps.research.commands.common as cmd_common
import apps.research.commands.evaluate as evaluate_cmd
import apps.research.commands.optimize as optimize_cmd
import apps.research.commands.report as report_cmd
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
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=None,
    help="Global default storage root (overrides per-command --storage-root).",
)
@click.option(
    "--config",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to an optional YAML config override file used for validation and run hashing.",
)
@click.pass_context
def main(
    ctx: click.Context,
    output_format: str,
    output_dir: Path | None,
    config: Path | None,
) -> None:
    """Run research-plane scaffolding commands."""
    ctx.ensure_object(dict)
    ctx.obj["format"] = output_format
    ctx.obj["output_dir"] = output_dir.resolve() if output_dir is not None else None
    ctx.obj["config"] = cmd_common.load_config_reference(config) if config is not None else None


@main.result_callback()
@click.pass_context
def _emit_run_summary(ctx: click.Context, _result: object, **_kwargs: object) -> None:
    """Emit a standardized :class:`~alpha_core.research.run_summary.RunSummary` block.

    Subcommands store a :class:`RunSummary` instance at
    ``ctx.obj["_run_summary"]`` when they want to emit one.  This callback
    reads that key after every subcommand exits, formatting the summary
    according to the active ``--format`` option (``text`` or ``json``).
    Nothing is emitted if the key is absent (e.g. plan-only or failed runs
    that already raised :class:`~click.ClickException`).
    """
    obj = ctx.obj or {}
    summary: RunSummary | None = obj.get("_run_summary")
    if summary is None:
        return
    fmt = obj.get("format", "text")
    if fmt == "json":
        click.echo(summary.as_json_str())
    else:
        click.echo(summary.as_text())


main.add_command(build_dataset_cmd.build_dataset_command)
main.add_command(build_features_cmd.build_features_command)
main.add_command(backtest_cmd.backtest_command)
main.add_command(evaluate_cmd.evaluate_command)
main.add_command(report_cmd.report_command)
main.add_command(optimize_cmd.optimize_command)


if __name__ == "__main__":
    main()
