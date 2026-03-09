"""Performance targets for the research plane section-6 budget table.

These tests are marked ``perf`` and are skipped unless pytest is run with
``--run-perf``. They encode the main runtime budgets as executable contracts.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest
from apps.research.backtester.engine import EventBacktestConfig, EventBacktestEngine
from apps.research.backtester.strategy import Strategy, StrategyState
from apps.research.backtester.sweep import (
    BacktestEvaluator as SweepEvaluator,
)
from apps.research.backtester.sweep import (
    ParameterGrid,
    ParameterSweepRunner,
)
from apps.research.backtester.vec_engine import VecBacktestConfig, VecBacktestEngine
from apps.research.backtester.vec_strategy import VecStrategy
from apps.research.commands.report import _build_report
from apps.research.reporting.writer import ReportWriter

import alpha_core.features.base as feature_base
import alpha_core.features.pm_specific as pm_features
import alpha_core.features.primitives as primitives
import alpha_core.instruments.master as master_mod
import alpha_core.instruments.models as instrument_models
import alpha_core.quality.gap_detector as gap_mod
import alpha_core.quality.partition_validator as pv_mod
import alpha_core.research.dataset as dataset_mod
import alpha_core.research.dataset_builder as dataset_builder_mod
import alpha_core.research.evaluate_runner as evaluate_runner_mod
import alpha_core.research.universe as universe_mod
import alpha_core.storage.parquet_reader as reader_mod
from alpha_core.evaluation.evaluator import BacktestEvaluator
from alpha_core.execution.models import BacktestOrderIntent
from alpha_core.features.registry import FeatureRegistry
from alpha_core.portfolio.models import Side
from alpha_core.portfolio.sizing import EqualWeightSizer

pytestmark = pytest.mark.perf

_BASE = datetime(2026, 1, 1, tzinfo=UTC)
_DATASET_BUILD_TARGET_SECONDS = 5.0
_UNIVERSE_SNAPSHOT_TARGET_MS = 100.0
_FEATURE_COMPUTE_TARGET_SECONDS = 2.0
_TOPOLOGICAL_SORT_TARGET_MS = 10.0
_EVENT_ENGINE_TARGET_SECONDS = 5.0
_VEC_ENGINE_TARGET_SECONDS = 3.0
_PARAMETER_SWEEP_TARGET_SECONDS = 60.0
_REPORT_GENERATION_TARGET_SECONDS = 1.0


def _make_market(venue: str, market_id: str) -> instrument_models.MarketSpec:
    return instrument_models.MarketSpec(
        market_id=market_id,
        venue=venue,
        title=f"{venue}/{market_id}",
        outcomes=[
            instrument_models.OutcomeSpec(
                outcome_id="yes",
                label="YES",
                canonical_id=f"{venue}:{market_id}:yes",
            ),
            instrument_models.OutcomeSpec(
                outcome_id="no",
                label="NO",
                canonical_id=f"{venue}:{market_id}:no",
            ),
        ],
        first_seen=_BASE - timedelta(days=1),
        last_updated=_BASE,
    )


def _dataset_build_trade_table(n_events: int = 10_000) -> pa.Table:
    timestamps = [_BASE + timedelta(seconds=index) for index in range(n_events)]
    return pa.table(
        {
            "event_id": [f"e{index}" for index in range(n_events)],
            "instrument_id": [
                "p:m1:yes" if index % 2 == 0 else "p:m1:no" for index in range(n_events)
            ],
            "venue_id": ["p"] * n_events,
            "event_type": ["trade"] * n_events,
            "ts_event": pa.array(timestamps, type=pa.timestamp("us", tz="UTC")),
            "ts_record": pa.array(timestamps, type=pa.timestamp("us", tz="UTC")),
            "price": pa.array([0.5] * n_events, type=pa.float64()),
            "size": pa.array([100.0] * n_events, type=pa.float64()),
        }
    )


def _cross_sectional_table(
    *,
    time_steps: int = 200,
    instrument_count: int = 50,
) -> pa.Table:
    """Return a 10K-row table when using the default 200 x 50 shape."""
    timestamps: list[datetime] = []
    instrument_ids: list[str] = []
    prices: list[float] = []
    sizes: list[float] = []

    for time_index in range(time_steps):
        ts_event = _BASE + timedelta(minutes=time_index)
        for instrument_index in range(instrument_count):
            venue = "v0" if instrument_index % 2 == 0 else "v1"
            market_id = f"m{instrument_index // 2}"
            timestamps.append(ts_event)
            instrument_ids.append(f"{venue}:{market_id}:yes")
            prices.append(0.20 + (instrument_index / 200.0) + ((time_index % 10) / 1000.0))
            sizes.append(100.0 + float(instrument_index % 5))

    return pa.table(
        {
            "instrument_id": instrument_ids,
            "price": pa.array(prices, type=pa.float64()),
            "size": pa.array(sizes, type=pa.float64()),
            "ts_event": pa.array(timestamps, type=pa.timestamp("us", tz="UTC")),
        }
    )


def _event_engine_table(n_events: int = 10_000) -> pa.Table:
    return pa.table(
        {
            "ts_event": pa.array(
                [_BASE + timedelta(seconds=index) for index in range(n_events)],
                type=pa.timestamp("us", tz="UTC"),
            ),
            "instrument_id": pa.array(["a"] * n_events, type=pa.string()),
            "price": pa.array(
                [0.5 + ((index % 10) / 1000.0) for index in range(n_events)],
                type=pa.float64(),
            ),
        }
    )


def _report_inputs(n_trades: int = 1_000) -> tuple[pd.DataFrame, pd.DataFrame]:
    trades_df = pd.DataFrame(
        {
            "ts_event": [_BASE + timedelta(minutes=index) for index in range(n_trades)],
            "instrument_id": [f"m{index % 20}" for index in range(n_trades)],
            "direction": ["long"] * n_trades,
            "price": [0.5] * n_trades,
            "size": [1.0] * n_trades,
            "realized_pnl": [1.0 if index % 2 == 0 else -0.5 for index in range(n_trades)],
        }
    )
    equity_df = pd.DataFrame(
        {
            "ts_event": [_BASE + timedelta(minutes=index) for index in range(n_trades + 1)],
            "equity": [10_000.0 + (index * 0.1) for index in range(n_trades + 1)],
        }
    )
    return trades_df, equity_df


class _MockDataset:
    def __init__(self, table: pa.Table) -> None:
        self._table = table

    def trades(self) -> pa.Table:
        return self._table


class _PerfEventStrategy(Strategy):
    name = "perf_event"

    def __init__(self) -> None:
        self._submitted = False

    def on_init(self, universe: list[str]) -> None:
        del universe

    def on_data(self, ts: datetime, state: StrategyState) -> list[BacktestOrderIntent]:
        del ts, state
        if self._submitted:
            return []
        self._submitted = True
        return [
            BacktestOrderIntent(
                instrument_id="a",
                side=Side.LONG,
                size=Decimal("5"),
                order_type="market",
            )
        ]

    def on_resolution(self, instrument_id: str, resolved_price: Decimal) -> None:
        del instrument_id, resolved_price


class _PerfVecStrategy(VecStrategy):
    name = "perf_vec"

    def generate_signals(
        self,
        features: pd.DataFrame,
        universe: list[str],
    ) -> pd.DataFrame:
        del features
        return pd.DataFrame({"instrument_id": universe, "signal": [1.0] * len(universe)})

    def size_positions(
        self,
        signals: pd.DataFrame,
        portfolio_value: Decimal,
        max_positions: int,
    ) -> pd.DataFrame:
        return EqualWeightSizer().size(signals, portfolio_value, max_positions)


class _SweepStrategy(VecStrategy):
    def __init__(self, params: dict[str, float]) -> None:
        self._threshold = params.get("threshold", 0.0)

    @property
    def name(self) -> str:
        return "perf_sweep"

    def generate_signals(
        self,
        features: pd.DataFrame,
        universe: list[str],
    ) -> pd.DataFrame:
        del features
        return pd.DataFrame({"instrument_id": universe, "signal": [1.0] * len(universe)})

    def size_positions(
        self,
        signals: pd.DataFrame,
        portfolio_value: Decimal,
        max_positions: int,
    ) -> pd.DataFrame:
        del portfolio_value, max_positions
        weights = np.linspace(1.0, 0.25, num=len(signals), dtype=float)
        return pd.DataFrame(
            {
                "instrument_id": signals["instrument_id"].tolist(),
                "target_weight": weights / weights.sum(),
            }
        )


class _DummyFeature(feature_base.Feature):
    def __init__(self, name: str, dependencies: list[str] | None = None) -> None:
        self._name = name
        self._dependencies = dependencies or []

    @property
    def name(self) -> str:
        return self._name

    @property
    def params(self) -> dict[str, object]:
        return {}

    @property
    def dependencies(self) -> list[str]:
        return self._dependencies

    def compute(
        self,
        data: pa.Table,
        *,
        instrument_id: str | None = None,
    ) -> feature_base.FeatureResult:
        del instrument_id
        return feature_base.FeatureResult(
            name=self._name,
            values=np.zeros(data.num_rows, dtype=float),
            params={},
        )


def test_dataset_builder_meets_section6_10k_event_budget(tmp_path: Path) -> None:
    reader = MagicMock(spec=reader_mod.ParquetEventReader)
    reader.read_trades.return_value = _dataset_build_trade_table()
    reader.read_ohlcv.return_value = pa.table({})
    reader.read_books.return_value = pa.table({})

    quality_validator = MagicMock(spec=pv_mod.PartitionValidator)
    gap_detector = MagicMock(spec=gap_mod.GapDetector)
    gap_detector.detect_trade_gaps.return_value = []
    gap_detector.detect_book_gaps.return_value = []
    gap_detector.detect_ohlcv_gaps.return_value = []

    master = master_mod.MarketMaster()
    master.register_market(_make_market("p", "m1"))
    builder = dataset_builder_mod.DatasetBuilder(
        reader=reader,
        universe_mgr=universe_mod.UniverseManager(master),
        quality_validator=quality_validator,
        gap_detector=gap_detector,
        storage_root=tmp_path,
    )
    config = dataset_mod.DatasetConfig(
        name="perf_dataset_build",
        start=_BASE,
        end=_BASE + timedelta(days=1),
        event_types=["trades"],
        require_quality_pass=False,
        require_gap_free=False,
    )

    started = time.perf_counter()
    manifest = builder.build(config)
    elapsed = time.perf_counter() - started

    assert manifest.row_counts["trades"] == 10_000
    assert elapsed < _DATASET_BUILD_TARGET_SECONDS


def test_universe_snapshot_meets_section6_1k_market_budget() -> None:
    master = master_mod.MarketMaster()
    for market_index in range(1_000):
        master.register_market(_make_market("p", f"m{market_index}"))

    manager = universe_mod.UniverseManager(master)

    started = time.perf_counter()
    snapshot = manager.snapshot_at(_BASE)
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    assert len(snapshot.markets) == 1_000
    assert elapsed_ms < _UNIVERSE_SNAPSHOT_TARGET_MS


def test_feature_compute_meets_section6_8_feature_budget() -> None:
    registry = FeatureRegistry()
    for feature in [
        primitives.RollingMean(window=20),
        primitives.RollingStd(window=20),
        primitives.ZScore(window=20),
        primitives.Return(periods=1),
        pm_features.ImpliedProbMomentum(window=20),
        pm_features.CrossVenueSpread(),
        pm_features.VolumeWeightedProb(window=20),
        pm_features.ProbAcceleration(fast=5, slow=20),
    ]:
        registry.register(feature)

    trades = _cross_sectional_table()

    started = time.perf_counter()
    enriched = registry.compute_all(trades)
    elapsed = time.perf_counter() - started

    assert enriched.num_rows == 10_000
    assert elapsed < _FEATURE_COMPUTE_TARGET_SECONDS


def test_feature_registry_toposort_meets_section6_budget() -> None:
    registry = FeatureRegistry()
    registry.register(_DummyFeature("f0"))
    for feature_index in range(1, 50):
        registry.register(_DummyFeature(f"f{feature_index}", [f"f{feature_index - 1}"]))

    started = time.perf_counter()
    order = registry.dependency_order()
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    assert len(order) == 50
    assert elapsed_ms < _TOPOLOGICAL_SORT_TARGET_MS


def test_event_engine_meets_section6_10k_event_budget() -> None:
    engine = EventBacktestEngine(
        EventBacktestConfig(
            dataset_id="perf_event",
            initial_cash=Decimal("1000"),
            slippage_model="fixed",
            slippage_params={"bps": 0},
        )
    )

    started = time.perf_counter()
    result = engine.run(_PerfEventStrategy(), _MockDataset(_event_engine_table()))
    elapsed = time.perf_counter() - started

    assert result.event_count == 10_000
    assert len(result.trades) == 1
    assert elapsed < _EVENT_ENGINE_TARGET_SECONDS


def test_vec_engine_meets_section6_cross_sectional_budget() -> None:
    """Use a 10K-row, 50-instrument cross-sectional matrix."""
    engine = VecBacktestEngine(
        VecBacktestConfig(
            dataset_id="perf_vec",
            initial_cash=Decimal("1000"),
            rebalance_frequency="1min",
        )
    )

    started = time.perf_counter()
    result = engine.run(_PerfVecStrategy(), _MockDataset(_cross_sectional_table()))
    elapsed = time.perf_counter() - started

    assert result.event_count == 10_000
    assert len(result.trades) > 0
    assert elapsed < _VEC_ENGINE_TARGET_SECONDS


def test_parameter_sweep_meets_section6_20_combo_budget() -> None:
    engine = VecBacktestEngine(
        VecBacktestConfig(
            dataset_id="perf_sweep",
            initial_cash=Decimal("1000"),
            rebalance_frequency="1min",
        )
    )
    runner = ParameterSweepRunner(engine=engine, evaluator=SweepEvaluator())
    grid = ParameterGrid({"threshold": [float(index) / 10.0 for index in range(20)]})

    started = time.perf_counter()
    result = runner.run(
        lambda params: _SweepStrategy(params),
        grid,
        dataset=_MockDataset(_cross_sectional_table()),
    )
    elapsed = time.perf_counter() - started

    assert len(result.trials) == 20
    assert elapsed < _PARAMETER_SWEEP_TARGET_SECONDS


def test_report_generation_meets_section6_1k_trade_budget(tmp_path: Path) -> None:
    trades_df, equity_df = _report_inputs()
    report = BacktestEvaluator().evaluate(
        backtest_id="perf_backtest",
        strategy_name="perf_strategy",
        trades_df=trades_df,
        equity_df=equity_df,
        starting_cash=10_000.0,
    )
    ReportWriter(tmp_path).write(report, "evaluate_run_perf")

    manifest = evaluate_runner_mod.EvaluateManifest(
        run_id="evaluate_run_perf",
        backtest_run_id="backtest_run_perf",
        metrics_profile="pm_core",
        built_at=_BASE,
        metrics={"trade_count": 1_000.0, "sharpe_ratio": 1.0},
        artifacts={},
    )
    manifest_path = (
        tmp_path / "runs" / "evaluate_run_perf" / "stage_outputs" / "evaluate_manifest.json"
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    started = time.perf_counter()
    payload = _build_report(tmp_path, "evaluate_run_perf")
    elapsed = time.perf_counter() - started

    assert payload["evaluation_run_id"] == "evaluate_run_perf"
    assert elapsed < _REPORT_GENERATION_TARGET_SECONDS
