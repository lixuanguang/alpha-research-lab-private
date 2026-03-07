"""DatasetBuilder I/O helpers for gold dataset persistence and discovery."""

from __future__ import annotations

import contextlib
import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

import alpha_core.research.dataset as dataset_mod
import alpha_core.research.manifest as manifest_mod
import alpha_core.research.run_context as run_context_mod
import alpha_core.research.universe as universe_mod

_UNIVERSE_SCHEMA = pa.schema(
    [
        pa.field("as_of", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("instrument_id", pa.string(), nullable=False),
        pa.field("market_id", pa.string(), nullable=False),
        pa.field("venue", pa.string(), nullable=False),
    ]
)


@dataclass(slots=True)
class DatasetBuildOutputs:
    manifest: dataset_mod.DatasetManifest
    dataset_id: str
    dataset_dir: Path
    meta_path: Path


@dataclass(slots=True)
class DatasetOutputSpec:
    config: dataset_mod.DatasetConfig
    start_utc: datetime
    end_utc: datetime
    snapshots: list[universe_mod.UniverseSnapshot]
    gold_tables: dict[str, pa.Table]
    quality_summary: dict[str, Any]
    instrument_count: int


def write_dataset_outputs(
    *,
    gold_root: Path,
    spec: DatasetOutputSpec,
) -> DatasetBuildOutputs:
    dataset_id = make_dataset_id(spec.config)
    dataset_dir = dataset_directory(gold_root, dataset_id)
    if dataset_dir.exists():
        raise FileExistsError(
            f"Dataset snapshot '{dataset_id}' already exists at {dataset_dir}. "
            "Dataset IDs are immutable; change the dataset config to create a new snapshot."
        )

    gold_root.mkdir(parents=True, exist_ok=True)
    staging_dir = gold_root / f".{dataset_id}.{uuid.uuid4().hex}.tmp"
    staging_dir.mkdir(parents=False, exist_ok=False)
    try:
        row_counts = _write_event_tables(dataset_dir=staging_dir, gold_tables=spec.gold_tables)
        _write_universe_table(dataset_dir=staging_dir, snapshots=spec.snapshots)

        manifest = dataset_mod.DatasetManifest(
            dataset_id=dataset_id,
            config=spec.config,
            built_at=datetime.now(tz=UTC),
            row_counts=row_counts,
            instrument_count=spec.instrument_count,
            date_range=(spec.start_utc, spec.end_utc),
            quality_summary=spec.quality_summary,
            schema_version=1,
        )
        staged_meta_path = staging_dir / "_meta.json"
        staged_meta_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        staging_dir.rename(dataset_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    meta_path = dataset_dir / "_meta.json"
    return DatasetBuildOutputs(
        manifest=manifest,
        dataset_id=dataset_id,
        dataset_dir=dataset_dir,
        meta_path=meta_path,
    )


def persist_build_artifacts(
    *,
    storage_root: Path,
    config_payload: dict[str, Any],
    run_context: run_context_mod.RunContext,
    outputs: DatasetBuildOutputs,
) -> None:
    completed_context = run_context_mod.close_run_context(run_context)
    artifact_map = {
        "dataset_id": outputs.dataset_id,
        "dataset_meta": str(outputs.meta_path),
        "dataset_dir": str(outputs.dataset_dir),
        "universe": str(outputs.dataset_dir / "universe.parquet"),
    }
    manifest_mod.persist_run_record(
        storage_root=storage_root,
        run_context=completed_context,
        config_payload=config_payload,
        artifacts=artifact_map,
        parent_run_id=None,
    )


def load_dataset(gold_root: Path, dataset_id: str) -> dataset_mod.GoldDataset:
    """Load a previously built gold dataset by dataset id or unique config name."""
    if not gold_root.exists() or not gold_root.is_dir():
        raise KeyError(f"No gold dataset found with id or name '{dataset_id}'")

    entries = _load_dataset_entries(gold_root)
    for manifest, candidate_dir in entries:
        if manifest.dataset_id == dataset_id:
            return dataset_mod.GoldDataset(manifest=manifest, dataset_dir=candidate_dir)

    name_matches = [
        (manifest, candidate_dir)
        for manifest, candidate_dir in entries
        if manifest.config.name == dataset_id
    ]
    if len(name_matches) == 1:
        manifest, candidate_dir = name_matches[0]
        return dataset_mod.GoldDataset(manifest=manifest, dataset_dir=candidate_dir)
    if len(name_matches) > 1:
        raise ValueError(
            f"Dataset name '{dataset_id}' is ambiguous; use an explicit dataset_id instead."
        )

    raise KeyError(f"No gold dataset found with id or name '{dataset_id}'")


def list_datasets(gold_root: Path) -> list[dataset_mod.DatasetManifest]:
    """Return metadata for all built gold datasets, sorted by build time."""
    if not gold_root.exists() or not gold_root.is_dir():
        return []
    return [manifest for manifest, _ in _load_dataset_entries(gold_root)]


def make_dataset_id(config: dataset_mod.DatasetConfig) -> str:
    """Deterministic SHA-256 hash of the serialised config."""
    payload = json.dumps(config.model_dump(mode="json"), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def dataset_directory(gold_root: Path, dataset_id: str) -> Path:
    """Return the immutable storage path for one dataset snapshot."""
    return gold_root / dataset_id


def _write_event_tables(
    *,
    dataset_dir: Path,
    gold_tables: dict[str, pa.Table],
) -> dict[str, int]:
    row_counts: dict[str, int] = {}
    for event_type, table in gold_tables.items():
        pq.write_table(table, dataset_dir / f"{event_type}.parquet", compression="zstd")
        row_counts[event_type] = table.num_rows
    return row_counts


def _write_universe_table(
    *,
    dataset_dir: Path,
    snapshots: list[universe_mod.UniverseSnapshot],
) -> None:
    universe_rows: list[dict[str, object]] = []
    for snapshot in snapshots:
        venue_id_map = _build_venue_map(snapshot)
        universe_rows.extend(
            {
                "as_of": snapshot.as_of,
                "instrument_id": instrument_id,
                "market_id": _market_for_instrument(instrument_id),
                "venue": venue_id_map.get(instrument_id, "unknown"),
            }
            for instrument_id in snapshot.instruments
        )

    universe_table = pa.Table.from_pylist(universe_rows, schema=_UNIVERSE_SCHEMA)
    pq.write_table(universe_table, dataset_dir / "universe.parquet", compression="zstd")


def _build_venue_map(snapshot: universe_mod.UniverseSnapshot) -> dict[str, str]:
    venue_map: dict[str, str] = {}
    for instrument_id in snapshot.instruments:
        venue_map[instrument_id] = instrument_id.split(":", 1)[0]
    return venue_map


def _market_for_instrument(instrument_id: str) -> str:
    """Derive the canonical market id from a canonical outcome id."""
    parts = instrument_id.rsplit(":", 1)
    return parts[0] if len(parts) == 2 else instrument_id


def _load_dataset_entries(
    gold_root: Path,
) -> list[tuple[dataset_mod.DatasetManifest, Path]]:
    entries: list[tuple[dataset_mod.DatasetManifest, Path]] = []
    for candidate_dir in gold_root.iterdir():
        meta_path = candidate_dir / "_meta.json"
        if not meta_path.exists():
            continue
        with contextlib.suppress(OSError, ValueError):
            manifest = dataset_mod.DatasetManifest.model_validate_json(
                meta_path.read_text(encoding="utf-8")
            )
            entries.append((manifest, candidate_dir))
    return sorted(entries, key=lambda entry: entry[0].built_at, reverse=True)
