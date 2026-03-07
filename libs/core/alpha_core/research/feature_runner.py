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

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, field_validator

import alpha_core.config.paths as config_paths
import alpha_core.features.factor_pack as factor_pack_mod
import alpha_core.research.artifact_store as artifact_store_mod
import alpha_core.research.dataset_builder_io as dataset_builder_io
import alpha_core.research.manifest as manifest_mod
import alpha_core.research.run_context as run_context_mod
import alpha_core.storage.conventions as storage_conventions

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_FEATURE_MANIFEST_SCHEMA_VERSION: int = 2

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
    factor_pack_version: str | None = Field(
        default=None,
        description="Resolved factor-pack version recorded in the feature manifest.",
    )

    @field_validator("dataset_id", "feature_set_version")
    @classmethod
    def _strip(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("field must not be blank")
        return cleaned

    @field_validator("factor_pack_id", "factor_pack_version")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
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
    factor_pack_version: str | None = None


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
        session_id: str | None = None,
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
        resolved_factor_packs = resolve_factor_pack_chain(
            config.factor_pack_id,
            expected_version=config.factor_pack_version,
        )
        run_context = run_context_mod.make_run_context(
            "feature_build",
            config_payload=effective_payload,
            session_id=session_id,
        )
        features_table = _compute_features(
            trades_path,
            config.lookback_bars,
            factor_packs=resolved_factor_packs,
        )
        feature_names = [col for col in features_table.schema.names if col not in _METADATA_COLS]
        factor_pack = resolved_factor_packs[-1] if resolved_factor_packs else None

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
            lookback_bars=_effective_lookback_bars(feature_names, fallback=config.lookback_bars),
            row_count=features_table.num_rows,
            feature_count=len(feature_names),
            feature_names=feature_names,
            artifacts={"features": str(features_path)},
            parent_run_id=parent_run_id,
            factor_pack_id=(
                factor_pack.pack_id if factor_pack is not None else config.factor_pack_id
            ),
            factor_pack_version=(
                factor_pack.version if factor_pack is not None else config.factor_pack_version
            ),
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
        if feature_manifest.factor_pack_id is not None:
            artifact_map["factor_pack_id"] = feature_manifest.factor_pack_id
        if feature_manifest.factor_pack_version is not None:
            artifact_map["factor_pack_version"] = feature_manifest.factor_pack_version
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


def _compute_features(
    trades_path: Path,
    lookback_bars: int,
    *,
    factor_packs: list[factor_pack_mod.FactorPackManifest] | None = None,
) -> pa.Table:
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
        return _empty_feature_table(
            _requested_feature_columns(
                factor_packs,
                fallback=lookback_bars,
            )
        )

    required = {"instrument_id", "ts_event", "price", "size"}
    missing = required - set(df.columns)
    if missing:
        raise FeatureRunError(f"trades.parquet is missing required columns: {sorted(missing)}")

    feature_columns = _requested_feature_columns(factor_packs, fallback=lookback_bars)

    df = _with_availability_time(df)
    df = df.sort_values(["instrument_id", "ts_available", "ts_event"]).reset_index(drop=True)

    grouped = df.groupby("instrument_id", sort=False)
    history_price = grouped["price"].shift(1)
    history_size = grouped["size"].shift(1)
    instrument_ids = df["instrument_id"]

    rolling_price_mean: dict[int, pd.Series] = {}
    rolling_price_std: dict[int, pd.Series] = {}
    rolling_volume_mean: dict[int, pd.Series] = {}
    lagged_price: dict[int, pd.Series] = {}

    def get_price_mean(window: int) -> pd.Series:
        if window not in rolling_price_mean:
            rolling_price_mean[window] = (
                history_price.groupby(instrument_ids, sort=False)
                .rolling(window, min_periods=window)
                .mean()
                .reset_index(level=0, drop=True)
            )
        return rolling_price_mean[window]

    def get_price_std(window: int) -> pd.Series:
        if window not in rolling_price_std:
            rolling_price_std[window] = (
                history_price.groupby(instrument_ids, sort=False)
                .rolling(window, min_periods=window)
                .std()
                .reset_index(level=0, drop=True)
            )
        return rolling_price_std[window]

    def get_volume_mean(window: int) -> pd.Series:
        if window not in rolling_volume_mean:
            rolling_volume_mean[window] = (
                history_size.groupby(instrument_ids, sort=False)
                .rolling(window, min_periods=window)
                .mean()
                .reset_index(level=0, drop=True)
            )
        return rolling_volume_mean[window]

    def get_price_lag(window: int) -> pd.Series:
        if window not in lagged_price:
            lagged_price[window] = grouped["price"].shift(window)
        return lagged_price[window]

    features_data: dict[str, pd.Series] = {
        "instrument_id": df["instrument_id"],
        "price": df["price"],
        "ts_available": df["ts_available"],
        "ts_event": df["ts_event"],
    }
    for feature_name in feature_columns:
        if match := re.fullmatch(r"price_mean_(\d+)", feature_name):
            features_data[feature_name] = get_price_mean(int(match.group(1)))
            continue
        if match := re.fullmatch(r"price_std_(\d+)", feature_name):
            features_data[feature_name] = get_price_std(int(match.group(1)))
            continue
        if match := re.fullmatch(r"price_zscore_(\d+)", feature_name):
            window = int(match.group(1))
            price_std = get_price_std(window)
            normalized_price = df["price"] - get_price_mean(window)
            features_data[feature_name] = normalized_price / price_std.replace(0, float("nan"))
            continue
        if match := re.fullmatch(r"volume_mean_(\d+)", feature_name):
            features_data[feature_name] = get_volume_mean(int(match.group(1)))
            continue
        if match := re.fullmatch(r"rolling_return_(\d+)", feature_name):
            lag = get_price_lag(int(match.group(1)))
            features_data[feature_name] = df["price"] / lag.replace(0, float("nan")) - 1.0
            continue
        raise FeatureRunError(
            f"Unsupported factor-pack feature column '{feature_name}'. "
            "Supported prefixes: price_mean_, price_std_, price_zscore_, "
            "volume_mean_, rolling_return_."
        )

    features_df = pd.DataFrame(features_data)

    return pa.Table.from_pandas(features_df, preserve_index=False)


def _empty_feature_table(feature_columns: list[str]) -> pa.Table:
    """Return an empty Arrow table with the canonical feature schema."""
    schema = pa.schema(
        [
            pa.field("instrument_id", pa.string()),
            pa.field("price", pa.float64()),
            pa.field("ts_available", pa.timestamp("us", tz="UTC")),
            pa.field("ts_event", pa.timestamp("us", tz="UTC")),
            *[pa.field(name, pa.float64()) for name in feature_columns],
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


def resolve_factor_pack_chain(
    factor_pack_id: str | None,
    *,
    expected_version: str | None = None,
) -> list[factor_pack_mod.FactorPackManifest]:
    if factor_pack_id is None:
        return []

    packs_dir = config_paths.find_project_root(__file__) / "config" / "research" / "factor_packs"
    available = _discover_factor_packs(packs_dir)
    requested = _resolve_factor_pack(
        factor_pack_id,
        available=available,
        expected_version=expected_version,
    )
    required_packs = _factor_pack_dependency_closure(requested, available=available)
    try:
        return factor_pack_mod.resolve_dependency_order(list(required_packs.values()))
    except ValueError as exc:
        raise FeatureRunError(str(exc)) from exc


def _discover_factor_packs(packs_dir: Path) -> list[factor_pack_mod.FactorPackManifest]:
    if not packs_dir.exists():
        raise FeatureRunError(f"Factor-pack config directory does not exist: {packs_dir}")

    manifests: list[factor_pack_mod.FactorPackManifest] = []
    for path in sorted(packs_dir.glob("*.yaml")) + sorted(packs_dir.glob("*.yml")):
        manifests.append(factor_pack_mod.load_factor_pack(path))
    for path in sorted(packs_dir.glob("*.json")):
        manifests.append(factor_pack_mod.load_factor_pack(path))
    return manifests


def _resolve_factor_pack(
    factor_pack_id: str,
    *,
    available: list[factor_pack_mod.FactorPackManifest],
    expected_version: str | None,
) -> factor_pack_mod.FactorPackManifest:
    matches = [pack for pack in available if pack.pack_id == factor_pack_id]
    if expected_version is not None:
        matches = [pack for pack in matches if pack.version == expected_version]
    if not matches:
        version_msg = (
            f" version '{expected_version}'" if expected_version is not None else ""
        )
        raise FeatureRunError(f"Factor pack '{factor_pack_id}'{version_msg} was not found.")
    if len(matches) > 1:
        versions = sorted(pack.version for pack in matches)
        raise FeatureRunError(
            f"Factor pack '{factor_pack_id}' is ambiguous across versions {versions}. "
            "Pass an explicit factor_pack_version."
        )
    return matches[0]


def _factor_pack_dependency_closure(
    pack: factor_pack_mod.FactorPackManifest,
    *,
    available: list[factor_pack_mod.FactorPackManifest],
) -> dict[str, factor_pack_mod.FactorPackManifest]:
    required_packs = {pack.pack_id: pack}
    for dependency_id in pack.dependencies:
        dependency = _resolve_factor_pack(
            dependency_id,
            available=available,
            expected_version=None,
        )
        nested_packs = _factor_pack_dependency_closure(dependency, available=available)
        for nested_pack_id, nested_pack in nested_packs.items():
            existing = required_packs.get(nested_pack_id)
            if existing is not None and existing.version != nested_pack.version:
                raise FeatureRunError(
                    f"Factor pack dependency '{nested_pack_id}' resolved to conflicting versions "
                    f"'{existing.version}' and '{nested_pack.version}'."
                )
            required_packs[nested_pack_id] = nested_pack
    return required_packs


def _requested_feature_columns(
    factor_packs: list[factor_pack_mod.FactorPackManifest] | None,
    *,
    fallback: int,
) -> list[str]:
    if not factor_packs:
        return [
            f"price_mean_{fallback}",
            f"price_std_{fallback}",
            f"price_zscore_{fallback}",
            f"volume_mean_{fallback}",
        ]

    columns: list[str] = []
    seen: set[str] = set()
    for pack in factor_packs:
        for column_name in pack.output_schema:
            if column_name in seen:
                continue
            seen.add(column_name)
            columns.append(column_name)
    _validate_feature_columns(columns)
    return columns


def _effective_lookback_bars(feature_names: list[str], *, fallback: int) -> int:
    windows = [
        int(match.group(1))
        for feature_name in feature_names
        if (match := re.search(r"_(\d+)$", feature_name)) is not None
    ]
    return max(windows, default=fallback)


def _validate_feature_columns(feature_columns: list[str]) -> None:
    allowed_patterns = (
        r"price_mean_\d+",
        r"price_std_\d+",
        r"price_zscore_\d+",
        r"volume_mean_\d+",
        r"rolling_return_\d+",
    )
    for feature_name in feature_columns:
        if any(re.fullmatch(pattern, feature_name) for pattern in allowed_patterns):
            continue
        raise FeatureRunError(
            f"Unsupported factor-pack feature column '{feature_name}'. "
            "Supported patterns: price_mean_N, price_std_N, price_zscore_N, "
            "volume_mean_N, rolling_return_N."
        )


__all__ = [
    "FeatureConfig",
    "FeatureManifest",
    "FeatureRunError",
    "FeatureRunner",
]
