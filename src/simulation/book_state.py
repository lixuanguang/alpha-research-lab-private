"""Retain complete offline L2 order, decision, liquidity and accounting restart state."""

from __future__ import annotations

# standard library imports
import hashlib
import re
from datetime import datetime
from decimal import Decimal
from fractions import Fraction

# project library imports
from accounting import Fill, LedgerBalance, LedgerMark, LedgerState
from financial_units import Money, Quantity
from market_data.contracts import BookObservation
from serialization import DomainCodec, WireRecord


class BookOrder(WireRecord, frozen=True):
    """Retain one signed IOC request and its level fills; canceled size is unsigned."""

    identity: str
    decision_at: datetime
    sent_at: datetime
    arrival_at: datetime
    response_at: datetime
    requested: Quantity
    reserved_cash: Money
    source_position: int
    status: str = "pending"
    fills: tuple[Fill, ...] = ()
    canceled: Quantity | None = None
    reason: str = "awaiting_arrival"

    def __post_init__(self) -> None:
        """Reject invalid timing, quantity, costs and inconsistent IOC outcomes."""
        for at in (self.decision_at, self.sent_at, self.arrival_at, self.response_at):
            self._require_utc(at, field_name="order clock")
        if (
            not self.identity
            or not self.decision_at <= self.sent_at < self.arrival_at <= self.response_at
            or type(self.requested) is not Quantity
            or self.requested.value == 0
            or type(self.reserved_cash) is not Money
            or self.reserved_cash.value < 0
            or type(self.source_position) is not int
            or self.source_position < 0
            or self.status not in ("pending", "filled", "partial", "canceled")
            or type(self.fills) is not tuple
            or not self.reason
        ):
            raise ValueError("invalid IOC order")
        self.requested.model_copy()
        self.reserved_cash.model_copy()
        filled = Quantity(value=Decimal(0), dimension=self.requested.dimension)
        for fill in self.fills:
            if type(fill) is not Fill:
                raise TypeError("IOC requires exact fills")
            fill.__post_init__()
            if (
                fill.decision_at != self.decision_at
                or fill.filled_at != self.arrival_at
                or (fill.quantity.value > 0) != (self.requested.value > 0)
            ):
                raise ValueError("IOC fill timing or side differs")
            filled = filled + fill.quantity
        if self.status == "pending":
            if self.fills or self.canceled is not None:
                raise ValueError("pending IOC already has an outcome")
        elif (
            self.canceled is None
            or self.canceled.dimension != self.requested.dimension
            or (
                self.canceled.value < 0
                or abs(Fraction(filled.value)) + Fraction(self.canceled.value)
                != abs(Fraction(self.requested.value))
            )
        ):
            raise ValueError("IOC filled and canceled size does not reconcile")
        if self.status != "pending" and self.canceled is not None:
            expected = (
                "filled" if self.canceled.value == 0 else "partial" if self.fills else "canceled"
            )
            if self.status != expected:
                raise ValueError("IOC status differs from filled/canceled quantities")


class BookDecision(WireRecord, frozen=True):
    """Identify exactly which delayed book and acknowledged holding a decision observed."""

    at: datetime
    source_position: int | None
    delivered_at: datetime | None
    known_holding: Quantity
    target: Quantity | None
    reason: str

    def __post_init__(self) -> None:
        """Require causal delivered clocks and exact positions."""
        self._require_utc(self.at, field_name="decision")
        if self.delivered_at is not None:
            self._require_utc(self.delivered_at, field_name="delivery")
            if self.delivered_at > self.at:
                raise ValueError("decision observed a future delivery")
        if type(self.known_holding) is not Quantity or not self.reason:
            raise ValueError("invalid book decision")
        self.known_holding.model_copy()
        if self.target is not None:
            self.target.model_copy()


class BookValuation(WireRecord, frozen=True):
    """Record cash, positions and exact marked NAV, preserving unavailable marks."""

    at: datetime
    balance: LedgerBalance
    mark: LedgerMark | None
    reason: str

    def __post_init__(self) -> None:
        """Reject untyped accounting or unknown valuation clocks."""
        self._require_utc(self.at, field_name="valuation")
        if type(self.balance) is not LedgerBalance or not self.reason:
            raise ValueError("invalid book valuation")
        self.balance.__post_init__()
        if self.mark is not None:
            self.mark.__post_init__()


class ConsumedLevel(WireRecord, frozen=True):
    """Retain simulated depletion at a native price until that level disappears."""

    side: str
    price: Decimal
    size: Decimal

    def __post_init__(self) -> None:
        """Reject invalid sides and nonpositive exact price or consumption."""
        if self.side not in ("bid", "ask") or any(
            type(value) is not Decimal or not value.is_finite() or value <= 0
            for value in (self.price, self.size)
        ):
            raise ValueError("invalid consumed book level")


class BookState(WireRecord, frozen=True):
    """Retain both information sets, pending delivery/order state and all exact postings."""

    clock: datetime
    input_count: int
    input_digest: str
    exchange: BookObservation | None
    local: BookObservation | None
    deliveries: tuple[BookObservation, ...]
    consumed: tuple[ConsumedLevel, ...]
    next_decision: datetime
    pending: int | None
    known_holding: Quantity
    ledger: LedgerState
    orders: tuple[BookOrder, ...]
    decisions: tuple[BookDecision, ...]
    valuations: tuple[BookValuation, ...]

    def __post_init__(self) -> None:
        """Validate restart coordinates and immutable native/economic records."""
        self._require_utc(self.clock, field_name="checkpoint")
        self._require_utc(self.next_decision, field_name="next decision")
        if (
            type(self.input_count) is not int
            or self.input_count < 0
            or not re.fullmatch(r"[a-f0-9]{64}", self.input_digest)
            or self.next_decision <= self.clock
            or type(self.ledger) is not LedgerState
            or type(self.known_holding) is not Quantity
        ):
            raise ValueError("invalid book restart coordinates")
        self.ledger.__post_init__()
        self.known_holding.model_copy()
        for row in (self.exchange, self.local):
            if row is not None:
                row.__post_init__()
                if row.position >= self.input_count:
                    raise ValueError("checkpoint book beyond source cursor")
        for values in (
            self.deliveries,
            self.consumed,
            self.orders,
            self.decisions,
            self.valuations,
        ):
            if type(values) is not tuple:
                raise TypeError("book state requires immutable collections")
            for value in values:
                value.__post_init__()
        if self.pending is not None and (
            type(self.pending) is not int or not 0 <= self.pending < len(self.orders)
        ):
            raise ValueError("invalid pending IOC cursor")
        if len({(item.side, item.price) for item in self.consumed}) != len(self.consumed):
            raise ValueError("duplicate consumed level")
        if (
            self.known_holding.dimension != self.ledger.dimension
            or self.known_holding.value < 0
            or len({order.identity for order in self.orders}) != len(self.orders)
            or any(
                order.status == "pending" and index != self.pending
                for index, order in enumerate(self.orders)
            )
        ):
            raise ValueError("inconsistent book account or pending-order state")
        if self.pending is not None:
            pending_order = self.orders[self.pending]
            next_event = (
                pending_order.arrival_at
                if pending_order.status == "pending"
                else pending_order.response_at
            )
            if next_event <= self.clock:
                raise ValueError("pending order event already passed checkpoint clock")
        if tuple(fill for order in self.orders for fill in order.fills) != self.ledger.fills:
            raise ValueError("order fills differ from ledger postings")


class BookCheckpoint(WireRecord, frozen=True):
    """Bind a complete state to source/config/code identity with an accidental-corruption digest."""

    identity: str
    state: BookState
    state_sha256: str
    schema_version: str = "l2-ioc-checkpoint-v1"

    def __post_init__(self) -> None:
        """Reject incompatible schemas, identities and changed serialized state."""
        if (
            self.schema_version != "l2-ioc-checkpoint-v1"
            or not re.fullmatch(r"[a-f0-9]{64}", self.identity)
            or type(self.state) is not BookState
        ):
            raise ValueError("unsupported book checkpoint")
        self.state.__post_init__()
        if hashlib.sha256(DomainCodec().encode_json(self.state)).hexdigest() != self.state_sha256:
            raise ValueError("book checkpoint state digest mismatch")

    @classmethod
    def create(cls, identity: str, state: BookState) -> BookCheckpoint:
        """Capture a complete deterministic event boundary.

        Args:
            identity: Bound source, configuration and implementation fingerprint.
            state: Complete simulator state after all phases at one clock.

        Returns:
            Versioned checkpoint with a digest covering every retained field.
        """
        return cls(
            identity=identity,
            state=state,
            state_sha256=hashlib.sha256(DomainCodec().encode_json(state)).hexdigest(),
        )
