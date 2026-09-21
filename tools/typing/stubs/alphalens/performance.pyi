"""Typed Alphalens Reloaded 0.4.3 performance functions used by research adapters."""

# third party library imports
import pandas as pd

def factor_information_coefficient(
    factor_data: pd.DataFrame,
    group_adjust: bool = ...,
    by_group: bool = ...,
) -> pd.DataFrame:
    """Compute date-level rank information coefficients.

    Args:
        factor_data: Alphalens factor/forward-return frame.
        group_adjust: Whether to demean by group.
        by_group: Whether to return group-level metrics.

    Returns:
        Date-level information-coefficient frame.
    """
    ...

def mean_return_by_quantile(
    factor_data: pd.DataFrame,
    by_date: bool = ...,
    by_group: bool = ...,
    demeaned: bool = ...,
    group_adjust: bool = ...,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute mean and standard-error returns by factor quantile.

    Args:
        factor_data: Alphalens factor/forward-return frame.
        by_date: Whether to retain date-level output.
        by_group: Whether to return group-level metrics.
        demeaned: Whether to demean forward returns.
        group_adjust: Whether to demean by group.

    Returns:
        Mean-return frame and standard-error frame.
    """
    ...

def quantile_turnover(
    quantile_factor: pd.Series,
    quantile: int,
    period: int = ...,
) -> pd.Series:
    """Compute the share of names entering one factor quantile.

    Args:
        quantile_factor: Quantile series indexed by date and asset.
        quantile: Quantile whose turnover is measured.
        period: Number of periods between memberships.

    Returns:
        Turnover series indexed by the retained decision date.
    """
    ...
