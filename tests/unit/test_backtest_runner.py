"""Unit tests for alpha_core.research.backtest_runner."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import alpha_core.research.artifact_paths as artifact_paths
import alpha_core.research.backtest_runner as backtest_runner_mod

_BASE = datetime(2026, 1, 1, tzinfo=UTC)
_FEATURE_RUN_ID = "feature_run_001"


def _write_recipe_features(
    storage_root: Path,
    *,
    factor_pack_id: str = "momentum",
    dataset_id: str = "ds_001",
    feature_set_version: str = "v1",
    frame: pd.DataFrame | None = None,
) -> None:
    features_path = artifact_paths.artifact_key_path(
        storage_root,
        _FEATURE_RUN_ID,
        "features.parquet",
    )
    features_path.parent.mkdir(parents=True, exist_ok=True)
    feature_frame = (
        frame
        if frame is not None
        else pd.DataFrame(
            {
                "instrument_id": ["p:m1:yes", "p:m1:yes"],
                "ts_event": [
                    _BASE,
                    _BASE + timedelta(hours=1),
                ],
                "price": [0.50, 0.51],
                "price_zscore_20": [2.0, -2.0],
                "price_zscore_50": [2.0, -2.0],
                "rolling_return_10": [0.01, 0.02],
                "rolling_return_20": [0.01, 0.02],
            }
        )
    )
    table = pa.Table.from_pandas(
        feature_frame,
        preserve_index=False,
    )
    pq.write_table(table, features_path, compression="zstd")

    feature_manifest_path = artifact_paths.artifact_key_path(
        storage_root,
        _FEATURE_RUN_ID,
        "feature_manifest.json",
    )
    feature_names = [
        column_name
        for column_name in feature_frame.columns
        if column_name not in {"instrument_id", "price", "ts_available", "ts_event"}
    ]
    feature_manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "run_id": _FEATURE_RUN_ID,
                "dataset_id": dataset_id,
                "feature_set_version": feature_set_version,
                "built_at": _BASE.isoformat(),
                "lookback_bars": 50,
                "row_count": len(feature_frame),
                "feature_count": len(feature_names),
                "feature_names": feature_names,
                "artifacts": {"features": str(features_path)},
                "parent_run_id": None,
                "factor_pack_id": factor_pack_id,
                "factor_pack_version": "1.0.0",
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def test_build_uses_strategy_recipe_defaults(tmp_path: Path) -> None:
    _write_recipe_features(tmp_path)

    runner = backtest_runner_mod.BacktestRunner(tmp_path)
    manifest = runner.build(
        backtest_runner_mod.BacktestConfig(
            dataset_id="ds_001",
            feature_set_version="v1",
            strategy_id="zscore_momentum_v1",
            strategy_recipe_id="zscore_momentum",
        ),
        parent_run_id=_FEATURE_RUN_ID,
    )

    trades = pq.read_table(
        artifact_paths.artifact_key_path(tmp_path, manifest.run_id, "trades.parquet")
    ).to_pandas()
    assert manifest.strategy_recipe_id == "zscore_momentum"
    assert manifest.strategy_recipe_version == "1.0.0"
    assert trades.iloc[0]["size"] == pytest.approx(100_000.0 * 0.05 / 0.51)
    assert trades.iloc[0]["price"] == pytest.approx(0.51 * 1.0002)


def test_build_rejects_mismatched_feature_pack_metadata(tmp_path: Path) -> None:
    _write_recipe_features(tmp_path, factor_pack_id="generic_features")

    runner = backtest_runner_mod.BacktestRunner(tmp_path)
    with pytest.raises(backtest_runner_mod.BacktestRunError, match="factor_pack_id='momentum'"):
        runner.build(
            backtest_runner_mod.BacktestConfig(
                dataset_id="ds_001",
                feature_set_version="v1",
                strategy_id="zscore_momentum_v1",
                strategy_recipe_id="zscore_momentum",
            ),
            parent_run_id=_FEATURE_RUN_ID,
        )


def test_build_rejects_mismatched_feature_dataset_lineage(tmp_path: Path) -> None:
    _write_recipe_features(tmp_path, dataset_id="ds_other")

    runner = backtest_runner_mod.BacktestRunner(tmp_path)
    with pytest.raises(backtest_runner_mod.BacktestRunError, match="dataset_id"):
        runner.build(
            backtest_runner_mod.BacktestConfig(
                dataset_id="ds_001",
                feature_set_version="v1",
                strategy_id="zscore_v1",
            ),
            parent_run_id=_FEATURE_RUN_ID,
        )


def test_build_rejects_missing_backtest_feature_columns(tmp_path: Path) -> None:
    _write_recipe_features(
        tmp_path,
        frame=pd.DataFrame(
            {
                "instrument_id": ["p:m1:yes"],
                "ts_event": [_BASE],
                "price": [0.50],
            }
        ),
    )

    runner = backtest_runner_mod.BacktestRunner(tmp_path)
    with pytest.raises(
        backtest_runner_mod.BacktestRunError,
        match="Feature artifact does not satisfy the backtest input contract",
    ):
        runner.build(
            backtest_runner_mod.BacktestConfig(
                dataset_id="ds_001",
                feature_set_version="v1",
                strategy_id="zscore_v1",
            ),
            parent_run_id=_FEATURE_RUN_ID,
        )


def test_build_delays_fill_until_strictly_later_timestamp(tmp_path: Path) -> None:
    _write_recipe_features(
        tmp_path,
        factor_pack_id="momentum",
        frame=pd.DataFrame(
            {
                "instrument_id": ["p:m1:yes", "p:m1:yes", "p:m1:yes"],
                "ts_event": [
                    _BASE,
                    _BASE,
                    _BASE + timedelta(hours=1),
                ],
                "price": [0.50, 0.51, 0.52],
                "price_zscore_20": [2.0, 2.0, -2.0],
                "price_zscore_50": [2.0, 2.0, -2.0],
                "rolling_return_10": [0.01, 0.01, 0.01],
                "rolling_return_20": [0.02, 0.02, 0.02],
            }
        ),
    )

    runner = backtest_runner_mod.BacktestRunner(tmp_path)
    manifest = runner.build(
        backtest_runner_mod.BacktestConfig(
            dataset_id="ds_001",
            feature_set_version="v1",
            strategy_id="zscore_v1",
        ),
        parent_run_id=_FEATURE_RUN_ID,
    )

    trades = pq.read_table(
        artifact_paths.artifact_key_path(tmp_path, manifest.run_id, "trades.parquet")
    ).to_pandas()
    assert not trades.empty
    assert trades.iloc[0]["ts_event"] > _BASE
