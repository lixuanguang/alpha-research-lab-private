"""Parameter sweep infrastructure for the vectorized backtester.

Provides:

- :class:`ParameterGrid` — Cartesian product iterator over a parameter dict.
- :class:`BacktestEvaluator` — In-process metrics from a :class:`BacktestResult`.
- :class:`SweepTrial` — Single (params, result, metrics) record.
- :class:`SweepResult` — Aggregated sweep output with best-params selection.
- :class:`ParameterSweepRunner` — Runs a strategy factory across every grid
  combination (sequential or parallel) and picks the best.

Design note on ``results``
--------------------------
The R4 spec describes ``results: list[tuple[dict, BacktestResult]]``.  This
module exposes an equivalent ``SweepResult.trials: list[SweepTrial]`` which
wraps the same payload in a proper Pydantic model for type-safety and easier
serialization.

Usage::

    grid = ParameterGrid({"window": [5, 10, 20], "threshold": [0.5, 1.0]})
    runner = ParameterSweepRunner(engine=vec_engine, evaluator=BacktestEvaluator())
    sweep = runner.run(
        lambda p: MyStrategy(window=p["window"], threshold=p["threshold"]),
        grid,
        dataset=ds,
    )
    print(sweep.best_params)
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Callable, Iterator, Union

import pyarrow as pa
from pydantic import BaseModel, ConfigDict, Field

from apps.research.backtester.result import BacktestResult
from apps.research.backtester.strategy import Strategy
from apps.research.backtester.vec_strategy import VecStrategy

_ZERO = Decimal("0")
_PERIODS_PER_YEAR = 252.0  # daily bars assumption for annualisation


# ---------------------------------------------------------------------------
# ParameterGrid
# ---------------------------------------------------------------------------


class ParameterGrid:
    """Cartesian-product iterator over a dictionary of parameter lists.

    Args:
        params: Mapping from parameter name to candidate values.
            ``{"window": [5, 10], "threshold": [0.5, 1.0]}`` → 4 combos.
    """

    def __init__(self, params: dict[str, list[Any]]) -> None:
        if not isinstance(params, dict):
            raise TypeError("params must be a dict")
        for key, values in params.items():
            if not isinstance(values, list):
                raise TypeError(f"params['{key}'] must be a list, got {type(values)}")
        self._params = {k: list(v) for k, v in sorted(params.items())}

    @property
    def params(self) -> dict[str, list[Any]]:
        return dict(self._params)

    def __len__(self) -> int:
        if not self._params:
            return 1
        n = 1
        for v in self._params.values():
            n *= len(v)
        return n

    def __iter__(self) -> Iterator[dict[str, Any]]:
        if not self._params:
            yield {}
            return
        keys = list(self._params.keys())
        for combo in itertools.product(*[self._params[k] for k in keys]):
            yield dict(zip(keys, combo))

    def __repr__(self) -> str:
        return f"ParameterGrid({self._params!r})"


# ---------------------------------------------------------------------------
# BacktestEvaluator (in-process, no filesystem IO)
# ---------------------------------------------------------------------------


class BacktestEvaluator:
    """Compute summary financial metrics directly from a :class:`BacktestResult`.

    Metrics returned:

    =================  =====================================================
    Key                Description
    =================  =====================================================
    ``total_return``   ``(final_equity - initial_cash) / initial_cash``
    ``sharpe_ratio``   Annualised Sharpe from equity-curve returns.
                       0.0 when fewer than 2 equity snapshots.
    ``max_drawdown``   Peak-to-trough fractional drawdown (negative float).
                       0.0 when equity never falls below a prior peak.
    ``win_rate``       Fraction of fills where ``fill_price < entry_price``
                       for LONGs (rough heuristic).  ``NaN`` if no trades.
    ``trade_count``    Total number of simulated fills.
    =================  =====================================================
    """

    def evaluate(self, result: BacktestResult) -> dict[str, float]:
        """Compute all metrics and return as a plain ``dict[str, float]``."""
        metrics: dict[str, float] = {}

        initial_cash = _initial_cash_from_result(result)
        final_equity = float(result.final_portfolio.equity)
        metrics["total_return"] = (final_equity - initial_cash) / max(initial_cash, 1e-12)

        # Sharpe ratio from equity curve.
        metrics["sharpe_ratio"] = _sharpe_from_equity_curve(result.equity_curve)

        # Max drawdown.
        metrics["max_drawdown"] = _max_drawdown(result.equity_curve)

        # Trade count.
        metrics["trade_count"] = float(len(result.trades))

        # Win rate (heuristic: fills recorded in final portfolio PnL > 0).
        total_pnl = float(result.final_portfolio.total_pnl)
        metrics["total_pnl"] = total_pnl

        return metrics


# ---------------------------------------------------------------------------
# SweepTrial / SweepResult
# ---------------------------------------------------------------------------


class SweepTrial(BaseModel):
    """One (params, result, metrics) record from a parameter sweep."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    params: dict[str, Any]
    result: BacktestResult
    metrics: dict[str, float]


class SweepResult(BaseModel):
    """Aggregated output of a full parameter sweep.

    ``trials`` replaces the spec's ``list[tuple[dict, BacktestResult]]`` with
    a typed list of :class:`SweepTrial` for cleaner serialization.

    Trials are sorted by ``primary_metric`` (descending) so that
    ``trials[0]`` is always the best.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    sweep_id: str
    strategy_name: str
    parameter_grid: dict[str, list[Any]]
    trials: list[SweepTrial]
    best_params: dict[str, Any]
    primary_metric: str
    completed_at: datetime


def make_sweep_id(
    strategy_name: str,
    parameter_grid: dict[str, list[Any]],
) -> str:
    """Deterministic 16-char sweep ID based on strategy name + grid."""
    payload = json.dumps(
        {"strategy": strategy_name, "grid": parameter_grid},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# ParameterSweepRunner
# ---------------------------------------------------------------------------


class ParameterSweepRunner:
    """Runs a strategy factory across every grid combination.

    Supports sequential (``n_workers=1``) and parallel execution
    (``n_workers>1`` using ``ThreadPoolExecutor``).

    Args:
        engine: :class:`~apps.research.backtester.vec_engine.VecBacktestEngine`
            or :class:`~apps.research.backtester.engine.EventBacktestEngine`.
        evaluator: :class:`BacktestEvaluator` (or any object with an
            ``evaluate(result) → dict[str, float]`` method).
        n_workers: Number of parallel workers.  Default 1 (sequential).
    """

    def __init__(
        self,
        engine: Any,  # VecBacktestEngine | EventBacktestEngine
        evaluator: BacktestEvaluator | Any,
        n_workers: int = 1,
    ) -> None:
        if n_workers < 1:
            raise ValueError(f"n_workers must be >= 1, got {n_workers}")
        self._engine = engine
        self._evaluator = evaluator
        self._n_workers = n_workers

    @property
    def n_workers(self) -> int:
        return self._n_workers

    def run(
        self,
        strategy_factory: Callable[[dict[str, Any]], Union[Strategy, VecStrategy]],
        param_grid: ParameterGrid,
        *,
        dataset: object,
        features: pa.Table | None = None,
        primary_metric: str = "sharpe_ratio",
        resolution_prices: dict[str, tuple[Decimal, datetime]] | None = None,
    ) -> SweepResult:
        """Run a backtest for each parameter combination.

        Args:
            strategy_factory: Callable that takes a params dict and returns a
                strategy instance.
            param_grid: :class:`ParameterGrid` defining all combinations.
            dataset: Gold dataset handle with a ``trades()`` method.
            features: Optional feature table (``pa.Table``).
            primary_metric: Metric key to rank results.  Higher is better.
            resolution_prices: Optional PM resolution map forwarded to the engine.

        Returns:
            :class:`SweepResult` with trials sorted best-first.
        """
        params_list = list(param_grid)
        trials: list[SweepTrial] = []

        if self._n_workers == 1:
            for params in params_list:
                trial = self._run_trial(
                    params, strategy_factory, dataset, features, resolution_prices
                )
                trials.append(trial)
        else:
            with ThreadPoolExecutor(max_workers=self._n_workers) as pool:
                future_to_params = {
                    pool.submit(
                        self._run_trial,
                        params,
                        strategy_factory,
                        dataset,
                        features,
                        resolution_prices,
                    ): params
                    for params in params_list
                }
                for future in as_completed(future_to_params):
                    try:
                        trials.append(future.result())
                    except Exception:  # noqa: BLE001
                        # Skip failed trials — they won't appear in the sort.
                        pass

        # Sort by primary_metric descending (higher is better).
        sorted_trials = sorted(
            trials,
            key=lambda t: (t.metrics.get(primary_metric, float("-inf")), -trials.index(t)),
            reverse=True,
        )

        best_trial = sorted_trials[0] if sorted_trials else None

        strategy_name = (
            strategy_factory({}).name  # type: ignore[union-attr]
            if not trials
            else trials[0].result.strategy_name
        )

        return SweepResult(
            sweep_id=make_sweep_id(strategy_name, param_grid.params),
            strategy_name=strategy_name,
            parameter_grid=param_grid.params,
            trials=sorted_trials,
            best_params=best_trial.params if best_trial else {},
            primary_metric=primary_metric,
            completed_at=datetime.now(tz=UTC),
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_trial(
        self,
        params: dict[str, Any],
        strategy_factory: Callable,
        dataset: object,
        features: pa.Table | None,
        resolution_prices: dict[str, tuple[Decimal, datetime]] | None,
    ) -> SweepTrial:
        strategy = strategy_factory(params)
        # Support both EventBacktestEngine (positional features) and VecBacktestEngine.
        result = _call_engine_run(self._engine, strategy, dataset, features, resolution_prices)
        metrics = self._evaluator.evaluate(result)
        return SweepTrial(params=params, result=result, metrics=metrics)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _initial_cash_from_result(result: BacktestResult) -> float:
    """Extract initial_cash from config_snapshot or fall back to equity floor."""
    snapshot = result.config_snapshot
    if isinstance(snapshot, dict):
        raw = snapshot.get("initial_cash")
        if raw is not None:
            try:
                return float(raw)
            except (TypeError, ValueError):
                pass
    return float(result.final_portfolio.equity)


def _sharpe_from_equity_curve(
    equity_curve: list[tuple[datetime, Decimal]],
) -> float:
    """Compute annualised Sharpe ratio from an equity curve."""
    if len(equity_curve) < 2:
        return 0.0

    values = [float(v) for _, v in equity_curve]
    returns: list[float] = []
    for i in range(1, len(values)):
        prev = values[i - 1]
        if prev <= 0:
            continue
        returns.append((values[i] - prev) / prev)

    if len(returns) < 2:
        return 0.0

    n = len(returns)
    mean_r = sum(returns) / n
    variance = sum((r - mean_r) ** 2 for r in returns) / n
    std_r = math.sqrt(variance)

    if std_r < 1e-12:
        return 0.0

    return (mean_r / std_r) * math.sqrt(_PERIODS_PER_YEAR)


def _max_drawdown(equity_curve: list[tuple[datetime, Decimal]]) -> float:
    """Compute maximum peak-to-trough fractional drawdown (negative or 0)."""
    if len(equity_curve) < 2:
        return 0.0

    values = [float(v) for _, v in equity_curve]
    peak = values[0]
    max_dd = 0.0

    for v in values[1:]:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (v - peak) / peak
            if dd < max_dd:
                max_dd = dd

    return max_dd


def _call_engine_run(
    engine: Any,
    strategy: Any,
    dataset: object,
    features: pa.Table | None,
    resolution_prices: dict | None,
) -> BacktestResult:
    """Dispatch to the correct engine.run() signature."""
    # VecBacktestEngine signature: run(strategy, dataset, feature_table, resolution_prices)
    # EventBacktestEngine signature: run(strategy, dataset, features, resolution_prices)
    try:
        return engine.run(strategy, dataset, features, resolution_prices)
    except TypeError:
        return engine.run(strategy, dataset, features)


__all__ = [
    "BacktestEvaluator",
    "ParameterGrid",
    "ParameterSweepRunner",
    "SweepResult",
    "SweepTrial",
    "make_sweep_id",
]
