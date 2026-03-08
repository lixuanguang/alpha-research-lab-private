"""FeatureSetBuilder — batch feature computation from gold datasets.

Persists feature matrices to ``{storage_root}/gold/features/{name}/`` in a
format loadable by :meth:`FeatureSetBuilder.load`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field

import alpha_core.features.registry as registry_mod
import alpha_core.research.dataset as dataset_mod
import alpha_core.storage.conventions as storage_conventions

# ---------------------------------------------------------------------------
# Config + Manifest
# ---------------------------------------------------------------------------

class FeatureSetConfig(BaseModel):
    """Configuration for a batch feature computation run."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1,
        description="Feature set name (used as directory name).",
    )
    dataset_id: str = Field(
        min_length=1,
        description="Gold dataset ID to compute features from.",
    )
    features: list[str] = Field(
        min_length=1,
        description="Feature names to compute (must be registered).",
    )
    # Per-feature param overrides recorded in metadata; registry instances are used as-is.
    # To compute with different params, register a variant feature under a distinct name.
    params_override: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Metadata-only: records intended param overrides. Not applied at runtime.",
    )


class FeatureSetManifest(BaseModel):
    """Metadata for a persisted feature set."""

    model_config = ConfigDict(extra="forbid")

    feature_set_name: str
    dataset_id: str
    features: list[str]
    params_override: dict[str, dict[str, Any]] = Field(default_factory=dict)
    config_hash: str
    built_at: datetime
    row_count: int
    column_count: int
    schema_version: int = 1


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

class FeatureSetBuilder:
    """Computes a feature set from a gold dataset and persists it.

    Storage layout::

        {storage_root}/gold/features/{name}/
            features.parquet   - [timestamp x instrument x feature_columns]
            _meta.json         - FeatureSetManifest

    Args:
        registry: Pre-populated :class:`FeatureRegistry` with all required features.
        storage_root: Root of the data lake (same convention as DatasetBuilder).
    """

    def __init__(
        self,
        registry: registry_mod.FeatureRegistry,
        storage_root: Path,
    ) -> None:
        self._registry = registry
        self._features_root = (
            storage_root / storage_conventions.StorageTier.GOLD / "features"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(
        self,
        config: FeatureSetConfig,
        dataset: dataset_mod.GoldDataset,
    ) -> Path:
        """Compute features and write ``features.parquet`` + ``_meta.json``.

        Args:
            config: Feature set specification.
            dataset: Gold dataset handle to read trade data from.

        Returns:
            Path to the written ``features.parquet`` file.

        Raises:
            ValueError: When a requested feature is not registered.
            FileExistsError: When the feature set directory already exists
                             with data (re-running the same name is idempotent
                             — call :meth:`delete` first to rebuild).
        """
        # Validate features are registered.
        unknown = set(config.features) - set(self._registry.registered)
        if unknown:
            raise ValueError(
                f"Features not registered: {sorted(unknown)}. "
                "Register them in the FeatureRegistry first."
            )

        output_dir = self._features_root / config.name
        features_path = output_dir / "features.parquet"
        meta_path = output_dir / "_meta.json"

        if features_path.exists():
            raise FileExistsError(
                f"Feature set '{config.name}' already exists at {output_dir}. "
                "Delete it first or use a different name."
            )

        # Load trade data and compute features.
        trades = dataset.trades()
        enriched = self._registry.compute_all(trades, features=config.features)

        # Write output.
        output_dir.mkdir(parents=True, exist_ok=True)
        pq.write_table(enriched, features_path, compression="zstd")

        manifest = FeatureSetManifest(
            feature_set_name=config.name,
            dataset_id=config.dataset_id,
            features=list(config.features),
            params_override=config.params_override,
            config_hash=_hash_config(config),
            built_at=datetime.now(tz=UTC),
            row_count=enriched.num_rows,
            column_count=len(config.features),
        )
        meta_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

        return features_path

    def load(self, feature_set_name: str) -> pa.Table:
        """Load a previously built feature set.

        Args:
            feature_set_name: The name used during ``build()``.

        Returns:
            PyArrow table with all feature columns.

        Raises:
            FileNotFoundError: When the feature set does not exist.
        """
        path = self._features_root / feature_set_name / "features.parquet"
        if not path.exists():
            raise FileNotFoundError(
                f"Feature set '{feature_set_name}' not found at {path}."
            )
        return pq.read_table(path)

    def load_manifest(self, feature_set_name: str) -> FeatureSetManifest:
        """Load the manifest for a previously built feature set."""
        path = self._features_root / feature_set_name / "_meta.json"
        if not path.exists():
            raise FileNotFoundError(
                f"Manifest for feature set '{feature_set_name}' not found at {path}."
            )
        return FeatureSetManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def list_feature_sets(self) -> list[str]:
        """Return names of all persisted feature sets (sorted)."""
        if not self._features_root.exists():
            return []
        return sorted(
            p.name
            for p in self._features_root.iterdir()
            if p.is_dir() and (p / "features.parquet").exists()
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_config(config: FeatureSetConfig) -> str:
    payload = json.dumps(config.model_dump(mode="json"), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


__all__ = ["FeatureSetBuilder", "FeatureSetConfig", "FeatureSetManifest"]
