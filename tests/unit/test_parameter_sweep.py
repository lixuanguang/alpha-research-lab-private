"""Unit tests for apps.research.backtester.sweep."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import apps.research.backtester.result as result_mod
import apps.research.backtester.sweep as sweep_mod
import apps.research.backtester.vec_engine as vec_engine_mod
import apps.research.backtester.vec_strategy as vec_strategy_mod
import pandas as pd
import pyarrow as pa
import pytest

import alpha_core.portfolio.models as portfolio_models
from alpha_core.portfolio.sizing import EqualWeightSizer

_T0 = datetime(2024, 1, 1, tzinfo=UTC)
_ZERO = Decimal("0")


# ---------------------------------------------------------------------------
# ParameterGrid
# ---------------------------------------------------------------------------


class TestParameterGrid:
    def test_empty_params_yields_one_empty_dict(self) -> None:
        g = sweep_mod.ParameterGrid({})
        assert len(g) == 1
        combos = list(g)
        assert combos == [{}]

    def test_single_param_yields_correct_count(self) -> None:
        g = sweep_mod.ParameterGrid({"window": [5, 10, 20]})
        assert len(g) == 3

    def test_two_params_cartesian_product(self) -> None:
        g = sweep_mod.ParameterGrid({"a": [1, 2], "b": [10, 20]})
        assert len(g) == 4
        combos = list(g)
        # All 4 combinations must be present.
        assert {"a": 1, "b": 10} in combos
        assert {"a": 1, "b": 20} in combos
        assert {"a": 2, "b": 10} in combos
        assert {"a": 2, "b": 20} in combos

    def test_iteration_produces_dicts(self) -> None:
        g = sweep_mod.ParameterGrid({"x": [1, 2]})
        for combo in g:
            assert isinstance(combo, dict)
            assert "x" in combo

    def test_non_dict_raises(self) -> None:
        with pytest.raises(TypeError):
            sweep_mod.ParameterGrid([1, 2])  # type: ignore[arg-type]

    def test_non_list_values_raises(self) -> None:
        with pytest.raises(TypeError):
            sweep_mod.ParameterGrid({"a": (1, 2)})  # type: ignore[dict-item]

    def test_repr_contains_params(self) -> None:
        g = sweep_mod.ParameterGrid({"w": [5, 10]})
        assert "ParameterGrid" in repr(g)


# ---------------------------------------------------------------------------
# make_sweep_id
# ---------------------------------------------------------------------------


class TestMakeSweepId:
    def test_deterministic(self) -> None:
        cid1 = sweep_mod.make_sweep_id("strategy_a", {"w": [5, 10]})
        cid2 = sweep_mod.make_sweep_id("strategy_a", {"w": [5, 10]})
        assert cid1 == cid2

    def test_length_is_16(self) -> None:
        cid = sweep_mod.make_sweep_id("my_strat", {"p": [1]})
        assert len(cid) == 16

    def test_different_strategy_different_id(self) -> None:
        cid1 = sweep_mod.make_sweep_id("strat_a", {"w": [5]})
        cid2 = sweep_mod.make_sweep_id("strat_b", {"w": [5]})
        assert cid1 != cid2

    def test_different_grid_different_id(self) -> None:
        cid1 = sweep_mod.make_sweep_id("strat", {"w": [5]})
        cid2 = sweep_mod.make_sweep_id("strat", {"w": [10]})
        assert cid1 != cid2


# ---------------------------------------------------------------------------
# BacktestEvaluator
# ---------------------------------------------------------------------------


def _make_equity_curve(values: list[float]) -> list[tuple[datetime, Decimal]]:
    return [
        (datetime(2024, 1, i + 1, tzinfo=UTC), Decimal(str(v)))
        for i, v in enumerate(values)
    ]


class TestBacktestEvaluator:
    def _minimal_result(
        self,
        equity: list[float],
        initial_cash: float = 1000.0,
    ) -> result_mod.BacktestResult:
        """Build a minimal BacktestResult for evaluator tests."""
        portfolio = portfolio_models.PortfolioState(
            timestamp=_T0,
            cash=Decimal(str(equity[-1])),
            positions={},
            total_pnl=Decimal(str(equity[-1] - initial_cash)),
            total_fees=_ZERO,
            equity=Decimal(str(equity[-1])),
        )
        return result_mod.BacktestResult(
            backtest_id="test0001",
            config_snapshot={"initial_cash": initial_cash},
            strategy_name="test",
            trades=[],
            equity_curve=_make_equity_curve(equity),
            final_portfolio=portfolio,
            duration_seconds=0.0,
            event_count=0,
        )

    def test_total_return_zero_when_flat(self) -> None:
        result = self._minimal_result([1000.0, 1000.0, 1000.0])
        ev = sweep_mod.BacktestEvaluator()
        metrics = ev.evaluate(result)
        assert metrics["total_return"] == pytest.approx(0.0, abs=1e-9)

    def test_total_return_positive(self) -> None:
        result = self._minimal_result([1000.0, 1100.0])
        ev = sweep_mod.BacktestEvaluator()
        metrics = ev.evaluate(result)
        assert metrics["total_return"] == pytest.approx(0.1, rel=0.001)

    def test_sharpe_zero_when_constant_equity(self) -> None:
        result = self._minimal_result([1000.0, 1000.0, 1000.0, 1000.0])
        ev = sweep_mod.BacktestEvaluator()
        metrics = ev.evaluate(result)
        assert metrics["sharpe_ratio"] == 0.0

    def test_sharpe_zero_when_single_point(self) -> None:
        result = self._minimal_result([1000.0])
        metrics = sweep_mod.BacktestEvaluator().evaluate(result)
        assert metrics["sharpe_ratio"] == 0.0

    def test_max_drawdown_zero_when_monotonic(self) -> None:
        result = self._minimal_result([1000.0, 1100.0, 1200.0])
        metrics = sweep_mod.BacktestEvaluator().evaluate(result)
        assert metrics["max_drawdown"] == pytest.approx(0.0, abs=1e-9)

    def test_max_drawdown_negative_on_drawdown(self) -> None:
        result = self._minimal_result([1000.0, 1200.0, 900.0])
        metrics = sweep_mod.BacktestEvaluator().evaluate(result)
        # Drawdown from 1200 to 900 = -300/1200 = -0.25
        assert metrics["max_drawdown"] == pytest.approx(-0.25, rel=0.01)

    def test_trade_count_matches(self) -> None:
        result = self._minimal_result([1000.0, 1000.0])
        metrics = sweep_mod.BacktestEvaluator().evaluate(result)
        assert metrics["trade_count"] == 0.0

    def test_all_expected_keys_present(self) -> None:
        result = self._minimal_result([1000.0, 1050.0])
        metrics = sweep_mod.BacktestEvaluator().evaluate(result)
        for key in ("total_return", "sharpe_ratio", "max_drawdown", "trade_count"):
            assert key in metrics


# ---------------------------------------------------------------------------
# ParameterSweepRunner integration with mock engine
# ---------------------------------------------------------------------------


def _make_trades_table(n_rows: int = 5) -> pa.Table:
    """Minimal trades table for sweep tests."""
    rows = [(datetime(2024, 1, i + 1, 12, 0, tzinfo=UTC), "a", 0.5) for i in range(n_rows)]
    return pa.table(
        {
            "ts_event": pa.array([r[0] for r in rows], type=pa.timestamp("us", tz="UTC")),
            "instrument_id": pa.array([r[1] for r in rows], type=pa.string()),
            "price": pa.array([r[2] for r in rows], type=pa.float64()),
        }
    )


class _MockDataset:
    def __init__(self, table: pa.Table) -> None:
        self._table = table

    def trades(self) -> pa.Table:
        return self._table


class _ParametricStrategy(vec_strategy_mod.VecStrategy):
    """Strategy parameterized by threshold; ignores the param value for simplicity."""

    def __init__(self, params: dict[str, Any]) -> None:
        self._threshold = params.get("threshold", 0.5)

    @property
    def name(self) -> str:
        return "parametric"

    def generate_signals(
        self,
        features: pd.DataFrame,
        universe: list[str],
    ) -> pd.DataFrame:
        # Always go long all instruments.
        del features
        return pd.DataFrame({"instrument_id": universe, "signal": [1.0] * len(universe)})

    def size_positions(
        self,
        signals: pd.DataFrame,
        portfolio_value: Decimal,
        max_positions: int,
    ) -> pd.DataFrame:
        return EqualWeightSizer().size(signals, portfolio_value, max_positions)


class TestParameterSweepRunner:
    def _engine(self) -> vec_engine_mod.VecBacktestEngine:
        return vec_engine_mod.VecBacktestEngine(
            vec_engine_mod.VecBacktestConfig(
                dataset_id="test",
                initial_cash=Decimal("1000"),
                rebalance_frequency="1D",
            )
        )

    def test_sweep_runs_all_combinations(self) -> None:
        grid = sweep_mod.ParameterGrid({"threshold": [0.5, 1.0, 1.5]})
        dataset = _MockDataset(_make_trades_table())
        runner = sweep_mod.ParameterSweepRunner(
            engine=vec_engine_mod.VecBacktestEngine(
                vec_engine_mod.VecBacktestConfig(
                    dataset_id="t",
                    initial_cash=Decimal("1000"),
                )
            ),
            evaluator=sweep_mod.BacktestEvaluator(),
        )
        sweep = runner.run(
            lambda p: _ParametricStrategy(p),
            grid,
            dataset=dataset,
        )
        assert len(sweep.trials) == 3

    def test_best_params_in_sweep_result(self) -> None:
        grid = sweep_mod.ParameterGrid({"threshold": [0.5, 1.0]})
        dataset = _MockDataset(_make_trades_table())
        runner = sweep_mod.ParameterSweepRunner(
            engine=vec_engine_mod.VecBacktestEngine(
                vec_engine_mod.VecBacktestConfig(
                    dataset_id="t",
                    initial_cash=Decimal("1000"),
                )
            ),
            evaluator=sweep_mod.BacktestEvaluator(),
        )
        sweep = runner.run(lambda p: _ParametricStrategy(p), grid, dataset=dataset)
        assert isinstance(sweep.best_params, dict)
        assert "threshold" in sweep.best_params

    def test_empty_grid_runs_once(self) -> None:
        grid = sweep_mod.ParameterGrid({})
        dataset = _MockDataset(_make_trades_table())
        runner = sweep_mod.ParameterSweepRunner(
            engine=vec_engine_mod.VecBacktestEngine(
                vec_engine_mod.VecBacktestConfig(
                    dataset_id="t",
                    initial_cash=Decimal("1000"),
                )
            ),
            evaluator=sweep_mod.BacktestEvaluator(),
        )
        sweep = runner.run(lambda p: _ParametricStrategy(p), grid, dataset=dataset)
        assert len(sweep.trials) == 1

    def test_sweep_id_is_16_chars(self) -> None:
        grid = sweep_mod.ParameterGrid({"threshold": [0.5]})
        dataset = _MockDataset(_make_trades_table())
        runner = sweep_mod.ParameterSweepRunner(
            engine=vec_engine_mod.VecBacktestEngine(
                vec_engine_mod.VecBacktestConfig(
                    dataset_id="t",
                    initial_cash=Decimal("1000"),
                )
            ),
            evaluator=sweep_mod.BacktestEvaluator(),
        )
        sweep = runner.run(lambda p: _ParametricStrategy(p), grid, dataset=dataset)
        assert len(sweep.sweep_id) == 16

    def test_invalid_n_workers_raises(self) -> None:
        with pytest.raises(ValueError):
            sweep_mod.ParameterSweepRunner(
                engine=None,
                evaluator=sweep_mod.BacktestEvaluator(),
                n_workers=0,
            )

    def test_primary_metric_propagated(self) -> None:
        grid = sweep_mod.ParameterGrid({"threshold": [0.5]})
        dataset = _MockDataset(_make_trades_table())
        runner = sweep_mod.ParameterSweepRunner(
            engine=vec_engine_mod.VecBacktestEngine(
                vec_engine_mod.VecBacktestConfig(
                    dataset_id="t",
                    initial_cash=Decimal("1000"),
                )
            ),
            evaluator=sweep_mod.BacktestEvaluator(),
        )
        sweep = runner.run(
            lambda p: _ParametricStrategy(p),
            grid,
            dataset=dataset,
            primary_metric="total_return",
        )
        assert sweep.primary_metric == "total_return"
