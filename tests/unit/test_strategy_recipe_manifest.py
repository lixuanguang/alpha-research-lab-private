"""Unit tests for alpha_core.research.strategy_recipe."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from alpha_core.research.strategy_recipe import (
    ExecutionTemplate,
    RiskTemplate,
    StrategyRecipeManifest,
    load_strategy_recipe,
    save_strategy_recipe,
    validate_recipe,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent.parent


def _make_recipe(
    recipe_id: str = "test_recipe",
    version: str = "1.0.0",
    factor_pack_ids: list[str] | None = None,
    strategy_params: dict | None = None,
    risk_kwargs: dict | None = None,
    exec_kwargs: dict | None = None,
) -> StrategyRecipeManifest:
    return StrategyRecipeManifest(
        recipe_id=recipe_id,
        version=version,
        description="unit-test recipe",
        factor_pack_ids=factor_pack_ids or [],
        risk_template=RiskTemplate(**(risk_kwargs or {})),
        execution_template=ExecutionTemplate(**(exec_kwargs or {})),
        strategy_params=strategy_params or {},
    )


# ---------------------------------------------------------------------------
# RiskTemplate / ExecutionTemplate schema
# ---------------------------------------------------------------------------


class TestSubTemplatesSchema:
    def test_risk_defaults(self) -> None:
        rt = RiskTemplate()
        assert rt.max_position_pct == pytest.approx(0.10)
        assert rt.max_drawdown_pct == pytest.approx(0.20)
        assert rt.min_trade_count == 0

    def test_execution_defaults(self) -> None:
        et = ExecutionTemplate()
        assert et.fee_bps == pytest.approx(5.0)
        assert et.slippage_bps == pytest.approx(2.0)
        assert et.fill_model == "immediate"

    def test_risk_custom_values(self) -> None:
        rt = RiskTemplate(max_position_pct=0.05, max_drawdown_pct=0.15, min_trade_count=50)
        assert rt.max_position_pct == pytest.approx(0.05)
        assert rt.min_trade_count == 50

    def test_execution_custom_fill_model(self) -> None:
        et = ExecutionTemplate(fill_model="vwap_approx")
        assert et.fill_model == "vwap_approx"

    def test_risk_extra_fields_allowed(self) -> None:
        # RiskTemplate uses extra="allow"
        rt = RiskTemplate(custom_guard=0.99)  # type: ignore[call-arg]
        assert rt.custom_guard == 0.99  # type: ignore[attr-defined]

    def test_risk_max_position_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            RiskTemplate(max_position_pct=0.0)

    def test_risk_max_position_above_one_raises(self) -> None:
        with pytest.raises(ValidationError):
            RiskTemplate(max_position_pct=1.5)

    def test_execution_negative_fee_raises(self) -> None:
        with pytest.raises(ValidationError):
            ExecutionTemplate(fee_bps=-1.0)


# ---------------------------------------------------------------------------
# StrategyRecipeManifest schema
# ---------------------------------------------------------------------------


class TestStrategyRecipeManifestSchema:
    def test_minimal_valid(self) -> None:
        recipe = StrategyRecipeManifest(recipe_id="simple", version="0.1.0")
        assert recipe.recipe_id == "simple"
        assert recipe.description == ""
        assert recipe.factor_pack_ids == []
        assert recipe.strategy_params == {}

    def test_full_valid(self) -> None:
        recipe = _make_recipe(
            recipe_id="full",
            version="2.0.0",
            factor_pack_ids=["momentum", "microstructure"],
            strategy_params={"threshold": 1.5, "weight": 0.05},
        )
        assert recipe.factor_pack_ids == ["momentum", "microstructure"]
        assert recipe.strategy_params["threshold"] == 1.5

    def test_missing_recipe_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            StrategyRecipeManifest(version="1.0.0")  # type: ignore[call-arg]

    def test_missing_version_raises(self) -> None:
        with pytest.raises(ValidationError):
            StrategyRecipeManifest(recipe_id="x")  # type: ignore[call-arg]

    def test_blank_recipe_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            StrategyRecipeManifest(recipe_id="", version="1.0.0")

    def test_blank_version_raises(self) -> None:
        with pytest.raises(ValidationError):
            StrategyRecipeManifest(recipe_id="x", version="   ")

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            StrategyRecipeManifest(recipe_id="x", version="1.0.0", evil_field="hack")  # type: ignore[call-arg]

    def test_recipe_id_whitespace_stripped(self) -> None:
        recipe = StrategyRecipeManifest(recipe_id="  my_recipe  ", version="1.0.0")
        assert recipe.recipe_id == "my_recipe"

    def test_version_whitespace_stripped(self) -> None:
        recipe = StrategyRecipeManifest(recipe_id="r", version="  3.0.0  ")
        assert recipe.version == "3.0.0"

    def test_strategy_params_any_values(self) -> None:
        recipe = _make_recipe(strategy_params={"nested": {"x": 1}, "flag": True})
        assert recipe.strategy_params["nested"]["x"] == 1


# ---------------------------------------------------------------------------
# canonical_id property
# ---------------------------------------------------------------------------


class TestCanonicalId:
    def test_format(self) -> None:
        recipe = _make_recipe(recipe_id="zscore_momentum", version="1.2.3")
        assert recipe.canonical_id == "zscore_momentum@1.2.3"

    def test_reflects_recipe_id_and_version(self) -> None:
        r1 = _make_recipe(recipe_id="r1", version="0.1.0")
        r2 = _make_recipe(recipe_id="r1", version="0.2.0")
        assert r1.canonical_id != r2.canonical_id
        assert r2.canonical_id.endswith("@0.2.0")

    def test_no_trailing_whitespace(self) -> None:
        recipe = _make_recipe(recipe_id="clean", version="1.0.0")
        assert " " not in recipe.canonical_id


# ---------------------------------------------------------------------------
# I/O round-trip
# ---------------------------------------------------------------------------


class TestStrategyRecipeIO:
    def test_save_and_load_yaml(self, tmp_path: Path) -> None:
        recipe = _make_recipe(
            recipe_id="io_test",
            factor_pack_ids=["momentum"],
            strategy_params={"threshold": 1.5},
        )
        dest = tmp_path / "io_test.yaml"
        save_strategy_recipe(recipe, dest)
        loaded = load_strategy_recipe(dest)
        assert loaded.recipe_id == recipe.recipe_id
        assert loaded.factor_pack_ids == recipe.factor_pack_ids
        assert loaded.strategy_params["threshold"] == pytest.approx(1.5)

    def test_save_and_load_json(self, tmp_path: Path) -> None:
        recipe = _make_recipe(recipe_id="json_recipe", version="2.0.0")
        dest = tmp_path / "recipe.json"
        save_strategy_recipe(recipe, dest)
        loaded = load_strategy_recipe(dest)
        assert loaded.canonical_id == "json_recipe@2.0.0"

    def test_load_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_strategy_recipe(tmp_path / "ghost.yaml")

    def test_load_invalid_schema_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text(yaml.dump({"version": "1.0.0"}), encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid strategy-recipe"):
            load_strategy_recipe(bad)

    def test_load_example_yaml(self) -> None:
        example = REPO_ROOT / "config" / "research" / "recipes" / "example.yaml"
        if not example.exists():
            pytest.skip("example.yaml not present")
        recipe = load_strategy_recipe(example)
        assert recipe.recipe_id
        assert recipe.version

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        recipe = _make_recipe(recipe_id="nested")
        dest = tmp_path / "a" / "b" / "recipe.yaml"
        save_strategy_recipe(recipe, dest)
        assert dest.exists()

    def test_json_round_trip_preserves_risk_template(self, tmp_path: Path) -> None:
        recipe = _make_recipe(
            recipe_id="risk_rt",
            risk_kwargs={"max_position_pct": 0.07, "min_trade_count": 25},
        )
        dest = tmp_path / "risk_rt.json"
        save_strategy_recipe(recipe, dest)
        raw = json.loads(dest.read_text())
        assert raw["risk_template"]["max_position_pct"] == pytest.approx(0.07)
        assert raw["risk_template"]["min_trade_count"] == 25

    def test_json_round_trip_preserves_execution_template(self, tmp_path: Path) -> None:
        recipe = _make_recipe(
            recipe_id="exec_rt",
            exec_kwargs={"fee_bps": 8.0, "fill_model": "vwap_approx"},
        )
        dest = tmp_path / "exec_rt.json"
        save_strategy_recipe(recipe, dest)
        raw = json.loads(dest.read_text())
        assert raw["execution_template"]["fee_bps"] == pytest.approx(8.0)
        assert raw["execution_template"]["fill_model"] == "vwap_approx"


# ---------------------------------------------------------------------------
# validate_recipe
# ---------------------------------------------------------------------------


class TestValidateRecipe:
    def test_empty_pack_ids_always_passes(self) -> None:
        recipe = _make_recipe(factor_pack_ids=[])
        validate_recipe(recipe, available_pack_ids=set())  # no exception

    def test_all_packs_available_passes(self) -> None:
        recipe = _make_recipe(factor_pack_ids=["momentum", "microstructure"])
        validate_recipe(recipe, available_pack_ids={"momentum", "microstructure", "extra"})

    def test_missing_single_pack_raises(self) -> None:
        recipe = _make_recipe(factor_pack_ids=["ghost"])
        with pytest.raises(ValueError, match="ghost"):
            validate_recipe(recipe, available_pack_ids=set())

    def test_partial_missing_raises(self) -> None:
        recipe = _make_recipe(factor_pack_ids=["momentum", "missing_pack"])
        with pytest.raises(ValueError, match="missing_pack"):
            validate_recipe(recipe, available_pack_ids={"momentum"})

    def test_multiple_missing_all_listed(self) -> None:
        recipe = _make_recipe(factor_pack_ids=["alpha", "beta", "gamma"])
        with pytest.raises(ValueError) as exc_info:
            validate_recipe(recipe, available_pack_ids=set())
        msg = str(exc_info.value)
        assert "alpha" in msg and "beta" in msg and "gamma" in msg

    def test_recipe_id_in_error_message(self) -> None:
        recipe = _make_recipe(recipe_id="my_strategy", factor_pack_ids=["absent"])
        with pytest.raises(ValueError, match="my_strategy"):
            validate_recipe(recipe, available_pack_ids=set())
