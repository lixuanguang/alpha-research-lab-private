"""lab.backtest — daily backtesting engine and walk-forward splits."""

from lab.backtest.daily_engine import BacktestResult, run_daily_backtest
from lab.backtest.leakage_checks import assert_no_lookahead, assert_splits_time_ordered
from lab.backtest.rebalance import rebalance_dates
from lab.backtest.splits import (
    expanding_splits,
    purged_kfold,
    rolling_splits,
    single_split,
)

__all__ = [
    "BacktestResult",
    "assert_no_lookahead",
    "assert_splits_time_ordered",
    "expanding_splits",
    "purged_kfold",
    "rebalance_dates",
    "rolling_splits",
    "run_daily_backtest",
    "single_split",
]
