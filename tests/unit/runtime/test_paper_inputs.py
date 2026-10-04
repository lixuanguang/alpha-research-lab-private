"""Exercise how declared candidate inputs map to provisioned paper feeds."""

from __future__ import annotations

# third party library imports
import pytest

# project library imports
from research.observations import InputRequirement, NumericField
from runtime import PaperInputs


class TestPaperInputs:
    """Partition book and trade fields and refuse families no paper feed serves."""

    @staticmethod
    def _input(name: str, family: str, clock: str, field: str, units: str) -> InputRequirement:
        """Declare one named source field with a fixed age."""
        return InputRequirement(
            name=name,
            family="book" if family == "book" else "trade" if family == "trade" else "non-book",
            clock="receipt" if clock == "receipt" else "event" if clock == "event" else "valid",
            field=NumericField(name=field, units=units),
            max_age_us=1_000_000,
        )

    def test_book_and_trade_fields_keep_their_declared_order_per_feed(self) -> None:
        """Each feed receives its own fields in declaration order."""
        ask = self._input("book", "book", "receipt", "ask", "quote/base")
        flow = self._input("trades", "trade", "event", "signed_flow", "BTC")
        bid = self._input("book", "book", "receipt", "bid", "quote/base")
        feeds = PaperInputs((ask, flow, bid), has_trades=True)
        assert (feeds.book, feeds.trades) == ((ask, bid), (flow,))

    def test_unprovisioned_trades_and_non_book_inputs_are_refused(self) -> None:
        """Trades need the source's trades feed; non-book inputs need the feature store."""
        flow = self._input("trades", "trade", "event", "signed_flow", "BTC")
        with pytest.raises(ValueError, match="no provisioned feed: trades"):
            PaperInputs((flow,), has_trades=False)
        funding = self._input("funding", "non-book", "valid", "rate", "dimensionless")
        with pytest.raises(ValueError, match="no provisioned feed: funding"):
            PaperInputs((funding,), has_trades=True)
