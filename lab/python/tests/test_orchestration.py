"""
test_orchestration.py
~~~~~~~~~~~~~~~~~~~~~
Acceptance tests for the orchestration layer:

- §6  Config schema: flat AND nested formats work
- §6  Data loader: load_prices_or_make_toy falls back to GBM
- §6  results.json: metrics + key config fields
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# ══════════════════════════════════════════════════════════════════════════════
# Config schema — flat vs nested
# ══════════════════════════════════════════════════════════════════════════════


class TestConfigFlatFormat:
    """Legacy flat format: signal=int, costs=float."""

    def test_flat_signal_and_costs(self) -> None:
        from lab.core.config import ExperimentConfig

        cfg = ExperimentConfig(
            exp="test",
            universe=("A", "B"),
            start_date="2020-01-01",
            end_date="2020-12-31",
            rebalance="monthly",
            signal=252,
            costs=8.0,
            initial_capital=1_000_000,
        )
        assert cfg.signal == 252
        assert cfg.costs == 8.0

    def test_flat_signal_cfg_accessor(self) -> None:
        from lab.core.config import ExperimentConfig

        cfg = ExperimentConfig(
            exp="test",
            universe=("A",),
            start_date="2020-01-01",
            end_date="2020-12-31",
            rebalance="daily",
            signal=60,
            costs=5.0,
            initial_capital=1_000_000,
        )
        sc = cfg.signal_cfg
        assert isinstance(sc, dict)
        assert sc["lookback"] == 60
        assert sc["name"] == "cs_mom"
        assert sc["long_only"] is True

    def test_flat_costs_bps_accessor(self) -> None:
        from lab.core.config import ExperimentConfig

        cfg = ExperimentConfig(
            exp="test",
            universe=("A",),
            start_date="2020-01-01",
            end_date="2020-12-31",
            rebalance="daily",
            signal=60,
            costs=8.0,
            initial_capital=1_000_000,
        )
        assert cfg.costs_bps == 8.0

    def test_flat_regime_cfg_defaults(self) -> None:
        from lab.core.config import ExperimentConfig

        cfg = ExperimentConfig(
            exp="test",
            universe=("A",),
            start_date="2020-01-01",
            end_date="2020-12-31",
            rebalance="daily",
            signal=60,
            costs=5.0,
            initial_capital=1_000_000,
        )
        rc = cfg.regime_cfg
        assert rc["fast"] == 20
        assert rc["slow"] == 60
        assert rc["risk_off_scale"] == 0.3


class TestConfigNestedFormat:
    """Nested format: signal=dict, costs=dict, regime=dict."""

    def test_nested_signal_dict(self) -> None:
        from lab.core.config import ExperimentConfig

        cfg = ExperimentConfig(
            exp="test",
            universe=("SPY", "TLT"),
            start_date="2016-01-01",
            end_date="2024-12-31",
            rebalance="weekly",
            signal={"name": "cs_mom", "lookback": 60, "long_only": True},
            costs={"bps": 5},
            initial_capital=1_000_000,
        )
        assert cfg.signal_cfg["lookback"] == 60
        assert cfg.signal_cfg["name"] == "cs_mom"
        assert cfg.signal_cfg["long_only"] is True

    def test_nested_costs_dict(self) -> None:
        from lab.core.config import ExperimentConfig

        cfg = ExperimentConfig(
            exp="test",
            universe=("SPY",),
            start_date="2016-01-01",
            end_date="2024-12-31",
            rebalance="weekly",
            signal={"name": "cs_mom", "lookback": 60},
            costs={"bps": 5},
            initial_capital=1_000_000,
        )
        assert cfg.costs_bps == 5.0

    def test_nested_regime_dict(self) -> None:
        from lab.core.config import ExperimentConfig

        cfg = ExperimentConfig(
            exp="test",
            universe=("SPY",),
            start_date="2016-01-01",
            end_date="2024-12-31",
            rebalance="weekly",
            signal=60,
            costs=5.0,
            initial_capital=1_000_000,
            regime={"name": "ma_crossover", "fast": 10, "slow": 50, "risk_off_scale": 0.2},
        )
        assert cfg.regime_cfg["fast"] == 10
        assert cfg.regime_cfg["slow"] == 50
        assert cfg.regime_cfg["risk_off_scale"] == 0.2


class TestConfigValidation:
    def test_signal_dict_passes_validation(self, tmp_path: Path) -> None:
        import yaml

        from lab.core.config import load_config

        cfg_dict = {
            "exp": "test",
            "universe": ["A", "B"],
            "start_date": "2020-01-01",
            "end_date": "2020-12-31",
            "rebalance": "monthly",
            "signal": {"name": "cs_mom", "lookback": 60},
            "costs": {"bps": 5},
            "initial_capital": 1_000_000,
        }
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml.dump(cfg_dict))
        cfg = load_config(p)
        assert cfg.signal_cfg["lookback"] == 60
        assert cfg.costs_bps == 5.0

    def test_signal_string_fails_validation(self, tmp_path: Path) -> None:
        import yaml

        from lab.core.config import ConfigValidationError, load_config

        cfg_dict = {
            "exp": "test",
            "universe": ["A"],
            "start_date": "2020-01-01",
            "end_date": "2020-12-31",
            "rebalance": "monthly",
            "signal": "bad_string",
            "costs": 5.0,
            "initial_capital": 1_000_000,
        }
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml.dump(cfg_dict))
        with pytest.raises(ConfigValidationError, match="signal"):
            load_config(p)

    def test_signal_boolean_fails_validation(self, tmp_path: Path) -> None:
        import yaml

        from lab.core.config import ConfigValidationError, load_config

        cfg_dict = {
            "exp": "test",
            "universe": ["A"],
            "start_date": "2020-01-01",
            "end_date": "2020-12-31",
            "rebalance": "monthly",
            "signal": True,
            "costs": 5.0,
            "initial_capital": 1_000_000,
        }
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml.dump(cfg_dict))
        with pytest.raises(ConfigValidationError, match="boolean"):
            load_config(p)

    def test_costs_boolean_fails_validation(self, tmp_path: Path) -> None:
        import yaml

        from lab.core.config import ConfigValidationError, load_config

        cfg_dict = {
            "exp": "test",
            "universe": ["A"],
            "start_date": "2020-01-01",
            "end_date": "2020-12-31",
            "rebalance": "monthly",
            "signal": 20,
            "costs": False,
            "initial_capital": 1_000_000,
        }
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml.dump(cfg_dict))
        with pytest.raises(ConfigValidationError, match="boolean"):
            load_config(p)

    def test_initial_capital_boolean_fails_validation(self, tmp_path: Path) -> None:
        import yaml

        from lab.core.config import ConfigValidationError, load_config

        cfg_dict = {
            "exp": "test",
            "universe": ["A"],
            "start_date": "2020-01-01",
            "end_date": "2020-12-31",
            "rebalance": "monthly",
            "signal": 20,
            "costs": 5.0,
            "initial_capital": True,
        }
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml.dump(cfg_dict))
        with pytest.raises(ConfigValidationError, match="initial_capital"):
            load_config(p)

    def test_start_date_after_end_date_fails_validation(self, tmp_path: Path) -> None:
        import yaml

        from lab.core.config import ConfigValidationError, load_config

        cfg_dict = {
            "exp": "test",
            "universe": ["A"],
            "start_date": "2021-01-01",
            "end_date": "2020-12-31",
            "rebalance": "monthly",
            "signal": 20,
            "costs": 5.0,
            "initial_capital": 1_000_000,
        }
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml.dump(cfg_dict))
        with pytest.raises(ConfigValidationError, match="start_date"):
            load_config(p)

    def test_duplicate_universe_tickers_fail_validation(self, tmp_path: Path) -> None:
        import yaml

        from lab.core.config import ConfigValidationError, load_config

        cfg_dict = {
            "exp": "test",
            "universe": ["A", "A"],
            "start_date": "2020-01-01",
            "end_date": "2020-12-31",
            "rebalance": "monthly",
            "signal": 20,
            "costs": 5.0,
            "initial_capital": 1_000_000,
        }
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml.dump(cfg_dict))
        with pytest.raises(ConfigValidationError, match="duplicate"):
            load_config(p)

    def test_regime_boolean_fields_fail_validation(self, tmp_path: Path) -> None:
        import yaml

        from lab.core.config import ConfigValidationError, load_config

        cfg_dict = {
            "exp": "test",
            "universe": ["A"],
            "start_date": "2020-01-01",
            "end_date": "2020-12-31",
            "rebalance": "monthly",
            "signal": 20,
            "costs": 5.0,
            "initial_capital": 1_000_000,
            "regime": {"fast": True, "slow": 60, "risk_off_scale": 0.3},
        }
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml.dump(cfg_dict))
        with pytest.raises(ConfigValidationError, match=r"regime\.fast"):
            load_config(p)


class TestMacroAllocatorConfigValidation:
    def test_valid_macro_config_passes(self) -> None:
        from lab.core.config import validate_macro_allocator_config

        raw = {
            "exp": "macro_allocator_ls",
            "strategy": "macro.allocator_ls",
            "universe_config": "experiments/macro/configs/universe.yaml",
            "dates": {"start": "2016-01-01", "end": "2024-12-31"},
            "rebalance": {"frequency": "W-FRI"},
            "signal": {
                "method": "ma_cross",
                "fast": 20,
                "slow": 120,
                "lookback_days": 252,
                "vol_scale_lookback": 63,
            },
            "regime": {
                "enabled": True,
                "lag_days": 30,
                "lookback_days": 63,
                "risk_off_bucket_multipliers": {"equities": 0.6},
            },
            "risk": {"vol_target_annual": 0.10, "vol_lookback_days": 63},
            "costs": {
                "use_meta_costs": True,
                "financing_bps_annual": 25.0,
                "short_borrow_bps_annual": 40.0,
                "regime_multipliers": {"risk_on": 1.0, "risk_off": 1.2},
                "impact": {
                    "enabled": True,
                    "turnover_ref": 0.10,
                    "coefficient_bps": 1.5,
                    "exponent": 0.5,
                },
                "capacity": {
                    "enabled": True,
                    "adv_column": "adv_usd_mn",
                    "notional_usd": 10_000_000.0,
                    "max_adv_participation": 0.2,
                    "impact_bps_at_100pct_adv": 8.0,
                    "breach_action": "warn",
                },
                "stress_multipliers": [1, 2, 4],
            },
            "evaluation": {
                "calendar": "OBSERVED_WEEKDAY",
                "folds": {"train_days": 1260, "test_days": 252, "step_days": 252, "embargo_days": 5},
            },
        }
        validate_macro_allocator_config(raw)

    def test_unknown_macro_field_fails(self) -> None:
        from lab.core.config import ConfigValidationError, validate_macro_allocator_config

        raw = {
            "exp": "macro_allocator_ls",
            "universe_config": "experiments/macro/configs/universe.yaml",
            "dates": {"start": "2016-01-01", "end": "2024-12-31"},
            "rebalance": {"frequency": "W-FRI"},
            "signal": {"method": "ma_cross", "fast": 20, "slow": 120, "lookback_days": 252},
            "evaluation": {"folds": {"train_days": 1260, "test_days": 252, "step_days": 252}},
            "unexpected_field": 123,
        }
        with pytest.raises(ConfigValidationError, match="unknown"):
            validate_macro_allocator_config(raw)

    def test_valid_macro_ensemble_signal_config_passes(self) -> None:
        from lab.core.config import validate_macro_allocator_config

        raw = {
            "exp": "macro_allocator_ls",
            "strategy": "macro.allocator_ls",
            "universe_config": "experiments/macro/configs/universe.yaml",
            "dates": {"start": "2016-01-01", "end": "2024-12-31"},
            "rebalance": {"frequency": "W-FRI"},
            "signal": {
                "name": "ensemble",
                "weights": {"trend": 1.0},
                "signals": {
                    "trend": {
                        "name": "ts_trend",
                        "method": "ma_cross",
                        "fast": 20,
                        "slow": 120,
                        "lookback_days": 252,
                    }
                },
                "risk_parity": {"enabled": True, "lookback_days": 63},
                "vol_scale_lookback": 63,
            },
            "evaluation": {
                "calendar": "OBSERVED_WEEKDAY",
                "folds": {"train_days": 1260, "test_days": 252, "step_days": 252, "embargo_days": 5},
            },
        }
        validate_macro_allocator_config(raw)

    def test_macro_numeric_boolean_fields_fail(self) -> None:
        from lab.core.config import ConfigValidationError, validate_macro_allocator_config

        raw = {
            "exp": "macro_allocator_ls",
            "universe_config": "experiments/macro/configs/universe.yaml",
            "dates": {"start": "2016-01-01", "end": "2024-12-31"},
            "rebalance": {"frequency": "W-FRI"},
            "signal": {
                "method": "ma_cross",
                "fast": True,
                "slow": 120,
                "lookback_days": 252,
                "vol_scale_lookback": 63,
            },
            "evaluation": {
                "folds": {"train_days": 1260, "test_days": 252, "step_days": 252, "embargo_days": 5}
            },
        }
        with pytest.raises(ConfigValidationError, match="boolean"):
            validate_macro_allocator_config(raw)

    def test_macro_negative_financing_fails(self) -> None:
        from lab.core.config import ConfigValidationError, validate_macro_allocator_config

        raw = {
            "exp": "macro_allocator_ls",
            "universe_config": "experiments/macro/configs/universe.yaml",
            "dates": {"start": "2016-01-01", "end": "2024-12-31"},
            "rebalance": {"frequency": "W-FRI"},
            "signal": {"method": "ma_cross", "fast": 20, "slow": 120, "lookback_days": 252},
            "costs": {"financing_bps_annual": -1.0},
            "evaluation": {
                "folds": {"train_days": 1260, "test_days": 252, "step_days": 252, "embargo_days": 5}
            },
        }
        with pytest.raises(ConfigValidationError, match="financing"):
            validate_macro_allocator_config(raw)

    def test_macro_invalid_capacity_breach_action_fails(self) -> None:
        from lab.core.config import ConfigValidationError, validate_macro_allocator_config

        raw = {
            "exp": "macro_allocator_ls",
            "universe_config": "experiments/macro/configs/universe.yaml",
            "dates": {"start": "2016-01-01", "end": "2024-12-31"},
            "rebalance": {"frequency": "W-FRI"},
            "signal": {"method": "ma_cross", "fast": 20, "slow": 120, "lookback_days": 252},
            "costs": {
                "capacity": {
                    "enabled": True,
                    "notional_usd": 5_000_000.0,
                    "max_adv_participation": 0.2,
                    "impact_bps_at_100pct_adv": 5.0,
                    "adv_column": "adv_usd_mn",
                    "breach_action": "stop",
                }
            },
            "evaluation": {
                "folds": {"train_days": 1260, "test_days": 252, "step_days": 252, "embargo_days": 5}
            },
        }
        with pytest.raises(ConfigValidationError, match="breach_action"):
            validate_macro_allocator_config(raw)


# ══════════════════════════════════════════════════════════════════════════════
# Data loader — load_prices_or_make_toy
# ══════════════════════════════════════════════════════════════════════════════


class TestLoadPricesOrMakeToy:
    def _cfg(self, **kw):
        from lab.core.config import ExperimentConfig

        defaults = dict(
            exp="test",
            universe=("SPY", "TLT"),
            start_date="2020-01-01",
            end_date="2020-12-31",
            rebalance="weekly",
            signal=60,
            costs=5.0,
            initial_capital=1_000_000,
        )
        defaults.update(kw)
        return ExperimentConfig(**defaults)

    def test_fallback_to_toy_when_no_parquet(self, tmp_path: Path, monkeypatch) -> None:
        """Without prices.parquet, should generate toy GBM data."""
        from lab.data.loader import load_prices_or_make_toy

        monkeypatch.setenv("LAB_DATA_ROOT", str(tmp_path))
        cfg = self._cfg()
        prices = load_prices_or_make_toy(cfg)
        assert isinstance(prices, pd.DataFrame)
        assert list(prices.columns) == ["SPY", "TLT"]
        assert len(prices) > 200  # ~252 bdays in 2020

    def test_loads_from_parquet_when_present(self, tmp_path: Path, monkeypatch) -> None:
        """When prices.parquet exists, load and filter it."""
        from lab.data.loader import load_prices_or_make_toy

        monkeypatch.setenv("LAB_DATA_ROOT", str(tmp_path))

        # Create a synthetic parquet with extra tickers
        dates = pd.bdate_range("2019-01-01", "2021-12-31")
        rng = np.random.default_rng(0)
        df = pd.DataFrame(
            rng.uniform(90, 110, size=(len(dates), 3)),
            index=dates,
            columns=["SPY", "TLT", "QQQ"],
        )
        df.to_parquet(tmp_path / "prices.parquet")

        cfg = self._cfg()
        prices = load_prices_or_make_toy(cfg)
        # Should only have SPY and TLT (from config.universe), not QQQ
        assert set(prices.columns) == {"SPY", "TLT"}
        # Should be filtered to 2020 only
        assert prices.index.min().year == 2020
        assert prices.index.max().year == 2020

    def test_missing_ticker_falls_back_gracefully(self, tmp_path: Path, monkeypatch) -> None:
        """If parquet has only some tickers, warn and use available ones."""
        from lab.data.loader import load_prices_or_make_toy

        monkeypatch.setenv("LAB_DATA_ROOT", str(tmp_path))

        dates = pd.bdate_range("2020-01-01", "2020-12-31")
        rng = np.random.default_rng(0)
        df = pd.DataFrame(
            rng.uniform(90, 110, size=(len(dates), 1)),
            index=dates,
            columns=["SPY"],
        )
        df.to_parquet(tmp_path / "prices.parquet")

        # Config wants SPY and TLT, but parquet only has SPY
        cfg = self._cfg()
        prices = load_prices_or_make_toy(cfg)
        assert list(prices.columns) == ["SPY"]

    def test_no_matching_tickers_falls_back_to_toy(self, tmp_path: Path, monkeypatch) -> None:
        """If parquet has zero matching tickers, fallback to toy data."""
        from lab.data.loader import load_prices_or_make_toy

        monkeypatch.setenv("LAB_DATA_ROOT", str(tmp_path))

        dates = pd.bdate_range("2020-01-01", "2020-12-31")
        rng = np.random.default_rng(0)
        df = pd.DataFrame(
            rng.uniform(90, 110, size=(len(dates), 1)),
            index=dates,
            columns=["QQQ"],
        )
        df.to_parquet(tmp_path / "prices.parquet")

        cfg = self._cfg()
        prices = load_prices_or_make_toy(cfg)
        # Should have fallen back to toy — has both config tickers
        assert set(prices.columns) == {"SPY", "TLT"}


# ══════════════════════════════════════════════════════════════════════════════
# Backtest engine — costs_bps accessor
# ══════════════════════════════════════════════════════════════════════════════


class TestCostsBpsInEngine:
    def test_nested_costs_flow_through_backtest(self) -> None:
        """Engine should use config.costs_bps for cost application."""
        from lab.backtest.daily_engine import run_daily_backtest
        from lab.core.config import ExperimentConfig

        cfg = ExperimentConfig(
            exp="test",
            universe=("A", "B"),
            start_date="2020-01-01",
            end_date="2020-12-31",
            rebalance="monthly",
            signal={"name": "cs_mom", "lookback": 20},
            costs={"bps": 10},
            initial_capital=1_000_000,
        )
        rng = np.random.default_rng(42)
        dates = pd.bdate_range("2020-01-02", "2020-12-31")
        prices = pd.DataFrame(
            100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, (len(dates), 2)), axis=0)),
            index=dates,
            columns=["A", "B"],
        )

        def _eq(config, p):
            return pd.Series(0.5, index=p.columns)

        result = run_daily_backtest(cfg, prices, _eq)
        # If costs flowed through, net returns < gross returns
        assert result.returns.sum() < result.gross_returns.sum()


# ══════════════════════════════════════════════════════════════════════════════
# Baseline YAML loads correctly with nested format
# ══════════════════════════════════════════════════════════════════════════════


class TestBaselineYAML:
    def test_load_baseline_yaml(self) -> None:
        """The updated baseline.yaml should load without error."""
        from lab.core.config import load_config
        from lab.core.paths import lab_root

        cfg_path = lab_root() / "experiments" / "macro_equities" / "configs" / "baseline.yaml"
        if not cfg_path.exists():
            pytest.skip("baseline.yaml not found")

        cfg = load_config(cfg_path)
        assert cfg.exp == "macro_regimes"
        assert set(cfg.universe) == {"SPY", "EFA", "EEM", "TLT"}
        assert cfg.rebalance == "weekly"
        assert cfg.signal_cfg["lookback"] == 60
        assert cfg.costs_bps == 5.0
        assert cfg.regime_cfg["fast"] == 20
        assert cfg.regime_cfg["slow"] == 60
        assert cfg.initial_capital == 1_000_000
