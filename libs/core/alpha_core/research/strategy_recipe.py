"""StrategyRecipeManifest — composes factor-packs with risk/execution templates.

A *strategy recipe* declares which factor packs a strategy depends on, default
risk and execution parameters, and any per-parameter overrides.  This lets
``backtest`` and ``build-features`` pipelines reference a single versioned
manifest instead of embedding configuration in notebooks.

Storage convention
------------------
Recipe manifests are YAML or JSON files.  Canonical location (by convention)::

    config/research/recipes/<recipe_id>_v<version>.yaml

Typical usage::

    import alpha_core.research.strategy_recipe as recipe_mod

    recipe = recipe_mod.load_strategy_recipe(
        Path("config/research/recipes/zscore_momentum_v1.yaml")
    )
    recipe_mod.validate_recipe(recipe, available_pack_ids={"momentum", "microstructure"})
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Sub-schemas
# ---------------------------------------------------------------------------


class RiskTemplate(BaseModel):
    """Default risk-guard parameters embedded in a strategy recipe."""

    model_config = ConfigDict(extra="allow")

    max_position_pct: float = Field(
        default=0.10,
        gt=0,
        le=1.0,
        description="Maximum single-instrument position as fraction of portfolio.",
    )
    max_drawdown_pct: float = Field(
        default=0.20,
        gt=0,
        le=1.0,
        description="Kill-switch drawdown threshold (fraction of peak equity).",
    )
    min_trade_count: int = Field(
        default=0,
        ge=0,
        description="Minimum trades required for a valid evaluation.",
    )


class ExecutionTemplate(BaseModel):
    """Default execution parameters embedded in a strategy recipe."""

    model_config = ConfigDict(extra="allow")

    fee_bps: float = Field(
        default=5.0,
        ge=0,
        description="Round-trip transaction cost in basis points.",
    )
    slippage_bps: float = Field(
        default=2.0,
        ge=0,
        description="Estimated slippage in basis points.",
    )
    resolution_fee_bps: float = Field(
        default=0.0,
        ge=0,
        description="Prediction-market settlement fee in basis points.",
    )
    fill_model: str = Field(
        default="immediate",
        description="Fill model identifier (e.g. 'immediate', 'vwap_approx').",
    )


# ---------------------------------------------------------------------------
# Top-level schema
# ---------------------------------------------------------------------------


class StrategyRecipeManifest(BaseModel):
    """Versioned contract composing factor packs + risk/execution templates.

    Fields
    ------
    recipe_id
        Stable identifier for this recipe (e.g. ``"zscore_momentum"``).
    version
        Semantic version string (e.g. ``"1.0.0"``).
    description
        Human-readable summary.
    factor_pack_ids
        Ordered list of ``pack_id`` strings this recipe depends on.
        The feature pipeline resolves these packs before computing features.
    risk_template
        Default risk parameters.  Overridable at run time.
    execution_template
        Default execution/fill parameters.  Overridable at run time.
    strategy_params
        Named parameter block (e.g. ``{"zscore_threshold": 1.5}``).
        These are passed directly to the strategy as ``strategy_params``.
    """

    model_config = ConfigDict(extra="forbid")

    recipe_id: str = Field(min_length=1, description="Stable recipe identifier.")
    version: str = Field(min_length=1, description="Semantic version string.")
    description: str = Field(default="", description="Human-readable description.")
    factor_pack_ids: list[str] = Field(
        default_factory=list,
        description="Ordered list of factor-pack IDs this recipe depends on.",
    )
    risk_template: RiskTemplate = Field(default_factory=RiskTemplate)
    execution_template: ExecutionTemplate = Field(default_factory=ExecutionTemplate)
    strategy_params: dict[str, Any] = Field(
        default_factory=dict,
        description="Strategy parameter block passed to the backtest runner.",
    )

    @field_validator("recipe_id", "version")
    @classmethod
    def _strip_nonempty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("field must not be blank")
        return cleaned

    @property
    def canonical_id(self) -> str:
        """Return ``{recipe_id}@{version}`` for manifest embedding."""
        return f"{self.recipe_id}@{self.version}"


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def load_strategy_recipe(path: Path) -> StrategyRecipeManifest:
    """Load a :class:`StrategyRecipeManifest` from a YAML or JSON file.

    Raises :exc:`FileNotFoundError` if *path* does not exist.
    Raises :exc:`ValueError` for schema errors.
    """
    if not path.exists():
        raise FileNotFoundError(f"Strategy recipe manifest not found: {path}")
    raw_text = path.read_text(encoding="utf-8")
    if path.suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(raw_text)
    else:
        data = json.loads(raw_text)
    try:
        return StrategyRecipeManifest.model_validate(data)
    except Exception as exc:
        raise ValueError(f"Invalid strategy-recipe manifest at {path}: {exc}") from exc


def save_strategy_recipe(recipe: StrategyRecipeManifest, path: Path) -> None:
    """Persist *recipe* as YAML (or JSON for ``.json`` suffix)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = cast(dict[str, Any], json.loads(recipe.model_dump_json()))
    if path.suffix in {".yaml", ".yml"}:
        path.write_text(yaml.dump(data, sort_keys=True, allow_unicode=True), encoding="utf-8")
    else:
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def validate_recipe(
    recipe: StrategyRecipeManifest,
    available_pack_ids: set[str],
) -> None:
    """Assert all *factor_pack_ids* declared in *recipe* are available.

    Raises :exc:`ValueError` listing any missing pack IDs.
    """
    missing = [pid for pid in recipe.factor_pack_ids if pid not in available_pack_ids]
    if missing:
        raise ValueError(
            f"Strategy recipe {recipe.recipe_id!r} references unknown factor pack(s): {missing}"
        )
