"""Expose pure lifecycle callbacks without giving a strategy account authority."""

from __future__ import annotations

# standard library imports
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

# project library imports
from financial_units import Money, Quantity
from serialization import WireRecord


class StrategyEvent(WireRecord, frozen=True):
    """Describe one observed runtime transition using UTC availability and exact balances.

    Market lineage names the received input; order status is an observation, never
    permission to trade. Optional balances are committed account observations.
    The supervisor owns delivery order and durable event deduplication.
    """

    identity: str
    kind: Literal["start", "stop", "timer", "market", "account", "order", "recovery", "fault"]
    at: datetime
    reason: str
    cash: Money | None = None
    holding: Quantity | None = None
    order_id: str | None = None
    order_status: str | None = None
    source_identity: str | None = None

    def __post_init__(self) -> None:
        """Reject malformed clocks, incomplete order facts and mutable account values."""
        self._require_utc(self.at, field_name="event availability")
        if self.kind not in (
            "start",
            "stop",
            "timer",
            "market",
            "account",
            "order",
            "recovery",
            "fault",
        ):
            raise ValueError("unsupported strategy lifecycle event")
        if not self.identity or not self.reason:
            raise ValueError("lifecycle event requires identity and reason")
        if (self.cash is None) != (self.holding is None):
            raise ValueError("account observation requires cash and holding together")
        if self.cash is not None:
            self.cash.model_copy()
        if self.holding is not None:
            self.holding.model_copy()
        if (self.order_id is None) != (self.order_status is None):
            raise ValueError("order observation requires identity and status together")
        if self.kind == "order" and (not self.order_id or not self.order_status):
            raise ValueError("order callback requires an observed order")
        if self.kind == "market" and not self.source_identity:
            raise ValueError("market callback requires input lineage")


@runtime_checkable
class DecisionLifecycle(Protocol):
    """Optionally extend a decision policy with pure, checkpointed lifecycle state.

    Implementations return successor bytes understood by their existing
    ``validate_state`` and ``decide`` methods. They must not retain hidden state
    or perform I/O: a failed transaction can replay the callback. The same
    protocol applies to replay, paper and shadow.
    """

    def on_event(self, event: StrategyEvent, state: bytes) -> bytes:
        """Return a validated successor without mutating the supplied event or state."""
        ...
