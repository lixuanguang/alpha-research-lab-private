"""Typed Alphalens Reloaded 0.4.3 quantile adapter surface."""

# third party library imports
import pandas as pd

def quantize_factor(
    factor_data: pd.DataFrame,
    quantiles: int = ...,
    bins: None = ...,
    by_group: bool = ...,
    no_raise: bool = ...,
    zero_aware: bool = ...,
) -> pd.Series:
    """Assign factor quantiles without deriving forward returns.

    Args:
        factor_data: Alphalens factor/forward-return frame.
        quantiles: Number of equal-frequency buckets.
        bins: Optional value-width bucket configuration.
        by_group: Whether to bucket separately by group.
        no_raise: Whether tied edges become missing assignments.
        zero_aware: Whether to split positive and negative factors.

    Returns:
        Quantile series indexed by date and asset.
    """
    ...
