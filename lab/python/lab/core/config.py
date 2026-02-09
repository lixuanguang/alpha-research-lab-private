"""
lab.core.config
~~~~~~~~~~~~~~~
Experiment configuration loading, validation, and normalization.

Supports two YAML formats:

**Flat (week-1 legacy)**::

    signal: 252
    costs: 8.0

**Nested (recommended)**::

    signal:
      name: cs_mom
      lookback: 60
      long_only: true
    regime:
      name: ma_crossover
      fast: 20
      slow: 60
      risk_off_scale: 0.3
    costs:
      bps: 5

Helper accessors (``signal_cfg``, ``regime_cfg``, ``costs_bps``) normalise
both forms so downstream code doesn't need to care.

Design
------
- YAML-driven with strict validation of required fields.
- Frozen dataclass to prevent mutation mid-run.
- ``normalize_config`` sorts keys recursively for deterministic hashing.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import yaml

# ── Required field names ─────────────────────────────────────────────────────

_REQUIRED_FIELDS: list[str] = [
    "exp",
    "universe",
    "start_date",
    "end_date",
    "rebalance",
    "signal",
    "costs",
    "initial_capital",
]

_VALID_REBALANCE = {"daily", "weekly", "monthly"}


# ── Dataclass ─────────────────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class ExperimentConfig:
    """Top-level experiment configuration, loaded from YAML.

    ``signal`` and ``costs`` may be either scalars (legacy flat format) or
    dicts (nested format).  Use the accessor helpers to normalise.
    """

    # Required
    exp: str  # experiment name
    universe: tuple[str, ...]  # ticker list (tuple for hashability)
    start_date: str  # "2016-01-01"
    end_date: str  # "2024-12-31"
    rebalance: str  # "daily" | "weekly" | "monthly"
    signal: int | dict[str, Any]  # lookback int  OR  nested dict
    costs: float | dict[str, Any]  # bps float     OR  nested dict
    initial_capital: float  # starting capital

    # Optional
    strategy: str = "macro_equities.baseline"
    regime: dict[str, Any] | None = None  # nested regime config (optional)
    params: dict[str, Any] = dataclasses.field(default_factory=dict)

    # ── Normalised accessors ──────────────────────────────────────────────

    @property
    def signal_cfg(self) -> dict[str, Any]:
        """Return signal config as a dict regardless of flat/nested format.

        Flat ``signal: 252`` → ``{"name": "cs_mom", "lookback": 252, "long_only": true}``
        """
        if isinstance(self.signal, dict):
            return self.signal
        return {"name": "cs_mom", "lookback": int(self.signal), "long_only": True}

    @property
    def regime_cfg(self) -> dict[str, Any]:
        """Return regime config as a dict (defaults if absent)."""
        if self.regime is not None:
            return self.regime
        return {
            "name": "ma_crossover",
            "fast": 20,
            "slow": 60,
            "risk_off_scale": 0.3,
        }

    @property
    def costs_bps(self) -> float:
        """Return one-way cost in basis points, regardless of format."""
        if isinstance(self.costs, dict):
            return float(self.costs.get("bps", 0.0))
        return float(self.costs)


# ── Validation ────────────────────────────────────────────────────────────────


class ConfigValidationError(Exception):
    """Raised when a config is missing required fields or has invalid values."""


def validate_config(raw: dict[str, Any]) -> None:
    """Validate that all required fields are present and well-typed.

    Raises
    ------
    ConfigValidationError
        On missing fields or type mismatches.
    """
    missing = [f for f in _REQUIRED_FIELDS if f not in raw]
    if missing:
        raise ConfigValidationError(f"Config missing required fields: {', '.join(missing)}")

    if not isinstance(raw["universe"], list):
        raise ConfigValidationError("'universe' must be a list of tickers.")

    if raw["rebalance"] not in _VALID_REBALANCE:
        raise ConfigValidationError(
            f"'rebalance' must be one of {_VALID_REBALANCE}, got '{raw['rebalance']}'"
        )

    sig = raw["signal"]
    if not isinstance(sig, (int, dict)):
        raise ConfigValidationError(
            "'signal' must be an integer (lookback) or a dict (nested config)."
        )

    costs = raw["costs"]
    if not isinstance(costs, (int, float, dict)):
        raise ConfigValidationError("'costs' must be a number (bps) or a dict with 'bps' key.")

    if not isinstance(raw["initial_capital"], (int, float)):
        raise ConfigValidationError("'initial_capital' must be a number.")


# ── Normalization (for hashing) ───────────────────────────────────────────────


def normalize_config(obj: Any) -> Any:
    """Recursively sort dict keys for deterministic YAML serialization."""
    if isinstance(obj, dict):
        return {k: normalize_config(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        return [normalize_config(v) for v in obj]
    return obj


# ── Loaders ───────────────────────────────────────────────────────────────────


def load_raw_config(path: str | Path) -> dict[str, Any]:
    """Load raw YAML config as a dict (for hashing / meta.json).

    No validation is performed — use :func:`load_config` for the full pipeline.
    """
    path = Path(path)
    with path.open() as fh:
        return yaml.safe_load(fh) or {}


def load_config(path: str | Path) -> ExperimentConfig:
    """Load, validate, and return an :class:`ExperimentConfig` from YAML.

    Parameters
    ----------
    path : str | Path
        Path to the YAML config file.

    Returns
    -------
    ExperimentConfig
        Frozen, validated experiment configuration.

    Raises
    ------
    ConfigValidationError
        If required fields are missing or invalid.
    """
    raw = load_raw_config(path)
    validate_config(raw)

    # Separate known fields from strategy-specific extras
    known_names = {f.name for f in dataclasses.fields(ExperimentConfig)}
    config_kwargs: dict[str, Any] = {}
    extra_params: dict[str, Any] = raw.get("params", {})

    for key, value in raw.items():
        if key in known_names:
            config_kwargs[key] = value
        elif key != "params":
            extra_params[key] = value

    # universe comes in as list; convert to tuple for frozen dataclass
    if "universe" in config_kwargs and isinstance(config_kwargs["universe"], list):
        config_kwargs["universe"] = tuple(config_kwargs["universe"])

    config_kwargs["params"] = extra_params
    return ExperimentConfig(**config_kwargs)
