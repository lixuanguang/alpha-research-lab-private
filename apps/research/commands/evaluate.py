"""evaluate command — computes financial and PM metrics from backtest artifacts.

Wiring
------
Use ``main.add_command(evaluate_command)`` in ``apps/research/main.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import click

import alpha_core.research.evaluate_runner as evaluate_runner_mod
import apps.research.commands.common as cmd_common


@click.command("evaluate")
@click.option("--backtest-run-id", required=True, help="Backtest run id to evaluate.")
@click.option(
    "--metrics-profile",
    type=click.Choice(["default", "pm_core", "microstructure", "minimal"]),
    default="pm_core",
    show_default=True,
    help="Named metrics preset.",
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
    help="Materialize evaluation artifacts or only emit a validated execution plan.",
)
@click.pass_context
def evaluate_command(
    ctx: click.Context,
    backtest_run_id: str,
    metrics_profile: str,
    storage_root: Path,
    execute: bool,
) -> None:
    """Plan or compute financial metrics from a completed backtest run.

    Example:

    \b
        python -m apps.research.main evaluate \\
            --backtest-run-id <backtest_run_id> \\
            --metrics-profile pm_core \\
            --execute
    """
    resolved_root = cmd_common.resolve_storage_root(ctx, storage_root)
    payload = cmd_common.build_run_payload(
        ctx,
        {
            "backtest_run_id": backtest_run_id,
            "metrics_profile": metrics_profile,
        },
    )

    if not execute:
        cmd_common.emit_planned_outcome(
            ctx,
            run_type="evaluate",
            payload=payload,
        )
        return

    fmt = cmd_common.get_output_format(ctx)
    try:
        runner = evaluate_runner_mod.EvaluateRunner(resolved_root)
        manifest = runner.build(
            backtest_run_id,
            metrics_profile=cast(evaluate_runner_mod.MetricsProfile, metrics_profile),
            config_payload=payload,
            parent_run_id=backtest_run_id,
            session_id=cmd_common.get_session_id(ctx),
        )
    except evaluate_runner_mod.EvaluateRunError as exc:
        raise click.ClickException(str(exc)) from exc

    cmd_common.emit_materialized_summary(
        storage_root=resolved_root,
        run_id=manifest.run_id,
        extra={
            "backtest_run_id": manifest.backtest_run_id,
            "metrics_profile": manifest.metrics_profile,
            "built_at": manifest.built_at.isoformat(),
            "metrics": manifest.metrics,
        },
        fmt=fmt,
    )


__all__ = ["evaluate_command"]
