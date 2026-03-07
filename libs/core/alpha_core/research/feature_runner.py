"""FeatureRunner — computes and persists versioned feature matrices from gold datasets.

Feature build steps (see :meth:`FeatureRunner.build`)
------------------------------------------------------
1. Locate dataset artifacts at ``{storage_root}/gold/datasets/{dataset_id}/``.
2. Fail fast when ``trades.parquet`` is absent.
3. Compute per-instrument rolling features using *lookback_bars*.
4. Write ``features.parquet`` under the canonical run artifact directory.
5. Persist ``feature_manifest.json`` and a ``RunManifest`` with ``feature_set_version``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, field_validator

import alpha_core.research.artifact_store as artifact_store_mod
import alpha_core.research.dataset_builder_io as dataset_builder_io
import alpha_core.research.manifest as manifest_mod
import alpha_core.research.run_context as run_context_mod
import alpha_core.storage.conventions as storage_conventions

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_FEATURE_MANIFEST_SCHEMA_VERSION: int = 1

# Columns in features.parquet that are not feature values.
_METADATA_COLS: frozenset[str] = frozenset({"instrument_id", "price", "ts_available", "ts_event"})


class FeatureConfig(BaseModel):
    """Configuration for a feature-build run."""

    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(min_length=1, description="Gold dataset id to build features from.")
    feature_set_version: str = Field(
        min_length=1,
        description="Monotonic version tag for this feature set (e.g. 'v1').",
    )
    lookback_bars: int = Field(
        default=200,
        gt=0,
        description="Rolling window size used by all time-series feature primitives.",
    )
    factor_pack_id: str | None = Field(
        default=None,
        description="Optional factor-pack ID whose manifest drives feature computation.",
    )

    @field_validator("dataset_id", "feature_set_version")
    @classmethod
    def _strip(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("field must not be blank")
        return cleaned


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


class FeatureManifest(BaseModel):
    """Persistent metadata for a completed feature-build run."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=_FEATURE_MANIFEST_SCHEMA_VERSION)
    run_id: str
    dataset_id: str
    feature_set_version: str
    built_at: datetime
    lookback_bars: int
    row_count: int
    feature_count: int
    feature_names: list[str]
    artifacts: dict[str, str]
    parent_run_id: str | None = None
    factor_pack_id: str | None = None


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FeatureRunError(RuntimeError):
    """Raised when the feature-build cannot proceed (e.g. missing dataset)."""


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class FeatureRunner:
    """Builds a versioned feature matrix from a gold dataset.

    Parameters
    ----------
    storage_root:
        Root directory shared with dataset builders and the run manifest store.
    """

    def __init__(
        self,
        storage_root: Path,
        store: artifact_store_mod.FilesystemArtifactStore | None = None,
    ) -> None:
        self._storage_root = storage_root
        self._gold_root = storage_root / storage_conventions.StorageTier.GOLD / "datasets"
        self._store = (
            store
            if store is not None
            else artifact_store_mod.FilesystemArtifactStore(storage_root)
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(
        self,
        config: FeatureConfig,
        *,
        config_payload: dict[str, Any] | None = None,
        parent_run_id: str | None = None,
    ) -> FeatureManifest:
        """Build and persist a feature matrix for *config*.

        Parameters
        ----------
        config:
            Feature-build configuration.
        config_payload:
            Optional serialised config dict used for run-manifest hashing.
            Falls back to ``config.model_dump(mode="json")``.
        parent_run_id:
            Optional upstream dataset run id for lineage tracking.

        Returns
        -------
        FeatureManifest
            Metadata for the completed build, also persisted to disk.

        Raises
        ------
        FeatureRunError
            When the target dataset directory or ``trades.parquet`` is absent.
        """
        effective_payload = (
            config_payload if config_payload is not None else config.model_dump(mode="json")
        )

        # 1. Fail fast: require dataset and trades artifact.
        try:
            dataset_locator = dataset_builder_io.resolve_dataset_locator(
                self._gold_root,
                config.dataset_id,
            )
        except (KeyError, ValueError) as exc:
            raise FeatureRunError(
                f"Dataset '{config.dataset_id}' could not be resolved: {exc}. "
                "Run build-dataset first."
            ) from exc

        trades_path = dataset_locator.dataset_dir / "trades.parquet"
        if not trades_path.exists():
            raise FeatureRunError(
                f"Dataset '{dataset_locator.dataset_id}' is missing 'trades.parquet'. "
                "The dataset may be empty or was built without the 'trades' event type."
            )

        # 2. Compute features.
        run_context = run_context_mod.make_run_context(
            "feature_build",
            config_payload=effective_payload,
        )
        features_table = _compute_features(trades_path, config.lookback_bars)
        feature_names = [col for col in features_table.schema.names if col not in _METADATA_COLS]

        # 3. Persist feature matrix.
        run_id = run_context.run_id
        features_path = self._store.prepare_path(run_id, "features.parquet")
        pq.write_table(features_table, features_path, compression="zstd")

        # 4. Finalize run context and assemble manifest.
        completed_context = run_context_mod.close_run_context(run_context)
        built_at = completed_context.completed_at_utc or datetime.now(tz=UTC)

        feature_manifest = FeatureManifest(
            run_id=run_id,
            dataset_id=dataset_locator.dataset_id,
            feature_set_version=config.feature_set_version,
            built_at=built_at,
            lookback_bars=config.lookback_bars,
            row_count=features_table.num_rows,
            feature_count=len(feature_names),
            feature_names=feature_names,
            artifacts={"features": str(features_path)},
            parent_run_id=parent_run_id,
            factor_pack_id=config.factor_pack_id,
        )

        # 5. Write feature manifest JSON.
        feature_manifest_path = self._store.prepare_path(run_id, "feature_manifest.json")
        feature_manifest_path.write_text(
            feature_manifest.model_dump_json(indent=2), encoding="utf-8"
        )

        # 6. Write artifacts index and run manifest (includes feature_set_version).
        artifact_map: dict[str, str] = {
            "features": str(features_path),
            "feature_manifest": str(feature_manifest_path),
            "feature_set_version": config.feature_set_version,
            "dataset_id": dataset_locator.dataset_id,
        }
        manifest_mod.persist_run_record(
            storage_root=self._storage_root,
            run_context=completed_context,
            config_payload=effective_payload,
            artifacts=artifact_map,
            parent_run_id=parent_run_id,
        )

        return feature_manifest


# ---------------------------------------------------------------------------
# Feature computation
# ---------------------------------------------------------------------------


def _compute_features(trades_path: Path, lookback_bars: int) -> pa.Table:
    """Compute per-instrument rolling features from a gold trades Parquet file.

    Features produced (all rolling over the prior *lookback_bars*)
    ----------------------------------------------------
    - ``price_mean_{N}`` — rolling mean of prior trade prices.
    - ``price_std_{N}``  — rolling standard deviation of prior trade prices.
    - ``price_zscore_{N}`` — current price vs prior rolling price distribution.
    - ``volume_mean_{N}`` — rolling mean of prior trade size.

    Feature history is ordered by ``ts_available = max(ts_event, ts_record)`` so
    late-arriving events cannot leak into earlier rows. Warm-up rows with
    insufficient history retain ``NaN`` values.

    Returns an Arrow table with columns:
    ``instrument_id``, ``price``, ``ts_available``, ``ts_event``, and the four
    feature columns above.
    """
    df = pq.read_table(trades_path).to_pandas()

    if df.empty or "price" not in df.columns:
        # Return an empty table with the correct schema.
        return _empty_feature_table(lookback_bars)

    required = {"instrument_id", "ts_event", "price", "size"}
    missing = required - set(df.columns)
    if missing:
        raise FeatureRunError(f"trades.parquet is missing required columns: {sorted(missing)}")

    n = lookback_bars
    col_prefix = f"_{n}"

    df = _with_availability_time(df)
    df = df.sort_values(["instrument_id", "ts_available", "ts_event"]).reset_index(drop=True)

    grouped = df.groupby("instrument_id", sort=False)
    history_price = grouped["price"].shift(1)
    history_size = grouped["size"].shift(1)
    instrument_ids = df["instrument_id"]

    price_mean = (
        history_price.groupby(instrument_ids, sort=False)
        .rolling(n, min_periods=n)
        .mean()
        .reset_index(level=0, drop=True)
    )
    price_std = (
        history_price.groupby(instrument_ids, sort=False)
        .rolling(n, min_periods=n)
        .std()
        .reset_index(level=0, drop=True)
    )
    price_zscore = (df["price"] - price_mean) / price_std.replace(0, float("nan"))
    volume_mean = (
        history_size.groupby(instrument_ids, sort=False)
        .rolling(n, min_periods=n)
        .mean()
        .reset_index(level=0, drop=True)
    )

    features_df = pd.DataFrame(
        {
            "instrument_id": df["instrument_id"],
            "price": df["price"],
            "ts_available": df["ts_available"],
            "ts_event": df["ts_event"],
            f"price_mean{col_prefix}": price_mean,
            f"price_std{col_prefix}": price_std,
            f"price_zscore{col_prefix}": price_zscore,
            f"volume_mean{col_prefix}": volume_mean,
        }
    )

    return pa.Table.from_pandas(features_df, preserve_index=False)


def _empty_feature_table(lookback_bars: int) -> pa.Table:
    """Return an empty Arrow table with the canonical feature schema."""
    n = lookback_bars
    col_prefix = f"_{n}"
    schema = pa.schema(
        [
            pa.field("instrument_id", pa.string()),
            pa.field("price", pa.float64()),
            pa.field("ts_available", pa.timestamp("us", tz="UTC")),
            pa.field("ts_event", pa.timestamp("us", tz="UTC")),
            pa.field(f"price_mean{col_prefix}", pa.float64()),
            pa.field(f"price_std{col_prefix}", pa.float64()),
            pa.field(f"price_zscore{col_prefix}", pa.float64()),
            pa.field(f"volume_mean{col_prefix}", pa.float64()),
        ]
    )
    return pa.table({name: [] for name in schema.names}, schema=schema)


def _with_availability_time(df: pd.DataFrame) -> pd.DataFrame:
    if "ts_record" not in df.columns:
        df["ts_available"] = df["ts_event"]
        return df

    recorded_at = df["ts_record"].where(df["ts_record"].notna(), df["ts_event"])
    df["ts_available"] = recorded_at.where(recorded_at >= df["ts_event"], df["ts_event"])
    return df


__all__ = [
    "FeatureConfig",
    "FeatureManifest",
    "FeatureRunError",
    "FeatureRunner",
]
