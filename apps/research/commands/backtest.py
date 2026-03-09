"""backtest command — event-driven simulation over gold feature artifacts.

Wiring
------
Use ``main.add_command(backtest_command)`` in ``apps/research/main.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import click
from pydantic import ValidationError

import alpha_core.research.backtest_runner as backtest_runner_mod
import apps.research.commands.common as cmd_common


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
    "--strategy-recipe",
    "strategy_recipe_id",
    default=None,
    help="Strategy-recipe ID to resolve, validate, and apply during simulation.",
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
    strategy_recipe_id: str | None,
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

    resolved_recipe = None
    strategy_params: dict[str, float] = {}
    fee_bps = 0.0
    slippage_bps = 0.0
    max_position_pct = None
    if strategy_recipe_id is not None:
        try:
            resolved_recipe = backtest_runner_mod.resolve_strategy_recipe(strategy_recipe_id)
        except backtest_runner_mod.BacktestRunError as exc:
            raise click.ClickException(str(exc)) from exc
        if resolved_recipe is None:
            raise click.ClickException(
                f"Strategy recipe '{strategy_recipe_id}' could not be resolved."
            )
        strategy_params = backtest_runner_mod.normalize_recipe_strategy_params(
            resolved_recipe.strategy_params
        )
        fee_bps = resolved_recipe.execution_template.fee_bps
        slippage_bps = resolved_recipe.execution_template.slippage_bps
        max_position_pct = resolved_recipe.risk_template.max_position_pct

    try:
        config = backtest_runner_mod.BacktestConfig(
            dataset_id=dataset_id,
            feature_set_version=feature_set_version,
            strategy_id=strategy_id,
            engine=cast(backtest_runner_mod.EngineType, engine),
            starting_cash=starting_cash,
            strategy_recipe_id=strategy_recipe_id,
            strategy_recipe_version=(
                resolved_recipe.version if resolved_recipe is not None else None
            ),
            strategy_params=strategy_params,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            max_position_pct=max_position_pct,
        )
    except ValidationError as exc:
        raise click.ClickException(str(exc)) from exc

    resolved_root = cmd_common.resolve_storage_root(ctx, storage_root)
    payload = cmd_common.build_run_payload(ctx, config.model_dump(mode="json"))

    if not execute:
        cmd_common.emit_planned_outcome(
            ctx,
            run_type="backtest",
            payload=payload,
        )
        return

    fmt = cmd_common.get_output_format(ctx)
    try:
        runner = backtest_runner_mod.BacktestRunner(resolved_root)
        manifest = runner.build(
            config,
            config_payload=payload,
            parent_run_id=parent_run_id,
            session_id=cmd_common.get_session_id(ctx),
        )
    except backtest_runner_mod.BacktestRunError as exc:
        raise click.ClickException(str(exc)) from exc

    cmd_common.emit_materialized_summary(
        storage_root=resolved_root,
        run_id=manifest.run_id,
        extra={
            "dataset_id": manifest.dataset_id,
            "feature_set_version": manifest.feature_set_version,
            "strategy_id": manifest.strategy_id,
            "engine": manifest.engine,
            "built_at": manifest.built_at.isoformat(),
            "trade_count": manifest.trade_count,
            "final_equity": manifest.final_equity,
            "total_return": manifest.total_return,
        },
        fmt=fmt,
    )


__all__ = ["backtest_command"]
