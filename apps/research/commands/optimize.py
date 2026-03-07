"""optimize command — grid/random parameter-sweep over the backtest/evaluate pipeline.

Wiring
------
Use ``main.add_command(optimize_command)`` in ``apps/research/main.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import click
from pydantic import ValidationError

import alpha_core.research.optimize_runner as optimize_runner_mod
import apps.research.commands.common as cmd_common


@click.command("optimize")
@click.option("--dataset-id", required=True, help="Gold dataset id the features were built from.")
@click.option(
    "--feature-set-version",
    default="v1",
    show_default=True,
    help="Feature set version tag used to identify the feature build.",
)
@click.option("--strategy-id", required=True, help="Base strategy identifier (e.g. 'zscore_v1').")
@click.option(
    "--feature-run-id",
    required=False,
    default=None,
    help="Feature-build run id whose features.parquet is consumed. Required with --execute.",
)
@click.option(
    "--search",
    "search_mode",
    type=click.Choice(["grid", "random"]),
    default="grid",
    show_default=True,
    help=(
        "Search mode. 'grid' exhausts the cartesian product of parameter_space values; "
        "'random' samples uniformly using --seed."
    ),
)
@click.option(
    "--objective",
    default="sharpe_ratio",
    show_default=True,
    help=(
        "Metric to optimise. Must be a key in the evaluation manifest metrics, "
        "e.g. 'sharpe_ratio', 'total_return', 'win_rate'."
    ),
)
@click.option(
    "--objective-minimize/--objective-maximize",
    default=False,
    show_default=True,
    help="Minimise the objective instead of maximising it.",
)
@click.option(
    "--max-trials",
    type=int,
    default=20,
    show_default=True,
    help="Maximum number of trials to evaluate.",
)
@click.option(
    "--top-n",
    type=int,
    default=5,
    show_default=True,
    help="Number of top feasible trials to include in the leaderboard artifact.",
)
@click.option(
    "--seed",
    type=int,
    default=42,
    show_default=True,
    help="RNG seed for reproducible random search.",
)
@click.option(
    "--threshold",
    "threshold_values",
    multiple=True,
    type=float,
    default=(1.5,),
    show_default=True,
    help="Candidate threshold values for the parameter sweep (repeat flag for multiple).",
)
@click.option(
    "--target-weight",
    "target_weight_values",
    multiple=True,
    type=float,
    default=(0.02,),
    show_default=True,
    help="Candidate target_weight values (repeat flag for multiple).",
)
@click.option(
    "--starting-cash",
    "starting_cash_values",
    multiple=True,
    type=float,
    default=(100_000.0,),
    show_default=True,
    help="Candidate starting_cash values (repeat flag for multiple).",
)
@click.option(
    "--min-trade-count",
    type=float,
    default=0.0,
    show_default=True,
    help="Constraint: minimum trade_count for a trial to be considered feasible.",
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
    help="Materialise optimization artifacts or only emit a validated execution plan.",
)
@click.pass_context
def optimize_command(
    ctx: click.Context,
    dataset_id: str,
    feature_set_version: str,
    strategy_id: str,
    feature_run_id: str | None,
    search_mode: str,
    objective: str,
    objective_minimize: bool,
    max_trials: int,
    top_n: int,
    seed: int,
    threshold_values: tuple[float, ...],
    target_weight_values: tuple[float, ...],
    starting_cash_values: tuple[float, ...],
    min_trade_count: float,
    storage_root: Path,
    execute: bool,
) -> None:
    """Plan or execute a parameter-sweep optimization over backtest/evaluate.

    Sweeps the given parameter ranges, evaluates each trial, and persists a
    trial registry, leaderboard, and best-run manifest reference.

    Examples — grid sweep over thresholds, then execute:

    \b
        python -m apps.research.main optimize \\
            --dataset-id <dataset_id> \\
            --strategy-id zscore_v1 \\
            --feature-run-id <feature_run_id> \\
            --threshold 1.0 --threshold 1.5 --threshold 2.0 \\
            --target-weight 0.01 --target-weight 0.02 \\
            --search grid --max-trials 20 \\
            --objective sharpe_ratio \\
            --execute

    Random search over larger space:

    \b
        python -m apps.research.main optimize \\
            --dataset-id <dataset_id> \\
            --strategy-id zscore_v1 \\
            --feature-run-id <feature_run_id> \\
            --threshold 0.5 --threshold 1.0 --threshold 1.5 --threshold 2.0 \\
            --target-weight 0.01 --target-weight 0.02 --target-weight 0.05 \\
            --search random --seed 42 --max-trials 6 \\
            --execute
    """
    if max_trials <= 0:
        raise click.ClickException("`--max-trials` must be > 0.")
    if top_n <= 0:
        raise click.ClickException("`--top-n` must be > 0.")

    parameter_space: dict[str, list[float]] = {}
    if threshold_values:
        parameter_space["threshold"] = list(threshold_values)
    if target_weight_values:
        parameter_space["target_weight"] = list(target_weight_values)
    if starting_cash_values:
        parameter_space["starting_cash"] = list(starting_cash_values)

    constraints: dict[str, float] = {}
    if min_trade_count > 0:
        constraints["trade_count"] = min_trade_count

    try:
        config = optimize_runner_mod.OptimizeConfig(
            dataset_id=dataset_id,
            feature_set_version=feature_set_version,
            strategy_id=strategy_id,
            search_mode=search_mode,  # type: ignore[arg-type]
            parameter_space=parameter_space,
            objective=objective,
            objective_minimize=objective_minimize,
            max_trials=max_trials,
            top_n=top_n,
            seed=seed,
            constraints=constraints,
        )
    except ValidationError as exc:
        raise click.ClickException(str(exc)) from exc

    resolved_root = cmd_common.resolve_storage_root(ctx, storage_root)
    payload = cmd_common.build_run_payload(ctx, config.model_dump(mode="json"))

    if not execute:
        cmd_common.emit_planned_outcome(
            ctx,
            run_type="optimize",
            payload=payload,
        )
        return

    fmt = cmd_common.get_output_format(ctx)
    if feature_run_id is None:
        raise click.ClickException(
            "`--feature-run-id` is required in --execute mode. "
            "Pass the run id from a completed build-features run."
        )

    try:
        runner = optimize_runner_mod.OptimizeRunner(resolved_root)
        manifest = runner.run(
            config,
            feature_run_id=feature_run_id,
            config_payload=payload,
            parent_run_id=feature_run_id,
            session_id=cmd_common.get_session_id(ctx),
        )
    except optimize_runner_mod.OptimizeRunError as exc:
        raise click.ClickException(str(exc)) from exc

    if fmt == "json":
        click.echo(
            json.dumps(
                {
                    "run_type": "optimize",
                    "status": "materialized",
                    "run_id": manifest.run_id,
                    "dataset_id": manifest.dataset_id,
                    "feature_set_version": manifest.feature_set_version,
                    "strategy_id": manifest.strategy_id,
                    "search_mode": manifest.search_mode,
                    "objective": manifest.objective,
                    "total_trials": manifest.total_trials,
                    "feasible_trials": manifest.feasible_trials,
                    "best_backtest_run_id": manifest.best_backtest_run_id,
                    "best_objective_value": manifest.best_objective_value,
                    "built_at": manifest.built_at.isoformat(),
                },
                indent=2,
            )
        )
        return

    click.echo(
        f"run_type=optimize  status=materialized  run_id={manifest.run_id}"
    )
    click.echo(
        f"trials={manifest.total_trials}  feasible={manifest.feasible_trials}  "
        f"objective={manifest.objective}"
    )
    if manifest.best_objective_value is not None:
        click.echo(
            f"best_value={manifest.best_objective_value:.4f}  "
            f"best_run={manifest.best_backtest_run_id}"
        )

__all__ = ["optimize_command"]
