"""Research CLI commands aligned with the R1-R6 stage contract."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import click

import alpha_core.research.dataset as research_dataset
import alpha_core.utils.time as time_utils
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
    type=click.Path(path_type=None, file_okay=False, dir_okay=True),
    default=None,
    help="Global default storage root (overrides per-command --storage-root).",
)
@click.option(
    "--config",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=None),
    default=None,
    help="Path to an optional YAML config override file.",
)
@click.pass_context
def main(
    ctx: click.Context,
    output_format: str,
    output_dir: str | None,
    config: str | None,
) -> None:
    """Run research-plane scaffolding commands."""
    ctx.ensure_object(dict)
    ctx.obj["format"] = output_format
    ctx.obj["output_dir"] = output_dir
    ctx.obj["config"] = config


@main.command("build-dataset")
@click.option("--name", required=True, help="Dataset name.")
@click.option("--start", required=True, help="Inclusive UTC start timestamp (ISO 8601).")
@click.option("--end", required=True, help="Inclusive UTC end timestamp (ISO 8601).")
@click.option(
    "--venue",
    "venues",
    multiple=True,
    help="Optional venue filter (repeat flag). Defaults to all discovered venues.",
)
@click.option(
    "--event-type",
    "event_types",
    multiple=True,
    default=("trades", "ohlcv"),
    show_default=True,
    help="Event types to include in the dataset.",
)
@click.option(
    "--require-quality-pass/--skip-quality-pass",
    default=True,
    show_default=True,
    help="Enforce partition-quality gates before dataset materialization.",
)
@click.option(
    "--require-gap-free/--allow-gaps",
    default=False,
    show_default=True,
    help="Fail when detected data gaps exceed --max-gap-hours.",
)
@click.option(
    "--max-gap-hours",
    type=float,
    default=24.0,
    show_default=True,
    help="Maximum tolerated gap duration (hours) when --require-gap-free is enabled.",
)
@click.option(
    "--storage-root",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=Path("data"),
    show_default=True,
    help="Root directory for run artifacts and gold datasets.",
)
@click.option(
    "--execute/--plan-only",
    default=False,
    show_default=True,
    help="Materialize run artifacts or only emit a validated execution plan.",
)
@click.pass_context
def build_dataset_command(
    ctx: click.Context,
    name: str,
    start: str,
    end: str,
    venues: tuple[str, ...],
    event_types: tuple[str, ...],
    require_quality_pass: bool,
    require_gap_free: bool,
    max_gap_hours: float,
    storage_root: Path,
    execute: bool,
) -> None:
    """Plan or materialize a dataset-build run scaffold."""
    if max_gap_hours <= 0:
        raise click.ClickException("`--max-gap-hours` must be > 0.")
    if not event_types:
        raise click.ClickException("At least one `--event-type` is required.")

    config = research_dataset.DatasetConfig(
        name=name,
        start=_parse_utc_datetime(start),
        end=_parse_utc_datetime(end),
        venues=list(venues) or None,
        event_types=list(event_types),
        require_quality_pass=require_quality_pass,
        require_gap_free=require_gap_free,
        max_gap_hours=max_gap_hours,
    )
    outcome = research_runtime.run_stage(
        research_runtime.ResearchStageRequest(
            run_type="dataset_build",
            payload=config.model_dump(mode="json"),
            storage_root=storage_root,
            execute=execute,
        )
    )
    cmd_common.emit_outcome(outcome, cmd_common.get_output_format(ctx))


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
    outcome = research_runtime.run_stage(
        research_runtime.ResearchStageRequest(
            run_type="feature_build",
            payload=payload,
            storage_root=storage_root,
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
    outcome = research_runtime.run_stage(
        research_runtime.ResearchStageRequest(
            run_type="backtest",
            payload=payload,
            storage_root=storage_root,
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
    outcome = research_runtime.run_stage(
        research_runtime.ResearchStageRequest(
            run_type="evaluate",
            payload=payload,
            storage_root=storage_root,
            execute=execute,
            parent_run_id=backtest_run_id,
        )
    )
    cmd_common.emit_outcome(outcome, cmd_common.get_output_format(ctx))


@main.command("report")
@click.option("--evaluation-run-id", required=True, help="Evaluation run id to report.")
@click.option(
    "--format",
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
    outcome = research_runtime.run_stage(
        research_runtime.ResearchStageRequest(
            run_type="evaluate",
            payload=payload,
            storage_root=storage_root,
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
    outcome = research_runtime.run_stage(
        research_runtime.ResearchStageRequest(
            run_type="optimize",
            payload=payload,
            storage_root=storage_root,
            execute=execute,
            parent_run_id=parent_run_id,
        )
    )
    cmd_common.emit_outcome(outcome, cmd_common.get_output_format(ctx))


def _parse_utc_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise click.ClickException(f"Invalid datetime '{value}' (expected ISO 8601).") from exc
    return time_utils.ensure_utc(parsed)


if __name__ == "__main__":
    main()
