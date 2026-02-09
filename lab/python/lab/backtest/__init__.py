"""lab.backtest — daily backtesting engine and walk-forward splits."""

from lab.backtest.daily_engine import BacktestResult, run_daily_backtest
from lab.backtest.splits import (
    expanding_splits,
    purged_kfold,
    rolling_splits,
    single_split,
)

__all__ = [
    "BacktestResult",
    "expanding_splits",
    "purged_kfold",
    "rolling_splits",
    "run_daily_backtest",
    "single_split",
]
