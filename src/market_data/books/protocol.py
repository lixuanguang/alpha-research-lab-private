"""Define the native book capability used by common receipt reconstruction."""

# standard library imports
from decimal import Decimal
from typing import Protocol

# project library imports
from market_data.contracts import Level, Order


class NativeBook(Protocol):
    """Apply native frames and expose exact bounded state at whole-message boundaries."""

    ready: bool
    sequence: int | None
    source_time: str | None
    orders: dict[str, Order]
    bids: dict[Decimal, Level]
    asks: dict[Decimal, Level]

    @property
    def identity(self) -> str:
        """Return the exact state fingerprint.

        Returns:
            Deterministic SHA-256 state identity.
        """
        ...

    @property
    def source_ns(self) -> int | None:
        """Return the original source clock in Unix nanoseconds.

        Returns:
            Exact source instant, or None when absent.
        """
        ...

    def apply(self, raw: bytes, *, snapshot: bool = False) -> str:
        """Apply one native frame without exposing partial mutations as valid state.

        Args:
            raw: Complete original native message.
            snapshot: Whether the message is an independently received snapshot.

        Returns:
            Native boundary classification.
        """
        ...

    def counts(self, max_orders: int) -> dict[str, object]:
        """Report native representation and depth limits.

        Args:
            max_orders: Selected visible-state ceiling.

        Returns:
            Non-secret native representation counters.
        """
        ...
