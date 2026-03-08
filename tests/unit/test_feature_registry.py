"""Unit tests for alpha_core.features.registry."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pyarrow as pa
import pytest

import alpha_core.features.base as feature_base
from alpha_core.features.registry import FeatureRegistry

# ---------------------------------------------------------------------------
# Minimal stub features
# ---------------------------------------------------------------------------

_T0 = datetime(2024, 1, 1, tzinfo=UTC)


class _Const(feature_base.Feature):
    """Always returns a constant array (value = self._val)."""

    def __init__(self, name: str, value: float = 1.0, deps: list[str] | None = None) -> None:
        self._name = name
        self._val = value
        self._deps = deps or []

    @property
    def name(self) -> str:
        return self._name

    @property
    def params(self) -> dict[str, float]:
        return {"value": self._val}

    @property
    def dependencies(self) -> list[str]:
        return self._deps

    def compute(
        self,
        data: pa.Table,
        *,
        instrument_id: str | None = None,
    ) -> feature_base.FeatureResult:
        n = data.num_rows
        del instrument_id
        return feature_base.FeatureResult(
            name=self._name,
            values=np.full(n, self._val),
            computed_at=datetime.now(tz=UTC),
            params=self.params,
        )


def _simple_table(n: int = 4) -> pa.Table:
    return pa.table({
        "instrument_id": ["a"] * n,
        "price": pa.array([0.5] * n, pa.float64()),
        "size": pa.array([1.0] * n, pa.float64()),
        "ts_event": pa.array(
            [_T0 + timedelta(minutes=i) for i in range(n)],
            pa.timestamp("us", tz="UTC"),
        ),
    })


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRegistration:
    def test_register_and_lookup(self) -> None:
        reg = FeatureRegistry()
        reg.register(_Const("feat_a"))
        assert "feat_a" in reg.registered

    def test_duplicate_name_raises(self) -> None:
        reg = FeatureRegistry()
        reg.register(_Const("feat_x"))
        with pytest.raises(ValueError, match="already registered"):
            reg.register(_Const("feat_x"))

    def test_unregistered_dep_raises(self) -> None:
        reg = FeatureRegistry()
        with pytest.raises(ValueError, match="unregistered"):
            reg.register(_Const("feat_child", deps=["feat_not_there"]))

    def test_dep_registered_first_allows_child(self) -> None:
        reg = FeatureRegistry()
        reg.register(_Const("parent"))
        reg.register(_Const("child", deps=["parent"]))
        assert "child" in reg.registered

    def test_registered_sorted_alphabetically(self) -> None:
        reg = FeatureRegistry()
        for name in ["zzz", "aaa", "mmm"]:
            reg.register(_Const(name))
        assert reg.registered == sorted(["zzz", "aaa", "mmm"])

    def test_deregister_removes_feature(self) -> None:
        reg = FeatureRegistry()
        reg.register(_Const("tmp"))
        assert "tmp" in reg.registered
        reg.deregister("tmp")
        assert "tmp" not in reg.registered

    def test_deregister_missing_raises_key_error(self) -> None:
        reg = FeatureRegistry()
        with pytest.raises(KeyError):
            reg.deregister("not_there")

    def test_deregister_with_dependant_raises(self) -> None:
        reg = FeatureRegistry()
        reg.register(_Const("parent"))
        reg.register(_Const("child", deps=["parent"]))
        with pytest.raises(ValueError, match="depended on"):
            reg.deregister("parent")


class TestComputeSingle:
    def test_compute_feature_known(self) -> None:
        reg = FeatureRegistry()
        reg.register(_Const("f1", value=42.0))
        t = _simple_table(4)
        result = reg.compute_feature("f1", t)
        assert result.name == "f1"
        assert all(v == 42.0 for v in result.values)

    def test_compute_feature_unknown_raises_key_error(self) -> None:
        reg = FeatureRegistry()
        with pytest.raises(KeyError):
            reg.compute_feature("ghost", _simple_table())


class TestComputeAll:
    def test_appends_columns_to_table(self) -> None:
        reg = FeatureRegistry()
        reg.register(_Const("f_alpha", 1.0))
        reg.register(_Const("f_beta", 2.0))
        t = _simple_table(3)
        result = reg.compute_all(t)
        assert "f_alpha" in result.schema.names
        assert "f_beta" in result.schema.names

    def test_features_subset(self) -> None:
        reg = FeatureRegistry()
        reg.register(_Const("only_this"))
        reg.register(_Const("not_this"))
        t = _simple_table(3)
        result = reg.compute_all(t, features=["only_this"])
        assert "only_this" in result.schema.names
        assert "not_this" not in result.schema.names

    def test_transitive_dep_included_automatically(self) -> None:
        reg = FeatureRegistry()
        reg.register(_Const("base_feat"))
        reg.register(_Const("derived_feat", deps=["base_feat"]))
        t = _simple_table(3)
        # Request only derived; base should be computed too.
        result = reg.compute_all(t, features=["derived_feat"])
        assert "base_feat" in result.schema.names
        assert "derived_feat" in result.schema.names

    def test_unknown_feature_in_subset_raises(self) -> None:
        reg = FeatureRegistry()
        reg.register(_Const("exists"))
        t = _simple_table()
        with pytest.raises(KeyError):
            reg.compute_all(t, features=["exists", "ghost"])

    def test_instrument_id_filter(self) -> None:
        reg = FeatureRegistry()
        reg.register(_Const("f"))
        # Build a table with two instruments.
        t = pa.table({
            "instrument_id": ["a", "a", "b", "b"],
            "price": pa.array([0.5] * 4, pa.float64()),
            "size": pa.array([1.0] * 4, pa.float64()),
            "ts_event": pa.array(
                [_T0 + timedelta(minutes=i) for i in range(4)],
                pa.timestamp("us", tz="UTC"),
            ),
        })
        result = reg.compute_all(t, instrument_ids=["a"])
        ids = result.column("instrument_id").to_pylist()
        assert set(ids) == {"a"}


class TestDependencyOrder:
    def test_no_deps_returns_all(self) -> None:
        reg = FeatureRegistry()
        for name in ["c", "a", "b"]:
            reg.register(_Const(name))
        order = reg.dependency_order()
        assert set(order) == {"a", "b", "c"}

    def test_dep_comes_before_dependent(self) -> None:
        reg = FeatureRegistry()
        reg.register(_Const("p"))
        reg.register(_Const("q", deps=["p"]))
        order = reg.dependency_order()
        assert order.index("p") < order.index("q")

    def test_cycle_raises(self) -> None:
        reg = FeatureRegistry()
        # Directly inject a cycle (bypass register validation).
        reg._features["x"] = _Const("x", deps=["y"])
        reg._features["y"] = _Const("y", deps=["x"])
        with pytest.raises(ValueError, match=r"[Cc]ycl"):
            reg.dependency_order()
