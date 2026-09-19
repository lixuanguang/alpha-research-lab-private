"""Exact vendor JSON boundaries and bounded visible-order state."""

from __future__ import annotations

# standard library imports
import hashlib
from decimal import Decimal

# project library imports
from market_data.contracts import Level, Order
from serialization import DomainCodec


class VisibleBook:
    """Own bounded resting orders and an order-independent state fingerprint."""

    def __init__(self, max_orders: int) -> None:
        """Bind the fail-closed order budget for this reconstruction epoch.

        Args:
            max_orders: Maximum visible orders before reconstruction fails closed.

        Raises:
            ValueError: The source schema, identity, continuity or resource contract is invalid.
        """
        if max_orders < 1:
            raise ValueError("max_orders must be positive")
        self.max_orders = max_orders
        self.orders: dict[str, Order] = {}
        self.bids: dict[Decimal, Level] = {}
        self.asks: dict[Decimal, Level] = {}
        self.ready = False
        self.sequence: int | None = None
        self._fingerprint = 0
        self._codec = DomainCodec()

    def set(self, order: Order) -> None:
        """Replace a visible order while updating the state fingerprint exactly.

        Args:
            order: Validated resting order replacing this native ID.

        Raises:
            ValueError: The source schema, identity, continuity or resource contract is invalid.
        """
        order.__post_init__()
        if order.order_id not in self.orders and len(self.orders) >= self.max_orders:
            raise ValueError("order state exceeds configured budget")
        self.remove(order.order_id)
        self.orders[order.order_id] = order
        self._fingerprint ^= int.from_bytes(hashlib.sha256(self._codec.encode_json(order)).digest())

    def remove(self, order_id: str) -> None:
        """Remove a visible order; deletion outside the visible window is harmless.

        Args:
            order_id: Native order ID whose visible entry is removed.
        """
        previous = self.orders.pop(order_id, None)
        if previous is not None:
            self._fingerprint ^= int.from_bytes(
                hashlib.sha256(self._codec.encode_json(previous)).digest()
            )

    @property
    def identity(self) -> str:
        """Identify current message-boundary state without implying order priority.

        Returns:
            Stable SHA-256 of the current bound identity or visible state.
        """
        return hashlib.sha256(
            self._codec.encode_json(
                (self._fingerprint, len(self.orders), self.sequence, self.ready)
            )
        ).hexdigest()

    def counts(self, max_orders: int) -> dict[str, object]:
        """Report visible orders under the selected source budget.

        Args:
            max_orders: Configured maximum visible order count.

        Returns:
            Retained order count and its explicit ceiling.
        """
        return {"orders": len(self.orders), "max_orders": max_orders}
