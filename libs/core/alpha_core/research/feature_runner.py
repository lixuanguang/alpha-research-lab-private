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

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field, field_validator

import alpha_core.config.paths as config_paths
import alpha_core.features.base as feature_base
import alpha_core.features.factor_pack as factor_pack_mod
import alpha_core.features.pm_specific as pm_features_mod
import alpha_core.instruments.master as master_mod
import alpha_core.research.artifact_paths as artifact_paths
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
            store if store is not None else artifact_store_mod.FilesystemArtifactStore(storage_root)
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
        effective_payload = self._resolve_config_payload(config, config_payload)
        dataset_locator, trades_path = self._resolve_dataset_inputs(config)
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
            dataset_dir=dataset_locator.dataset_dir,
            storage_root=self._storage_root,
            factor_packs=resolved_factor_packs,
        )
        features_path = self._persist_feature_table(
            run_id=run_context.run_id,
            features_table=features_table,
        )
        completed_context = run_context_mod.close_run_context(run_context)
        feature_manifest = self._build_feature_manifest(
            run_id=run_context.run_id,
            config=config,
            dataset_id=dataset_locator.dataset_id,
            completed_context=completed_context,
            features_table=features_table,
            features_path=features_path,
            resolved_factor_packs=resolved_factor_packs,
            parent_run_id=parent_run_id,
        )
        self._persist_run_record(
            feature_manifest=feature_manifest,
            config=config,
            dataset_id=dataset_locator.dataset_id,
            completed_context=completed_context,
            effective_payload=effective_payload,
            parent_run_id=parent_run_id,
        )
        return feature_manifest

    @staticmethod
    def _resolve_config_payload(
        config: FeatureConfig,
        config_payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if config_payload is not None:
            return config_payload
        return config.model_dump(mode="json")

    def _resolve_dataset_inputs(
        self,
        config: FeatureConfig,
    ) -> tuple[dataset_builder_io.DatasetLocator, Path]:
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
        return dataset_locator, trades_path

    def _persist_feature_table(self, *, run_id: str, features_table: pa.Table) -> Path:
        features_path = self._store.prepare_path(run_id, "features.parquet")
        pq.write_table(features_table, features_path, compression="zstd")
        return features_path

    def _build_feature_manifest(
        self,
        *,
        run_id: str,
        config: FeatureConfig,
        dataset_id: str,
        completed_context: run_context_mod.RunContext,
        features_table: pa.Table,
        features_path: Path,
        resolved_factor_packs: list[factor_pack_mod.FactorPackManifest],
        parent_run_id: str | None,
    ) -> FeatureManifest:
        feature_names = [col for col in features_table.schema.names if col not in _METADATA_COLS]
        factor_pack = resolved_factor_packs[-1] if resolved_factor_packs else None
        built_at = completed_context.completed_at_utc or datetime.now(tz=UTC)
        return FeatureManifest(
            run_id=run_id,
            dataset_id=dataset_id,
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

    def _persist_run_record(
        self,
        *,
        feature_manifest: FeatureManifest,
        config: FeatureConfig,
        dataset_id: str,
        completed_context: run_context_mod.RunContext,
        effective_payload: dict[str, Any],
        parent_run_id: str | None,
    ) -> None:
        feature_manifest_path = artifact_paths.artifact_key_path(
            self._storage_root,
            feature_manifest.run_id,
            "feature_manifest.json",
        )
        feature_manifest.artifacts["feature_manifest"] = str(feature_manifest_path)
        self._store.put(
            feature_manifest.run_id,
            "feature_manifest.json",
            feature_manifest.model_dump_json(indent=2).encode("utf-8"),
        )
        feature_manifest.artifacts["feature_set_version"] = config.feature_set_version
        feature_manifest.artifacts["dataset_id"] = dataset_id
        if feature_manifest.factor_pack_id is not None:
            feature_manifest.artifacts["factor_pack_id"] = feature_manifest.factor_pack_id
        if feature_manifest.factor_pack_version is not None:
            feature_manifest.artifacts["factor_pack_version"] = feature_manifest.factor_pack_version
        manifest_mod.persist_run_record(
            storage_root=self._storage_root,
            run_context=completed_context,
            config_payload=effective_payload,
            artifacts=feature_manifest.artifacts,
            parent_run_id=parent_run_id,
        )


# ---------------------------------------------------------------------------
# Feature computation
# ---------------------------------------------------------------------------


class _RollingFeatureCache:
    """Memoized rolling statistics used by :func:`_compute_features`."""

    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df
        self._grouped = df.groupby("instrument_id", sort=False)
        self._history_price = self._grouped["price"].shift(1)
        self._history_size = self._grouped["size"].shift(1)
        self._instrument_ids = df["instrument_id"]
        self._rolling_price_mean: dict[int, pd.Series] = {}
        self._rolling_price_std: dict[int, pd.Series] = {}
        self._rolling_volume_mean: dict[int, pd.Series] = {}
        self._lagged_price: dict[int, pd.Series] = {}

    def price_mean(self, window: int) -> pd.Series:
        if window not in self._rolling_price_mean:
            self._rolling_price_mean[window] = (
                self._history_price.groupby(self._instrument_ids, sort=False)
                .rolling(window, min_periods=window)
                .mean()
                .reset_index(level=0, drop=True)
            )
        return self._rolling_price_mean[window]

    def price_std(self, window: int) -> pd.Series:
        if window not in self._rolling_price_std:
            self._rolling_price_std[window] = (
                self._history_price.groupby(self._instrument_ids, sort=False)
                .rolling(window, min_periods=window)
                .std()
                .reset_index(level=0, drop=True)
            )
        return self._rolling_price_std[window]

    def volume_mean(self, window: int) -> pd.Series:
        if window not in self._rolling_volume_mean:
            self._rolling_volume_mean[window] = (
                self._history_size.groupby(self._instrument_ids, sort=False)
                .rolling(window, min_periods=window)
                .mean()
                .reset_index(level=0, drop=True)
            )
        return self._rolling_volume_mean[window]

    def price_lag(self, window: int) -> pd.Series:
        if window not in self._lagged_price:
            self._lagged_price[window] = self._grouped["price"].shift(window)
        return self._lagged_price[window]


def _compute_features(
    trades_path: Path,
    lookback_bars: int,
    *,
    dataset_dir: Path,
    storage_root: Path,
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
    late-arriving events cannot leak into earlier rows. PM-native factor packs
    are enriched from ``instruments.parquet`` and optional ``books.parquet``
    before feature computation. Warm-up rows with insufficient history retain
    ``NaN`` values.

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
    df = _enrich_trade_frame(
        df,
        dataset_dir=dataset_dir,
        storage_root=storage_root,
        requested_features=feature_columns,
    )
    df = df.sort_values(["instrument_id", "ts_available", "ts_event"]).reset_index(drop=True)
    cache = _RollingFeatureCache(df)
    pm_input_table: pa.Table | None = None

    features_data: dict[str, pd.Series] = {
        "instrument_id": df["instrument_id"],
        "price": df["price"],
        "ts_available": df["ts_available"],
        "ts_event": df["ts_event"],
    }
    for feature_name in feature_columns:
        if match := re.fullmatch(r"price_mean_(\d+)", feature_name):
            features_data[feature_name] = cache.price_mean(int(match.group(1)))
            continue
        if match := re.fullmatch(r"price_std_(\d+)", feature_name):
            features_data[feature_name] = cache.price_std(int(match.group(1)))
            continue
        if match := re.fullmatch(r"price_zscore_(\d+)", feature_name):
            window = int(match.group(1))
            price_std = cache.price_std(window)
            normalized_price = df["price"] - cache.price_mean(window)
            features_data[feature_name] = normalized_price / price_std.replace(0, float("nan"))
            continue
        if match := re.fullmatch(r"volume_mean_(\d+)", feature_name):
            features_data[feature_name] = cache.volume_mean(int(match.group(1)))
            continue
        if match := re.fullmatch(r"rolling_return_(\d+)", feature_name):
            lag = cache.price_lag(int(match.group(1)))
            features_data[feature_name] = df["price"] / lag.replace(0, float("nan")) - 1.0
            continue
        pm_feature = _resolve_pm_feature(feature_name)
        if pm_feature is not None:
            if pm_input_table is None:
                pm_input_table = pa.Table.from_pandas(df, preserve_index=False)
            result = pm_feature.compute(pm_input_table)
            features_data[feature_name] = pd.Series(result.values)
            continue
        raise FeatureRunError(
            f"Unsupported factor-pack feature column '{feature_name}'. "
            "Supported prefixes: price_mean_, price_std_, price_zscore_, "
            "volume_mean_, rolling_return_, implied_prob_momentum_, "
            "volume_weighted_prob_, prob_acceleration_, category_momentum_, "
            "book_imbalance_, plus cross_venue_spread and time_to_resolution_decay."
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


def _enrich_trade_frame(
    df: pd.DataFrame,
    *,
    dataset_dir: Path,
    storage_root: Path,
    requested_features: list[str],
) -> pd.DataFrame:
    enriched = df.copy()
    if any(_needs_market_metadata(feature_name) for feature_name in requested_features):
        enriched = _enrich_with_market_metadata(enriched, storage_root=storage_root)
    if any(_needs_book_snapshots(feature_name) for feature_name in requested_features):
        enriched = _enrich_with_book_snapshots(enriched, dataset_dir=dataset_dir)
    _validate_feature_inputs(enriched, requested_features=requested_features)
    return enriched


def _needs_market_metadata(feature_name: str) -> bool:
    return feature_name == "time_to_resolution_decay" or feature_name.startswith(
        "category_momentum_"
    )


def _needs_book_snapshots(feature_name: str) -> bool:
    return feature_name.startswith("book_imbalance_")


def _validate_feature_inputs(df: pd.DataFrame, *, requested_features: list[str]) -> None:
    if "time_to_resolution_decay" in requested_features and (
        "resolution_date" not in df.columns or not df["resolution_date"].notna().any()
    ):
        raise FeatureRunError(
            "Feature 'time_to_resolution_decay' requires point-in-time market metadata. "
            "Persist instruments to 'instruments.parquet' before running build-features."
        )
    if any(
        feature_name.startswith("category_momentum_") for feature_name in requested_features
    ) and ("category" not in df.columns or not df["category"].notna().any()):
        raise FeatureRunError(
            "Feature 'category_momentum_*' requires market category metadata. "
            "Persist instruments to 'instruments.parquet' before running build-features."
        )
    if any(feature_name.startswith("book_imbalance_") for feature_name in requested_features) and (
        not {"bids_json", "asks_json"}.issubset(df.columns)
        or not df["bids_json"].notna().any()
        or not df["asks_json"].notna().any()
    ):
        raise FeatureRunError(
            "Feature 'book_imbalance_*' requires gold books data. "
            "Build the dataset with '--event-type books' before running build-features."
        )


def _sequence_column(df: pd.DataFrame) -> str:
    if "ts_available" in df.columns:
        return "ts_available"
    if "ts_record" in df.columns:
        return "ts_record"
    return "ts_event"


def _utc_timestamp_series(values: pd.Series) -> pd.Series:
    series = pd.to_datetime(values, utc=True, errors="coerce")
    return pd.Series(series.astype("datetime64[ns, UTC]"), index=values.index)


def _market_id_for_instrument(instrument_id: object) -> str | None:
    if not isinstance(instrument_id, str):
        return None
    parts = instrument_id.rsplit(":", 1)
    if len(parts) != 2 or not parts[0]:
        return None
    return parts[0]


def _enrich_with_market_metadata(df: pd.DataFrame, *, storage_root: Path) -> pd.DataFrame:
    instruments_path = storage_root / "instruments.parquet"
    if not instruments_path.exists():
        return df

    metadata = _load_market_metadata_frame(instruments_path)
    if metadata.empty:
        return df

    sequence_col = _sequence_column(df)
    left = df.copy()
    left["_market_id"] = left["instrument_id"].map(_market_id_for_instrument)
    left["_sequence_ts"] = _utc_timestamp_series(left[sequence_col])
    left["_row_order"] = pd.RangeIndex(len(left))
    left = left.sort_values(["_sequence_ts", "_market_id"], kind="stable")

    merged = pd.merge_asof(
        left,
        metadata.sort_values(["effective_at", "market_id"], kind="stable"),
        left_on="_sequence_ts",
        right_on="effective_at",
        left_by="_market_id",
        right_by="market_id",
        direction="backward",
    )
    if "category" not in merged.columns:
        merged["category"] = merged["_category_meta"]
    else:
        merged["category"] = merged["category"].where(
            merged["category"].notna(),
            merged["_category_meta"],
        )
    if "resolution_date" not in merged.columns:
        merged["resolution_date"] = merged["_resolution_date_meta"]
    else:
        merged["resolution_date"] = merged["resolution_date"].where(
            merged["resolution_date"].notna(),
            merged["_resolution_date_meta"],
        )

    return (
        merged.sort_values("_row_order", kind="stable")
        .drop(
            columns=[
                "_market_id",
                "_sequence_ts",
                "_row_order",
                "market_id",
                "effective_at",
                "_category_meta",
                "_resolution_date_meta",
            ],
            errors="ignore",
        )
        .reset_index(drop=True)
    )


def _load_market_metadata_frame(instruments_path: Path) -> pd.DataFrame:
    master = master_mod.MarketMaster()
    master.restore(instruments_path)
    snapshot = master.snapshot()["markets"]
    if not isinstance(snapshot, dict):
        return pd.DataFrame(
            columns=["market_id", "effective_at", "_category_meta", "_resolution_date_meta"]
        )

    rows: list[dict[str, object]] = []
    for canonical_market_id in sorted(snapshot):
        history = master.get_market_history(str(canonical_market_id))
        for index, market in enumerate(history):
            rows.append(
                {
                    "market_id": str(canonical_market_id),
                    "effective_at": market.first_seen if index == 0 else market.last_updated,
                    "_category_meta": market.category,
                    "_resolution_date_meta": market.resolution_date,
                }
            )
    if not rows:
        return pd.DataFrame(
            columns=["market_id", "effective_at", "_category_meta", "_resolution_date_meta"]
        )
    frame = pd.DataFrame(rows)
    frame["effective_at"] = _utc_timestamp_series(frame["effective_at"])
    if "_resolution_date_meta" in frame.columns:
        frame["_resolution_date_meta"] = _utc_timestamp_series(frame["_resolution_date_meta"])
    return frame


def _enrich_with_book_snapshots(df: pd.DataFrame, *, dataset_dir: Path) -> pd.DataFrame:
    books_path = dataset_dir / "books.parquet"
    if not books_path.exists():
        return df

    books_df = pq.read_table(books_path).to_pandas()
    if books_df.empty or "instrument_id" not in books_df.columns:
        return df

    books_df = _with_availability_time(books_df)
    required = {"instrument_id", "ts_available", "bids_json", "asks_json"}
    if not required.issubset(books_df.columns):
        return df

    sequence_col = _sequence_column(df)
    left = df.copy()
    left["_sequence_ts"] = _utc_timestamp_series(left[sequence_col])
    left["_row_order"] = pd.RangeIndex(len(left))
    left = left.sort_values(["_sequence_ts", "instrument_id"], kind="stable")

    right = books_df.loc[:, ["instrument_id", "ts_available", "bids_json", "asks_json"]].copy()
    right["ts_available"] = _utc_timestamp_series(right["ts_available"])
    right = right.rename(
        columns={
            "ts_available": "_book_available",
            "bids_json": "_bids_json_book",
            "asks_json": "_asks_json_book",
        }
    )
    right = right.sort_values(["_book_available", "instrument_id"], kind="stable")

    merged = pd.merge_asof(
        left,
        right,
        left_on="_sequence_ts",
        right_on="_book_available",
        by="instrument_id",
        direction="backward",
    )
    if "bids_json" not in merged.columns:
        merged["bids_json"] = merged["_bids_json_book"]
    else:
        merged["bids_json"] = merged["bids_json"].where(
            merged["bids_json"].notna(),
            merged["_bids_json_book"],
        )
    if "asks_json" not in merged.columns:
        merged["asks_json"] = merged["_asks_json_book"]
    else:
        merged["asks_json"] = merged["asks_json"].where(
            merged["asks_json"].notna(),
            merged["_asks_json_book"],
        )

    return (
        merged.sort_values("_row_order", kind="stable")
        .drop(
            columns=[
                "_sequence_ts",
                "_row_order",
                "_book_available",
                "_bids_json_book",
                "_asks_json_book",
            ],
            errors="ignore",
        )
        .reset_index(drop=True)
    )


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
        version_msg = f" version '{expected_version}'" if expected_version is not None else ""
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


def _resolve_pm_feature(feature_name: str) -> feature_base.Feature | None:
    if match := re.fullmatch(r"implied_prob_momentum_(\d+)", feature_name):
        return pm_features_mod.ImpliedProbMomentum(window=int(match.group(1)))
    if feature_name == "cross_venue_spread":
        return pm_features_mod.CrossVenueSpread()
    if match := re.fullmatch(r"volume_weighted_prob_(\d+)", feature_name):
        return pm_features_mod.VolumeWeightedProb(window=int(match.group(1)))
    if feature_name == "time_to_resolution_decay":
        return pm_features_mod.TimeToResolutionDecay()
    if match := re.fullmatch(r"category_momentum_(\d+)", feature_name):
        return pm_features_mod.CategoryMomentum(window=int(match.group(1)))
    if match := re.fullmatch(r"book_imbalance_(\d+)", feature_name):
        return pm_features_mod.BookImbalance(levels=int(match.group(1)))
    if match := re.fullmatch(r"prob_acceleration_(\d+)_(\d+)", feature_name):
        return pm_features_mod.ProbAcceleration(
            fast=int(match.group(1)),
            slow=int(match.group(2)),
        )
    return None


def _validate_feature_columns(feature_columns: list[str]) -> None:
    allowed_patterns = (
        r"price_mean_\d+",
        r"price_std_\d+",
        r"price_zscore_\d+",
        r"volume_mean_\d+",
        r"rolling_return_\d+",
        r"implied_prob_momentum_\d+",
        r"cross_venue_spread",
        r"volume_weighted_prob_\d+",
        r"time_to_resolution_decay",
        r"category_momentum_\d+",
        r"book_imbalance_\d+",
        r"prob_acceleration_\d+_\d+",
    )
    for feature_name in feature_columns:
        if any(re.fullmatch(pattern, feature_name) for pattern in allowed_patterns):
            continue
        raise FeatureRunError(
            f"Unsupported factor-pack feature column '{feature_name}'. "
            "Supported patterns: price_mean_N, price_std_N, price_zscore_N, "
            "volume_mean_N, rolling_return_N, implied_prob_momentum_N, "
            "cross_venue_spread, volume_weighted_prob_N, time_to_resolution_decay, "
            "category_momentum_N, book_imbalance_N, prob_acceleration_fast_slow."
        )


__all__ = [
    "FeatureConfig",
    "FeatureManifest",
    "FeatureRunError",
    "FeatureRunner",
]
