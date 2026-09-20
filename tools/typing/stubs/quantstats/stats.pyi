"""Describe the consumed QuantStats 0.0.81 series statistics."""

# third party library imports
from pandas import Series

def comp(returns: Series) -> float:
    """Compound complete simple returns.

    Args:
        returns: Complete return series.

    Returns:
        Total simple return.
    """
    ...

def max_drawdown(prices: Series) -> float:
    """Compute signed peak-to-trough loss.

    Args:
        prices: Positive wealth with initial NAV anchor.

    Returns:
        Most negative observed drawdown.
    """
    ...
