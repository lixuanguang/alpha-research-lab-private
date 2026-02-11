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
import math
from pathlib import Path
from typing import Any

import pandas as pd
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
_MACRO_ALLOWED_TOP_LEVEL = {
    "exp",
    "strategy",
    "universe_config",
    "dates",
    "rebalance",
    "signal",
    "regime",
    "risk",
    "costs",
    "evaluation",
}


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


def _parse_date(value: Any, field: str) -> pd.Timestamp:
    try:
        ts = pd.Timestamp(value)
    except Exception as exc:  # pragma: no cover - defensive parsing branch
        raise ConfigValidationError(f"'{field}' must be a valid date, got {value!r}") from exc
    if pd.isna(ts):
        raise ConfigValidationError(f"'{field}' must be a valid date, got {value!r}")
    return ts


def _coerce_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ConfigValidationError(f"'{field}' must be an integer, got boolean.")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigValidationError(f"'{field}' must be an integer, got {value!r}.") from exc


def _coerce_float(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ConfigValidationError(f"'{field}' must be numeric, got boolean.")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigValidationError(f"'{field}' must be numeric, got {value!r}.") from exc
    if not math.isfinite(out):
        raise ConfigValidationError(f"'{field}' must be finite, got {value!r}.")
    return out


def _validate_universe(universe: Any) -> None:
    if not isinstance(universe, list):
        raise ConfigValidationError("'universe' must be a list of tickers.")
    if not universe:
        raise ConfigValidationError("'universe' must not be empty.")
    bad = [t for t in universe if not isinstance(t, str) or not t.strip()]
    if bad:
        raise ConfigValidationError("'universe' must contain non-empty ticker strings.")
    if len(set(universe)) != len(universe):
        raise ConfigValidationError("'universe' must not contain duplicate tickers.")


def _validate_signal(signal: Any) -> None:
    if isinstance(signal, bool):
        raise ConfigValidationError("'signal' integer lookback must be an integer, not boolean.")
    if isinstance(signal, int):
        if signal <= 0:
            raise ConfigValidationError("'signal' integer lookback must be > 0.")
        return
    if not isinstance(signal, dict):
        raise ConfigValidationError(
            "'signal' must be an integer (lookback) or a dict (nested config)."
        )

    if "lookback" in signal:
        lookback = _coerce_int(signal["lookback"], "signal.lookback")
        if lookback <= 0:
            raise ConfigValidationError("'signal.lookback' must be > 0.")
    if "long_only" in signal and not isinstance(signal["long_only"], bool):
        raise ConfigValidationError("'signal.long_only' must be boolean when provided.")
    if "name" in signal and (not isinstance(signal["name"], str) or not signal["name"].strip()):
        raise ConfigValidationError("'signal.name' must be a non-empty string when provided.")


def _validate_costs(costs: Any) -> None:
    if isinstance(costs, bool):
        raise ConfigValidationError("'costs' must be numeric, not boolean.")
    if isinstance(costs, (int, float)):
        if _coerce_float(costs, "costs") < 0:
            raise ConfigValidationError("'costs' must be >= 0.")
        return
    if not isinstance(costs, dict):
        raise ConfigValidationError("'costs' must be a number (bps) or a dict.")

    if "bps" in costs:
        bps = _coerce_float(costs["bps"], "costs.bps")
        if bps < 0:
            raise ConfigValidationError("'costs.bps' must be >= 0.")
    if "per_asset_bps" in costs:
        per_asset = costs["per_asset_bps"]
        if not isinstance(per_asset, dict):
            raise ConfigValidationError("'costs.per_asset_bps' must be a mapping.")
        for ticker, bps in per_asset.items():
            if not isinstance(ticker, str) or not ticker.strip():
                raise ConfigValidationError(
                    "'costs.per_asset_bps' keys must be non-empty ticker strings."
                )
            if _coerce_float(bps, "costs.per_asset_bps") < 0:
                raise ConfigValidationError("'costs.per_asset_bps' values must be >= 0.")


def _validate_legacy_dates(raw: dict[str, Any]) -> None:
    start = _parse_date(raw["start_date"], "start_date")
    end = _parse_date(raw["end_date"], "end_date")
    if start > end:
        raise ConfigValidationError("'start_date' must be <= 'end_date'.")


def validate_macro_allocator_config(raw: dict[str, Any]) -> None:
    """Strict schema validation for week-2 macro allocator configs."""
    if not isinstance(raw, dict):
        raise ConfigValidationError("macro allocator config must be a mapping.")

    required = {"exp", "universe_config", "dates", "rebalance", "signal", "evaluation"}
    missing = sorted(required - set(raw))
    if missing:
        raise ConfigValidationError(f"Macro config missing required fields: {', '.join(missing)}")

    unknown = sorted(set(raw) - _MACRO_ALLOWED_TOP_LEVEL)
    if unknown:
        raise ConfigValidationError(f"Macro config contains unknown fields: {', '.join(unknown)}")

    if not isinstance(raw["exp"], str) or not raw["exp"].strip():
        raise ConfigValidationError("'exp' must be a non-empty string.")
    if not isinstance(raw["universe_config"], str) or not raw["universe_config"].strip():
        raise ConfigValidationError("'universe_config' must be a non-empty path string.")

    dates = raw["dates"]
    if not isinstance(dates, dict):
        raise ConfigValidationError("'dates' must be a mapping with 'start' and 'end'.")
    if "start" not in dates or "end" not in dates:
        raise ConfigValidationError("'dates' must define both 'start' and 'end'.")
    start = _parse_date(dates["start"], "dates.start")
    end = _parse_date(dates["end"], "dates.end")
    if start > end:
        raise ConfigValidationError("'dates.start' must be <= 'dates.end'.")

    rebalance = raw["rebalance"]
    if not isinstance(rebalance, dict):
        raise ConfigValidationError("'rebalance' must be a mapping.")
    freq = rebalance.get("frequency")
    if not isinstance(freq, str) or not freq.strip():
        raise ConfigValidationError("'rebalance.frequency' must be a non-empty string.")
    try:
        pd.date_range(start="2024-01-01", periods=2, freq=freq)
    except ValueError as exc:
        raise ConfigValidationError(f"'rebalance.frequency' is invalid: {freq!r}") from exc

    signal = raw["signal"]
    if not isinstance(signal, dict):
        raise ConfigValidationError("'signal' must be a mapping.")
    method = signal.get("method", "ma_cross")
    if method not in {"sign_return", "ma_cross"}:
        raise ConfigValidationError("'signal.method' must be one of {'sign_return', 'ma_cross'}.")
    lookback_days = _coerce_int(signal.get("lookback_days", 252), "signal.lookback_days")
    if lookback_days <= 0:
        raise ConfigValidationError("'signal.lookback_days' must be > 0.")
    fast = _coerce_int(signal.get("fast", 20), "signal.fast")
    slow = _coerce_int(signal.get("slow", 120), "signal.slow")
    if fast <= 0 or slow <= 0:
        raise ConfigValidationError("'signal.fast' and 'signal.slow' must be > 0.")
    if method == "ma_cross" and fast >= slow:
        raise ConfigValidationError("'signal.fast' must be < 'signal.slow' for 'ma_cross'.")
    vol_scale = _coerce_int(signal.get("vol_scale_lookback", 63), "signal.vol_scale_lookback")
    if vol_scale < 0:
        raise ConfigValidationError("'signal.vol_scale_lookback' must be >= 0.")

    risk = raw.get("risk", {})
    if not isinstance(risk, dict):
        raise ConfigValidationError("'risk' must be a mapping when provided.")
    if _coerce_float(risk.get("vol_target_annual", 0.0), "risk.vol_target_annual") < 0:
        raise ConfigValidationError("'risk.vol_target_annual' must be >= 0.")
    if _coerce_int(risk.get("vol_lookback_days", 63), "risk.vol_lookback_days") <= 1:
        raise ConfigValidationError("'risk.vol_lookback_days' must be > 1.")

    regime = raw.get("regime", {})
    if not isinstance(regime, dict):
        raise ConfigValidationError("'regime' must be a mapping when provided.")
    if "lag_days" in regime and _coerce_int(regime["lag_days"], "regime.lag_days") < 1:
        raise ConfigValidationError("'regime.lag_days' must be >= 1.")
    if "lookback_days" in regime and _coerce_int(regime["lookback_days"], "regime.lookback_days") <= 1:
        raise ConfigValidationError("'regime.lookback_days' must be > 1.")
    multipliers = regime.get("risk_off_bucket_multipliers", {})
    if not isinstance(multipliers, dict):
        raise ConfigValidationError("'regime.risk_off_bucket_multipliers' must be a mapping.")
    for bucket, mult in multipliers.items():
        if not isinstance(bucket, str) or not bucket.strip():
            raise ConfigValidationError("regime multiplier keys must be non-empty bucket names.")
        if _coerce_float(mult, "regime.risk_off_bucket_multipliers") < 0:
            raise ConfigValidationError("regime multipliers must be >= 0.")

    costs = raw.get("costs", {})
    if not isinstance(costs, dict):
        raise ConfigValidationError("'costs' must be a mapping.")
    if not isinstance(costs.get("use_meta_costs", True), bool):
        raise ConfigValidationError("'costs.use_meta_costs' must be boolean.")
    if _coerce_float(costs.get("bps", 5.0), "costs.bps") < 0:
        raise ConfigValidationError("'costs.bps' must be >= 0.")
    if _coerce_float(costs.get("financing_bps_annual", 0.0), "costs.financing_bps_annual") < 0:
        raise ConfigValidationError("'costs.financing_bps_annual' must be >= 0.")
    if (
        _coerce_float(costs.get("short_borrow_bps_annual", 0.0), "costs.short_borrow_bps_annual")
        < 0
    ):
        raise ConfigValidationError("'costs.short_borrow_bps_annual' must be >= 0.")

    regime_mult = costs.get("regime_multipliers", {})
    if not isinstance(regime_mult, dict):
        raise ConfigValidationError("'costs.regime_multipliers' must be a mapping.")
    for key in ("risk_on", "risk_off"):
        if key in regime_mult and _coerce_float(regime_mult[key], f"costs.regime_multipliers.{key}") <= 0:
            raise ConfigValidationError(f"'costs.regime_multipliers.{key}' must be > 0.")

    impact = costs.get("impact", {})
    if not isinstance(impact, dict):
        raise ConfigValidationError("'costs.impact' must be a mapping.")
    impact_enabled = bool(impact.get("enabled", False))
    if impact_enabled:
        if _coerce_float(impact.get("turnover_ref", 0.0), "costs.impact.turnover_ref") <= 0:
            raise ConfigValidationError("'costs.impact.turnover_ref' must be > 0 when enabled.")
        if _coerce_float(impact.get("coefficient_bps", 0.0), "costs.impact.coefficient_bps") < 0:
            raise ConfigValidationError(
                "'costs.impact.coefficient_bps' must be >= 0 when enabled."
            )
        if _coerce_float(impact.get("exponent", 0.0), "costs.impact.exponent") <= 0:
            raise ConfigValidationError("'costs.impact.exponent' must be > 0 when enabled.")

    capacity = costs.get("capacity", {})
    if not isinstance(capacity, dict):
        raise ConfigValidationError("'costs.capacity' must be a mapping.")
    capacity_enabled = bool(capacity.get("enabled", False))
    if capacity_enabled:
        if _coerce_float(capacity.get("notional_usd", 0.0), "costs.capacity.notional_usd") <= 0:
            raise ConfigValidationError("'costs.capacity.notional_usd' must be > 0 when enabled.")
        if (
            _coerce_float(
                capacity.get("max_adv_participation", 0.0), "costs.capacity.max_adv_participation"
            )
            <= 0
        ):
            raise ConfigValidationError(
                "'costs.capacity.max_adv_participation' must be > 0 when enabled."
            )
        if (
            _coerce_float(
                capacity.get("impact_bps_at_100pct_adv", 0.0),
                "costs.capacity.impact_bps_at_100pct_adv",
            )
            < 0
        ):
            raise ConfigValidationError(
                "'costs.capacity.impact_bps_at_100pct_adv' must be >= 0 when enabled."
            )
        breach_action = str(capacity.get("breach_action", "warn")).strip().lower()
        if breach_action not in {"warn", "raise"}:
            raise ConfigValidationError(
                "'costs.capacity.breach_action' must be one of {'warn', 'raise'}."
            )
        adv_col = capacity.get("adv_column", "adv_usd")
        if not isinstance(adv_col, str) or not adv_col.strip():
            raise ConfigValidationError("'costs.capacity.adv_column' must be a non-empty string.")

    stress = costs.get("stress_multipliers", [1, 2, 4])
    if not isinstance(stress, list) or not stress:
        raise ConfigValidationError("'costs.stress_multipliers' must be a non-empty list.")
    if any(_coerce_float(x, "costs.stress_multipliers") <= 0 for x in stress):
        raise ConfigValidationError("'costs.stress_multipliers' entries must be > 0.")

    evaluation = raw["evaluation"]
    if not isinstance(evaluation, dict):
        raise ConfigValidationError("'evaluation' must be a mapping.")
    if "calendar" in evaluation:
        cal = evaluation["calendar"]
        if not isinstance(cal, str) or not cal.strip():
            raise ConfigValidationError("'evaluation.calendar' must be a non-empty string.")
    folds = evaluation.get("folds")
    if not isinstance(folds, dict):
        raise ConfigValidationError("'evaluation.folds' must be a mapping.")
    for key in ("train_days", "test_days", "step_days"):
        if _coerce_int(folds.get(key, 0), f"evaluation.folds.{key}") <= 0:
            raise ConfigValidationError(f"'evaluation.folds.{key}' must be > 0.")
    if _coerce_int(folds.get("embargo_days", 0), "evaluation.folds.embargo_days") < 0:
        raise ConfigValidationError("'evaluation.folds.embargo_days' must be >= 0.")


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

    _validate_universe(raw["universe"])
    _validate_legacy_dates(raw)

    if raw["rebalance"] not in _VALID_REBALANCE:
        raise ConfigValidationError(
            f"'rebalance' must be one of {_VALID_REBALANCE}, got '{raw['rebalance']}'"
        )

    _validate_signal(raw["signal"])
    _validate_costs(raw["costs"])

    if isinstance(raw["initial_capital"], bool) or not isinstance(raw["initial_capital"], (int, float)):
        raise ConfigValidationError("'initial_capital' must be a number.")
    if _coerce_float(raw["initial_capital"], "initial_capital") <= 0:
        raise ConfigValidationError("'initial_capital' must be > 0.")

    if "regime" in raw and raw["regime"] is not None:
        regime = raw["regime"]
        if not isinstance(regime, dict):
            raise ConfigValidationError("'regime' must be a mapping when provided.")
        if "fast" in regime and _coerce_int(regime["fast"], "regime.fast") <= 0:
            raise ConfigValidationError("'regime.fast' must be > 0.")
        if "slow" in regime and _coerce_int(regime["slow"], "regime.slow") <= 0:
            raise ConfigValidationError("'regime.slow' must be > 0.")
        if "fast" in regime and "slow" in regime and _coerce_int(
            regime["fast"], "regime.fast"
        ) >= _coerce_int(regime["slow"], "regime.slow"):
            raise ConfigValidationError("'regime.fast' must be < 'regime.slow'.")
        if "risk_off_scale" in regime and not 0 <= _coerce_float(
            regime["risk_off_scale"], "regime.risk_off_scale"
        ) <= 1:
            raise ConfigValidationError("'regime.risk_off_scale' must be in [0, 1].")


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
