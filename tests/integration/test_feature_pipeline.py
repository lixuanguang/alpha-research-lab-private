"""Integration tests for the end-to-end feature computation pipeline.

These tests exercise the full flow:
    raw trade table → FeatureRegistry.compute_all → enriched table with feature columns
and (for FeatureSetBuilder tests) the persistence layer with a mock GoldDataset.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pyarrow as pa
import pytest

import alpha_core.features.base as feature_base
from alpha_core.features.feature_set import FeatureSetBuilder, FeatureSetConfig
from alpha_core.features.pm_specific import (
    ImpliedProbMomentum,
    ProbAcceleration,
    VolumeWeightedProb,
)
from alpha_core.features.primitives import RollingMean, RollingStd
from alpha_core.features.registry import FeatureRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _trade_table(n: int = 40, num_instruments: int = 1) -> pa.Table:
    """Synthetic trade table with predictable drifting prices."""
    rows_per_instrument = n // num_instruments
    instr_ids: list[str] = []
    prices: list[float] = []
    sizes: list[float] = []
    ts_list: list[datetime] = []

    for idx in range(num_instruments):
        instr = f"instr_{idx}"
        for i in range(rows_per_instrument):
            instr_ids.append(instr)
            prices.append(0.3 + 0.01 * math.sin(i * 0.3 + idx))
            sizes.append(1.0 + float(i % 5))
            ts_list.append(_T0 + timedelta(minutes=i + idx * rows_per_instrument))

    return pa.table({
        "instrument_id": pa.array(instr_ids, pa.string()),
        "price": pa.array(prices, pa.float64()),
        "size": pa.array(sizes, pa.float64()),
        "ts_event": pa.array(ts_list, pa.timestamp("us", tz="UTC")),
    })


def _mock_dataset(table: pa.Table) -> MagicMock:
    ds = MagicMock()
    ds.trades.return_value = table
    return ds


class _OnesFeature(feature_base.Feature):
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def params(self) -> dict[str, object]:
        return {}

    def compute(
        self,
        data: pa.Table,
        *,
        instrument_id: str | None = None,
    ) -> feature_base.FeatureResult:
        del instrument_id
        return feature_base.FeatureResult(
            name=self._name,
            values=np.ones(data.num_rows),
            computed_at=datetime.now(tz=UTC),
            params={},
        )


# ---------------------------------------------------------------------------
# Integration: FeatureRegistry.compute_all
# ---------------------------------------------------------------------------

class TestRegistryComputeAllIntegration:
    def test_single_primitive_appends_column(self) -> None:
        reg = FeatureRegistry()
        reg.register(RollingMean(window=5))
        t = _trade_table(n=20)
        enriched = reg.compute_all(t)
        assert "rolling_mean_price_5" in enriched.schema.names
        assert enriched.num_rows == t.num_rows

    def test_dependency_chain_computed_in_order(self) -> None:
        """ZScore depends on the source column, not another feature here.
        Use ProbAcceleration (fast EWM - slow EWM) to verify a two-step computation."""
        reg = FeatureRegistry()
        reg.register(ProbAcceleration(fast=3, slow=10))
        t = _trade_table(n=30)
        enriched = reg.compute_all(t)
        assert "prob_acceleration_3_10" in enriched.schema.names

    def test_multiple_primitives_all_present(self) -> None:
        reg = FeatureRegistry()
        reg.register(RollingMean(window=5))
        reg.register(RollingStd(window=5))
        reg.register(VolumeWeightedProb(window=5))
        t = _trade_table(n=25)
        enriched = reg.compute_all(t)
        for col in ["rolling_mean_price_5", "rolling_std_price_5", "volume_weighted_prob_5"]:
            assert col in enriched.schema.names

    def test_multi_instrument_no_cross_bleed(self) -> None:
        """RollingMean for instrument 0 must not be influenced by instrument 1 data."""
        reg = FeatureRegistry()
        reg.register(RollingMean(window=3))
        t = _trade_table(n=6, num_instruments=2)  # 3 rows each

        # Compute per-instrument separately.
        import pyarrow.compute as pc

        mask_a = pc.equal(t.column("instrument_id"), "instr_0")
        t_a = t.filter(mask_a)

        enriched = reg.compute_all(t)
        enriched_a = enriched.filter(pc.equal(enriched.column("instrument_id"), "instr_0"))
        enriched_a_solo = reg.compute_all(t_a)

        vals_joint = enriched_a.column("rolling_mean_price_3").to_pylist()
        vals_solo = enriched_a_solo.column("rolling_mean_price_3").to_pylist()
        # Values should match whether computed together or in isolation.
        for j, s in zip(vals_joint, vals_solo):
            if math.isnan(j) and math.isnan(s):
                continue
            assert j == pytest.approx(s, rel=1e-6)

    def test_sufficient_history_yields_non_nan_tail(self) -> None:
        reg = FeatureRegistry()
        window = 5
        reg.register(RollingMean(window=window))
        t = _trade_table(n=30)
        enriched = reg.compute_all(t)
        vals = enriched.column("rolling_mean_price_5").to_pylist()
        # The last several values must be non-NaN.
        assert not any(math.isnan(v) for v in vals[-5:])


# ---------------------------------------------------------------------------
# Integration: FeatureSetBuilder end-to-end
# ---------------------------------------------------------------------------

class TestFeatureSetBuilderIntegration:
    def test_build_and_load_roundtrip(self, tmp_path: Path) -> None:
        table = _trade_table(n=20)
        reg = FeatureRegistry()
        reg.register(RollingMean(window=5))
        reg.register(ImpliedProbMomentum(window=5))
        builder = FeatureSetBuilder(registry=reg, storage_root=tmp_path)
        cfg = FeatureSetConfig(
            name="e2e_set",
            dataset_id="test_ds",
            features=["rolling_mean_price_5", "implied_prob_momentum_5"],
        )
        builder.build(cfg, _mock_dataset(table))
        loaded = builder.load("e2e_set")
        assert "rolling_mean_price_5" in loaded.schema.names
        assert "implied_prob_momentum_5" in loaded.schema.names
        assert loaded.num_rows == table.num_rows

    def test_manifest_feature_count_matches_config(self, tmp_path: Path) -> None:
        table = _trade_table(n=15)
        reg = FeatureRegistry()
        for name_suffix in ["a", "b", "c"]:
            reg.register(_OnesFeature(f"feat_{name_suffix}"))

        builder = FeatureSetBuilder(registry=reg, storage_root=tmp_path)
        cfg = FeatureSetConfig(
            name="count_check",
            dataset_id="ds1",
            features=["feat_a", "feat_b", "feat_c"],
        )
        builder.build(cfg, _mock_dataset(table))
        manifest = builder.load_manifest("count_check")
        assert manifest.column_count == 3
        assert manifest.row_count == table.num_rows
