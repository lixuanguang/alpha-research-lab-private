"""Typed, venue-neutral facts and transport boundaries for spot execution."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime
from decimal import Decimal
from fractions import Fraction
from typing import Literal, Protocol

# third party library imports
import msgspec

# project library imports
from configuration import CapabilityProfile

type VenueSide = Literal["buy", "sell"]
type VenueTimeInForce = Literal["gtc", "ioc"]
type VenueOrderStatus = Literal["open", "partial", "filled", "cancelled", "rejected"]
type VenueStreamKind = Literal[
    "authenticated", "orders_snapshot", "order", "fill", "balance", "heartbeat", "recovery_required"
]


class VenueProtocolError(ValueError):
    """Report malformed, unsupported, or incomplete venue evidence."""


class VenueOutcomeUnknownError(RuntimeError):
    """Require reconciliation before retrying a possibly accepted command."""


class VenueRejectedError(RuntimeError):
    """Report a definite venue rejection without echoing secrets or account data."""


class VenueCredentials(msgspec.Struct, frozen=True):
    """Hold caller-resolved credentials; never include them in recorded facts."""

    api_key: str
    api_secret: str
    passphrase: str | None = None

    def __post_init__(self) -> None:
        """Reject empty credential material."""
        if not self.api_key or not self.api_secret:
            raise ValueError("venue credentials require key and secret")

    def __repr__(self) -> str:
        """Prevent routine diagnostic rendering from exposing key material."""
        return "VenueCredentials(<redacted>)"


class VenueOrderRequest(msgspec.Struct, frozen=True):
    """Describe one already admitted physical spot order in native venue units."""

    client_id: str
    symbol: str
    side: VenueSide
    quantity: Decimal
    limit_price: Decimal
    time_in_force: VenueTimeInForce = "gtc"
    post_only: bool = False

    def __post_init__(self) -> None:
        """Forbid unsafe amounts and conflicting execution instructions."""
        if (
            not self.client_id
            or not self.symbol
            or self.side not in ("buy", "sell")
            or self.time_in_force not in ("gtc", "ioc")
            or not self.quantity.is_finite()
            or not self.limit_price.is_finite()
            or self.quantity <= 0
            or self.limit_price <= 0
            or (self.post_only and self.time_in_force == "ioc")
        ):
            raise ValueError("invalid venue spot order request")


class VenueCommandAck(msgspec.Struct, frozen=True):
    """Retain request acknowledgement separately from final order state."""

    operation: Literal["submit", "cancel"]
    client_id: str
    venue_order_id: str | None
    received_at: datetime
    raw: bytes

    def __post_init__(self) -> None:
        """Require a traceable request and UTC receipt."""
        if self.operation not in ("submit", "cancel") or not self.client_id:
            raise ValueError("invalid venue command acknowledgement")
        if self.received_at.tzinfo is None or self.received_at.utcoffset() != UTC.utcoffset(None):
            raise ValueError("venue command receipt must be UTC")


class VenueOrderFact(msgspec.Struct, frozen=True):
    """Retain venue-observed cumulative state without inventing finality."""

    client_id: str
    venue_order_id: str
    symbol: str
    side: VenueSide
    original_quantity: Decimal
    filled_quantity: Decimal
    remaining_quantity: Decimal
    limit_price: Decimal
    time_in_force: VenueTimeInForce
    post_only: bool
    status: VenueOrderStatus
    source_at: datetime | None
    received_at: datetime
    raw: bytes

    def __post_init__(self) -> None:
        """Keep exact spot quantity conservation and identifiable source facts."""
        if (
            not self.client_id
            or not self.venue_order_id
            or not self.symbol
            or self.side not in ("buy", "sell")
            or self.status not in ("open", "partial", "filled", "cancelled", "rejected")
            or any(
                not value.is_finite()
                for value in (
                    self.original_quantity,
                    self.filled_quantity,
                    self.remaining_quantity,
                    self.limit_price,
                )
            )
            or self.original_quantity <= 0
            or self.filled_quantity < 0
            or self.remaining_quantity < 0
            or Fraction(self.filled_quantity) + Fraction(self.remaining_quantity)
            != Fraction(self.original_quantity)
            or self.limit_price <= 0
        ):
            raise ValueError("invalid venue order fact")
        if self.received_at.tzinfo is None or self.received_at.utcoffset() != UTC.utcoffset(None):
            raise ValueError("venue order receipt must be UTC")
        if self.source_at is not None and (
            self.source_at.tzinfo is None or self.source_at.utcoffset() != UTC.utcoffset(None)
        ):
            raise ValueError("venue order source time must be UTC")


class VenueFillFact(msgspec.Struct, frozen=True):
    """Retain an individual execution and signed fee in its native currency.

    Positive fee is cost; negative fee is a rebate. Conversion into the local
    account's quote currency is a separate qualified boundary.
    """

    fill_id: str
    client_id: str
    venue_order_id: str
    symbol: str
    side: VenueSide
    quantity: Decimal
    price: Decimal
    fee: Decimal
    fee_currency: str
    source_at: datetime | None
    received_at: datetime
    raw: bytes

    def __post_init__(self) -> None:
        """Reject unidentifiable or non-finite execution economics."""
        if (
            not self.fill_id
            or not self.client_id
            or not self.venue_order_id
            or not self.symbol
            or not self.fee_currency
            or self.side not in ("buy", "sell")
            or any(not value.is_finite() for value in (self.quantity, self.price, self.fee))
            or self.quantity <= 0
            or self.price <= 0
        ):
            raise ValueError("invalid venue fill fact")
        if self.received_at.tzinfo is None or self.received_at.utcoffset() != UTC.utcoffset(None):
            raise ValueError("venue fill receipt must be UTC")
        if self.source_at is not None and (
            self.source_at.tzinfo is None or self.source_at.utcoffset() != UTC.utcoffset(None)
        ):
            raise ValueError("venue fill source time must be UTC")


class VenueBalance(msgspec.Struct, frozen=True):
    """Retain one observed physical currency balance and its availability."""

    currency: str
    total: Decimal
    available: Decimal
    received_at: datetime
    raw: bytes

    def __post_init__(self) -> None:
        """Keep signed balances exact and the receipt clock explicit."""
        if not self.currency or not self.total.is_finite() or not self.available.is_finite():
            raise ValueError("invalid venue balance")
        if self.received_at.tzinfo is None or self.received_at.utcoffset() != UTC.utcoffset(None):
            raise ValueError("venue balance receipt must be UTC")


class VenueFillPage(msgspec.Struct, frozen=True):
    """Expose bounded history and refuse to call a truncated window complete.

    A continuation may repeat executions at its page boundary; callers apply
    each fill identity once and refuse a repeat with different economics.
    """

    fills: tuple[VenueFillFact, ...]
    next_cursor: str | None
    complete: bool


class VenueCapabilityProfile(msgspec.Struct, frozen=True):
    """Declare the supported native spot surface and observed account mode."""

    venue: Literal["okx", "bitfinex"]
    environment: Literal["okx_demo", "bitfinex_paper"]
    account_identity: str
    account_verified: bool
    supported_order_types: tuple[VenueTimeInForce, ...] = ("gtc", "ioc")
    supports_post_only: bool = True

    def __post_init__(self) -> None:
        """Require a physical identity before allocating firm account ownership."""
        if not self.account_identity or not self.account_identity.isascii():
            raise ValueError("venue capability requires physical account identity")


class VenueStreamEvent(msgspec.Struct, frozen=True):
    """Carry one private-stream fact or an explicit recovery signal."""

    kind: VenueStreamKind
    received_at: datetime
    raw: bytes
    orders: tuple[VenueOrderFact, ...] = ()
    fill: VenueFillFact | None = None
    balances: tuple[VenueBalance, ...] = ()
    reason: str | None = None


class VenueHttpRequest(msgspec.Struct, frozen=True):
    """Represent one exact signed REST request to a fixed venue host."""

    method: Literal["GET", "POST"]
    path: str
    headers: tuple[tuple[str, str], ...]
    body: bytes = b""

    def __repr__(self) -> str:
        """Keep signed headers out of ordinary transport diagnostics."""
        return f"VenueHttpRequest(method={self.method!r}, path={self.path!r}, headers=<redacted>)"


class VenueHttpResponse(msgspec.Struct, frozen=True):
    """Retain bounded response bytes and local receipt time."""

    status: int
    body: bytes
    received_at: datetime


class VenueHttpTransport(Protocol):
    """Allow fixture transport and the real TLS transport to share one boundary."""

    def request(self, request: VenueHttpRequest) -> VenueHttpResponse:
        """Execute exactly one request without hidden retries."""


class VenueAdapter(Protocol):
    """Expose the same physical spot operations to the durable gateway."""

    @property
    def capability_profiles(self) -> tuple[CapabilityProfile, ...]:
        """Declare fixture-qualified registry support without external claims."""

    def submit(self, order: VenueOrderRequest, *, at: datetime, nonce: int) -> VenueCommandAck:
        """Send once; uncertain outcome raises VenueOutcomeUnknownError."""

    def cancel(
        self,
        symbol: str,
        client_id: str,
        *,
        submitted_at: datetime,
        venue_order_id: str | None,
        at: datetime,
        nonce: int,
    ) -> VenueCommandAck:
        """Request cancellation without claiming confirmed cancellation."""

    def order(
        self,
        symbol: str,
        client_id: str,
        *,
        submitted_at: datetime,
        venue_order_id: str | None,
        at: datetime,
        nonce: int,
    ) -> VenueOrderFact | None:
        """Look up one durable client identity across open and recent closed state."""

    def open_orders(self, *, at: datetime, nonce: int) -> tuple[VenueOrderFact, ...]:
        """Read the complete account-wide spot open-order set or fail closed."""

    def fills(
        self,
        *,
        symbol: str,
        start_ms: int,
        end_ms: int,
        limit: int,
        cursor: str | None,
        at: datetime,
        nonce: int,
    ) -> VenueFillPage:
        """Read one bounded history page with an explicit, possibly overlapping continuation."""

    def balances(self, *, at: datetime, nonce: int) -> tuple[VenueBalance, ...]:
        """Read account physical balances without inferring strategy ownership."""

    def qualify_account(self, *, at: datetime, nonce: int) -> VenueCapabilityProfile:
        """Verify the configured non-live account surface before command use."""

    def private_login(self, *, at: datetime, nonce: int) -> bytes:
        """Build an authenticated private WebSocket login frame."""

    def private_configuration(self) -> tuple[bytes, ...]:
        """Build protocol configuration frames sent before login."""

    def private_subscriptions(self) -> tuple[bytes, ...]:
        """Build the authenticated private channel subscriptions."""

    def decode_private(self, raw: bytes, *, received_at: datetime) -> VenueStreamEvent:
        """Decode one private frame or require recovery on loss/ambiguity."""
