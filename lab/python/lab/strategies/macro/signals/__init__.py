"""Macro signal models and config-driven factory helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lab.strategies.macro.signals.base import Signal
from lab.strategies.macro.signals.ensemble import EnsembleSignal
from lab.strategies.macro.signals.trend import TrendSignal


def _signal_name(signal_cfg: Mapping[str, Any]) -> str:
    return str(signal_cfg.get("name", "ts_trend")).strip().lower()


def build_signal(signal_cfg: Mapping[str, Any]) -> Signal:
    """Build a concrete signal model from config."""
    name = _signal_name(signal_cfg)
    if name in {"", "trend", "ts_trend"}:
        return TrendSignal.from_config(signal_cfg)

    if name == "ensemble":
        raw_signals = signal_cfg.get("signals")
        if not isinstance(raw_signals, Mapping) or not raw_signals:
            raise ValueError("'signal.signals' must be a non-empty mapping for ensemble.")

        children: dict[str, Signal] = {}
        for component, child_cfg_obj in raw_signals.items():
            if not isinstance(component, str) or not component.strip():
                raise ValueError("ensemble signal names must be non-empty strings.")
            if not isinstance(child_cfg_obj, Mapping):
                raise ValueError(f"ensemble component '{component}' must be a mapping.")

            child_cfg: dict[str, Any] = dict(child_cfg_obj)
            if "name" not in child_cfg:
                if component.strip().lower() in {"trend", "ts_trend"}:
                    child_cfg["name"] = "ts_trend"
                else:
                    child_cfg["name"] = component
            children[component] = build_signal(child_cfg)

        weights_cfg = signal_cfg.get("weights")
        weights: dict[str, float] | None = None
        if weights_cfg is not None:
            if not isinstance(weights_cfg, Mapping):
                raise ValueError("'signal.weights' must be a mapping when provided.")
            weights = {str(k): float(v) for k, v in weights_cfg.items()}

        rp_cfg = signal_cfg.get("risk_parity", False)
        rp_enabled = False
        rp_lookback = 63
        rp_min_periods: int | None = None
        if isinstance(rp_cfg, bool):
            rp_enabled = rp_cfg
        elif isinstance(rp_cfg, Mapping):
            rp_enabled = bool(rp_cfg.get("enabled", True))
            rp_lookback = int(rp_cfg.get("lookback_days", 63))
            if "min_periods" in rp_cfg:
                rp_min_periods = int(rp_cfg["min_periods"])
        else:
            raise ValueError("'signal.risk_parity' must be boolean or mapping.")

        normalize_components = bool(signal_cfg.get("normalize_components", True))
        return EnsembleSignal(
            children,
            weights=weights,
            normalize_components=normalize_components,
            risk_parity_enabled=rp_enabled,
            risk_parity_lookback=rp_lookback,
            risk_parity_min_periods=rp_min_periods,
        )

    raise ValueError(f"unknown macro signal '{name}'")


__all__ = ["EnsembleSignal", "Signal", "TrendSignal", "build_signal"]
