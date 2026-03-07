"""evaluate command — computes financial and PM metrics from backtest artifacts.

Wiring
------
Use ``main.add_command(evaluate_command)`` in ``apps/research/main.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

import alpha_core.research.evaluate_runner as evaluate_runner_mod
import apps.research.commands.common as cmd_common
import apps.research.runtime as research_runtime


def make_evaluate_runner(storage_root: Path) -> evaluate_runner_mod.EvaluateRunner:
    """Construct an :class:`EvaluateRunner` wired to *storage_root*.

    Callers in tests can monkeypatch this function.
    """
    return evaluate_runner_mod.EvaluateRunner(storage_root)


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
    fmt = cmd_common.get_output_format(ctx)
    payload = cmd_common.build_run_payload(ctx, {
        "backtest_run_id": backtest_run_id,
        "metrics_profile": metrics_profile,
    })

    if not execute:
        outcome = research_runtime.run_stage(
            research_runtime.ResearchStageRequest(
                run_type="evaluate",
                payload=payload,
                storage_root=resolved_root,
                execute=False,
                parent_run_id=backtest_run_id,
            )
        )
        cmd_common.emit_outcome(outcome, fmt)
        return

    try:
        runner = make_evaluate_runner(resolved_root)
        manifest = runner.build(
            backtest_run_id,
            metrics_profile=metrics_profile,  # type: ignore[arg-type]
            config_payload=payload,
            parent_run_id=backtest_run_id,
        )
    except evaluate_runner_mod.EvaluateRunError as exc:
        raise click.ClickException(str(exc)) from exc

    _emit_manifest_outcome(manifest, fmt)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _emit_manifest_outcome(
    manifest: evaluate_runner_mod.EvaluateManifest,
    fmt: cmd_common.OutputFormat,
) -> None:
    if fmt == "json":
        data: dict[str, Any] = {
            "run_type": "evaluate",
            "status": "materialized",
            "run_id": manifest.run_id,
            "backtest_run_id": manifest.backtest_run_id,
            "metrics_profile": manifest.metrics_profile,
            "built_at": manifest.built_at.isoformat(),
            "metrics": manifest.metrics,
        }
        click.echo(json.dumps(data, indent=2))
    else:
        click.echo(
            f"run_type=evaluate  status=materialized  run_id={manifest.run_id}  "
            f"profile={manifest.metrics_profile}"
        )
        for key, value in manifest.metrics.items():
            click.echo(f"  {key}={value}")


__all__ = ["evaluate_command", "make_evaluate_runner"]
