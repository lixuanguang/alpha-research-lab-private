"""build-dataset command — materializes a gold dataset from silver Parquet.

Wiring
------
Use ``main.add_command(build_dataset_command)`` in ``apps/research/main.py``
to register this command under the ``research`` CLI group.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import click
from pydantic import ValidationError

import alpha_core.instruments.master as master_mod
import alpha_core.quality.gap_detector as gap_mod
import alpha_core.quality.partition_validator as pv_mod
import alpha_core.research.artifact_paths as artifact_paths
import alpha_core.research.dataset as research_dataset
import alpha_core.research.dataset_builder as builder_mod
import alpha_core.research.manifest as manifest_mod
import alpha_core.research.universe as universe_mod
import alpha_core.storage.handoff_manifest as handoff_mod
import alpha_core.storage.lineage as lineage_mod
import alpha_core.storage.parquet_reader as parquet_reader_mod
import alpha_core.utils.time as time_utils
import apps.research.commands.common as cmd_common

# Conventional path for the persisted instrument master within a storage root.
_INSTRUMENTS_PARQUET = "instruments.parquet"
_DEFAULT_EVENT_TYPES: tuple[str, ...] = ("trades", "ohlcv")


@dataclass(frozen=True)
class _ResolvedDatasetInvocation:
    config: research_dataset.DatasetConfig
    config_payload: dict[str, Any]
    parent_run_id: str | None
    extra_artifacts: dict[str, str]
    handoff_source_run_ids: tuple[str, ...]
    partition_refs_by_event_type: dict[str, list[str]]


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


def _resolve_dataset_invocation(
    *,
    ctx: click.Context,
    name: str,
    start: str | None,
    end: str | None,
    venues: tuple[str, ...],
    event_types: tuple[str, ...],
    require_quality_pass: bool,
    require_gap_free: bool,
    max_gap_hours: float,
    parent_run_id: str | None,
    handoff_manifest: str | None,
    storage_root: Path,
) -> _ResolvedDatasetInvocation:
    if handoff_manifest is None:
        config = _dataset_config_from_cli(
            name=name,
            start=start,
            end=end,
            venues=venues,
            event_types=event_types,
            require_quality_pass=require_quality_pass,
            require_gap_free=require_gap_free,
            max_gap_hours=max_gap_hours,
        )
        return _ResolvedDatasetInvocation(
            config=config,
            config_payload=cmd_common.build_run_payload(ctx, config.model_dump(mode="json")),
            parent_run_id=parent_run_id,
            extra_artifacts={},
            handoff_source_run_ids=(),
            partition_refs_by_event_type={},
        )

    _validate_handoff_cli_usage(
        start=start,
        end=end,
        venues=venues,
        event_types=event_types,
        parent_run_id=parent_run_id,
    )
    handoff_manifest_obj, handoff_path = _resolve_handoff_manifest(
        handoff_manifest,
        storage_root=storage_root,
    )
    if not handoff_manifest_obj.is_dataset_ready():
        raise click.ClickException(
            f"Handoff manifest '{handoff_manifest_obj.handoff_id}' is not dataset-ready."
        )
    partition_refs_by_event_type = _partition_refs_by_event_type(handoff_manifest_obj)
    config = research_dataset.DatasetConfig(
        name=name,
        start=handoff_manifest_obj.window_start_utc,
        end=handoff_manifest_obj.window_end_utc,
        venues=[handoff_manifest_obj.venue],
        event_types=handoff_manifest_obj.event_types,
        require_quality_pass=require_quality_pass,
        require_gap_free=require_gap_free,
        max_gap_hours=max_gap_hours,
    )
    stage_payload = config.model_dump(mode="json")
    stage_payload["handoff_id"] = handoff_manifest_obj.handoff_id
    stage_payload["handoff_source_run_ids"] = list(handoff_manifest_obj.source_run_ids)
    resolved_parent_run_id = (
        handoff_manifest_obj.source_run_ids[0]
        if len(handoff_manifest_obj.source_run_ids) == 1
        else None
    )
    return _ResolvedDatasetInvocation(
        config=config,
        config_payload=cmd_common.build_run_payload(ctx, stage_payload),
        parent_run_id=resolved_parent_run_id,
        extra_artifacts={
            "handoff_id": handoff_manifest_obj.handoff_id,
            "handoff_manifest": str(handoff_path),
        },
        handoff_source_run_ids=tuple(handoff_manifest_obj.source_run_ids),
        partition_refs_by_event_type=partition_refs_by_event_type,
    )


def _dataset_config_from_cli(
    *,
    name: str,
    start: str | None,
    end: str | None,
    venues: tuple[str, ...],
    event_types: tuple[str, ...],
    require_quality_pass: bool,
    require_gap_free: bool,
    max_gap_hours: float,
) -> research_dataset.DatasetConfig:
    if start is None or end is None:
        raise click.ClickException(
            "`--start` and `--end` are required when no handoff is provided."
        )
    try:
        return research_dataset.DatasetConfig(
            name=name,
            start=_parse_utc_dt(start),
            end=_parse_utc_dt(end),
            venues=list(venues) or None,
            event_types=list(event_types) or list(_DEFAULT_EVENT_TYPES),
            require_quality_pass=require_quality_pass,
            require_gap_free=require_gap_free,
            max_gap_hours=max_gap_hours,
        )
    except ValidationError as exc:
        raise click.ClickException(str(exc)) from exc


def _validate_handoff_cli_usage(
    *,
    start: str | None,
    end: str | None,
    venues: tuple[str, ...],
    event_types: tuple[str, ...],
    parent_run_id: str | None,
) -> None:
    if start is not None or end is not None:
        raise click.ClickException(
            "`--handoff-manifest` cannot be combined with `--start` or `--end`."
        )
    if venues:
        raise click.ClickException("`--handoff-manifest` cannot be combined with `--venue`.")
    if event_types:
        raise click.ClickException("`--handoff-manifest` cannot be combined with `--event-type`.")
    if parent_run_id is not None:
        raise click.ClickException(
            "`--handoff-manifest` cannot be combined with `--parent-run-id`."
        )


def _resolve_handoff_manifest(
    handoff_ref: str,
    *,
    storage_root: Path,
) -> tuple[handoff_mod.DatasetHandoffManifest, Path]:
    candidate_path = Path(handoff_ref)
    if candidate_path.exists():
        return _load_handoff_manifest_file(candidate_path)

    handoff_store = handoff_mod.HandoffManifestStore(storage_root)
    stored_manifest = handoff_store.load(handoff_ref)
    if stored_manifest is not None:
        return stored_manifest, _handoff_manifest_path(storage_root, handoff_ref)

    run_manifest_path = artifact_paths.run_manifest_path(storage_root, handoff_ref)
    if run_manifest_path.exists():
        run_manifest = manifest_mod.read_run_manifest(run_manifest_path)
        handoff_path = run_manifest.artifacts.get("handoff_manifest")
        if handoff_path is None:
            raise click.ClickException(
                f"Run '{handoff_ref}' does not declare a 'handoff_manifest' artifact."
            )
        return _load_handoff_manifest_file(Path(handoff_path))

    raise click.ClickException(
        f"Handoff reference '{handoff_ref}' was not found as a file, handoff id, or run id."
    )


def _load_handoff_manifest_file(path: Path) -> tuple[handoff_mod.DatasetHandoffManifest, Path]:
    if not path.exists():
        raise click.ClickException(f"Handoff manifest path does not exist: {path}")
    if path.is_dir():
        raise click.ClickException(f"Handoff manifest path must be a file: {path}")
    try:
        manifest = handoff_mod.DatasetHandoffManifest.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise click.ClickException(f"Invalid handoff manifest '{path}': {exc}") from exc
    return manifest, path


def _handoff_manifest_path(storage_root: Path, handoff_id: str) -> Path:
    safe_id = handoff_id.strip().replace("/", "_").replace("..", "_")
    return storage_root / "_lineage" / "handoffs" / f"{safe_id}.json"


def _partition_refs_by_event_type(
    manifest: handoff_mod.DatasetHandoffManifest,
) -> dict[str, list[str]]:
    refs_by_event_type: dict[str, list[str]] = {
        event_type: [] for event_type in manifest.event_types
    }
    for partition_ref in manifest.partition_refs:
        event_type = _event_type_from_partition_ref(partition_ref)
        if event_type not in refs_by_event_type:
            raise click.ClickException(
                f"Handoff manifest '{manifest.handoff_id}' contains unexpected partition ref "
                f"for event type '{event_type}': {partition_ref}"
            )
        if not _partition_ref_matches_venue(partition_ref, manifest.venue):
            raise click.ClickException(
                f"Handoff manifest '{manifest.handoff_id}' contains a partition ref for a "
                f"different venue: {partition_ref}"
            )
        refs_by_event_type[event_type].append(partition_ref)
    missing = [event_type for event_type, refs in refs_by_event_type.items() if not refs]
    if missing:
        raise click.ClickException(
            f"Handoff manifest '{manifest.handoff_id}' is missing partition refs for "
            f"event type(s): {missing}"
        )
    return refs_by_event_type


def _event_type_from_partition_ref(partition_ref: str) -> str:
    segments = [segment for segment in partition_ref.replace("\\", "/").split("/") if segment]
    try:
        silver_index = segments.index("silver")
    except ValueError as exc:
        raise click.ClickException(
            f"Invalid handoff partition ref '{partition_ref}': expected a silver/ path."
        ) from exc
    if silver_index + 1 >= len(segments):
        raise click.ClickException(
            f"Invalid handoff partition ref '{partition_ref}': missing event type segment."
        )
    return segments[silver_index + 1].strip().lower()


def _partition_ref_matches_venue(partition_ref: str, venue: str) -> bool:
    venue_segment = f"venue={venue.strip().lower()}"
    segments = [segment.strip().lower() for segment in partition_ref.replace("\\", "/").split("/")]
    return venue_segment in segments


def _link_handoff_source_runs(
    *,
    storage_root: Path,
    dataset_run_id: str,
    source_run_ids: tuple[str, ...],
    parent_run_id: str | None,
) -> None:
    if not source_run_ids:
        return
    store = lineage_mod.LineageStore(storage_root)
    for source_run_id in dict.fromkeys(source_run_ids):
        if source_run_id == parent_run_id:
            continue
        try:
            store.link_downstream_run(source_run_id, dataset_run_id)
        except KeyError:
            continue


@click.command("build-dataset")
@click.option("--name", required=True, help="Dataset name.")
@click.option("--start", required=False, help="Inclusive UTC start timestamp (ISO 8601).")
@click.option("--end", required=False, help="Inclusive UTC end timestamp (ISO 8601).")
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
    help="Event types to include.",
)
@click.option(
    "--handoff-manifest",
    default=None,
    help=(
        "Dataset-ready handoff reference: file path, handoff id, or ingestion run id "
        "with a 'handoff_manifest' artifact."
    ),
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
    start: str | None,
    end: str | None,
    venues: tuple[str, ...],
    event_types: tuple[str, ...],
    handoff_manifest: str | None,
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

    try:
        resolved_root = cmd_common.resolve_storage_root(ctx, storage_root)
        invocation = _resolve_dataset_invocation(
            ctx=ctx,
            name=name,
            start=start,
            end=end,
            venues=venues,
            event_types=event_types,
            handoff_manifest=handoff_manifest,
            require_quality_pass=require_quality_pass,
            require_gap_free=require_gap_free,
            max_gap_hours=max_gap_hours,
            parent_run_id=parent_run_id,
            storage_root=resolved_root,
        )
    except ValidationError as exc:
        raise click.ClickException(str(exc)) from exc

    if not execute:
        cmd_common.emit_planned_outcome(
            ctx,
            run_type="dataset_build",
            payload=invocation.config_payload,
        )
        return

    fmt = cmd_common.get_output_format(ctx)
    try:
        builder = make_dataset_builder(resolved_root)
        manifest = builder.build(
            invocation.config,
            config_payload=invocation.config_payload,
            parent_run_id=invocation.parent_run_id,
            session_id=cmd_common.get_session_id(ctx),
            extra_artifacts=invocation.extra_artifacts,
            partition_refs_by_event_type=invocation.partition_refs_by_event_type,
        )
        _link_handoff_source_runs(
            storage_root=resolved_root,
            dataset_run_id=manifest.run_id,
            source_run_ids=invocation.handoff_source_run_ids,
            parent_run_id=invocation.parent_run_id,
        )
    except builder_mod.DatasetBuildError as exc:
        raise click.ClickException(str(exc)) from exc

    cmd_common.emit_materialized_summary(
        storage_root=resolved_root,
        run_id=manifest.run_id,
        extra={
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
        fmt=fmt,
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
