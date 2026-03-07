"""build-features command — computes a versioned feature matrix from a gold dataset.

Wiring
------
Use ``main.add_command(build_features_command)`` in ``apps/research/main.py``
to register this command under the ``research`` CLI group.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click
from pydantic import ValidationError

import alpha_core.research.feature_runner as feature_runner_mod
import apps.research.commands.common as cmd_common
import apps.research.runtime as research_runtime


def make_feature_runner(storage_root: Path) -> feature_runner_mod.FeatureRunner:
    """Construct a :class:`FeatureRunner` wired to *storage_root*.

    Callers in tests can monkeypatch this function to inject mocked runners.
    """
    return feature_runner_mod.FeatureRunner(storage_root)


@click.command("build-features")
@click.option("--dataset-id", required=True, help="Gold dataset id or name to build features from.")
@click.option(
    "--feature-set-version",
    default="v1",
    show_default=True,
    help="Monotonic version tag for this feature set (e.g. 'v1', 'v2').",
)
@click.option(
    "--lookback-bars",
    type=int,
    default=200,
    show_default=True,
    help="Rolling window size used by all time-series feature primitives.",
)
@click.option("--parent-run-id", default=None, help="Optional upstream dataset run id for lineage.")
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
    help="Materialize feature artifacts or only emit a validated execution plan.",
)
@click.pass_context
def build_features_command(
    ctx: click.Context,
    dataset_id: str,
    feature_set_version: str,
    lookback_bars: int,
    parent_run_id: str | None,
    storage_root: Path,
    execute: bool,
) -> None:
    """Plan or materialize a versioned feature matrix from a gold dataset.

    In plan-only mode (default) a run scaffold is emitted without writing any
    data.  Pass ``--execute`` to run the full feature-build pipeline.

    Example — plan first, then execute:

    \b
        python -m apps.research.main build-features \\
            --dataset-id <dataset_id> \\
            --feature-set-version v1 \\
            --lookback-bars 200

        # Add --execute to materialize
    """
    if lookback_bars <= 0:
        raise click.ClickException("`--lookback-bars` must be > 0.")

    try:
        config = feature_runner_mod.FeatureConfig(
            dataset_id=dataset_id,
            feature_set_version=feature_set_version,
            lookback_bars=lookback_bars,
        )
    except ValidationError as exc:
        raise click.ClickException(str(exc)) from exc

    resolved_root = cmd_common.resolve_storage_root(ctx, storage_root)
    fmt = cmd_common.get_output_format(ctx)
    payload = cmd_common.build_run_payload(ctx, config.model_dump(mode="json"))

    if not execute:
        outcome = research_runtime.run_stage(
            research_runtime.ResearchStageRequest(
                run_type="feature_build",
                payload=payload,
                storage_root=resolved_root,
                execute=False,
                parent_run_id=parent_run_id,
            )
        )
        cmd_common.emit_outcome(outcome, fmt)
        return

    try:
        runner = make_feature_runner(resolved_root)
        manifest = runner.build(config, config_payload=payload, parent_run_id=parent_run_id)
    except feature_runner_mod.FeatureRunError as exc:
        raise click.ClickException(str(exc)) from exc

    _emit_manifest_outcome(manifest, fmt)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _emit_manifest_outcome(
    manifest: feature_runner_mod.FeatureManifest,
    fmt: cmd_common.OutputFormat,
) -> None:
    """Print a feature build outcome summary to stdout."""
    if fmt == "json":
        data: dict[str, Any] = {
            "run_type": "feature_build",
            "status": "materialized",
            "run_id": manifest.run_id,
            "dataset_id": manifest.dataset_id,
            "feature_set_version": manifest.feature_set_version,
            "built_at": manifest.built_at.isoformat(),
            "row_count": manifest.row_count,
            "feature_count": manifest.feature_count,
            "feature_names": manifest.feature_names,
        }
        click.echo(json.dumps(data, indent=2))
    else:
        click.echo(
            f"run_type=feature_build  status=materialized  "
            f"run_id={manifest.run_id}  feature_set_version={manifest.feature_set_version}"
        )
        click.echo(
            f"dataset_id={manifest.dataset_id}  "
            f"rows={manifest.row_count}  features={manifest.feature_count}  "
            f"built_at={manifest.built_at.isoformat()}"
        )


__all__ = ["build_features_command", "make_feature_runner"]
