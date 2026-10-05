"""Partition candidates' declared inputs by the paper feed that serves them."""

from __future__ import annotations

# project library imports
from research.observations import InputRequirement


class PaperInputs:
    """Resolve each declared source input to a provisioned paper feed, or refuse it.

    Book fields come from the source's native book and trade fields from its public
    trades feed, when the source records one. Reference and non-book inputs reach
    paper candidates only through the feature store, so a source-fed candidate that
    declares one is refused here, before any process starts.
    """

    def __init__(self, inputs: tuple[InputRequirement, ...], *, has_trades: bool) -> None:
        """Partition ordered distinct inputs, refusing any family with no provisioned feed.

        Raises:
            ValueError: An input's family has no feed in this source.
        """
        book: list[InputRequirement] = []
        trades: list[InputRequirement] = []
        for item in inputs:
            item.__post_init__()
            if item.family == "book":
                book.append(item)
            elif item.family == "trade" and has_trades:
                trades.append(item)
            else:
                raise ValueError(f"paper input has no provisioned feed: {item.name}")
        self.book, self.trades = tuple(book), tuple(trades)
