#!/usr/bin/env python
"""
run_experiment.py
~~~~~~~~~~~~~~~~~
CLI entry-point to run week-1 and week-2 experiment pipelines.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

# Ensure the lab package is importable when running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import matplotlib

matplotlib.use("Agg")  # headless backend — no GUI needed

# Importing the strategies package triggers @register decorators
import lab.strategies.macro_equities  # noqa: F401
from lab.core.config import load_config, load_raw_config, validate_macro_allocator_config
from lab.core.logging import get_logger, setup_logging
from lab.core.registry import (
    compute_config_hash,
    compute_results_hash,
    compute_stable_frame_hash,
    compute_stable_series_hash,
    create_run,
)
from lab.core.strategy_registry import get as get_strategy

log = get_logger("scripts.run_experiment")


@dataclasses.dataclass
class MacroRunConfig:
    """Config adapter consumed by the generic daily engine."""

    exp: str
    rebalance: str
    costs: float | dict[str, Any]

    @property
    def costs_bps(self) -> float:
        if isinstance(self.costs, dict):
            if "bps" in self.costs:
                return float(self.costs["bps"])
            per_asset = self.costs.get("per_asset_bps", {})
            if per_asset:
                vals = [float(v) for v in per_asset.values()]
                return float(sum(vals) / len(vals))
            return 0.0
        return float(self.costs)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _finalize_meta(rdir: Path) -> dict[str, Any]:
    """Add run end-time to meta.json and return the updated metadata."""
    meta_path = rdir / "meta.json"
    meta: dict[str, Any] = {}
    if meta_path.exists():
        with open(meta_path) as fh:
            meta = json.load(fh)
    meta["end_time"] = _utc_now_iso()
    with open(meta_path, "w") as fh:
        json.dump(meta, fh, indent=2)
    return meta


def _metric_view(metrics: dict[str, float]) -> dict[str, float]:
    """Map internal metric keys to stable results.json schema keys."""
    return {
        "cagr": float(metrics.get("cagr", 0.0)),
        "vol_annual": float(metrics.get("ann_vol", 0.0)),
        "sharpe": float(metrics.get("sharpe", 0.0)),
        "sortino": float(metrics.get("sortino", 0.0)),
        "max_drawdown": float(metrics.get("max_dd", 0.0)),
        "calmar": float(metrics.get("calmar", 0.0)),
    }


def _gross_metric_view(metrics: dict[str, float]) -> dict[str, float]:
    return {
        "cagr": float(metrics.get("cagr", 0.0)),
        "vol_annual": float(metrics.get("ann_vol", 0.0)),
        "sharpe": float(metrics.get("sharpe", 0.0)),
        "max_drawdown": float(metrics.get("max_dd", 0.0)),
    }


def _round_nested(obj: Any, ndigits: int = 6) -> Any:
    if isinstance(obj, dict):
        return {k: _round_nested(v, ndigits=ndigits) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_nested(v, ndigits=ndigits) for v in obj]
    if isinstance(obj, float):
        return round(obj, ndigits)
    return obj


def _compute_data_snapshot_id(prices: pd.DataFrame) -> str:
    """Compute a deterministic snapshot identifier from the full close panel."""
    return f"prices_close_{compute_stable_frame_hash(prices)[:12]}"


def _safe_corr(a: pd.Series, b: pd.Series) -> float:
    x = a.astype(float).fillna(0.0)
    y = b.astype(float).fillna(0.0)
    c = x.corr(y)
    if pd.isna(c):
        return 0.0
    return float(c)


def _validate_macro_inputs(prices: pd.DataFrame, meta: pd.DataFrame, tickers: list[str]) -> None:
    if prices.empty:
        raise ValueError("Loaded close-price panel is empty.")
    if not prices.index.is_monotonic_increasing or not prices.index.is_unique:
        raise ValueError("Close-price index must be unique and strictly increasing.")
    if not prices.columns.is_unique:
        raise ValueError("Close-price columns must be unique.")
    if list(prices.columns) != tickers:
        raise ValueError("Close-price columns must exactly match configured ticker order.")

    arr = prices.to_numpy(dtype=float, copy=False)
    if not np.isfinite(arr).all():
        raise ValueError("Close-price panel contains NaN/inf values.")
    if (arr <= 0).any():
        raise ValueError("Close-price panel contains non-positive prices.")

    if meta.empty:
        raise ValueError("Universe metadata is empty.")
    if meta["ticker"].duplicated().any():
        raise ValueError("Universe metadata contains duplicate tickers.")
    if set(meta["ticker"]) != set(tickers):
        raise ValueError("Universe metadata tickers must match price-panel tickers exactly.")
    cost_bps = pd.to_numeric(meta["cost_bps"], errors="coerce")
    per_asset_cap = pd.to_numeric(meta["per_asset_cap"], errors="coerce")
    bucket = meta["bucket"].astype(str).str.strip()

    if not np.isfinite(cost_bps.to_numpy(dtype=float)).all():
        raise ValueError("Universe metadata cost_bps must be finite.")
    if not np.isfinite(per_asset_cap.to_numpy(dtype=float)).all():
        raise ValueError("Universe metadata per_asset_cap must be finite.")
    if (cost_bps < 0).any():
        raise ValueError("Universe metadata cost_bps must be >= 0.")
    if (per_asset_cap <= 0).any():
        raise ValueError("Universe metadata per_asset_cap must be > 0.")
    if bucket.eq("").any():
        raise ValueError("Universe metadata bucket must be non-empty for all assets.")
    for adv_col in ("adv_usd", "adv_usd_mn"):
        if adv_col in meta.columns:
            adv = meta[adv_col].astype(float)
            if not np.isfinite(adv.to_numpy()).all():
                raise ValueError(f"Universe metadata {adv_col} must be finite when provided.")
            if (adv <= 0).any():
                raise ValueError(f"Universe metadata {adv_col} must be > 0 when provided.")


def _artifact_hashes(
    *,
    net_returns: pd.Series,
    gross_returns: pd.Series,
    turnover: pd.Series,
    costs: pd.Series,
    weights: pd.DataFrame,
    weights_daily: pd.DataFrame,
    bucket_exposure: pd.DataFrame,
    costs_by_asset: pd.DataFrame,
) -> dict[str, str]:
    return {
        "returns": compute_stable_series_hash(net_returns),
        "gross_returns": compute_stable_series_hash(gross_returns),
        "turnover": compute_stable_series_hash(turnover),
        "costs": compute_stable_series_hash(costs),
        "weights_rebalance": compute_stable_frame_hash(weights),
        "weights_daily": compute_stable_frame_hash(weights_daily),
        "bucket_exposure": compute_stable_frame_hash(bucket_exposure),
        "costs_by_asset": compute_stable_frame_hash(costs_by_asset),
    }


def _resolve_path(path_like: str | Path, *, base: Path, fallbacks: tuple[Path, ...] = ()) -> Path:
    p = Path(path_like)
    if p.is_absolute():
        return p

    candidates = [(base / p).resolve()]
    candidates.extend((fb / p).resolve() for fb in fallbacks)

    for candidate in candidates:
        if candidate.exists():
            return candidate

    # Return the primary resolution target for predictable downstream errors.
    return candidates[0]


def _universe_meta(universe_raw: dict[str, Any]) -> pd.DataFrame:
    tickers = universe_raw.get("tickers", [])
    if not isinstance(tickers, list) or not tickers:
        raise ValueError("universe config must define a non-empty 'tickers' list.")
    if len(set(tickers)) != len(tickers):
        raise ValueError("universe config 'tickers' must not contain duplicates.")
    ticker_meta = universe_raw.get("ticker_meta", {})
    if not isinstance(ticker_meta, dict):
        raise ValueError("universe config 'ticker_meta' must be a mapping.")

    rows: list[dict[str, Any]] = []
    for t in tickers:
        info = ticker_meta.get(t)
        if not isinstance(info, dict):
            raise ValueError(f"ticker_meta must define mapping for ticker '{t}'.")
        missing = {"bucket", "cost_bps", "per_asset_cap"} - set(info)
        if missing:
            fields = ", ".join(sorted(missing))
            raise ValueError(f"ticker_meta for '{t}' missing required fields: {fields}")
        row: dict[str, Any] = {
            "ticker": t,
            "bucket": str(info["bucket"]),
            "cost_bps": float(info["cost_bps"]),
            "per_asset_cap": float(info["per_asset_cap"]),
        }
        if "adv_usd" in info:
            row["adv_usd"] = float(info["adv_usd"])
        if "adv_usd_mn" in info:
            row["adv_usd_mn"] = float(info["adv_usd_mn"])
        rows.append(row)
    return pd.DataFrame(rows)


def _concat_series(parts: list[pd.Series], name: str) -> pd.Series:
    if not parts:
        return pd.Series(dtype=float, name=name)
    out = pd.concat(parts).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    out.name = name
    return out


def _concat_frames(parts: list[pd.DataFrame]) -> pd.DataFrame:
    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out


def _bucket_exposure_from_weights(weights_daily: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    if weights_daily.empty:
        return pd.DataFrame(index=weights_daily.index)

    bucket_map = meta.set_index("ticker").reindex(weights_daily.columns)["bucket"].fillna("other")
    buckets = sorted(bucket_map.unique())
    out = pd.DataFrame(index=weights_daily.index, columns=buckets, dtype=float)

    for b in buckets:
        cols = bucket_map[bucket_map == b].index
        out[b] = weights_daily[cols].sum(axis=1)

    return out


def _calendar_label_from_index(index: pd.DatetimeIndex) -> str:
    if len(index) == 0:
        return "UNKNOWN"
    weekdays_only = bool((index.weekday < 5).all())
    return "OBSERVED_WEEKDAY" if weekdays_only else "OBSERVED_NON_WEEKDAY"


def _adv_usd_series(meta: pd.DataFrame, adv_column: str) -> pd.Series | None:
    """Resolve ADV in USD from metadata, supporting million-USD shorthand."""
    if adv_column in meta.columns:
        s = meta.set_index("ticker")[adv_column].astype(float)
        if adv_column.endswith("_mn"):
            s = s * 1_000_000.0
        return s
    if adv_column != "adv_usd" and "adv_usd" in meta.columns:
        return meta.set_index("ticker")["adv_usd"].astype(float)
    if adv_column == "adv_usd" and "adv_usd_mn" in meta.columns:
        return meta.set_index("ticker")["adv_usd_mn"].astype(float) * 1_000_000.0
    return None


def _save_fold_metrics(
    fold_id: int,
    train_dates: pd.DatetimeIndex,
    test_dates: pd.DatetimeIndex,
    metrics: dict[str, float],
) -> dict[str, Any]:
    return {
        "fold": fold_id,
        "train_start": str(train_dates.min().date()),
        "train_end": str(train_dates.max().date()),
        "test_start": str(test_dates.min().date()),
        "test_end": str(test_dates.max().date()),
        "metrics": {k: float(v) for k, v in metrics.items()},
    }


def _run_macro_allocator(
    args: argparse.Namespace,
    *,
    config_path: Path,
    raw_config: dict[str, Any],
    rid: str,
    rdir: Path,
    raw_config_hash: str,
) -> None:
    from lab.backtest.daily_engine import run_daily_backtest
    from lab.backtest.leakage_checks import assert_no_lookahead, assert_splits_time_ordered
    from lab.backtest.splits import rolling_splits
    from lab.costs.daily import adv_participation, carry_costs, turnover_impact_bps
    from lab.data.loaders.prices import load_close_prices
    from lab.eval.metrics import summary
    from lab.eval.plots import (
        bucket_exposure_plot,
        capacity_participation_plot,
        cumulative_returns,
        drawdown,
        gross_net_exposure,
        risk_contribution_plot,
        turnover_plot,
    )
    from lab.eval.reports import save_macro_allocator_report
    from lab.eval.risk_attribution import compute_risk_contributions
    from lab.features.macro.regime import compute_risk_off_regime
    from lab.portfolio.allocator_ls import build_weights
    from lab.portfolio.vol_target import apply_vol_target
    from lab.strategies.macro.baselines import equal_weight_long_only, sixty_forty_proxy
    from lab.strategies.macro.signals import build_signal as build_macro_signal

    # ── Load config components ───────────────────────────────────────────
    repo_root = Path(__file__).resolve().parent.parent
    universe_cfg_path = _resolve_path(
        raw_config["universe_config"],
        base=config_path.parent,
        fallbacks=(repo_root,),
    )
    universe_raw = yaml.safe_load(universe_cfg_path.read_text()) or {}

    dates_cfg = raw_config.get("dates", {})
    start = dates_cfg.get("start", "2016-01-01")
    end = dates_cfg.get("end", "2024-12-31")

    meta = _universe_meta(universe_raw)
    tickers = meta["ticker"].tolist()
    if not tickers:
        raise ValueError("universe config produced zero tickers.")
    prices = load_close_prices(tickers=tickers, start=start, end=end)
    _validate_macro_inputs(prices, meta, tickers)
    log.info("Loaded macro panel: %d days × %d assets", *prices.shape)

    constraints = universe_raw.get("constraints", {})
    if not isinstance(constraints, dict):
        raise ValueError("universe config 'constraints' must be a mapping.")
    required_constraints = {"gross_cap", "net_target", "net_band", "bucket_gross_caps"}
    missing_constraints = required_constraints - set(constraints)
    if missing_constraints:
        miss = ", ".join(sorted(missing_constraints))
        raise ValueError(f"universe config constraints missing required fields: {miss}")
    gross_cap = float(constraints.get("gross_cap", 1.5))
    net_target = float(constraints.get("net_target", 0.0))
    net_band = float(constraints.get("net_band", 0.15))
    raw_bucket_caps = constraints.get("bucket_gross_caps", {})
    if not isinstance(raw_bucket_caps, dict) or not raw_bucket_caps:
        raise ValueError("constraints.bucket_gross_caps must be a non-empty mapping.")
    bucket_caps = {k: float(v) for k, v in raw_bucket_caps.items()}
    if gross_cap <= 0:
        raise ValueError("constraints.gross_cap must be > 0.")
    if net_band < 0:
        raise ValueError("constraints.net_band must be >= 0.")
    if abs(net_target) > gross_cap:
        raise ValueError("constraints.net_target magnitude must be <= constraints.gross_cap.")
    if any(v < 0 for v in bucket_caps.values()):
        raise ValueError("constraints.bucket_gross_caps values must be >= 0.")
    default_per_asset_cap = float(meta["per_asset_cap"].max()) if not meta.empty else 0.35

    signal_cfg = raw_config.get("signal", {})
    if not isinstance(signal_cfg, dict):
        raise ValueError("signal config must be a mapping.")
    signal_name = str(signal_cfg.get("name", "ts_trend")).strip() or "ts_trend"
    strategy_signal_label = f"{signal_name.lower().replace(' ', '_')}_ls"
    signal_method = str(signal_cfg.get("method", "ma_cross"))
    lookback_days = int(signal_cfg.get("lookback_days", 252))
    fast = int(signal_cfg.get("fast", 20))
    slow = int(signal_cfg.get("slow", 120))
    vol_scale_lb = int(signal_cfg.get("vol_scale_lookback", 63))
    if vol_scale_lb < 0:
        raise ValueError("signal.vol_scale_lookback must be >= 0.")

    rebalance_freq = raw_config.get("rebalance", {}).get("frequency", "W-FRI")

    risk_cfg = raw_config.get("risk", {})
    vol_target = float(risk_cfg.get("vol_target_annual", 0.10))
    vol_lookback_days = int(risk_cfg.get("vol_lookback_days", 63))
    if vol_target < 0:
        raise ValueError("risk.vol_target_annual must be >= 0.")
    if vol_lookback_days <= 1:
        raise ValueError("risk.vol_lookback_days must be > 1.")

    regime_cfg = raw_config.get("regime", {})
    regime_enabled = bool(regime_cfg.get("enabled", False))
    regime_lag = int(regime_cfg.get("lag_days", 30))
    regime_rates = str(regime_cfg.get("rates_proxy", "TLT"))
    regime_equity = str(regime_cfg.get("equity_proxy", "SPY"))
    regime_lb = int(regime_cfg.get("lookback_days", 63))
    risk_off_multipliers = {
        k: float(v) for k, v in regime_cfg.get("risk_off_bucket_multipliers", {}).items()
    }
    if any(v < 0 for v in risk_off_multipliers.values()):
        raise ValueError("regime risk-off bucket multipliers must be >= 0.")

    costs_cfg = raw_config.get("costs", {})
    use_meta_costs = bool(costs_cfg.get("use_meta_costs", True))
    stress_multipliers = [float(x) for x in costs_cfg.get("stress_multipliers", [1, 2, 4])]
    if not stress_multipliers or any(x <= 0 for x in stress_multipliers):
        raise ValueError("costs.stress_multipliers must be a non-empty list of >0 values.")
    financing_bps_annual = float(costs_cfg.get("financing_bps_annual", 0.0))
    short_borrow_bps_annual = float(costs_cfg.get("short_borrow_bps_annual", 0.0))
    if financing_bps_annual < 0 or short_borrow_bps_annual < 0:
        raise ValueError("costs financing/borrow bps must be >= 0.")

    regime_cost_mult = costs_cfg.get("regime_multipliers", {})
    if not isinstance(regime_cost_mult, dict):
        raise ValueError("costs.regime_multipliers must be a mapping when provided.")
    regime_cost_mult_on = float(regime_cost_mult.get("risk_on", 1.0))
    regime_cost_mult_off = float(regime_cost_mult.get("risk_off", 1.0))
    if regime_cost_mult_on <= 0 or regime_cost_mult_off <= 0:
        raise ValueError("costs.regime_multipliers values must be > 0.")

    impact_cfg = costs_cfg.get("impact", {})
    if not isinstance(impact_cfg, dict):
        raise ValueError("costs.impact must be a mapping when provided.")
    impact_enabled = bool(impact_cfg.get("enabled", False))
    impact_turnover_ref = float(impact_cfg.get("turnover_ref", 0.10))
    impact_coeff_bps = float(impact_cfg.get("coefficient_bps", 0.0))
    impact_exponent = float(impact_cfg.get("exponent", 0.5))
    if impact_enabled:
        if impact_turnover_ref <= 0:
            raise ValueError("costs.impact.turnover_ref must be > 0 when enabled.")
        if impact_coeff_bps < 0:
            raise ValueError("costs.impact.coefficient_bps must be >= 0 when enabled.")
        if impact_exponent <= 0:
            raise ValueError("costs.impact.exponent must be > 0 when enabled.")

    capacity_cfg = costs_cfg.get("capacity", {})
    if not isinstance(capacity_cfg, dict):
        raise ValueError("costs.capacity must be a mapping when provided.")
    capacity_enabled = bool(capacity_cfg.get("enabled", False))
    capacity_notional_usd = float(capacity_cfg.get("notional_usd", 0.0))
    capacity_max_adv_participation = float(capacity_cfg.get("max_adv_participation", 0.20))
    capacity_impact_bps = float(capacity_cfg.get("impact_bps_at_100pct_adv", 0.0))
    capacity_breach_action = str(capacity_cfg.get("breach_action", "warn")).strip().lower()
    capacity_adv_column = str(capacity_cfg.get("adv_column", "adv_usd")).strip()
    if capacity_enabled:
        if capacity_notional_usd <= 0:
            raise ValueError("costs.capacity.notional_usd must be > 0 when enabled.")
        if capacity_max_adv_participation <= 0:
            raise ValueError("costs.capacity.max_adv_participation must be > 0 when enabled.")
        if capacity_impact_bps < 0:
            raise ValueError("costs.capacity.impact_bps_at_100pct_adv must be >= 0.")
        if capacity_breach_action not in {"warn", "raise"}:
            raise ValueError("costs.capacity.breach_action must be one of {'warn', 'raise'}.")
        if not capacity_adv_column:
            raise ValueError("costs.capacity.adv_column must be a non-empty string when enabled.")

    if use_meta_costs:
        per_asset_bps = meta.set_index("ticker")["cost_bps"].to_dict()
        engine_costs: float | dict[str, Any] = {
            "per_asset_bps": {k: float(v) for k, v in per_asset_bps.items()}
        }
    else:
        engine_costs = float(costs_cfg.get("bps", 5.0))

    if isinstance(engine_costs, dict):
        base_asset_cost_bps = (
            pd.Series(engine_costs.get("per_asset_bps", {}), dtype=float)
            .reindex(tickers)
            .fillna(meta.set_index("ticker")["cost_bps"])
            .fillna(meta["cost_bps"].mean())
        )
    else:
        base_asset_cost_bps = pd.Series(float(engine_costs), index=tickers, dtype=float)

    # ── Walk-forward folds + leakage checks ──────────────────────────────
    folds_cfg = raw_config.get("evaluation", {}).get("folds", {})
    embargo_days = int(folds_cfg.get("embargo_days", 5))
    folds = list(
        rolling_splits(
            prices.index,
            train_days=int(folds_cfg.get("train_days", 1260)),
            test_days=int(folds_cfg.get("test_days", 252)),
            step_days=int(folds_cfg.get("step_days", 252)),
            embargo_days=embargo_days,
        )
    )
    if not folds:
        raise ValueError("No valid rolling folds produced by evaluation.folds settings")

    assert_splits_time_ordered(folds)

    # Probe explicit future-return leakage with a model fitted only on the
    # first training fold. This avoids training on future observations.
    probe_signal_model = build_macro_signal(signal_cfg)
    probe_signal_model.fit(prices.reindex(folds[0][0]), None, meta)
    signal_panel = probe_signal_model.compute(prices, None, meta)
    assert_no_lookahead(signal_panel, prices, min_lag=1)

    eval_cfg = raw_config.get("evaluation", {})
    calendar_label = str(eval_cfg.get("calendar", "")).strip() or _calendar_label_from_index(
        prices.index
    )

    if regime_enabled:
        regime_series = compute_risk_off_regime(
            prices,
            lag_days=regime_lag,
            rates_proxy=regime_rates,
            equity_proxy=regime_equity,
            lookback_days=regime_lb,
        )
    else:
        regime_series = pd.Series(0, index=prices.index, dtype=int)
    regime_series = regime_series.reindex(prices.index).fillna(0).astype(int)

    adv_usd = _adv_usd_series(meta, capacity_adv_column)
    if capacity_enabled and adv_usd is None:
        raise ValueError(
            f"capacity enabled but no ADV column available in metadata (requested '{capacity_adv_column}')."
        )

    def _apply_execution_realism(
        *,
        fold_label: str,
        test_idx: pd.DatetimeIndex,
        fold_gross: pd.Series,
        fold_costs: pd.Series,
        fold_cost_asset: pd.DataFrame,
        fold_to_asset: pd.DataFrame,
        fold_gross_exposure: pd.Series,
        daily_w: pd.DataFrame,
    ) -> dict[str, Any]:
        gross = fold_gross.reindex(test_idx).fillna(0.0).astype(float)
        costs = fold_costs.reindex(test_idx).fillna(0.0).astype(float)
        cost_asset = (
            fold_cost_asset.reindex(test_idx).reindex(columns=tickers).fillna(0.0).astype(float)
        )
        to_asset = (
            fold_to_asset.reindex(test_idx).reindex(columns=tickers).fillna(0.0).clip(lower=0.0)
        )
        gross_exp = fold_gross_exposure.reindex(test_idx).ffill().fillna(0.0).astype(float)
        weights = daily_w.reindex(test_idx).reindex(columns=tickers).fillna(0.0).astype(float)

        regime_state = regime_series.reindex(test_idx).fillna(0).astype(int)
        regime_mult = pd.Series(
            np.where(regime_state == 1, regime_cost_mult_off, regime_cost_mult_on),
            index=test_idx,
            dtype=float,
        )
        regime_adj_asset = cost_asset.mul(regime_mult - 1.0, axis=0)

        impact_asset = pd.DataFrame(0.0, index=test_idx, columns=tickers, dtype=float)
        if impact_enabled and impact_coeff_bps > 0:
            impact_bps = turnover_impact_bps(
                to_asset,
                turnover_ref=impact_turnover_ref,
                coefficient_bps=impact_coeff_bps,
                exponent=impact_exponent,
            )
            impact_asset = to_asset.mul(impact_bps, axis=0) / 1e4

        participation = pd.DataFrame(0.0, index=test_idx, columns=tickers, dtype=float)
        capacity_asset = pd.DataFrame(0.0, index=test_idx, columns=tickers, dtype=float)
        capacity_breach_days = 0
        capacity_max_participation = 0.0
        if capacity_enabled:
            assert adv_usd is not None
            participation = adv_participation(
                to_asset,
                notional_usd=capacity_notional_usd,
                adv_usd=adv_usd,
            )
            if not participation.empty:
                capacity_max_participation = float(participation.to_numpy().max())
                day_max = participation.max(axis=1)
                breach_mask = day_max > capacity_max_adv_participation
                capacity_breach_days = int(breach_mask.sum())
                if capacity_breach_days > 0:
                    msg = (
                        f"{fold_label}: capacity breaches on {capacity_breach_days} days "
                        f"(max participation={capacity_max_participation:.4f}, "
                        f"limit={capacity_max_adv_participation:.4f})"
                    )
                    if capacity_breach_action == "raise":
                        raise ValueError(msg)
                    log.warning(msg)
            if capacity_impact_bps > 0:
                cap_bps = np.sqrt(participation.clip(lower=0.0)) * capacity_impact_bps
                capacity_asset = to_asset.mul(cap_bps, axis=0) / 1e4

        short_exposure = weights.clip(upper=0.0).abs().sum(axis=1)
        carry_total, financing_costs, borrow_costs = carry_costs(
            gross_exp,
            short_exposure,
            financing_bps_annual=financing_bps_annual,
            short_borrow_bps_annual=short_borrow_bps_annual,
        )

        extra_asset = regime_adj_asset + impact_asset + capacity_asset
        total_cost_asset = cost_asset + extra_asset
        total_costs = costs + extra_asset.sum(axis=1) + carry_total
        total_costs.name = "costs"

        net = gross - total_costs
        net.name = "net_return"
        short_exposure.name = "short_exposure"
        financing_costs = financing_costs.reindex(test_idx).fillna(0.0)
        borrow_costs = borrow_costs.reindex(test_idx).fillna(0.0)
        carry_total = carry_total.reindex(test_idx).fillna(0.0)

        return {
            "net": net,
            "costs": total_costs,
            "costs_by_asset": total_cost_asset,
            "short_exposure": short_exposure,
            "financing_costs": financing_costs,
            "borrow_costs": borrow_costs,
            "carry_costs": carry_total,
            "participation": participation,
            "capacity_breach_days": capacity_breach_days,
            "capacity_max_participation": capacity_max_participation,
        }

    macro_engine_cfg = MacroRunConfig(
        exp=str(raw_config.get("exp", args.exp)),
        rebalance=rebalance_freq,
        costs=engine_costs,
    )

    def _build_fold_signal_model(train_idx: pd.DatetimeIndex) -> Any:
        """Create and fit a fold-local model to prevent cross-fold leakage."""
        model = build_macro_signal(signal_cfg)
        model.fit(prices.reindex(train_idx), None, meta)
        return model

    def _strategy_signal(
        signal_model: Any,
        _cfg: MacroRunConfig,
        px: pd.DataFrame,
        *,
        with_regime: bool = True,
    ) -> pd.Series:
        scores_t = signal_model.compute(px, None, meta).iloc[-1]

        vol_t: pd.Series | None
        if vol_scale_lb > 1:
            vol_t = px.pct_change().rolling(vol_scale_lb).std().iloc[-1] * np.sqrt(252.0)
        else:
            vol_t = None

        bucket_multipliers = None
        if with_regime and regime_enabled:
            regime = compute_risk_off_regime(
                px,
                lag_days=regime_lag,
                rates_proxy=regime_rates,
                equity_proxy=regime_equity,
                lookback_days=regime_lb,
            )
            risk_off = int(regime.iloc[-1]) if len(regime) else 0
            if risk_off == 1:
                bucket_multipliers = risk_off_multipliers

        w = build_weights(
            scores_t=scores_t,
            vol_t=vol_t,
            meta=meta,
            gross_cap=gross_cap,
            net_target=net_target,
            net_band=net_band,
            per_asset_cap=default_per_asset_cap,
            bucket_caps=bucket_caps,
            bucket_multipliers=bucket_multipliers,
        )

        if vol_target > 0:
            trailing = px.pct_change().dropna()
            w = apply_vol_target(
                w,
                trailing_returns=trailing,
                target_vol_annual=vol_target,
                lookback_days=vol_lookback_days,
                gross_cap=gross_cap,
            )
        return w

    # ── Run folds ────────────────────────────────────────────────────────
    net_parts: list[pd.Series] = []
    gross_parts: list[pd.Series] = []
    turnover_parts: list[pd.Series] = []
    gross_exposure_parts: list[pd.Series] = []
    net_exposure_parts: list[pd.Series] = []
    short_exposure_parts: list[pd.Series] = []
    costs_parts: list[pd.Series] = []
    financing_cost_parts: list[pd.Series] = []
    borrow_cost_parts: list[pd.Series] = []
    carry_cost_parts: list[pd.Series] = []
    costs_asset_parts: list[pd.DataFrame] = []
    turnover_asset_parts: list[pd.DataFrame] = []
    participation_parts: list[pd.DataFrame] = []
    rebalance_weights_parts: list[pd.DataFrame] = []
    daily_weights_parts: list[pd.DataFrame] = []
    bucket_exp_parts: list[pd.DataFrame] = []
    eval_folds: list[dict[str, Any]] = []
    by_fold_results: list[dict[str, Any]] = []
    capacity_breach_days_total = 0
    capacity_max_participation = 0.0

    for i, (train_dates, test_dates) in enumerate(folds, start=1):
        seg_prices = prices.loc[train_dates.min() : test_dates.max()]
        fold_id = f"fold_{i - 1}"
        fold_signal_model = _build_fold_signal_model(train_dates)

        fold_res = run_daily_backtest(
            macro_engine_cfg,
            seg_prices,
            lambda cfg, p, model=fold_signal_model: _strategy_signal(
                model, cfg, p, with_regime=True
            ),
        )

        test_idx = test_dates
        fold_gross = fold_res.gross_returns.reindex(test_idx).fillna(0.0)
        fold_to = fold_res.turnover.reindex(test_idx).fillna(0.0)

        fold_gross_exposure = fold_res.gross_exposure.reindex(test_idx).ffill().fillna(0.0)
        fold_net_exposure = fold_res.net_exposure.reindex(test_idx).ffill().fillna(0.0)

        fold_costs = fold_res.costs.reindex(test_idx).fillna(0.0)
        fold_to_asset = fold_res.turnover_by_asset.reindex(test_idx).fillna(0.0)
        fold_cost_asset = fold_res.costs_by_asset.reindex(test_idx).fillna(0.0)

        fold_weights_rebal = fold_res.weights[fold_res.weights.index.isin(test_idx)]
        daily_w = (
            fold_res.weights.reindex(seg_prices.index)
            .ffill()
            .fillna(0.0)
            .reindex(test_idx)
            .fillna(0.0)
        )

        overlay = _apply_execution_realism(
            fold_label=fold_id,
            test_idx=test_idx,
            fold_gross=fold_gross,
            fold_costs=fold_costs,
            fold_cost_asset=fold_cost_asset,
            fold_to_asset=fold_to_asset,
            fold_gross_exposure=fold_gross_exposure,
            daily_w=daily_w,
        )
        fold_net = overlay["net"]
        fold_costs = overlay["costs"]
        fold_cost_asset = overlay["costs_by_asset"]
        fold_short_exposure = overlay["short_exposure"]
        fold_financing_costs = overlay["financing_costs"]
        fold_borrow_costs = overlay["borrow_costs"]
        fold_carry_costs = overlay["carry_costs"]
        fold_participation = overlay["participation"]
        capacity_breach_days_total += int(overlay["capacity_breach_days"])
        capacity_max_participation = max(
            capacity_max_participation, float(overlay["capacity_max_participation"])
        )

        fold_bucket_exp = _bucket_exposure_from_weights(daily_w, meta)

        fold_metrics = summary(fold_net, turnover=fold_to, gross_returns=fold_gross)
        eval_folds.append(
            {
                "fold_id": fold_id,
                "train_start": str(train_dates.min().date()),
                "train_end": str(train_dates.max().date()),
                "test_start": str(test_dates.min().date()),
                "test_end": str(test_dates.max().date()),
                "embargo_days": embargo_days,
            }
        )
        by_fold_results.append(
            {
                "fold_id": fold_id,
                "metrics_net": _metric_view(fold_metrics),
                "turnover_annualized": float(fold_to.mean() * 252.0),
                "gross_avg": float(fold_gross_exposure.mean()),
                "net_avg": float(fold_net_exposure.mean()),
            }
        )

        net_parts.append(fold_net)
        gross_parts.append(fold_gross)
        turnover_parts.append(fold_to)
        gross_exposure_parts.append(fold_gross_exposure)
        net_exposure_parts.append(fold_net_exposure)
        short_exposure_parts.append(fold_short_exposure)
        costs_parts.append(fold_costs)
        financing_cost_parts.append(fold_financing_costs)
        borrow_cost_parts.append(fold_borrow_costs)
        carry_cost_parts.append(fold_carry_costs)
        turnover_asset_parts.append(fold_to_asset)
        costs_asset_parts.append(fold_cost_asset)
        if capacity_enabled:
            participation_parts.append(fold_participation)
        rebalance_weights_parts.append(fold_weights_rebal)
        daily_weights_parts.append(daily_w)
        bucket_exp_parts.append(fold_bucket_exp)

    net_returns = _concat_series(net_parts, "net_return")
    gross_returns = _concat_series(gross_parts, "gross_return")
    turnover = _concat_series(turnover_parts, "turnover")
    gross_exposure = _concat_series(gross_exposure_parts, "gross_exposure")
    net_exposure = _concat_series(net_exposure_parts, "net_exposure")
    short_exposure = _concat_series(short_exposure_parts, "short_exposure")
    costs = _concat_series(costs_parts, "costs")
    financing_costs = _concat_series(financing_cost_parts, "financing_costs")
    borrow_costs = _concat_series(borrow_cost_parts, "borrow_costs")
    carry_costs_total = _concat_series(carry_cost_parts, "carry_costs")

    turnover_by_asset = _concat_frames(turnover_asset_parts).reindex(columns=tickers).fillna(0.0)
    costs_by_asset = _concat_frames(costs_asset_parts).reindex(columns=tickers).fillna(0.0)
    weights = _concat_frames(rebalance_weights_parts).reindex(columns=tickers).fillna(0.0)
    weights_daily = _concat_frames(daily_weights_parts).reindex(columns=tickers).fillna(0.0)
    bucket_exposure = _concat_frames(bucket_exp_parts).fillna(0.0)
    participation = (
        _concat_frames(participation_parts).reindex(columns=tickers).fillna(0.0)
        if participation_parts
        else pd.DataFrame(0.0, index=net_returns.index, columns=tickers, dtype=float)
    )

    metrics = summary(net_returns, turnover=turnover, gross_returns=gross_returns)

    # ── Baselines ────────────────────────────────────────────────────────
    def _baseline_metrics(static_weights: pd.Series) -> tuple[dict[str, float], pd.Series]:
        parts_net: list[pd.Series] = []
        parts_gross: list[pd.Series] = []
        parts_to: list[pd.Series] = []
        for train_dates, test_dates in folds:
            seg_prices = prices.loc[train_dates.min() : test_dates.max()]
            r = run_daily_backtest(
                macro_engine_cfg,
                seg_prices,
                lambda _cfg, _p: static_weights,
            )
            idx = test_dates
            fold_gross = r.gross_returns.reindex(idx).fillna(0.0)
            fold_to = r.turnover.reindex(idx).fillna(0.0)
            fold_costs = r.costs.reindex(idx).fillna(0.0)
            fold_to_asset = r.turnover_by_asset.reindex(idx).fillna(0.0)
            fold_cost_asset = r.costs_by_asset.reindex(idx).fillna(0.0)
            fold_gross_exposure = r.gross_exposure.reindex(idx).ffill().fillna(0.0)
            daily_w = (
                r.weights.reindex(seg_prices.index).ffill().fillna(0.0).reindex(idx).fillna(0.0)
            )

            overlay = _apply_execution_realism(
                fold_label="baseline",
                test_idx=idx,
                fold_gross=fold_gross,
                fold_costs=fold_costs,
                fold_cost_asset=fold_cost_asset,
                fold_to_asset=fold_to_asset,
                fold_gross_exposure=fold_gross_exposure,
                daily_w=daily_w,
            )

            parts_net.append(overlay["net"])
            parts_gross.append(fold_gross)
            parts_to.append(fold_to)

        bn = _concat_series(parts_net, "net_return")
        bg = _concat_series(parts_gross, "gross_return")
        bt = _concat_series(parts_to, "turnover")
        return summary(bn, turnover=bt, gross_returns=bg), bn

    eq_w = equal_weight_long_only(tickers, gross_cap=gross_cap)
    eq_metrics, _eq_returns = _baseline_metrics(eq_w)

    sixty_w = sixty_forty_proxy(tickers, gross_cap=gross_cap)
    sixty_metrics, sixty_returns = _baseline_metrics(sixty_w)

    no_reg_parts_net: list[pd.Series] = []
    no_reg_parts_gross: list[pd.Series] = []
    no_reg_parts_to: list[pd.Series] = []
    for train_dates, test_dates in folds:
        seg_prices = prices.loc[train_dates.min() : test_dates.max()]
        fold_signal_model = _build_fold_signal_model(train_dates)
        r = run_daily_backtest(
            macro_engine_cfg,
            seg_prices,
            lambda cfg, p, model=fold_signal_model: _strategy_signal(
                model, cfg, p, with_regime=False
            ),
        )
        idx = test_dates
        fold_gross = r.gross_returns.reindex(idx).fillna(0.0)
        fold_to = r.turnover.reindex(idx).fillna(0.0)
        fold_costs = r.costs.reindex(idx).fillna(0.0)
        fold_to_asset = r.turnover_by_asset.reindex(idx).fillna(0.0)
        fold_cost_asset = r.costs_by_asset.reindex(idx).fillna(0.0)
        fold_gross_exposure = r.gross_exposure.reindex(idx).ffill().fillna(0.0)
        daily_w = r.weights.reindex(seg_prices.index).ffill().fillna(0.0).reindex(idx).fillna(0.0)
        overlay = _apply_execution_realism(
            fold_label="trend_no_regime",
            test_idx=idx,
            fold_gross=fold_gross,
            fold_costs=fold_costs,
            fold_cost_asset=fold_cost_asset,
            fold_to_asset=fold_to_asset,
            fold_gross_exposure=fold_gross_exposure,
            daily_w=daily_w,
        )
        no_reg_parts_net.append(overlay["net"])
        no_reg_parts_gross.append(fold_gross)
        no_reg_parts_to.append(fold_to)

    no_reg_net = _concat_series(no_reg_parts_net, "net_return")
    no_reg_gross = _concat_series(no_reg_parts_gross, "gross_return")
    no_reg_to = _concat_series(no_reg_parts_to, "turnover")
    no_reg_metrics = summary(no_reg_net, turnover=no_reg_to, gross_returns=no_reg_gross)

    baselines = {
        "equal_weight_long_only": {k: float(v) for k, v in eq_metrics.items()},
        "sixty_forty_proxy": {k: float(v) for k, v in sixty_metrics.items()},
        "trend_no_regime": {k: float(v) for k, v in no_reg_metrics.items()},
    }
    sixty_bond = "IEF" if "IEF" in tickers else ("TLT" if "TLT" in tickers else tickers[0])
    baselines_payload = [
        {
            "name": "equal_weight_long_only",
            "params": {"gross_cap": gross_cap, "long_only": True},
            "metrics_net": _gross_metric_view(eq_metrics),
        },
        {
            "name": "60_40_proxy",
            "params": {"equity": "SPY", "bond": sixty_bond, "gross_cap": gross_cap},
            "metrics_net": _gross_metric_view(sixty_metrics),
        },
        {
            "name": "trend_only_no_regime",
            "params": {
                "signal_name": signal_name,
                "method": signal_method,
                "fast": fast,
                "slow": slow,
                "lookback_days": lookback_days,
            },
            "metrics_net": _gross_metric_view(no_reg_metrics),
        },
    ]

    # ── Cost stress ──────────────────────────────────────────────────────
    regime_state_full = regime_series.reindex(net_returns.index).fillna(0).astype(int)
    regime_cost_mult_series = pd.Series(
        np.where(regime_state_full == 1, regime_cost_mult_off, regime_cost_mult_on),
        index=net_returns.index,
        dtype=float,
    )
    cost_stress: dict[str, dict[str, float]] = {}
    cost_stress_payload: list[dict[str, Any]] = []
    used_stress_labels: set[str] = set()
    for mult in stress_multipliers:
        base_label = f"{mult:g}x"
        label = base_label
        suffix = 2
        while label in used_stress_labels:
            label = f"{base_label}_{suffix}"
            suffix += 1
        used_stress_labels.add(label)

        stressed_txn_asset = turnover_by_asset.mul(base_asset_cost_bps * mult, axis=1) / 1e4
        stressed_txn_asset = stressed_txn_asset.mul(regime_cost_mult_series, axis=0)

        stressed_impact_asset = pd.DataFrame(
            0.0, index=net_returns.index, columns=tickers, dtype=float
        )
        if impact_enabled and impact_coeff_bps > 0:
            stress_impact_bps = turnover_impact_bps(
                turnover_by_asset,
                turnover_ref=impact_turnover_ref,
                coefficient_bps=impact_coeff_bps * mult,
                exponent=impact_exponent,
            )
            stressed_impact_asset = turnover_by_asset.mul(stress_impact_bps, axis=0) / 1e4

        stressed_capacity_asset = pd.DataFrame(
            0.0, index=net_returns.index, columns=tickers, dtype=float
        )
        if capacity_enabled and capacity_impact_bps > 0:
            cap_bps = np.sqrt(participation.clip(lower=0.0)) * (capacity_impact_bps * mult)
            stressed_capacity_asset = turnover_by_asset.mul(cap_bps, axis=0) / 1e4

        stressed_total_cost = (
            stressed_txn_asset.sum(axis=1)
            + stressed_impact_asset.sum(axis=1)
            + stressed_capacity_asset.sum(axis=1)
            + carry_costs_total.reindex(net_returns.index).fillna(0.0)
        )
        stressed_net = gross_returns - stressed_total_cost
        stress_metrics = summary(stressed_net, turnover=turnover, gross_returns=gross_returns)
        cost_stress[label] = {k: float(v) for k, v in stress_metrics.items()}
        cost_stress_payload.append(
            {
                "multiplier": float(mult),
                "metrics_net": _gross_metric_view(stress_metrics),
                "total_cost_return": -float(stressed_total_cost.sum()),
            }
        )

    # ── Risk attribution + regime split ──────────────────────────────────
    asset_returns = prices.pct_change().reindex(net_returns.index).fillna(0.0)
    asset_rc, bucket_rc = compute_risk_contributions(
        weights_daily,
        asset_returns,
        meta,
        window=63,
    )

    regime_on_idx = net_returns.index[
        regime_series.reindex(net_returns.index).fillna(0).astype(int) == 0
    ]
    regime_off_idx = net_returns.index[
        regime_series.reindex(net_returns.index).fillna(0).astype(int) == 1
    ]

    regime_split = {}
    if len(regime_on_idx) > 0:
        regime_split["risk_on"] = {
            k: float(v)
            for k, v in summary(
                net_returns.reindex(regime_on_idx),
                turnover=turnover.reindex(regime_on_idx),
                gross_returns=gross_returns.reindex(regime_on_idx),
            ).items()
        }
    if len(regime_off_idx) > 0:
        regime_split["risk_off"] = {
            k: float(v)
            for k, v in summary(
                net_returns.reindex(regime_off_idx),
                turnover=turnover.reindex(regime_off_idx),
                gross_returns=gross_returns.reindex(regime_off_idx),
            ).items()
        }

    # ── Save primary CSV artefacts ───────────────────────────────────────
    net_returns.to_csv(rdir / "returns.csv", header=True)
    gross_returns.to_csv(rdir / "gross_returns.csv", header=True)
    turnover.to_csv(rdir / "turnover.csv", header=True)
    weights.to_csv(rdir / "weights.csv")
    gross_exposure.to_csv(rdir / "gross_exposure.csv", header=True)
    net_exposure.to_csv(rdir / "net_exposure.csv", header=True)
    short_exposure.to_csv(rdir / "short_exposure.csv", header=True)
    bucket_exposure.to_csv(rdir / "bucket_exposure.csv")
    costs.to_csv(rdir / "costs.csv", header=True)
    financing_costs.to_csv(rdir / "financing_costs.csv", header=True)
    borrow_costs.to_csv(rdir / "borrow_costs.csv", header=True)
    carry_costs_total.to_csv(rdir / "carry_costs.csv", header=True)
    costs_by_asset.to_csv(rdir / "costs_by_asset.csv")
    if capacity_enabled:
        participation.to_csv(rdir / "capacity_participation.csv")

    with open(rdir / "metrics.json", "w") as fh:
        json.dump({k: round(float(v), 6) for k, v in metrics.items()}, fh, indent=2)

    # ── Figures ──────────────────────────────────────────────────────────
    from matplotlib import pyplot as plt

    fig_dir = rdir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    fig = cumulative_returns(
        net_returns,
        title=f"{raw_config.get('exp', args.exp)} — Equity Curve (Post-Cost)",
        benchmark=sixty_returns.reindex(net_returns.index),
    )
    fig.savefig(fig_dir / "equity_curve.png", dpi=150, bbox_inches="tight")

    fig = drawdown(net_returns, title=f"{raw_config.get('exp', args.exp)} — Drawdown")
    fig.savefig(fig_dir / "drawdown.png", dpi=150, bbox_inches="tight")

    fig = turnover_plot(turnover, title=f"{raw_config.get('exp', args.exp)} — Turnover")
    fig.savefig(fig_dir / "turnover.png", dpi=150, bbox_inches="tight")

    fig = gross_net_exposure(gross_exposure, net_exposure, title="Gross / Net Exposure")
    fig.savefig(fig_dir / "gross_net_exposure.png", dpi=150, bbox_inches="tight")

    fig = bucket_exposure_plot(bucket_exposure, title="Bucket Net Exposure")
    fig.savefig(fig_dir / "bucket_exposure.png", dpi=150, bbox_inches="tight")

    fig = risk_contribution_plot(bucket_rc, title="Risk Contribution by Bucket")
    fig.savefig(fig_dir / "risk_contribution_bucket.png", dpi=150, bbox_inches="tight")

    if capacity_enabled and not participation.empty:
        fig = capacity_participation_plot(
            participation,
            limit=capacity_max_adv_participation,
            title="Capacity Participation (Max / P95)",
        )
        fig.savefig(fig_dir / "capacity_participation.png", dpi=150, bbox_inches="tight")

    plt.close("all")

    # ── results.json ─────────────────────────────────────────────────────
    rounded_metrics = {k: round(float(v), 6) for k, v in metrics.items()}

    exposure_summary = {
        "avg_gross_exposure": float(gross_exposure.mean()),
        "avg_net_exposure": float(net_exposure.mean()),
        "avg_short_exposure": float(short_exposure.mean()),
        "avg_turnover": float(turnover[turnover > 0].mean()) if (turnover > 0).any() else 0.0,
        "total_costs": float(costs.sum()),
        "total_financing_costs": float(financing_costs.sum()),
        "total_borrow_costs": float(borrow_costs.sum()),
        "total_carry_costs": float(carry_costs_total.sum()),
    }

    risk_summary = {
        f"bucket_rc_{k}": float(v) for k, v in bucket_rc.mean().sort_index().to_dict().items()
    }
    risk_summary.update(
        {
            f"asset_rc_{k}": float(v)
            for k, v in asset_rc.mean().sort_values(ascending=False).head(3).to_dict().items()
        }
    )
    spy_proxy = "SPY" if "SPY" in prices.columns else prices.columns[0]
    spy_returns = prices[spy_proxy].pct_change().reindex(net_returns.index).fillna(0.0)
    corr_spy = _safe_corr(net_returns, spy_returns)
    spy_mdd = float(summary(spy_returns).get("max_dd", 0.0))
    mdd_vs_spy = float(metrics.get("max_dd", 0.0) - spy_mdd)

    gross_metrics = summary(gross_returns)
    metrics_net_schema = _metric_view(metrics)
    metrics_gross_schema = _gross_metric_view(gross_metrics)

    avg_daily_turnover = float(turnover.mean())
    avg_rebalance_turnover = float(turnover[turnover > 0].mean()) if (turnover > 0).any() else 0.0
    annualized_turnover = float(avg_daily_turnover * 252.0)

    tables_dir = rdir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    cost_stress_rows = []
    for row in cost_stress_payload:
        flat = {
            "multiplier": row["multiplier"],
            "total_cost_return": row["total_cost_return"],
        }
        flat.update({f"metrics_net_{k}": v for k, v in row["metrics_net"].items()})
        cost_stress_rows.append(flat)
    pd.DataFrame(cost_stress_rows).to_csv(tables_dir / "cost_stress.csv", index=False)

    by_fold_rows = []
    for row in by_fold_results:
        flat = {
            "fold_id": row["fold_id"],
            "turnover_annualized": row["turnover_annualized"],
            "gross_avg": row["gross_avg"],
            "net_avg": row["net_avg"],
        }
        flat.update({f"metrics_net_{k}": v for k, v in row["metrics_net"].items()})
        by_fold_rows.append(flat)
    pd.DataFrame(by_fold_rows).to_csv(tables_dir / "by_fold_metrics.csv", index=False)

    if capacity_enabled:
        cap = participation.reindex(columns=tickers).fillna(0.0)
        cap_summary = pd.DataFrame(
            {
                "ticker": cap.columns,
                "mean_participation": cap.mean(axis=0).to_numpy(),
                "p95_participation": cap.quantile(0.95, axis=0).to_numpy(),
                "max_participation": cap.max(axis=0).to_numpy(),
                "breach_days": (cap > capacity_max_adv_participation)
                .sum(axis=0)
                .astype(int)
                .to_numpy(),
            }
        )
        if len(cap) > 0:
            cap_summary["breach_rate"] = cap_summary["breach_days"] / float(len(cap))
        else:
            cap_summary["breach_rate"] = 0.0
        cap_summary.to_csv(tables_dir / "capacity_summary.csv", index=False)

        if len(cap) > 0:
            day_max = cap.max(axis=1)
            day_argmax = cap.idxmax(axis=1)
            breach_mask = day_max > capacity_max_adv_participation
            cap_breaches = pd.DataFrame(
                {
                    "date": cap.index,
                    "max_participation": day_max.to_numpy(),
                    "max_asset": day_argmax.to_numpy(),
                    "breach_limit": breach_mask.to_numpy(),
                }
            )
            cap_breaches = cap_breaches[cap_breaches["breach_limit"]].reset_index(drop=True)
        else:
            cap_breaches = pd.DataFrame(
                columns=["date", "max_participation", "max_asset", "breach_limit"]
            )
        cap_breaches.to_csv(tables_dir / "capacity_breaches.csv", index=False)

    ticker_meta_records: list[dict[str, Any]] = []
    for _, row in meta.reset_index(drop=True).iterrows():
        rec = {
            "ticker": str(row["ticker"]),
            "bucket": str(row["bucket"]),
            "cost_bps": float(row["cost_bps"]),
            "per_asset_cap": float(row["per_asset_cap"]),
        }
        if "adv_usd" in meta.columns and pd.notna(row.get("adv_usd")):
            rec["adv_usd"] = float(row["adv_usd"])
        if "adv_usd_mn" in meta.columns and pd.notna(row.get("adv_usd_mn")):
            rec["adv_usd_mn"] = float(row["adv_usd_mn"])
        ticker_meta_records.append(rec)

    run_meta = _finalize_meta(rdir)
    data_snapshot_id = _compute_data_snapshot_id(prices)
    artifact_hashes = _artifact_hashes(
        net_returns=net_returns,
        gross_returns=gross_returns,
        turnover=turnover,
        costs=costs,
        weights=weights,
        weights_daily=weights_daily,
        bucket_exposure=bucket_exposure,
        costs_by_asset=costs_by_asset,
    )
    results_hash = compute_results_hash(
        rounded_metrics,
        config_hash=raw_config_hash,
        toy_seed=args.toy_seed,
        data_snapshot_id=data_snapshot_id,
        artifact_hashes=artifact_hashes,
    )

    results = {
        "schema_version": "1.0",
        "run": {
            "run_id": rid,
            "exp_name": raw_config.get("exp", args.exp),
            "timestamp_utc": run_meta.get("end_time", _utc_now_iso()),
            "git_commit": run_meta.get("git_commit", "unknown") or "unknown",
            "config_path": str(config_path),
            "config_hash": raw_config_hash,
            "data_snapshot_id": data_snapshot_id,
            "results_hash": results_hash,
        },
        "universe": {
            "tickers": tickers,
            "ticker_meta": ticker_meta_records,
            "constraints": {
                "gross_cap": gross_cap,
                "net_target": net_target,
                "net_band": net_band,
                "bucket_gross_caps": bucket_caps,
            },
        },
        "evaluation": {
            "frequency": "daily",
            "rebalance_rule": rebalance_freq,
            "calendar": calendar_label,
            "folds": eval_folds,
        },
        "strategy": {
            "name": strategy_signal_label,
            "params": {
                "signal_name": signal_name,
                "method": signal_method,
                "fast": fast,
                "slow": slow,
                "lookback_days": lookback_days,
                "vol_scale_lookback": vol_scale_lb,
                "signal_config": _round_nested(signal_cfg),
            },
            "assumptions": {
                "macro_lag_days": regime_lag if regime_enabled else 0,
                "financing_included": financing_bps_annual > 0,
                "short_borrow_included": short_borrow_bps_annual > 0,
            },
        },
        "results": {
            "overall": {
                "metrics_net": metrics_net_schema,
                "metrics_gross": metrics_gross_schema,
                "turnover": {
                    "avg_daily": avg_daily_turnover,
                    "avg_rebalance": avg_rebalance_turnover,
                    "annualized": annualized_turnover,
                },
                "costs": {
                    "total_cost_return": -float(costs.sum()),
                    "avg_daily_cost_return": -float(costs.mean()),
                    "assumed_costs": {
                        "use_meta_costs": use_meta_costs,
                        "cost_multiplier": 1.0,
                        "financing_bps_annual": financing_bps_annual,
                        "short_borrow_bps_annual": short_borrow_bps_annual,
                        "regime_multipliers": {
                            "risk_on": regime_cost_mult_on,
                            "risk_off": regime_cost_mult_off,
                        },
                        "impact": {
                            "enabled": impact_enabled,
                            "turnover_ref": impact_turnover_ref,
                            "coefficient_bps": impact_coeff_bps,
                            "exponent": impact_exponent,
                        },
                        "capacity": {
                            "enabled": capacity_enabled,
                            "notional_usd": capacity_notional_usd,
                            "max_adv_participation": capacity_max_adv_participation,
                            "impact_bps_at_100pct_adv": capacity_impact_bps,
                            "adv_column": capacity_adv_column,
                            "breach_action": capacity_breach_action,
                        },
                    },
                },
                "exposure": {
                    "gross_avg": float(gross_exposure.mean()),
                    "gross_p95": float(gross_exposure.quantile(0.95)),
                    "net_avg": float(net_exposure.mean()),
                    "net_p95_abs": float(net_exposure.abs().quantile(0.95)),
                    "short_avg": float(short_exposure.mean()),
                },
            },
            "by_fold": by_fold_results,
            "cost_stress": cost_stress_payload,
            "baselines": baselines_payload,
            "diagnostics": {
                "correlation_to": {"SPY": corr_spy},
                "risk_contrib_by_bucket_avg": {
                    str(k): float(v) for k, v in bucket_rc.mean().sort_index().to_dict().items()
                },
                "max_drawdown_vs_spy": {
                    "strategy_max_drawdown": float(metrics.get("max_dd", 0.0)),
                    "spy_max_drawdown": spy_mdd,
                    "difference": mdd_vs_spy,
                },
                "execution_realism": {
                    "carry_cost_total": float(carry_costs_total.sum()),
                    "financing_cost_total": float(financing_costs.sum()),
                    "borrow_cost_total": float(borrow_costs.sum()),
                    "capacity_breach_days": int(capacity_breach_days_total),
                    "capacity_max_participation": float(capacity_max_participation),
                    "capacity_limit": float(capacity_max_adv_participation),
                },
            },
        },
        "artifacts": {
            "figures": [
                {"name": "equity_curve_net", "path": "figures/equity_curve.png"},
                {"name": "drawdown", "path": "figures/drawdown.png"},
                {"name": "turnover", "path": "figures/turnover.png"},
                {"name": "gross_net_exposure", "path": "figures/gross_net_exposure.png"},
                {"name": "bucket_exposure", "path": "figures/bucket_exposure.png"},
                {
                    "name": "risk_contribution_by_bucket",
                    "path": "figures/risk_contribution_bucket.png",
                },
            ],
            "tables": [
                {"name": "cost_stress", "path": "tables/cost_stress.csv"},
                {"name": "by_fold_metrics", "path": "tables/by_fold_metrics.csv"},
                {"name": "short_exposure", "path": "short_exposure.csv"},
                {"name": "financing_costs", "path": "financing_costs.csv"},
                {"name": "borrow_costs", "path": "borrow_costs.csv"},
                {"name": "carry_costs", "path": "carry_costs.csv"},
            ],
            "hashes": artifact_hashes,
        },
    }
    if capacity_enabled:
        results["artifacts"]["figures"].append(
            {"name": "capacity_participation", "path": "figures/capacity_participation.png"}
        )
        results["artifacts"]["tables"].append(
            {"name": "capacity_participation", "path": "capacity_participation.csv"}
        )
        results["artifacts"]["tables"].append(
            {"name": "capacity_summary", "path": "tables/capacity_summary.csv"}
        )
        results["artifacts"]["tables"].append(
            {"name": "capacity_breaches", "path": "tables/capacity_breaches.csv"}
        )

    # Keep legacy keys as non-breaking aliases while report readers migrate.
    results["legacy"] = {
        "run_id": rid,
        "results_hash": results_hash,
        "config_hash": raw_config_hash,
        "toy_seed": int(args.toy_seed),
        "metrics": rounded_metrics,
        "baselines": baselines,
        "cost_stress": cost_stress,
        "regime_split": regime_split,
        "exposure_summary": exposure_summary,
        "risk_summary": risk_summary,
    }

    with open(rdir / "results.json", "w") as fh:
        json.dump(_round_nested(results), fh, indent=2)

    # ── report.md ────────────────────────────────────────────────────────

    figure_filenames = [
        "figures/equity_curve.png",
        "figures/drawdown.png",
        "figures/turnover.png",
        "figures/gross_net_exposure.png",
        "figures/bucket_exposure.png",
        "figures/risk_contribution_bucket.png",
    ]
    if capacity_enabled and (fig_dir / "capacity_participation.png").exists():
        figure_filenames.append("figures/capacity_participation.png")

    save_macro_allocator_report(
        raw_config.get("exp", args.exp),
        output_dir=rdir,
        metrics=metrics,
        baselines=baselines,
        cost_stress=cost_stress,
        regime_split=regime_split,
        exposure_summary=exposure_summary,
        risk_summary=risk_summary,
        figure_filenames=figure_filenames,
        meta=run_meta,
    )

    log.info("✅ Macro allocator run complete → %s", rdir)
    print(f"RUN_ID={rid}")


def _run_legacy(
    args: argparse.Namespace,
    *,
    config_path: Path,
    raw_config: dict[str, Any],
    rid: str,
    rdir: Path,
) -> None:
    """Week-1 path (kept for backward compatibility)."""
    config = load_config(config_path)
    log.info("Loaded config: %s (strategy=%s)", config.exp, config.strategy)

    # Resolve strategy
    try:
        strategy_fn = get_strategy(config.strategy)
    except KeyError as exc:
        log.error(str(exc))
        sys.exit(1)

    # Load prices
    from lab.data.loader import load_prices_or_make_toy

    prices = load_prices_or_make_toy(config, seed=args.toy_seed)
    log.info("  Prices: %d days × %d assets", *prices.shape)

    # Backtest
    from lab.backtest.daily_engine import run_daily_backtest

    result = run_daily_backtest(config, prices, strategy_fn)

    # Save CSVs
    result.returns.to_csv(rdir / "returns.csv", header=True)
    result.gross_returns.to_csv(rdir / "gross_returns.csv", header=True)
    if not result.weights.empty:
        result.weights.to_csv(rdir / "weights.csv")
    result.turnover.to_csv(rdir / "turnover.csv", header=True)
    log.info("CSVs saved.")

    # Metrics
    from lab.eval.metrics import summary

    metrics = summary(
        result.returns,
        turnover=result.turnover,
        gross_returns=result.gross_returns,
    )
    with open(rdir / "metrics.json", "w") as fh:
        json.dump({k: round(float(v), 6) for k, v in metrics.items()}, fh, indent=2)
    log.info("Metrics: %s", {k: f"{v:.4f}" for k, v in metrics.items()})

    # results.json
    rounded_metrics = {k: round(float(v), 6) for k, v in metrics.items()}
    config_hash = compute_config_hash(raw_config)
    data_snapshot_id = _compute_data_snapshot_id(prices)
    artifact_hashes = {
        "returns": compute_stable_series_hash(result.returns),
        "gross_returns": compute_stable_series_hash(result.gross_returns),
        "turnover": compute_stable_series_hash(result.turnover),
        "weights": compute_stable_frame_hash(
            result.weights.reindex(columns=list(config.universe)).fillna(0.0)
        ),
    }
    results_hash = compute_results_hash(
        rounded_metrics,
        config_hash=config_hash,
        toy_seed=args.toy_seed,
        data_snapshot_id=data_snapshot_id,
        artifact_hashes=artifact_hashes,
    )

    results = {
        "metrics": rounded_metrics,
        "results_hash": results_hash,
        "config_hash": config_hash,
        "data_snapshot_id": data_snapshot_id,
        "toy_seed": args.toy_seed,
        "artifact_hashes": artifact_hashes,
        "config": {
            "exp": config.exp,
            "strategy": config.strategy,
            "universe": list(config.universe),
            "start_date": config.start_date,
            "end_date": config.end_date,
            "rebalance": config.rebalance,
            "signal": config.signal,
            "costs_bps": config.costs_bps,
            "initial_capital": config.initial_capital,
        },
        "run_id": rid,
    }
    with open(rdir / "results.json", "w") as fh:
        json.dump(results, fh, indent=2)

    # Figures
    from lab.eval.plots import cumulative_returns, drawdown, turnover_plot

    fig_dir = rdir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    fig1 = cumulative_returns(result.returns, title=f"{config.exp} — Cumulative Returns")
    fig1.savefig(fig_dir / "cumulative_returns.png", dpi=150, bbox_inches="tight")

    fig2 = drawdown(result.returns, title=f"{config.exp} — Drawdown")
    fig2.savefig(fig_dir / "drawdown.png", dpi=150, bbox_inches="tight")

    fig3 = turnover_plot(result.turnover, title=f"{config.exp} — Turnover")
    fig3.savefig(fig_dir / "turnover.png", dpi=150, bbox_inches="tight")

    import matplotlib.pyplot as plt

    plt.close("all")

    from lab.eval.reports import save_report

    figure_filenames = [
        f"figures/{f}"
        for f in ["cumulative_returns.png", "drawdown.png", "turnover.png"]
        if (fig_dir / f).exists()
    ]

    meta = _finalize_meta(rdir)

    save_report(
        config.exp,
        metrics=metrics,
        output_dir=rdir,
        figure_filenames=figure_filenames,
        meta=meta,
    )

    log.info("✅ Run complete → %s", rdir)
    print(f"RUN_ID={rid}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an alpha-research experiment.")
    parser.add_argument(
        "--exp",
        type=str,
        required=True,
        help="Experiment family name, e.g. 'macro_equities'.",
    )
    parser.add_argument(
        "--config",
        type=str,
        required=True,
        help="Path to experiment YAML config.",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    parser.add_argument(
        "--toy-seed",
        type=int,
        default=42,
        help="RNG seed used when toy synthetic data is generated.",
    )
    args = parser.parse_args()

    setup_logging(level=args.log_level)

    # ── Load raw config + create run folder ─────────────────────────────
    config_path = Path(args.config).resolve()
    raw_config = load_raw_config(config_path)
    if "universe_config" in raw_config:
        validate_macro_allocator_config(raw_config)

    rid, rdir = create_run(
        exp_name=args.exp,
        config_path=config_path,
        raw_config=raw_config,
    )
    log.info("Run id: %s → %s", rid, rdir)

    # Copy config for reproducibility
    shutil.copy2(config_path, rdir / "config.yaml")

    raw_config_hash = compute_config_hash(raw_config)

    if "universe_config" in raw_config:
        _run_macro_allocator(
            args,
            config_path=config_path,
            raw_config=raw_config,
            rid=rid,
            rdir=rdir,
            raw_config_hash=raw_config_hash,
        )
    else:
        _run_legacy(
            args,
            config_path=config_path,
            raw_config=raw_config,
            rid=rid,
            rdir=rdir,
        )


if __name__ == "__main__":
    main()
