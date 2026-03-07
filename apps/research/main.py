"""Research CLI commands aligned with the R1-R6 stage contract."""

from __future__ import annotations

from pathlib import Path

import click

import apps.research.commands.build_dataset as build_dataset_cmd
import apps.research.commands.common as cmd_common
import apps.research.runtime as research_runtime


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
    ctx.obj["config"] = (
        cmd_common.load_config_reference(config)
        if config is not None
        else None
    )


main.add_command(build_dataset_cmd.build_dataset_command)


@main.command("build-features")
@click.option("--dataset-id", required=True, help="Dataset id or dataset name.")
@click.option("--feature-set", required=True, help="Feature set identifier.")
@click.option(
    "--lookback-bars",
    type=int,
    default=200,
    show_default=True,
    help="Lookback bars used by rolling feature primitives.",
)
@click.option("--parent-run-id", default=None, help="Optional upstream dataset run id.")
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
@click.pass_context
def build_features_command(
    ctx: click.Context,
    dataset_id: str,
    feature_set: str,
    lookback_bars: int,
    parent_run_id: str | None,
    storage_root: Path,
    execute: bool,
) -> None:
    """Plan or materialize a feature-build run scaffold."""
    if lookback_bars <= 0:
        raise click.ClickException("`--lookback-bars` must be > 0.")
    payload: dict[str, object] = {
        "dataset_id": dataset_id,
        "feature_set": feature_set,
        "lookback_bars": lookback_bars,
    }
    runtime_payload = cmd_common.build_run_payload(ctx, payload)
    outcome = research_runtime.run_stage(
        research_runtime.ResearchStageRequest(
            run_type="feature_build",
            payload=runtime_payload,
            storage_root=cmd_common.resolve_storage_root(ctx, storage_root),
            execute=execute,
            parent_run_id=parent_run_id,
        )
    )
    cmd_common.emit_outcome(outcome, cmd_common.get_output_format(ctx))


@main.command("backtest")
@click.option("--dataset-id", required=True, help="Dataset id or dataset name.")
@click.option("--feature-set", required=True, help="Feature set identifier.")
@click.option("--strategy-id", required=True, help="Strategy identifier.")
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
    help="Initial cash used by the simulation scaffold.",
)
@click.option("--parent-run-id", default=None, help="Optional upstream feature-build run id.")
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
@click.pass_context
def backtest_command(
    ctx: click.Context,
    dataset_id: str,
    feature_set: str,
    strategy_id: str,
    engine: str,
    starting_cash: float,
    parent_run_id: str | None,
    storage_root: Path,
    execute: bool,
) -> None:
    """Plan or materialize a backtest run scaffold."""
    if starting_cash <= 0:
        raise click.ClickException("`--starting-cash` must be > 0.")
    payload: dict[str, object] = {
        "dataset_id": dataset_id,
        "feature_set": feature_set,
        "strategy_id": strategy_id,
        "engine": engine,
        "starting_cash": starting_cash,
    }
    runtime_payload = cmd_common.build_run_payload(ctx, payload)
    outcome = research_runtime.run_stage(
        research_runtime.ResearchStageRequest(
            run_type="backtest",
            payload=runtime_payload,
            storage_root=cmd_common.resolve_storage_root(ctx, storage_root),
            execute=execute,
            parent_run_id=parent_run_id,
        )
    )
    cmd_common.emit_outcome(outcome, cmd_common.get_output_format(ctx))


@main.command("evaluate")
@click.option("--backtest-run-id", required=True, help="Backtest run id to evaluate.")
@click.option(
    "--metrics-profile",
    type=click.Choice(["default", "pm_core", "microstructure", "minimal"]),
    default="pm_core",
    show_default=True,
    help="Named metrics set.",
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
@click.pass_context
def evaluate_command(
    ctx: click.Context,
    backtest_run_id: str,
    metrics_profile: str,
    storage_root: Path,
    execute: bool,
) -> None:
    """Plan or materialize an evaluation run scaffold."""
    payload: dict[str, object] = {
        "backtest_run_id": backtest_run_id,
        "metrics_profile": metrics_profile,
    }
    runtime_payload = cmd_common.build_run_payload(ctx, payload)
    outcome = research_runtime.run_stage(
        research_runtime.ResearchStageRequest(
            run_type="evaluate",
            payload=runtime_payload,
            storage_root=cmd_common.resolve_storage_root(ctx, storage_root),
            execute=execute,
            parent_run_id=backtest_run_id,
        )
    )
    cmd_common.emit_outcome(outcome, cmd_common.get_output_format(ctx))


@main.command("report")
@click.option("--evaluation-run-id", required=True, help="Evaluation run id to report.")
@click.option(
    "--report-format",
    "report_format",
    type=click.Choice(["json", "markdown"]),
    default="json",
    show_default=True,
    help="Rendered report format.",
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
@click.pass_context
def report_command(
    ctx: click.Context,
    evaluation_run_id: str,
    report_format: str,
    storage_root: Path,
    execute: bool,
) -> None:
    """Plan or materialize a report-generation scaffold run."""
    payload: dict[str, object] = {
        "evaluation_run_id": evaluation_run_id,
        "report_format": report_format,
    }
    runtime_payload = cmd_common.build_run_payload(ctx, payload)
    outcome = research_runtime.run_stage(
        research_runtime.ResearchStageRequest(
            run_type="report",
            payload=runtime_payload,
            storage_root=cmd_common.resolve_storage_root(ctx, storage_root),
            execute=execute,
            parent_run_id=evaluation_run_id,
        )
    )
    cmd_common.emit_outcome(outcome, cmd_common.get_output_format(ctx))


@main.command("optimize")
@click.option("--dataset-id", required=True, help="Dataset id or dataset name.")
@click.option("--feature-set", required=True, help="Feature set identifier.")
@click.option("--strategy-id", required=True, help="Strategy identifier.")
@click.option(
    "--search",
    type=click.Choice(["grid", "random"]),
    default="grid",
    show_default=True,
    help="Optimization search mode.",
)
@click.option(
    "--max-trials",
    type=int,
    default=20,
    show_default=True,
    help="Maximum optimization trials.",
)
@click.option("--objective", default="sharpe", show_default=True, help="Optimization objective.")
@click.option("--parent-run-id", default=None, help="Optional upstream run id.")
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
@click.pass_context
def optimize_command(
    ctx: click.Context,
    dataset_id: str,
    feature_set: str,
    strategy_id: str,
    search: str,
    max_trials: int,
    objective: str,
    parent_run_id: str | None,
    storage_root: Path,
    execute: bool,
) -> None:
    """Plan or materialize an optimization run scaffold."""
    if max_trials <= 0:
        raise click.ClickException("`--max-trials` must be > 0.")
    payload: dict[str, object] = {
        "dataset_id": dataset_id,
        "feature_set": feature_set,
        "strategy_id": strategy_id,
        "search": search,
        "max_trials": max_trials,
        "objective": objective,
    }
    runtime_payload = cmd_common.build_run_payload(ctx, payload)
    outcome = research_runtime.run_stage(
        research_runtime.ResearchStageRequest(
            run_type="optimize",
            payload=runtime_payload,
            storage_root=cmd_common.resolve_storage_root(ctx, storage_root),
            execute=execute,
            parent_run_id=parent_run_id,
        )
    )
    cmd_common.emit_outcome(outcome, cmd_common.get_output_format(ctx))


if __name__ == "__main__":
    main()
