"""Unit tests for alpha_core.features.factor_pack."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from alpha_core.features.factor_pack import (
    FactorPackManifest,
    load_factor_pack,
    resolve_dependency_order,
    save_factor_pack,
    validate_dependencies,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent.parent


def _make_pack(
    pack_id: str = "base",
    version: str = "1.0.0",
    dependencies: list[str] | None = None,
    output_schema: dict[str, str] | None = None,
    parameters: dict[str, Any] | None = None,
) -> FactorPackManifest:
    return FactorPackManifest(
        pack_id=pack_id,
        version=version,
        description="test pack",
        dependencies=dependencies or [],
        output_schema=output_schema or {},
        parameters=parameters or {},
    )


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestFactorPackManifestSchema:
    def test_minimal_valid(self) -> None:
        pack = FactorPackManifest(pack_id="my_pack", version="0.1.0")
        assert pack.pack_id == "my_pack"
        assert pack.version == "0.1.0"
        assert pack.description == ""
        assert pack.dependencies == []
        assert pack.output_schema == {}
        assert pack.parameters == {}

    def test_full_valid(self) -> None:
        pack = _make_pack(
            pack_id="momentum",
            version="1.2.3",
            dependencies=["base"],
            output_schema={"score": "float64", "rank": "int32"},
            parameters={"lookback": 20},
        )
        assert pack.pack_id == "momentum"
        assert pack.dependencies == ["base"]
        assert pack.output_schema["score"] == "float64"
        assert pack.parameters["lookback"] == 20

    def test_missing_pack_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            FactorPackManifest(version="1.0.0")  # type: ignore[call-arg]

    def test_missing_version_raises(self) -> None:
        with pytest.raises(ValidationError):
            FactorPackManifest(pack_id="bad")  # type: ignore[call-arg]

    def test_blank_pack_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            FactorPackManifest(pack_id="   ", version="1.0.0")

    def test_blank_version_raises(self) -> None:
        with pytest.raises(ValidationError):
            FactorPackManifest(pack_id="ok", version="")

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            FactorPackManifest(pack_id="ok", version="1.0.0", unknown_field="oops")  # type: ignore[call-arg]

    def test_pack_id_whitespace_stripped(self) -> None:
        pack = FactorPackManifest(pack_id="  my_pack  ", version="1.0.0")
        assert pack.pack_id == "my_pack"

    def test_version_whitespace_stripped(self) -> None:
        pack = FactorPackManifest(pack_id="x", version="  2.0.0  ")
        assert pack.version == "2.0.0"

    def test_parameters_any_values(self) -> None:
        pack = _make_pack(parameters={"nested": {"a": 1}, "flag": True, "items": [1, 2]})
        assert pack.parameters["nested"]["a"] == 1
        assert pack.parameters["flag"] is True


# ---------------------------------------------------------------------------
# I/O round-trip
# ---------------------------------------------------------------------------


class TestFactorPackIO:
    def test_save_and_load_yaml(self, tmp_path: Path) -> None:
        pack = _make_pack(
            pack_id="io_test",
            output_schema={"col_a": "float64"},
            parameters={"window": 10},
        )
        dest = tmp_path / "io_test.yaml"
        save_factor_pack(pack, dest)
        loaded = load_factor_pack(dest)
        assert loaded.pack_id == pack.pack_id
        assert loaded.version == pack.version
        assert loaded.output_schema == pack.output_schema
        assert loaded.parameters == pack.parameters

    def test_save_and_load_json(self, tmp_path: Path) -> None:
        pack = _make_pack(pack_id="json_pack", dependencies=["dep1"])
        dest = tmp_path / "json_pack.json"
        save_factor_pack(pack, dest)
        loaded = load_factor_pack(dest)
        assert loaded.pack_id == "json_pack"
        assert loaded.dependencies == ["dep1"]

    def test_load_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_factor_pack(tmp_path / "nonexistent.yaml")

    def test_load_invalid_schema_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text(yaml.dump({"version": "1.0.0"}), encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid factor-pack"):
            load_factor_pack(bad)

    def test_load_example_yaml(self) -> None:
        example = REPO_ROOT / "config" / "research" / "factor_packs" / "example.yaml"
        if not example.exists():
            pytest.skip("example.yaml not present")
        pack = load_factor_pack(example)
        assert pack.pack_id
        assert pack.version

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        pack = _make_pack(pack_id="nested_pack")
        dest = tmp_path / "a" / "b" / "c" / "pack.yaml"
        save_factor_pack(pack, dest)
        assert dest.exists()

    def test_yaml_round_trip_preserves_order(self, tmp_path: Path) -> None:
        pack = _make_pack(
            pack_id="ordered",
            output_schema={"z_col": "float64", "a_col": "int32"},
        )
        dest = tmp_path / "ordered.yaml"
        save_factor_pack(pack, dest)
        loaded = load_factor_pack(dest)
        assert set(loaded.output_schema.keys()) == {"z_col", "a_col"}

    def test_json_round_trip_preserves_parameters(self, tmp_path: Path) -> None:
        params = {"alpha": 0.01, "beta": 2, "labels": ["a", "b"]}
        pack = _make_pack(pack_id="param_pack", parameters=params)
        dest = tmp_path / "param_pack.json"
        save_factor_pack(pack, dest)
        raw = json.loads(dest.read_text())
        assert raw["parameters"]["alpha"] == 0.01
        assert raw["parameters"]["labels"] == ["a", "b"]


# ---------------------------------------------------------------------------
# resolve_dependency_order
# ---------------------------------------------------------------------------


class TestResolveDependencyOrder:
    def test_single_pack_no_deps(self) -> None:
        pack = _make_pack(pack_id="p")
        result = resolve_dependency_order([pack])
        assert [r.pack_id for r in result] == ["p"]

    def test_linear_chain(self) -> None:
        a = _make_pack(pack_id="a")
        b = _make_pack(pack_id="b", dependencies=["a"])
        c = _make_pack(pack_id="c", dependencies=["b"])
        result = resolve_dependency_order([c, b, a])
        ids = [p.pack_id for p in result]
        assert ids.index("a") < ids.index("b") < ids.index("c")

    def test_diamond_dag(self) -> None:
        root = _make_pack(pack_id="root")
        left = _make_pack(pack_id="left", dependencies=["root"])
        right = _make_pack(pack_id="right", dependencies=["root"])
        top = _make_pack(pack_id="top", dependencies=["left", "right"])
        result = resolve_dependency_order([top, right, left, root])
        ids = [p.pack_id for p in result]
        assert ids.index("root") < ids.index("left")
        assert ids.index("root") < ids.index("right")
        assert ids.index("left") < ids.index("top")
        assert ids.index("right") < ids.index("top")

    def test_missing_dependency_raises(self) -> None:
        a = _make_pack(pack_id="a", dependencies=["missing"])
        with pytest.raises(ValueError, match="missing"):
            resolve_dependency_order([a])

    def test_cycle_raises(self) -> None:
        a = _make_pack(pack_id="a", dependencies=["b"])
        b = _make_pack(pack_id="b", dependencies=["a"])
        with pytest.raises(ValueError, match=r"[Cc]ircular"):
            resolve_dependency_order([a, b])

    def test_self_loop_raises(self) -> None:
        a = _make_pack(pack_id="a", dependencies=["a"])
        with pytest.raises(ValueError):
            resolve_dependency_order([a])

    def test_empty_list(self) -> None:
        assert resolve_dependency_order([]) == []

    def test_deterministic(self) -> None:
        packs = [
            _make_pack(pack_id="z"),
            _make_pack(pack_id="m"),
            _make_pack(pack_id="a"),
        ]
        r1 = [p.pack_id for p in resolve_dependency_order(packs)]
        r2 = [p.pack_id for p in resolve_dependency_order(packs)]
        assert r1 == r2

    def test_multiple_roots(self) -> None:
        r1 = _make_pack(pack_id="r1")
        r2 = _make_pack(pack_id="r2")
        child = _make_pack(pack_id="child", dependencies=["r1", "r2"])
        result = resolve_dependency_order([child, r2, r1])
        ids = [p.pack_id for p in result]
        assert ids.index("r1") < ids.index("child")
        assert ids.index("r2") < ids.index("child")


# ---------------------------------------------------------------------------
# validate_dependencies
# ---------------------------------------------------------------------------


class TestValidateDependencies:
    def test_no_deps_always_passes(self) -> None:
        pack = _make_pack(pack_id="solo")
        validate_dependencies(pack, available_packs=[])  # no exception

    def test_deps_present_passes(self) -> None:
        dep = _make_pack(pack_id="dep1")
        pack = _make_pack(pack_id="consumer", dependencies=["dep1"])
        validate_dependencies(pack, available_packs=[dep])  # no exception

    def test_missing_dep_raises(self) -> None:
        pack = _make_pack(pack_id="consumer", dependencies=["ghost"])
        with pytest.raises(ValueError, match="ghost"):
            validate_dependencies(pack, available_packs=[])

    def test_partial_deps_raises(self) -> None:
        dep = _make_pack(pack_id="present")
        pack = _make_pack(pack_id="consumer", dependencies=["present", "absent"])
        with pytest.raises(ValueError, match="absent"):
            validate_dependencies(pack, available_packs=[dep])

    def test_multiple_missing_deps_all_listed(self) -> None:
        pack = _make_pack(pack_id="multi", dependencies=["a", "b", "c"])
        with pytest.raises(ValueError) as exc_info:
            validate_dependencies(pack, available_packs=[])
        msg = str(exc_info.value)
        assert "a" in msg and "b" in msg and "c" in msg
