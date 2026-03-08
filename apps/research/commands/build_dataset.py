"""build-dataset command — materializes a gold dataset from silver Parquet.

Wiring
------
Use ``main.add_command(build_dataset_command)`` in ``apps/research/main.py``
to register this command under the ``research`` CLI group.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import click
from pydantic import ValidationError

import alpha_core.instruments.master as master_mod
import alpha_core.quality.gap_detector as gap_mod
import alpha_core.quality.partition_validator as pv_mod
import alpha_core.research.dataset as research_dataset
import alpha_core.research.dataset_builder as builder_mod
import alpha_core.research.universe as universe_mod
import alpha_core.storage.parquet_reader as parquet_reader_mod
import alpha_core.utils.time as time_utils
import apps.research.commands.common as cmd_common

# Conventional path for the persisted instrument master within a storage root.
_INSTRUMENTS_PARQUET = "instruments.parquet"


def make_dataset_builder(storage_root: Path) -> builder_mod.DatasetBuilder:
    """Construct a :class:`DatasetBuilder` wired to *storage_root*.

    Loads the market master from ``{storage_root}/instruments.parquet`` if it
    exists, so the universe manager reflects historically discovered markets.
    Callers in tests can monkeypatch this function to inject mocked dependencies.
    """
    reader = parquet_reader_mod.ParquetEventReader(storage_root)
    master = master_mod.MarketMaster()
    instruments_path = storage_root / _INSTRUMENTS_PARQUET
    if instruments_path.exists():
        master.restore(instruments_path)
    universe_mgr = universe_mod.UniverseManager(master)
    quality_validator = pv_mod.PartitionValidator.from_defaults(reader)
    gap_detector = gap_mod.GapDetector(reader)
    return builder_mod.DatasetBuilder(
        reader=reader,
        universe_mgr=universe_mgr,
        quality_validator=quality_validator,
        gap_detector=gap_detector,
        storage_root=storage_root,
    )


@click.command("build-dataset")
@click.option("--name", required=True, help="Dataset name.")
@click.option("--start", required=True, help="Inclusive UTC start timestamp (ISO 8601).")
@click.option("--end", required=True, help="Inclusive UTC end timestamp (ISO 8601).")
@click.option(
    "--venue",
    "venues",
    multiple=True,
    help="Venue filter (repeat flag for multiple). Defaults to all discovered venues.",
)
@click.option(
    "--event-type",
    "event_types",
    multiple=True,
    default=("trades", "ohlcv"),
    show_default=True,
    help="Event types to include.",
)
@click.option(
    "--require-quality-pass/--skip-quality-pass",
    default=True,
    show_default=True,
    help="Enforce partition-quality gates before materialization.",
)
@click.option(
    "--require-gap-free/--allow-gaps",
    default=True,
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
    "--parent-run-id",
    default=None,
    help="Optional upstream ingestion run id for lineage linking.",
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
    parent_run_id: str | None,
    storage_root: Path,
    execute: bool,
) -> None:
    """Plan or materialize a gold dataset from silver Parquet partitions.

    In plan-only mode (default) a run scaffold is emitted without writing any
    data.  Pass ``--execute`` to run the full build pipeline.

    Example — plan first, then execute:

    \b
        python -m apps.research.main build-dataset \\
            --name my_dataset \\
            --start 2026-01-01T00:00:00Z \\
            --end   2026-01-31T23:59:59Z \\
            --venue polymarket --event-type trades --event-type ohlcv \\
            --skip-quality-pass

        # Add --execute to materialize
    """
    if max_gap_hours <= 0:
        raise click.ClickException("`--max-gap-hours` must be > 0.")
    if not event_types:
        raise click.ClickException("At least one `--event-type` is required.")

    try:
        config = research_dataset.DatasetConfig(
            name=name,
            start=_parse_utc_dt(start),
            end=_parse_utc_dt(end),
            venues=list(venues) or None,
            event_types=list(event_types),
            require_quality_pass=require_quality_pass,
            require_gap_free=require_gap_free,
            max_gap_hours=max_gap_hours,
        )
    except ValidationError as exc:
        raise click.ClickException(str(exc)) from exc

    resolved_root = cmd_common.resolve_storage_root(ctx, storage_root)
    payload = cmd_common.build_run_payload(ctx, config.model_dump(mode="json"))

    if not execute:
        cmd_common.emit_planned_outcome(
            ctx,
            run_type="dataset_build",
            payload=payload,
        )
        return

    fmt = cmd_common.get_output_format(ctx)
    try:
        builder = make_dataset_builder(resolved_root)
        manifest = builder.build(
            config,
            config_payload=payload,
            parent_run_id=parent_run_id,
            session_id=cmd_common.get_session_id(ctx),
        )
    except builder_mod.DatasetBuildError as exc:
        raise click.ClickException(str(exc)) from exc

    if fmt == "json":
        click.echo(
            json.dumps(
                {
                    "run_type": "dataset_build",
                    "status": "materialized",
                    "run_id": manifest.run_id,
                    "dataset_id": manifest.dataset_id,
                    "name": manifest.config.name,
                    "built_at": manifest.built_at.isoformat(),
                    "row_counts": manifest.row_counts,
                    "instrument_count": manifest.instrument_count,
                    "date_range": [
                        manifest.date_range[0].isoformat(),
                        manifest.date_range[1].isoformat(),
                    ],
                },
                indent=2,
            )
        )
        return
    click.echo(
        f"run_type=dataset_build  status=materialized  "
        f"run_id={manifest.run_id}  "
        f"dataset_id={manifest.dataset_id}  "
        f"name={manifest.config.name}"
    )
    click.echo(
        f"rows={manifest.row_counts}  "
        f"instruments={manifest.instrument_count}  "
        f"built_at={manifest.built_at.isoformat()}"
    )


def _parse_utc_dt(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise click.ClickException(
            f"Invalid datetime '{value}' — expected ISO 8601 (e.g. 2026-01-01T00:00:00Z)."
        ) from exc
    return time_utils.ensure_utc(parsed)


__all__ = ["build_dataset_command", "make_dataset_builder"]
