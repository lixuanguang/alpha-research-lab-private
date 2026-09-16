"""Exact vendor JSON boundaries and bounded visible-order state."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import cast

# third party library imports
import msgspec

# project library imports
from alpha_research.serialization import DomainCodec


class Wire:
    """Decode JSON numbers exactly and validate only explicitly understood fields."""

    _decoder: msgspec.json.Decoder[object] = msgspec.json.Decoder(object, float_hook=Decimal)

    @classmethod
    def decode(cls, raw: bytes) -> object:
        """Parse vendor bytes without passing decimal tokens through binary floats.

        Args:
            raw: Original received JSON bytes, before any numeric conversion.

        Returns:
            JSON value with decimal tokens parsed directly to Decimal.
        """
        return cls._decoder.decode(raw)

    @staticmethod
    def mapping(value: object) -> dict[str, object]:
        """Require a JSON object at the current protocol boundary.

        Args:
            value: Untrusted decoded source value at this field boundary.

        Returns:
            Validated source object without coercion.

        Raises:
            ValueError: The source schema, identity, continuity or resource contract is invalid.
        """
        if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
            raise ValueError("expected JSON object")
        return cast(dict[str, object], value)

    @staticmethod
    def array(value: object) -> list[object]:
        """Require a JSON array at the current protocol boundary.

        Args:
            value: Untrusted decoded source value at this field boundary.

        Returns:
            Validated source array without coercion.

        Raises:
            ValueError: The source schema, identity, continuity or resource contract is invalid.
        """
        if not isinstance(value, list):
            raise ValueError("expected JSON array")
        return cast(list[object], value)

    @staticmethod
    def text(value: object) -> str:
        """Require nonempty source text without coercing unknown identities.

        Args:
            value: Untrusted decoded source value at this field boundary.

        Returns:
            Original nonempty source text.

        Raises:
            ValueError: The source schema, identity, continuity or resource contract is invalid.
        """
        if not isinstance(value, str) or not value:
            raise ValueError("expected source text")
        return value

    @staticmethod
    def integer(value: object) -> int:
        """Read nonnegative source sequence/order IDs, including Coinbase numeric text.

        Args:
            value: Untrusted decoded source value at this field boundary.

        Returns:
            Exact nonnegative integer from the source.

        Raises:
            ValueError: The source schema, identity, continuity or resource contract is invalid.
        """
        if type(value) is int and value >= 0:
            return value
        if isinstance(value, str) and value.isascii() and value.isdigit():
            return int(value)
        raise ValueError("expected nonnegative integer")

    @staticmethod
    def decimal(value: object) -> Decimal:
        """Require a finite exact number; floats and booleans are never admitted.

        Args:
            value: Untrusted decoded source value at this field boundary.

        Returns:
            Finite Decimal within the supported precision and magnitude limits.

        Raises:
            ValueError: The source schema, identity, continuity or resource contract is invalid.
        """
        if not isinstance(value, (str, Decimal, int)) or isinstance(value, bool):
            raise ValueError("expected exact decimal")
        try:
            result = Decimal(value)
        except InvalidOperation:
            raise ValueError("invalid decimal") from None
        if (
            not result.is_finite()
            or len(result.as_tuple().digits) > 40
            or abs(result.adjusted()) > 30
        ):
            raise ValueError("nonfinite decimal")
        return result

    @staticmethod
    def source_time(value: object) -> str | None:
        """Validate supplied UTC source text while retaining its original fractional precision.

        Args:
            value: Untrusted decoded source value at this field boundary.

        Returns:
            Original UTC timestamp text, or None when the source omitted it.

        Raises:
            ValueError: The source schema, identity, continuity or resource contract is invalid.
        """
        if value is None:
            return None
        text = Wire.text(value)
        timestamp = datetime.fromisoformat(text)
        if timestamp.utcoffset() != timedelta(0):
            raise ValueError("source timestamp must be UTC")
        return text


class Order(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """A visible resting order; no queue rank or simulated fill is inferred."""

    order_id: str
    side: str
    price: Decimal
    size: Decimal

    def __post_init__(self) -> None:
        """Reject invalid order identities, sides and nonpositive exact values."""
        if not self.order_id or self.side not in ("buy", "sell"):
            raise ValueError("invalid order identity or side")
        for value in (self.price, self.size):
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise ValueError("orders require positive exact price and size")


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
