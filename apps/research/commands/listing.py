"""List existing research artifacts with stable JSON/text output."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import click
from pydantic import BaseModel

import alpha_core.research.artifact_paths as artifact_paths
import alpha_core.research.backtest_runner as backtest_runner_mod
import alpha_core.research.dataset_builder_io as dataset_builder_io
import alpha_core.research.feature_runner as feature_runner_mod
import alpha_core.research.manifest as manifest_mod
import apps.research.commands.common as cmd_common

ModelT = TypeVar("ModelT", bound=BaseModel)


@click.command("list-datasets")
@click.option(
    "--storage-root",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=Path("data"),
    show_default=True,
    help="Root directory for run artifacts.",
)
@click.pass_context
def list_datasets_command(ctx: click.Context, storage_root: Path) -> None:
    """List built gold datasets."""
    resolved_root = cmd_common.resolve_storage_root(ctx, storage_root)
    payload = [
        {
            "dataset_id": manifest.dataset_id,
            "name": manifest.config.name,
            "run_id": manifest.run_id,
            "built_at": manifest.built_at.isoformat(),
            "instrument_count": manifest.instrument_count,
            "date_range": [ts.isoformat() for ts in manifest.date_range],
            "row_counts": manifest.row_counts,
        }
        for manifest in dataset_builder_io.list_datasets(resolved_root / "gold" / "datasets")
    ]
    _emit_listing(
        fmt=cmd_common.get_output_format(ctx),
        payload=payload,
        render_text=lambda item: (
            f"{item['dataset_id']} name={item['name']} run_id={item['run_id']} "
            f"built_at={item['built_at']} instruments={item['instrument_count']}"
        ),
        empty_message="No datasets found.",
    )


@click.command("list-features")
@click.option(
    "--storage-root",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=Path("data"),
    show_default=True,
    help="Root directory for run artifacts.",
)
@click.pass_context
def list_features_command(ctx: click.Context, storage_root: Path) -> None:
    """List feature-build runs."""
    resolved_root = cmd_common.resolve_storage_root(ctx, storage_root)
    payload = [
        {
            "run_id": feature_manifest.run_id,
            "dataset_id": feature_manifest.dataset_id,
            "feature_set_version": feature_manifest.feature_set_version,
            "built_at": feature_manifest.built_at.isoformat(),
            "row_count": feature_manifest.row_count,
            "feature_count": feature_manifest.feature_count,
            "factor_pack_id": feature_manifest.factor_pack_id,
            "factor_pack_version": feature_manifest.factor_pack_version,
            "parent_run_id": run_manifest.parent_run_id,
        }
        for run_manifest, feature_manifest in _iter_stage_manifests(
            resolved_root,
            run_type="feature_build",
            artifact_key="feature_manifest",
            loader=feature_runner_mod.FeatureManifest.model_validate_json,
            fallback_filename="feature_manifest.json",
        )
    ]
    _emit_listing(
        fmt=cmd_common.get_output_format(ctx),
        payload=payload,
        render_text=lambda item: (
            f"{item['run_id']} dataset_id={item['dataset_id']} "
            f"feature_set_version={item['feature_set_version']} "
            f"rows={item['row_count']} features={item['feature_count']}"
        ),
        empty_message="No feature runs found.",
    )


@click.command("list-backtests")
@click.option(
    "--storage-root",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=Path("data"),
    show_default=True,
    help="Root directory for run artifacts.",
)
@click.pass_context
def list_backtests_command(ctx: click.Context, storage_root: Path) -> None:
    """List backtest runs."""
    resolved_root = cmd_common.resolve_storage_root(ctx, storage_root)
    payload = [
        {
            "run_id": backtest_manifest.run_id,
            "dataset_id": backtest_manifest.dataset_id,
            "feature_set_version": backtest_manifest.feature_set_version,
            "strategy_id": backtest_manifest.strategy_id,
            "engine": backtest_manifest.engine,
            "built_at": backtest_manifest.built_at.isoformat(),
            "trade_count": backtest_manifest.trade_count,
            "final_equity": backtest_manifest.final_equity,
            "total_return": backtest_manifest.total_return,
            "strategy_recipe_id": backtest_manifest.strategy_recipe_id,
            "strategy_recipe_version": backtest_manifest.strategy_recipe_version,
            "parent_run_id": run_manifest.parent_run_id,
        }
        for run_manifest, backtest_manifest in _iter_stage_manifests(
            resolved_root,
            run_type="backtest",
            artifact_key="backtest_manifest",
            loader=backtest_runner_mod.BacktestManifest.model_validate_json,
            fallback_filename="backtest_manifest.json",
        )
    ]
    _emit_listing(
        fmt=cmd_common.get_output_format(ctx),
        payload=payload,
        render_text=lambda item: (
            f"{item['run_id']} dataset_id={item['dataset_id']} "
            f"strategy_id={item['strategy_id']} engine={item['engine']} "
            f"trades={item['trade_count']} final_equity={item['final_equity']:.6f}"
        ),
        empty_message="No backtest runs found.",
    )


def _iter_stage_manifests(
    storage_root: Path,
    *,
    run_type: str,
    artifact_key: str,
    loader: Callable[[str], ModelT],
    fallback_filename: str,
) -> list[tuple[manifest_mod.RunManifest, ModelT]]:
    entries: list[tuple[manifest_mod.RunManifest, ModelT]] = []
    runs_root = storage_root / "runs"
    if not runs_root.exists():
        return entries

    for manifest_path in sorted(runs_root.glob("*/manifest.json")):
        run_manifest = manifest_mod.read_run_manifest(manifest_path)
        if run_manifest.run.run_type != run_type:
            continue
        stage_manifest_path = _resolve_stage_manifest_path(
            storage_root=storage_root,
            run_manifest=run_manifest,
            artifact_key=artifact_key,
            fallback_filename=fallback_filename,
        )
        entries.append(
            (
                run_manifest,
                loader(stage_manifest_path.read_text(encoding="utf-8")),
            )
        )

    entries.sort(
        key=lambda item: item[0].run.completed_at_utc or item[0].run.started_at_utc,
        reverse=True,
    )
    return entries


def _resolve_stage_manifest_path(
    *,
    storage_root: Path,
    run_manifest: manifest_mod.RunManifest,
    artifact_key: str,
    fallback_filename: str,
) -> Path:
    run_id = run_manifest.run.run_id
    registered = artifact_paths.resolve_registered_artifact_path(
        storage_root,
        run_id,
        run_manifest.artifacts.get(artifact_key),
    )
    if registered is not None:
        return registered

    fallback = artifact_paths.artifact_key_path(storage_root, run_id, fallback_filename)
    if not fallback.exists():
        raise click.ClickException(
            f"Run '{run_id}' is missing required artifact '{fallback_filename}'."
        )
    return fallback


def _emit_listing(
    *,
    fmt: cmd_common.OutputFormat,
    payload: list[dict[str, Any]],
    render_text: Callable[[dict[str, Any]], str],
    empty_message: str,
) -> None:
    if fmt == "json":
        click.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    if not payload:
        click.echo(empty_message)
        return
    for item in payload:
        click.echo(render_text(item))


__all__ = [
    "list_backtests_command",
    "list_datasets_command",
    "list_features_command",
]
