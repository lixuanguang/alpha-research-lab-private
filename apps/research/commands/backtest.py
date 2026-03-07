"""backtest command — event-driven simulation over gold feature artifacts.

Wiring
------
Use ``main.add_command(backtest_command)`` in ``apps/research/main.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click
from pydantic import ValidationError

import alpha_core.research.backtest_runner as backtest_runner_mod
import apps.research.commands.common as cmd_common
import apps.research.runtime as research_runtime


def make_backtest_runner(storage_root: Path) -> backtest_runner_mod.BacktestRunner:
    """Construct a :class:`BacktestRunner` wired to *storage_root*.

    Callers in tests can monkeypatch this function.
    """
    return backtest_runner_mod.BacktestRunner(storage_root)


@click.command("backtest")
@click.option("--dataset-id", required=True, help="Gold dataset id the features were built from.")
@click.option(
    "--feature-set-version",
    default="v1",
    show_default=True,
    help="Feature set version tag used to identify the feature build.",
)
@click.option("--strategy-id", required=True, help="Strategy identifier tag for artifact labeling.")
@click.option(
    "--engine",
    type=click.Choice(["event", "vectorized"]),
    default="event",
    show_default=True,
    help="Backtest engine flavor.",
)
@click.option(
    "--starting-cash",
    type=float,
    default=100_000.0,
    show_default=True,
    help="Initial notional cash used by the simulation.",
)
@click.option(
    "--parent-run-id",
    required=False,
    default=None,
    help="Feature-build run id whose features.parquet is consumed. Required with --execute.",
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
    help="Materialize backtest artifacts or only emit a validated execution plan.",
)
@click.pass_context
def backtest_command(
    ctx: click.Context,
    dataset_id: str,
    feature_set_version: str,
    strategy_id: str,
    engine: str,
    starting_cash: float,
    parent_run_id: str | None,
    storage_root: Path,
    execute: bool,
) -> None:
    """Plan or run a strategy simulation over feature artifacts.

    Requires a completed build-features run (--parent-run-id) in execute mode.

    Example — plan first, then execute:

    \b
        python -m apps.research.main backtest \\
            --dataset-id <dataset_id> \\
            --strategy-id zscore_v1 \\
            --parent-run-id <feature_run_id> \\
            --execute
    """
    if starting_cash <= 0:
        raise click.ClickException("`--starting-cash` must be > 0.")

    try:
        config = backtest_runner_mod.BacktestConfig(
            dataset_id=dataset_id,
            feature_set_version=feature_set_version,
            strategy_id=strategy_id,
            engine=engine,
            starting_cash=starting_cash,
        )
    except ValidationError as exc:
        raise click.ClickException(str(exc)) from exc

    resolved_root = cmd_common.resolve_storage_root(ctx, storage_root)
    fmt = cmd_common.get_output_format(ctx)
    payload = cmd_common.build_run_payload(ctx, config.model_dump(mode="json"))

    if not execute:
        outcome = research_runtime.run_stage(
            research_runtime.ResearchStageRequest(
                run_type="backtest",
                payload=payload,
                storage_root=resolved_root,
                execute=False,
                parent_run_id=parent_run_id,
            )
        )
        cmd_common.emit_outcome(outcome, fmt)
        return

    try:
        runner = make_backtest_runner(resolved_root)
        manifest = runner.build(config, config_payload=payload, parent_run_id=parent_run_id)
    except backtest_runner_mod.BacktestRunError as exc:
        raise click.ClickException(str(exc)) from exc

    _emit_manifest_outcome(manifest, fmt)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _emit_manifest_outcome(
    manifest: backtest_runner_mod.BacktestManifest,
    fmt: cmd_common.OutputFormat,
) -> None:
    if fmt == "json":
        data: dict[str, Any] = {
            "run_type": "backtest",
            "status": "materialized",
            "run_id": manifest.run_id,
            "dataset_id": manifest.dataset_id,
            "feature_set_version": manifest.feature_set_version,
            "strategy_id": manifest.strategy_id,
            "engine": manifest.engine,
            "built_at": manifest.built_at.isoformat(),
            "trade_count": manifest.trade_count,
            "final_equity": manifest.final_equity,
            "total_return": manifest.total_return,
        }
        click.echo(json.dumps(data, indent=2))
    else:
        click.echo(
            f"run_type=backtest  status=materialized  run_id={manifest.run_id}  "
            f"strategy_id={manifest.strategy_id}"
        )
        click.echo(
            f"trades={manifest.trade_count}  "
            f"total_return={manifest.total_return:.4f}  "
            f"final_equity={manifest.final_equity:.2f}  "
            f"built_at={manifest.built_at.isoformat()}"
        )


__all__ = ["backtest_command", "make_backtest_runner"]
