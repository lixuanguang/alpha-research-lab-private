"""Define exact public trade observations and injected public-source boundaries."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

# project library imports
from configuration import DataCapability, PublicDataJob
from financial_units import DecimalGrid
from market_data.contracts.raw import RawObject, RequestBinding
from reference_data.catalogs import InstrumentDefinition, VenueSpecification
from serialization import DomainCodec, WireRecord


class PublicTrade(WireRecord, frozen=True, kw_only=True):
    """Preserve one venue trade ID, millisecond source time and exact native spot units."""

    trade_id: str
    event_ms: int
    price: Decimal
    quantity: Decimal
    side: Literal["buy", "sell"]

    def __post_init__(self) -> None:
        """Reject invalid source identity, clock, side or financial values."""
        if (
            type(self.trade_id) is not str
            or not self.trade_id.isascii()
            or not self.trade_id.isdigit()
        ):
            raise ValueError("public trade requires a numeric native trade ID")
        if (
            len(self.trade_id) > 40
            or type(self.event_ms) is not int
            or not 0 < self.event_ms < 253402300800000
        ):
            raise ValueError("invalid public trade identity or millisecond timestamp")
        for value in (self.price, self.quantity):
            DecimalGrid.require_decimal(value)
            if value <= 0:
                raise ValueError("trade price and quantity must be positive")
        if self.side not in ("buy", "sell"):
            raise ValueError("invalid aggressor side")


class PublicRequest(WireRecord, frozen=True, kw_only=True):
    """Bind each original response to the job, installed adapter, listing and cursor."""

    job_identity: str
    implementation_identity: str
    instrument: InstrumentDefinition
    kind: Literal["reference", "trades"]
    cursor: str | None
    ordinal: int

    def __post_init__(self) -> None:
        """Require complete immutable request identities and nonnegative pagination position."""
        RequestBinding(self.job_identity)
        RequestBinding(self.implementation_identity)
        if type(self.instrument) is not InstrumentDefinition:
            raise ValueError("public request requires instrument definition")
        self.instrument.__post_init__()
        if (
            self.kind not in ("reference", "trades")
            or type(self.ordinal) is not int
            or self.ordinal < 0
        ):
            raise ValueError("invalid public request kind or ordinal")
        if self.cursor is not None and (
            type(self.cursor) is not str
            or not self.cursor.isascii()
            or not self.cursor.isdigit()
            or len(self.cursor) > 40
        ):
            raise ValueError("invalid public pagination cursor")
        if self.kind == "reference" and (self.cursor is not None or self.ordinal != 0):
            raise ValueError("reference request has no trade cursor")

    @property
    def binding(self) -> RequestBinding:
        """Return the neutral binding used by the existing raw-byte store."""
        self.__post_init__()
        return RequestBinding(hashlib.sha256(DomainCodec().encode_json(self)).hexdigest())


class PublicReceipt(WireRecord, frozen=True, kw_only=True):
    """Retain one durably saved response's request and original local receipt clocks."""

    request: PublicRequest
    raw: RawObject

    def __post_init__(self) -> None:
        """Reject response metadata bound to another request."""
        if type(self.request) is not PublicRequest or type(self.raw) is not RawObject:
            raise ValueError("invalid public receipt")
        self.request.__post_init__()
        self.raw.__post_init__()
        if self.raw.request_identity != self.request.binding.identity:
            raise ValueError("public receipt request mismatch")


class TradePage(WireRecord, frozen=True, kw_only=True):
    """Return native-order rows and a checked continuation; exhaustion is not completeness."""

    trades: tuple[PublicTrade, ...]
    next_cursor: str | None

    def __post_init__(self) -> None:
        """Require validated trade rows and a bounded numeric continuation."""
        if type(self.trades) is not tuple:
            raise ValueError("trade page requires immutable rows")
        for trade in self.trades:
            if type(trade) is not PublicTrade:
                raise ValueError("invalid public trade row")
            trade.__post_init__()
        if self.next_cursor is not None and (
            type(self.next_cursor) is not str
            or not self.next_cursor.isascii()
            or not self.next_cursor.isdigit()
            or len(self.next_cursor) > 40
        ):
            raise ValueError("invalid next trade cursor")


class PublicSource(Protocol):
    """Supply admitted source-specific parsing, pagination and current reference semantics."""

    @property
    def capability(self) -> DataCapability:
        """Declare the actual installed adapter contract."""
        ...

    def endpoint(self, job: PublicDataJob, request: PublicRequest) -> tuple[str, str]:
        """Return the fixed official HTTPS host and escaped path for an admitted request."""
        ...

    def trades(self, job: PublicDataJob, request: PublicRequest, payload: bytes) -> TradePage:
        """Validate source rows and continuation without inventing historical knowledge."""
        ...

    def reference(
        self, instrument: InstrumentDefinition, payload: bytes, received: datetime
    ) -> VenueSpecification:
        """Decode current observed specifications, leaving unavailable fields unknown."""
        ...


class PublicSources(Protocol):
    """Resolve reviewed implementations without coupling neutral readers to venue modules."""

    def public(self, instrument: InstrumentDefinition) -> PublicSource:
        """Return an implemented compatible source or reject the product before work."""
        ...


class PublicTransport(Protocol):
    """Own a bounded public read-only request; no authenticated or order endpoints exist."""

    def get(self, host: str, path: str) -> bytes:
        """Fetch a bounded exact response, raising on timeout, HTTP or encoding errors."""
        ...
