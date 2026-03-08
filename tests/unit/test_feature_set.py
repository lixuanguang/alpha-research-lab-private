"""Unit tests for alpha_core.features.feature_set."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pyarrow as pa
import pytest

import alpha_core.features.base as feature_base
from alpha_core.features.feature_set import (
    FeatureSetBuilder,
    FeatureSetConfig,
    FeatureSetManifest,
)
from alpha_core.features.registry import FeatureRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_T0 = datetime(2024, 1, 1, tzinfo=UTC)


class _Const(feature_base.Feature):
    def __init__(self, name: str, value: float = 1.0) -> None:
        self._name = name
        self._value = value

    @property
    def name(self) -> str:
        return self._name

    @property
    def params(self) -> dict[str, float]:
        return {"value": self._value}

    def compute(
        self,
        data: pa.Table,
        *,
        instrument_id: str | None = None,
    ) -> feature_base.FeatureResult:
        del instrument_id
        return feature_base.FeatureResult(
            name=self._name,
            values=np.full(data.num_rows, self._value),
            computed_at=datetime.now(tz=UTC),
            params=self.params,
        )


def _make_registry(*feature_names: str) -> FeatureRegistry:
    reg = FeatureRegistry()
    for name in feature_names:
        reg.register(_Const(name))
    return reg


def _make_trade_table(n: int = 6) -> pa.Table:
    return pa.table({
        "instrument_id": ["a"] * n,
        "price": pa.array([0.5] * n, pa.float64()),
        "size": pa.array([1.0] * n, pa.float64()),
        "ts_event": pa.array(
            [_T0 + timedelta(minutes=i) for i in range(n)],
            pa.timestamp("us", tz="UTC"),
        ),
    })


def _mock_dataset(table: pa.Table | None = None) -> MagicMock:
    """Return a mock GoldDataset whose trades() returns *table*."""
    ds = MagicMock()
    ds.trades.return_value = table if table is not None else _make_trade_table()
    return ds


# ---------------------------------------------------------------------------
# FeatureSetConfig
# ---------------------------------------------------------------------------

class TestFeatureSetConfig:
    def test_basic_construction(self) -> None:
        cfg = FeatureSetConfig(name="my_set", dataset_id="ds_001", features=["f1", "f2"])
        assert cfg.name == "my_set"
        assert cfg.dataset_id == "ds_001"
        assert cfg.features == ["f1", "f2"]

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(Exception):
            FeatureSetConfig(name="x", dataset_id="y", features=["f"], unknown_field="bad")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# FeatureSetBuilder.build
# ---------------------------------------------------------------------------

class TestFeatureSetBuilderBuild:
    def test_build_writes_parquet_and_meta(self, tmp_path: Path) -> None:
        reg = _make_registry("feat_one")
        builder = FeatureSetBuilder(registry=reg, storage_root=tmp_path)
        cfg = FeatureSetConfig(name="test_set", dataset_id="ds1", features=["feat_one"])
        path = builder.build(cfg, _mock_dataset())
        assert path.exists()
        assert (path.parent / "_meta.json").exists()

    def test_build_returns_correct_path(self, tmp_path: Path) -> None:
        reg = _make_registry("feat_two")
        builder = FeatureSetBuilder(registry=reg, storage_root=tmp_path)
        cfg = FeatureSetConfig(name="my_features", dataset_id="ds1", features=["feat_two"])
        path = builder.build(cfg, _mock_dataset())
        assert path.name == "features.parquet"
        assert "my_features" in str(path)

    def test_build_duplicate_name_raises_file_exists(self, tmp_path: Path) -> None:
        reg = _make_registry("f")
        builder = FeatureSetBuilder(registry=reg, storage_root=tmp_path)
        cfg = FeatureSetConfig(name="dup_set", dataset_id="ds1", features=["f"])
        builder.build(cfg, _mock_dataset())
        with pytest.raises(FileExistsError):
            builder.build(cfg, _mock_dataset())

    def test_build_unknown_feature_raises_value_error(self, tmp_path: Path) -> None:
        reg = _make_registry("known")
        builder = FeatureSetBuilder(registry=reg, storage_root=tmp_path)
        cfg = FeatureSetConfig(name="bad_set", dataset_id="ds1", features=["unknown_feat"])
        with pytest.raises(ValueError, match="not registered"):
            builder.build(cfg, _mock_dataset())


# ---------------------------------------------------------------------------
# FeatureSetBuilder.load
# ---------------------------------------------------------------------------

class TestFeatureSetBuilderLoad:
    def test_load_returns_table_with_feature_columns(self, tmp_path: Path) -> None:
        reg = _make_registry("feat_load")
        builder = FeatureSetBuilder(registry=reg, storage_root=tmp_path)
        cfg = FeatureSetConfig(name="loadable", dataset_id="ds1", features=["feat_load"])
        builder.build(cfg, _mock_dataset())
        table = builder.load("loadable")
        assert isinstance(table, pa.Table)
        assert "feat_load" in table.schema.names

    def test_load_missing_raises_file_not_found(self, tmp_path: Path) -> None:
        reg = _make_registry()
        builder = FeatureSetBuilder(registry=reg, storage_root=tmp_path)
        with pytest.raises(FileNotFoundError):
            builder.load("nonexistent")


# ---------------------------------------------------------------------------
# FeatureSetBuilder.load_manifest
# ---------------------------------------------------------------------------

class TestFeatureSetBuilderManifest:
    def test_manifest_roundtrip(self, tmp_path: Path) -> None:
        reg = _make_registry("feat_m")
        builder = FeatureSetBuilder(registry=reg, storage_root=tmp_path)
        cfg = FeatureSetConfig(name="manifested", dataset_id="ds99", features=["feat_m"])
        builder.build(cfg, _mock_dataset())
        manifest = builder.load_manifest("manifested")
        assert isinstance(manifest, FeatureSetManifest)
        assert manifest.feature_set_name == "manifested"
        assert manifest.dataset_id == "ds99"
        assert "feat_m" in manifest.features

    def test_manifest_has_row_count(self, tmp_path: Path) -> None:
        table = _make_trade_table(n=10)
        reg = _make_registry("feat_r")
        builder = FeatureSetBuilder(registry=reg, storage_root=tmp_path)
        cfg = FeatureSetConfig(name="row_check", dataset_id="ds1", features=["feat_r"])
        builder.build(cfg, _mock_dataset(table))
        manifest = builder.load_manifest("row_check")
        assert manifest.row_count == 10


# ---------------------------------------------------------------------------
# FeatureSetBuilder.list_feature_sets
# ---------------------------------------------------------------------------

class TestListFeatureSets:
    def test_empty_root_returns_empty(self, tmp_path: Path) -> None:
        reg = _make_registry()
        builder = FeatureSetBuilder(registry=reg, storage_root=tmp_path)
        assert builder.list_feature_sets() == []

    def test_lists_after_build(self, tmp_path: Path) -> None:
        reg = _make_registry("f1", "f2")
        builder = FeatureSetBuilder(registry=reg, storage_root=tmp_path)
        cfg_a = FeatureSetConfig(name="set_alpha", dataset_id="ds1", features=["f1"])
        cfg_b = FeatureSetConfig(name="set_beta", dataset_id="ds1", features=["f2"])
        builder.build(cfg_a, _mock_dataset())
        builder.build(cfg_b, _mock_dataset())
        names = builder.list_feature_sets()
        assert names == sorted(["set_alpha", "set_beta"])
