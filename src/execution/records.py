"""Describe portable paper order decisions, lifecycle state, and journal evidence."""

from __future__ import annotations

# standard library imports
from datetime import datetime
from typing import Literal

# project library imports
from accounting import Fill, LedgerBalance
from financial_units import Money, Price, Quantity
from serialization import WireRecord
from strategies import DecisionIntent, OrderIntent

type OrderStatus = Literal[
    "intent",
    "request_ack",
    "accepted",
    "partial",
    "cancel_requested",
    "cancel_ack",
    "unknown",
    "filled",
    "cancelled",
    "rejected",
]
type EventKind = Literal[
    "request_ack",
    "accepted",
    "fill",
    "cancel_requested",
    "cancel_ack",
    "cancelled",
    "rejected",
    "unknown",
    "reconcile_open",
    "reconcile_cancelled",
    "reconcile_rejected",
]


class OrderDecision(WireRecord, frozen=True):
    """Carry one pure strategy intent without importing research policy machinery."""

    identity: str
    at: datetime
    intent: DecisionIntent

    def __post_init__(self) -> None:
        """Require stable lineage, a UTC decision clock and a supported intent."""
        self._require_utc(self.at, field_name="order decision")
        if type(self.identity) is not str or not self.identity:
            raise ValueError("order decision requires an identity")
        self.intent.__post_init__()


class OrderState(WireRecord, frozen=True):
    """Retain one child order and its exact unfilled account commitment."""

    identity: str
    decision_identity: str
    decision_at: datetime
    intent: OrderIntent
    status: OrderStatus
    filled: Quantity
    paid_fee: Money
    maximum_fee: Money
    request_acknowledged: bool = False
    accepted: bool = False
    cancel_requested: bool = False
    cancel_acknowledged: bool = False
    replace_of: str | None = None

    def __post_init__(self) -> None:
        """Require coherent exact quantities, fees and distinct lifecycle facts."""
        self._require_utc(self.decision_at, field_name="order decision")
        self.intent.__post_init__()
        self.filled.model_copy()
        self.paid_fee.model_copy()
        self.maximum_fee.model_copy()
        if (
            not self.identity
            or not self.decision_identity
            or self.status
            not in (
                "intent",
                "request_ack",
                "accepted",
                "partial",
                "cancel_requested",
                "cancel_ack",
                "unknown",
                "filled",
                "cancelled",
                "rejected",
            )
            or self.filled.dimension != self.intent.quantity.dimension
            or self.filled.value < 0
            or self.filled.value > self.intent.quantity.value
            or self.paid_fee.currency != self.intent.limit.currency
            or self.maximum_fee.currency != self.intent.limit.currency
            or self.paid_fee.value < 0
            or self.maximum_fee.value < self.paid_fee.value
            or (self.status == "filled") != (self.filled.value == self.intent.quantity.value)
            or (self.status == "partial" and self.filled.value == 0)
            or (self.status == "request_ack" and not self.request_acknowledged)
            or (self.status == "accepted" and not self.accepted)
            or (self.status in ("cancel_requested", "cancel_ack") and not self.cancel_requested)
            or (self.status == "cancel_ack" and not self.cancel_acknowledged)
        ):
            raise ValueError("inconsistent paper order state")
        if self.replace_of is not None and not self.replace_of:
            raise ValueError("invalid replacement order lineage")

    @property
    def remaining(self) -> Quantity:
        """Return exact unresolved base quantity, including unknown outcomes."""
        return self.intent.quantity - self.filled

    @property
    def is_terminal(self) -> bool:
        """Report only confirmed economic completion or terminal cancellation/rejection."""
        return self.status in ("filled", "cancelled", "rejected")


class OrderEvent(WireRecord, frozen=True):
    """Identify one paper lifecycle fact independently of transport retry."""

    identity: str
    order_id: str
    at: datetime
    kind: EventKind
    fill: Fill | None = None

    def __post_init__(self) -> None:
        """Require an identified UTC event and fill data only for fill events."""
        self._require_utc(self.at, field_name="order event")
        if (
            type(self.identity) is not str
            or not self.identity
            or type(self.order_id) is not str
            or not self.order_id
            or self.kind
            not in (
                "request_ack",
                "accepted",
                "fill",
                "cancel_requested",
                "cancel_ack",
                "cancelled",
                "rejected",
                "unknown",
                "reconcile_open",
                "reconcile_cancelled",
                "reconcile_rejected",
            )
            or (self.kind == "fill") != (self.fill is not None)
        ):
            raise ValueError("invalid order event")
        if self.fill is not None:
            self.fill.__post_init__()


class JournalEvent(WireRecord, frozen=True):
    """Pair a monotonic durable event sequence with its resulting order state."""

    sequence: int
    event: OrderEvent
    order: OrderState
    balance: LedgerBalance

    def __post_init__(self) -> None:
        """Keep callback replay tied to a positive persisted sequence."""
        if type(self.sequence) is not int or self.sequence <= 0:
            raise ValueError("invalid journal event sequence")
        self.event.__post_init__()
        self.order.__post_init__()
        self.balance.__post_init__()
        if self.event.order_id != self.order.identity:
            raise ValueError("journal event references another order")


class StepCommit(WireRecord, frozen=True):
    """State whether one candidate step admitted orders or a visible rejection."""

    status: Literal["committed", "rejected"]
    reason: str
    orders: tuple[OrderState, ...]

    def __post_init__(self) -> None:
        """Reject an accepted-but-unaccounted result."""
        if self.status not in ("committed", "rejected") or not self.reason:
            raise ValueError("invalid paper step result")
        if self.status == "rejected" and self.orders:
            raise ValueError("rejected step cannot admit orders")
        for order in self.orders:
            order.__post_init__()


class StepRecord(WireRecord, frozen=True):
    """Retain exact candidate continuation and source/result bytes with admission."""

    step_id: str
    checkpoint: bytes
    input_bytes: bytes
    result_bytes: bytes
    decision: OrderDecision | None
    reference: Price | None
    maximum_fee: Money
    commit: StepCommit

    def __post_init__(self) -> None:
        """Require immutable bytes and validated decision economics."""
        if not self.step_id or any(
            type(value) is not bytes
            for value in (self.checkpoint, self.input_bytes, self.result_bytes)
        ):
            raise ValueError("invalid durable candidate step")
        if self.decision is not None:
            self.decision.__post_init__()
        if self.reference is not None:
            self.reference.model_copy()
        self.maximum_fee.model_copy()
        self.commit.__post_init__()


class AccountReservations(WireRecord, frozen=True):
    """Expose conservative pending buy cash and sell inventory commitments."""

    cash: Money
    buy_quantity: Quantity
    sell_quantity: Quantity

    def __post_init__(self) -> None:
        """Retain exact positive amounts and one instrument/currency definition."""
        self.cash.model_copy()
        self.buy_quantity.model_copy()
        self.sell_quantity.model_copy()
        if (
            self.cash.value < 0
            or self.buy_quantity.value < 0
            or self.sell_quantity.value < 0
            or self.buy_quantity.dimension != self.sell_quantity.dimension
        ):
            raise ValueError("invalid paper reservations")
