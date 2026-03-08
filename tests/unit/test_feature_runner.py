"""Unit tests for alpha_core.research.feature_runner."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import alpha_core.features.factor_pack as factor_pack_mod
import alpha_core.research.feature_runner as feature_runner_mod

_BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _write_trades_dataset(storage_root: Path, dataset_id: str = "ds_pm") -> None:
    dataset_dir = storage_root / "gold" / "datasets" / dataset_id
    dataset_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table(
            {
                "event_id": ["e1", "e2"],
                "instrument_id": ["kalshi:m1:yes", "polymarket:m1:yes"],
                "venue_id": ["kalshi", "polymarket"],
                "event_type": ["trade", "trade"],
                "ts_event": pa.array(
                    [_BASE, _BASE + timedelta(minutes=1)],
                    type=pa.timestamp("us", tz="UTC"),
                ),
                "ts_record": pa.array(
                    [_BASE, _BASE + timedelta(minutes=1)],
                    type=pa.timestamp("us", tz="UTC"),
                ),
                "price": [0.4, 0.5],
                "size": [100.0, 120.0],
            }
        ),
        dataset_dir / "trades.parquet",
        compression="zstd",
    )


def test_resolve_factor_pack_chain_honors_expected_version(tmp_path: Path) -> None:
    packs_dir = tmp_path / "config" / "research" / "factor_packs"
    packs_dir.mkdir(parents=True)
    factor_pack_mod.save_factor_pack(
        factor_pack_mod.FactorPackManifest(pack_id="momentum", version="1.0.0"),
        packs_dir / "momentum_v1.yaml",
    )
    factor_pack_mod.save_factor_pack(
        factor_pack_mod.FactorPackManifest(pack_id="momentum", version="2.0.0"),
        packs_dir / "momentum_v2.yaml",
    )

    with patch(
        "alpha_core.research.feature_runner.config_paths.find_project_root",
        return_value=tmp_path,
    ):
        chain = feature_runner_mod.resolve_factor_pack_chain(
            "momentum",
            expected_version="1.0.0",
        )

    assert [(pack.pack_id, pack.version) for pack in chain] == [("momentum", "1.0.0")]


def test_pm_factor_pack_requires_supporting_metadata_and_books(tmp_path: Path) -> None:
    _write_trades_dataset(tmp_path)
    runner = feature_runner_mod.FeatureRunner(tmp_path)

    with pytest.raises(feature_runner_mod.FeatureRunError, match=r"instruments\.parquet"):
        runner.build(
            feature_runner_mod.FeatureConfig(
                dataset_id="ds_pm",
                feature_set_version="v1",
                factor_pack_id="pm_core",
                factor_pack_version="1.0.0",
            )
        )
